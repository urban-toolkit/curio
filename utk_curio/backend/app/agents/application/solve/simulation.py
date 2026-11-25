"""Build & validate over a plan that landed: ordered actions, the stream, and cancel.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import contextlib
import threading
import time as _time
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.infrastructure.providers import ProviderConfig
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import dataset_resolution as agents_dataset_resolution
from utk_curio.backend.app.agents.application import in_the_room as agents_room
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import plans as agents_plans
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.agents.application.solve import budgets as agents_budgets
from utk_curio.backend.app.agents.application.solve import run_node as agents_run_node
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.solve import validate as agents_validate
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


def _reading_from(plan: dict, refs) -> set[str]:
    """*refs* and every node of *plan* that reads from one of them, through
    the plan's connections."""
    edges = [(e.get("from"), e.get("to")) for e in plan.get("edges") or [] if isinstance(e, dict)]
    reached = set(refs)
    frontier = list(reached)
    while frontier:
        ref = frontier.pop()
        for start, end in edges:
            if start == ref and end not in reached:
                reached.add(end)
                frontier.append(end)
    return reached


def _next_simulation_action(plan: dict, proposal: dict, session: dict, waiting=()) -> dict | None:
    """THE transition function (step and auto share it): the next single
    action for the persisted state, or None when every node of the landed
    plan that can go on is approved.

    Per ref, in topological order: created/failed → validate (a failed ref
    validates again on resume: the pause happened when it FIRST failed);
    awaiting-source → validate, which asks no one while its source still
    waits for the user; validated → approve (its code landed when it passed;
    approving records it); approved → next ref. A ref of *waiting*, which
    the run found waiting for the user to pick its source, is passed over
    with every node that reads from it: every other node goes on. The plan's
    nodes and connections landed with it, so nothing is created or connected
    here."""
    node_states = session.get("nodeStates") or {}
    held = _reading_from(plan, waiting) if waiting else set()
    for ref in _ordered_plan_refs(plan):
        if ref in held:
            continue
        state = node_states.get(ref, "created")
        if state in ("created", "failed", agents_validate.AWAITING_SOURCE):
            return {"action": "validate", "ref": ref}
        if state == "validated":
            return {"action": "approve", "ref": ref}
        # "approved" → continue to the next ref.
    return None


def _names(labels: list[str]) -> str:
    """*labels* as a sentence names them: "A", "A and B", "A, B and C"."""
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def awaiting_source_reason(user_key: str, spec: dict, session: dict, plan: dict, refs) -> dict:
    """Why Build & validate paused: every node of *refs* waits for the user
    to pick its source in its Dataset Finder's chat, and no other node can go
    on. Each is named by its ref, its node and its Finder's attachment, and
    the message names them; the strip ends it with how to go on."""
    node_ids = session.get("nodeIds") or {}
    nodes, labels, finders = [], [], []
    for ref in refs:
        node_id = node_ids.get(ref)
        finder = agents_dataset_resolution.finder_attachment(spec, node_id, user_key=user_key) if node_id else None
        nodes.append({"ref": ref, "nodeId": node_id, "attachmentId": (finder or {}).get("attachmentId")})
        labels.append(agents_plans._plan_endpoint_label(ref, plan, {}))
        finders.append(agents_spec_reads._agent_name(user_key, str((finder or {}).get("coord") or "")))
    finder_name = (
        next((name for name in finders if name), None)
        or agents_spec_reads._shipped_name_declaring(agents_dataset_resolution.DISCOVER)
        or agents_dataset_resolution.DISCOVER
    )
    message = (
        f"{labels[0]} needs a source: its {finder_name}'s chat asks you for it" if len(labels) == 1
        else f"{_names(labels)} need a source: each one's {finder_name} chat asks you for it"
    )
    return {"kind": agents_validate.AWAITING_SOURCE, "nodes": nodes, "message": message}


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
    failure is written). A loader that waits for the user to pick its source
    is passed over with every node that reads from it, so each loader's
    Dataset Finder is asked in one pass, and the run pauses once, naming every
    such loader, when no other node can go on. Code that passes its check
    lands as the agent's change when it is validated. Every transition
    persists to ``builderSession`` BEFORE it is emitted, so a reload resumes
    exactly; resume = calling this endpoint again.
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
    if session.get("simulatingSince") and now - float(session.get("simulatingSince") or 0) < agents_budgets.SIMULATE_STALE_SECONDS:
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
        # The refs this run found waiting for the user to pick their source,
        # in the order it found them: passed over with what reads from them.
        self.waiting: list[str] = []

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

    def _waits_for_sources(self) -> dict:
        """Pause once, naming every node this run found waiting for its
        source, when no other node can go on."""
        spec, _, session, proposal = self._fresh()
        return self._pause(awaiting_source_reason(
            self.user_key, spec, session, (proposal or {}).get("plan") or {}, self.waiting,
        ))

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
        cancellation or the cap; returns the done payload. A node found still
        waiting for its source, which it already did when the run reached it,
        is passed over: that is no step's action."""
        done: dict = self._completed()
        try:
            yield "simulate_started", {
                "executionId": self.simulate_execution_id, "mode": self.mode,
            }
            for _ in range(agents_budgets.SIMULATE_MAX_ACTIONS):
                if self._cancelled():
                    done = {"status": "cancelled", "mode": self.mode}
                    break
                spec, record, session, proposal = self._fresh()
                if proposal is None:
                    done = self._completed()
                    break
                plan = proposal.get("plan") or {}
                action = _next_simulation_action(plan, proposal, session, self.waiting)
                if action is None:
                    done = self._waits_for_sources() if self.waiting else self._completed()
                    break
                ref = action.get("ref")
                was_waiting = (session.get("nodeStates") or {}).get(ref) == agents_validate.AWAITING_SOURCE
                yield "stage", {**action, "label": agents_plans._plan_endpoint_label(ref, plan, {}) if ref else None}
                self._set_current(ref)
                stopped = yield from self._perform(action, ref)
                if stopped is not None:
                    done = stopped
                    break
                if self.mode == "step" and not (was_waiting and ref in self.waiting):
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
                (proposal4 or {}).get("plan") or {}, proposal4 or {}, session4, self.waiting
            )
            if proposal4 is not None  # dev/71: content work continues
            else None                  # on the completed structure
        )
        if next_action is None and self.waiting:
            # Nothing can go on but nodes that wait for their source.
            return self._waits_for_sources()
        return {"status": "stepped", "mode": self.mode, "nextAction": next_action}

    def _clear_in_flight(self) -> None:
        _SIMULATE_CANCEL_EVENTS.pop(self.simulate_execution_id, None)
        with contextlib.suppress(Exception):
            spec, record, session, _ = self._fresh()
            session.pop("simulatingSince", None)
            session.pop("simulateExecutionId", None)
            session.pop("simulateCancelRequested", None)
            session.pop("currentRef", None)
            record["builderSession"] = session
            self._write(spec)

    # ── the actions ──────────────────────────────────────────────────────────
    def _validate(self, ref):
        """Validate one node (``validate.py``): code that passes its check
        lands as the agent's change, and its ``change`` event rides this
        stream. A failure pauses the run: nothing downstream is written, and
        the attempts, each with its code, are in the node's agent chat. A
        node that waits for its source is noted, and the run goes on."""
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
        if verdict == agents_validate.AWAITING_SOURCE:
            # The node waits for the user to pick its source in its Dataset
            # Finder's chat: the run goes on with every node that does not
            # read from it, and pauses, naming it, when none can.
            if ref not in self.waiting:
                self.waiting.append(ref)
            return None
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
