"""A tab whose ping is overdue is closed inside a send to it, and leaves its doc
on a thread of its own.

engineio closes a client whose ping is overdue from inside a send to it
(``Socket.send``, ``check_ping_timeout``) and runs its disconnect there, on the
sending thread, which holds the client's send lock (``extensions.whole_sends``).
The collaboration's disconnect takes the lock of each doc the tab synced
(``dataflow_docs.leave``), and a relay holds a doc's lock while it waits for
each tab's send lock: the two threads waited for each other for good. The 11-07
flake hunt's stress repeat 4 (run 42382836219) stalled a room of 100 users that
way, and from then on every client whose socket hashed to the stuck lock hung
at its first send, so 40 to 50% of connects failed until the run ended.

Flask-SocketIO's test client never goes through engineio's sockets or their
pings, so here the backend app is served as the backend serves it, over
WebSocket. Its tab C is synced to a dataflow and then quiet: it answers nothing
the server sends. C's ping is made overdue by hand; no real ping, and none of
engineio's own checks of overdue pings, comes during a test. Each client's send
lock gives up after :data:`GIVES_UP_S` here, so a deadlock fails the test
instead of hanging the suite.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest
from werkzeug.serving import WSGIRequestHandler, make_server

from ._support import NAMESPACE, make_project, make_user

#: alice's dataflow: one node with code.
SPEC = {
    "dataflow": {
        "nodes": [{"id": "loader", "type": "curio.builtin/code", "x": 10, "y": 20,
                   "content": "x = 1\n", "out": "DATAFRAME", "in": "DEFAULT", "goal": "",
                   "metadata": {"keywords": []}}],
        "edges": [],
        "name": "Shared", "task": "", "timestamp": 1, "provenance_id": "Shared",
    },
}

#: The longest any wait here takes before the test fails: a hang is a finding.
WAIT_S = 15.0
#: How long a send waits for a client's send lock here before it raises: a
#: deadlock on one ends the test, never the suite.
GIVES_UP_S = 30.0
#: engineio's interval between pings here: no ping comes during a test.
PING_INTERVAL_S = 600
#: A Yjs update that brings nothing, which a relay sends as it sends any.
NOTHING = b"\x00\x00"


class _GivesUp:
    """A client's send lock (``extensions._CLIENT_LOCKS``) whose wait raises
    after :data:`GIVES_UP_S`."""

    def __init__(self):
        self._lock = threading.Lock()

    def __enter__(self):
        if not self._lock.acquire(timeout=GIVES_UP_S):
            raise TimeoutError(f"a client's send lock was held for {GIVES_UP_S:.0f}s")
        return self

    def __exit__(self, *_exc):
        self._lock.release()


def _request_handler():
    """The backend's request handler (``server.RequestHandler``), made here:
    importing ``server`` makes an app of its own."""
    from utk_curio.common.request_deadline import RequestHeadDeadline

    return type("RequestHandler", (RequestHeadDeadline, WSGIRequestHandler), {})


@dataclass
class _Tab:
    """Tab C, synced to alice's dataflow, as the server holds it."""

    sio: object
    entry: object
    room: str
    sid: str
    eio_sid: str
    socket: object


@pytest.fixture()
def tab(monkeypatch, tmp_path):
    """The backend app on a database file, since its sockets' threads read and
    write it, served by Werkzeug; and alice's tab C of her dataflow over
    WebSocket, joined and synced."""
    from pycrdt import create_sync_message

    from utk_curio.backend import extensions as _ext
    from utk_curio.backend.app import create_app
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping, room_state
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.tests.stress.sockets import TabClient

    class Config:
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'collab.db'}"
        SQLALCHEMY_TRACK_MODIFICATIONS = False
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False

    monkeypatch.setattr(_ext, "socketio", None, raising=True)
    monkeypatch.setattr(dataflow_docs, "BACKGROUND", False, raising=True)
    monkeypatch.setattr(_ext, "_CLIENT_LOCKS", tuple(_GivesUp() for _ in _ext._CLIENT_LOCKS))
    application = create_app(Config)
    # After the app is made, so its start seeds the packages where it always does.
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path))
    sio = application.extensions["socketio"]
    eio = sio.server.eio
    eio.ping_interval = PING_INTERVAL_S
    # engineio's own thread checks each socket's ping holding no client's send
    # lock: here the overdue ping is found by a send.
    eio.start_service_task = False

    with application.app_context():
        _ext.db.create_all()
        room_state.reset_for_tests()
        dataflow_docs.reset_for_tests()
        alice, session = make_user("alice")
        project_id = make_project(alice)
        owner_key, token = str(alice.id), session.token
        # Ends this thread's read: the server's threads write (the handshake
        # touches the sign-in).
        _ext.db.session.commit()
        storage.write_spec(owner_key, project_id, SPEC)
        httpd = make_server("127.0.0.1", 0, application, threaded=True, request_handler=_request_handler())
        # A WebSocket's request thread lasts as long as its socket: closing the
        # server waits for none.
        httpd.block_on_close = False
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        # python-socketio's client on the stress tabs' in-order engineio client,
        # with no handlers: C answers nothing, so nothing more is sent to it.
        client = TabClient(reconnection=False, handle_sigint=False, logger=False,
                           engineio_logger=False, request_timeout=WAIT_S)
        try:
            client.connect(f"http://127.0.0.1:{httpd.server_port}", namespaces=[NAMESPACE],
                           auth={"token": token}, transports=["websocket"], wait_timeout=WAIT_S)
            joined = client.call("join_session", {"projectId": project_id}, namespace=NAMESPACE,
                                 timeout=WAIT_S)
            assert joined.get("ok") is True and joined.get("role") == "owner", joined
            # Sync step 1, which the server answers with its step 2 and its own
            # step 1 before this ack.
            step1 = create_sync_message(doc_mapping.new_doc())
            synced = client.call(dataflow_docs.EVENT, {"projectId": project_id, "message": step1},
                                 namespace=NAMESPACE, timeout=WAIT_S)
            assert synced.get("ok") is True, synced
            sid = client.get_sid(NAMESPACE)
            entry = dataflow_docs._open_entry(project_id)
            assert entry is not None and list(entry.tabs) == [sid], "C is not the doc's one tab"
            eio_sid = sio.server.manager.eio_sid_from_sid(sid, NAMESPACE)
            yield _Tab(sio=sio, entry=entry, room=room_state.room_for(project_id), sid=sid,
                       eio_sid=eio_sid, socket=eio.sockets[eio_sid])
        finally:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001 - a socket the server closed
                pass
            httpd.shutdown()
            httpd.server_close()
            dataflow_docs.reset_for_tests()
            room_state.reset_for_tests()
            _ext.db.session.remove()
            _ext.db.engine.dispose()


def _leave_entered(monkeypatch, sid: str, held: list | None = None) -> threading.Event:
    """Set once the disconnect of the socket *sid* enters ``dataflow_docs.leave``,
    its first step, before it takes the doc's lock. *held* gets whether that
    thread held a client's sends then (``extensions.whole_sends``)."""
    from utk_curio.backend import extensions
    from utk_curio.backend.app.collaboration import dataflow_docs

    entered = threading.Event()
    leave = dataflow_docs.leave

    def leaving(left: str) -> None:
        if left == sid:
            if held is not None:
                held.append(getattr(extensions._holding, "held", False))
            entered.set()
        leave(left)

    monkeypatch.setattr(dataflow_docs, "leave", leaving)
    return entered


def _overdue(tab: _Tab) -> None:
    """C's ping is overdue: engineio's socket notes when it pinged last
    (``last_ping``, ``None`` between a pong and the next ping)."""
    tab.socket.last_ping = time.time() - tab.socket.server.ping_timeout - 60


def _send_kept(tab: _Tab) -> tuple[threading.Thread, list]:
    """A thread that sends C a batch's answer, ``yjs_kept``, as the doc's
    thread does once the batch is applied, outside the doc's lock
    (``dataflow_docs._send_kept``); and the errors it meets."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    errors: list = []

    def send() -> None:
        try:
            dataflow_docs._send_kept(tab.entry, {tab.sid: {"answered": 1, "kept": {}, "refused": {}}})
        except Exception as exc:  # noqa: BLE001 - reported by the test
            errors.append(exc)

    thread = threading.Thread(target=send, name="kept answer to C", daemon=True)
    thread.start()
    return thread, errors


def _left(tab: _Tab) -> bool:
    """Whether C's disconnect is over: C left its doc and its room, and the
    Socket.IO server forgot its socket, the disconnect's last step."""
    from utk_curio.backend.app.collaboration import room_state

    return (tab.sid not in tab.entry.tabs and not room_state.is_member(tab.room, tab.sid)
            and tab.eio_sid not in tab.sio.server.environ)


def _wait_for(ready, message: str) -> None:
    deadline = time.monotonic() + WAIT_S
    while not ready():
        assert time.monotonic() < deadline, message
        time.sleep(0.01)


def test_a_relay_to_a_tab_closed_inside_a_send_does_not_wait_for_the_tabs_disconnect(tab, monkeypatch):
    """The hunt's two threads: one sends C its kept answer outside the doc's
    lock and finds C's ping overdue, while the other relays the doc to C under
    the doc's lock. The relay ends, and C leaves the doc and the room."""
    from utk_curio.backend.app.collaboration import dataflow_docs

    entered = _leave_entered(monkeypatch, tab.sid)
    holds = threading.Event()
    outcome: list = []

    def relay() -> None:
        try:
            with tab.entry.lock:
                holds.set()
                if not entered.wait(WAIT_S):
                    outcome.append(f"C's disconnect had not reached its doc after {WAIT_S:.0f}s")
                    return
                if not tab.socket.closing:
                    outcome.append("C's disconnect did not come from the close of its overdue ping")
                    return
                dataflow_docs._relay(tab.entry, [(None, [NOTHING])])
            outcome.append("relayed")
        except Exception as exc:  # noqa: BLE001 - reported below
            outcome.append(f"{type(exc).__name__}: {exc}")

    relayer = threading.Thread(target=relay, name="relay to C under the doc's lock", daemon=True)
    relayer.start()
    assert holds.wait(WAIT_S), "the relay never took the doc's lock"
    _overdue(tab)
    sender, errors = _send_kept(tab)
    relayer.join(WAIT_S)
    stuck = relayer.is_alive()
    # Where the disconnect runs under C's send lock, the relay's wait for that
    # lock gives up after GIVES_UP_S, and both threads end before the test does.
    relayer.join(GIVES_UP_S + WAIT_S)
    sender.join(GIVES_UP_S + WAIT_S)
    assert not relayer.is_alive() and not sender.is_alive(), "a thread of the test never ended"
    assert not stuck, (
        f"the relay to C under the doc's lock was still waiting {WAIT_S:.0f}s on: C's disconnect, "
        "run inside the send that found its ping overdue, held C's send lock while it waited "
        f"for the doc's lock the relay held ({outcome})"
    )
    assert outcome == ["relayed"], outcome
    assert not errors, errors
    _wait_for(lambda: _left(tab), f"C was still in its doc or its room {WAIT_S:.0f}s after the relay")


def test_a_tab_closed_inside_a_send_leaves_on_a_thread_that_holds_no_clients_sends(tab, monkeypatch):
    """C's disconnect emits to its rooms: the room hears ``user_left``, and C's
    awareness is cleared for the doc's other tabs. Run inside the send that
    closed C, which holds C's send lock, each of those emits would take no
    member's lock (``whole_sends``), so another thread's packet could land
    between the packets of a doc message to that member."""
    held: list = []
    entered = _leave_entered(monkeypatch, tab.sid, held)
    _overdue(tab)
    sender, errors = _send_kept(tab)
    assert entered.wait(WAIT_S), f"C's disconnect had not reached its doc after {WAIT_S:.0f}s"
    sender.join(WAIT_S)
    assert not sender.is_alive(), f"the send to C had not returned after {WAIT_S:.0f}s"
    assert not errors, errors
    assert tab.socket.closing, "C's disconnect did not come from the close of its overdue ping"
    assert held == [False], (
        "C's disconnect ran on the thread whose send found its ping overdue, holding C's send "
        "lock: its emits took no member's send lock"
    )
    _wait_for(lambda: _left(tab), f"C was still in its doc or its room after {WAIT_S:.0f}s")
