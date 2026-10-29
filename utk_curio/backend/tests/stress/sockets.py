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
from collections import deque
from dataclasses import dataclass, field
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
CONNECT_TIMEOUT_S = 60.0
CALL_TIMEOUT_S = 60.0
ROOM_WAIT_S = 300.0
SETTLE_TIMEOUT_S = 60.0

#: The roles whose changes the server applies (``projects/access.py``).
EDIT_ROLES = ("owner", "editor")

#: The Socket.IO event the doc's messages travel in.
EVENT = doc_mapping.EVENT
#: The event that answers a tab's updates the server queued, once applied.
KEPT_EVENT = doc_mapping.KEPT_EVENT
#: The doc's roots that hold the nodes by id, and their order.
NODES, NODE_ORDER = "nodes", "nodeOrder"

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
    the answers to the tab's queued updates (:data:`KEPT_EVENT`)."""

    def __init__(self, backend_url: str, namespace: str, token: str,
                 on_yjs: Callable, on_close: Callable):
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
        origin, path = socket_target(backend_url)
        self._client.connect(
            origin, namespaces=[namespace], auth={"token": token},
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
    together. ``members[0]`` owns the dataflow."""

    def __init__(self, index: int, members: list[str]):
        self.index = index
        self.members = list(members)
        self.owner = self.members[0]
        #: The owner's dataflow, once it is created, and the nodes to type in:
        #: (node id, line comment of its language), from the owner's dataflow.
        self.project_id: Optional[str] = None
        self.targets: list[tuple[str, str]] = []
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
        room's tabs spread over the dataflow's code and some share a node."""
        if not self.targets:
            return []
        shift = self.members.index(member) % len(self.targets)
        return self.targets[shift:] + self.targets[:shift]

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
        """What the room's tabs did, for the report (``report.socket_summary``)."""
        with self._cond:
            tabs = list(self._tabs.values())
        state = [t["state_bytes"] for t in tabs if t.get("state_bytes") is not None]
        return {
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
        self.doc_id: Optional[str] = None
        self.synced = False
        self.closing = False
        self.dropped: Optional[str] = None
        self.keystrokes = self.drags = self.received = 0
        self.state_bytes: Optional[int] = None
        self._remote = False
        self._local: list[bytes] = []
        self._have_doc = threading.Event()
        #: The messages sent and not answered yet, oldest first: each one's
        #: label and when it was sent. Guarded by the condition.
        self._acks = threading.Condition()
        self._waiting: deque = deque()
        self._cursor: Optional[_Cursor] = None
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

        self.role = self._call("socket join_session", "join_session",
                               {"projectId": self.project_id}, problem).get("role")

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

    def work(self, targets: list[tuple[str, str]], pacing) -> None:
        """Type :data:`LINES_TYPED` lines into a node's code, dragging the node
        after every :data:`DRAG_EVERY` keystrokes, at *pacing*'s pace
        (``key_gap()``, and ``pause()`` after each drag)."""
        node_id, comment = self.target(targets)
        text = "".join(TYPED_LINE.format(prefix=comment, user=self.name) for _ in range(LINES_TYPED))
        for count, char in enumerate(text, 1):
            self.keystroke(node_id, char)
            if count % DRAG_EVERY == 0:
                self.drag(node_id)
                pause = pacing.pause()
                if pause:
                    time.sleep(pause)
            gap = pacing.key_gap()
            if gap:
                time.sleep(gap)

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
        """What the room's tabs edit in the doc, each node's code and place, as
        a digest the room's tabs compare; and the size of the doc a tab
        joining now would download.

        Not the whole dataflow: a spec written outside the doc, as the owner's
        save of its outputs writes one, reaches the doc as the server's own
        transaction at its next write (``dataflow_docs._catch_up``), relayed
        to every tab a moment later, so tabs reading at that moment would
        differ for no fault. Such a write changes the dataflow's datasets,
        never a node's code or place."""
        with self.lock:
            dataflow = doc_mapping.doc_to_dataflow(self.doc)
            self.state_bytes = len(self.doc.get_update())
        edits = {
            node.get("id"): [node.get(CODE_KEY), node.get("x"), node.get("y")]
            for node in dataflow.get("nodes") or [] if isinstance(node, dict)
        }
        return hashlib.sha256(json.dumps(edits, sort_keys=True).encode("utf-8")).hexdigest()

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
        }


# ---------------------------------------------------------------------------
# One user's tab, from the room's invitation to its close
# ---------------------------------------------------------------------------

def run_tab(user, room: Room, *, backend_url: str, namespace: str, pacing,
            make_link: Optional[Callable] = None) -> None:
    """Open *user*'s tab of its room's dataflow, type and drag with the rest of
    the room, check every tab holds the same doc, and keep the tab open until
    the user's dataflow run is done (``user.dataflow_done``). Each failure is
    recorded on the user (``user.socket_sample``)."""
    record = user.socket_sample
    tab: Optional[Tab] = None
    try:
        if not room.invited.wait(ROOM_WAIT_S):
            record("socket room", ROOM_WAIT_S, False,
                   f"the room's owner had not invited its editors after {ROOM_WAIT_S:.0f}s", "socket")
            return
        if room.project_id is None or not room.present(user.name):
            return  # no dataflow to open: what stopped it is recorded where it happened
        tab = Tab(user.name, room.project_id, room.ledger, record,
                  on_drop=lambda: room.leave(user.name))
        tab.connect(make_link or (lambda on_yjs, on_close: SocketLink(
            backend_url, namespace, user.token, on_yjs, on_close)))
        tab.join()
        tab.sync()
        room.ledger.synced(user.name)
        if not room.reach("synced", user.name, ROOM_WAIT_S):
            record("socket room", ROOM_WAIT_S, False,
                   f"the rest of the room had not synced after {ROOM_WAIT_S:.0f}s", "socket")
        tab.work(room.targets_for(user.name), pacing)
        tab.wait_for_answers(CALL_TIMEOUT_S)
        room.reach("typed", user.name, ROOM_WAIT_S)
        if not room.ledger.wait_settled(SETTLE_TIMEOUT_S):
            count, tabs = room.ledger.still_waiting(user.name)
            if count:
                record("socket settle", SETTLE_TIMEOUT_S, False,
                       f"{count} of its updates were not in every other tab "
                       f"{SETTLE_TIMEOUT_S:.0f}s after the room's last: {', '.join(tabs)} lack some",
                       "unsynced")
        if room.settle(user.name, ROOM_WAIT_S):
            # Only once every update is everywhere: a missing one is reported
            # above, and would make every tab differ for the same reason.
            other = room.check(user.name, tab.digest(), ROOM_WAIT_S)
            if other is not None:
                record("socket converge", 0.0, False,
                       f"its nodes' code and places differ from {other}'s tab's, "
                       "with every update in both", "diverged")
        else:
            tab.digest()  # the doc's size, all the same
        user.dataflow_done.wait()
    except TabFailed:
        pass
    except Exception as exc:  # noqa: BLE001 - a crashed tab is a finding too
        record("socket tab", 0.0, False, f"{type(exc).__name__}: {exc}", "socket")
    finally:
        if tab is not None:
            tab.close()
            user.result.tab = tab.summary()
            room.closed_tab(user.name, user.result.tab)
        room.leave(user.name)
