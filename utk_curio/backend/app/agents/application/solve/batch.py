"""The Solve batch: one session over a graph, as an object (memo dev/142, B3; re-derived on enh/agent-catalog).

This is the body of the former ``_solve_events`` closure (dev/63 → dev/118 →
dev/131 → dev/134), with its shared state on the instance and its nested
functions as methods. Nothing about WHAT the batch does changed: passes until
stop or budget, waves in topological order, one persist per wave, honest
reasons, one idempotent finish. What changed is that each stage has a name
and a signature — :meth:`events` is the stream, :meth:`_run_passes` the
session, :meth:`_run_pass` one pass, :meth:`_drain_wave` one wave's worker
outcomes, :meth:`record_outcome` the fold, :meth:`finish` the single persist
— so a reader (or a test) can reach one stage without holding the whole loop.

Workers report through a thread-safe queue and never touch the response;
the generator drains it between yields. :meth:`finish` is reached from
normal completion, cancellation, client disconnect (``GeneratorExit``) and
unexpected errors alike.

Session-level helpers (waves, blocker signatures, the deadline check, the
waiting summary, the progress-event table) stay in :mod:`session` and are
called through that module so a test patches them in one place.
"""

from __future__ import annotations

import logging
import queue as _queue
import time
from concurrent.futures import ThreadPoolExecutor

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import failure_text
from utk_curio.backend.app.agents.domain.counts import count_label
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.domain import upstream_schema as agents_upstream_schema
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.packages import service as _pkg_services
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


class SolveBatch:
    """One Solve session over *targets* of *spec*; :meth:`events` streams it."""

    # ── construction ────────────────────────────────────────────────────────

    def __init__(
        self,
        user_key: str,
        project_id: str,
        attachment_id: str,
        config: ProviderConfig,
        targets: list[str],
        nodes_by_id: dict,
        manifest: AgentManifest | None,
        coord: str,
        session_id,
        solve_execution_id: str,
        stop,
        *,
        spec: dict | None = None,
        mode: str = "write",
        return_phase: str | None = None,
        verify: bool = True,
        grounding_base: dict | None = None,
        dataset_paths: dict | None = None,
        retry_of: str | None = None,
        catalog_rows: list | None = None,
        acting_user=None,
    ):
        self.user_key = user_key
        self.project_id = project_id
        self.attachment_id = attachment_id
        self.config = config
        self.targets = targets
        self.nodes_by_id = nodes_by_id
        self.manifest = manifest
        self.coord = coord
        self.session_id = session_id
        self.solve_execution_id = solve_execution_id
        self.stop = stop
        self.spec = spec
        self.mode = mode
        self.return_phase = return_phase
        self.verify = verify
        self.retry_of = retry_of
        self.catalog_rows = catalog_rows
        self.acting_user = acting_user

        self.results: dict[str, dict] = {}
        # dev/131 (owner correction): consecutive passes in which a node's every
        # failed attempt was a REPEAT — the builder handed back the code that
        # already failed. Retrying that is not persistence, it is a spin, so a
        # node is dropped from later passes once it stalls this way.
        self.weak_passes: dict[str, int] = {}
        self.applied_contents: list[dict] = []
        # dev/127: one bounded artifact preview per artifact per batch, turned into
        # the columns and dtypes its frame holds (memo dev/127 §1 D5).
        self.schema_cache: dict[str, dict | None] = {}
        self.delegations: list = []
        self.unstarted: list[str] = []
        self.started = time.monotonic()
        self.finished = False
        self.payload_out: dict = {}
        # dev/106: a batch-level reason (the missing-specialist case) and the
        # proposal parts minted for it — the Solve turn carries them.
        self.batch_reason: str | None = None
        self.extra_parts: list[dict] = []
        # dev/118 (DEC-075): waves. The spec the loop and the context composer see
        # is re-read after every wave's persist, so a downstream target executes
        # against the upstream content that actually ran.
        self.current: dict = {"spec": spec, "wave": 0}
        self.wave_outputs: dict[str, dict] = {}
        self.persisted: set[str] = set()
        # dev/118: the batch's time budget (§3.6) — a bound, never a failure.
        self.deadline_s = agents_budgets.solve_batch_deadline_s()
        # dev/131: the session's own budget — the owner's fifteen minutes. The
        # batch ceiling above stays the outer guard.
        self.session_deadline_s = agents_budgets.solve_session_deadline_s()
        self.session_wait_s = agents_budgets.solve_session_wait_s()
        self.deadline_reason = (
            f"the batch's time budget ({max(1, self.deadline_s // 60)} min) was spent; "
            "Retry continues from here"
        )
        # dev/114: ONE grounding base per batch (catalog paths, mission + plan
        # texts), built in the request thread — workers hold no request context;
        # ONE egress budget for the batch's probes. dev/115: the request thread
        # resolved these; computing them here is only the fallback for a direct caller.
        self.solve_ground = (
            grounding_base if grounding_base is not None
            else agents_grounding._solve_grounding_base(user_key, project_id, spec, nodes_by_id, targets)
        )
        self.solve_ctx: dict = {"granted": [], "manifest": manifest}
        self.solve_dataset_paths = (
            dataset_paths if dataset_paths is not None
            else (agents_grounding._resolve_catalog_execution_paths(
                project_id, list(self.solve_ground.get("catalog_ids") or {}))
                  if verify else {})
        )
        self.batch_templates = agents_roster._roster_templates(user_key, project_id)  # dev/119: ONE snapshot per batch
        # dev/131: session bookkeeping lives ABOVE the resolution branch, because
        # every exit — including "no specialist installed" — must still report how
        # the session ended.
        self.ended_by = "complete"
        self.pass_no = 0
        # The passes that actually ran, which the done payload reports.
        # ``pass_no`` numbers the loop's turns instead: it is bumped before the
        # stop, budget and nothing-left checks, and on a turn that only waits,
        # so it ran one ahead of the passes made whenever the session ended.
        self.passes_run = 0
        self.attempted_signature: dict[str, tuple] = {}
        self.resolution = None
        self.goals: list[str] = []
        self.outcome_queue: _queue.Queue = _queue.Queue()

    # ── small predicates and lookups ────────────────────────────────────────

    def schema_of_artifact(self, artifact_id: str) -> dict | None:
        if artifact_id in self.schema_cache:
            return self.schema_cache[artifact_id]
        from utk_curio.backend.app.execution import runner as _runner

        summary = None
        try:
            preview = _runner.load_artifact_preview(artifact_id)
            summary = agents_upstream_schema.summarize(preview) if preview else None
        except Exception:  # noqa: BLE001
            log.warning("Could not describe artifact %s", artifact_id, exc_info=True)
        self.schema_cache[artifact_id] = summary
        return summary

    def _flag_requested(self) -> bool:
        # The durable cancel signal, read lazily at node boundaries only.
        try:
            flag_spec = agents_spec_reads._read_spec_or_404(self.user_key, self.project_id)
            flag_record = agents_spec_reads._record_or_404(flag_spec, self.attachment_id)
            return bool((flag_record.get("builderSession") or {}).get("cancelRequested"))
        except Exception:
            return False

    def should_stop(self) -> bool:
        if self.stop.is_set():
            return True
        if self._flag_requested():
            self.stop.set()
            return True
        return False

    def _session_time_left(self) -> int:
        return max(int(self.session_deadline_s - (time.monotonic() - self.started)), 0)

    def _session_deadline_passed(self) -> bool:
        return (time.monotonic() - self.started) >= self.session_deadline_s

    def _batch_deadline_spent(self) -> bool:
        return agents_session._batch_deadline_spent(self.started, self.deadline_s)

    @staticmethod
    def is_data_loading(node_obj: dict) -> bool:
        return source_grounding.is_data_loading_type(
            _pkg_services.canonical_template_id((node_obj or {}).get("type"))
        )

    def is_executable(self, node_obj: dict) -> bool:  # dev/118 (DEC-075) → dev/119 (DEC-076)
        return agents_roster._node_is_executable(node_obj, self.batch_templates)

    def content_kind(self, node_obj: dict) -> str:  # dev/134
        return workflow_spec.content_kind(
            str((node_obj or {}).get("type") or ""), self.batch_templates
        )

    def _ungrounded_error(self, refusal: str, node_id: str) -> str:
        return (
            "ungrounded source: " + refusal.split("Allowed sources:")[0]
            .replace("source grounding refused — ", "").strip()
        )[:220] + agents_grounding._ungrounded_remedy(
            agents_rounds._dataset_finder_attachment_id(self.spec, node_id))

    # ── the fold: one worker outcome into the batch state ───────────────────

    def record_outcome(self, node_id: str, status: str, text, child) -> dict | None:
        # dev/131: a later pass must not ERASE an earlier pass's evidence. A
        # node that is still awaiting the user produces a fresh result with no
        # attempts (nothing was tried this pass), and overwriting the trail of
        # the pass that DID try left the user with a bare "pending". So the
        # record is merged: a result carrying attempts always wins; one without
        # them keeps the earlier trail and updates only the reason.
        previous = dict(self.results.get(node_id) or {})
        if previous.get("status") in ("solved", "proposed") and status != "verified":
            # dev/131: a session NEVER un-solves a node. A later pass exists to
            # pick up work that became possible, not to downgrade a node whose
            # content already landed (a slice bound or a cancellation arriving
            # after the fact must not rewrite "solved" into "skipped").
            return None
        event = self._record_outcome_inner(node_id, status, text, child)
        fresh = self.results.get(node_id)
        if isinstance(fresh, dict):
            self._merge_trail(node_id, fresh, previous, event)
        return event

    def _merge_trail(self, node_id: str, fresh: dict, previous: dict, event) -> None:
        if fresh.get("attempts") and previous.get("attempts"):
            # dev/131 (owner correction): a session keeps attempting, and the
            # owner asked for ALL attempts to be visible — so a later pass
            # APPENDS its rounds to the trail instead of replacing it. And a
            # pass that only repeated itself must not bury the concrete error
            # the earlier pass found: the sentence stays the concrete one.
            this_pass_was_weak = agents_rounds._weak_failure(fresh)
            if fresh.get("status") == "failed" and this_pass_was_weak:
                self.weak_passes[node_id] = self.weak_passes.get(node_id, 0) + 1
            else:
                self.weak_passes.pop(node_id, None)
            fresh["attempts"] = (
                list(previous["attempts"]) + list(fresh["attempts"])
            )[-agents_budgets._MAX_TRAIL_ATTEMPTS:]
            if (
                fresh.get("status") == "failed"
                and previous.get("status") == "failed"
                and previous.get("error")
                and this_pass_was_weak
                and not agents_rounds._weak_failure(previous)
            ):
                fresh["error"] = previous["error"]
            if isinstance(event, dict):
                event["attempts"] = fresh["attempts"]
                if fresh.get("error"):
                    event["error"] = fresh["error"]
        if not fresh.get("attempts") and previous.get("attempts"):
            # An emptied field counts as absent, not as an answer: the awaiting
            # path records ``attempts: []`` and ``rounds: 0``, which used to
            # win over a real trail purely because they are not None.
            for key in ("attempts", "rounds", "verdict", "stoppedBy"):
                if previous.get(key) is not None and not fresh.get(key):
                    fresh[key] = previous[key]
            if isinstance(event, dict) and not event.get("attempts"):
                for key in ("attempts", "rounds", "verdict", "stoppedBy"):
                    if fresh.get(key) is not None:
                        event[key] = fresh[key]

    def _record_outcome_inner(self, node_id: str, status: str, text, child) -> dict | None:
        """Fold one worker outcome into the batch state — no yields, so it is
        safe on the disconnect drain. Returns the node_result payload, or
        None for an unstarted (cancelled-before-dispatch) target, which stays
        ``pending`` — it was never attempted, so no new status enters the
        state machine."""
        if status == "no-content":
            return self._record_no_content(node_id)
        if status == "deadline":
            return self._record_deadline(node_id)
        if child is not None:
            self.delegations.append(child)
        if status == "verified":
            return self._record_verified(node_id, text)
        if status == "solved":
            return self._record_solved(node_id, text)
        if status == "failed":
            err = (text or "")[:300]
            self.results[node_id] = {"status": "failed", "error": err}
            return {"nodeId": node_id, "status": "failed", "error": err}
        if status == "skipped":
            self.results[node_id] = {"status": "skipped"}
            return {"nodeId": node_id, "status": "skipped"}
        self.unstarted.append(node_id)
        return None

    def _record_no_content(self, node_id: str) -> dict:
        # dev/134: nothing is owed and nothing was spent. Not "skipped"
        # (that means a bound refused it) and not "pending" (that means
        # work remains): the node is resolved, and the reason says why
        # there was never anything to write.
        node = self.nodes_by_id.get(node_id) or {}
        reason = (
            f"{node.get('type')} is wired, not written: this kind has no "
            "content to author; it renders or forwards its input"
        )
        result = {"status": "solved",
                  "verification": {"status": "no-content", "reason": reason[:300]}}
        self.results[node_id] = result
        return {"nodeId": node_id, "status": "solved", **result}

    def _record_deadline(self, node_id: str) -> dict:
        # dev/118: the budget ran out before this node was dispatched — it
        # stays pending, says why, and the batch names the reason once.
        self.results[node_id] = {"status": "pending", "reason": self.deadline_reason}
        if node_id not in self.unstarted:
            self.unstarted.append(node_id)
        self.batch_reason = self.batch_reason or self.deadline_reason
        return {"nodeId": node_id, "status": "pending", "reason": self.deadline_reason}

    def _record_verified(self, node_id: str, outcome: dict) -> dict:
        # dev/115 (DEC-073): the verified-content loop's outcome. Only
        # code that PASSED is written; exhaustion is failed with the
        # trail; a sandbox outage is pending with the reason — never a
        # content failure, never silently written.
        for c in outcome.get("delegations") or []:
            if c is not None:
                self.delegations.append(c)
        trail = {
            "verdict": outcome.get("verdict"),
            "rounds": outcome.get("rounds"),
            "attempts": outcome.get("attempts") or [],
            # dev/127: which bound ended the loop, all the way to the UI.
            "stoppedBy": outcome.get("stoppedBy"),
        }
        if outcome.get("verdict") == "pass":
            return self._verified_pass(node_id, outcome, trail)
        evidence = outcome.get("evidence") or {}
        if outcome.get("verdict") == "not-executable" and (outcome.get("candidate") or "").strip():
            return self._verified_not_executable(node_id, outcome, evidence, trail)
        if outcome.get("verdict") == "infrastructure":
            reason = (
                "not verified (sandbox unreachable): "
                + str(evidence.get("detail") or "")[:160]
                + "; nothing was run or written; Retry when the sandbox is back"
            )[:300]
            self.results[node_id] = {"status": "pending", "reason": reason, **trail}
            return {"nodeId": node_id, "status": "pending", "error": reason, **trail}
        if outcome.get("verdict") == "awaiting-source":
            # dev/126: the node's source is with the USER now — the Dataset
            # Finder on this node proposed candidates (or said it found
            # none). Nothing was generated or written, so this is PENDING
            # with the reason, never a failure of content.
            reason = (
                "awaiting your dataset selection: "
                + str(evidence.get("detail") or "")[:240]
            )[:300]
            remedy = evidence.get("remedy") if isinstance(evidence.get("remedy"), dict) else None
            extra = {"remedy": remedy} if remedy else {}
            self.results[node_id] = {"status": "pending", "reason": reason, **trail, **extra}
            return {"nodeId": node_id, "status": "pending", "reason": reason,
                    **trail, **extra}
        return self._verified_failure(node_id, outcome, evidence, trail)

    def _verified_pass(self, node_id: str, outcome: dict, trail: dict) -> dict:
        candidate = outcome.get("candidate") or ""
        self.results[node_id] = {"status": "solved", **trail}
        self.applied_contents.append({"nodeId": node_id, "content": candidate})
        self.wave_outputs[node_id] = {
            "nodeId": node_id,
            "goal": str((self.nodes_by_id.get(node_id) or {}).get("goal") or "")[:200],
            "outputDataType": (outcome.get("evidence") or {}).get("outputDataType") or "",
            "wave": self.current["wave"],
            # dev/118 commit 4: the artifact a dependent's validation reuses.
            "output": (outcome.get("evidence") or {}).get("output"),
        }
        return {"nodeId": node_id, "status": "solved", "content": candidate, **trail}

    def _verified_not_executable(self, node_id: str, outcome: dict, evidence: dict, trail: dict) -> dict:
        # dev/118 (DEC-075): a browser-rendered kind — SAID to be
        # unexecuted, never "verified". dev/129: and never written
        # unchecked — an authored document that nothing here can
        # validate stays OUT of the node.
        candidate = outcome.get("candidate") or ""
        if evidence.get("documentUnchecked") and not evidence.get("documentPassive"):
            reason = (
                "written nothing: " + str(evidence["documentUnchecked"])[:200]
                + "; Play the dataflow to see whether it renders"
            )[:300]
            self.results[node_id] = {"status": "pending", "reason": reason, **trail}
            return {"nodeId": node_id, "status": "pending", "reason": reason, **trail}
        verification = (
            {"status": "document-valid",
             "reason": f"{evidence['documentValidated']} document validated, not executed"}
            if evidence.get("documentValidated") else
            {"status": "not-executable", "reason": str(evidence.get("detail") or "")[:300]}
        )
        self.results[node_id] = {"status": "solved", "verification": verification, **trail}
        self.applied_contents.append({"nodeId": node_id, "content": candidate})
        return {"nodeId": node_id, "status": "solved", "content": candidate,
                "verification": verification, **trail}

    def _verified_failure(self, node_id: str, outcome: dict, evidence: dict, trail: dict) -> dict:
        kind = evidence.get("kind") or "fail"
        raw_detail = str(evidence.get("stderrTail") or evidence.get("detail") or "")
        if kind in agents_rounds._WEAK_CARRY_KINDS:
            # dev/131 (owner correction): the loop stopped because the
            # correction repeated itself — that is HOW it stopped, not WHAT
            # is wrong. The sentence names the error it is stuck on (the
            # last attempt that actually ran and failed); ``stoppedBy``
            # still says a repeat ended it.
            stronger = next(
                (
                    a for a in reversed(trail.get("attempts") or [])
                    if isinstance(a, dict)
                    and a.get("verdict") != "pass"
                    and str(a.get("kind") or "") not in agents_rounds._WEAK_CARRY_KINDS
                    and str(a.get("stderrTail") or a.get("detail") or "").strip()
                ),
                None,
            )
            if stronger is not None:
                kind = str(stronger.get("kind") or kind)
                raw_detail = str(
                    stronger.get("stderrTail") or stronger.get("detail") or raw_detail
                )
        if evidence.get("upstreamEmpty"):
            # dev/118 live fix: the upstream has no content (it failed, or
            # is not a target) — this node waits, pending with the reason;
            # Retry runs it once the upstream is solved or filled.
            reason = f"waiting: {raw_detail[:240]}" if raw_detail else "waiting: an upstream node has no content yet"
            # The session summary reads what the node waits on from here, not
            # from the reason's wording.
            self.results[node_id] = {"status": "pending", "reason": reason, "waitingOn": "upstream", **trail}
            return {"nodeId": node_id, "status": "pending", "reason": reason, **trail}
        if kind == "precondition":
            # dev/118 (DEC-075): the runner refused the SLICE (the 25-node
            # bound, a cycle) — a bound on validation, not a failure of the
            # content: skipped, with the bound named.
            reason = f"skipped: {raw_detail[:240]}" if raw_detail else "skipped: validation refused the slice"
            self.results[node_id] = {"status": "skipped", "reason": reason, **trail}
            return {"nodeId": node_id, "status": "skipped", "reason": reason, **trail}
        # dev/127: a refusal's head names the literal; a traceback is read
        # for its exception line and frame, never sliced by character count
        # (the report's "execution-error: das/core/generic.py" was the tail
        # of pandas/core/generic.py, cut mid-path).
        detail = (
            failure_text.excerpt(raw_detail, limit=200, head=True)
            if kind in agents_rounds._HEAD_FIRST_KINDS
            else failure_text.summary(
                raw_detail,
                code=agents_rounds._last_attempt_code(trail),
                limit=200,
            )
        )
        rounds = outcome.get("rounds") or 0
        remedy_payload = evidence.get("remedy") if isinstance(evidence.get("remedy"), dict) else None
        remedy = (
            agents_grounding._ungrounded_remedy(agents_rounds._dataset_finder_attachment_id(self.spec, node_id))
            if kind == "ungrounded-source" else
            agents_grounding._source_missing_remedy(remedy_payload)
            if kind == "source-missing" else ""
        )
        bound = agents_rounds._stopped_by_clause(outcome.get("stoppedBy"))
        err = (
            f"not fixed after {rounds} attempt{'s' if rounds != 1 else ''}{bound}: "
            f"{kind}: {detail[:200 - len(remedy)] if remedy else detail}{remedy}"
        )[:300]
        extra = {"remedy": remedy_payload} if remedy_payload else {}
        self.results[node_id] = {"status": "failed", "error": err, **trail, **extra}
        return {"nodeId": node_id, "status": "failed", "error": err, **trail, **extra}

    def _record_solved(self, node_id: str, text) -> dict:
        # The child replies with response formatting around the code —
        # only the executable content is written (dev/57).
        text_out = content.extract_node_content(text)
        # dev/114 (DEC-072): the gate — a fabricated path or an
        # unverified URL never reaches the spec; the node fails LOUDLY
        # with the literal and the remedy named.
        node = self.nodes_by_id.get(node_id) or {}
        _verdict, refusal = agents_grounding._gate_generated_content(
            self.user_key, self.project_id, self.solve_ctx,
            code=text_out, engine="python", node_type=node.get("type"),
            base=self.solve_ground,
        )
        if refusal:
            err = self._ungrounded_error(refusal, node_id)
            self.results[node_id] = {"status": "failed", "error": err[:300]}
            return {"nodeId": node_id, "status": "failed", "error": err[:300]}
        result: dict = {"status": "solved"}
        if not self.is_executable(node):
            # dev/118 (DEC-075): written like before, and SAID to be unexecuted.
            result["verification"] = {
                "status": "not-executable",
                "reason": f"{node.get('type')} has no code the sandbox could run; written, not executed",
            }
        self.results[node_id] = result
        self.applied_contents.append({"nodeId": node_id, "content": text_out})
        return {"nodeId": node_id, "status": "solved", "content": text_out, **(
            {"verification": result["verification"]} if "verification" in result else {}
        )}

    # ── persistence ─────────────────────────────────────────────────────────

    def apply_contents(self, spec_doc: dict) -> None:
        """Write every solved content not yet persisted into *spec_doc*,
        re-guarded against the CURRENT nodes (deleted → skipped; a user edit
        wins). Shared by the per-wave persist and the final one (dev/118)."""
        current_nodes = {
            n.get("id"): n
            for n in (spec_doc.get("dataflow") or {}).get("nodes") or []
            if isinstance(n, dict)
        }
        for item in self.applied_contents:
            if item["nodeId"] in self.persisted:
                continue
            self.persisted.add(item["nodeId"])
            node = current_nodes.get(item["nodeId"])
            if node is None:
                self.results[item["nodeId"]] = {"status": "skipped"}  # deleted meanwhile
                continue
            if (node.get("content") or "").strip():
                self.results[item["nodeId"]] = {"status": "skipped"}  # user edit wins
                continue
            node["content"] = item["content"]

    def persist_wave(self, wave_ids: list[str]) -> None:
        """dev/118 (DEC-075): the wave boundary IS the persist — and the
        heartbeat. Under the spec lock: the wave's solved contents land (the
        same guards as the final write), its nodeRuns say what happened, and
        ``solvingSince`` is refreshed so the stale marker means "no wave
        completed for 15 minutes". A process that dies between waves leaves
        every persisted wave in place (DEC-021: nothing replayed; Retry
        continues). The re-read spec is what the next wave runs against."""
        with projects_storage.spec_write_lock(self.user_key, self.project_id):
            spec_doc = agents_spec_reads._read_spec_or_404(self.user_key, self.project_id)
            record = agents_spec_reads._record_or_404(spec_doc, self.attachment_id)
            session = record.get("builderSession") or {}
            self.apply_contents(spec_doc)
            node_runs = session.get("nodeRuns") or {}
            for nid in wave_ids:
                outcome = self.results.get(nid)
                if outcome and nid in node_runs and outcome.get("status") in ("solved", "failed", "skipped"):
                    node_runs[nid] = outcome["status"]
            session["nodeRuns"] = node_runs
            if session.get("phase") == "solving":
                session["solvingSince"] = time.time()
            record["builderSession"] = session
            projects_storage.write_spec(self.user_key, self.project_id, spec_doc)
        self.current["spec"] = spec_doc

    def finish(self) -> dict:
        # One batched spec write: contents (re-guarded against the CURRENT
        # spec under the read-modify-write), statuses, and the exit phase —
        # plus the transcript card. Idempotent: exactly one persist per batch.
        # dev/118: the LAST wave's persist — earlier waves already landed.
        if self.finished:
            return self.payload_out
        self.finished = True
        cancelled = self.stop.is_set()
        session, applied = self._finish_persist()
        solved = sum(1 for r in self.results.values() if r["status"] == "solved")
        proposed = sum(1 for r in self.results.values() if r["status"] == "proposed")
        if isinstance(self.session_id, str):
            self._append_transcript_card(solved, proposed, cancelled)
        self.payload_out.update({
            "attachmentId": self.attachment_id,
            "executionId": self.solve_execution_id,
            "results": self.results,
            "appliedContents": applied,
            "builderSession": session,
            "cancelled": cancelled,
            "notAttempted": sorted(self.unstarted),
            "mode": self.mode,
        })
        if self.batch_reason:
            self.payload_out["reason"] = self.batch_reason
        return self.payload_out

    def _finish_persist(self) -> tuple[dict, list]:
        with projects_storage.spec_write_lock(self.user_key, self.project_id):
            spec = agents_spec_reads._read_spec_or_404(self.user_key, self.project_id)
            record = agents_spec_reads._record_or_404(spec, self.attachment_id)
            session = record.get("builderSession") or {}
            node_runs = session.get("nodeRuns") or {}
            self.apply_contents(spec)
            applied = [
                i for i in self.applied_contents if self.results.get(i["nodeId"], {}).get("status") == "solved"
            ]
            ids_to_ref = {
                nid: ref for ref, nid in (session.get("nodeIds") or {}).items()
            }
            node_states = session.get("nodeStates")
            for node_id, outcome in self.results.items():
                if outcome["status"] == "proposed":
                    # dev/67-6: nothing was written — the node stays pending
                    # until the user applies the content proposal; the plan row
                    # advances to "solving" (a review awaits).
                    ref = ids_to_ref.get(node_id)
                    if node_states is not None and ref is not None:
                        node_states[ref] = "solving"
                    continue
                if node_id in node_runs:
                    node_runs[node_id] = outcome["status"] if outcome["status"] != "skipped" else "skipped"
            session["nodeRuns"] = node_runs
            session.pop("solvingSince", None)
            session.pop("solveExecutionId", None)
            session.pop("cancelRequested", None)
            if self.mode == "propose" and self.return_phase not in (None, "", "solving"):
                # The propose batch resolved nothing — the session returns to the
                # phase the solve interrupted (typically "simulating").
                session["phase"] = self.return_phase
            else:
                session["phase"] = (
                    "ready"
                    if all(s not in ("pending", "failed") for s in node_runs.values())
                    else "applied"
                )
            record["builderSession"] = session
            projects_storage.write_spec(self.user_key, self.project_id, spec)
        return session, applied

    def _transcript_lines(self, cancelled: bool) -> tuple[list[str], list]:
        lines: list[str] = []
        for node_id, outcome in list(self.results.items())[:10]:
            line = f"{node_id[:8]} · {outcome['status']}"
            if outcome.get("verdict"):
                # dev/115: the verified loop's verdict and, on failure,
                # the attempt trail — one line per round, bounded.
                rounds = outcome.get("rounds") or 0
                line += f" · {outcome['verdict']} after {rounds} round{'s' if rounds != 1 else ''}"
            if outcome.get("reason") and outcome["status"] in ("pending", "skipped"):
                line += f": {str(outcome['reason'])[:120]}"
            lines.append(line)
            if outcome.get("verdict") == "fail":
                for attempt in (outcome.get("attempts") or [])[:3]:
                    why = agents_rounds._attempt_why(attempt, limit=160)
                    lines.append(f"  round {attempt.get('round')}: {attempt.get('kind')} ({why})")
                    if attempt.get("endpointEvidence"):
                        lines.append(f"    endpoint: {str(attempt['endpointEvidence'])[:200]}")
        lines = lines[:24]
        # dev/127: every attempt, in the transcript, per node that has a
        # trail — the card's lines cannot carry code, so the trail is its
        # own part. Bounded: the first _MAX_ATTEMPT_PARTS nodes, then a
        # line naming the rest (each still reachable from its own chat).
        attempt_parts: list = []
        trailed = [
            (nid, outcome) for nid, outcome in self.results.items()
            if (outcome or {}).get("attempts")
            and (outcome or {}).get("status") in ("failed", "pending", "skipped")
        ]
        for nid, outcome in trailed[:agents_budgets._MAX_ATTEMPT_PARTS]:
            node = self.nodes_by_id.get(nid) or {}
            part = agents_rounds._solve_attempts_part(
                self.current.get("spec") or self.spec, nid,
                str(node.get("goal") or nid)[:120], outcome,
            )
            if part is not None:
                attempt_parts.append(part)
        if len(trailed) > agents_budgets._MAX_ATTEMPT_PARTS:
            lines.append(
                f"{len(trailed) - agents_budgets._MAX_ATTEMPT_PARTS} more node(s) have attempt trails; "
                "open each node's agent to read them"
            )
        if cancelled:
            lines.append(f"cancelled: {len(self.unstarted)} node(s) not attempted")
        if self.batch_reason:
            # ONE reason line for the batch (not six identical ones).
            lines.append(f"reason: {self.batch_reason}")
        return lines, attempt_parts

    def _append_transcript_card(self, solved: int, proposed: int, cancelled: bool) -> None:
        lines, attempt_parts = self._transcript_lines(cancelled)
        config = self.config
        sessions.append_turns(
            self.user_key, self.project_id, self.session_id, self.attachment_id,
            [
                sessions.make_turn(
                    "agent",
                    (
                        f"Proposed content for {proposed} of {len(self.targets)} plan nodes."
                        if self.mode == "propose"
                        else f"Solved {solved} of {len(self.targets)} plan nodes."
                    )
                    + (f" Cancelled: {len(self.unstarted)} not attempted." if cancelled else ""),
                    content=[{
                        "type": "card",
                        "kind": "result",
                        "title": f"Solve: {solved} of {count_label(len(self.targets), 'node')}",
                        "lines": lines,
                    }, *attempt_parts, *self.extra_parts],
                    execution=agents_policy._execution_record(
                        self.solve_execution_id,
                        {"coord": self.coord, "provider": config.api_type,
                         "model": config.model, "tools": [], "intentEdited": False,
                         "llm": provider_config.llm_pin(config)},
                        {}, self.started, "ok", delegations=self.delegations,
                        retry_of=self.retry_of,
                    ),
                )
            ],
        )

    # ── the stream ──────────────────────────────────────────────────────────

    def events(self):
        try:
            yield "solve_started", {"executionId": self.solve_execution_id, "targets": list(self.targets)}
            self.resolution = delegation.resolve(
                self.user_key, self.project_id, self.manifest, "node.content.generate"
            ) if self.manifest is not None else delegation.Resolution("unresolvable")
            if self.resolution.outcome != "ok":
                yield from self._blocked_by_resolution()
            else:
                self.goals = [
                    str(self.nodes_by_id[t].get("goal") or "") for t in self.targets if t in self.nodes_by_id
                ]
                yield from self._run_passes()
            payload = self.finish()
            # dev/131: every session ends in exactly one of three ways, and says so.
            payload["endedBy"] = self.ended_by
            payload["passes"] = self.passes_run
            payload["waiting"] = agents_session._session_waiting_summary(
                self.results,
                [nid for nid, r in self.results.items() if (r or {}).get("status") in ("pending", "failed")],
            )
            yield "done", payload
        finally:
            agents_session._SOLVE_CANCEL_EVENTS.pop(self.solve_execution_id, None)
            self.finish()

    def _blocked_by_resolution(self):
        # Missing specialist: ONE reviewed install proposal (not per node),
        # every target failed — the panel explains and Retry works after
        # the user applies the install (REQ-ORCH-001).
        resolution = self.resolution
        if resolution.outcome == "not-installed":
            loop_ctx = {
                "attachment_id": self.attachment_id,
                "session_id": self.session_id,
            }
            specialist = resolution.manifest.name if resolution.manifest else resolution.coord
            status, text, part = agents_mint._mint_project_install(
                self.user_key, self.project_id, loop_ctx,
                resolution.coord,
                specialist,
                "node.content.generate",
            )
            if status == "proposed" and part is not None:
                self.extra_parts.append(part)
                reason = (
                    f"specialist not installed: {specialist} ({resolution.coord}) is not "
                    "installed in this project; an install proposal awaits review below; "
                    "Apply it, then Retry"
                )
            else:
                # dev/106: an unminted proposal is never claimed (the
                # refusal text says what to do instead).
                reason = f"specialist not installed: {text}"
        else:
            reason = "no installed agent declares node.content.generate"
        self.batch_reason = reason
        for node_id in self.targets:
            self.results[node_id] = {"status": "failed", "error": reason}
            yield "node_result", {"nodeId": node_id, "status": "failed", "error": reason}
        # dev/131: nothing a further pass could change — the missing
        # specialist is an install the USER applies, and the proposal for it
        # is already in the chat.
        self.ended_by = "blocked"

    def _run_passes(self):
        """dev/131: SOLVE IS A SESSION. dev/118's pass — waves in topological
        order, per-wave persist, honest reasons — is unchanged inside; what
        changed is that it no longer ends the run. The session keeps making
        passes while unresolved nodes remain, the session budget is unspent
        and the user has not stopped, so a blocker that clears later (a
        dataset the user confirms mid-run, an upstream a later pass fills) is
        picked up instead of stranding the dataflow (the owner's `224d23a2`:
        six solved, three left, exited in thirteen seconds)."""
        while True:
            self.pass_no += 1
            if self.pass_no > agents_budgets._SOLVE_MAX_PASSES:
                self.ended_by = "budget"
                break
            if self.should_stop():
                self.ended_by = "stopped"
                break
            if self._session_deadline_passed():
                self.ended_by = "budget"
                break
            if self.pass_no > 1 and self._batch_deadline_spent():
                # dev/118's outer ceiling: nothing would be dispatched, so
                # another pass could only re-mark the same nodes. Only from
                # the second pass on — the first pass IS dev/118's batch and
                # keeps its own boundary checks, unchanged.
                self.ended_by = "budget"
                break
            # Re-read the spec every pass: a selection confirmed, a node
            # edited or content written since the last pass all count.
            pass_spec = self._fresh_spec(fallback=self.current.get("spec") or self.spec)
            unresolved = self._unresolved(pass_spec)
            if not unresolved:
                self.ended_by = "complete"
                break
            pass_targets = self._pass_targets(pass_spec, unresolved)
            if not pass_targets:
                # Nothing can progress yet. The session STAYS ALIVE — the
                # user may confirm a source or edit a node — and says what
                # it is waiting for, checking again after a bounded,
                # stop-aware pause.
                if self.should_stop():
                    self.ended_by = "stopped"
                    break
                if self._session_deadline_passed():
                    self.ended_by = "budget"
                    break
                yield "solve_waiting", {
                    "pass": self.pass_no,
                    "seconds": self.session_wait_s,
                    "waiting": agents_session._session_waiting_summary(self.results, unresolved),
                    "secondsLeft": self._session_time_left(),
                }
                if agents_session._wait_for_stop(self.stop, self.session_wait_s):
                    self.ended_by = "stopped"
                    break
                continue
            yield from self._run_pass(pass_spec, pass_targets)

    def _fresh_spec(self, *, fallback: dict) -> dict:
        try:
            return agents_spec_reads._read_spec_or_404(self.user_key, self.project_id)
        except AgentServiceError:
            return fallback

    def _unresolved(self, pass_spec: dict) -> list[str]:
        record_now = attachments.get_attachment(pass_spec, self.attachment_id) or {}
        runs_now = (record_now.get("builderSession") or {}).get("nodeRuns") or {}
        return [
            nid for nid in self.targets
            if str(runs_now.get(nid, "pending")) in ("pending", "failed")
            # dev/131 (owner correction): what THIS session already
            # settled counts too. dev/118 persists a wave only at a
            # wave boundary, so the pass's last wave lands in
            # ``finish``; reading the disk alone made a node this
            # session had just solved look pending and re-solved it
            # every pass.
            and str((self.results.get(nid) or {}).get("status") or "pending")
            in ("pending", "failed")
        ]

    def _pass_targets(self, pass_spec: dict, unresolved: list[str]) -> list[str]:
        # dev/131: pass 1 attempts everything. A later pass attempts
        # every node that is NOT parked on the user — carrying the
        # error its last attempt produced, which is a different input
        # than the pass before had (owner correction: "it should carry
        # the currently error that is being given"). A node waiting on
        # a user action has no new input, so that one is attempted
        # again only when something that could unblock it changed.
        return [
            nid for nid in unresolved
            if self.pass_no == 1
            or (
                not agents_rounds._awaits_user_action(self.results.get(nid))
                and self.weak_passes.get(nid, 0) < agents_budgets._MAX_WEAK_PASSES
            )
            or self.attempted_signature.get(nid) != agents_session._blocker_signature(pass_spec, nid)
        ]

    def _run_pass(self, pass_spec: dict, pass_targets: list[str]):
        self.passes_run += 1
        self.spec = pass_spec
        self.current["spec"] = pass_spec
        self.nodes_by_id = {
            n.get("id"): n
            for n in (pass_spec.get("dataflow") or {}).get("nodes") or []
            if isinstance(n, dict)
        }
        waiting = agents_session._session_waiting_summary(self.results, pass_targets)
        yield "solve_pass", {
            "pass": self.pass_no,
            "targets": list(pass_targets),
            "remaining": len(pass_targets),
            "waiting": waiting,
            "secondsLeft": self._session_time_left(),
        }

        pool = ThreadPoolExecutor(max_workers=agents_budgets._SOLVE_MAX_WORKERS)
        # dev/131 (owner correction): the waves are this PASS's targets
        # — a node parked on the user (or already solved) is not
        # re-dispatched, so its trail and its reason survive the pass
        # that could not touch it. Depth is recomputed over the pass's
        # own set: an upstream outside it either has content already or
        # is named as a blocker honestly, exactly as dev/118 intends.
        waves = agents_session._solve_waves(self.spec, list(pass_targets))
        try:
            for wave_no, wave in enumerate(waves, 1):
                self.current["wave"] = wave_no
                if self.should_stop():
                    # Cancelled between waves: nothing here was dispatched.
                    for nid in wave:
                        self.record_outcome(nid, "unstarted", None, None)
                    continue
                if self._batch_deadline_spent():
                    # dev/118: out of time before this wave — its targets
                    # stay pending with the reason; Retry continues.
                    for nid in wave:
                        event = self.record_outcome(nid, "deadline", None, None)
                        if event is not None:
                            yield "node_result", event
                    continue
                yield "solve_wave", {"wave": wave_no, "of": len(waves), "nodeIds": list(wave)}
                for target in wave:
                    pool.submit(self.solve_one, target)
                yield from self._drain_wave(wave)
                if wave_no < len(waves):
                    # dev/118: the wave boundary persists and heartbeats;
                    # the next wave runs against what actually landed.
                    self.persist_wave(list(wave))
        except GeneratorExit:
            # Client gone (dev/63): stop dispatch, let in-flight children
            # finish, fold their results in WITHOUT yielding — the finally
            # persist keeps everything that completed.
            self.stop.set()
            pool.shutdown(wait=True)
            while not self.outcome_queue.empty():
                node_id, status, text, child = self.outcome_queue.get_nowait()
                if status != "started":
                    self.record_outcome(node_id, status, text, child)
            raise
        finally:
            pool.shutdown(wait=True)
        # dev/131 (owner correction): the pass boundary persists what
        # the pass settled — including its LAST wave, which dev/118
        # deliberately left to ``finish`` because a batch ended
        # there. A session does not end at a pass, so a pass that is
        # not the last must leave the same truth on disk.
        self.persist_wave(list(pass_targets))
        # dev/131: the signature is taken AFTER the pass, from a fresh
        # spec — a node attempted once its upstream landed in the same
        # pass has already seen that content, so the next pass must not
        # count it as a change. Taking it before the pass made every
        # pass that solved anything trigger another one.
        settled = self._fresh_spec(fallback=self.current.get("spec") or pass_spec)
        for nid in pass_targets:
            self.attempted_signature[nid] = agents_session._blocker_signature(settled, nid)

    def _drain_wave(self, wave: list[str]):
        remaining = len(wave)
        while remaining:
            node_id, status, text, child = self.outcome_queue.get()
            if status == "started":
                yield "node_started", {"nodeId": node_id}
                continue
            if status == "progress":
                # dev/115: the verified loop's rounds, live — the strip
                # shows "verifying" and each round's verdict.
                progress = dict(text)
                kind = progress.pop("kind", "")
                event_name = agents_session._SOLVE_PROGRESS_EVENTS.get(kind)
                if event_name:
                    yield event_name, {"nodeId": node_id, **progress}
                continue
            remaining -= 1
            if self.mode == "propose" and status == "verified":
                yield from self._propose_from_verified(node_id, text)
                continue
            if self.mode == "propose" and status == "solved":
                yield from self._propose_from_solved(node_id, text, child)
                continue
            event = self.record_outcome(node_id, status, text, child)
            if event is not None:
                yield "node_result", event

    def _propose_from_verified(self, node_id: str, outcome: dict):
        # dev/115: an EXECUTED review — the validation block
        # (verdict, rounds, attempts) rides the part, PASS or
        # FAIL (dev/67-7's labeled choice); a sandbox outage
        # mints nothing and the node stays pending.
        for c in outcome.get("delegations") or []:
            if c is not None:
                self.delegations.append(c)
        if outcome.get("verdict") == "infrastructure":
            event = self.record_outcome(node_id, "verified", outcome, None)
            if event is not None:
                yield "node_result", event
            return
        validation_block = {
            "verdict": outcome.get("verdict"),
            "rounds": outcome.get("rounds"),
            "evidence": outcome.get("evidence") or {},
            "attempts": outcome.get("attempts") or [],
        }
        part, home_att, mint_text = agents_delegates._mint_content_review_from_delegate(
            self.user_key, self.project_id,
            node_id=node_id,
            generated_text=outcome.get("candidate") or "",
            parent_attachment_id=self.attachment_id,
            parent_session_id=self.session_id,
            local_turn=True,
            validation=validation_block,
            grounding_base=self.solve_ground,
        )
        if part is not None:
            self.results[node_id] = {
                "status": "proposed",
                "proposalId": part["proposalId"],
                "proposalAttachmentId": home_att,
                "verdict": validation_block["verdict"],
                "rounds": validation_block["rounds"],
                "attempts": validation_block["attempts"],
            }
            yield "node_result", {
                "nodeId": node_id,
                "status": "proposed",
                "proposalId": part["proposalId"],
                "proposalAttachmentId": home_att,
                "verdict": validation_block["verdict"],
                "rounds": validation_block["rounds"],
            }
        else:
            self.results[node_id] = {"status": "failed", "error": mint_text[:300]}
            yield "node_result", {
                "nodeId": node_id, "status": "failed", "error": mint_text[:300],
            }

    def _propose_from_solved(self, node_id: str, text, child):
        # dev/67-6 (Simulation Mode: solve): nothing is
        # written — the child's content mints a reviewed
        # node.content.write proposal through the EXISTING
        # machinery (digest-pinned against the current
        # content). dev/72: the review lives with the node's
        # agent when one exists (find-only — the drain never
        # writes the spec beyond the mint's own write).
        if child is not None:
            self.delegations.append(child)
        # dev/114: the gate runs on the batch base BEFORE the
        # mint so the node's failure names the source.
        _pnode = self.nodes_by_id.get(node_id) or {}
        _v, _refusal = agents_grounding._gate_generated_content(
            self.user_key, self.project_id, self.solve_ctx,
            code=content.extract_node_content(text), engine="python",
            node_type=_pnode.get("type"), base=self.solve_ground,
        )
        if _refusal:
            err = self._ungrounded_error(_refusal, node_id)
            self.results[node_id] = {"status": "failed", "error": err[:300]}
            yield "node_result", {"nodeId": node_id, "status": "failed", "error": err[:300]}
            return
        # dev/73: the shared content→review sequence (also the
        # chat loops' — one mint policy, three callers).
        part, home_att, mint_text = agents_delegates._mint_content_review_from_delegate(
            self.user_key, self.project_id,
            node_id=node_id,
            generated_text=text,
            parent_attachment_id=self.attachment_id,
            parent_session_id=self.session_id,
            local_turn=True,
        )
        if part is not None:
            self.results[node_id] = {
                "status": "proposed",
                "proposalId": part["proposalId"],
                "proposalAttachmentId": home_att,
            }
            node = self.nodes_by_id.get(node_id) or {}
            node_label = (node.get('goal') or node_id)[:60]
            if home_att != self.attachment_id and isinstance(self.session_id, str):
                sessions.append_turns(
                    self.user_key, self.project_id, self.session_id, self.attachment_id,
                    [sessions.make_turn(
                        "agent",
                        f"Proposed content for {node_label!r} — "
                        "the review lives in the node's Node Builder.",
                        content=[content.make_delegation_part(
                            capability="node.content.generate",
                            coord="agent.node-builder",
                            name="Node Builder",
                            category="node",
                            attachment_id=home_att,
                            status="ok",
                            summary=f"content proposed for {node_label!r}",
                        )],
                    )],
                )
            yield "node_result", {
                "nodeId": node_id,
                "status": "proposed",
                "proposalId": part["proposalId"],
                "proposalAttachmentId": home_att,
            }
        else:
            self.results[node_id] = {
                "status": "failed", "error": mint_text[:300]
            }
            yield "node_result", {
                "nodeId": node_id, "status": "failed",
                "error": mint_text[:300],
            }

    # ── the worker (runs on the pool) ───────────────────────────────────────

    def solve_one(self, node_id: str) -> None:
        queue = self.outcome_queue
        try:
            if self.should_stop():
                queue.put((node_id, "unstarted", None, None))
                return
            if self._batch_deadline_spent():
                queue.put((node_id, "deadline", None, None))
                return
            queue.put((node_id, "started", None, None))
            node = self.nodes_by_id.get(node_id)
            if node is None:
                queue.put((node_id, "skipped", None, None))
                return
            if (node.get("content") or "").strip():
                # User content preserved.
                queue.put((node_id, "skipped", None, None))
                return
            if self.content_kind(node) == workflow_spec.CONTENT_KIND_NONE:
                # dev/134: this kind authors NOTHING — it renders or
                # forwards its input and everything it does comes from
                # the wiring (a merge, a pool, a simple view, a spatial
                # join). Asking a model for its content spends a call
                # to produce something that can only be wrong: the
                # owner's `e72c7080` wrote the reply "not controllable"
                # into a merge-flow and a data-pool as their content.
                queue.put((node_id, "no-content", None, None))
                return
            # dev/67-6: the ONE context composer — the child sees the
            # node's neighborhood (goals, runtime status, datasets),
            # not just its own intent.
            wave_spec = self.current["spec"]
            upstream_outputs = agents_session._upstream_outputs_for(
                wave_spec, node_id, self.wave_outputs, schema_fn=self.schema_of_artifact,
            )
            inputs = self._worker_inputs(node_id, node, wave_spec, upstream_outputs)
            if self.verify and self.content_kind(node) in (
                workflow_spec.CONTENT_KIND_CODE,
                workflow_spec.CONTENT_KIND_GRAMMAR,
            ):
                self._run_verified_worker(node_id, node, wave_spec, upstream_outputs)
                return
            status, text, child, _home = agents_delegates._run_delegate_traced(
                self.user_key, self.project_id, self.resolution.coord,
                "node.content.generate", inputs, self.config,
                parent_execution_id=self.solve_execution_id,
                parent_coord=self.coord,
                attachment_id=self.attachment_id,
                node_id=node_id,
                home_create=False,  # workers never write the spec
            )
            queue.put(
                (node_id, "solved" if status == "ok" else "failed", text, child)
            )
        except BaseException as exc:  # a lost item would deadlock the drain
            queue.put((node_id, "failed", f"solve worker error: {exc}", None))

    def _worker_inputs(self, node_id: str, node: dict, wave_spec: dict, upstream_outputs) -> dict:
        inputs = {
            "nodeType": node.get("type"),
            "intent": node.get("goal"),
            "planSiblings": self.goals[:20],
            "nodeContext": node_context.compose_node_context(
                self.user_key, self.project_id, wave_spec, node_id
            ),
        }
        if upstream_outputs:
            # dev/118: what the nodes feeding this one actually
            # produced when they ran — a type to write against.
            inputs["upstreamOutputs"] = upstream_outputs
        # dev/114: the seventh DEC-063 application — a data-
        # loading child is HANDED its grounded sources.
        if source_grounding.is_data_loading_type(
            _pkg_services.canonical_template_id(node.get("type"))
        ):
            inputs["sourceGrounding"] = agents_grounding._source_grounding_inputs(
                agents_grounding._grounding_context(
                    self.user_key, self.project_id, self.solve_ctx,
                    node_type=node.get("type"), base=self.solve_ground,
                    extra_texts=(str(node.get("goal") or ""),),
                )
            )
        return inputs

    def _traced_runner(self, node_id: str):
        # every round traced at the node's home (dev/72), the loop's progress
        # relayed as node_* events, the outcome folded by record_outcome.
        def _traced(delegate_inputs, _node_id=node_id):
            st, tx, ch, _h = agents_delegates._run_delegate_traced(
                self.user_key, self.project_id, self.resolution.coord,
                "node.content.generate", delegate_inputs, self.config,
                parent_execution_id=self.solve_execution_id,
                parent_coord=self.coord,
                attachment_id=self.attachment_id,
                node_id=_node_id,
                home_create=False,  # workers never write the spec
            )
            return st, tx, ch

        return _traced

    def _recorded_failure(self, node_id: str, node: dict):
        # dev/129: errors from ANY execution feed the fix. A node that still
        # holds the code a Play run raised on is repaired FROM that code —
        # round 0 re-runs it and the correction works on the real traceback —
        # instead of being regenerated as if nothing had happened.
        try:
            from utk_curio.backend.app.execution import runtime_journal

            candidate_failure = runtime_journal.last_failure(
                self.user_key, self.project_id, node_id
            )
            if runtime_journal.failure_matches(
                candidate_failure, node.get("content")
            ):
                return candidate_failure
        except Exception:  # noqa: BLE001
            return None
        return None

    def _run_verified_worker(self, node_id: str, node: dict, wave_spec: dict, upstream_outputs) -> None:
        """dev/115 (DEC-073) → dev/118 (DEC-075): the ONE verified-content
        loop for EVERY executable kind — and, since dev/134, for every
        GRAMMAR kind too: the runner reports "not executable" for a document
        and dev/129's validator decides, so nothing unvalidated is written on
        any path. The batch used to route a Vega or AUTK node past this
        loop, which is how an invalid document and the sentence "not
        controllable" reached two nodes in the owner's `e72c7080`."""
        recorded = self._recorded_failure(node_id, node)
        # dev/131 (owner correction): on a later pass the error
        # this node's last attempt produced is the input this
        # one starts from — never the same blank inputs again.
        # A recorded on-disk failure is the stronger evidence
        # (it is the code actually ON the node), so it wins.
        carry = (
            None if recorded
            else agents_rounds._carry_forward_error(self.results.get(node_id))
        )
        gen = agents_rounds._verified_content_rounds(
            self.user_key, self.project_id,
            spec=wave_spec, node=node, resolution=self.resolution, config=self.config,
            start_from_current=bool(recorded),
            recorded_failure=recorded,
            carry_forward=carry,
            parent_execution_id=self.solve_execution_id, parent_coord=self.coord,
            attachment_id=self.attachment_id, exec_fn=None,
            grounding_loop_ctx=self.solve_ctx, grounding_base=self.solve_ground,
            extra_inputs={"planSiblings": self.goals[:20],
                          **({"upstreamOutputs": upstream_outputs} if upstream_outputs else {})},
            delegate_runner=self._traced_runner(node_id),
            # dev/132 (closes dev/131 F4): the eager mapping,
            # topped up for a dataset the user imported or
            # installed since this session started.
            dataset_paths_fn=lambda codes: agents_grounding._session_dataset_paths(
                self.project_id, self.acting_user, self.solve_dataset_paths, codes
            ),
            # dev/133: the batch's memoized preview — one
            # description per artifact, reused by the emptiness
            # check and by the next node's input schema.
            result_summary_fn=self.schema_of_artifact,
            exec_user_key=self.user_key,
            acting_user=self.acting_user,
            secrets_fn=agents_grounding._exec_secrets_resolver(self.user_key),
            prior_outputs_fn=lambda: {
                nid: o["output"] for nid, o in self.wave_outputs.items() if o.get("output")
            },
            # dev/126: the batch resolves a data-loading node's
            # source before generating for it.
            resolve_source=agents_grounding._source_resolver(
                self.user_key, self.project_id, coord=self.coord,
                attachment_id=self.attachment_id,
                execution_id=self.solve_execution_id, config=self.config,
                manifest=self.manifest,
                extra_texts=(str((self.spec.get("dataflow") or {}).get("task") or ""),),
                catalog_rows=self.catalog_rows,
            ),
            # dev/131: this node may not outlive the session.
            node_budget_s=max(
                int(self.session_deadline_s - (time.monotonic() - self.started)), 1
            ),
        )
        try:
            while True:
                kind, data = next(gen)
                self.outcome_queue.put((node_id, "progress", {"kind": kind, **data}, None))
        except StopIteration as stop_iter:
            self.outcome_queue.put((node_id, "verified", stop_iter.value, None))
