import random
import sqlite3
import time

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError


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


def commit_with_retry(apply_changes, attempts: int = _WRITE_CONFLICT_ATTEMPTS):
    """Apply a change and commit it, retrying if another writer got there first.

    ``apply_changes`` is re-run on each attempt, not just the commit: a rollback
    discards the pending insert or the attribute assignment along with the
    transaction, so replaying the change is what makes the retry meaningful. It
    must therefore be safe to run more than once -- these are single-object
    writes, so it is.

    Anything that is not a lost write race is re-raised on the spot, and so is
    the last attempt: a caller that keeps failing should see the real error
    rather than a swallowed one.
    """
    delay = _WRITE_CONFLICT_BASE_DELAY
    for attempt in range(attempts):
        try:
            result = apply_changes()
            db.session.commit()
            return result
        except OperationalError as exc:
            db.session.rollback()
            if not _is_write_conflict(exc) or attempt == attempts - 1:
                raise
            # Jittered, so two racing writers do not line up again on the retry.
            time.sleep(delay + random.uniform(0, delay))
            delay *= 2


# Flask-SocketIO singleton, populated by init_socketio(app) when
# ENABLE_COLLAB=True. Left as None otherwise so the flask-socketio package is
# never imported on deployments that don't use real-time collaboration.
socketio = None


def init_socketio(app):
    """Construct + bind the SocketIO singleton.

    Imported lazily so backends running with ENABLE_COLLAB=0 don't need
    flask-socketio installed.
    """
    global socketio
    if socketio is not None:
        return socketio
    from flask_socketio import SocketIO
    from utk_curio.backend.config import COLLAB_CORS_ORIGINS
    raw = COLLAB_CORS_ORIGINS.strip()
    if raw == "*":
        origins = "*"
    else:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
    # async_mode="threading" mirrors the existing Flask dev server's threaded
    # model so the reloader keeps working without monkey-patching the world
    # (eventlet/gevent would require import-time patching).
    # manage_session=False: flask-socketio's default tries to assign to
    # ``RequestContext.session``, which became a read-only property in
    # Flask 3.x. We do not use the Flask session anyway — every per-sid
    # detail (user_id, username, …) is stashed via
    # ``sio.server.save_session(...)`` in the collaboration auth handshake.
    socketio = SocketIO(
        app,
        cors_allowed_origins=origins,
        async_mode="threading",
        manage_session=False,
        logger=False,
        engineio_logger=False,
    )
    return socketio