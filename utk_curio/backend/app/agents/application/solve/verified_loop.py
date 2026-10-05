"""The verified-content loop, as an object (memo dev/142, B3; re-derived on enh/agent-catalog).

This is the body of the former ``_verified_content_rounds`` (dev/115,
DEC-073 → dev/118 → dev/126 → dev/127 → dev/129 → dev/131 → dev/133 → dev/134
→ dev/136 → dev/137 → dev/138): the ONE generate → gate → execute → correct
loop every Solve path runs. Nothing about WHAT a round does changed; what
changed is that each stage has a name — :meth:`_generation_inputs`,
:meth:`_source_gate`, :meth:`_input_contract_gate`, :meth:`_repeat_check`,
:meth:`_validate`, :meth:`_document_check`, :meth:`_absent_output_check`,
:meth:`_empty_result_check`, :meth:`_record_round` — and :meth:`run` reads
as the loop it is.

Stage methods are generators (they relay ``node_executed`` and
``round_verdict`` events) and return a control token: ``None`` to proceed
to the next stage, ``CONTINUE`` to start the next round, ``BREAK`` to leave
the loop, or a result dict to end the whole loop with that result.

The attempt/remedy/probe helpers stay in :mod:`rounds` and are called
through that module so a test patches them in one place.
"""

from __future__ import annotations

import logging
import queue as _queue
import threading
import time

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import contracts
from utk_curio.backend.app.agents.domain import document_validation
from utk_curio.backend.app.agents.domain import failure_text
from utk_curio.backend.app.agents.domain import input_contract
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.domain import result_shape
from utk_curio.backend.app.agents.domain import upstream_schema
from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.domain import validation as agents_validation
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.packages import service as packages_services

log = logging.getLogger(__name__)

CONTINUE = "continue"
BREAK = "break"


class VerifiedRounds:
    """One node's verified-content loop; :meth:`run` streams it and returns
    the outcome dict (``verdict``, ``evidence``, ``rounds``, ``candidate``,
    ``delegations``, ``roundsTrace``, ``attempts``, ``stoppedBy``)."""

    def __init__(
        self,
        user_key: str,
        project_id: str,
        *,
        spec: dict,
        node: dict,
        resolution,
        config: ProviderConfig,
        parent_execution_id: str,
        parent_coord: str,
        attachment_id: str | None,
        exec_fn,
        grounding_loop_ctx: dict,
        grounding_base: dict | None = None,
        start_from_current: bool = False,
        extra_inputs: dict | None = None,
        delegate_runner=None,
        dataset_paths_fn=None,
        exec_user_key: str | None = None,
        secrets_fn=None,
        prior_outputs_fn=None,
        resolve_source=None,
        clock=time.monotonic,
        recorded_failure=None,
        node_budget_s=None,
        carry_forward=None,
        result_summary_fn=None,
        acting_user=None,
    ):
        self.user_key = user_key
        self.project_id = project_id
        self.spec = spec
        self.node = node
        self.exec_fn = exec_fn
        self.start_from_current = start_from_current
        self.extra_inputs = extra_inputs
        self.dataset_paths_fn = dataset_paths_fn
        self.exec_user_key = exec_user_key
        # #485: the account's User row, captured in the request; validation
        # runs on a thread of its own, where the request's user is gone.
        self.acting_user = acting_user
        self.secrets_fn = secrets_fn
        self.prior_outputs_fn = prior_outputs_fn
        self.resolve_source = resolve_source
        self.clock = clock
        self.recorded_failure = recorded_failure
        self.carry_forward = carry_forward
        self.result_summary_fn = result_summary_fn
        self.run_delegate = delegate_runner or (
            lambda inputs: delegation.run_delegate(
                user_key, project_id, resolution.coord,
                "node.content.generate", inputs, config,
                parent_execution_id=parent_execution_id,
                parent_coord=parent_coord,
                attachment_id=attachment_id,
            )
        )
        self.node_id = node.get("id")
        self.node_type = node.get("type")
        self.is_data_loading = source_grounding.is_data_loading_type(
            packages_services.canonical_template_id(self.node_type)
        )
        self.available, self.loop_templates = self._roster()
        self.grounding_loop_ctx = self._loop_grounding_ctx(grounding_loop_ctx)
        self.grounding_ctx = self._grounding_context(grounding_base)
        # ── loop state ──
        self.verdict_result: dict | None = None
        self.rounds_used = 0
        self.candidate = ""
        self.delegations: list = []
        self.rounds_trace: list[str] = []
        self.attempts: list[dict] = []
        self.previous_attempt: str | None = None
        self.previous_error: str | None = None
        self.url_evidence: list[dict] = []
        self.confirmed_source: dict | None = None
        self.stopped_by: str | None = None  # dev/127: which bound ended the loop
        self.repeats = 0
        self.use_current = False
        self.reuse_retried = False
        self.dataset_paths = None
        self.secrets = None
        self._seed_from_recorded_failure()
        self._seed_from_carry_forward()
        # dev/128: what ``arg`` IS for this node — a fact of the graph, computed
        # once (it cannot change mid-loop), handed to the child as an input, and
        # enforced before the sandbox. The owner's report: a node with several
        # inputs received ``arg`` and treated it as a frame.
        self.arg_contract = input_contract.arg_shape(spec, self.node_id)
        if (extra_inputs or {}).get("upstreamOutputs"):
            self.arg_contract = input_contract.with_schemas(
                self.arg_contract, (extra_inputs or {}).get("upstreamOutputs")
            )
        # dev/129: the wall budget is the bound; the attempt count is a cap that
        # sits ABOVE what a quarter hour affords, so in practice the clock stops
        # the loop and `stoppedBy` says so. A deployment (or a test) that wants a
        # tighter cap sets CURIO_SOLVE_MAX_ATTEMPTS and gets it.
        self.max_rounds = min(agents_budgets.solve_max_attempts(), agents_budgets.MAX_SOLVE_ATTEMPTS)
        # dev/131: a node's repair budget is clamped by what remains of the
        # SESSION's, so the owner's fifteen minutes means the same thing at both
        # levels and one node cannot spend a session it shares.
        self.node_budget_s = (
            max(int(node_budget_s), 1) if isinstance(node_budget_s, (int, float))
            else agents_budgets.solve_node_budget_s()
        )
        self.loop_started = None

    # ── setup ───────────────────────────────────────────────────────────────

    def _roster(self) -> tuple[dict | None, dict | None]:
        """The template roster: arity metadata for the type check (fails open
        when unavailable) and, dev/119 (DEC-076), the same roster classifies
        executability for the runner; dev/134: and routes the document validator."""
        try:
            available = {
                t["id"]: t for t in packages_services.available_templates(self.user_key, self.project_id)
            }
        except Exception:
            available = None  # arity metadata unavailable: type check fails open
        loop_templates = (
            {tid: {
                "executable": bool(row.get("executable")),
                "engine": row.get("engine") or "python",
                "contentKind": row.get("contentKind") or "none",
                **({"grammar": row["grammar"]} if row.get("grammar") else {}),
            } for tid, row in available.items()}
            if available else None
        )
        return available, loop_templates

    @staticmethod
    def _loop_grounding_ctx(shared: dict) -> dict:
        """ONE grounding context per loop: the same catalog/verified-URL evidence
        for every round, one probe budget. dev/116 live fix (2026-09-09): the
        budget is the LOOP's own — a failed round spends up to five calls and
        the run-wide four starved every correction of its evidence. The probe
        cache and the verified map stay shared with the caller's context."""
        loop_ctx = dict(shared)
        loop_ctx["_probe_cache"] = shared.setdefault("_probe_cache", {})
        loop_ctx["_verified_urls"] = shared.setdefault("_verified_urls", {})
        loop_ctx["_egress_budget"] = egress.CallBudget(agents_budgets._LOOP_EGRESS_CALLS)
        return loop_ctx

    def _grounding_context(self, grounding_base):
        dataflow = (self.spec or {}).get("dataflow") or {}
        try:
            # The node's goal and the dataflow's mission are human-authored intent
            # (a plan goal saying "synthetic sample data" authorizes inline data).
            return agents_grounding._grounding_context(
                self.user_key, self.project_id, self.grounding_loop_ctx, node_type=self.node_type,
                base=grounding_base,
                extra_texts=(str(self.node.get("goal") or ""), str(dataflow.get("task") or "")),
            )
        except Exception:
            log.warning("Grounding context unavailable for node %s", self.node_id, exc_info=True)
            return None

    def _seed_from_recorded_failure(self) -> None:
        recorded_failure = self.recorded_failure
        if isinstance(recorded_failure, dict) and recorded_failure.get("stderr"):
            # dev/129: the loop is starting from code that already failed — in a
            # Play run or an earlier validation — and the traceback is on disk.
            # Round 0 re-runs it (start_from_current), so this line is the trail's
            # explanation of WHY it starts there; the correction gets the real
            # traceback from the run itself.
            self.rounds_trace.append(
                f"starting from the code on the node, which failed at "
                f"{recorded_failure.get('origin') or 'a previous run'}"
                f"{' (' + str(recorded_failure.get('ranAt')) + ')' if recorded_failure.get('ranAt') else ''}"
                f": {failure_text.summary(recorded_failure['stderr'], limit=200)}"
            )
            self.previous_error = str(recorded_failure["stderr"])[-2000:]

    def _seed_from_carry_forward(self) -> None:
        carry_forward = self.carry_forward
        if isinstance(carry_forward, dict) and (carry_forward.get("error") or "").strip():
            # dev/131 (owner correction): a retry must not carry the SAME inputs.
            # When an earlier pass of this session already tried and failed, its
            # last candidate and the error it produced are the inputs this pass
            # starts from — so round 0 generates a CORRECTION, not another blank
            # first draft. (A node blocked on the user has no such input, which is
            # why only that case waits.)
            self.previous_attempt = (
                str(carry_forward.get("code") or "")[:6000] or self.previous_attempt
            )
            self.previous_error = str(carry_forward["error"])[-2000:]
            self.rounds_trace.append(
                "carrying forward the previous attempt's error: "
                + failure_text.summary(
                    str(carry_forward["error"]), code=carry_forward.get("code"), limit=200
                )
            )

    # ── the loop ────────────────────────────────────────────────────────────

    def run(self):
        early = self._resolve_source_first()
        if early is not None:
            return early
        self.loop_started = self.clock()
        for round_index in range(self.max_rounds):
            if round_index and (self.clock() - self.loop_started) >= self.node_budget_s:
                # dev/127: the budget is checked BEFORE a new round is dispatched,
                # so a round in flight always finishes and is recorded. dev/129:
                # this is now the NORMAL stop, which is why it is checked first.
                self.stopped_by = "budget"
                self.rounds_trace.append(
                    f"stopped after round {self.rounds_used}: this node's "
                    f"{self.node_budget_s}s repair budget is spent"
                )
                break
            self.rounds_used = round_index + 1
            yield "generation_round", {"round": self.rounds_used}
            self.use_current = bool(
                round_index == 0 and self.start_from_current and str(self.node.get("content") or "").strip()
            )
            if self.use_current:
                self.candidate = str(self.node.get("content") or "")
            else:
                status, text, child = self.run_delegate(self._generation_inputs())
                self.delegations.append(child)
                if status != "ok":
                    self._generation_failed(text)
                    break
                self.candidate = content.extract_node_content(text)
            token = None
            for stage in (
                self._source_gate,
                self._input_contract_gate,
                self._repeat_check,
                self._validate,
                self._document_check,
                self._absent_output_check,
                self._empty_result_check,
                self._record_round,
            ):
                token = yield from stage()
                if token is not None:
                    break
            if isinstance(token, dict):
                return token
            if token == BREAK:
                break
        return self._finish()

    # ── stage: generation ───────────────────────────────────────────────────

    def _generation_inputs(self) -> dict:
        inputs = {
            "nodeType": self.node_type,
            "intent": self.node.get("goal"),
            "nodeContext": node_context.compose_node_context(
                self.user_key, self.project_id, self.spec, self.node_id
            ),
        }
        if self.is_data_loading and self.grounding_ctx is not None:
            # dev/114's seventh DEC-063 application, on every caller.
            inputs["sourceGrounding"] = agents_grounding._source_grounding_inputs(self.grounding_ctx)
            if self.confirmed_source is not None:
                # dev/126: the source the USER confirmed on this node —
                # handed over, not inferred from what was verified once.
                inputs["sourceGrounding"]["confirmedSource"] = self.confirmed_source
        if self.arg_contract.get("kind") != input_contract.KIND_NONE:
            # dev/128 (DEC-063, ninth application): the shape of `arg`, per
            # node, on the first generation and on every correction.
            inputs["inputContract"] = self.arg_contract
        if self.extra_inputs:
            inputs.update({k: v for k, v in self.extra_inputs.items() if k not in inputs})
        if self.previous_attempt is not None or (self.previous_error or "").strip():
            # The NCB instruction's self-correction contract: fix
            # precisely the failure, grounded in the real traceback.
            # dev/131: a carried-forward error with no code (a prose
            # decline, a refusal that named no candidate) still rides —
            # the error IS the new input.
            inputs["validationError"] = (self.previous_error or "")[:2000]
            if self.previous_attempt is not None:
                inputs["previousAttempt"] = self.previous_attempt[:6000]
            if self.url_evidence:
                inputs["urlEvidence"] = self.url_evidence
        return inputs

    def _generation_failed(self, text) -> None:
        self.verdict_result = {
            "verdict": "fail",
            "evidence": {"kind": "generation-error", "detail": (text or "")[:300]},
        }
        self.attempts.append({
            "round": self.rounds_used, "verdict": "fail", "kind": "generation-error",
            "detail": (text or "")[:agents_budgets._ATTEMPT_DETAIL_CHARS],
        })
        self.stopped_by = "generation"

    # ── the shared "this round failed" record ───────────────────────────────

    def _record_failed_round(self, kind: str, refusal: str, *, trace: str | None = None,
                             trace_limit: int = 200, source: str | None = None,
                             prose: bool = False):
        """Set the round's verdict, relay it, write the trace line and the
        attempt; the caller decides what the next round carries."""
        self.verdict_result = {"verdict": "fail", "evidence": {"kind": kind, "detail": refusal[:2000]}}
        yield "round_verdict", {"round": self.rounds_used, "verdict": "fail"}
        self.rounds_trace.append(
            f"round {self.rounds_used}: fail — {trace if trace is not None else refusal[:trace_limit]}"
        )
        attempt = {
            "round": self.rounds_used, "contentSha256": agents_rounds._content_sha(self.candidate),
            "verdict": "fail", "kind": kind,
            "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
            "source": source or ("current content" if self.use_current else "generated"),
            **agents_rounds._attempt_code_field(self.candidate, prose=prose),
        }
        self.attempts.append(attempt)
        return attempt

    def _carry(self, error: str) -> None:
        self.previous_attempt = self.candidate
        self.previous_error = error
        self.url_evidence = []

    # ── stages: gates before the sandbox ────────────────────────────────────

    def _source_gate(self):
        """DEC-072: the gate runs BEFORE the sandbox does — a fabricated path
        or an unverified URL never executes, and the refusal is the error
        the next round corrects."""
        if self.grounding_ctx is None:
            return None
        gate = source_grounding.check_grounding(self.candidate, "python", self.grounding_ctx)
        if gate.ok:
            return None
        refusal = source_grounding.refusal_text(gate, self.grounding_ctx)
        kind = "ungrounded-source"
        declined = not self.use_current and agents_rounds._is_prose_decline(self.candidate)
        if declined:
            # The delegate followed its rule ("return a one-line
            # explanation of what source is missing instead of code").
            # Record ITS words as the attempt, not a gate verdict on
            # prose (dev/115 field fix, 2026-09-08).
            refusal = f"the content builder declined: {self.candidate.strip()}"
            kind = "source-missing"
        # dev/127: what was refused, verbatim — the literal the gate named is
        # IN this text, so showing it is the point.
        attempt = yield from self._record_failed_round(kind, refusal, trace_limit=160, prose=declined)
        if declined:
            # dev/116: when the decline is about a credential and the
            # failed attempt named a host, the remedy is concrete —
            # add a connection key for that host (or use the saved one).
            remedy = agents_rounds._decline_remedy(self.candidate, self.previous_attempt, self.grounding_ctx)
            if remedy:
                self.verdict_result["evidence"]["remedy"] = remedy
                attempt["remedy"] = remedy
            # A decline names an input nobody in this loop can supply
            # (a key, a path, a URL). Asking the same builder again
            # with the same inputs only repeats it — the user is the
            # correction; stop and say so.
            self.stopped_by = "decline"
            return BREAK
        self._carry(refusal)
        return CONTINUE

    def _input_contract_gate(self):
        """dev/128: the shape gate, beside the DEC-072 source gate and before
        the sandbox. A list-shaped `arg` used as a frame is provably wrong —
        a list has no such attribute — so the round fails HERE, for free,
        with the slot table as its correction instead of a library's
        AttributeError three minutes later."""
        violation = input_contract.check(self.candidate, self.arg_contract)
        if violation is None:
            return None
        refusal = input_contract.refusal_text(self.arg_contract, violation)
        yield from self._record_failed_round("input-contract", refusal)
        self._carry(refusal)
        return CONTINUE

    def _repeat_check(self):
        """A repeat is judged AFTER the gate: a refused candidate keeps its own
        kind. dev/116 live fix (2026-09-09): the correction changed only
        comments or spacing — running it again would fail the same way. Not
        run; the next round is told so, in plain words."""
        if self.use_current or self.previous_attempt is None:
            return None
        if not agents_rounds._same_code(self.candidate, self.previous_attempt):
            return None
        detail = (
            "the correction repeated the previous attempt (only comments or spacing "
            "changed) — not run again; change the request that failed: "
            + (self.previous_error or "")[:400]
        )
        yield from self._record_failed_round(
            "repeated-attempt", detail, trace="repeated the previous attempt", source="generated",
        )
        self.repeats += 1
        if self.repeats >= agents_budgets._MAX_REPEATED_ATTEMPTS:
            # dev/129: a repeat no longer ends the loop — the owner asked
            # for as many retries as the budget affords. It ESCALATES: the
            # next round is told how many times it has repeated itself and
            # that it must change approach, not phrasing. Only an
            # implausible run of identical candidates stops the loop, so a
            # stuck model cannot spend fifteen minutes of provider calls.
            detail = (
                f"you have now returned the same code {self.repeats} times. Stop repeating it: "
                "change the APPROACH — a different library call, a different key or column, "
                "a different shape of the result — or say plainly what you cannot do. "
                + detail
            )
            self.previous_error = detail
            self.attempts[-1]["detail"] = detail[:agents_budgets._ATTEMPT_DETAIL_CHARS]
            if self.repeats >= agents_budgets._MAX_REPEATED_ATTEMPTS_HARD:
                self.stopped_by = "repeat"
                return BREAK
        self.previous_attempt = self.candidate
        self.previous_error = detail
        return CONTINUE  # url_evidence: unchanged — same request, same answer

    # ── stage: the sandbox ──────────────────────────────────────────────────

    def _round_dataset_paths(self):
        if self.dataset_paths_fn is None:
            return None
        try:
            slice_codes = [
                str(n.get("content") or "")
                for n in ((self.spec.get("dataflow") or {}).get("nodes") or [])
                if isinstance(n, dict)
            ]
            return self.dataset_paths_fn([self.candidate, *slice_codes]) or None
        except Exception:
            return None

    def _round_secrets(self):
        # dev/116: the connection keys THIS candidate names, resolved per round
        # so a correction that adopts curio_secret("<name>") runs with it.
        if self.secrets_fn is None:
            return None
        try:
            return self.secrets_fn([self.candidate]) or None
        except Exception:
            return None

    def _round_prior_outputs(self):
        # dev/118 commit 4: the outputs recorded for ancestors that passed
        # earlier in this batch stand in for their re-run (fresh per round).
        if self.prior_outputs_fn is None:
            return None
        try:
            return self.prior_outputs_fn() or None
        except Exception:
            return None

    def _validate_with(self, prior, candidate_text, paths, secret_values):
        progress_queue: _queue.Queue = _queue.Queue()

        def _run_validation():
            try:
                result = agents_validation.validate_candidate(
                    self.user_key, self.project_id, self.spec, self.node_id, candidate_text,
                    exec_fn=self.exec_fn,
                    available_templates=self.available,
                    dataset_paths=paths,
                    exec_user_key=self.exec_user_key,
                    secrets=secret_values,
                    prior_outputs=prior,
                    templates=self.loop_templates,
                    acting_user=self.acting_user,
                    progress=lambda nid, i, total: progress_queue.put(
                        ("progress", nid, i, total)
                    ),
                )
            except Exception as exc:  # the validator must never kill the stream
                result = {
                    "verdict": "infrastructure",
                    "evidence": {"kind": "infrastructure", "detail": str(exc)[:300]},
                }
            progress_queue.put(("done", result))

        thread = threading.Thread(target=_run_validation)
        thread.start()
        while True:
            item = progress_queue.get()
            if item[0] == "progress":
                _, nid, index, total = item
                yield "node_executed", {"nodeId": nid, "index": index, "total": total}
                continue
            thread.join(timeout=5)
            return item[1]

    def _validate(self):
        """The candidate runs with ITS dataset paths, connection keys and the
        batch's prior outputs; a vanished reused input re-runs the slice whole,
        once, silently."""
        self.dataset_paths = self._round_dataset_paths()
        self.secrets = self._round_secrets()
        prior_outputs = self._round_prior_outputs()
        candidate = self.candidate
        self.verdict_result = yield from self._validate_with(
            prior_outputs, candidate, self.dataset_paths, self.secrets)
        self.reuse_retried = False
        if prior_outputs and agents_session._looks_like_a_vanished_reused_input(self.verdict_result):
            # A reused artifact is gone (the sandbox store moved on): that is
            # not the candidate's fault. Once, silently, the slice runs whole.
            self.verdict_result = yield from self._validate_with(
                None, candidate, self.dataset_paths, self.secrets)
            self.reuse_retried = True
        return None

    # ── stages: verdicts the sandbox cannot give ────────────────────────────

    def _document_check(self):
        """dev/129: the sandbox cannot RUN a Vega or AUTK document, which is
        not the same as being unable to CHECK it. An invalid document is a
        failed round like any other — the validator's message is the
        correction — and a valid one is written with a stronger, still
        truthful claim than "no code to run". dev/134: routed by the roster's
        own grammarId, and checked against the columns this node's input
        actually has — the same rows the generation request was handed
        (DEC-063). The roster's own row only: an unknown kind is not passive."""
        if self.verdict_result.get("verdict") != "not-executable" or not str(self.candidate or "").strip():
            return None
        # #662: checked as it runs, its references resolved the way the canvas
        # resolves them before it draws: widgets, input chips, shared tags.
        resolved, unresolved = self._resolved_document()
        if unresolved:
            yield from self._record_failed_round("document-invalid", unresolved)
            self._carry(unresolved)
            return CONTINUE
        roster_row = (self.loop_templates or {}).get(str(self.node_type).split("@", 1)[0]) or {}
        document = document_validation.validate(
            self.node_type, resolved,
            grammar_id=workflow_spec.grammar_id_of(self.node_type, self.loop_templates),
            content_kind=roster_row.get("contentKind"),
            columns=upstream_schema.columns_of(
                (self.extra_inputs or {}).get("upstreamOutputs")
            ),
        )
        if document["status"] == document_validation.STATUS_INVALID:
            refusal = document_validation.refusal_text(
                self.node_type, document,
                grammar_id=workflow_spec.grammar_id_of(self.node_type, self.loop_templates),
            )
            yield from self._record_failed_round("document-invalid", refusal)
            self._carry(refusal)
            return CONTINUE
        evidence = self.verdict_result.setdefault("evidence", {})
        if document["status"] == document_validation.STATUS_VALID:
            token = yield from self._empty_render_check()
            if token is not None:
                return token
            evidence["documentValidated"] = document_validation.canonical_suffix(self.node_type)
        else:
            evidence["documentUnchecked"] = str(document.get("why") or "")[:300]
            evidence["documentPassive"] = bool(document.get("passive"))
        return None

    def _resolved_document(self) -> tuple[str, str | None]:
        """The candidate document with its references resolved against this
        node in the saved spec, and why one cannot be, or None. A document with
        no references is itself."""
        candidate = str(self.candidate or "")
        if "[!!" not in candidate:
            return candidate, None
        spec = workflow_spec.parse_workflow_dict(self.spec or {})
        node = next((n for n in spec.nodes if n.id == self.node_id), None)
        if node is None:
            return candidate, None
        try:
            return spec.node_code(node, "json", candidate), None
        except workflow_spec.CodeReferenceError as exc:
            return candidate, f"the document's references cannot be resolved: {exc}"

    def _empty_render_check(self):
        """dev/136: a valid document is not a drawn picture. When the node's
        last RENDER drew nothing and the document on it is the one that drew
        nothing, passing here would end the loop on a chart the user is looking
        at empty — the owner's report. The recorded render failure becomes this
        round's verdict instead."""
        recorded_failure = self.recorded_failure
        render_cause = (
            result_shape.empty_render_cause((recorded_failure or {}).get("kind"))
            if self.use_current and isinstance(recorded_failure, dict) else None
        )
        if render_cause is None:
            return None
        upstream_rows = (self.extra_inputs or {}).get("upstreamOutputs")
        refusal = result_shape.empty_render_refusal(
            message=str((recorded_failure or {}).get("stderr") or ""),
            cause=render_cause,
            upstream_outputs=upstream_rows,
        )
        if not result_shape.is_document_at_fault(render_cause):
            # Nothing arrived, so no document could have drawn
            # anything: dev/133's rule, applied to a picture. The
            # node WAITS on its upstream (dev/118's vocabulary) and
            # its document is left exactly as it is.
            return {
                "verdict": "fail",
                "evidence": {
                    "kind": contracts.EMPTY_RENDER_KIND,
                    "detail": refusal,
                    "upstreamEmpty": True,
                },
                "rounds": self.rounds_used,
                "candidate": self.candidate,
                "delegations": self.delegations,
                "roundsTrace": self.rounds_trace + [
                    f"round {self.rounds_used}: the document is valid and its "
                    "last render drew nothing — its input was empty"
                ],
                "attempts": self.attempts + [{
                    "round": self.rounds_used,
                    "contentSha256": agents_rounds._content_sha(self.candidate),
                    "verdict": "fail", "kind": contracts.EMPTY_RENDER_KIND,
                    "detail": refusal[:agents_budgets._ATTEMPT_DETAIL_CHARS],
                    "source": "current content",
                    **agents_rounds._attempt_code_field(self.candidate),
                }],
                "stoppedBy": "blocker",
            }
        yield from self._record_failed_round(contracts.EMPTY_RENDER_KIND, refusal, source="current content")
        self._carry(refusal)
        return CONTINUE

    def _absent_output_check(self):
        """dev/138: the run passed and produced NO output — `return None`
        types as "null", which read as success in three places at once. The
        journal and the consumer type check now name it too; here it becomes
        the round's own verdict, with the node's own conclusion quoted back
        and the decline path named."""
        if self.verdict_result.get("verdict") != "pass":
            return None
        from utk_curio.backend.app.execution import runtime_journal as _journal

        produced = (self.verdict_result.get("evidence") or {}).get("output") or {}
        if not _journal.is_absent_output(produced):
            return None
        refusal = result_shape.absent_output_refusal(
            code=self.candidate,
            output_data_type=str(
                (self.verdict_result.get("evidence") or {}).get("outputDataType") or ""
            ),
            upstream_outputs=(self.extra_inputs or {}).get("upstreamOutputs"),
        )
        yield from self._record_failed_round("empty-result", refusal)
        self._carry(refusal)
        return CONTINUE

    def _empty_result_check(self):
        """dev/133: "it ran" is not "it worked". A node that produced a
        countable result with NO rows in it, out of inputs that had rows,
        destroyed the dataflow's data — the owner's `e72c7080` joined
        community-area numbers to census-tract ids, ran clean in 45 ms, and
        left the pool and the chart empty while the chat said solved. The
        check is silent whenever it cannot attribute the emptiness."""
        if self.verdict_result.get("verdict") != "pass" or self.result_summary_fn is None:
            return None
        artifact = ((self.verdict_result.get("evidence") or {}).get("output") or {}).get("path")
        summary = None
        if artifact:
            try:
                summary = self.result_summary_fn(artifact)
            except Exception:  # noqa: BLE001 — a shape we cannot read is not a failure
                summary = None
        upstream_rows = (self.extra_inputs or {}).get("upstreamOutputs")
        # dev/137 (dev/133's own F1): a result can be non-empty and still
        # contain nothing. A `how="left"` join on keys that cannot match
        # keeps its rows and fills the other side with nulls — the row
        # count passes, the field check passes (the column exists), and
        # every plot below is empty. An all-null column this node CREATED
        # is the same verdict as no rows at all.
        null_created = (
            result_shape.created_null_columns(summary, upstream_rows)
            if not result_shape.is_empty(summary) else []
        )
        if null_created and result_shape.inputs_had_rows(upstream_rows) is not False:
            refusal = result_shape.null_refusal_text(
                columns=null_created,
                summary=summary,
                upstream_outputs=upstream_rows,
            )
            yield from self._record_failed_round("empty-result", refusal)
            self._carry(refusal)
            return CONTINUE
        if result_shape.is_empty(summary) and (
            result_shape.inputs_had_rows(upstream_rows) is not False
        ):
            refusal = result_shape.refusal_text(
                summary=summary,
                upstream_outputs=upstream_rows,
                output_data_type=str(
                    (self.verdict_result.get("evidence") or {}).get("outputDataType") or ""
                ),
            )
            yield from self._record_failed_round("empty-result", refusal)
            self._carry(refusal)
            return CONTINUE
        return None

    # ── stage: the round's record and what the next one carries ─────────────

    def _record_round(self):
        verdict_result = self.verdict_result
        yield "round_verdict", {
            "round": self.rounds_used, "verdict": verdict_result["verdict"],
        }
        round_evidence = (verdict_result.get("evidence") or {})
        self.rounds_trace.append(
            f"round {self.rounds_used}: {verdict_result['verdict']}"
            + (
                # dev/127: the exception line, whole — this is the line that
                # reached the owner's chat as "round 2: execution-error — de".
                " — " + failure_text.summary(
                    round_evidence.get("stderrTail") or round_evidence.get("detail") or "",
                    code=self.candidate, limit=200,
                )
                if verdict_result["verdict"] != "pass"
                else f" — output {round_evidence.get('outputDataType') or '?'}"
            )
        )
        attempt = self._round_attempt(round_evidence)
        self.attempts.append(attempt)
        if verdict_result["verdict"] != "fail":
            self.stopped_by = "passed" if verdict_result["verdict"] == "pass" else (
                "infrastructure" if verdict_result["verdict"] == "infrastructure" else None
            )
            return BREAK
        if round_evidence.get("kind") == "precondition" or round_evidence.get("upstreamEmpty"):
            # dev/118: the runner refused the SLICE (bound, cycle), or an
            # upstream has no content yet — no correction of THIS content can
            # change that; one round says so.
            self.stopped_by = "blocker"
            return BREAK
        self.previous_attempt = self.candidate
        self.previous_error = round_evidence.get("stderrTail") or round_evidence.get("detail") or ""
        self.url_evidence = agents_rounds._correction_url_evidence(
            self.candidate, self.previous_error, self.grounding_ctx)
        if self.url_evidence:
            # The endpoint's real answer joins the trail the card shows, so a
            # key-gated API reads as such instead of as a JSON decode error.
            attempt["endpointEvidence"] = agents_rounds._url_evidence_summary(self.url_evidence)
        return None

    def _round_attempt(self, round_evidence: dict) -> dict:
        verdict = self.verdict_result["verdict"]
        attempt = {
            "round": self.rounds_used,
            "contentSha256": agents_rounds._content_sha(self.candidate),
            "verdict": verdict,
            "kind": round_evidence.get("kind"),
            "source": "current content" if self.use_current else "generated",
        }
        if round_evidence.get("detail"):
            attempt["detail"] = str(round_evidence["detail"])[:agents_budgets._ATTEMPT_DETAIL_CHARS]
        if round_evidence.get("stderrTail"):
            attempt["stderrTail"] = str(round_evidence["stderrTail"])[-agents_budgets._ATTEMPT_STDERR_CHARS:]
        if round_evidence.get("outputDataType"):
            attempt["outputDataType"] = round_evidence["outputDataType"]
        if round_evidence.get("durationMs") is not None:
            attempt["durationMs"] = round_evidence["durationMs"]
        if round_evidence.get("reusedNodes"):
            attempt["reusedNodes"] = list(round_evidence["reusedNodes"])[:12]
        if self.reuse_retried:
            attempt["reuseRetried"] = True
        if verdict != "pass":
            # dev/127: the code that ran and failed, ON the attempt — the
            # owner could not see any of it without opening another chat.
            attempt.update(agents_rounds._attempt_code_field(self.candidate))
        return attempt

    # ── source resolution (dev/126) and the outcome ─────────────────────────

    def _awaiting_source(self, state: dict, *, rounds: int, after: str | None,
                         stopped_by: str | None) -> dict:
        detail = str(state.get("detail") or "a source must be selected")
        return {
            "verdict": "awaiting-source",
            "evidence": {
                "kind": "awaiting-selection",
                "detail": detail[:2000],
                **({"after": after} if after is not None else {}),
                **({"remedy": {
                    "kind": "dataset-selection",
                    "attachmentId": state["attachmentId"],
                    "nodeId": self.node_id,
                }} if state.get("attachmentId") else {}),
            },
            "rounds": rounds,
            "candidate": "",
            "delegations": self.delegations,
            "roundsTrace": (
                [f"awaiting dataset selection — {detail[:160]}"] if stopped_by is None
                else self.rounds_trace
            ),
            "attempts": [] if stopped_by is None else self.attempts,
            **({"stoppedBy": stopped_by} if stopped_by is not None else {}),
        }

    def _resolve_source_first(self) -> dict | None:
        """dev/126: a data-loading node RESOLVES ITS SOURCE FIRST. Discovery is
        initiated by the runtime (never left to the model to think of), and a
        node whose source the user has not confirmed yet waits for them instead
        of ending in the old dead end — the content builder declining, or the
        gate refusing a filename it had to invent."""
        if not (self.is_data_loading and self.resolve_source is not None):
            return None
        try:
            source_state = self.resolve_source(self.node, self.grounding_ctx) or {}
        except Exception:  # noqa: BLE001
            log.warning("Source resolution failed for node %s", self.node_id, exc_info=True)
            source_state = {}
        if source_state.get("state") == "unresolved" and source_state.get("discovery"):
            # Discovery was initiated and produced nothing selectable: say so
            # in the trail and let the round proceed, so the node still ends
            # with ITS own evidence (a refusal naming the literal, or the
            # builder's own decline) rather than a promise of candidates.
            self.rounds_trace.append(
                f"discovery found no source — {str(source_state.get('detail'))[:160]}"
            )
        if source_state.get("state") == "awaiting":
            return self._awaiting_source(source_state, rounds=0, after=None, stopped_by=None)
        self.confirmed_source = source_state.get("confirmedSource")
        if source_state.get("detail"):
            self.rounds_trace.append(f"source: {str(source_state['detail'])[:160]}")
        return None

    def _finish(self) -> dict:
        final_evidence = (self.verdict_result or {}).get("evidence") or {}
        final_verdict = self.verdict_result["verdict"] if self.verdict_result else "fail"
        if (
            self.is_data_loading
            and self.resolve_source is not None
            and final_verdict == "fail"
            and final_evidence.get("kind") in ("ungrounded-source", "source-missing")
        ):
            # dev/126: the round itself proved the source is missing — the gate
            # refused the literal the builder wrote, or the builder declined and
            # named what it needs. THIS is where the old dead end was: a failure
            # whose remedy text asked the user to attach the Dataset Finder by
            # hand. Discovery is initiated on that evidence, the attempt trail is
            # kept (the user sees what was tried), and the node WAITS instead of
            # failing.
            try:
                post = self.resolve_source(self.node, self.grounding_ctx, stage="post") or {}
            except Exception:  # noqa: BLE001
                log.warning("Post-failure source resolution failed for node %s",
                            self.node_id, exc_info=True)
                post = {}
            if post.get("state") == "unresolved" and post.get("detail"):
                final_evidence = {**final_evidence,
                                  "discovery": str(post["detail"])[:600]}
                self.rounds_trace.append(
                    f"discovery found no source — {str(post['detail'])[:160]}"
                )
            if post.get("state") == "awaiting":
                detail = str(post.get("detail") or "a source must be selected")
                self.rounds_trace.append(f"awaiting dataset selection — {detail[:160]}")
                return self._awaiting_source(
                    post, rounds=self.rounds_used,
                    after=str(final_evidence.get("detail") or "")[:600], stopped_by="source",
                )
        return {
            "verdict": final_verdict,
            "evidence": final_evidence,
            "rounds": self.rounds_used,
            "candidate": self.candidate,
            "delegations": self.delegations,
            "roundsTrace": self.rounds_trace,
            "attempts": self.attempts,
            # dev/127: which bound ended the loop. Unset means the rounds ran out.
            "stoppedBy": self.stopped_by or "rounds",
        }
