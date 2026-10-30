"""Attachments as private agent instances in the project graph: list, attach, detach, intent/title edits, session read/clear, and the attachment card.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.attachments import AttachmentError
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import delegation as agents_delegation
from utk_curio.backend.app.agents.application import lifecycle as agents_lifecycle
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.turns import prompts as agents_prompts
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.collaboration import dataflow_docs


def _node_build_delegate(user_key: str, m) -> str | None:
    """The name of the agent *m* hands ``node.build`` to, as its manifest names
    it, or None when *m* builds nodes itself or hands that to no visible agent."""
    if m is None or content.NODE_BUILD_CAPABILITY in m.capability_ids:
        return None
    return agents_delegation.delegate_name(user_key, m, content.NODE_BUILD_CAPABILITY)


def _attachment_card(spec: dict, record: dict, user_key: str) -> dict:
    """Attachment record + a resolved name/hooks for its source template (best-effort).

    ``intent`` is the record's override when the user edited it, else the
    definition's instruction prompt bytes resolved at read time — so an
    unedited intent always reflects the actual prompt source (memo ``dev/19``;
    nothing duplicates prompt text into stored state).
    """
    coord = record.get("coord", "")
    m = agents_catalog._resolve_definition(user_key, coord)
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
        # dev/115: the running background job this process holds for the
        # attachment (Solve batch / per-node Solve), or null.
        "liveJob": agents_store._live_job_payload(user_key, record),
    }


def list_project_attachments(user_key: str, project_id: str) -> list[dict]:
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
    return [_attachment_card(spec, r, user_key) for r in records]


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
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = attachments.get_attachment(spec, attachment_id)
    removed = attachments.detach(spec, attachment_id)
    if removed:
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
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
    """The attachment's persisted transcript (empty for a session with no file)."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session_id = record.get("sessionId")
    turns = (
        sessions.read_turns(user_key, project_id, session_id)
        if isinstance(session_id, str)
        else []
    )
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": turns}


def clear_attachment_session(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Clear the transcript (keeps the attachment and its session id)."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session_id = record.get("sessionId")
    if isinstance(session_id, str):
        sessions.clear_turns(user_key, project_id, session_id, attachment_id)
    # An auto-generated title describes the conversation that was just cleared
    # — drop it so the next first message regenerates one. A manual title is
    # the user's deliberate name for the instance and is kept (memo dev/25).
    if record.get("title") and not record.get("titleEdited"):
        attachments.set_title(spec, attachment_id, None, edited=False)
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "attachment"))
    return {"attachmentId": attachment_id, "sessionId": session_id, "turns": []}
