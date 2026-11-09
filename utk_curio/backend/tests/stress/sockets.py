"""Each simulated user's tab of a shared dataflow, over Socket.IO.

A tier's users are put in rooms of :data:`ROOM_SIZE`. The first user of a room
owns the dataflow it created for its own run, and invites the others to edit
it, by username, through the route the Share menu calls
(``POST /api/projects/<id>/editors``): the server drops a watcher's changes
(``projects/access.py``). Each user then opens a tab of its room's dataflow,
as the canvas does:

* it connects with its sign-in token to the namespace ``/api/config/public``
  names, at the backend's ``socket.io`` path (``collabSocketTarget.ts``), over
  WebSocket, which the canvas tries first;
* joins the room (``join_session``) and syncs the doc: sync step 1 in a ``yjs``
  event, ``{projectId, message}``, framed as y-protocols frames it, which the
  server answers with step 2 and, to an editor, its own step 1
  (``collaboration/dataflow_docs.py``; its tests drive the same frames from
  ``test_collaboration/_ydoc_client.py``);
* types comment lines into a node's code, a keystroke a transaction, and drags
  that node, each change a ``yjs`` update; a node's code and its place are
  where ``src/contracts/dataflowDoc.json`` puts them (``doc_mapping``);
* and stays open until its user's own dataflow run is done, as a person's tab
  does while their nodes run.

**A shared canvas** (``--shared-canvas``) is a room whose members all work on
its one dataflow, the owner's. After the sync each member adds a Python node
of its own below a node of the dataflow (``run.canvas_parent``), with its
connection, as the canvas writes a node it adds (:func:`member_node`,
``doc_mapping.apply_dataflow``). Once every member's node is in every tab, it
asks for the lock of the node it types in, as the canvas does when the node
takes focus (``node_lock``), types and drags, and lets the lock go
(``node_unlock``). Locks are soft: a member whose lock another holds types
anyway, as the canvas lets it, and lets go only of a lock it got. Each tab
keeps the room's locks as the canvas does, from the join's snapshot and the
lock events (:data:`ROOM_EVENTS`). Once the room's docs agree, the member
plays the dataflow with the code its tab holds and its owner runs it on the
server and saves it (``driver.VirtualUser.on_the_canvas``). Before any tab
closes, which would let go of its locks, the server's lock table, read as a
tab joining then reads it, and each tab's must hold no lock.

**Agents** (``--agents``, ``agents.py``): on a shared canvas each member also
asks its agent to write its own node. A tab reads the agents' events too
(:data:`AGENT_EVENTS`): each ask's events, and an agent's join and leave. The
room's agents (``room.agents``, ``agents.RoomAgents``) are asked as
:func:`run_tab` and ``driver.VirtualUser.on_the_canvas`` go, kept out of the
tabs' compare of their docs, and checked once every member's work is over,
before the room's locks are read.

**Sync time** is how long an update took to be in every other tab of the room
that had synced when it was sent: from just before the sender emits it to the
moment the last of them has applied it. An update is known by its sender's
client id and the sender's clock after it, and a tab holds it once its state
vector holds that clock, which is how Yjs itself decides what a doc has: the
server relays what its own doc observed, not the sender's bytes.

**An update's answer** is its ack when the server applies it at once, and
otherwise a :data:`KEPT_EVENT` message once its batch is applied, the ack then
saying ``queued``. A tab's answers come in the order it sent its updates, and
``socket yjs update`` times each from its send to its answer.

A tab's doc is one any thread may use (``doc_mapping.new_doc``), behind a lock
of its own: the user's thread edits it, and the socket's thread applies what
the server sends.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit

import engineio
import socketio
from pycrdt import (
    Array,
    Assoc,
    Decoder,
    Map,
    Text,
    YMessageType,
    YSyncMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from utk_curio.backend.app.collaboration import doc_mapping

#: Tabs per room: its owner and the editors it invites.
ROOM_SIZE = 5

#: What each tab types into its node's code: this line, this many times, a
#: comment in the node's language when it has line comments. A drag of the
#: node follows every :data:`DRAG_EVERY` keystrokes.
TYPED_LINE = "{prefix}{user} typed this line\n"
LINES_TYPED = 2
DRAG_EVERY = 15
#: How far a drag moves the node, in canvas units, along each axis.
DRAG_STEP = 24

#: A keystroke's pace when everyone types at once (the burst profile): a
#: person typing steadily, five keys a second. The session profile's pace is
#: in ``run.py``.
BURST_KEY_GAP_S = 0.2

# Each wait is a judgement, as API_TIMEOUT_S in driver.py is: nothing on the
# server bounds these, so the value says when slow becomes a failure.
#   CONNECT - a tab's handshake and its namespace's connect, which reads the
#             sign-in. socket.io-client gives up on one after 20 s and tries
#             again; three of those is a failure worth seeing.
#   CALL    - join_session, sync step 1, and the server's answer to an update.
#   ROOM    - how long a tab waits for the rest of its room at a phase, the
#             start gate's wait (driver.START_GATE_TIMEOUT_S): arrivals of the
#             session profile spread over two minutes.
#   SETTLE  - after the room's last update, how long until every update must
#             be in every tab of the room.
#   DONE    - on a shared canvas, how long a tab whose member's work is over
#             waits for the rest of its room's (every member's plays, and the
#             owner's run on the server and save) before the room's locks are
#             read: about a member's plays under a 100-user burst, twice over.
CONNECT_TIMEOUT_S = 60.0
CALL_TIMEOUT_S = 60.0
ROOM_WAIT_S = 300.0
SETTLE_TIMEOUT_S = 60.0
DONE_WAIT_S = 900.0

#: The roles whose changes the server applies (``projects/access.py``).
EDIT_ROLES = ("owner", "editor")

#: The Socket.IO event the doc's messages travel in.
EVENT = doc_mapping.EVENT
#: The event that answers a tab's updates the server queued, once applied.
KEPT_EVENT = doc_mapping.KEPT_EVENT
#: The room's events a tab reads besides the doc's, each with its handler in
#: :meth:`Tab.room_event`: a lock taken and let go (``collaboration/events.py``),
#: and a participant's leave, which lets go of its locks
#: (``room_state.remove_user``), kept as the canvas keeps them
#: (``CollaborationProvider.tsx``).
ROOM_EVENTS = ("node_locked", "node_unlocked", "user_left")
#: The events of the agents at work in the room a tab reads too (``--agents``,
#: ``agents.py``), each with its handler in :meth:`Tab.room_event`: each event
#: of an ask, told to the owner's and the editors' tabs
#: (``agents/application/turns/turn_jobs.py``), and an agent's join and leave
#: (``collaboration/agent_peers.py``); and the events that end an ask.
AGENT_EVENTS = ("agent_turn", "agent_joined", "agent_left")
ASK_ENDINGS = ("done", "error", "withdrawn")
#: What ``node_lock`` answers when another participant holds the lock: no
#: failure, since locks are soft and the canvas only shows a chip.
LOCKED_BY_OTHER = "locked_by_other"
#: The doc's roots that hold the nodes by id, and their order.
NODES, NODE_ORDER = "nodes", "nodeOrder"
#: What the room's tabs compare of each connection (:meth:`Tab.digest`).
EDGE_FIELDS = ("id", "source", "target", "sourceHandle", "targetHandle", "type")

#: A member's own node on a shared canvas: a Python node whose one line of
#: code passes its input on (``input_0``, its one circle), placed a column to
#: the right of the node it reads and a row lower per member.
MEMBER_NODE_TYPE = "curio.builtin/python-computation"
PASS_ON_CODE = "return input_0"
MEMBER_NODE_DX = 645
MEMBER_NODE_DY = 120

_NODE_FIELDS: dict = doc_mapping.LAYOUT["node"]
#: The node key that holds its code: the Trill field the layout keeps as a Text.
CODE_KEY = next(name for name, place in _NODE_FIELDS.items() if place == doc_mapping.TEXT)
#: The node key that holds its place, one value of the members below.
PLACE_KEY, X_MEMBER = _NODE_FIELDS["x"].split(".", 1)
_Y_GROUP, Y_MEMBER = _NODE_FIELDS["y"].split(".", 1)

if (
    _Y_GROUP != PLACE_KEY
    or doc_mapping.LAYOUT["roots"].get(NODES) != "map"
    or doc_mapping.LAYOUT["roots"].get(NODE_ORDER) != "array"
):
    raise RuntimeError(
        "src/contracts/dataflowDoc.json no longer keeps a node's place as one "
        "value, or its nodes in the roots the stress tabs type and drag in"
    )


class TabFailed(Exception):
    """A tab could not go on. What happened is already recorded."""


def state_vector(doc) -> dict[int, int]:
    """The doc's state vector: each client's next clock, read as the server's
    ``dataflow_docs._clocks`` reads it."""
    decoder = Decoder(doc.get_state())
    clocks: dict[int, int] = {}
    for _ in range(decoder.read_var_uint()):
        client = decoder.read_var_uint()
        clocks[client] = decoder.read_var_uint()
    return clocks


def socket_target(backend_url: str) -> tuple[str, str]:
    """The server's origin and its Socket.IO path, as ``collabSocketTarget.ts``
    finds them: a backend under a path (``/api``) puts its prefix in the path,
    and the namespace is given apart."""
    parts = urlsplit(backend_url)
    return f"{parts.scheme}://{parts.netloc}", f"{parts.path.rstrip('/')}/socket.io"


def member_node(parent: dict, row: int) -> tuple[dict, dict]:
    """A member's own node on a shared canvas and its connection below
    *parent* (``{id, x, y}``), each as the canvas writes it in Trill
    (``TrillGenerator.generateTrill``): a Python node with an id as uuid4 makes
    one, whose code passes its input on (:data:`PASS_ON_CODE`), at *row* below
    the others; and an edge from the parent's output to its input."""
    node_id = str(uuid.uuid4())
    x = parent.get("x") if isinstance(parent.get("x"), (int, float)) else 0
    y = parent.get("y") if isinstance(parent.get("y"), (int, float)) else 0
    node = {
        "id": node_id, "type": MEMBER_NODE_TYPE,
        "x": x + MEMBER_NODE_DX, "y": y + MEMBER_NODE_DY * row,
        "content": PASS_ON_CODE, "out": "DEFAULT", "in": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }
    edge = {
        "id": f"reactflow__edge-{parent['id']}out-{node_id}in",
        "source": parent["id"], "target": node_id,
        "sourceHandle": "out", "targetHandle": "in",
    }
    return node, edge


def holder(lock) -> str:
    """Who holds *lock*, a lock as the server tells of it: an agent's lock
    names its agent too (``room_state.AGENT_LOCK_FIELDS``). An agent at work
    in the room (``agent_peers``) holds its lock under its own name, its
    ``agent`` saying who asked it (``askedBy``): ``Node Builder for Ana``."""
    lock = lock if isinstance(lock, dict) else {}
    agent = lock.get("agent")
    if isinstance(agent, dict):
        asked = agent.get("askedBy") if isinstance(agent.get("askedBy"), dict) else {}
        name = str(lock.get("name") or agent.get("coord") or lock.get("participant_id") or "an agent")
        return f"{name} for {asked.get('name') or asked.get('account') or 'someone'}"
    who = str(lock.get("username") or lock.get("name") or lock.get("participant_id") or "someone")
    return f"{agent} for {who}" if agent else who


def require_websocket_client() -> None:
    """Stop at once, rather than as every tab's connect runs out, where
    python-socketio's client has no WebSocket to connect with."""
    try:
        import websocket  # noqa: F401  (websocket-client)
    except ImportError as exc:
        raise SystemExit(
            "[stress] the tabs connect over WebSocket, as the canvas does, "
            "which python-socketio's client does through websocket-client; "
            "install requirements.txt"
        ) from exc


# ---------------------------------------------------------------------------
# The socket
# ---------------------------------------------------------------------------

class InOrderEngineIOClient(engineio.Client):
    """engineio's client, handing each message to Socket.IO on the thread that
    read it, in the order it came.

    Its own client starts a thread per message, and python-socketio's client
    puts a binary event together (its header, then each attachment, each a
    message of its own) across those threads, so under load an attachment can
    be read before its header and the stream goes wrong from there. Every doc
    message is a binary event. python-socketio's server turns the same thing
    off for its own engineio (``async_handlers=False`` in
    ``socketio.base_server``), and a browser's socket.io-client reads its
    messages in order on the page's one thread.
    """

    def _trigger_event(self, event, *args, **kwargs):
        if event == "message":
            kwargs["run_async"] = False
        return super()._trigger_event(event, *args, **kwargs)


class TabClient(socketio.Client):
    """python-socketio's client on :class:`InOrderEngineIOClient`."""

    def _engineio_client_class(self):
        return InOrderEngineIOClient


class SocketLink:
    """A tab's socket: connected as the canvas connects, with no reconnection,
    since a tab that reconnects is outside the room it joined until it joins
    again; a drop is a failure instead. *on_yjs* takes the doc's messages and
    the answers to the tab's queued updates (:data:`KEPT_EVENT`); *on_room*,
    given, takes each of :data:`ROOM_EVENTS` and :data:`AGENT_EVENTS` as
    ``on_room(name, payload)``."""

    def __init__(self, backend_url: str, namespace: str, token: str,
                 on_yjs: Callable, on_close: Callable, on_room: Optional[Callable] = None,
                 dataflow: Optional[str] = None):
        self.namespace = namespace
        # emit() is not thread-safe for a message of several packets, which
        # every binary event is; the tab's thread and the socket's both send.
        self._send_lock = threading.Lock()
        self._client = TabClient(
            reconnection=False, handle_sigint=False, logger=False,
            engineio_logger=False, request_timeout=CONNECT_TIMEOUT_S,
        )
        self._client.on(EVENT, on_yjs, namespace=namespace)
        self._client.on(KEPT_EVENT, on_yjs, namespace=namespace)
        self._client.on("disconnect", on_close, namespace=namespace)
        if on_room is not None:
            for name in ROOM_EVENTS + AGENT_EVENTS:
                self._client.on(name, lambda *args, name=name: on_room(name, args[0] if args else None),
                                namespace=namespace)
        origin, path = socket_target(backend_url)
        # tmp/sharded-backend: the handshake names the tab's dataflow, which
        # the router sends to the backend process that owns it.
        headers = {}
        if dataflow:
            origin = f"{origin}?dataflow={dataflow}"
            headers["X-Curio-Dataflow"] = dataflow
        self._client.connect(
            origin, headers=headers, namespaces=[namespace], auth={"token": token},
            transports=["websocket"], socketio_path=path,
            wait_timeout=CONNECT_TIMEOUT_S,
        )
        self.transport = self._client.transport()

    def emit(self, event: str, data, callback=None) -> None:
        with self._send_lock:
            self._client.emit(event, data, namespace=self.namespace, callback=callback)

    def call(self, event: str, data, timeout: float):
        """Emit and wait for the server's answer. Never called on the socket's
        thread, which is the one that reads the answer."""
        answered = threading.Event()
        answers: list = []

        def acked(*args):
            answers.append(args[0] if args else None)
            answered.set()

        self.emit(event, data, callback=acked)
        if not answered.wait(timeout):
            raise TimeoutError(f"no answer to {event} in {timeout:.0f}s")
        return answers[0]

    def close(self) -> None:
        self._client.disconnect()


# ---------------------------------------------------------------------------
# When each update was everywhere
# ---------------------------------------------------------------------------

@dataclass
class _Sent:
    sender: str
    clock: int
    at: float
    waiting: set
    last: Optional[float] = None


class SyncLedger:
    """When each update a tab of the room sent was in every other tab that had
    synced when it was sent. Times are ``time.perf_counter()``: every tab of a
    run is in this one process."""

    def __init__(self):
        self._cond = threading.Condition()
        #: Each sender's client id -> what it sent, in the order of its clock.
        self._sent: dict[int, list[_Sent]] = {}
        #: (tab, sender's client id) -> how many of that sender's updates the
        #: tab is known to hold.
        self._held: dict[tuple[str, int], int] = {}
        self._tabs: set[str] = set()
        self._open = 0
        #: Each update's sync time, in seconds, once every other tab holds it.
        self.seconds: list[float] = []
        self.updates = 0
        #: Updates times the tabs each one reached.
        self.deliveries = 0

    def synced(self, tab: str) -> None:
        """*tab* holds the doc: what is sent from now on is waited for there."""
        with self._cond:
            self._tabs.add(tab)

    def left(self, tab: str) -> None:
        """*tab* is gone: no update waits for it any more."""
        with self._cond:
            self._tabs.discard(tab)
            for entries in self._sent.values():
                for entry in entries:
                    if tab in entry.waiting:
                        entry.waiting.discard(tab)
                        if not entry.waiting:
                            self._close(entry)
            self._cond.notify_all()

    def sent(self, sender: str, client_id: int, clock: int, at: float) -> None:
        """*sender* sent an update, which leaves its client's clock at *clock*."""
        with self._cond:
            waiting = self._tabs - {sender}
            self._sent.setdefault(client_id, []).append(_Sent(sender, clock, at, set(waiting)))
            self.updates += 1
            if waiting:
                self._open += 1

    def applied(self, tab: str, clocks: dict[int, int], at: float) -> None:
        """*tab* applied what the server sent, and its state vector is now
        *clocks*: each update it now holds is delivered there at *at*."""
        with self._cond:
            for client_id, clock in clocks.items():
                entries = self._sent.get(client_id)
                if not entries:
                    continue
                key = (tab, client_id)
                index = self._held.get(key, 0)
                while index < len(entries) and entries[index].clock <= clock:
                    entry = entries[index]
                    if tab in entry.waiting:
                        entry.waiting.discard(tab)
                        entry.last = at
                        self.deliveries += 1
                        if not entry.waiting:
                            self._close(entry)
                    index += 1
                self._held[key] = index
            self._cond.notify_all()

    def _close(self, entry: _Sent) -> None:
        self._open -= 1
        if entry.last is not None:
            self.seconds.append(entry.last - entry.at)

    @property
    def open(self) -> int:
        """Updates not yet in every tab they wait for."""
        with self._cond:
            return self._open

    def wait_settled(self, timeout: float) -> bool:
        """Whether every update reached every tab it waits for in *timeout*."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._open:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)
            return True

    def still_waiting(self, sender: str) -> tuple[int, list[str]]:
        """How many of *sender*'s updates some tab still lacks, and those tabs."""
        with self._cond:
            open_ones = [entry for entries in self._sent.values() for entry in entries
                         if entry.sender == sender and entry.waiting]
            return len(open_ones), sorted({tab for entry in open_ones for tab in entry.waiting})


# ---------------------------------------------------------------------------
# A room
# ---------------------------------------------------------------------------

class Room:
    """The tabs of one shared dataflow, and the phases they go through
    together. ``members[0]`` owns the dataflow. A room on a shared canvas
    (*shared*) also keeps what each member added and typed in it, the locks
    the server held once the members' work was over, and the owner's run of
    the dataflow on the server and its save."""

    def __init__(self, index: int, members: list[str], shared: bool = False):
        self.index = index
        self.members = list(members)
        self.owner = self.members[0]
        self.shared = shared
        #: The owner's dataflow, once it is created, and the nodes to type in:
        #: (node id, line comment of its language), from the owner's dataflow.
        self.project_id: Optional[str] = None
        self.targets: list[tuple[str, str]] = []
        #: On a shared canvas: the example the dataflow was made from, and the
        #: node of it each member's own node goes below, ``{id, x, y}``.
        self.example: Optional[str] = None
        self.parent: Optional[dict] = None
        #: Each member's own node, its connection and the node it reads
        #: (ids); and the node each member typed in, with the line it typed.
        self.added: dict[str, tuple[str, str, str]] = {}
        self.typed: dict[str, tuple[str, str]] = {}
        #: The locks the server held once every member's work was over, node
        #: id -> who, as the first tab there read them; None until read.
        self.locks_at_end: Optional[dict] = None
        self._locks_reader: Optional[str] = None
        #: The owner's run of the dataflow on the server, and its save read
        #: back, as the owner's driver records them (``VirtualUser.on_the_canvas``).
        self.server_run: Optional[dict] = None
        self.saved: Optional[dict] = None
        #: With ``--agents``, the members' agents (``agents.RoomAgents``).
        self.agents = None
        #: Set once the owner has invited its editors, or has failed to.
        self.invited = threading.Event()
        self.ledger = SyncLedger()
        self._cond = threading.Condition()
        self._reached: dict[str, set[str]] = {}
        self._gone: set[str] = set()
        self._digests: dict[str, str] = {}
        self._tabs: dict[str, dict] = {}
        self._settled: Optional[bool] = None
        self.diverged = False

    def arrive(self, phase: str, member: str) -> None:
        with self._cond:
            self._reached.setdefault(phase, set()).add(member)
            self._cond.notify_all()

    def wait_all(self, phase: str, timeout: float) -> bool:
        """Whether every member still in the room reached *phase* in *timeout*."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                reached = self._reached.get(phase, set())
                if all(m in reached or m in self._gone for m in self.members):
                    return True
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cond.wait(left)

    def reach(self, phase: str, member: str, timeout: float) -> bool:
        self.arrive(phase, member)
        return self.wait_all(phase, timeout)

    def leave(self, member: str) -> None:
        """*member* is gone: no phase waits for it, and no update for its tab."""
        with self._cond:
            self._gone.add(member)
            self._cond.notify_all()
        self.ledger.left(member)

    def present(self, member: str) -> bool:
        with self._cond:
            return member not in self._gone

    def registered_editors(self) -> list[str]:
        """The members, but the owner, whose accounts exist and who are still in."""
        with self._cond:
            reached = self._reached.get("registered", set())
            return [m for m in self.members[1:] if m in reached and m not in self._gone]

    def targets_for(self, member: str) -> list[tuple[str, str]]:
        """The nodes to type in, the one *member* starts with first, so a
        room's tabs spread over the dataflow's code and some share a node.

        On a shared canvas whose dataflow has no Python or JavaScript node
        (only Autark documents, which a typed line would break, and the
        canvas's own nodes), the members' own nodes instead, two members to a
        node, once every member's node is in (:meth:`add`)."""
        if self.targets:
            shift = self.members.index(member) % len(self.targets)
            return self.targets[shift:] + self.targets[:shift]
        if not self.shared:
            return []
        with self._cond:
            position = self.members.index(member)
            pair = self.members[position - position % 2]
            first = [self.added[pair][0]] if pair in self.added else []
            rest = [self.added[m][0] for m in self.members if m in self.added and m != pair]
        return [(node_id, "# ") for node_id in first + rest]

    def add(self, member: str, node_id: str, edge_id: str, parent_id: str) -> None:
        """*member* added its own node, connected below *parent_id*."""
        with self._cond:
            self.added[member] = (node_id, edge_id, parent_id)

    def typed_in(self, member: str, node_id: str, line: str) -> None:
        """*member* typed *line*, :data:`LINES_TYPED` times, in *node_id*."""
        with self._cond:
            self.typed[member] = (node_id, line)

    def reads_the_locks(self, member: str) -> bool:
        """Whether *member*'s tab is the one that reads the server's locks
        once every member's work is over: the first tab to ask."""
        with self._cond:
            if self._locks_reader is None:
                self._locks_reader = member
            return self._locks_reader == member

    def settle(self, member: str, timeout: float) -> bool:
        """Reach the "settled" phase; then the room's one verdict on whether
        every update was in every tab, taken by the first tab past it, so the
        tabs that go on to compare their docs are the same for all."""
        self.reach("settled", member, timeout)
        with self._cond:
            if self._settled is None:
                self._settled = self.ledger.open == 0
            return self._settled

    def check(self, member: str, digest: str, timeout: float) -> Optional[str]:
        """Once each tab still in gave its doc's digest, the member whose doc
        *member*'s differs from (the room's first one in), or None."""
        with self._cond:
            self._digests[member] = digest
        self.reach("checked", member, timeout)
        with self._cond:
            reference = next(m for m in self.members if m in self._digests)
            if self._digests[reference] == digest:
                return None
            self.diverged = True
            return reference

    def closed_tab(self, member: str, summary: dict) -> None:
        with self._cond:
            self._tabs[member] = summary

    def outcome(self) -> dict:
        """What the room's tabs did, for the report (``report.socket_summary``,
        and ``report.canvas_summary`` for a shared canvas's ``canvas``)."""
        with self._cond:
            tabs = list(self._tabs.values())
        state = [t["state_bytes"] for t in tabs if t.get("state_bytes") is not None]
        outcome = {
            "room": self.index,
            "project_id": self.project_id,
            "members": len(self.members),
            "tabs": sum(1 for t in tabs if t.get("synced")),
            "transports": sorted({t["transport"] for t in tabs if t.get("transport")}),
            "doc_ids": sorted({t["doc_id"] for t in tabs if t.get("doc_id")}),
            "updates": self.ledger.updates,
            "keystrokes": sum(t.get("keystrokes", 0) for t in tabs),
            "drags": sum(t.get("drags", 0) for t in tabs),
            "deliveries": self.ledger.deliveries,
            "sync_seconds": list(self.ledger.seconds),
            "unsynced": self.ledger.open,
            "diverged": self.diverged,
            "doc_state_bytes": max(state) if state else None,
        }
        if self.shared:
            outcome["canvas"] = self._canvas(tabs)
        if self.agents is not None:
            outcome["agents"] = self.agents.outcome(tabs)
        return outcome

    def _canvas(self, tabs: list[dict]) -> dict:
        """What the members did on the shared canvas: the nodes and
        connections they added, the locks they took, were refused and let go,
        those the server and the tabs still showed at the end, and the
        owner's run on the server and save."""
        held = None
        if self.locks_at_end is not None:
            held = sorted(f"{node_id} by {who}" for node_id, who in self.locks_at_end.items())
        return {
            "example": self.example,
            "nodes_added": sum(t.get("nodes_added", 0) for t in tabs),
            "edges_added": sum(t.get("edges_added", 0) for t in tabs),
            "locks": {
                "taken": sum(t.get("locks_taken", 0) for t in tabs),
                "refused": sum(t.get("locks_refused", 0) for t in tabs),
                "released": sum(t.get("locks_released", 0) for t in tabs),
                "held_at_end": held,
                "tabs_showing_locks": sum(1 for t in tabs if t.get("locks_left")),
            },
            "server_run": self.server_run,
            "saved": self.saved,
        }


# ---------------------------------------------------------------------------
# A tab
# ---------------------------------------------------------------------------

@dataclass
class _Cursor:
    """Where a tab types next in a node's code: after its own last keystroke,
    whatever other tabs typed since, as an editor's cursor stays."""

    node_id: str
    sticky: object = None


class Tab:
    """One user's tab of the room's dataflow.

    *record* is ``record(label, seconds, ok, error=None, kind=None)``, which
    keeps a sample on the user's result; *on_drop* is called when the socket
    closes under the tab.
    """

    def __init__(self, name: str, project_id: str, ledger: SyncLedger,
                 record: Callable, on_drop: Callable = lambda: None):
        self.name = name
        self.project_id = project_id
        self.ledger = ledger
        self.record = record
        self.on_drop = on_drop
        self.doc = doc_mapping.new_doc()
        self.lock = threading.Lock()
        with self.lock:
            self.client_id = self.doc.client_id
        self.link = None
        self.transport: Optional[str] = None
        self.role: Optional[str] = None
        #: Who this tab is in the room (its join's answer), which a lock names.
        self.participant_id: Optional[str] = None
        self.doc_id: Optional[str] = None
        self.synced = False
        self.closing = False
        self.dropped: Optional[str] = None
        self.keystrokes = self.drags = self.received = 0
        self.nodes_added = self.edges_added = 0
        self.locks_taken = self.locks_refused = self.locks_released = 0
        #: The locks this tab still showed at the end, ``node by who``; None
        #: until read (:meth:`wait_for_no_locks`).
        self.locks_left: Optional[list] = None
        self.state_bytes: Optional[int] = None
        self._remote = False
        self._local: list[bytes] = []
        self._have_doc = threading.Event()
        #: The messages sent and not answered yet, oldest first: each one's
        #: label and when it was sent. Guarded by the condition.
        self._acks = threading.Condition()
        self._waiting: deque = deque()
        self._cursor: Optional[_Cursor] = None
        #: The room's locks as the server told this tab of them, node id ->
        #: the lock (its holder's participant id and names), as the canvas
        #: keeps them; guarded by the condition. Each of :data:`ROOM_EVENTS`
        #: has its handler here.
        self._room = threading.Condition()
        self._locks: dict[str, dict] = {}
        self._room_handlers: dict[str, Callable] = {
            "node_locked": self._node_locked,
            "node_unlocked": self._node_unlocked,
            "user_left": self._user_left,
        }
        #: What the room's agents did as this tab was told of it (``--agents``,
        #: :data:`AGENT_EVENTS`), guarded by the room's condition: the asks it
        #: was told the end of, the agents in the room now (participant id ->
        #: name), and how many of their events came; and, once read at the
        #: end, the agents it still showed and the asks it was never told the
        #: end of (:meth:`wait_for_no_agents`, :meth:`wait_told_ends`).
        self._room_handlers.update({"agent_turn": self._agent_turn, "agent_joined": self._agent_joined,
                                    "agent_left": self._agent_left})
        self._asks_ended: set = set()
        self._agents_here: dict[str, str] = {}
        self.agent_events = self.agents_joined = self.agents_left = 0
        self.agents_shown: Optional[list] = None
        self.asks_untold: Optional[list] = None
        self.doc.observe(self._observed)

    # -- the server's messages ---------------------------------------------

    def _observed(self, event) -> None:
        if not self._remote:
            self._local.append(event.update)

    def receive(self, payload) -> None:
        """One ``yjs`` event: the server's step 1 is answered with what it
        lacks; its step 2 and updates are applied, and the ledger told. Or one
        :data:`KEPT_EVENT` message, which answers that many of the tab's
        queued updates."""
        if isinstance(payload, dict) and "answered" in payload:
            self._kept(payload)
            return
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, bytearray):
            message = bytes(message)
        if not isinstance(message, bytes) or len(message) < 2 or message[0] != YMessageType.SYNC:
            return  # awareness, which these tabs neither set nor read
        if message[1] == YSyncMessageType.SYNC_STEP1:
            with self.lock:
                answer = handle_sync_message(message[1:], self.doc)
            if answer:
                try:
                    self._send(answer, "socket yjs step 2")
                except TabFailed:
                    pass  # recorded; the tab's own thread meets the same socket
            return
        with self.lock:
            self._remote = True
            try:
                handle_sync_message(message[1:], self.doc)
            finally:
                self._remote = False
            clocks = state_vector(self.doc)
        at = time.perf_counter()
        self.received += 1
        if message[1] == YSyncMessageType.SYNC_STEP2:
            self._have_doc.set()
        self.ledger.applied(self.name, clocks, at)

    def room_event(self, name: str, payload) -> None:
        """One of the room's events (:data:`ROOM_EVENTS`), from the socket."""
        handler = self._room_handlers.get(name)
        if handler is None or not isinstance(payload, dict):
            return
        with self._room:
            handler(payload)
            self._room.notify_all()

    def _node_locked(self, payload: dict) -> None:
        if isinstance(payload.get("nodeId"), str):
            lock = payload.get("lock")
            self._locks[payload["nodeId"]] = lock if isinstance(lock, dict) else {}

    def _node_unlocked(self, payload: dict) -> None:
        self._locks.pop(payload.get("nodeId"), None)

    def _user_left(self, payload: dict) -> None:
        """A participant left, letting go of the locks it names; a node
        someone took since keeps its new lock, as on the canvas."""
        released = payload.get("released_locks")
        who = payload.get("participant_id")
        for node_id in released if isinstance(released, list) and who else ():
            if (self._locks.get(node_id) or {}).get("participant_id") == who:
                self._locks.pop(node_id, None)

    def room_locks(self) -> dict[str, str]:
        """The room's locks as this tab knows them: node id -> its holder."""
        with self._room:
            return {node_id: holder(lock) for node_id, lock in self._locks.items()}

    def wait_for_no_locks(self, timeout: float) -> dict[str, str]:
        """The locks this tab still shows after waiting up to *timeout* for
        none, node id -> its holder; kept as :attr:`locks_left`."""
        deadline = time.monotonic() + timeout
        with self._room:
            while self._locks:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._room.wait(left)
            shown = {node_id: holder(lock) for node_id, lock in self._locks.items()}
        self.locks_left = sorted(f"{node_id} by {who}" for node_id, who in shown.items())
        return shown

    # -- the room's agents (--agents) ---------------------------------------

    def _agent_turn(self, payload: dict) -> None:
        """An event of an ask (``{projectId, attachmentId, askId, seq, event,
        data}``): one that ends the ask is kept by its id."""
        ask_id = payload.get("askId")
        if not isinstance(ask_id, str):
            return
        self.agent_events += 1
        if payload.get("event") in ASK_ENDINGS:
            self._asks_ended.add(ask_id)

    def _agent_joined(self, payload: dict) -> None:
        who = payload.get("participant_id")
        if isinstance(who, str) and isinstance(payload.get("agent"), dict):
            self.agents_joined += 1
            self._agents_here[who] = str(payload.get("name") or "an agent")

    def _agent_left(self, payload: dict) -> None:
        who = payload.get("participant_id")
        if isinstance(who, str):
            self.agents_left += 1
            self._agents_here.pop(who, None)

    def wait_for_no_agents(self, timeout: float) -> dict[str, str]:
        """The agents this tab still shows in the room after waiting up to
        *timeout* for none, participant id -> name; kept as
        :attr:`agents_shown`."""
        deadline = time.monotonic() + timeout
        with self._room:
            while self._agents_here:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._room.wait(left)
            shown = dict(self._agents_here)
        self.agents_shown = sorted(shown.values())
        return shown

    def wait_told_ends(self, ask_ids: list, timeout: float) -> list[str]:
        """The asks of *ask_ids* this tab was not told the end of after
        waiting up to *timeout* for every end; kept as :attr:`asks_untold`."""
        deadline = time.monotonic() + timeout
        with self._room:
            while not set(ask_ids) <= self._asks_ended:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._room.wait(left)
            untold = sorted(set(ask_ids) - self._asks_ended)
        self.asks_untold = untold
        return untold

    def code_of(self, node_id: str) -> Optional[str]:
        """The node's code as this tab's doc holds it now; None for no such
        node, or one whose code is no text."""
        with self.lock:
            node = self.doc.get(NODES, type=Map).get(node_id)
            code = node.get(CODE_KEY) if isinstance(node, Map) else None
            return str(code) if isinstance(code, Text) else None

    def wait_for_code(self, expected: dict, timeout: float) -> dict:
        """The nodes of *expected* (node id -> code) whose code this tab's doc
        still does not hold after waiting up to *timeout*, each with what it
        holds instead."""
        deadline = time.monotonic() + timeout
        while True:
            wrong = {}
            for node_id, code in expected.items():
                held = self.code_of(node_id)
                if held != code:
                    wrong[node_id] = held
            if not wrong or time.monotonic() >= deadline:
                return wrong
            time.sleep(0.1)

    def server_room(self) -> dict:
        """The room as the server holds it now, as a tab joining the room now
        is told of it (``join_session``'s snapshot: its users, locks and
        Activity), asked again on this tab's socket."""
        ack = self._call("socket room agents", "join_session", {"projectId": self.project_id})
        snapshot = ack.get("snapshot")
        return snapshot if isinstance(snapshot, dict) else {}

    def _closed(self, reason=None) -> None:
        if self.closing:
            return
        self.dropped = str(reason)
        self.record("socket closed", 0.0, False,
                    f"the socket closed under the tab ({reason})", "socket")
        self.on_drop()

    # -- sending ------------------------------------------------------------

    def _send(self, message: bytes, label: str) -> None:
        """Send *message* in a ``yjs`` event; its answer is recorded when it
        comes: its ack, or the :data:`KEPT_EVENT` message that answers it
        when the ack says the server queued it."""
        sent = (label, time.perf_counter())
        with self._acks:
            self._waiting.append(sent)

        def acked(ack=None, *_rest):
            if isinstance(ack, dict) and ack.get("ok") is True and ack.get("queued"):
                return  # its answer comes in a kept message
            ok = isinstance(ack, dict) and ack.get("ok") is True
            self._answered(1, None if ok else [f"the server answered {ack!r}"])

        try:
            self.link.emit(EVENT, {"projectId": self.project_id, "message": message}, callback=acked)
        except Exception as exc:  # noqa: BLE001 - a dead socket is a finding
            with self._acks:
                if sent in self._waiting:
                    self._waiting.remove(sent)
                self._acks.notify_all()
            self.record(label, time.perf_counter() - sent[1], False,
                        f"{type(exc).__name__}: {exc}", "socket")
            raise TabFailed(label) from exc

    def _kept(self, payload: dict) -> None:
        """A :data:`KEPT_EVENT` message: it answers the tab's *answered*
        oldest messages, those it ``refused``, by why, as failures."""
        refused = payload.get("refused") if isinstance(payload.get("refused"), dict) else {}
        problems = [f"the server refused it ({why})" for why, count in refused.items()
                    for _ in range(int(count))]
        self._answered(int(payload.get("answered") or 0), problems)

    def _answered(self, count: int, problems: Optional[list] = None) -> None:
        """The server answered the tab's *count* oldest messages, in the order
        sent, which is the order it answers them: each is recorded with its
        time, the first ones of *problems* as failures."""
        now = time.perf_counter()
        with self._acks:
            done = [self._waiting.popleft() for _ in range(min(count, len(self._waiting)))]
            self._acks.notify_all()
        problems = problems or []
        for index, (label, started) in enumerate(done):
            problem = problems[index] if index < len(problems) else None
            self.record(label, now - started, problem is None, problem,
                        None if problem is None else "socket")

    def _call(self, label: str, event: str, data: dict, problem=None) -> dict:
        """Emit and wait for the answer; record it, and stop the tab on a
        refusal or on what *problem* (a function of the answer) finds wrong."""
        started = time.perf_counter()
        try:
            ack = self.link.call(event, data, CALL_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - a timeout or a dead socket
            self.record(label, time.perf_counter() - started, False,
                        f"{type(exc).__name__}: {exc}", "socket")
            raise TabFailed(label) from exc
        seconds = time.perf_counter() - started
        if not (isinstance(ack, dict) and ack.get("ok") is True):
            self.record(label, seconds, False, f"the server answered {ack!r}", "socket")
            raise TabFailed(label)
        wrong = problem(ack) if problem else None
        self.record(label, seconds, wrong is None, wrong, None if wrong is None else "socket")
        if wrong is not None:
            raise TabFailed(label)
        return ack

    def _publish(self, updates: list[bytes], clock: Optional[int]) -> None:
        if not updates:
            return
        self.ledger.sent(self.name, self.client_id, clock, time.perf_counter())
        for update in updates:
            self._send(create_update_message(update), "socket yjs update")

    # -- the session ----------------------------------------------------------

    def connect(self, make_link: Callable) -> None:
        """Open the socket: ``make_link(on_yjs, on_close)``."""
        started = time.perf_counter()
        try:
            self.link = make_link(self.receive, self._closed)
        except Exception as exc:  # noqa: BLE001 - refused, or never connected
            self.record("socket connect", time.perf_counter() - started, False,
                        f"{type(exc).__name__}: {exc}", "socket")
            raise TabFailed("socket connect") from exc
        self.transport = getattr(self.link, "transport", None)
        self.record("socket connect", time.perf_counter() - started, True)

    def join(self) -> None:
        """Join the room, as an owner or an editor: a watcher's changes are dropped."""
        def problem(ack):
            if ack.get("role") not in EDIT_ROLES:
                return (f"joined as {ack.get('role')!r}: the server drops a "
                        "watcher's changes, so the owner's invitation did not hold")
            return None

        ack = self._call("socket join_session", "join_session", {"projectId": self.project_id}, problem)
        self.role = ack.get("role")
        self.participant_id = ack.get("participant_id")
        # The room's locks when it joined, which the lock events then keep up
        # to date; one told of meanwhile stands.
        locks = (ack.get("snapshot") or {}).get("locks")
        with self._room:
            for node_id, lock in (locks.items() if isinstance(locks, dict) else ()):
                self._locks.setdefault(node_id, lock if isinstance(lock, dict) else {})

    def server_locks(self) -> dict[str, str]:
        """The locks the server holds now, node id -> its holder, as a tab
        joining the room now is told of them (``join_session``'s snapshot),
        asked again on this tab's socket."""
        ack = self._call("socket room locks", "join_session", {"projectId": self.project_id})
        locks = (ack.get("snapshot") or {}).get("locks")
        return {node_id: holder(lock) for node_id, lock in (locks.items() if isinstance(locks, dict) else ())}

    def sync(self) -> None:
        """Sync step 1; returns once the doc holds the server's (its step 2)."""
        with self.lock:
            step1 = create_sync_message(self.doc)
        ack = self._call("socket yjs sync", EVENT, {"projectId": self.project_id, "message": step1})
        self.doc_id = ack.get("docId")
        if not self._have_doc.wait(CALL_TIMEOUT_S):
            self.record("socket yjs sync", 0.0, False,
                        "the server answered the sync but never sent its doc (step 2)", "socket")
            raise TabFailed("socket yjs sync")
        self.synced = True

    def target(self, targets: list[tuple[str, str]]) -> tuple[str, str]:
        """The node to type in and its language's line comment: the first of
        *targets* whose code is text in the doc, else the doc's first such
        node, typed in with no comment."""
        def has_code(nodes, node_id) -> bool:
            node = nodes.get(node_id)
            return isinstance(node, Map) and isinstance(node.get(CODE_KEY), Text)

        with self.lock:
            nodes = self.doc.get(NODES, type=Map)
            for node_id, comment in targets:
                if has_code(nodes, node_id):
                    return node_id, comment
            order = [i for i in self.doc.get(NODE_ORDER, type=Array) if isinstance(i, str)]
            for node_id in order + sorted(set(nodes.keys()) - set(order)):
                if has_code(nodes, node_id):
                    return node_id, ""
        self.record("socket type", 0.0, False, "the room's dataflow has no node with code to type in", "socket")
        raise TabFailed("socket type")

    def keystroke(self, node_id: str, char: str) -> None:
        """Type *char* into the node's code after this tab's last keystroke
        there, the start of the code the first time."""
        with self.lock:
            code = self.doc.get(NODES, type=Map)[node_id][CODE_KEY]
            cursor = self._cursor if self._cursor and self._cursor.node_id == node_id else None
            at = 0 if cursor is None else min(cursor.sticky.get_index(), len(code))
            with self.doc.transaction():
                code.insert(at, char)
            self._cursor = _Cursor(node_id, code.sticky_index(at + len(char), Assoc.BEFORE))
            updates, self._local = self._local, []
            clock = state_vector(self.doc).get(self.client_id)
        self.keystrokes += 1
        self._publish(updates, clock)

    def drag(self, node_id: str) -> None:
        """Drag the node: its place, one value, moved by :data:`DRAG_STEP`."""
        with self.lock:
            node = self.doc.get(NODES, type=Map)[node_id]
            place = doc_mapping.decode(node.get(PLACE_KEY)) if PLACE_KEY in node else None
            place = place if isinstance(place, dict) else {}
            x, y = place.get(X_MEMBER), place.get(Y_MEMBER)
            x = x if isinstance(x, (int, float)) else 0
            y = y if isinstance(y, (int, float)) else 0
            with self.doc.transaction():
                node[PLACE_KEY] = doc_mapping.encode({X_MEMBER: x + DRAG_STEP, Y_MEMBER: y + DRAG_STEP})
            updates, self._local = self._local, []
            clock = state_vector(self.doc).get(self.client_id)
        self.drags += 1
        self._publish(updates, clock)

    def add_node(self, node: dict, edge: dict) -> None:
        """Add *node* and *edge*, each as Trill, as the canvas writes a node it
        adds and the connection it draws: one transaction from the dataflow
        the doc holds to the same with both (``doc_mapping.apply_dataflow``,
        the twin of the canvas's ``applyDataflow``), which also writes the
        nodes' and the connections' order again, as the canvas's does."""
        with self.lock:
            base = doc_mapping.doc_to_dataflow(self.doc)
            target = {**base, "nodes": [*(base.get("nodes") or []), node],
                      "edges": [*(base.get("edges") or []), edge]}
            doc_mapping.apply_dataflow(self.doc, base, target)
            updates, self._local = self._local, []
            clock = state_vector(self.doc).get(self.client_id)
        self.nodes_added += 1
        self.edges_added += 1
        self._publish(updates, clock)

    def _lock_call(self, label: str, event: str, node_id: str):
        """Send a lock event for *node_id* and return its answer, recording
        how long it took only when it fails to come."""
        started = time.perf_counter()
        try:
            ack = self.link.call(event, {"projectId": self.project_id, "nodeId": node_id}, CALL_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - a timeout or a dead socket
            self.record(label, time.perf_counter() - started, False,
                        f"{type(exc).__name__}: {exc}", "socket")
            raise TabFailed(label) from exc
        return ack, time.perf_counter() - started

    def take_lock(self, node_id: str) -> bool:
        """Ask for the node's lock, as the canvas does when the node takes
        focus (``node_lock``): whether this tab holds it now. Another
        participant's lock is no failure (:data:`LOCKED_BY_OTHER`): locks are
        soft, and the canvas only shows a chip and still lets one type."""
        ack, seconds = self._lock_call("socket node_lock", "node_lock", node_id)
        if isinstance(ack, dict) and ack.get("ok") is True:
            self.locks_taken += 1
            self.record("socket node_lock", seconds, True)
            return True
        if isinstance(ack, dict) and ack.get("error") == LOCKED_BY_OTHER:
            self.locks_refused += 1
            self.record("socket node_lock", seconds, True)
            return False
        self.record("socket node_lock", seconds, False, f"the server answered {ack!r}", "socket")
        return False

    def release_lock(self, node_id: str) -> None:
        """Let go of the node's lock, which this tab holds, as the canvas does
        when focus leaves the node (``node_unlock``)."""
        ack, seconds = self._lock_call("socket node_unlock", "node_unlock", node_id)
        if isinstance(ack, dict) and ack.get("ok") is True:
            self.locks_released += 1
            self.record("socket node_unlock", seconds, True)
            return
        self.record("socket node_unlock", seconds, False,
                    f"the server answered {ack!r} to letting go of node {node_id}'s lock, "
                    "which this tab held", "socket")

    def work(self, targets: list[tuple[str, str]], pacing, *, lock: bool = False) -> tuple[str, str]:
        """Type :data:`LINES_TYPED` lines into a node's code, dragging the node
        after every :data:`DRAG_EVERY` keystrokes, at *pacing*'s pace
        (``key_gap()``, and ``pause()`` after each drag): the node, and the
        line typed. With *lock*, the node's lock is asked for first and let go
        of after, if this tab got it (:meth:`take_lock`)."""
        node_id, comment = self.target(targets)
        line = TYPED_LINE.format(prefix=comment, user=self.name)
        held = self.take_lock(node_id) if lock else False
        for count, char in enumerate(line * LINES_TYPED, 1):
            self.keystroke(node_id, char)
            if count % DRAG_EVERY == 0:
                self.drag(node_id)
                pause = pacing.pause()
                if pause:
                    time.sleep(pause)
            gap = pacing.key_gap()
            if gap:
                time.sleep(gap)
        if held:
            self.release_lock(node_id)
        return node_id, line

    def wait_for_answers(self, timeout: float) -> bool:
        """Whether the server answered every update this tab sent in *timeout*."""
        deadline = time.monotonic() + timeout
        with self._acks:
            while self._waiting:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._acks.wait(left)
            missing = len(self._waiting)
        if missing:
            self.record("socket yjs update", timeout, False,
                        f"{missing} update(s) had no answer in {timeout:.0f}s", "socket")
        return not missing

    def digest(self) -> str:
        """What the room's tabs edit in the doc, as a digest the room's tabs
        compare: its nodes, in the doc's order, each with its type, code and
        place, and its connections, each with its ends, handles and type; and
        the size of the doc a tab joining now would download.

        Not the whole dataflow: a spec written outside the doc, as the owner's
        save of its outputs writes one, reaches the doc as the server's own
        transaction at its next write (``dataflow_docs._catch_up``), relayed
        to every tab a moment later, so tabs reading at that moment would
        differ for no fault. Such a write changes the dataflow's datasets,
        never which nodes and connections it has, nor a node's code or place."""
        with self.lock:
            dataflow = doc_mapping.doc_to_dataflow(self.doc)
            self.state_bytes = len(self.doc.get_update())
        nodes = [[node.get("id"), node.get("type"), node.get(CODE_KEY), node.get("x"), node.get("y")]
                 for node in dataflow.get("nodes") or [] if isinstance(node, dict)]
        edges = [[edge.get(name) for name in EDGE_FIELDS]
                 for edge in dataflow.get("edges") or [] if isinstance(edge, dict)]
        return hashlib.sha256(json.dumps({"nodes": nodes, "edges": edges}).encode("utf-8")).hexdigest()

    def dataflow(self) -> dict:
        """The Trill ``dataflow`` the tab's doc holds now."""
        with self.lock:
            return doc_mapping.doc_to_dataflow(self.doc)

    def close(self) -> None:
        self.closing = True
        if self.link is not None:
            try:
                self.link.close()
            except Exception:  # noqa: BLE001 - closing a dead socket
                pass

    def summary(self) -> dict:
        return {
            "transport": self.transport, "role": self.role, "doc_id": self.doc_id,
            "synced": self.synced, "keystrokes": self.keystrokes, "drags": self.drags,
            "received": self.received, "state_bytes": self.state_bytes,
            "dropped": self.dropped,
            "nodes_added": self.nodes_added, "edges_added": self.edges_added,
            "locks_taken": self.locks_taken, "locks_refused": self.locks_refused,
            "locks_released": self.locks_released, "locks_left": self.locks_left,
            "agent_events": self.agent_events, "agents_joined": self.agents_joined,
            "agents_left": self.agents_left, "agents_shown": self.agents_shown,
            "asks_untold": self.asks_untold,
        }


# ---------------------------------------------------------------------------
# One user's tab, from the room's invitation to its close
# ---------------------------------------------------------------------------

def _add_own_node(user, room: Room, tab: Tab) -> None:
    """Add *user*'s own node below the room's node it reads (``room.parent``),
    then wait until every member's node is in every tab, as a person looks at
    the canvas before typing: a member may type in another's node."""
    node, edge = member_node(room.parent, room.members.index(user.name) + 1)
    tab.add_node(node, edge)
    user.own_node = node
    room.add(user.name, node["id"], edge["id"], room.parent["id"])
    room.reach("added", user.name, ROOM_WAIT_S)
    # A member whose node is not everywhere by then is reported by the
    # settling after the typing, as any update is.
    room.ledger.wait_settled(SETTLE_TIMEOUT_S)


def _locks_at_the_end(user, room: Room, tab: Tab) -> None:
    """Once every member's work is over, and before any tab closes, which
    would let go of its locks: the locks the server holds, read by the room's
    first tab there as a tab joining then is told of them, and those this tab
    still shows. Every member let go of each lock it got, so each is a
    failure (``locked``)."""
    record = user.socket_sample
    if room.reads_the_locks(user.name):
        held = tab.server_locks()
        room.locks_at_end = held
        if held:
            record("socket locks", 0.0, False,
                   f"the server still held {len(held)} lock(s) once every member's work was over: "
                   + ", ".join(f"node {node_id} by {who}" for node_id, who in sorted(held.items())),
                   "locked")
    shown = tab.wait_for_no_locks(SETTLE_TIMEOUT_S)
    if shown:
        record("socket locks", SETTLE_TIMEOUT_S, False,
               f"its tab still showed {len(shown)} lock(s) {SETTLE_TIMEOUT_S:.0f}s after every member's "
               "work was over: " + ", ".join(f"node {node_id} by {who}" for node_id, who in sorted(shown.items())),
               "locked")


def run_tab(user, room: Room, *, backend_url: str, namespace: str, pacing,
            make_link: Optional[Callable] = None) -> bool:
    """Open *user*'s tab of its room's dataflow, type and drag with the rest of
    the room, check every tab holds the same doc, and keep the tab open until
    the user's dataflow run is done (``user.dataflow_done``).

    On a shared canvas (``room.shared``), run on the user's own thread, the
    member adds its own node first (:func:`_add_own_node`), takes the lock of
    the node it types in, works on the dataflow once the room's docs agree
    (``user.on_the_canvas``), and the room's locks are read once every
    member's work is over (:func:`_locks_at_the_end`).

    Whether the tab got through; each failure is recorded on the user
    (``user.socket_sample``)."""
    record = user.socket_sample
    tab: Optional[Tab] = None
    through = False
    try:
        if not room.invited.wait(ROOM_WAIT_S):
            record("socket room", ROOM_WAIT_S, False,
                   f"the room's owner had not invited its editors after {ROOM_WAIT_S:.0f}s", "socket")
            return False
        if room.project_id is None or not room.present(user.name):
            if room.shared:
                # Its owner's failure to make the dataflow or to invite it is
                # recorded on the owner; that this member did none of its
                # work on the canvas, here.
                record("socket room", 0.0, False,
                       "it was left out of its room's shared dataflow (its owner did not make it, "
                       "or could not invite it), so it did none of its work there", "socket")
            return False  # no dataflow to open: what stopped it is recorded where it happened
        tab = Tab(user.name, room.project_id, room.ledger, record,
                  on_drop=lambda: room.leave(user.name))
        on_room = tab.room_event
        tab.connect(make_link or (lambda on_yjs, on_close: SocketLink(
            backend_url, namespace, user.token, on_yjs, on_close, on_room=on_room,
            dataflow=room.project_id)))
        tab.join()
        tab.sync()
        room.ledger.synced(user.name)
        if not room.reach("synced", user.name, ROOM_WAIT_S):
            record("socket room", ROOM_WAIT_S, False,
                   f"the rest of the room had not synced after {ROOM_WAIT_S:.0f}s", "socket")
        if room.shared:
            _add_own_node(user, room, tab)
        if room.agents is not None:
            room.agents.ask_early(user, tab)
        typed = tab.work(room.targets_for(user.name), pacing, lock=room.shared)
        if room.shared:
            room.typed_in(user.name, *typed)
        tab.wait_for_answers(CALL_TIMEOUT_S)
        room.reach("typed", user.name, ROOM_WAIT_S)
        if not room.ledger.wait_settled(SETTLE_TIMEOUT_S):
            count, tabs = room.ledger.still_waiting(user.name)
            if count:
                record("socket settle", SETTLE_TIMEOUT_S, False,
                       f"{count} of its updates were not in every other tab "
                       f"{SETTLE_TIMEOUT_S:.0f}s after the room's last: {', '.join(tabs)} lack some",
                       "unsynced")
        if room.agents is not None:
            room.agents.before_compare(user, tab)
        if room.settle(user.name, ROOM_WAIT_S):
            # Only once every update is everywhere: a missing one is reported
            # above, and would make every tab differ for the same reason.
            other = room.check(user.name, tab.digest(), ROOM_WAIT_S)
            if other is not None:
                record("socket converge", 0.0, False,
                       f"its nodes, connections, code or places differ from {other}'s tab's, "
                       "with every update in both", "diverged")
        else:
            tab.digest()  # the doc's size, all the same
        if room.shared:
            through = user.on_the_canvas(tab)
            room.reach("done", user.name, DONE_WAIT_S)
            if room.agents is not None:
                room.agents.at_the_end(user, tab)
            _locks_at_the_end(user, room, tab)
            room.reach("locks read", user.name, ROOM_WAIT_S)
        else:
            user.dataflow_done.wait()
            through = True
    except TabFailed:
        pass  # what happened is already recorded
    except Exception as exc:  # noqa: BLE001 - a crashed tab is a finding too
        record("socket tab", 0.0, False, f"{type(exc).__name__}: {exc}", "socket")
    finally:
        if tab is not None:
            tab.close()
            user.result.tab = tab.summary()
            room.closed_tab(user.name, user.result.tab)
        room.leave(user.name)
    return through
