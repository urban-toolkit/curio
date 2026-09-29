"""The Solve session over a graph: reconcile, reopen failed renders, waves, passes until stop, blocker signatures, and the event stream (memos dev/118, dev/131).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import queue as _queue
import threading
import time
import time as _time
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import failure_text
from utk_curio.backend.app.agents.domain import node_context
from utk_curio.backend.app.agents.domain import upstream_schema
from utk_curio.backend.app.agents.domain.manifest import AgentManifest
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.infrastructure import provider_config
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import acquire as agents_acquire
from utk_curio.backend.app.agents.application.proposals import mint as agents_mint
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import rounds as agents_rounds
from utk_curio.backend.app.agents.application.turns import delegates as agents_delegates
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
from utk_curio.backend.app.agents.application.turns import policy as agents_policy
from utk_curio.backend.app.agents.application.turns import roster as agents_roster
from utk_curio.backend.app.agents.domain import upstream_schema as agents_upstream_schema
from utk_curio.backend.app.execution import workflow_spec
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


def _reconcile_solve_session(user_key: str, project_id: str, spec: dict, record: dict) -> bool:
    """dev/115 (DEC-021, single-process): a builder session left ``solving``
    by an execution this process does not hold becomes ``interrupted`` — the
    transcript says so once, nothing is re-run, and the caller's *spec* is
    persisted when anything changed. Runs wherever a builder session is read
    for action (attachment listing, Solve, cancel)."""
    session = record.get("builderSession")
    if not isinstance(session, dict):
        return False
    before = session.get("solveExecutionId")
    if not agent_jobs.reconcile_builder_session(session):
        return False
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        try:
            pending = sum(
                1 for status in (session.get("nodeRuns") or {}).values()
                if status in ("pending", "failed")
            )
            sessions.append_turns(
                user_key, project_id, session_id, record.get("attachmentId"),
                [sessions.make_turn(
                    "agent",
                    "Solve was interrupted — the server stopped while it was running. "
                    "Nothing was replayed; finished nodes kept their content. "
                    f"{pending} node{'s' if pending != 1 else ''} still need solving — Retry continues.",
                    content=[{
                        "type": "card", "kind": "error", "title": "Solve interrupted",
                        "lines": [
                            f"execution {str(before or '')[:8]} expired with the process",
                            "Retry starts a new execution linked to it (DEC-021: never a replay)",
                        ],
                    }],
                )],
            )
        except Exception:
            pass
    return True


# In-flight cancellation (dev/63): solve executionId → stop event. The
# in-process fast path; the persisted ``cancelRequested`` session flag is the
# durable signal (other workers, a lost registry entry).
_SOLVE_CANCEL_EVENTS: dict[str, object] = {}


def _is_data_loading_node(node: object) -> bool:
    from utk_curio.backend.app.packages import service as _pkg_services

    return source_grounding.is_data_loading_type(
        _pkg_services.canonical_template_id((node or {}).get("type") if isinstance(node, dict) else None)
    )


def _delegate_capabilities(nodes) -> list[str]:
    """What a content run always delegates: the content, and discovery when a
    data-loading node may need a source."""
    capabilities = ["node.content.generate"]
    if any(_is_data_loading_node(node) for node in nodes):
        capabilities.append("dataset.discover")
    return capabilities


def _check_delegate_llms(user_key: str, project_id: str, manifest, config: ProviderConfig,
                         capabilities: list[str]) -> None:
    """Resolve the LLM configuration of each delegate a run always relies on,
    BEFORE anything is written, so a broken choice in AI Settings refuses the
    run once, with its remedy, instead of failing every node. Raises
    ``ProviderConfigError``. A delegate that does not resolve at all is left
    to the run, which reports a missing specialist its own way."""
    if manifest is None:
        return
    for capability in capabilities:
        resolution = delegation.resolve(user_key, project_id, manifest, capability)
        if resolution.outcome == "ok" and resolution.coord:
            provider_config.resolve_llm(user_key, resolution.coord.split("@", 1)[0], caller=config)


def solve_attachment(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    node_ids: list[str] | None = None,
    verify: bool = True,
) -> dict:
    """The dev/52 Solve batch (DEC-048), blocking form: drains the streaming
    batch (dev/63 — one implementation) and returns its terminal payload,
    minus the stream-only keys, so the response is byte-compatible. Always
    write mode — propose mode (dev/67-6) is the streaming route's.
    ``verify`` (dev/115): data-loading nodes execute before they are final."""
    payload: dict | None = None
    for kind, data in solve_attachment_stream(
        user_key, project_id, attachment_id, config, node_ids, verify=verify
    ):
        if kind == "done":
            payload = dict(data)
    if payload is None:  # the stream ended without a terminal event — loud
        raise AgentServiceError("solve ended without a result", 500)
    payload.pop("cancelled", None)
    payload.pop("notAttempted", None)
    payload.pop("mode", None)
    return payload


def request_solve_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """User-initiated solve cancellation (dev/63, the DEC-021 user slice).

    Sets BOTH signals: the persisted ``cancelRequested`` flag (durable —
    honored by any worker at the next node boundary) and the in-process stop
    event (immediate). In-flight children are never aborted; undispatched
    targets revert to ``pending``. Idempotent while a solve runs; 409 when
    nothing is running.
    """
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    _reconcile_solve_session(user_key, project_id, spec, record)
    session = record.get("builderSession") or {}
    if session.get("phase") != "solving":
        raise AgentServiceError("no solve is running for this attachment", 409)
    session["cancelRequested"] = True
    projects_storage.write_spec(user_key, project_id, spec)
    event = _SOLVE_CANCEL_EVENTS.get(str(session.get("solveExecutionId") or ""))
    if event is not None:
        event.set()  # type: ignore[attr-defined]
    return {"attachmentId": attachment_id, "cancelRequested": True}


def solve_attachment_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    node_ids: list[str] | None = None,
    mode: str = "write",
    verify: bool = True,
):
    """The dev/52 Solve batch (DEC-048) as an event stream (dev/63): ONE
    explicit, authenticated user action authorizes filling the applied plan's
    pending nodes.

    The endpoint is the review: it is scoped to plan-created placeholder
    nodes (the builder session's ``nodeRuns``) and digest-guarded per node
    (only still-empty content is written — user edits are ``skipped``,
    never overwritten). Each node runs a depth-1 child under
    ``delegation.run_delegate`` with every dev/48 guarantee (own ledger pair
    under the child's policy, ``parentExecutionId``, failure isolation) —
    coordinated by a bounded worker pool. The endpoint itself consumes no
    quota; children reserve individually. Retry = the same endpoint with the
    failed subset.

    Validation is eager (409s stay JSON); the returned generator yields
    ``(kind, payload)``: ``solve_started`` → ``node_started`` /
    ``node_result`` per target → ``done``. The terminal state comes from ONE
    re-guarded spec write that also runs on client disconnect and
    cancellation — streamed events are transport, never truth.

    ``mode`` (dev/67-6): ``"write"`` — the classic DEC-048 batch, content
    written under the per-node digest guard; ``"propose"`` — each solved
    child MINTS a reviewed ``node.content.write`` proposal instead (the
    Simulation Mode solve stage): nothing is written, ``node_result`` carries
    the ``proposalId``, the node stays ``pending`` until the user applies,
    and the session returns to its pre-solve phase. The single-activeProposal
    model means a multi-node propose batch supersedes all but the last —
    the 67-9 sequence solves one node at a time by design.

    ``verify`` (dev/115, DEC-073): a data-loading node's content is not final
    until it has EXECUTED — the worker drives the one verified-content loop
    (generate → gate → run in the sandbox → correct with the traceback → run
    again, ≤2 corrections) and only code that passed is written (write mode)
    or minted (propose mode, with the validation block); exhaustion is
    ``failed`` with the attempt trail, a sandbox outage leaves the node
    ``pending`` with the reason. ``verify=False`` keeps the legacy path.
    """

    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    # DEC-080 (dev/126): Solve hard-invokes node.content.generate and, for a
    # data-loading node, dataset.discover — both required delegates, completed
    # before the batch resolves them.
    if agents_lifecycle._repair_required_closure(
        user_key, project_id, record.get("coord", ""), attachment_id=attachment_id
    ):
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
    _reconcile_solve_session(user_key, project_id, spec, record)
    session = record.get("builderSession") or {}
    if not session.get("appliedPlanId"):
        raise AgentServiceError("nothing to solve — apply a plan first", 409)
    now = _time.time()
    if session.get("phase") == "solving" and now - float(session.get("solvingSince") or 0) < agents_budgets._SOLVE_STALE_SECONDS:
        raise AgentServiceError("a solve is already running for this plan", 409)
    try:
        # dev/115: refuse BEFORE persisting any in-flight state.
        agent_jobs.check_can_start(user_key, attachment_id)
    except agent_jobs.JobRefused as exc:
        raise AgentServiceError(str(exc), exc.status)
    node_runs: dict = session.get("nodeRuns") or {}
    targets = [
        node_id
        for node_id, status in node_runs.items()
        if status in ("pending", "failed") and (node_ids is None or node_id in node_ids)
    ]
    if not targets:
        raise AgentServiceError("no pending or failed plan nodes to solve", 409)
    if mode not in ("write", "propose"):
        raise AgentServiceError("mode must be 'write' or 'propose'", 422)
    return_phase = session.get("phase")  # propose mode restores it (dev/67-6)
    nodes_by_id = {
        n.get("id"): n
        for n in (spec.get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict)
    }
    solve_execution_id = uuid.uuid4().hex
    # dev/115 (DEC-021): a Solve after an interruption is a NEW execution
    # linked to the expired one — recorded, never replayed.
    retry_of = session.pop("interruptedExecutionId", None) if session.get("phase") == "interrupted" else None
    session.pop("interruptedAt", None)
    manifest = agents_catalog._resolve_definition(user_key, record.get("coord", ""))
    _check_delegate_llms(
        user_key, project_id, manifest, config,
        _delegate_capabilities(nodes_by_id.get(node_id) for node_id in targets),
    )
    # The in-flight guard + cancellation identity persist before any provider
    # work; the cancel endpoint finds the run through ``solveExecutionId``.
    session["phase"] = "solving"
    session["solvingSince"] = now
    session["solveExecutionId"] = solve_execution_id
    session.pop("cancelRequested", None)
    projects_storage.write_spec(user_key, project_id, spec)
    stop = threading.Event()
    _SOLVE_CANCEL_EVENTS[solve_execution_id] = stop
    coord = record.get("coord", "")
    session_id = record.get("sessionId")
    # dev/115: everything that needs the REQUEST context is resolved here —
    # the job thread holds no ``g``: the batch's grounding base (catalog refs,
    # mission + plan texts) and the sandbox's dataset-path mapping.
    solve_ground = agents_grounding._solve_grounding_base(user_key, project_id, spec, nodes_by_id, targets)
    solve_dataset_paths = (
        agents_grounding._resolve_catalog_execution_paths(project_id, list(solve_ground.get("catalog_ids") or {}))
        if verify else {}
    )
    # dev/126: and the Data Catalog rows the discovery delegate is handed.
    agents_acquire._settle_lake_acquisitions(user_key, project_id)
    solve_catalog_rows = agents_grounding._catalog_rows_for_discovery(user_key, project_id)
    # dev/132 (closes dev/131 F4): the acting user, so a dataset that arrives
    # DURING the session can still be resolved to a sandbox path.
    solve_user = agents_spec_reads._acting_user()
    events = _solve_events(
        user_key, project_id, attachment_id, config, targets, nodes_by_id,
        manifest, coord, session_id, solve_execution_id, stop,
        spec=spec, mode=mode, return_phase=return_phase, verify=verify,
        grounding_base=solve_ground, dataset_paths=solve_dataset_paths,
        catalog_rows=solve_catalog_rows, acting_user=solve_user,
        retry_of=retry_of if isinstance(retry_of, str) else None,
    )
    # dev/115 (DEC-021, single-process slice): the batch runs as a detached
    # job — the request only SUBSCRIBES (replay + tail); a disconnect no
    # longer ends the Solve, and a reload re-attaches through the jobs stream.
    job = agent_jobs.start_job(
        user_key=user_key, project_id=project_id, attachment_id=attachment_id,
        kind="solve-batch", job_id=solve_execution_id, events=events,
        redact_values={"llm-api-key": config.api_key},
    )
    return agent_jobs.subscribe(job)


def _solve_events(
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
    """The solve batch body (dev/63). Workers report through a thread-safe
    queue — they never touch the response; the generator drains it between
    yields. ``_finish`` is the single idempotent persist + transcript card,
    reached from normal completion, cancellation, client disconnect
    (``GeneratorExit``), and unexpected errors alike."""
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, dict] = {}
    # dev/131 (owner correction): consecutive passes in which a node's every
    # failed attempt was a REPEAT — the builder handed back the code that
    # already failed. Retrying that is not persistence, it is a spin, so a
    # node is dropped from later passes once it stalls this way (below).
    weak_passes: dict[str, int] = {}
    applied_contents: list[dict] = []
    # dev/127: one bounded artifact preview per artifact per batch, turned into
    # the columns and dtypes its frame holds. A node that had to join two
    # frames used to be told only their TYPE and spent its whole budget
    # guessing a join key (memo dev/127 §1 D5).
    schema_cache: dict[str, dict | None] = {}

    def _schema_of_artifact(artifact_id: str) -> dict | None:
        if artifact_id in schema_cache:
            return schema_cache[artifact_id]
        from utk_curio.backend.app.execution import runner as _runner

        summary = None
        try:
            preview = _runner.load_artifact_preview(artifact_id)
            summary = agents_upstream_schema.summarize(preview) if preview else None
        except Exception:  # noqa: BLE001
            log.warning("Could not describe artifact %s", artifact_id, exc_info=True)
        schema_cache[artifact_id] = summary
        return summary
    delegations: list = []
    unstarted: list[str] = []
    started = time.monotonic()
    state = {"finished": False}
    payload_out: dict = {}
    # dev/106: a batch-level reason (the missing-specialist case) and the
    # proposal parts minted for it — the Solve turn carries them, so the
    # reviewed install is visible where the failure is, not only in the
    # attachment mirror.
    batch_reason: str | None = None
    extra_parts: list[dict] = []
    # dev/118 (DEC-075): waves. The spec the loop and the context composer see
    # is re-read after every wave's persist, so a downstream target executes
    # against the upstream content that actually ran; the outputs recorded for
    # passing upstream targets are handed to their dependents' corrections.
    current: dict = {"spec": spec, "wave": 0}
    wave_outputs: dict[str, dict] = {}
    persisted: set[str] = set()
    # dev/118: the batch's time budget (§3.6) — a bound, never a failure.
    deadline_s = agents_budgets.solve_batch_deadline_s()
    # dev/131: the session's own budget — the owner's fifteen minutes. The
    # batch ceiling above stays the outer guard.
    session_deadline_s = agents_budgets.solve_session_deadline_s()
    session_wait_s = agents_budgets.solve_session_wait_s()
    deadline_reason = (
        f"the batch's time budget ({max(1, deadline_s // 60)} min) was spent — "
        "Retry continues from here"
    )

    def _flag_requested() -> bool:
        # The durable cancel signal, read lazily at node boundaries only.
        try:
            flag_spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
            flag_record = agents_spec_reads._record_or_404(flag_spec, attachment_id)
            return bool((flag_record.get("builderSession") or {}).get("cancelRequested"))
        except Exception:
            return False

    def _should_stop() -> bool:
        if stop.is_set():
            return True
        if _flag_requested():
            stop.set()
            return True
        return False

    # dev/114: ONE grounding base per batch (catalog paths, mission + plan
    # texts), built here in the request thread — workers hold no request
    # context; ONE egress budget for the batch's probes.
    # dev/115: the request thread resolved these (the generator body runs in
    # the job thread, which holds no request context); computing them here is
    # only the fallback for a direct caller.
    solve_ground = (
        grounding_base if grounding_base is not None
        else agents_grounding._solve_grounding_base(user_key, project_id, spec, nodes_by_id, targets)
    )
    solve_ctx: dict = {"granted": [], "manifest": manifest}
    solve_dataset_paths = (
        dataset_paths if dataset_paths is not None
        else (agents_grounding._resolve_catalog_execution_paths(project_id, list(solve_ground.get("catalog_ids") or {}))
              if verify else {})
    )
    from utk_curio.backend.app.packages import service as _pkg_services

    def _is_data_loading(node_obj: dict) -> bool:
        return source_grounding.is_data_loading_type(
            _pkg_services.canonical_template_id((node_obj or {}).get("type"))
        )

    batch_templates = agents_roster._roster_templates(user_key, project_id)  # dev/119: ONE snapshot per batch

    def _is_executable(node_obj: dict) -> bool:  # dev/118 (DEC-075) → dev/119 (DEC-076)
        return agents_roster._node_is_executable(node_obj, batch_templates)

    def _content_kind(node_obj: dict) -> str:  # dev/134
        return workflow_spec.content_kind(
            str((node_obj or {}).get("type") or ""), batch_templates
        )

    def _record_outcome(node_id: str, status: str, text, child) -> dict | None:
        # dev/131: a later pass must not ERASE an earlier pass's evidence. A
        # node that is still awaiting the user produces a fresh result with no
        # attempts (nothing was tried this pass), and overwriting the trail of
        # the pass that DID try left the user with a bare "pending". So the
        # record is merged: a result carrying attempts always wins; one without
        # them keeps the earlier trail and updates only the reason.
        previous = dict(results.get(node_id) or {})
        if previous.get("status") in ("solved", "proposed") and status != "verified":
            # dev/131: a session NEVER un-solves a node. A later pass exists to
            # pick up work that became possible, not to downgrade a node whose
            # content already landed (a slice bound or a cancellation arriving
            # after the fact must not rewrite "solved" into "skipped").
            return None
        event = _record_outcome_inner(node_id, status, text, child)
        fresh = results.get(node_id)
        if isinstance(fresh, dict) and fresh.get("attempts") and previous.get("attempts"):
            # dev/131 (owner correction): a session keeps attempting, and the
            # owner asked for ALL attempts to be visible — so a later pass
            # APPENDS its rounds to the trail instead of replacing it. And a
            # pass that only repeated itself must not bury the concrete error
            # the earlier pass found: the sentence stays the concrete one.
            this_pass_was_weak = agents_rounds._weak_failure(fresh)
            if fresh.get("status") == "failed" and this_pass_was_weak:
                weak_passes[node_id] = weak_passes.get(node_id, 0) + 1
            else:
                weak_passes.pop(node_id, None)
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
        if isinstance(fresh, dict) and not fresh.get("attempts") and previous.get("attempts"):
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
        return event

    def _record_outcome_inner(node_id: str, status: str, text, child) -> dict | None:
        nonlocal batch_reason
        if status == "no-content":
            # dev/134: nothing is owed and nothing was spent. Not "skipped"
            # (that means a bound refused it) and not "pending" (that means
            # work remains): the node is resolved, and the reason says why
            # there was never anything to write.
            node = nodes_by_id.get(node_id) or {}
            reason = (
                f"{node.get('type')} is wired, not written — this kind has no "
                "content to author; it renders or forwards its input"
            )
            result = {"status": "solved",
                      "verification": {"status": "no-content", "reason": reason[:300]}}
            results[node_id] = result
            return {"nodeId": node_id, "status": "solved", **result}
        if status == "deadline":
            # dev/118: the budget ran out before this node was dispatched — it
            # stays pending, says why, and the batch names the reason once.
            results[node_id] = {"status": "pending", "reason": deadline_reason}
            if node_id not in unstarted:
                unstarted.append(node_id)
            batch_reason = batch_reason or deadline_reason
            return {"nodeId": node_id, "status": "pending", "reason": deadline_reason}
        """Fold one worker outcome into the batch state — no yields, so it is
        safe on the disconnect drain. Returns the node_result payload, or
        None for an unstarted (cancelled-before-dispatch) target, which stays
        ``pending`` — it was never attempted, so no new status enters the
        state machine."""
        if child is not None:
            delegations.append(child)
        if status == "verified":
            # dev/115 (DEC-073): the verified-content loop's outcome. Only
            # code that PASSED is written; exhaustion is failed with the
            # trail; a sandbox outage is pending with the reason — never a
            # content failure, never silently written.
            outcome = text
            for c in outcome.get("delegations") or []:
                if c is not None:
                    delegations.append(c)
            trail = {
                "verdict": outcome.get("verdict"),
                "rounds": outcome.get("rounds"),
                "attempts": outcome.get("attempts") or [],
                # dev/127: which bound ended the loop, all the way to the UI.
                "stoppedBy": outcome.get("stoppedBy"),
            }
            if outcome.get("verdict") == "pass":
                candidate = outcome.get("candidate") or ""
                results[node_id] = {"status": "solved", **trail}
                applied_contents.append({"nodeId": node_id, "content": candidate})
                wave_outputs[node_id] = {
                    "nodeId": node_id,
                    "goal": str((nodes_by_id.get(node_id) or {}).get("goal") or "")[:200],
                    "outputDataType": (outcome.get("evidence") or {}).get("outputDataType") or "",
                    "wave": current["wave"],
                    # dev/118 commit 4: the artifact a dependent's validation reuses.
                    "output": (outcome.get("evidence") or {}).get("output"),
                }
                return {"nodeId": node_id, "status": "solved", "content": candidate, **trail}
            evidence = outcome.get("evidence") or {}
            if outcome.get("verdict") == "not-executable" and (outcome.get("candidate") or "").strip():
                # dev/118 (DEC-075): a browser-rendered kind — SAID to be
                # unexecuted, never "verified". dev/129: and never written
                # unchecked — an authored document that nothing here can
                # validate stays OUT of the node.
                candidate = outcome.get("candidate") or ""
                if evidence.get("documentUnchecked") and not evidence.get("documentPassive"):
                    reason = (
                        "written nothing — " + str(evidence["documentUnchecked"])[:200]
                        + "; Play the dataflow to see whether it renders"
                    )[:300]
                    results[node_id] = {"status": "pending", "reason": reason, **trail}
                    return {"nodeId": node_id, "status": "pending", "reason": reason, **trail}
                verification = (
                    {"status": "document-valid",
                     "reason": f"{evidence['documentValidated']} document validated — not executed"}
                    if evidence.get("documentValidated") else
                    {"status": "not-executable", "reason": str(evidence.get("detail") or "")[:300]}
                )
                results[node_id] = {"status": "solved", "verification": verification, **trail}
                applied_contents.append({"nodeId": node_id, "content": candidate})
                return {"nodeId": node_id, "status": "solved", "content": candidate,
                        "verification": verification, **trail}
            if outcome.get("verdict") == "infrastructure":
                reason = (
                    "not verified — sandbox unreachable: "
                    + str(evidence.get("detail") or "")[:160]
                    + " — nothing was run or written; Retry when the sandbox is back"
                )[:300]
                results[node_id] = {"status": "pending", "reason": reason, **trail}
                return {"nodeId": node_id, "status": "pending", "error": reason, **trail}
            if outcome.get("verdict") == "awaiting-source":
                # dev/126: the node's source is with the USER now — the Dataset
                # Finder on this node proposed candidates (or said it found
                # none). Nothing was generated or written, so this is PENDING
                # with the reason, never a failure of content.
                reason = (
                    "awaiting your dataset selection — "
                    + str(evidence.get("detail") or "")[:240]
                )[:300]
                remedy = evidence.get("remedy") if isinstance(evidence.get("remedy"), dict) else None
                extra = {"remedy": remedy} if remedy else {}
                results[node_id] = {"status": "pending", "reason": reason, **trail, **extra}
                return {"nodeId": node_id, "status": "pending", "reason": reason,
                        **trail, **extra}
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
                reason = f"waiting — {raw_detail[:240]}" if raw_detail else "waiting — an upstream node has no content yet"
                results[node_id] = {"status": "pending", "reason": reason, **trail}
                return {"nodeId": node_id, "status": "pending", "reason": reason, **trail}
            if kind == "precondition":
                # dev/118 (DEC-075): the runner refused the SLICE (the 25-node
                # bound, a cycle) — a bound on validation, not a failure of the
                # content: skipped, with the bound named.
                reason = f"skipped — {raw_detail[:240]}" if raw_detail else "skipped — validation refused the slice"
                results[node_id] = {"status": "skipped", "reason": reason, **trail}
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
                agents_grounding._ungrounded_remedy(agents_rounds._dataset_finder_attachment_id(spec, node_id))
                if kind == "ungrounded-source" else
                agents_grounding._source_missing_remedy(remedy_payload)
                if kind == "source-missing" else ""
            )
            bound = agents_rounds._stopped_by_clause(outcome.get("stoppedBy"))
            err = (
                f"not fixed after {rounds} attempt{'s' if rounds != 1 else ''}{bound} — "
                f"{kind}: {detail[:200 - len(remedy)] if remedy else detail}{remedy}"
            )[:300]
            extra = {"remedy": remedy_payload} if remedy_payload else {}
            results[node_id] = {"status": "failed", "error": err, **trail, **extra}
            return {"nodeId": node_id, "status": "failed", "error": err, **trail, **extra}
        if status == "solved":
            # The child replies with response formatting around the code —
            # only the executable content is written (dev/57).
            text_out = content.extract_node_content(text)
            # dev/114 (DEC-072): the gate — a fabricated path or an
            # unverified URL never reaches the spec; the node fails LOUDLY
            # with the literal and the remedy named.
            node = nodes_by_id.get(node_id) or {}
            _verdict, refusal = agents_grounding._gate_generated_content(
                user_key, project_id, solve_ctx,
                code=text_out, engine="python", node_type=node.get("type"),
                base=solve_ground,
            )
            if refusal:
                err = (
                    "ungrounded source: " + refusal.split("Allowed sources:")[0]
                    .replace("source grounding refused — ", "").strip()
                )[:220] + agents_grounding._ungrounded_remedy(agents_rounds._dataset_finder_attachment_id(spec, node_id))
                results[node_id] = {"status": "failed", "error": err[:300]}
                return {"nodeId": node_id, "status": "failed", "error": err[:300]}
            result: dict = {"status": "solved"}
            if not _is_executable(node):
                # dev/118 (DEC-075): written like before, and SAID to be unexecuted.
                result["verification"] = {
                    "status": "not-executable",
                    "reason": f"{node.get('type')} has no code the sandbox could run — written, not executed",
                }
            results[node_id] = result
            applied_contents.append({"nodeId": node_id, "content": text_out})
            return {"nodeId": node_id, "status": "solved", "content": text_out, **(
                {"verification": result["verification"]} if "verification" in result else {}
            )}
        if status == "failed":
            err = (text or "")[:300]
            results[node_id] = {"status": "failed", "error": err}
            return {"nodeId": node_id, "status": "failed", "error": err}
        if status == "skipped":
            results[node_id] = {"status": "skipped"}
            return {"nodeId": node_id, "status": "skipped"}
        unstarted.append(node_id)
        return None

    def _apply_contents(spec_doc: dict) -> None:
        """Write every solved content not yet persisted into *spec_doc*,
        re-guarded against the CURRENT nodes (deleted → skipped; a user edit
        wins). Shared by the per-wave persist and the final one (dev/118)."""
        current_nodes = {
            n.get("id"): n
            for n in (spec_doc.get("dataflow") or {}).get("nodes") or []
            if isinstance(n, dict)
        }
        for item in applied_contents:
            if item["nodeId"] in persisted:
                continue
            persisted.add(item["nodeId"])
            node = current_nodes.get(item["nodeId"])
            if node is None:
                results[item["nodeId"]] = {"status": "skipped"}  # deleted meanwhile
                continue
            if (node.get("content") or "").strip():
                results[item["nodeId"]] = {"status": "skipped"}  # user edit wins
                continue
            node["content"] = item["content"]

    def _persist_wave(wave_ids: list[str]) -> None:
        """dev/118 (DEC-075): the wave boundary IS the persist — and the
        heartbeat. Under the spec lock: the wave's solved contents land (the
        same guards as the final write), its nodeRuns say what happened, and
        ``solvingSince`` is refreshed so the stale marker means "no wave
        completed for 15 minutes". A process that dies between waves leaves
        every persisted wave in place (DEC-021: nothing replayed; Retry
        continues). The re-read spec is what the next wave runs against."""
        with projects_storage.spec_write_lock(user_key, project_id):
            spec_doc = agents_spec_reads._read_spec_or_404(user_key, project_id)
            record = agents_spec_reads._record_or_404(spec_doc, attachment_id)
            session = record.get("builderSession") or {}
            _apply_contents(spec_doc)
            node_runs = session.get("nodeRuns") or {}
            for nid in wave_ids:
                outcome = results.get(nid)
                if outcome and nid in node_runs and outcome.get("status") in ("solved", "failed", "skipped"):
                    node_runs[nid] = outcome["status"]
            session["nodeRuns"] = node_runs
            if session.get("phase") == "solving":
                session["solvingSince"] = time.time()
            record["builderSession"] = session
            projects_storage.write_spec(user_key, project_id, spec_doc)
        current["spec"] = spec_doc

    def _finish() -> dict:
        # One batched spec write: contents (re-guarded against the CURRENT
        # spec under the read-modify-write), statuses, and the exit phase —
        # plus the transcript card. Idempotent: exactly one persist per batch.
        # dev/118: the LAST wave's persist — earlier waves already landed.
        if state["finished"]:
            return payload_out
        state["finished"] = True
        cancelled = stop.is_set()
        with projects_storage.spec_write_lock(user_key, project_id):
            spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
            record = agents_spec_reads._record_or_404(spec, attachment_id)
            session = record.get("builderSession") or {}
            node_runs = session.get("nodeRuns") or {}
            _apply_contents(spec)
            applied = [
                i for i in applied_contents if results.get(i["nodeId"], {}).get("status") == "solved"
            ]
            ids_to_ref = {
                nid: ref for ref, nid in (session.get("nodeIds") or {}).items()
            }
            node_states = session.get("nodeStates")
            for node_id, outcome in results.items():
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
            if mode == "propose" and return_phase not in (None, "", "solving"):
                # The propose batch resolved nothing — the session returns to the
                # phase the solve interrupted (typically "simulating").
                session["phase"] = return_phase
            else:
                session["phase"] = (
                    "ready"
                    if all(s not in ("pending", "failed") for s in node_runs.values())
                    else "applied"
                )
            record["builderSession"] = session
            projects_storage.write_spec(user_key, project_id, spec)
        solved = sum(1 for r in results.values() if r["status"] == "solved")
        proposed = sum(1 for r in results.values() if r["status"] == "proposed")
        if isinstance(session_id, str):
            lines: list[str] = []
            for node_id, outcome in list(results.items())[:10]:
                line = f"{node_id[:8]} · {outcome['status']}"
                if outcome.get("verdict"):
                    # dev/115: the verified loop's verdict and, on failure,
                    # the attempt trail — one line per round, bounded.
                    rounds = outcome.get("rounds") or 0
                    line += f" · {outcome['verdict']} after {rounds} round{'s' if rounds != 1 else ''}"
                if outcome.get("reason") and outcome["status"] in ("pending", "skipped"):
                    line += f" — {str(outcome['reason'])[:120]}"
                lines.append(line)
                if outcome.get("verdict") == "fail":
                    for attempt in (outcome.get("attempts") or [])[:3]:
                        why = agents_rounds._attempt_why(attempt, limit=160)
                        lines.append(f"  round {attempt.get('round')}: {attempt.get('kind')} — {why}")
                        if attempt.get("endpointEvidence"):
                            lines.append(f"    endpoint: {str(attempt['endpointEvidence'])[:200]}")
            lines = lines[:24]
            # dev/127: every attempt, in the transcript, per node that has a
            # trail — the card's lines cannot carry code, so the trail is its
            # own part. Bounded: the first _MAX_ATTEMPT_PARTS nodes, then a
            # line naming the rest (each still reachable from its own chat).
            attempt_parts: list = []
            trailed = [
                (nid, outcome) for nid, outcome in results.items()
                if (outcome or {}).get("attempts")
                and (outcome or {}).get("status") in ("failed", "pending", "skipped")
            ]
            for nid, outcome in trailed[:agents_budgets._MAX_ATTEMPT_PARTS]:
                node = nodes_by_id.get(nid) or {}
                part = agents_rounds._solve_attempts_part(
                    current.get("spec") or spec, nid,
                    str(node.get("goal") or nid)[:120], outcome,
                )
                if part is not None:
                    attempt_parts.append(part)
            if len(trailed) > agents_budgets._MAX_ATTEMPT_PARTS:
                lines.append(
                    f"{len(trailed) - agents_budgets._MAX_ATTEMPT_PARTS} more node(s) have attempt trails — "
                    "open each node's agent to read them"
                )
            if cancelled:
                lines.append(f"cancelled — {len(unstarted)} node(s) not attempted")
            if batch_reason:
                # ONE reason line for the batch (not six identical ones).
                lines.append(f"reason: {batch_reason}")
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [
                    sessions.make_turn(
                        "agent",
                        (
                            f"Proposed content for {proposed} of {len(targets)} plan nodes."
                            if mode == "propose"
                            else f"Solved {solved} of {len(targets)} plan nodes."
                        )
                        + (f" Cancelled — {len(unstarted)} not attempted." if cancelled else ""),
                        content=[{
                            "type": "card",
                            "kind": "result",
                            "title": f"Solve: {solved} of {len(targets)} nodes",
                            "lines": lines,
                        }, *attempt_parts, *extra_parts],
                        execution=agents_policy._execution_record(
                            solve_execution_id,
                            {"coord": coord, "provider": config.api_type,
                             "model": config.model, "tools": [], "intentEdited": False,
                             "llm": provider_config.llm_pin(config)},
                            {}, started, "ok", delegations=delegations,
                            retry_of=retry_of,
                        ),
                    )
                ],
            )
        payload_out.update({
            "attachmentId": attachment_id,
            "executionId": solve_execution_id,
            "results": results,
            "appliedContents": applied,
            "builderSession": session,
            "cancelled": cancelled,
            "notAttempted": sorted(unstarted),
            "mode": mode,
        })
        if batch_reason:
            payload_out["reason"] = batch_reason
        return payload_out

    # dev/131: session bookkeeping lives ABOVE the resolution branch, because
    # every exit — including "no specialist installed" — must still report how
    # the session ended.
    ended_by = "complete"
    pass_no = 0
    attempted_signature: dict[str, tuple] = {}
    try:
        yield "solve_started", {"executionId": solve_execution_id, "targets": list(targets)}
        resolution = delegation.resolve(
            user_key, project_id, manifest, "node.content.generate"
        ) if manifest is not None else delegation.Resolution("unresolvable")
        if resolution.outcome != "ok":
            # Missing specialist: ONE reviewed install proposal (not per node),
            # every target failed — the panel explains and Retry works after
            # the user applies the install (REQ-ORCH-001).
            if resolution.outcome == "not-installed":
                loop_ctx = {
                    "attachment_id": attachment_id,
                    "session_id": session_id,
                }
                specialist = resolution.manifest.name if resolution.manifest else resolution.coord
                status, text, part = agents_mint._mint_project_install(
                    user_key, project_id, loop_ctx,
                    resolution.coord,
                    specialist,
                    "node.content.generate",
                )
                if status == "proposed" and part is not None:
                    extra_parts.append(part)
                    reason = (
                        f"specialist not installed — {specialist} ({resolution.coord}) is not "
                        "installed in this project; an install proposal awaits review below — "
                        "Apply it, then Retry"
                    )
                else:
                    # dev/106: an unminted proposal is never claimed (the
                    # refusal text says what to do instead).
                    reason = f"specialist not installed — {text}"
            else:
                reason = "no installed agent declares node.content.generate"
            batch_reason = reason
            for node_id in targets:
                results[node_id] = {"status": "failed", "error": reason}
                yield "node_result", {"nodeId": node_id, "status": "failed", "error": reason}
            # dev/131: nothing a further pass could change — the missing
            # specialist is an install the USER applies, and the proposal for it
            # is already in the chat.
            ended_by = "blocked"
        else:
            goals = [
                str(nodes_by_id[t].get("goal") or "") for t in targets if t in nodes_by_id
            ]
            outcome_queue: _queue.Queue = _queue.Queue()

            def _solve_one(node_id: str) -> None:
                try:
                    if _should_stop():
                        outcome_queue.put((node_id, "unstarted", None, None))
                        return
                    if _batch_deadline_spent(started, deadline_s):
                        outcome_queue.put((node_id, "deadline", None, None))
                        return
                    outcome_queue.put((node_id, "started", None, None))
                    node = nodes_by_id.get(node_id)
                    if node is None:
                        outcome_queue.put((node_id, "skipped", None, None))
                        return
                    if (node.get("content") or "").strip():
                        # User content preserved.
                        outcome_queue.put((node_id, "skipped", None, None))
                        return
                    if _content_kind(node) == workflow_spec.CONTENT_KIND_NONE:
                        # dev/134: this kind authors NOTHING — it renders or
                        # forwards its input and everything it does comes from
                        # the wiring (a merge, a pool, a simple view, a spatial
                        # join). Asking a model for its content spends a call
                        # to produce something that can only be wrong: the
                        # owner's `e72c7080` wrote the reply "not controllable"
                        # into a merge-flow and a data-pool as their content.
                        outcome_queue.put((node_id, "no-content", None, None))
                        return
                    # dev/67-6: the ONE context composer — the child sees the
                    # node's neighborhood (goals, runtime status, datasets),
                    # not just its own intent.
                    wave_spec = current["spec"]
                    upstream_outputs = _upstream_outputs_for(
                        wave_spec, node_id, wave_outputs, schema_fn=_schema_of_artifact,
                    )
                    inputs = {
                        "nodeType": node.get("type"),
                        "intent": node.get("goal"),
                        "planSiblings": goals[:20],
                        "nodeContext": node_context.compose_node_context(
                            user_key, project_id, wave_spec, node_id
                        ),
                    }
                    if upstream_outputs:
                        # dev/118: what the nodes feeding this one actually
                        # produced when they ran — a type to write against.
                        inputs["upstreamOutputs"] = upstream_outputs
                    # dev/114: the seventh DEC-063 application — a data-
                    # loading child is HANDED its grounded sources.
                    from utk_curio.backend.app.packages import service as _pkg

                    if source_grounding.is_data_loading_type(
                        _pkg.canonical_template_id(node.get("type"))
                    ):
                        inputs["sourceGrounding"] = agents_grounding._source_grounding_inputs(
                            agents_grounding._grounding_context(
                                user_key, project_id, solve_ctx,
                                node_type=node.get("type"), base=solve_ground,
                                extra_texts=(str(node.get("goal") or ""),),
                            )
                        )
                    if verify and _content_kind(node) in (
                        workflow_spec.CONTENT_KIND_CODE,
                        workflow_spec.CONTENT_KIND_GRAMMAR,
                    ):
                        # dev/115 (DEC-073) → dev/118 (DEC-075): the ONE
                        # verified-content loop for EVERY executable kind —
                        # and, since dev/134, for every GRAMMAR kind too: the
                        # runner reports "not executable" for a document and
                        # dev/129's validator decides, so nothing unvalidated
                        # is written on any path. The batch used to route a
                        # Vega or AUTK node past this loop, which is how an
                        # invalid document and the sentence "not controllable"
                        # reached two nodes in the owner's `e72c7080`.
                        # every round traced at the node's home (dev/72), the
                        # loop's progress relayed as node_* events, the outcome
                        # folded by _record_outcome.
                        def _traced(delegate_inputs, _node_id=node_id):
                            st, tx, ch, _h = agents_delegates._run_delegate_traced(
                                user_key, project_id, resolution.coord,
                                "node.content.generate", delegate_inputs, config,
                                parent_execution_id=solve_execution_id,
                                parent_coord=coord,
                                attachment_id=attachment_id,
                                node_id=_node_id,
                                home_create=False,  # workers never write the spec
                            )
                            return st, tx, ch

                        # dev/129: errors from ANY execution feed the fix. A
                        # node that still holds the code a Play run raised on
                        # is repaired FROM that code — round 0 re-runs it and
                        # the correction works on the real traceback — instead
                        # of being regenerated as if nothing had happened.
                        recorded = None
                        try:
                            from utk_curio.backend.app.execution import runtime_journal

                            candidate_failure = runtime_journal.last_failure(
                                user_key, project_id, node_id
                            )
                            if runtime_journal.failure_matches(
                                candidate_failure, node.get("content")
                            ):
                                recorded = candidate_failure
                        except Exception:  # noqa: BLE001
                            recorded = None
                        # dev/131 (owner correction): on a later pass the error
                        # this node's last attempt produced is the input this
                        # one starts from — never the same blank inputs again.
                        # A recorded on-disk failure is the stronger evidence
                        # (it is the code actually ON the node), so it wins.
                        carry = (
                            None if recorded
                            else agents_rounds._carry_forward_error(results.get(node_id))
                        )
                        gen = agents_rounds._verified_content_rounds(
                            user_key, project_id,
                            spec=wave_spec, node=node, resolution=resolution, config=config,
                            start_from_current=bool(recorded),
                            recorded_failure=recorded,
                            carry_forward=carry,
                            parent_execution_id=solve_execution_id, parent_coord=coord,
                            attachment_id=attachment_id, exec_fn=None,
                            grounding_loop_ctx=solve_ctx, grounding_base=solve_ground,
                            extra_inputs={"planSiblings": goals[:20],
                                          **({"upstreamOutputs": upstream_outputs} if upstream_outputs else {})},
                            delegate_runner=_traced,
                            # dev/132 (closes dev/131 F4): the eager mapping,
                            # topped up for a dataset the user imported or
                            # installed since this session started.
                            dataset_paths_fn=lambda codes: agents_grounding._session_dataset_paths(
                                project_id, acting_user, solve_dataset_paths, codes
                            ),
                            # dev/133: the batch's memoized preview — one
                            # description per artifact, reused by the emptiness
                            # check and by the next node's input schema.
                            result_summary_fn=_schema_of_artifact,
                            exec_user_key=user_key,
                            secrets_fn=agents_grounding._exec_secrets_resolver(user_key),
                            prior_outputs_fn=lambda: {
                                nid: o["output"] for nid, o in wave_outputs.items() if o.get("output")
                            },
                            # dev/126: the batch resolves a data-loading node's
                            # source before generating for it.
                            resolve_source=agents_grounding._source_resolver(
                                user_key, project_id, coord=coord,
                                attachment_id=attachment_id,
                                execution_id=solve_execution_id, config=config,
                                manifest=manifest,
                                extra_texts=(str((spec.get("dataflow") or {}).get("task") or ""),),
                                catalog_rows=catalog_rows,
                            ),
                            # dev/131: this node may not outlive the session.
                            node_budget_s=max(
                                int(session_deadline_s - (time.monotonic() - started)), 1
                            ),
                        )
                        try:
                            while True:
                                kind, data = next(gen)
                                outcome_queue.put((node_id, "progress", {"kind": kind, **data}, None))
                        except StopIteration as stop_iter:
                            outcome_queue.put((node_id, "verified", stop_iter.value, None))
                        return
                    status, text, child, _home = agents_delegates._run_delegate_traced(
                        user_key, project_id, resolution.coord,
                        "node.content.generate", inputs, config,
                        parent_execution_id=solve_execution_id,
                        parent_coord=coord,
                        attachment_id=attachment_id,
                        node_id=node_id,
                        home_create=False,  # workers never write the spec
                    )
                    outcome_queue.put(
                        (node_id, "solved" if status == "ok" else "failed", text, child)
                    )
                except BaseException as exc:  # a lost item would deadlock the drain
                    outcome_queue.put((node_id, "failed", f"solve worker error: {exc}", None))

            # dev/131: SOLVE IS A SESSION. dev/118's pass — waves in
            # topological order, per-wave persist, honest reasons — is unchanged
            # inside; what changed is that it no longer ends the run. The
            # session keeps making passes while unresolved nodes remain, the
            # session budget is unspent and the user has not stopped, so a
            # blocker that clears later (a dataset the user confirms mid-run, an
            # upstream a later pass fills) is picked up instead of stranding the
            # dataflow (the owner's `224d23a2`: six solved, three left, exited
            # in thirteen seconds).
            while True:
                pass_no += 1
                if pass_no > agents_budgets._SOLVE_MAX_PASSES:
                    ended_by = "budget"
                    break
                if _should_stop():
                    ended_by = "stopped"
                    break
                if (time.monotonic() - started) >= session_deadline_s:
                    ended_by = "budget"
                    break
                if pass_no > 1 and _batch_deadline_spent(started, deadline_s):
                    # dev/118's outer ceiling: nothing would be dispatched, so
                    # another pass could only re-mark the same nodes. Only from
                    # the second pass on — the first pass IS dev/118's batch and
                    # keeps its own boundary checks, unchanged.
                    ended_by = "budget"
                    break
                # Re-read the spec every pass: a selection confirmed, a node
                # edited or content written since the last pass all count.
                try:
                    pass_spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
                except AgentServiceError:
                    pass_spec = current.get("spec") or spec
                record_now = attachments.get_attachment(pass_spec, attachment_id) or {}
                runs_now = (record_now.get("builderSession") or {}).get("nodeRuns") or {}
                unresolved = [
                    nid for nid in targets
                    if str(runs_now.get(nid, "pending")) in ("pending", "failed")
                    # dev/131 (owner correction): what THIS session already
                    # settled counts too. dev/118 persists a wave only at a
                    # wave boundary, so the pass's last wave lands in
                    # ``_finish``; reading the disk alone made a node this
                    # session had just solved look pending and re-solved it
                    # every pass.
                    and str((results.get(nid) or {}).get("status") or "pending")
                    in ("pending", "failed")
                ]
                if not unresolved:
                    ended_by = "complete"
                    break
                # dev/131: pass 1 attempts everything. A later pass attempts
                # every node that is NOT parked on the user — carrying the
                # error its last attempt produced, which is a different input
                # than the pass before had (owner correction: "it should carry
                # the currently error that is being given"). A node waiting on
                # a user action has no new input, so that one is attempted
                # again only when something that could unblock it changed.
                pass_targets = [
                    nid for nid in unresolved
                    if pass_no == 1
                    or (
                        not agents_rounds._awaits_user_action(results.get(nid))
                        and weak_passes.get(nid, 0) < agents_budgets._MAX_WEAK_PASSES
                    )
                    or attempted_signature.get(nid) != _blocker_signature(pass_spec, nid)
                ]
                if not pass_targets:
                    # Nothing can progress yet. The session STAYS ALIVE — the
                    # user may confirm a source or edit a node — and says what
                    # it is waiting for, checking again after a bounded,
                    # stop-aware pause.
                    if _should_stop():
                        ended_by = "stopped"
                        break
                    if (time.monotonic() - started) >= session_deadline_s:
                        ended_by = "budget"
                        break
                    yield "solve_waiting", {
                        "pass": pass_no,
                        "seconds": session_wait_s,
                        "waiting": _session_waiting_summary(results, unresolved),
                        "secondsLeft": max(
                            int(session_deadline_s - (time.monotonic() - started)), 0
                        ),
                    }
                    if _wait_for_stop(stop, session_wait_s):
                        ended_by = "stopped"
                        break
                    continue
                spec = pass_spec
                current["spec"] = pass_spec
                nodes_by_id = {
                    n.get("id"): n
                    for n in (pass_spec.get("dataflow") or {}).get("nodes") or []
                    if isinstance(n, dict)
                }
                waiting = _session_waiting_summary(results, pass_targets)
                yield "solve_pass", {
                    "pass": pass_no,
                    "targets": list(pass_targets),
                    "remaining": len(pass_targets),
                    "waiting": waiting,
                    "secondsLeft": max(int(session_deadline_s - (time.monotonic() - started)), 0),
                }

                pool = ThreadPoolExecutor(max_workers=agents_budgets._SOLVE_MAX_WORKERS)
                # dev/131 (owner correction): the waves are this PASS's targets
                # — a node parked on the user (or already solved) is not
                # re-dispatched, so its trail and its reason survive the pass
                # that could not touch it. Depth is recomputed over the pass's
                # own set: an upstream outside it either has content already or
                # is named as a blocker honestly, exactly as dev/118 intends.
                waves = _solve_waves(spec, list(pass_targets))
                try:
                    for wave_no, wave in enumerate(waves, 1):
                        current["wave"] = wave_no
                        if _should_stop():
                            # Cancelled between waves: nothing here was dispatched.
                            for nid in wave:
                                _record_outcome(nid, "unstarted", None, None)
                            continue
                        if _batch_deadline_spent(started, deadline_s):
                            # dev/118: out of time before this wave — its targets
                            # stay pending with the reason; Retry continues.
                            for nid in wave:
                                event = _record_outcome(nid, "deadline", None, None)
                                if event is not None:
                                    yield "node_result", event
                            continue
                        yield "solve_wave", {"wave": wave_no, "of": len(waves), "nodeIds": list(wave)}
                        for target in wave:
                            pool.submit(_solve_one, target)
                        remaining = len(wave)
                        while remaining:
                            node_id, status, text, child = outcome_queue.get()
                            if status == "started":
                                yield "node_started", {"nodeId": node_id}
                                continue
                            if status == "progress":
                                # dev/115: the verified loop's rounds, live — the strip
                                # shows "verifying" and each round's verdict.
                                progress = dict(text)
                                kind = progress.pop("kind", "")
                                event_name = _SOLVE_PROGRESS_EVENTS.get(kind)
                                if event_name:
                                    yield event_name, {"nodeId": node_id, **progress}
                                continue
                            remaining -= 1
                            if mode == "propose" and status == "verified":
                                # dev/115: an EXECUTED review — the validation block
                                # (verdict, rounds, attempts) rides the part, PASS or
                                # FAIL (dev/67-7's labeled choice); a sandbox outage
                                # mints nothing and the node stays pending.
                                outcome = text
                                for c in outcome.get("delegations") or []:
                                    if c is not None:
                                        delegations.append(c)
                                if outcome.get("verdict") == "infrastructure":
                                    event = _record_outcome(node_id, "verified", outcome, None)
                                    if event is not None:
                                        yield "node_result", event
                                    continue
                                validation_block = {
                                    "verdict": outcome.get("verdict"),
                                    "rounds": outcome.get("rounds"),
                                    "evidence": outcome.get("evidence") or {},
                                    "attempts": outcome.get("attempts") or [],
                                }
                                part, home_att, mint_text = agents_delegates._mint_content_review_from_delegate(
                                    user_key, project_id,
                                    node_id=node_id,
                                    generated_text=outcome.get("candidate") or "",
                                    parent_attachment_id=attachment_id,
                                    parent_session_id=session_id,
                                    local_turn=True,
                                    validation=validation_block,
                                    grounding_base=solve_ground,
                                )
                                if part is not None:
                                    results[node_id] = {
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
                                    results[node_id] = {"status": "failed", "error": mint_text[:300]}
                                    yield "node_result", {
                                        "nodeId": node_id, "status": "failed", "error": mint_text[:300],
                                    }
                                continue
                            if mode == "propose" and status == "solved":
                                # dev/67-6 (Simulation Mode: solve): nothing is
                                # written — the child's content mints a reviewed
                                # node.content.write proposal through the EXISTING
                                # machinery (digest-pinned against the current
                                # content). dev/72: the review lives with the node's
                                # agent when one exists (find-only — the drain never
                                # writes the spec beyond the mint's own write).
                                if child is not None:
                                    delegations.append(child)
                                # dev/114: the gate runs on the batch base BEFORE the
                                # mint so the node's failure names the source.
                                _pnode = nodes_by_id.get(node_id) or {}
                                _v, _refusal = agents_grounding._gate_generated_content(
                                    user_key, project_id, solve_ctx,
                                    code=content.extract_node_content(text), engine="python",
                                    node_type=_pnode.get("type"), base=solve_ground,
                                )
                                if _refusal:
                                    err = ("ungrounded source: " + _refusal.split("Allowed sources:")[0]
                                           .replace("source grounding refused — ", "").strip())[:220] + \
                                          agents_grounding._ungrounded_remedy(
                                              agents_rounds._dataset_finder_attachment_id(spec, node_id))
                                    results[node_id] = {"status": "failed", "error": err[:300]}
                                    yield "node_result", {"nodeId": node_id, "status": "failed", "error": err[:300]}
                                    continue
                                # dev/73: the shared content→review sequence (also the
                                # chat loops' — one mint policy, three callers).
                                part, home_att, mint_text = agents_delegates._mint_content_review_from_delegate(
                                    user_key, project_id,
                                    node_id=node_id,
                                    generated_text=text,
                                    parent_attachment_id=attachment_id,
                                    parent_session_id=session_id,
                                    local_turn=True,
                                )
                                if part is not None:
                                    results[node_id] = {
                                        "status": "proposed",
                                        "proposalId": part["proposalId"],
                                        "proposalAttachmentId": home_att,
                                    }
                                    node = nodes_by_id.get(node_id) or {}
                                    node_label = (node.get('goal') or node_id)[:60]
                                    if home_att != attachment_id and isinstance(session_id, str):
                                        sessions.append_turns(
                                            user_key, project_id, session_id, attachment_id,
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
                                    results[node_id] = {
                                        "status": "failed", "error": mint_text[:300]
                                    }
                                    yield "node_result", {
                                        "nodeId": node_id, "status": "failed",
                                        "error": mint_text[:300],
                                    }
                                continue
                            event = _record_outcome(node_id, status, text, child)
                            if event is not None:
                                yield "node_result", event
                        if wave_no < len(waves):
                            # dev/118: the wave boundary persists and heartbeats;
                            # the next wave runs against what actually landed.
                            _persist_wave(list(wave))
                except GeneratorExit:
                    # Client gone (dev/63): stop dispatch, let in-flight children
                    # finish, fold their results in WITHOUT yielding — the finally
                    # persist keeps everything that completed.
                    stop.set()
                    pool.shutdown(wait=True)
                    while not outcome_queue.empty():
                        node_id, status, text, child = outcome_queue.get_nowait()
                        if status != "started":
                            _record_outcome(node_id, status, text, child)
                    raise
                finally:
                    pool.shutdown(wait=True)
                # dev/131 (owner correction): the pass boundary persists what
                # the pass settled — including its LAST wave, which dev/118
                # deliberately left to ``_finish`` because a batch ended
                # there. A session does not end at a pass, so a pass that is
                # not the last must leave the same truth on disk.
                _persist_wave(list(pass_targets))
                # dev/131: the signature is taken AFTER the pass, from a fresh
                # spec — a node attempted once its upstream landed in the same
                # pass has already seen that content, so the next pass must not
                # count it as a change. Taking it before the pass made every
                # pass that solved anything trigger another one.
                try:
                    settled = agents_spec_reads._read_spec_or_404(user_key, project_id)
                except AgentServiceError:
                    settled = current.get("spec") or pass_spec
                for nid in pass_targets:
                    attempted_signature[nid] = _blocker_signature(settled, nid)


        payload = _finish()
        # dev/131: every session ends in exactly one of three ways, and says so.
        payload["endedBy"] = ended_by
        payload["passes"] = pass_no
        payload["waiting"] = _session_waiting_summary(
            results, [nid for nid, r in results.items() if (r or {}).get("status") in ("pending", "failed")]
        )
        yield "done", payload
    finally:
        _SOLVE_CANCEL_EVENTS.pop(solve_execution_id, None)
        _finish()


def _solve_waves(spec: dict | None, targets: list[str]) -> list[list[str]]:
    """dev/118 (DEC-075): the batch's topological waves over its OWN targets.
    Depth 0 = no target upstream (an upstream that is not a target already has
    content, or will be named as a blocker honestly); depth k = one more than
    the deepest target upstream. Data-flow edges only (Interaction edges carry
    selection state). Targets caught in a cycle land in one last wave — the
    runner refuses a cyclic slice by name. Order within a wave is the
    targets' own."""
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    targets = [t for t in targets if isinstance(t, str)]
    target_set = set(targets)
    try:
        wf = parse_workflow_dict(spec or {})
        upstream = {t: [u for u in wf.upstream_nodes(t) if u in target_set and u != t] for t in targets}
    except Exception:
        return [list(targets)] if targets else []
    depth: dict[str, int] = {}
    remaining = list(targets)
    while remaining:
        progressed = False
        for t in list(remaining):
            ups = upstream.get(t, [])
            if all(u in depth for u in ups):
                depth[t] = 1 + max((depth[u] for u in ups), default=-1)
                remaining.remove(t)
                progressed = True
        if not progressed:
            last = max(depth.values(), default=-1) + 1
            for t in remaining:
                depth[t] = last
            break
    return [[t for t in targets if depth[t] == d] for d in sorted(set(depth.values()))]


def _upstream_outputs_for(
    spec: dict | None,
    node_id: str,
    wave_outputs: dict,
    *,
    schema_fn=None,
) -> list[dict]:
    """What the nodes feeding this one actually produced (dev/118, dev/127).

    dev/118 listed the direct upstreams that had passed earlier in the batch —
    which skipped the case that mattered: a ``merge-flow`` is written but never
    executed (``DEC-075``), so it holds no output, so a node fed THROUGH one
    was handed an empty list and had to invent its inputs (memo dev/127 §1 D5,
    the owner's join that guessed ``community_area`` three times).

    So the walk goes THROUGH a node that produced nothing, into its own
    upstreams, in ``in_0…in_n`` order — which is the order the child will index
    as ``arg[0]``, ``arg[1]`` — and each row carries ``argIndex`` when it
    arrived that way. ``schema_fn`` (optional) turns a recorded artifact into
    the columns and dtypes it holds; an artifact it cannot describe leaves the
    row without a schema rather than with a guess.
    """
    if not wave_outputs:
        return []
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    try:
        graph = parse_workflow_dict(spec or {})
    except Exception:
        return []

    def _row(nid: str, arg_index: int | None) -> dict:
        record = wave_outputs[nid]
        row = {k: v for k, v in record.items() if k != "output"}
        if arg_index is not None:
            row["argIndex"] = arg_index
        if schema_fn is not None:
            artifact = (record.get("output") or {}).get("path")
            if artifact:
                try:
                    schema = schema_fn(artifact)
                except Exception:  # noqa: BLE001
                    schema = None
                if schema:
                    row["schema"] = schema
        return row

    def _walk(target: str, arg_index: int | None, depth: int) -> list[dict]:
        if depth > agents_budgets._UPSTREAM_WALK_MAX_DEPTH:
            return []
        try:
            ups = graph.upstream_nodes(target)
        except Exception:
            return []
        rows: list[dict] = []
        indexed = len(ups) > 1
        for index, up in enumerate(ups):
            slot = index if indexed else arg_index
            if up in wave_outputs:
                rows.append(_row(up, slot))
            else:
                # A node with no recorded output of its own (a merge, a pool,
                # or one that has not run): look through it, keeping the slot
                # order the child will index by.
                rows.extend(_walk(up, slot, depth + 1))
        return rows

    return _walk(node_id, None, 0)[:agents_budgets._UPSTREAM_ROWS_MAX]


_VANISHED_INPUT_MARKERS = (
    "could not be loaded", "not found", "no such file", "does not exist",
    "keyerror", "artifact", "outputs table", "no output",
)


def _looks_like_a_vanished_reused_input(result: dict | None) -> bool:
    """dev/118 commit 4: a failed round that ran with reused ancestor outputs,
    where the TARGET failed while loading its input — the artifact behind a
    reused record is gone, not the code wrong. Only when ancestors were
    actually reused; a failure with a named upstream blocker or of another
    shape is the candidate's own."""
    if not isinstance(result, dict) or result.get("verdict") != "fail":
        return False
    evidence = result.get("evidence") or {}
    if not evidence.get("reusedNodes") or evidence.get("kind") != "execution-error":
        return False
    text = str(evidence.get("stderrTail") or evidence.get("detail") or "").lower()
    return any(marker in text for marker in _VANISHED_INPUT_MARKERS)


def _wait_for_stop(stop, seconds: float) -> bool:
    """Sleep up to *seconds*, returning True the moment a stop is requested.

    ``stop`` is dev/63's in-process event; a durable cancel flag is checked by
    the caller's own ``_should_stop`` on the next pass. Waiting on the event
    rather than sleeping means Stop is felt immediately (memo dev/131 §6.5).
    """
    try:
        return bool(stop.wait(timeout=seconds))
    except Exception:  # noqa: BLE001 — a stop we cannot wait on is not a stop
        time.sleep(min(seconds, 1))
        return False


def _blocker_signature(spec: dict | None, node_id: str) -> tuple:
    """What would have to CHANGE for this node to be worth attempting again.

    dev/131: a session that keeps making passes must not re-burn provider calls
    on identical conditions — "consistently attempt to resolve" means keep
    watching and attempt whenever progress became possible, not attempt the
    same impossible thing in a loop. The signature is the node's own content,
    the content of everything upstream of it, and the state of its dataset
    selection; when none of those moved, a new attempt would ask the same
    question of the same model with the same inputs.
    """
    from utk_curio.backend.app.execution.workflow_spec import parse_workflow_dict

    dataflow = (spec or {}).get("dataflow") or {}
    nodes = {
        n.get("id"): str(n.get("content") or "")
        for n in dataflow.get("nodes") or []
        if isinstance(n, dict)
    }
    upstreams: list[str] = []
    try:
        graph = parse_workflow_dict(spec or {})
        frontier = [node_id]
        seen = set()
        while frontier:
            current_id = frontier.pop()
            for up in graph.upstream_nodes(current_id):
                if up in seen:
                    continue
                seen.add(up)
                upstreams.append(up)
                frontier.append(up)
    except Exception:  # noqa: BLE001
        upstreams = []
    record = agents_dataset_resolution.source_record(spec, node_id) or {}
    return (
        len(nodes.get(node_id) or ""),
        tuple(sorted((up, len(nodes.get(up) or "")) for up in upstreams)),
        str(record.get("status") or ""),
        len(record.get("picks") or []),
    )


def _session_waiting_summary(results: dict, targets: list) -> list[dict]:
    """What the session is blocked on, per node, for the strip's live line.

    dev/131: a node awaiting the USER (dev/126's dataset selection) is the case
    that used to end a run; naming it is how the user learns the session is
    waiting for them rather than stuck.
    """
    out: list[dict] = []
    for node_id in targets:
        result = results.get(node_id) or {}
        remedy = result.get("remedy") if isinstance(result.get("remedy"), dict) else None
        kind = (
            "dataset-selection" if (remedy or {}).get("kind") == "dataset-selection"
            else "upstream" if "waiting — upstream" in str(result.get("reason") or "")
            else "retry"
        )
        out.append({
            "nodeId": node_id,
            "kind": kind,
            "reason": str(result.get("reason") or result.get("error") or "")[:200],
            **({"attachmentId": (remedy or {}).get("attachmentId")} if remedy else {}),
        })
    return out[:12]


def _batch_deadline_spent(started: float, deadline_s: int) -> bool:
    """Whether a batch begun at monotonic *started* has used its budget —
    checked at every wave boundary and before every node dispatch."""
    return (time.monotonic() - started) >= deadline_s


def _artifact_summary_fn():
    """A memoized ``artifact id -> shape summary`` reader (dev/127's preview +
    dev/133's emptiness check), for a caller with no batch-wide cache."""
    cache: dict = {}

    def _summary(artifact_id: str) -> dict | None:
        if artifact_id in cache:
            return cache[artifact_id]
        from utk_curio.backend.app.execution import runner as _runner

        summary = None
        try:
            preview = _runner.load_artifact_preview(artifact_id)
            summary = upstream_schema.summarize(preview) if preview else None
        except Exception:  # noqa: BLE001
            log.warning("Could not describe artifact %s", artifact_id, exc_info=True)
        cache[artifact_id] = summary
        return summary

    return _summary


#: dev/115: the verified loop's progress, relayed on the Solve stream.
_SOLVE_PROGRESS_EVENTS = {
    "generation_round": "node_round",
    "node_executed": "node_executed",
    "round_verdict": "node_verdict",
}
