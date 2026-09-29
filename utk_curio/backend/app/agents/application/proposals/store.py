"""Proposal records on the attachment: storing, summarizing, pending-plan lookups, stale marks, and the applied-turn log.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure import agent_jobs
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.projects import storage as projects_storage


def _effective_active_proposal(record: dict) -> dict | None:
    """dev/90 A16, read-only: the proposal the listing should surface — the
    active slot while it is pending, else the first still-pending same-reply
    sibling waiting in the queue (write-path promotion happens in
    ``attachments.reconcile_proposal_queue``)."""
    active = record.get("activeProposal")
    if isinstance(active, dict) and active.get("status") == "pending":
        return active
    queue = record.get("queuedProposals")
    if isinstance(queue, list):
        for queued in queue:
            if isinstance(queued, dict) and queued.get("status") == "pending":
                return queued
    return active if isinstance(active, dict) else None


def _proposal_summary(proposal: object) -> dict | None:
    if not isinstance(proposal, dict):
        return None
    summary = {
        "proposalId": proposal.get("proposalId"),
        "tool": proposal.get("tool"),
        "nodeId": proposal.get("nodeId"),
        "summary": proposal.get("summary"),
        "status": proposal.get("status"),
    }
    # dev/67-5: the per-node review state survives reloads through the mirror.
    if proposal.get("tool") == "dataflow.plan.write":
        summary["editedGoals"] = dict(proposal.get("editedGoals") or {})
        summary["appliedRefs"] = list(proposal.get("appliedRefs") or [])
        summary["edgeStates"] = dict(proposal.get("edgeStates") or {})
    return summary


def _live_job_payload(user_key: str, record: dict) -> dict | None:
    """dev/115: the attachment's running background job, if this process
    holds one — the dock's running indicator (docs/11:178)."""
    job = agent_jobs.live_job(user_key, str(record.get("attachmentId") or ""))
    return job.to_payload() if job is not None else None


def _mark_stale(
    user_key: str,
    project_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
    message: str,
) -> AgentServiceError:
    """Shared apply-drift path: proposal → ``stale`` in both homes, 409 out."""
    proposal["status"] = "stale"
    projects_storage.write_spec(user_key, project_id, spec)
    if isinstance(session_id, str):
        sessions.update_proposal_status(user_key, project_id, session_id, proposal_id, "stale")
    return AgentServiceError(message, 409)


def _log_applied_turn(
    user_key: str,
    project_id: str,
    session_id: object,
    attachment_id: str,
    proposal_id: str,
    text: str,
    title: str,
    lines: list[str],
    *,
    extra_parts: list[dict] | None = None,
) -> None:
    """Mark applied + append the result-card turn (mutation_applied, dev/03:344).
    ``extra_parts`` (dev/105 A3, additive) ride the same turn after the result
    card — the follow-up proposal cards an apply queued, rendered below it."""
    if not isinstance(session_id, str):
        return
    sessions.update_proposal_status(user_key, project_id, session_id, proposal_id, "applied")
    sessions.append_turns(
        user_key,
        project_id,
        session_id,
        attachment_id,
        [
            sessions.make_turn(
                "agent",
                text,
                content=[{"type": "card", "kind": "result", "title": title, "lines": lines}]
                + list(extra_parts or []),
            )
        ],
    )


def _pending_plan_proposal(spec: dict, attachment_id: str, proposal_id: str) -> dict:
    """The dev/67-5 per-node review preamble: the attachment's active
    dataflow-plan proposal, pending, matching *proposal_id* — or the honest
    404/409."""
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if proposal is None or proposal.get("proposalId") != proposal_id:
        # dev/67-9: the plan may be PARKED while a content review occupies
        # the active slot — its stages stay addressable.
        record = attachments.get_attachment(spec, attachment_id)
        parked = (record or {}).get("planProposal")
        if isinstance(parked, dict) and parked.get("proposalId") == proposal_id:
            proposal = parked
        else:
            raise AgentServiceError(f"proposal {proposal_id!r} not found", 404)
    status = proposal.get("status")
    if status != "pending":
        raise AgentServiceError(
            f"this proposal is {status!r} and can no longer be worked on", 409
        )
    if proposal.get("tool") != "dataflow.plan.write":
        raise AgentServiceError("this proposal is not a dataflow plan", 409)
    return proposal


def _pending_plan_proposal_or_none(spec: dict, attachment_id: str, proposal_id: str):
    """The pending plan proposal (active or parked) or None — the driver's
    loop guard (completion is an outcome, not an error)."""
    try:
        return _pending_plan_proposal(spec, attachment_id, proposal_id)
    except AgentServiceError:
        return None


def _plan_proposal_any(spec: dict, attachment_id: str, proposal_id: str):
    """The plan proposal in ANY status (active or parked) — dev/71: the
    structure may complete (status applied) while content work continues;
    the driver and per-row lifecycle still need the plan."""
    proposal = attachments.get_active_proposal(spec, attachment_id)
    if isinstance(proposal, dict) and proposal.get("proposalId") == proposal_id:
        return proposal
    record = attachments.get_attachment(spec, attachment_id)
    parked = (record or {}).get("planProposal")
    if isinstance(parked, dict) and parked.get("proposalId") == proposal_id:
        return parked
    return None


def _store_proposal(
    user_key: str,
    project_id: str,
    spec: dict,
    loop_ctx: dict,
    proposal: dict,
    part: dict,
) -> None:
    """Shared proposal persistence (dev/41 semantics + dev/90 A16): a mint
    from a LATER reply supersedes every still-pending proposal in both places
    each lives (mirror/queue + transcript part) — but siblings minted in the
    SAME reply form one jointly-pending sequence: the first keeps the active
    slot, the rest queue behind it. Without the queue, a reply proposing a
    question note then an answer note silently killed the question — its
    card kept a live Apply button pointing at a dead proposal (the same-turn
    part was not yet persisted, so the supersede status never landed)."""
    attachment_id = loop_ctx["attachment_id"]
    session_id = loop_ctx["session_id"]
    # The mint sequence identity: one id per run loop, created lazily at the
    # first mint — solve/simulate children each carry their OWN loop_ctx, so
    # their one-at-a-time supersession (dev/67-9) is untouched.
    proposal["mintSequenceId"] = loop_ctx.setdefault("_mint_sequence_id", uuid.uuid4().hex)
    record = attachments.get_attachment(spec, attachment_id)
    attachments.reconcile_proposal_queue(spec, attachment_id)
    previous = attachments.get_active_proposal(spec, attachment_id)
    if previous is not None and previous.get("status") == "pending":
        if (
            previous.get("tool") == "dataflow.plan.write"
            and proposal.get("tool") != "dataflow.plan.write"
            and record is not None
        ):
            # dev/67-9: the plan PARKS while per-node content reviews occupy
            # the active slot — its per-node/edge stages stay addressable
            # (_pending_plan_proposal falls back to the parked slot); it is
            # never silently superseded by its own sequence.
            record["planProposal"] = previous
        elif (
            record is not None
            and previous.get("mintSequenceId") == proposal["mintSequenceId"]
        ):
            # dev/90 A16: same-reply sibling — jointly pending, applied or
            # dismissed by id in any order, promoted on reconcile.
            record.setdefault("queuedProposals", []).append(proposal)
            projects_storage.write_spec(user_key, project_id, spec)
            return
        else:
            sessions.update_proposal_status(
                user_key, project_id, session_id, previous.get("proposalId", ""), "superseded"
            )
            # A later reply supersedes the WHOLE previous sequence, queued
            # siblings included — their parts are persisted by now.
            for queued in attachments.get_queued_proposals(spec, attachment_id):
                if queued.get("status") == "pending":
                    queued["status"] = "superseded"
                    sessions.update_proposal_status(
                        user_key, project_id, session_id,
                        queued.get("proposalId", ""), "superseded",
                    )
            if record is not None:
                record.pop("queuedProposals", None)
    if proposal.get("tool") == "dataflow.plan.write" and record is not None:
        record.pop("planProposal", None)  # a new plan replaces any parked one
    attachments.set_active_proposal(spec, attachment_id, proposal)
    projects_storage.write_spec(user_key, project_id, spec)
