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
from utk_curio.backend.app.agents.application.solve import node_work as agents_node_work
from utk_curio.backend.app.agents.application.solve import run_node as agents_run_node
from utk_curio.backend.app.agents.application.solve import session as agents_session
from utk_curio.backend.app.agents.application.solve import validate as agents_validate
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.projects import storage as projects_storage


#: The drivers of the builds this process runs, by execution id: each one's
#: stop event. A build no entry holds has no driver here.
_SIMULATE_CANCEL_EVENTS: dict[str, object] = {}

#: The fields a running Build & validate keeps on the plan's record, which it
#: clears when it ends: among them the start it began in (``simulateBootId``).
_IN_FLIGHT = (
    "simulatingSince", "simulateExecutionId", "simulateMode", "simulateCancelRequested", "currentRef",
    "simulateBootId",
)


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
    waiting for its source (``validate.SOURCE_WAITS``) → validate, which asks
    no one while its source still waits; validated → approve (its code landed
    when it passed; approving records it); approved → next ref. A ref of
    *waiting*, which the run found waiting for its source, is passed over
    with every node that reads from it: every other node goes on. The plan's
    nodes and connections landed with it, so nothing is created or connected
    here."""
    node_states = session.get("nodeStates") or {}
    held = _reading_from(plan, waiting) if waiting else set()
    for ref in _ordered_plan_refs(plan):
        if ref in held:
            continue
        state = node_states.get(ref, "created")
        if state in ("created", "failed", *agents_validate.SOURCE_WAITS):
            return {"action": "validate", "ref": ref}
        if state == "validated":
            return {"action": "approve", "ref": ref}
        # "approved" → continue to the next ref.
    return None


def _names(labels: list[str]) -> str:
    """*labels* as a sentence names them: "A", "A and B", "A, B and C"."""
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + " and " + labels[-1]


def _waits_said(wait: str, labels: list[str]) -> str:
    """How a pause says that the loaders *labels* wait for their source, for
    *wait* (a state of ``validate.SOURCE_WAITS``): the user's pick on each
    one's candidates card, which the chat of the plan's agent holds (the chat
    that asks for a loader's candidates gets their card), a download into the
    Data Catalog, or the install of the dataset picked."""
    one = len(labels) == 1
    names = labels[0] if one else _names(labels)
    if wait == agents_validate.AWAITING_DOWNLOAD:
        return (f"{names} waits for its source to download into the Data Catalog" if one
                else f"{names} wait for their sources to download into the Data Catalog")
    if wait == agents_validate.AWAITING_INSTALL:
        return (f"{names} waits for the install of the dataset picked for it" if one
                else f"{names} wait for the install of the datasets picked for them")
    return (f"{names} needs a source: pick one on its card in this chat" if one
            else f"{names} need a source: pick each one on its card in this chat")


def awaiting_source_reason(user_key: str, spec: dict, session: dict, plan: dict, refs) -> dict:
    """Why Build & validate paused: every node of *refs* waits for its source,
    and no other node can go on. Each waits for what the plan's ledger says
    (``validate.SOURCE_WAITS``): the user's pick on its candidates card, a
    download into the Data Catalog, or an install. Each is named by its ref,
    its node and its Finder's attachment, and the message names them by what
    they wait for; the strip ends it with how to go on."""
    node_ids = session.get("nodeIds") or {}
    states = session.get("nodeStates") or {}
    nodes = []
    waiting: dict[str, list[str]] = {}
    for ref in refs:
        node_id = node_ids.get(ref)
        finder = agents_dataset_resolution.finder_attachment(spec, node_id, user_key=user_key) if node_id else None
        nodes.append({"ref": ref, "nodeId": node_id, "attachmentId": (finder or {}).get("attachmentId")})
        wait = states.get(ref) if states.get(ref) in agents_validate.SOURCE_WAITS else agents_validate.AWAITING_SOURCE
        waiting.setdefault(wait, []).append(agents_plans._plan_endpoint_label(ref, plan, {}))
    message = "; ".join(
        _waits_said(wait, waiting[wait])
        for wait in agents_validate.SOURCE_WAITS if wait in waiting
    )
    return {"kind": agents_validate.AWAITING_SOURCE, "nodes": nodes, "message": message}


def _in_flight(session: dict) -> str | None:
    """The mode of the Build & validate running on *session*'s plan, or None
    when none runs, as the server decides it everywhere
    (``node_work.build_running``): one whose start is older than the stale
    bound, or that an earlier start began, is gone."""
    return agents_node_work.build_running(session)


def _pause_follows(user_key: str, spec: dict, record: dict, session: dict) -> None:
    """A pause for loaders' sources names those of its loaders that still wait,
    each as it waits now, and ends when none does."""
    reason = session.get("pauseReason")
    if not (isinstance(reason, dict) and reason.get("kind") == agents_validate.AWAITING_SOURCE):
        return
    states = session.get("nodeStates") or {}
    left = [
        entry.get("ref") for entry in reason.get("nodes") or []
        if isinstance(entry, dict) and states.get(entry.get("ref")) in agents_validate.SOURCE_WAITS
    ]
    if not left:
        session.pop("pauseReason", None)
        return
    proposal = agents_store._plan_proposal_any(spec, record.get("attachmentId"), session.get("planProposalId"))
    session["pauseReason"] = awaiting_source_reason(user_key, spec, session, (proposal or {}).get("plan") or {}, left)


def follow_the_sources(user_key: str, spec: dict) -> list[dict]:
    """Each landed plan's waits follow its loaders' sources, in *spec*, the
    dataflow a writer holds under its spec lock after it changed a Dataset
    Finder's record. A plan node that waits for its source
    (``validate.SOURCE_WAITS``) waits for what its Finder's record says now:
    the user's pick, a download or an install (``validate.plan_wait_state``).
    One whose source waits for nothing more is placed again (``created``),
    and the next pass builds it, or the running one: the pick resolved it,
    its download landed, its install was applied, or the record went with a
    cleared chat or a Finder taken off, and the next pass asks a Finder
    again. A pause for sources names those still waiting, each as it waits,
    and ends when none does.

    Returns one entry per plan node that moved: its plan's agent
    (``attachmentId``, ``coord``), its ``ref``, ``nodeId`` and new
    ``state``, whether the pause it waited in named it (``pausedOn``: Build &
    validate paused on it, rather than a row's Solve leaving it waiting),
    what left it waiting (``waitedBy``: ``auto`` or ``step`` for Build &
    validate or a Step, ``node`` for a row's Solve, as ``sourceWaitBy``
    recorded it, else None), whether a pause still stands (``paused``) and
    the mode of a Build & validate running on it (``running``, else None)."""
    moved: list[dict] = []
    for record in attachments.list_attachments(spec):
        session = record.get("builderSession")
        states = session.get("nodeStates") if isinstance(session, dict) else None
        if not isinstance(states, dict):
            continue
        node_ids = session.get("nodeIds") or {}
        waited_by = dict(session.get("sourceWaitBy") or {})
        refs = []
        for ref, state in states.items():
            if state not in agents_validate.SOURCE_WAITS:
                continue
            now = agents_validate.plan_wait_state(spec, node_ids.get(ref), user_key)
            if now != state:
                states[ref] = now
                refs.append(ref)
        if not refs:
            continue
        # A node placed again waits for nothing: what left it waiting goes.
        for ref in refs:
            if states[ref] not in agents_validate.SOURCE_WAITS:
                (session.get("sourceWaitBy") or {}).pop(ref, None)
        paused_on = _paused_on(session)
        _pause_follows(user_key, spec, record, session)
        moved += [{
            "attachmentId": record.get("attachmentId"),
            "coord": str(record.get("coord") or ""),
            "ref": ref,
            "nodeId": node_ids.get(ref),
            "state": states[ref],
            "pausedOn": ref in paused_on,
            "waitedBy": waited_by.get(ref),
            "paused": bool(session.get("pauseReason")),
            "running": _in_flight(session),
        } for ref in refs]
    return moved


def plan_waiting_on(spec: dict, node_id: str) -> dict | None:
    """The landed plan whose node *node_id* waits for its source
    (``validate.SOURCE_WAITS``), as *spec* holds its ledger: its agent's
    ``attachmentId`` and ``coord``, the node's ``ref`` and ``state``, whether
    the plan's pause names it (``pausedOn``) and the mode of a Build &
    validate running on it (``running``, else None); None when no plan waits
    for it."""
    for record in attachments.list_attachments(spec):
        session = record.get("builderSession")
        states = session.get("nodeStates") if isinstance(session, dict) else None
        if not isinstance(states, dict):
            continue
        for ref, waited in (session.get("nodeIds") or {}).items():
            if waited == node_id and states.get(ref) in agents_validate.SOURCE_WAITS:
                return {"attachmentId": record.get("attachmentId"), "coord": str(record.get("coord") or ""),
                        "ref": ref, "state": states[ref], "pausedOn": ref in _paused_on(session),
                        "running": _in_flight(session)}
    return None


def _paused_on(session: dict) -> set[str]:
    """The refs a pause of *session* for loaders' sources names."""
    reason = session.get("pauseReason")
    if not (isinstance(reason, dict) and reason.get("kind") == agents_validate.AWAITING_SOURCE):
        return set()
    return {entry.get("ref") for entry in reason.get("nodes") or [] if isinstance(entry, dict)}


def _not_built(state: str) -> bool:
    """Whether a plan node in *state* is one its plan has not built yet."""
    return state in ("created", "failed", *agents_validate.SOURCE_WAITS)


def built_outside_the_plan(user_key: str, project_id: str, node_id: str, *, change: dict | None = None,
                           actor=None) -> list[dict]:
    """A node whose code Solve this node left in it and checked (written into
    it, kept as it was, or landed as the agent's change) counts as built in
    each landed plan that holds it and has not built it yet: its row is
    validated, with its change (*change*, ``{changeId, attachmentId}``) when
    its code landed as one, so Build & validate approves it, recording the
    approval on that change when there is one and in the plan's ledger, and
    never builds it again. A pause for sources that named it names it no
    more, and ends when it named no other. Written under the spec lock, on the
    dataflow as it is now, by *actor*. Returns ``{attachmentId, ref}`` for
    each plan row that moved."""
    moved: list[dict] = []
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = dataflow_docs.live(user_key, project_id)
        if spec is None:
            return moved
        for record in attachments.list_attachments(spec):
            session = record.get("builderSession")
            states = session.get("nodeStates") if isinstance(session, dict) else None
            if not isinstance(states, dict):
                continue
            refs = [
                ref for ref, built in (session.get("nodeIds") or {}).items()
                if built == node_id and _not_built(states.get(ref, "created"))
            ]
            if not refs:
                continue
            for ref in refs:
                states[ref] = "validated"
                (session.get("sourceWaitBy") or {}).pop(ref, None)
                if change and change.get("changeId"):
                    session.setdefault("nodeChanges", {})[ref] = dict(change)
            _pause_follows(user_key, spec, record, session)
            record["builderSession"] = session
            moved += [{"attachmentId": record.get("attachmentId"), "ref": ref} for ref in refs]
        if moved:
            dataflow_docs.write(user_key, project_id, spec, actor or dataflow_docs.by_curio(user_key, "solve"))
    return moved


def request_simulate_cancel(user_key: str, project_id: str, attachment_id: str) -> dict:
    """Cancel a running simulation (dev/67-9): both dev/63 signals, the
    durable session flag plus the in-process event; the run stops at the next
    action boundary with everything already done persisted.

    A build no driver of this process holds (the process that drove it is
    gone, or its stream ended without clearing it) has nobody to stop: its
    Stop clears it at once, so it holds the plan no more (``cleared``). This
    process runs the dataflow's builds, so its drivers are all there are."""
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        if not session.get("simulatingSince"):
            raise AgentServiceError("no simulation is running for this attachment", 409)
        event = _SIMULATE_CANCEL_EVENTS.get(str(session.get("simulateExecutionId") or ""))
        if event is None:
            for key in _IN_FLIGHT:
                session.pop(key, None)
        else:
            session["simulateCancelRequested"] = True
        record["builderSession"] = session
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "simulate"))
    if event is None:
        return {"attachmentId": attachment_id, "cancelRequested": True, "cleared": True}
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
    failure is written). A loader that waits for its source (the user's pick,
    a download or an install) is passed over with every node that reads from
    it, so each loader's Dataset Finder is asked in one pass, and the run
    pauses once, naming every such loader, when no other node can go on. A
    source that comes while the run goes on places its loader again, and the
    run builds it (:func:`follow_the_sources`). Code that passes its check
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
    _refuse_over_work(session)
    now = _time.time()
    agents_session._check_delegate_llms(
        user_key, project_id, agents_catalog._resolve_definition(user_key, record.get("coord", "")), config,
        agents_session._delegate_capabilities((proposal.get("plan") or {}).get("nodes") or []),
    )
    simulate_execution_id = uuid.uuid4().hex
    # The driver's event is there before the run is marked in flight: a Stop
    # that comes at once finds a driver to stop, not a build to clear.
    stop = threading.Event()
    _SIMULATE_CANCEL_EVENTS[simulate_execution_id] = stop
    try:
        _start_the_run(user_key, project_id, attachment_id, simulate_execution_id, mode, now)
    except BaseException:
        _SIMULATE_CANCEL_EVENTS.pop(simulate_execution_id, None)
        raise
    return _simulate_events(
        user_key, project_id, attachment_id, config, plan_proposal_id,
        simulate_execution_id, mode, stop, exec_fn,
        coord=record.get("coord", ""), room_asker=agents_room.asker(),
    )


def _refuse_over_work(session: dict) -> None:
    """Refuse a Build & validate over work on the plan of *session* (409): a
    build already running on it, or a row's Solve of one of its nodes
    (``node_work``). A build an earlier start left, or one older than its
    bound, holds nothing."""
    if agents_node_work.build_running(session):
        raise AgentServiceError("a simulation is already running for this attachment", 409)
    if agents_node_work.row_solve_running(session):
        raise AgentServiceError(agents_node_work.ROW_SOLVING, 409)


def _start_the_run(user_key: str, project_id: str, attachment_id: str, simulate_execution_id: str,
                   mode: str, now: float) -> None:
    """Mark the run in flight, with its mode and the start it runs in
    (``simulateBootId``), and drop the pause it resumes from, on the plan's
    record as the dataflow holds it now, under its spec lock: a pick that
    moved the plan's ledger since the run's checks read it keeps its move. A
    run already in flight, or a row's Solve running on the plan, refuses this
    one (409)."""
    with projects_storage.spec_write_lock(user_key, project_id):
        spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
        record = agents_spec_reads._record_or_404(spec, attachment_id)
        session = record.get("builderSession") or {}
        _refuse_over_work(session)
        session["simulatingSince"] = now
        session["simulateExecutionId"] = simulate_execution_id
        session["simulateMode"] = mode
        session["simulateBootId"] = agents_node_work.this_start()
        session.pop("simulateCancelRequested", None)
        session.pop("pauseReason", None)
        record["builderSession"] = session
        dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._agent_actor(user_key, spec, attachment_id, "simulate"))


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
        # The refs this run found waiting for their source, in the order it
        # found them, while they still wait: passed over with what reads from
        # them.
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

    def _locked(self):
        """The dataflow's spec lock, which every write of the plan's record
        holds from its read to its write, as every writer of a node's source
        does: a pick that lands meanwhile is never written over."""
        return projects_storage.spec_write_lock(self.user_key, self.project_id)

    def _write(self, spec) -> None:
        """Write *spec*, a fresh state this driver changed, as the attachment's agent."""
        dataflow_docs.write(
            self.user_key, self.project_id, spec,
            agents_spec_reads._agent_actor(self.user_key, spec, self.attachment_id, "simulate"),
        )

    def _write_session(self, mutate) -> dict:
        with self._locked():
            spec, record, session, _ = self._fresh()
            mutate(session)
            record["builderSession"] = session
            self._write(spec)
        return session

    def _still_waiting(self, session: dict) -> list[str]:
        """The refs of :attr:`waiting` whose source still waits, as *session*,
        the plan's record read fresh, says: a source picked, landed or
        installed since places its node again, and this run builds it."""
        states = session.get("nodeStates") or {}
        return [ref for ref in self.waiting if states.get(ref) in agents_validate.SOURCE_WAITS]

    def _pause(self, reason: dict) -> dict:
        """Persist a pause reason, ending the run in the same write, and answer
        the paused done payload: a pick that lands after it sees no run in
        flight."""

        def _mutate(session):
            session["pauseReason"] = reason
            for key in _IN_FLIGHT:
                session.pop(key, None)

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

    def _waits_for_sources(self) -> dict | None:
        """Pause once, naming every node this run found waiting for its
        source, when no other node can go on: decided and written under the
        spec lock, on the record as it is now. When a source came for one of
        them since, the run goes on with it instead, and this answers None."""
        with self._locked():
            spec, record, session, proposal = self._fresh()
            still = self._still_waiting(session)
            if still != self.waiting:
                self.waiting = still
                return None
            session["pauseReason"] = awaiting_source_reason(
                self.user_key, spec, session, (proposal or {}).get("plan") or {}, still,
            )
            for key in _IN_FLIGHT:
                session.pop(key, None)
            record["builderSession"] = session
            self._write(spec)
        return {"status": "paused", "mode": self.mode, "reason": session["pauseReason"]}

    def _free_recheck(self, spec: dict, session: dict, ref: str) -> bool:
        """Whether validating *ref* again is a free check: it waits for its
        source, and its Dataset Finder's record still holds what it waits on
        (candidates awaiting a pick, or a pick awaiting its download or
        install), so the check asks no one and changes nothing. A node whose
        record went asks a Finder anew, and one whose record resolved is
        built: either is an action."""
        if (session.get("nodeStates") or {}).get(ref) not in agents_validate.SOURCE_WAITS:
            return False
        node_id = (session.get("nodeIds") or {}).get(ref)
        record = agents_dataset_resolution.source_record(spec, node_id, user_key=self.user_key) if node_id else None
        return (record or {}).get("status") in (
            agents_dataset_resolution.STATE_CANDIDATES_PENDING, agents_dataset_resolution.STATE_AWAITING_INSTALL,
        )

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
        cancellation or the cap; returns the done payload. Each pass reads the
        plan's record fresh: a node whose source came since this run found it
        waiting is placed again, and this run builds it. A free check of a
        node still waiting for its source is no step's action
        (:meth:`_free_recheck`)."""
        done: dict = self._completed()
        try:
            yield "simulate_started", {
                "executionId": self.simulate_execution_id, "mode": self.mode,
            }
            for _ in range(agents_budgets.SIMULATE_MAX_ACTIONS):
                if self._cancelled():
                    done = {"status": "cancelled", "mode": self.mode}
                    break
                spec, _, session, proposal = self._fresh()
                if proposal is None:
                    done = self._completed()
                    break
                plan = proposal.get("plan") or {}
                self.waiting = self._still_waiting(session)
                action = _next_simulation_action(plan, proposal, session, self.waiting)
                if action is None:
                    paused = self._waits_for_sources() if self.waiting else self._completed()
                    if paused is None:
                        continue  # a source came meanwhile: its node goes on
                    done = paused
                    break
                ref = action.get("ref")
                free = self._free_recheck(spec, session, ref)
                yield "stage", {**action, "label": agents_plans._plan_endpoint_label(ref, plan, {}) if ref else None}
                self._set_current(ref)
                stopped = yield from self._perform(action, ref)
                if stopped is not None:
                    done = stopped
                    break
                if self.mode == "step" and not (free and ref in self.waiting):
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

    def _next_action(self) -> dict | None:
        """The next action, read fresh, past the nodes that still wait."""
        _, _, session, proposal = self._fresh()
        if proposal is None:  # dev/71: content work continues on the
            return None       # completed structure
        self.waiting = self._still_waiting(session)
        return _next_simulation_action(proposal.get("plan") or {}, proposal, session, self.waiting)

    def _stepped(self) -> dict:
        next_action = self._next_action()
        if next_action is None and self.waiting:
            # Nothing can go on but nodes that wait for their source.
            paused = self._waits_for_sources()
            if paused is not None:
                return paused
            next_action = self._next_action()  # a source came meanwhile
        return {"status": "stepped", "mode": self.mode, "nextAction": next_action}

    def _clear_in_flight(self) -> None:
        _SIMULATE_CANCEL_EVENTS.pop(self.simulate_execution_id, None)
        with contextlib.suppress(Exception), self._locked():
            spec, record, session, _ = self._fresh()
            if session.get("simulateExecutionId") not in (None, self.simulate_execution_id):
                # This run's pause ended it, and a Resume started the next
                # run since: the fields in flight are that run's.
                return
            for key in _IN_FLIGHT:
                session.pop(key, None)
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
        # The build's own validation: stamped with its mode, so it is no
        # row's Solve, and a node it leaves waiting records that this build
        # left it so (``sourceWaitBy``).
        for kind, payload in agents_run_node._validate_node_inline(
            self.user_key, self.project_id, self.attachment_id, self.config, ref, self.exec_fn, by=self.mode,
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
            # The node waits for its source: the run goes on with every node
            # that does not read from it, and pauses, naming it, when none
            # can. A source that came while it was checked places it again,
            # and the next pass builds it.
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
        approving records it (DEC-054: an approval is recorded, never
        silent), on its change when its code landed as one, and in the plan's
        ledger. Both are written on the records as the dataflow holds them,
        under its spec lock."""
        with self._locked():
            spec, record, ledger, _ = self._fresh()
            entry = (ledger.get("nodeChanges") or {}).get(ref) or {}
            home = attachments.get_attachment(spec, entry.get("attachmentId") or self.attachment_id)
            for change in (home or {}).get("changes") or []:
                if isinstance(change, dict) and change.get("changeId") == entry.get("changeId"):
                    change["approvedBy"] = "simulation-auto"
            ledger.setdefault("nodeStates", {})[ref] = "approved"
            record["builderSession"] = ledger
            self._write(spec)
        yield "action_result", {"action": "approve", "ref": ref, "outcome": "approved"}
        return None
