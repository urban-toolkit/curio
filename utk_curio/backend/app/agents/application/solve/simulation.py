"""Build & validate over a plan that landed: ordered actions, the stream, and cancel.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility. Sibling modules are reached
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
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import run_node as agents_run_node
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.collaboration import dataflow_docs


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
    action for the persisted state, or None when every node of the landed
    plan is approved.

    Per ref, in topological order: created/failed → validate (a failed ref
    validates again on resume: the pause happened when it FIRST failed);
    validated → approve (its code landed when it passed; approving records
    it); approved → next ref. The plan's nodes and connections landed with
    it, so nothing is created or connected here."""
    node_states = session.get("nodeStates") or {}
    for ref in _ordered_plan_refs(plan):
        state = node_states.get(ref, "created")
        if state in ("created", "failed"):
            return {"action": "validate", "ref": ref}
        if state == "validated":
            return {"action": "approve", "ref": ref}
        # "approved" → continue to the next ref.
    return None


def request_simulate_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Cancel a running simulation (dev/67-9): both dev/63 signals — the
    durable session flag plus the in-process event; the run stops at the next
    action boundary with everything already done persisted."""
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    if not session.get("simulatingSince"):
        raise AgentServiceError("no simulation is running for this attachment", 409)
    session["simulateCancelRequested"] = True
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "simulate"))
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
    """Build & validate (memo dev/67-9, DEC-054) over a plan that landed.

    ``step`` performs exactly the NEXT action and returns; ``auto`` chains
    the same actions, validate then approve, per node in topological order,
    PAUSING at the first failure with the reason (nothing downstream of a
    failure is written). Code that passes its check lands as the agent's
    change when it is validated. Every transition persists to
    ``builderSession`` BEFORE it is emitted, so a reload resumes exactly;
    resume = calling this endpoint again.
    """

    if mode not in ("step", "auto"):
        raise AgentServiceError("mode must be 'step' or 'auto'", 422)
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    session = record.get("builderSession") or {}
    plan_proposal_id = session.get("planProposalId")
    if not isinstance(plan_proposal_id, str):
        raise AgentServiceError("no plan to build: ask for a plan first", 409)
    proposal = agents_store._plan_proposal_any(spec, attachment_id, plan_proposal_id)
    if proposal is None:
        raise AgentServiceError("the plan is no longer available: nothing to build", 409)
    if _next_simulation_action(proposal.get("plan") or {}, proposal, session) is None:
        raise AgentServiceError(
            "the plan is complete: nothing to build", 409
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
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._agent_actor(user_key, spec, attachment_id, "simulate"))
    stop = threading.Event()
    _SIMULATE_CANCEL_EVENTS[simulate_execution_id] = stop
    return _simulate_events(
        user_key, project_id, attachment_id, config, plan_proposal_id,
        simulate_execution_id, mode, stop, exec_fn,
        coord=record.get("coord", ""), room_asker=agents_room.asker(),
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
    *,
    coord: str | None = None,
    room_asker: agents_room.Asker | None = None,
):
    """The driver body: read fresh state, one action, persist, emit,
    repeated in auto until completion, a pause, or cancellation. Each code
    that lands rides the stream as a ``change`` event, so a canvas no doc
    binds applies it live. The plan's agent (*coord*) is at work in the
    dataflow's room while it runs, asked by *room_asker*, and leaves before
    ``done``."""
    yield from SimulationDriver(
        user_key, project_id, attachment_id, config, plan_proposal_id, simulate_execution_id, mode, stop, exec_fn,
        coord=coord, room_asker=room_asker,
    ).events()


class SimulationDriver:
    """The Simulation Mode driver (dev/67-9) as an object (memo dev/142 B3, re-derived on this
    branch): fresh state, one action, persist, emit — repeated in auto until completion, a pause or
    cancellation. Each action is a named step; the loop in :meth:`events` only sequences them."""

    def __init__(self, user_key, project_id, attachment_id, config, plan_proposal_id,
                 simulate_execution_id, mode, stop, exec_fn, *, coord=None, room_asker=None):
        self.user_key = user_key
        self.project_id = project_id
        self.attachment_id = attachment_id
        self.config = config
        self.plan_proposal_id = plan_proposal_id
        self.simulate_execution_id = simulate_execution_id
        self.mode = mode
        self.stop = stop
        self.exec_fn = exec_fn
        # The plan's agent at work in the room (its coord) and who asked it.
        self.coord: str | None = coord
        self.room_asker: agents_room.Asker | None = room_asker

    # ── state ────────────────────────────────────────────────────────────────
    def _fresh(self):
        spec = agents_spec_reads._live_spec_or_404(self.user_key, self.project_id)
        record = agents_spec_reads._record_or_404(spec, self.attachment_id)
        session = record.get("builderSession") or {}
        # dev/71: the plan stays readable after its structure completes —
        # validate/approve actions continue on the applied plan.
        proposal = agents_store._plan_proposal_any(spec, self.attachment_id, self.plan_proposal_id)
        return spec, record, session, proposal

    def _write(self, spec) -> None:
        """Write *spec*, a fresh state this driver changed, as the attachment's agent."""
        dataflow_docs.write(
            self.user_key, self.project_id, spec,
            agents_spec_reads._agent_actor(self.user_key, spec, self.attachment_id, "simulate"),
        )

    def _write_session(self, mutate) -> dict:
        spec, record, session, _ = self._fresh()
        mutate(session)
        record["builderSession"] = session
        self._write(spec)
        return session

    def _pause(self, reason: dict) -> dict:
        """Persist a pause reason and answer the paused done payload."""

        def _mutate(session):
            session["pauseReason"] = reason
            session.pop("currentRef", None)

        session = self._write_session(_mutate)
        return {"status": "paused", "mode": self.mode, "reason": session["pauseReason"]}

    def _set_current(self, ref: str | None) -> None:
        def _mutate(session):
            if ref is None:
                session.pop("currentRef", None)
            else:
                session["currentRef"] = ref

        self._write_session(_mutate)

    def _cancelled(self) -> bool:
        if self.stop.is_set():
            return True
        _, _, session, _ = self._fresh()
        if session.get("simulateCancelRequested"):
            self.stop.set()
            return True
        return False

    def _completed(self) -> dict:
        return {"status": "completed", "mode": self.mode}

    # ── the loop ─────────────────────────────────────────────────────────────
    def events(self):
        # The plan's agent is in the room while Build & validate works, and
        # leaves before ``done``; each validation's run of it shares its peer.
        with agents_room.at_work(self.user_key, self.project_id, self.attachment_id,
                                 coord=self.coord, who=self.room_asker):
            done = yield from self._actions()
            _, _, final_session, _ = self._fresh()
            done["builderSession"] = final_session
        yield "done", done

    def _actions(self):
        """The actions, one at a time, until completion, a pause, a
        cancellation or the cap; returns the done payload."""
        done: dict = self._completed()
        try:
            yield "simulate_started", {
                "executionId": self.simulate_execution_id, "mode": self.mode,
            }
            for _ in range(agents_budgets._SIMULATE_MAX_ACTIONS):
                if self._cancelled():
                    done = {"status": "cancelled", "mode": self.mode}
                    break
                spec, record, session, proposal = self._fresh()
                if proposal is None:
                    done = self._completed()
                    break
                plan = proposal.get("plan") or {}
                action = _next_simulation_action(plan, proposal, session)
                if action is None:
                    done = self._completed()
                    break
                ref = action.get("ref")
                yield "stage", {**action, "label": agents_plans._plan_endpoint_label(ref, plan, {}) if ref else None}
                self._set_current(ref)
                stopped = yield from self._perform(action, ref)
                if stopped is not None:
                    done = stopped
                    break
                if self.mode == "step":
                    done = self._stepped()
                    break
            else:
                done = {"status": "paused", "mode": self.mode,
                        "reason": {"kind": "action-cap", "message": "action cap reached"}}
        finally:
            self._clear_in_flight()
        return done

    def _perform(self, action: dict, ref):
        """One action; a returned dict is the done payload that stops the loop."""
        kind = action["action"]
        if kind == "validate":
            return (yield from self._validate(ref))
        if kind == "approve":
            return (yield from self._approve(ref))
        return None

    def _stepped(self) -> dict:
        spec4, _, session4, proposal4 = self._fresh()
        next_action = (
            _next_simulation_action(
                (proposal4 or {}).get("plan") or {}, proposal4 or {}, session4
            )
            if proposal4 is not None  # dev/71: content work continues
            else None                  # on the completed structure
        )
        return {"status": "stepped", "mode": self.mode, "nextAction": next_action}

    def _clear_in_flight(self) -> None:
        _SIMULATE_CANCEL_EVENTS.pop(self.simulate_execution_id, None)
        try:
            spec, record, session, _ = self._fresh()
            session.pop("simulatingSince", None)
            session.pop("simulateExecutionId", None)
            session.pop("simulateCancelRequested", None)
            session.pop("currentRef", None)
            record["builderSession"] = session
            self._write(spec)
        except Exception:
            pass

    # ── the actions ──────────────────────────────────────────────────────────
    def _validate(self, ref):
        """Validate one node (``validate.py``): code that passes its check
        lands as the agent's change, and its ``change`` event rides this
        stream. A failure pauses the run: nothing downstream is written, and
        the attempts, each with its code, are in the node's agent chat."""
        validate_done: dict | None = None
        for kind, payload in agents_run_node._validate_node_inline(
            self.user_key, self.project_id, self.attachment_id, self.config, ref, self.exec_fn
        ):
            if kind == "done":
                validate_done = payload
            else:
                yield kind, payload
        verdict = (validate_done or {}).get("verdict", "fail")
        change_id = (validate_done or {}).get("changeId")
        if change_id:
            # Where the node's change lives (dev/72: with the node's agent).
            def _mutate(session2):
                session2.setdefault("nodeChanges", {})[ref] = {
                    "changeId": change_id,
                    "attachmentId": (validate_done or {}).get("changeAttachmentId") or self.attachment_id,
                }

            self._write_session(_mutate)
        yield "action_result", {
            "action": "validate", "ref": ref, "outcome": verdict,
            **({"changeId": change_id} if change_id else {}),
        }
        if verdict == "infrastructure":
            return self._pause({
                "kind": "infrastructure", "ref": ref,
                "message": (validate_done or {}).get("evidence", {}).get("detail")
                or "the sandbox is unreachable: retry when it is back",
            })
        if verdict == "fail":
            return self._pause({
                "kind": "validation-failed", "ref": ref,
                "message": "validation failed and nothing was written: each attempt's code is in the "
                "node's agent chat; edit the node or its inputs, then continue",
            })
        return None

    def _approve(self, ref):
        """Approve one validated node: its code landed when it passed, so
        approving records it, on its change (DEC-054: an approval is
        recorded, never silent) and in the plan's ledger."""
        _, _, session, _ = self._fresh()
        entry = (session.get("nodeChanges") or {}).get(ref) or {}
        change_attachment = entry.get("attachmentId") or self.attachment_id
        spec, _, _, _ = self._fresh()
        home = attachments.get_attachment(spec, change_attachment)
        for change in (home or {}).get("changes") or []:
            if isinstance(change, dict) and change.get("changeId") == entry.get("changeId"):
                change["approvedBy"] = "simulation-auto"
        record = attachments.get_attachment(spec, self.attachment_id)
        if record is not None:
            ledger = record.get("builderSession") or {}
            ledger.setdefault("nodeStates", {})[ref] = "approved"
            record["builderSession"] = ledger
        self._write(spec)
        yield "action_result", {"action": "approve", "ref": ref, "outcome": "approved"}
        return None
