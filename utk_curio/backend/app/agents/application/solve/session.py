"""The Solve session over a graph: reconcile, reopen failed renders, waves, passes until stop, blocker signatures, and the event stream (memos dev/118, dev/131).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import threading
import time
import time as _time
import uuid

from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application import source_grounding
from utk_curio.backend.app.agents.application import verify
from utk_curio.backend.app.agents.application.errors import AgentServiceError
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
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import batch as agents_batch
from utk_curio.backend.app.agents.application.turns import grounding as agents_grounding
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
    agents_acquire._settle_discovery_acquisitions(user_key, project_id)
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
    """The solve batch stream (dev/63 → dev/118 → dev/131): one
    :class:`solve.batch.SolveBatch` over *targets*, its events relayed. Kept a
    generator so the batch (and its grounding fallback) is built when the
    stream is first pulled, in the job thread, exactly as the closure was.
    Keyword names are the batch's public contract; see :mod:`solve.batch`."""
    batch = agents_batch.SolveBatch(
        user_key, project_id, attachment_id, config, targets, nodes_by_id, manifest, coord,
        session_id, solve_execution_id, stop,
        spec=spec, mode=mode, return_phase=return_phase, verify=verify,
        grounding_base=grounding_base, dataset_paths=dataset_paths, retry_of=retry_of,
        catalog_rows=catalog_rows, acting_user=acting_user,
    )
    yield from batch.events()


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
            else "upstream" if result.get("waitingOn") == "upstream"
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
