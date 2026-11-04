import random
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from flask import has_app_context
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError


db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):
    """Make SQLite behave under concurrent requests.

    Out of the box SQLite runs a rollback journal with a 5 s busy timeout: any
    writer blocks every reader for the duration of its transaction, and a
    reader that waits longer than 5 s gets ``OperationalError: database is
    locked`` -- which the API surfaces as a 500. Under load (the parallel e2e
    run measured 192 of them on one backend in ~25 minutes; ``GET /api/projects``
    500ing is what turned whole workflow groups into setup errors) that is
    routine, not exceptional.

    WAL lets readers proceed while one writer commits; ``busy_timeout`` makes a
    genuinely contended writer wait instead of failing; ``synchronous=NORMAL``
    is the usual WAL companion (durable across process crashes, not power
    loss -- the standard trade-off for a WAL database). This is NOT a test-only
    setting: it is applied per connection on every engine this process creates,
    so a deployed backend, a dev ``curio.py start``, the migrations and the test
    rig all run the same way. A multi-tab or multi-user deployment on SQLite
    hits exactly the same reader/writer contention.
    A ``:memory:`` database answers ``journal_mode=WAL`` with ``memory`` and is
    otherwise unaffected, so the unit suites keep their in-memory engines.
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Who holds the write lock
# ---------------------------------------------------------------------------

# The statements the sqlite3 driver opens a transaction for: it keeps its
# legacy transaction control here, so a SELECT runs outside any transaction
# and only these begin one, which holds SQLite's write lock until the commit
# or rollback.
_WRITE_STATEMENT = re.compile(r"\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
_WRITER_THREAD = "curio_writer_thread"


@event.listens_for(Engine, "before_cursor_execute")
def _note_writer(conn, _cursor, statement, _parameters, _context, _executemany):
    """Note the thread that writes on a connection, for
    :func:`session_holds_write_lock`. The in-memory test database hands every
    thread one shared connection, so a transaction open on it is not always
    the asking thread's."""
    if _WRITE_STATEMENT.match(statement):
        conn.info[_WRITER_THREAD] = threading.get_ident()


@event.listens_for(Engine, "commit")
@event.listens_for(Engine, "rollback")
def _forget_writer(conn):
    """The write ends with its transaction. A closed or invalidated connection
    is left alone: it holds no transaction, and reading its ``info`` would
    reconnect it."""
    if not conn.closed and not conn.invalidated:
        conn.info.pop(_WRITER_THREAD, None)


def session_holds_write_lock() -> bool:
    """Whether this thread's session has written and not yet committed or
    rolled back, and so holds SQLite's write lock.

    Reads never count: they open no transaction (see ``_WRITE_STATEMENT``).
    Unflushed changes do not count either; they write when they are flushed.
    False outside an app context, where there is no session.
    """
    if not has_app_context():
        return False
    try:
        session = db.session()  # this app context's Session, not the scoped proxy
        if not session.in_transaction():
            return False
        connection = session.connection()
        dbapi_connection = connection.connection.dbapi_connection
    except (RuntimeError, SQLAlchemyError):
        # An app without this SQLAlchemy instance, or a session whose failed
        # flush has already rolled its transaction back: no write lock held.
        return False
    return bool(getattr(dbapi_connection, "in_transaction", False)) and (
        connection.info.get(_WRITER_THREAD) == threading.get_ident()
    )


# ---------------------------------------------------------------------------
# Writes that lost a race with another writer
# ---------------------------------------------------------------------------

# The one case the pragmas above cannot cover. ``busy_timeout`` makes a
# connection WAIT for the write lock, but a transaction that has already READ
# and only then writes has no lock to wait for: if another connection committed
# in between, this one's snapshot is stale and SQLite fails the write
# immediately, however long the timeout is. Request handlers are full of that
# shape -- sign-up checks the username, creates the user, seeds the examples
# and only then inserts the session -- and five people registering at the same
# moment was enough to 500 three of them.
#
# Starting every transaction with BEGIN IMMEDIATE would fix it and was measured
# to be worse: a node run queries the session table to authenticate and then
# holds its connection for the whole execution, so the whole database would
# stay write-locked for the 40 seconds the sandbox takes. Retrying the one
# write that lost the race keeps the lock short and costs nothing when there is
# no contention.
_WRITE_CONFLICT_ATTEMPTS = 6
_WRITE_CONFLICT_BASE_DELAY = 0.02  # seconds; worst case ~1.2s of backoff


def _is_write_conflict(exc: BaseException) -> bool:
    """True when *exc* is SQLite refusing a write that another writer won."""
    message = str(getattr(exc, "orig", exc)).lower()
    return "database is locked" in message or "database table is locked" in message


def retry_on_write_conflict(apply_changes, attempts: int = _WRITE_CONFLICT_ATTEMPTS):
    """Run a unit of work, replaying it if another writer got there first.

    ``apply_changes`` is re-run in full on each attempt rather than just the
    failing statement: a rollback discards the pending insert or the attribute
    assignment along with the transaction, so replaying the change is what
    makes the retry meaningful. It must therefore be safe to run more than
    once, which is why callers pass the ORM work and leave file writes and
    other side effects outside.

    Anything that is not a lost write race is re-raised on the spot, and so is
    the last attempt: a caller that keeps failing should see the real error
    rather than a swallowed one.
    """
    delay = _WRITE_CONFLICT_BASE_DELAY
    for attempt in range(attempts):
        try:
            return apply_changes()
        except OperationalError as exc:
            db.session.rollback()
            if not _is_write_conflict(exc) or attempt == attempts - 1:
                raise
            # Jittered, so two racing writers do not line up again on the retry.
            time.sleep(delay + random.uniform(0, delay))
            delay *= 2


def commit_with_retry(apply_changes, attempts: int = _WRITE_CONFLICT_ATTEMPTS):
    """Apply a change and commit it, retrying the pair on a lost write race."""
    def _apply_and_commit():
        result = apply_changes()
        db.session.commit()
        return result

    return retry_on_write_conflict(_apply_and_commit, attempts=attempts)


# The app's Flask-SocketIO server, made by init_socketio(app) for every backend:
# the collaboration room and each open dataflow's doc (app/collaboration/)
# travel over it.
socketio = None


def init_socketio(app):
    """Make *app*'s SocketIO server, and keep it as this module's ``socketio``.

    One per app, so an app made later (the test suites make many) serves its
    own sockets rather than an earlier app's.
    """
    global socketio
    from flask_socketio import SocketIO
    from utk_curio.backend.config import COLLAB_CORS_ORIGINS
    raw = COLLAB_CORS_ORIGINS.strip()
    if raw == "*":
        origins = "*"
    else:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
    # async_mode="threading" mirrors the existing Flask dev server's threaded
    # model so the reloader keeps working without monkey-patching the world
    # (eventlet/gevent would require import-time patching). Its WebSocket
    # transport is simple-websocket, a thread per open socket.
    # manage_session=False: flask-socketio's default tries to assign to
    # ``RequestContext.session``, which became a read-only property in
    # Flask 3.x. The Flask session is not used anyway: what each socket is
    # (user_id, username, participant) is kept in collaboration/room_state.py
    # by the handshake.
    # async_handlers=False: a socket's events are handled one at a time, in
    # the order it sent them, on the thread that reads that socket, as
    # Flask-SocketIO's test client runs them for the tests. python-socketio's
    # default starts a thread for every event, so the backend's threads grew
    # with the rate of events rather than with its sockets: a hundred tabs
    # typing at once took the stress stack's container to its task limit,
    # and the sandbox and node runs beside it could start no thread either.
    # No handler waits on a client's answer (the server's call()), which this
    # mode does not allow.
    socketio = SocketIO(
        app,
        cors_allowed_origins=origins,
        async_mode="threading",
        async_handlers=False,
        manage_session=False,
        logger=False,
        engineio_logger=False,
    )
    _whole_messages(socketio.server)
    return socketio


# A Socket.IO message with binary data, as every doc message is, goes out as
# several packets, each its own put on the client's queue, and python-socketio's
# sends are not thread safe ("use standard concurrency solutions (such as a Lock
# object)", its Server.emit). A packet another thread sends the client meanwhile,
# such as the answer to one of its events, could land between a message's
# packets, which the client's parser takes as a broken stream: socket.io-client
# closes the connection on it. So every send to a client takes the client's lock,
# and whoever puts a message of several packets holds it across them
# (emit_whole). A thread holding one client's lock never waits for another's, so
# no two sends can wait for each other.
_CLIENT_LOCKS = tuple(threading.Lock() for _ in range(64))
_holding = threading.local()


@contextmanager
def whole_sends(eio_sid: str):
    """Hold the sends to the Engine.IO client *eio_sid* while this thread puts
    a message's packets, so no other thread's packet to it lands between them."""
    if getattr(_holding, "held", False):
        yield
        return
    with _CLIENT_LOCKS[hash(eio_sid) % len(_CLIENT_LOCKS)]:
        _holding.held = True
        try:
            yield
        finally:
            _holding.held = False


def _whole_messages(server) -> None:
    """Make each send of *server*, a ``socketio.Server``, take its client's
    lock (:func:`whole_sends`): an event's answer and every other packet the
    server sends (``_send_packet``), and each packet of an emit
    (``_send_eio_packet``)."""
    send_packet, send_eio_packet = server._send_packet, server._send_eio_packet

    def locked_send_packet(eio_sid, pkt):
        with whole_sends(eio_sid):
            send_packet(eio_sid, pkt)

    def locked_send_eio_packet(eio_sid, eio_pkt):
        with whole_sends(eio_sid):
            send_eio_packet(eio_sid, eio_pkt)

    server._send_packet = locked_send_packet
    server._send_eio_packet = locked_send_eio_packet


def emit_whole(socketio, event: str, data, *, namespace: str, to: str, skip_sid=None) -> None:
    """Emit *event* with *data* to *to*, a room or a client, but *skip_sid*, a
    client or a list of them, encoded once and put whole to each client:
    every packet of it while that client's sends are held
    (:func:`whole_sends`)."""
    from engineio import packet as eio_packet
    from socketio import packet

    server = socketio.server
    encoded = server.packet_class(packet.EVENT, namespace=namespace, data=[event, data]).encode()
    parts = [eio_packet.Packet(eio_packet.MESSAGE, part)
             for part in (encoded if isinstance(encoded, list) else [encoded])]
    skipped = set(skip_sid) if isinstance(skip_sid, list) else {skip_sid}
    for sid, eio_sid in list(server.manager.get_participants(namespace, to)):
        if sid in skipped:
            continue
        with whole_sends(eio_sid):
            for part in parts:
                server._send_eio_packet(eio_sid, part)