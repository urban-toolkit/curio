"""An agent at work in a dataflow's room: a peer of its doc, which the server runs.

While an agent works on a dataflow, it is in the dataflow's room as a person
there is. The server writes its awareness state into the dataflow's doc
(``dataflow_docs.set_agent_state``), under a client id no tab holds (above the
32 bits of every Yjs client's), and every tab of the doc gets it with
everyone's. Its fields:

* ``user``: who it is, as the server names it: ``participant_id``
  (``agent-<hex>``), ``user_id`` ``None``, ``name`` (its manifest's), and
  ``agent``: ``attachmentId``, ``coord``, ``category`` and ``askedBy``, the
  person who asked it, ``{account, name}``.
* ``skills``: the skills its run holds and has loaded.
* ``editing``: the node whose lock it holds, as a person's focus names one.
* ``pointer``: ``{x, y, t}`` in flow coordinates, during a drag only: its drop
  point, set as the drag starts, ``None`` as it ends.
* ``carrying``: during a drag only, what it drags: ``{id, kind, from, onto,
  node: {type, label}, ms}``. ``kind`` is ``add``, ``move`` or ``onto``, and
  ``from`` a palette's item (``{palette, item}``) or a node's place.

:func:`at_work` puts the agent of an attachment in the room for a run: one peer
per attachment and dataflow, which nested runs share, joining at the first
entry and leaving at the last. The room's Activity gets :data:`JOINED_EVENT`
and :data:`LEFT_EVENT`, with what it did, sent to the room's tabs as they
happen and kept for a join's snapshot (``room_state.record_activity``).

:func:`act` plays the peer's actions one at a time, in the order they come: it
waits while someone else holds a node it changes (:func:`wait_for_people`),
takes their locks, plays its drag, checks its targets again, writes, keeps the
locks a second and lets go. :func:`holding` is the same hold around a write its
caller makes, with no drag. A lock is ``room_state``'s soft lock, named after
the agent, with ``agent``, as its state's ``user.agent``, and ``writes``
(:data:`WRITES`).

**Pace.** A drag (:data:`DRAG_MS`) and the second a lock is kept after its
write (:data:`KEEP_AFTER_WRITE_S`) are waited only while some tab is bound to
the dataflow's doc (``dataflow_docs.has_tabs``). No wait, for a person's lock
either, happens under the spec lock or a doc's lock: only the write takes them,
so no other writer of the dataflow waits on an agent's pace, and :func:`act`
and :func:`holding` refuse to start under the dataflow's spec lock.

**Renewal.** Tabs drop a state not renewed for 30 s (y-protocols'
``outdatedTimeout``), and a run can last minutes, so one thread sends each
peer's state again :data:`RENEW_EVERY_S` after it was last sent
(:func:`renew_due`). It starts with the first peer and ends after the last.

**Locks**, in this order: a peer's turn (:attr:`Peer.turn`), then its own lock
(its state, held while it sends it) or the spec lock, then a doc's lock and
the doc module's own. This module's lock guards the peers it holds and is held
for no call out. Nothing a doc's lock is held for calls into this module.
"""

from __future__ import annotations

import copy
import logging
import random
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Callable, Iterator, NamedTuple, Optional

from utk_curio.backend.app.collaboration import dataflow_docs, room_state
from utk_curio.backend.app.projects import storage
from utk_curio.backend.config import COLLAB_NAMESPACE

logger = logging.getLogger(__name__)

#: What the room's tabs are told as an agent joins and leaves, and the kinds of
#: its Activity entries.
JOINED_EVENT = "agent_joined"
LEFT_EVENT = "agent_left"
#: The room's lock events, as a person's lock sends them (``events.py``).
LOCKED_EVENT = "node_locked"
UNLOCKED_EVENT = "node_unlocked"

#: What an agent's lock says it writes on the node.
WRITES = frozenset({"code", "spec", "widgets", "settings"})
#: The kinds of a canvas drag: a node added, a node moved, a card dropped onto
#: a node.
DRAG_KINDS = frozenset({"add", "move", "onto"})

#: How long a drag takes, in milliseconds, while a tab is bound.
DRAG_MS = 500
#: Seconds an agent keeps its lock after its write, while a tab is bound: the
#: node's code view shows the change while it holds it.
KEEP_AFTER_WRITE_S = 1.0
#: Seconds after which a peer's state is sent again, renewed: half the time
#: after which a tab drops a state not renewed.
RENEW_EVERY_S = 15.0
#: Seconds an action waits while someone else holds a node it changes, and how
#: often it looks again (step 13's ``changes.LOCK_WAIT_S``).
LOCK_WAIT_S = 30.0
LOCK_POLL_S = 0.25

#: Whether a thread renews the peers' states as they come due. Off,
#: :func:`renew_due` does it when it is called.
BACKGROUND = True

#: The clock and the wait of this module, which the tests set.
_clock = time.monotonic
_sleep = time.sleep

_lock = threading.RLock()
_wake = threading.Condition(_lock)
_peers: dict[tuple[str, str], "Peer"] = {}
_renewer: Optional[threading.Thread] = None


def _client_id() -> int:
    """A client id no tab holds: Yjs gives each client a 32-bit one, and lib0
    reads integers up to 53 bits."""
    return random.randrange(1 << 32, 1 << 53)


def asker(user) -> dict:
    """The person who asked an agent, as its ``askedBy`` names them: the
    account as a history point names it (``projects.services._history_person``)."""
    return {"account": str(user.id), "name": user.name or user.username}


class Peer:
    """An agent at work in a dataflow's room (:func:`at_work`)."""

    def __init__(self, user_key: str, project_id: str, attachment_id: str, *,
                 coord: str, name: str, category: Optional[str], asked_by: dict):
        self.user_key = str(user_key)
        self.project_id = project_id
        self.room = room_state.room_for(project_id)
        self.attachment_id = attachment_id
        self.participant_id = f"agent-{uuid.uuid4().hex}"
        self.client_id = _client_id()
        self.name = name
        #: Its state's ``user``, which its Activity entries carry too.
        self.user = {
            "participant_id": self.participant_id,
            "user_id": None,
            "name": name,
            "agent": {
                "attachmentId": attachment_id,
                "coord": coord,
                "category": category,
                "askedBy": {"account": _text(asked_by.get("account")), "name": _text(asked_by.get("name"))},
            },
        }
        #: One action of the peer at a time (:func:`act`, :func:`holding`).
        #: Reentrant: a nested run on the same thread plays inside its own.
        self.turn = threading.RLock()
        #: Its state, held while it is sent.
        self._lock = threading.Lock()
        self._skills: list[str] = []
        self._editing: Optional[str] = None
        #: The nodes whose lock it holds, in the order it took them, each with
        #: how many of its holds take it.
        self._held: dict[str, int] = {}
        #: What it did, by verb and thing: the ids done.
        self._did: dict[str, dict[str, dict]] = {}
        self._entries = 0
        self._joined = threading.Event()
        #: When its state was last sent, by this module's clock.
        self.sent_at = 0.0
        self.left = False

    @property
    def asker_account(self) -> Optional[str]:
        return self.user["agent"]["askedBy"]["account"]

    @property
    def skills(self) -> list[str]:
        return list(self._skills)

    def use_skills(self, names) -> None:
        """Add *names* to the skills its run holds and has loaded."""
        with self._lock:
            new = [name for name in dict.fromkeys(str(name) for name in names) if name not in self._skills]
            if not new:
                return
            self._skills += new
            self._send({"skills": list(self._skills)})

    def did(self) -> dict:
        """What it did, as its :data:`LEFT_EVENT` says it: for each verb, how
        many of each thing, in the order first done."""
        with self._lock:
            return {verb: {thing: len(done) for thing, done in things.items()}
                    for verb, things in self._did.items()}

    def _note(self, did) -> None:
        with self._lock:
            for verb, thing, ident in did:
                done = self._did.setdefault(str(verb), {}).setdefault(str(thing), {})
                done[object() if ident is None else ident] = True

    def _state(self) -> dict:
        return {"user": copy.deepcopy(self.user), "skills": list(self._skills),
                "editing": self._editing, "pointer": None, "carrying": None}

    def _send(self, fields: dict, *, joining: bool = False) -> None:
        """Write *fields* into its state in the room, under its own lock. A
        failure is logged: the room's view of an agent never ends its run."""
        try:
            dataflow_docs.set_agent_state(self.project_id, self.client_id, fields, joining=joining)
        except Exception:  # noqa: BLE001 - presence never fails the agent's work
            logger.exception("dataflow %s: the state of agent %s could not be sent", self.project_id, self.name)
        self.sent_at = _clock()


def _text(value) -> Optional[str]:
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# Joining and leaving
# ---------------------------------------------------------------------------

@contextmanager
def at_work(user_key: str, project_id: str, *, attachment_id: str, coord: str, name: str,
            category: Optional[str], asked_by: dict, skills=()) -> Iterator[Peer]:
    """The agent of *attachment_id* at work in *project_id*'s room for the
    block: the dataflow's peer of the attachment, which joins as the first
    block that needs it begins and leaves as the last one ends. A block nested
    in another, on any thread, shares its peer, and adds its *skills*.

    *user_key* is the dataflow's owner's storage key, *name* and *category*
    the agent's manifest's, and *asked_by* the person who asked
    (:func:`asker`)."""
    peer = _enter(user_key, project_id, str(attachment_id), coord=coord, name=name,
                  category=category, asked_by=asked_by, skills=skills)
    try:
        yield peer
    finally:
        _exit(peer)


def peer_of(project_id: str, attachment_id: str) -> Optional[Peer]:
    """The peer of *attachment_id* at work in *project_id*'s room, if any."""
    with _lock:
        return _peers.get((project_id, str(attachment_id)))


def _enter(user_key, project_id, attachment_id, *, coord, name, category, asked_by, skills) -> Peer:
    key = (project_id, attachment_id)
    with _lock:
        peer = _peers.get(key)
        joining = peer is None
        if joining:
            peer = _peers[key] = Peer(user_key, project_id, attachment_id, coord=coord, name=name,
                                      category=category, asked_by=asked_by)
        peer._entries += 1
    if joining:
        try:
            _join(peer, skills)
        except BaseException:
            peer._joined.set()
            _exit(peer)
            raise
        peer._joined.set()
    else:
        peer._joined.wait()
        peer.use_skills(skills)
    return peer


def _join(peer: Peer, skills) -> None:
    with peer._lock:
        peer._skills = list(dict.fromkeys(str(name) for name in skills))
        peer._send(peer._state(), joining=True)
    payload = copy.deepcopy(peer.user)
    room_state.record_activity(peer.room, JOINED_EVENT, payload)
    _emit(JOINED_EVENT, payload, peer.room)
    _ensure_renewer()


def _exit(peer: Peer) -> None:
    key = (peer.project_id, peer.attachment_id)
    with _wake:
        peer._entries -= 1
        leaving = peer._entries == 0
        if leaving:
            peer.left = True
            if _peers.get(key) is peer:
                del _peers[key]
            _wake.notify_all()
    if leaving:
        _leave(peer)


def _leave(peer: Peer) -> None:
    """The peer's last block ended: once an action another thread plays for
    it ends, its locks go, its state goes, and Activity says what it did. A
    block that ends under the dataflow's spec lock leaves at once, since such
    an action may be waiting for that lock to write."""
    under_the_spec_lock = storage.holds_spec_lock(peer.user_key, peer.project_id)
    with nullcontext() if under_the_spec_lock else peer.turn:
        with peer._lock:
            held, peer._held = list(peer._held), {}
        for node_id in held:
            if room_state.release_lock(peer.room, node_id, peer.participant_id):
                _emit(UNLOCKED_EVENT, {"nodeId": node_id}, peer.room)
        try:
            dataflow_docs.clear_agent_state(peer.project_id, peer.client_id)
        except Exception:  # noqa: BLE001 - presence never fails the agent's work
            logger.exception("dataflow %s: agent %s could not leave its doc", peer.project_id, peer.name)
    payload = {**copy.deepcopy(peer.user), "did": peer.did()}
    room_state.record_activity(peer.room, LEFT_EVENT, payload)
    _emit(LEFT_EVENT, payload, peer.room)


def _emit(event: str, payload: dict, room: str) -> None:
    """Tell the room's tabs *event*, as the room's own events are told."""
    from utk_curio.backend import extensions

    sio = extensions.socketio
    if sio is None:
        return
    try:
        sio.emit(event, payload, to=room, namespace=COLLAB_NAMESPACE)
    except Exception:  # noqa: BLE001 - presence never fails the agent's work
        logger.exception("the room %s could not be told %s", room, event)


# ---------------------------------------------------------------------------
# Locks, and waiting for people
# ---------------------------------------------------------------------------

def _holder(project_id: str, node_ids, asker_account, peer: Optional[Peer]) -> Optional[str]:
    """The name of someone whose lock holds one of *node_ids*: anyone but the
    person who asked (their own focus never holds their agent back), and but
    *peer* itself. Another agent's lock holds."""
    if not node_ids:
        return None
    locks = room_state.snapshot(room_state.room_for(project_id)).get("locks") or {}
    for node_id in node_ids:
        lock = locks.get(node_id)
        if not lock:
            continue
        if peer is not None and lock.get("participant_id") == peer.participant_id:
            continue
        if asker_account is not None and str(lock.get("user_id")) == str(asker_account):
            continue
        return str(lock.get("name") or lock.get("username") or "Someone")
    return None


def wait_for_people(project_id: str, node_ids, asker_account=None, *, peer: Optional[Peer] = None,
                    within: Optional[float] = None, poll: Optional[float] = None,
                    clock: Optional[Callable[[], float]] = None,
                    sleep: Optional[Callable[[float], None]] = None) -> Optional[str]:
    """Wait while someone else holds one of *node_ids*, as one person waits for
    another to leave a node: anyone but *asker_account*, the account that asked
    (``None``: anyone), and but *peer*. Up to *within* seconds
    (:data:`LOCK_WAIT_S`), looking again every *poll* (:data:`LOCK_POLL_S`).
    The name of who still holds one then, or ``None``. No lock is held while
    it waits."""
    within = LOCK_WAIT_S if within is None else within
    poll = LOCK_POLL_S if poll is None else poll
    clock = clock or _clock
    sleep = sleep or _sleep
    deadline = clock() + within
    while True:
        holder = _holder(project_id, node_ids, asker_account, peer)
        if holder is None or clock() >= deadline:
            return holder
        sleep(poll)


def _locked(peer: Peer, node_ids: tuple, writes: str) -> tuple[list[str], Optional[str]]:
    """Take the lock of each of *node_ids* that nobody holds; a node the
    person who asked holds stays theirs, and the agent writes beside them.
    The nodes it took, and the name of someone else who took one first, in
    which case it holds none of them."""
    holder = {"participant_id": peer.participant_id, "user_id": None, "username": None,
              "name": peer.name, "agent": copy.deepcopy(peer.user["agent"]), "writes": writes}
    with peer._lock:
        already = set(peer._held)
    taken: list[tuple[str, dict]] = []
    for node_id in node_ids:
        lock = room_state.try_lock(peer.room, node_id, holder)
        if lock is not None:
            taken.append((node_id, lock))
            continue
        someone = _holder(peer.project_id, [node_id], peer.asker_account, peer)
        if someone is not None:
            for node, _lock_record in taken:
                if node not in already:
                    room_state.release_lock(peer.room, node, peer.participant_id)
            return [], someone
    with peer._lock:
        for node_id, _lock_record in taken:
            peer._held[node_id] = peer._held.get(node_id, 0) + 1
        _send_editing(peer)
    for node_id, lock in taken:
        _emit(LOCKED_EVENT, {"nodeId": node_id, "lock": lock}, peer.room)
    return [node_id for node_id, _lock_record in taken], None


def _unlocked(peer: Peer, node_ids: list[str]) -> None:
    """Let go of the locks of *node_ids* this hold took."""
    gone = []
    with peer._lock:
        for node_id in node_ids:
            count = peer._held.get(node_id, 0) - 1
            if count > 0:
                peer._held[node_id] = count
            elif node_id in peer._held:
                del peer._held[node_id]
                gone.append(node_id)
        _send_editing(peer)
    for node_id in gone:
        if room_state.release_lock(peer.room, node_id, peer.participant_id):
            _emit(UNLOCKED_EVENT, {"nodeId": node_id}, peer.room)


def _send_editing(peer: Peer) -> None:
    """Under the peer's lock: its ``editing``, the first node it holds."""
    editing = next(iter(peer._held), None)
    if editing != peer._editing and not peer.left:
        peer._editing = editing
        peer._send({"editing": editing})


# ---------------------------------------------------------------------------
# Actions, one at a time
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Action:
    """One action of an agent's (:func:`act`)."""

    #: What it does, in a few words: what is left undone when it cannot land.
    what: str
    #: The write itself, called with no lock held: it takes the spec lock and
    #: the doc's lock (``dataflow_docs.write``). What it returns is
    #: :attr:`Acted.result`.
    write: Callable[[], Any]
    #: The nodes whose lock it takes for the write, and what it writes on them
    #: (:data:`WRITES`).
    holds: tuple = ()
    writes: Optional[str] = None
    #: The canvas drag it plays before the write: ``kind``, ``from``,
    #: ``onto``, ``node`` (``type``, ``label``) and ``to``, its drop point
    #: (``x``, ``y``, in flow coordinates).
    drag: Optional[dict] = None
    #: The nodes the dataflow must still hold when it writes.
    targets: tuple = ()
    #: What it did once it lands, each ``(verb, thing, id)``: ``("added",
    #: "node", "n1")``. :data:`LEFT_EVENT` counts them by verb and thing.
    did: tuple = ()


class Acted(NamedTuple):
    """What an action did (:func:`act`)."""

    #: Whether its write was made.
    landed: bool
    #: What its write returned.
    result: Any = None
    #: Its :attr:`Action.what`, when it did not land, and why: who still held
    #: one of its nodes, or its targets gone from the dataflow.
    left: Optional[str] = None
    held_by: Optional[str] = None
    gone: tuple = ()


class Holding:
    """A hold of nodes' locks for a write (:func:`holding`)."""

    def __init__(self, held_by: Optional[str], nodes: tuple):
        #: Who still held one of the nodes when the wait ran out; then it
        #: holds none and the block writes nothing.
        self.held_by = held_by
        #: The nodes whose lock it took.
        self.nodes = nodes
        #: Whether the locks are kept a second after the block (a write that
        #: did not happen shows nothing).
        self.keep = True


def _not_under_the_spec_lock(peer: Peer) -> None:
    if storage.holds_spec_lock(peer.user_key, peer.project_id):
        raise RuntimeError(
            "an agent's action waits for people, its drag and its lock's second, "
            "so it never starts under its dataflow's spec lock"
        )


@contextmanager
def holding(peer: Peer, nodes=(), writes: Optional[str] = None, *,
            within: Optional[float] = None) -> Iterator[Holding]:
    """Hold *nodes* for a write the block makes, the peer's one action then:
    wait while someone else holds one (:func:`wait_for_people`), take their
    locks, and after the block keep them a second while a tab is bound, then
    let go. The block writes nothing when :attr:`Holding.held_by` names who
    still held one. Started under the dataflow's spec lock, it raises
    ``RuntimeError``: the block takes that lock for its write."""
    nodes = tuple(dict.fromkeys(nodes))
    if nodes and writes not in WRITES:
        raise ValueError(f"an agent's lock writes one of {sorted(WRITES)}, not {writes!r}")
    if peer.left:
        raise RuntimeError("the agent left its dataflow's room")
    _not_under_the_spec_lock(peer)
    with peer.turn:
        held_by, taken = None, []
        if nodes:
            held_by, taken = _wait_and_lock(peer, nodes, writes, LOCK_WAIT_S if within is None else within)
        hold = Holding(held_by, tuple(taken))
        try:
            yield hold
            if taken and hold.keep and dataflow_docs.has_tabs(peer.project_id):
                _sleep(KEEP_AFTER_WRITE_S)
        finally:
            _unlocked(peer, taken)


def _wait_and_lock(peer: Peer, nodes: tuple, writes: str, within: float) -> tuple[Optional[str], list[str]]:
    """Wait for people, then lock: again, while someone takes a node first."""
    deadline = _clock() + within
    while True:
        holder = wait_for_people(peer.project_id, nodes, peer.asker_account, peer=peer,
                                 within=max(0.0, deadline - _clock()))
        if holder is not None:
            return holder, []
        taken, holder = _locked(peer, nodes, writes)
        if holder is None:
            return None, taken
        if _clock() >= deadline:
            return holder, []
        _sleep(LOCK_POLL_S)


def act(peer: Peer, action: Action) -> Acted:
    """Play *action*, the peer's one action then, its others waiting their
    turn: wait while someone else holds one of its nodes, take their locks,
    play its drag (``pointer`` and ``carrying`` in the peer's state for
    :data:`DRAG_MS` while a tab is bound), check that the dataflow still holds
    its targets, write, keep the locks a second while a tab is bound, and let
    go. An action whose nodes someone still holds, or whose targets went,
    writes nothing and says what it left undone. Started under the dataflow's
    spec lock, it raises ``RuntimeError``."""
    drag = _dragged(action.drag) if action.drag is not None else None
    with holding(peer, action.holds, action.writes) as hold:
        if hold.held_by is not None:
            return Acted(False, left=action.what, held_by=hold.held_by)
        dragging = False
        try:
            if drag is not None:
                drag["pointer"]["t"] = int(time.time() * 1000)  # when it is sent, as a tab's
                with peer._lock:
                    peer._send(drag)
                dragging = True
                if dataflow_docs.has_tabs(peer.project_id):
                    _sleep(DRAG_MS / 1000)
            gone = _gone(peer, action.targets)
            if gone:
                hold.keep = False
                return Acted(False, left=action.what, gone=gone)
            result = action.write()
        finally:
            if dragging:
                with peer._lock:
                    peer._send({"pointer": None, "carrying": None})
        peer._note(action.did)
        return Acted(True, result=result)


def _dragged(drag: dict) -> dict:
    """The ``pointer`` and ``carrying`` a drag puts in the peer's state,
    checked before the action waits for anything."""
    kind = drag.get("kind")
    if kind not in DRAG_KINDS:
        raise ValueError(f"a drag is one of {sorted(DRAG_KINDS)}, not {kind!r}")
    to = drag.get("to") or {}
    x, y = to.get("x"), to.get("y")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (x, y)):
        raise ValueError(f"a drag drops at a point of the dataflow, not {to!r}")
    node = drag.get("node") or {}
    return {
        "pointer": {"x": x, "y": y, "t": int(time.time() * 1000)},
        "carrying": {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "from": copy.deepcopy(drag.get("from")),
            "onto": drag.get("onto"),
            "node": {"type": node.get("type"), "label": node.get("label")},
            "ms": DRAG_MS,
        },
    }


def _gone(peer: Peer, targets) -> tuple:
    """The *targets* gone from the dataflow as it is now."""
    if not targets:
        return ()
    spec = dataflow_docs.live(peer.user_key, peer.project_id)
    nodes = ((spec or {}).get("dataflow") or {}).get("nodes") or []
    present = {node.get("id") for node in nodes if isinstance(node, dict)}
    return tuple(target for target in targets if target not in present)


# ---------------------------------------------------------------------------
# Renewal
# ---------------------------------------------------------------------------

def renew_due(now: Optional[float] = None) -> None:
    """Send again each peer's state last sent :data:`RENEW_EVERY_S` ago or
    more, its clock moved on, so no tab drops it."""
    now = _clock() if now is None else now
    with _lock:
        peers = list(_peers.values())
    for peer in peers:
        if not peer.left and now - peer.sent_at >= RENEW_EVERY_S:
            with peer._lock:
                peer._send({})


def _ensure_renewer() -> None:
    global _renewer
    if not BACKGROUND:
        return
    with _wake:
        if _renewer is None or not _renewer.is_alive():
            _renewer = threading.Thread(target=_renew, name="agent-peers", daemon=True)
            try:
                _renewer.start()
            except RuntimeError:  # no thread to be had: tabs drop the agent after 30 s
                _renewer = None
                logger.exception("the agents' states in their rooms will not be renewed")


def _renew() -> None:
    """The renewing thread: it sends each peer's state again as it comes due,
    and ends once no peer is at work."""
    global _renewer
    while True:
        with _wake:
            if not _peers or not BACKGROUND:
                if _renewer is threading.current_thread():
                    _renewer = None
                return
            wait = min(peer.sent_at for peer in _peers.values()) + RENEW_EVERY_S - _clock()
            if wait > 0:
                _wake.wait(timeout=wait)
                continue
        try:
            renew_due()
        except Exception:  # noqa: BLE001 - a renewal that fails must not stop the next ones
            logger.exception("renewing the agents' states in their rooms failed")
            with _wake:
                _wake.wait(timeout=RENEW_EVERY_S)


def reset_for_tests() -> None:
    """Forget every peer at work, telling no room, and end the renewing
    thread, as a backend that stopped does."""
    with _wake:
        for peer in _peers.values():
            peer.left = True
        _peers.clear()
        renewer = _renewer
        _wake.notify_all()
    if renewer is not None:
        renewer.join(timeout=10)
