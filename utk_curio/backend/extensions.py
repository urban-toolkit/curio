import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine


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