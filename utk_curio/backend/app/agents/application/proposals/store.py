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
from utk_curio.backend.app.collaboration import dataflow_docs


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
    # A landed plan: each ref the plan placed, with the node it is, which its
    # rows' Solve and Run read.
    if proposal.get("tool") == "dataflow.plan.write":
        summary["appliedRefs"] = list(proposal.get("appliedNodeIds") or {})
        summary["nodeIds"] = dict(proposal.get("appliedNodeIds") or {})
        # #662: which of the plan's scenarios are saved, when it has any.
        if proposal.get("scenarioStates"):
            summary["scenarioStates"] = dict(proposal["scenarioStates"])
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
    dataflow_docs.write(user_key, project_id, spec, dataflow_docs.person(user_key, "apply"))
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


def _plan_proposal_any(spec: dict, attachment_id: str, proposal_id: str):
    """The plan the attachment's agent landed, *proposal_id* (dev/71: its
    nodes' content work goes on after it lands): what Build & validate and
    the rows' Solve and Run work on. None when it holds another, or none."""
    record = attachments.get_attachment(spec, attachment_id)
    plan = (record or {}).get("planProposal")
    if isinstance(plan, dict) and plan.get("proposalId") == proposal_id:
        return plan
    return None


def _store_proposal(
    user_key: str,
    project_id: str,
    spec: dict,
    loop_ctx: dict,
    proposal: dict,
    part: dict,
) -> None:
    """Shared persistence of an install's proposal (dev/41 semantics + dev/90
    A16): a mint from a LATER reply supersedes every still-pending proposal
    in both places each lives (mirror/queue + transcript part), but siblings
    minted in the SAME reply form one jointly-pending sequence: the first
    keeps the active slot, the rest queue behind it, so each card's Apply
    points at a live proposal."""
    attachment_id = loop_ctx["attachment_id"]
    session_id = loop_ctx["session_id"]
    # The mint sequence identity: one id per run loop, created lazily at the
    # first mint.
    proposal["mintSequenceId"] = loop_ctx.setdefault("_mint_sequence_id", uuid.uuid4().hex)
    record = attachments.get_attachment(spec, attachment_id)
    actor = dataflow_docs.by_agent((record or {}).get("coord"), user_key, "proposal")
    attachments.reconcile_proposal_queue(spec, attachment_id)
    previous = attachments.get_active_proposal(spec, attachment_id)
    if previous is not None and previous.get("status") == "pending":
        if (
            record is not None
            and previous.get("mintSequenceId") == proposal["mintSequenceId"]
        ):
            # dev/90 A16: same-reply sibling — jointly pending, applied or
            # dismissed by id in any order, promoted on reconcile.
            record.setdefault("queuedProposals", []).append(proposal)
            dataflow_docs.write(user_key, project_id, spec, actor)
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
    attachments.set_active_proposal(spec, attachment_id, proposal)
    dataflow_docs.write(user_key, project_id, spec, actor)
