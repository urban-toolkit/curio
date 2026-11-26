"""Attachments as private agent instances in the project graph: list, attach, detach, intent/title edits, session read/clear, and the attachment card.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.attachments import AttachmentError
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import delegation as agents_delegation
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import node_work as agents_node_work
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.solve import simulation as agents_simulation
from utk_curio.backend.app.agents.application.turns import prompts as agents_prompts
from utk_curio.backend.app.agents.application.turns import turn_jobs
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


def _node_build_delegate(user_key: str, m) -> str | None:
    """The name of the agent *m* hands ``node.build`` to, as its manifest names
    it, or None when *m* builds nodes itself or hands that to no visible agent."""
    if m is None or content.NODE_BUILD_CAPABILITY in m.capability_ids:
        return None
    return agents_delegation.delegate_name(user_key, m, content.NODE_BUILD_CAPABILITY)


def _solves_nodes(user_key: str, spec: dict, coord: str, m) -> bool:
    """Whether a node's Solve from the chat of the agent *m* (at *coord*)
    goes ahead on this dataflow: the check ``node_solve.solve_node_stream``
    makes before it refuses, that an agent installed here writes node content
    for it, over the agents installed once that Solve installed the agents
    *m* requires (``lifecycle._repair_required_closure``), which it does
    first when every one of them is visible. The listing installs nothing:
    it is a read, which a hosted guest's listing of an example makes too, and
    a repair writes the lockfile and a turn in the agent's chat. It answers
    as that Solve will find the dataflow. An answer that cannot be read, an
    installed agent's manifest that no longer parses among them, is no, and
    the reason is logged."""
    if m is None:
        return False
    try:
        installed = set(project_agents.project_agents(spec))
        required, missing = agents_delegation.required_closure(user_key, m)
        if not missing:
            installed.update(required)
        return agents_delegation.resolve_among(user_key, installed, m, "node.content.generate").outcome == "ok"
    except Exception:  # noqa: BLE001 - one agent's answer never fails the listing
        log.warning("Could not tell whether a node's Solve from %s goes ahead", coord, exc_info=True)
        return False


def _attachment_card(spec: dict, record: dict, user_key: str, *,
                     waits: dict | None = None, solves: dict | None = None) -> dict:
    """Attachment record + a resolved name/hooks for its source template (best-effort).

    ``intent`` is the record's override when the user edited it, else the
    definition's instruction prompt bytes resolved at read time — so an
    unedited intent always reflects the actual prompt source (memo ``dev/19``;
    nothing duplicates prompt text into stored state).

    A listing of many cards hands each the same *waits*
    (``dataset_resolution.waiting_on_user`` of *spec*) and *solves*, each
    agent's ``solvesNodes`` by its coord, filled as the listing meets it: both
    are read once per listing, not once per card.
    """
    coord = record.get("coord", "")
    m = agents_catalog._resolve_definition(user_key, coord)
    if waits is None:
        waits = agents_dataset_resolution.waiting_on_user(spec)
    if solves is None:
        solves = {}
    if coord not in solves:
        solves[coord] = _solves_nodes(user_key, spec, coord, m)
    return {
        "attachmentId": record.get("attachmentId"),
        "coord": coord,
        "target": record.get("target"),
        "sessionId": record.get("sessionId"),
        "revision": record.get("revision", 1),
        "name": m.name if m else coord,
        "category": m.category if m else None,
        # What the agent declares: the chat offers each of its features to any
        # agent that declares the capability behind it.
        "capabilities": list(m.capability_ids) if m else [],
        # The agent it hands a node to build to, by name: the candidates
        # card's hand-off names it.
        "nodeBuildDelegate": _node_build_delegate(user_key, m),
        "hooks": [t.kind for t in m.compatible_targets] if m else [],
        # The manifest's declared inputs (dev/38) — drives the client-side
        # grounded-context composer (memo dev/44).
        "reads": list(m.inputs_reads) if m else [],
        "intent": record.get("intent") or agents_prompts._resolve_instruction_text(user_key, coord),
        "intentEdited": bool(record.get("intent")),
        # Conversation title (memo dev/25): the custom portion only — the
        # client composes "<name>: <title>" at display time.
        "title": record.get("title") or None,
        "titleEdited": bool(record.get("titleEdited")),
        # An install's review mirror (memo dev/41): status card wiring only; the
        # transcript's proposal part remains the display record. dev/90 A16:
        # when the slot settled but a same-reply sibling is still pending in
        # the queue, the summary shows THAT one (read-only promote).
        "activeProposal": agents_store._proposal_summary(agents_store._effective_active_proposal(record)),
        # The plan the agent landed, whose nodes Build & validate and Solve fill.
        "planProposal": agents_store._proposal_summary(record.get("planProposal")),
        # The Dataflow Builder orchestration session (dev/52 DR-2) — drives
        # the phase-aware builder panel; absent for every other agent.
        "builderSession": record.get("builderSession"),
        # The server's word on what runs on that plan now (``node_work``): the
        # mode of its Build & validate, and its plan row's Solve, ``{ref,
        # nodeId}``. A tab trusts these and never its own clock: a build an
        # earlier start left, or one past its bound, runs no more.
        "buildRunning": agents_node_work.build_running(record.get("builderSession")),
        "validating": agents_node_work.row_solve_running(record.get("builderSession")),
        # dev/115: the running background job this process holds for the
        # attachment (Solve batch / per-node Solve), or null.
        "liveJob": agents_store._live_job_payload(user_key, record),
        # The nodes whose source this agent waits for the user to pick: a
        # Dataset Finder's own node, and the nodes whose candidates its chat
        # asked for. Empty when it waits for none.
        "waitsForYou": list(waits.get(record.get("attachmentId"), [])),
        # A Dataset Finder's record of its node's source, or null.
        "sourceRecord": (
            record.get(agents_dataset_resolution.RECORD_KEY)
            if isinstance(record.get(agents_dataset_resolution.RECORD_KEY), dict) else None
        ),
        # Whether a node's Solve from this agent's chat goes ahead.
        "solvesNodes": solves[coord],
    }


def list_project_attachments(user_key: str, project_id: str, *, writes: bool = True) -> list[dict]:
    """The dataflow's attachments, each as its card (:func:`_attachment_card`).

    The listing repairs what it finds, and writes it: an attachment whose node
    or connection is gone is taken off with its transcript, and a Solve session
    a process that is gone left ``solving`` reads interrupted. So it reads the
    dataflow as a writer does (``dataflow_docs.live``), which only the backend
    process that owns the dataflow may.

    Without *writes* it writes nothing. It reads the dataflow as any process
    reads one, its owner's log included (``dataflow_docs.read``), and lists
    what a repair would leave, each Solve session as it stands: a hosted
    guest's listing of an example before the guest's own copy of it is made
    (``agents/routes/common.py``'s ``Dataflow.writable``), on the process that
    copy belongs to, which does not own the example."""
    if not writes:
        spec = dataflow_docs.read(user_key, project_id)
        if spec is None:
            raise AgentServiceError(f"project {project_id!r} has no spec", 404)
        attachments.prune_orphaned_attachments(spec)
        return _cards(spec, attachments.list_attachments(spec), user_key)
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    # A node or a connection removed on a canvas bound to the dataflow's doc
    # takes its attachments with it here, and their transcripts (dev/32): no
    # tab saves the dataflow, whose save pruned them, and its canvas lists the
    # attachments again once the server has the removal.
    pruned = attachments.prune_orphaned_attachments(spec)
    if pruned:
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
        sessions.delete_sessions_of(user_key, project_id, pruned)
    records = attachments.list_attachments(spec)
    # dev/115 (DEC-021): a session left "solving" by a process that is gone is
    # reconciled to "interrupted" the first time anyone reads it.
    for record in records:
        agents_session._reconcile_solve_session(user_key, project_id, spec, record)
    return _cards(spec, records, user_key)


def _cards(spec: dict, records: list[dict], user_key: str) -> list[dict]:
    """Each of *records* as its card, who waits for the user read once and
    each agent's ``solvesNodes`` once, for every card that agent has."""
    waits = agents_dataset_resolution.waiting_on_user(spec)
    solves: dict[str, bool] = {}
    return [_attachment_card(spec, r, user_key, waits=waits, solves=solves) for r in records]


def attach_agent(user_key: str, project_id: str, coord: str, target: object) -> dict:
    """Attach an installed template to a target. Requires the template installed
    in this project (no auto-install), and a valid target."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    if coord not in project_agents.project_agents(spec):
        raise AgentServiceError(
            "install the agent in this project before attaching it", 400
        )
    # DEC-080 (dev/126): attaching is acting on this agent — complete its
    # declared closure before it can run.
    if agents_lifecycle._repair_required_closure(user_key, project_id, coord):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    # Enforce the agent's declared compatibility: a canvas-only agent can only
    # attach to the canvas, a node-only agent only to nodes, a dual-compatible
    # agent to either. (attachments.attach still validates the target exists.)
    manifest = agents_catalog._resolve_definition(user_key, coord)
    allowed = {t.kind for t in manifest.compatible_targets} if manifest else set()
    kind = target.get("kind") if isinstance(target, dict) else None
    if kind and allowed and kind not in allowed:
        raise AgentServiceError(
            f"this agent attaches to {', '.join(sorted(allowed))}, not {kind}", 400
        )
    # compatibleTargets[].requires (memo dev/50): a node target must be one of
    # what it declares, a template flag (``loadsDataset``) or a template-id
    # suffix. Empty requires = any node.
    if kind == "node" and manifest is not None:
        node_target = next(
            (t for t in manifest.compatible_targets if t.kind == "node"), None
        )
        if node_target is not None and node_target.requires:
            from utk_curio.backend.app.packages import service as packages_services

            target_id = target.get("targetId") if isinstance(target, dict) else None
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next(
                (n for n in nodes if isinstance(n, dict) and n.get("id") == target_id), None
            )
            node_type = str((node or {}).get("type") or "")
            templates = packages_services.roster_templates(user_key, project_id)
            # dev/126: ONE reading of the rule, the same predicate the plan
            # apply's automatic attach uses (attachments.node_target_matches).
            if not attachments.node_target_matches(manifest, node_type, templates):
                raise AgentServiceError(
                    "this agent attaches to "
                    f"{attachments.describe_node_requirements(node_target.requires, templates)}; "
                    f"that node is {node_type or 'untyped'}",
                    400,
                )
    try:
        record = attachments.attach(
            spec, coord, target, attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex
        )
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
    return _attachment_card(spec, record, user_key)


def detach_agent(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Take an attachment off the dataflow, with its transcript. A Dataset
    Finder's record of its node's source goes with it, so a plan that waited
    for that source waits no more (``simulation.follow_the_sources``): its
    next pass asks a Finder again. Written under the spec lock, as every
    writer of a node's source writes."""
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = attachments.get_attachment(spec, attachment_id)
        removed = attachments.detach(spec, attachment_id)
        if removed:
            agents_simulation.follow_the_sources(user_key, spec)
            dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
    if removed:
        # A transcript lives exactly as long as its attachment (dev/20).
        sessions.delete_sessions_of(user_key, project_id, [record])
    return {"attachmentId": attachment_id, "detached": removed}


def update_attachment_intent(
    user_key: str, project_id: str, attachment_id: str, intent: str | None
) -> dict:
    """Set/clear the attachment's intent override; empty falls back to the prompt source."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    try:
        record = attachments.set_intent(spec, attachment_id, intent)
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
    return _attachment_card(spec, record, user_key)


def update_attachment_title(
    user_key: str, project_id: str, attachment_id: str, title: str
) -> dict:
    """Manually rename the conversation (memo dev/25). A manual title always
    wins over auto-generation and survives conversation clears."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    try:
        record = attachments.set_title(spec, attachment_id, title, edited=True)
    except AttachmentError as exc:
        raise AgentServiceError(str(exc), 400) from exc
    if record is None:
        raise AgentServiceError(f"attachment {attachment_id!r} not found", 404)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
    return _attachment_card(spec, record, user_key)


def get_attachment_session(user_key: str, project_id: str, attachment_id: str) -> dict:
    """The attachment's persisted transcript (empty for a session with no
    file), and its asks as they stand (``turn_jobs.asks_of``): the running
    turn's message and reply so far, then the asks waiting their turn. The
    asks are read first: a turn that ends meanwhile is in the transcript, and
    leaves the asks (by its execution id), so a tab never shows it twice or
    misses it."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    asks = turn_jobs.asks_of(user_key, project_id, attachment_id)
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str)
        else []
    )
    settled = {(turn.get("execution") or {}).get("executionId") for turn in turns if isinstance(turn, dict)}
    asks = [each for each in asks if not _settled_in(each, settled)]
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": turns, "asks": asks}


def _settled_in(asked: dict, settled: set) -> bool:
    """Whether the ask *asked* (its view) ended with an execution the
    transcript holds."""
    execution_id = next((event["data"].get("executionId") for event in asked.get("events") or []
                         if event.get("event") == "execution"), None)
    return execution_id is not None and execution_id in settled


def clear_attachment_session(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Clear the transcript (keeps the attachment and its session id).

    The candidates a chat held go with it: a chat that asked for them no
    longer waits for their pick, and a Dataset Finder's chat whose source
    still waited for the user leaves its node unresolved, so the next Solve
    asks the Finder again, and a plan that waited for it waits no more
    (``simulation.follow_the_sources``). The records are changed on the
    dataflow as it is now, under its spec lock, as every writer of a node's
    source changes them: a pick that lands meanwhile is kept."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.clear_turns(user_key, project_id, session_id, attachment_id)
    with projects_storage.spec_write_lock(user_key, project_id):
        fresh = agents_spec_reads._live_spec_or_404(user_key, project_id)
        fresh_record = agents_spec_reads._record_or_404(fresh, attachment_id)
        changed = bool(agents_dataset_resolution.forget_asker(fresh, attachment_id))
        if agents_dataset_resolution.forget_candidates(fresh, attachment_id):
            agents_simulation.follow_the_sources(user_key, fresh)
            changed = True
        # An auto-generated title describes the conversation that was just
        # cleared: drop it so the next first message regenerates one. A manual
        # title is the user's deliberate name for the instance and is kept
        # (memo dev/25).
        if fresh_record.get("title") and not fresh_record.get("titleEdited"):
            attachments.set_title(fresh, attachment_id, None, edited=False)
            changed = True
        if changed:
            dataflow_docs.write(user_key, project_id, fresh, agents_spec_reads._person(user_key, "attachment"))
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": []}
