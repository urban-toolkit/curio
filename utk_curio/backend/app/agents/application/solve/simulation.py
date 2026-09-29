"""Plan simulation: ordered actions, the stream, and cancel.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import threading
import time as _time
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import apply as agents_apply
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import run_node as agents_run_node
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.projects import storage as projects_storage


_SIMULATE_CANCEL_EVENTS: dict[str, object] = {}


def _ordered_plan_refs(plan: dict) -> list[str]:
    """Plan refs in topological order (mint's depth math), stable within a
    level by plan order — upstream validates before downstream generates."""
    depths = agents_plans._plan_depths(plan.get("nodes", []), plan.get("edges", []))
    return [
        n["ref"]
        for n in sorted(
            plan.get("nodes", []),
            key=lambda n: depths.get(n["ref"], 0),
        )
    ]


def _next_simulation_action(plan: dict, proposal: dict, session: dict) -> dict | None:
    """THE transition function (step and auto share it): the next single
    action for the persisted state, or None when the plan is complete.

    Per ref, in topological order: planned → create; created/failed →
    validate (a failed ref re-validates on resume — the pause happened when
    it FIRST failed); validated → approve (apply its content proposal);
    solving → pause (a content review outside the driver's own loop awaits);
    approved → next ref. All refs approved → connect (the edges stage; with
    zero edges it simply completes the proposal)."""
    node_states = session.get("nodeStates") or {}
    for ref in _ordered_plan_refs(plan):
        state = node_states.get(ref, "planned")
        if state == "planned":
            return {"action": "create", "ref": ref}
        if state in ("created", "failed"):
            return {"action": "validate", "ref": ref}
        if state == "validated":
            return {"action": "approve", "ref": ref}
        if state == "solving":
            return {"action": "await-review", "ref": ref}
        # "approved" → continue to the next ref.
    if proposal.get("status") == "pending":
        return {"action": "connect"}
    return None


def request_simulate_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Cancel a running simulation (dev/67-9): both dev/63 signals — the
    durable session flag plus the in-process event; the run stops at the next
    action boundary with everything already done persisted."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if not session.get("simulatingSince"):
        raise AgentServiceError("no simulation is running for this attachment", 409)
    session["simulateCancelRequested"] = True
    projects_storage.write_spec(user_key, project_id, spec)
    event = _SIMULATE_CANCEL_EVENTS.get(str(session.get("simulateExecutionId") or ""))
    if event is not None:
        event.set()  # type: ignore[attr-defined]
    return {"attachmentId": attachment_id, "cancelRequested": True}


def simulate_stream(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    *,
    mode: str = "step",
    exec_fn=None,
):
    """The Simulation Mode driver (memo dev/67-9, DEC-054).

    ``step`` performs exactly the NEXT action and returns; ``auto`` (the
    re-targeted Apply Plan) chains the same actions — create → validate →
    auto-approve on PASS — per node in topological order, then the connection
    stage, PAUSING on any failure with the reason and the pending review
    (nothing downstream of a failure is generated). Every transition persists
    to ``builderSession`` BEFORE it is emitted, so a reload resumes exactly;
    resume = calling this endpoint again.
    """

    if mode not in ("step", "auto"):
        raise AgentServiceError("mode must be 'step' or 'auto'", 422)
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    plan_proposal_id = session.get("planProposalId")
    if not isinstance(plan_proposal_id, str):
        raise AgentServiceError("no plan to simulate — ask for a plan first", 409)
    proposal = agents_store._plan_proposal_any(spec, attachment_id, plan_proposal_id)
    if proposal is None:
        raise AgentServiceError("the plan is no longer available — nothing to simulate", 409)
    if proposal.get("status") not in ("pending", "applied"):
        raise AgentServiceError(
            f"the plan is {proposal.get('status')!r} — nothing to simulate", 409
        )
    if _next_simulation_action(proposal.get("plan") or {}, proposal, session) is None:
        raise AgentServiceError(
            "the plan is complete — nothing to simulate", 409
        )
    now = _time.time()
    if session.get("simulatingSince") and now - float(session.get("simulatingSince") or 0) < agents_budgets._SIMULATE_STALE_SECONDS:
        raise AgentServiceError("a simulation is already running for this attachment", 409)
    agents_session._check_delegate_llms(
        user_key, project_id, agents_catalog._resolve_definition(user_key, record.get("coord", "")), config,
        agents_session._delegate_capabilities((proposal.get("plan") or {}).get("nodes") or []),
    )
    simulate_execution_id = uuid.uuid4().hex
    session["simulatingSince"] = now
    session["simulateExecutionId"] = simulate_execution_id
    session.pop("simulateCancelRequested", None)
    session.pop("pauseReason", None)
    record["builderSession"] = session
    projects_storage.write_spec(user_key, project_id, spec)
    stop = threading.Event()
    _SIMULATE_CANCEL_EVENTS[simulate_execution_id] = stop
    return _simulate_events(
        user_key, project_id, attachment_id, config, plan_proposal_id,
        simulate_execution_id, mode, stop, exec_fn,
    )


def _simulate_events(
    user_key: str,
    project_id: str,
    attachment_id: str,
    config: ProviderConfig,
    plan_proposal_id: str,
    simulate_execution_id: str,
    mode: str,
    stop,
    exec_fn,
):
    """The driver body: read fresh state → one action → persist → emit —
    repeated in auto until completion, a pause, or cancellation. Canvas
    mutations ride the stream (``node_created`` / ``node_content_applied`` /
    ``edges_created``) so the frontend applies them live."""

    def _fresh():
        spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        # dev/71: the plan stays readable after its structure completes —
        # validate/approve actions continue on the applied plan.
        proposal = agents_store._plan_proposal_any(spec, attachment_id, plan_proposal_id)
        return spec, record, session, proposal

    def _persist_pause(reason: dict):
        spec, record, session, _ = _fresh()
        session["pauseReason"] = reason
        session.pop("currentRef", None)
        record["builderSession"] = session
        projects_storage.write_spec(user_key, project_id, spec)
        return session

    def _set_current(ref: str | None):
        spec, record, session, _ = _fresh()
        if ref is None:
            session.pop("currentRef", None)
        else:
            session["currentRef"] = ref
        record["builderSession"] = session
        projects_storage.write_spec(user_key, project_id, spec)

    def _cancelled() -> bool:
        if stop.is_set():
            return True
        _, _, session, _ = _fresh()
        if session.get("simulateCancelRequested"):
            stop.set()
            return True
        return False

    done: dict = {"status": "completed", "mode": mode}
    try:
        yield "simulate_started", {
            "executionId": simulate_execution_id, "mode": mode,
        }
        for _ in range(agents_budgets._SIMULATE_MAX_ACTIONS):
            if _cancelled():
                done = {"status": "cancelled", "mode": mode}
                break
            spec, record, session, proposal = _fresh()
            if proposal is None:
                done = {"status": "completed", "mode": mode}
                break
            plan = proposal.get("plan") or {}
            action = _next_simulation_action(plan, proposal, session)
            if action is None:
                done = {"status": "completed", "mode": mode}
                break
            ref = action.get("ref")
            yield "stage", {**action, "label": agents_plans._plan_endpoint_label(ref, plan, {}) if ref else None}
            if action["action"] == "await-review":
                session = _persist_pause({
                    "kind": "content-review-pending", "ref": ref,
                    "message": "review the pending content proposal first, then continue",
                })
                done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                break
            _set_current(ref)
            if action["action"] == "create":
                result = agents_plans.apply_plan_node(
                    user_key, project_id, attachment_id, plan_proposal_id, ref
                )
                if result.get("createdNode"):
                    yield "node_created", {"createdNode": result["createdNode"]}
                if result.get("createdEdges"):
                    # dev/71: the progressive sweep connected what it could.
                    yield "edges_created", {"createdEdges": result["createdEdges"]}
                yield "action_result", {"action": "create", "ref": ref, "outcome": "created"}
            elif action["action"] == "validate":
                validate_done: dict | None = None
                for kind, payload in agents_run_node._validate_node_inline(
                    user_key, project_id, attachment_id, config, ref, exec_fn
                ):
                    if kind == "done":
                        validate_done = payload
                    else:
                        yield kind, payload
                verdict = (validate_done or {}).get("verdict", "fail")
                proposal_id = (validate_done or {}).get("proposalId")
                if proposal_id:
                    # The resume/apply linkage (67-6's deferred nodeProposals;
                    # dev/72: the proposal may live on the node's agent).
                    spec2, record2, session2, _ = _fresh()
                    session2.setdefault("nodeProposals", {})[ref] = {
                        "proposalId": proposal_id,
                        "attachmentId": (validate_done or {}).get("proposalAttachmentId")
                        or attachment_id,
                    }
                    record2["builderSession"] = session2
                    projects_storage.write_spec(user_key, project_id, spec2)
                yield "action_result", {
                    "action": "validate", "ref": ref, "outcome": verdict,
                    **({"proposalId": proposal_id} if proposal_id else {}),
                }
                if verdict == "infrastructure":
                    session = _persist_pause({
                        "kind": "infrastructure", "ref": ref,
                        "message": (validate_done or {}).get("evidence", {}).get("detail")
                        or "the sandbox is unreachable — retry when it is back",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
                if verdict == "fail":
                    session = _persist_pause({
                        "kind": "validation-failed", "ref": ref,
                        "proposalId": proposal_id,
                        "message": "validation failed — review the proposed content "
                        "(Apply anyway or edit), then continue",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
            elif action["action"] == "approve":
                _, _, session, _ = _fresh()
                entry = (session.get("nodeProposals") or {}).get(ref)
                # dev/72 shape {proposalId, attachmentId}; old string tolerated.
                if isinstance(entry, dict):
                    content_proposal_id = entry.get("proposalId")
                    proposal_attachment_id = entry.get("attachmentId") or attachment_id
                else:
                    content_proposal_id = entry
                    proposal_attachment_id = attachment_id
                if not content_proposal_id:
                    session = _persist_pause({
                        "kind": "content-review-pending", "ref": ref,
                        "message": "the validated proposal is not addressable — review it manually",
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
                apply_result = agents_apply.apply_proposal(
                    user_key, project_id, proposal_attachment_id, content_proposal_id
                )
                # DEC-054: auto-approval is recorded, never silent.
                spec3, _, _, _ = _fresh()
                approved = attachments.get_active_proposal(spec3, proposal_attachment_id)
                if approved is not None and approved.get("proposalId") == content_proposal_id:
                    approved["approvedBy"] = "simulation-auto"
                    projects_storage.write_spec(user_key, project_id, spec3)
                applied_content = apply_result.get("appliedContent")
                if applied_content:
                    yield "node_content_applied", applied_content
                yield "action_result", {"action": "approve", "ref": ref, "outcome": "approved"}
            elif action["action"] == "connect":
                edges_result = agents_plans.apply_plan_edges(
                    user_key, project_id, attachment_id, plan_proposal_id, None
                )
                if edges_result.get("createdEdges"):
                    yield "edges_created", {"createdEdges": edges_result["createdEdges"]}
                refused = {
                    idx: row for idx, row in (edges_result.get("results") or {}).items()
                    if row.get("status") == "refused"
                }
                yield "action_result", {
                    "action": "connect",
                    "outcome": "refused" if refused else "connected",
                    "refused": {i: r.get("reason") for i, r in refused.items()},
                }
                if refused:
                    session = _persist_pause({
                        "kind": "connection-refused",
                        "message": "; ".join(
                            f"{r.get('fromLabel')} → {r.get('toLabel')}: {r.get('reason')}"
                            for r in list(refused.values())[:3]
                        ),
                    })
                    done = {"status": "paused", "mode": mode, "reason": session["pauseReason"]}
                    break
            if mode == "step":
                spec4, _, session4, proposal4 = _fresh()
                next_action = (
                    _next_simulation_action(
                        (proposal4 or {}).get("plan") or {}, proposal4 or {}, session4
                    )
                    if proposal4 is not None  # dev/71: content work continues
                    else None                  # on the completed structure
                )
                done = {"status": "stepped", "mode": mode, "nextAction": next_action}
                break
        else:
            done = {"status": "paused", "mode": mode,
                    "reason": {"kind": "action-cap", "message": "action cap reached"}}
    finally:
        _SIMULATE_CANCEL_EVENTS.pop(simulate_execution_id, None)
        try:
            spec, record, session, _ = _fresh()
            session.pop("simulatingSince", None)
            session.pop("simulateExecutionId", None)
            session.pop("simulateCancelRequested", None)
            session.pop("currentRef", None)
            record["builderSession"] = session
            projects_storage.write_spec(user_key, project_id, spec)
        except Exception:
            pass
    _, _, final_session, _ = _fresh()
    done["builderSession"] = final_session
    yield "done", done
