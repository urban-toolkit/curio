from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate


db = SQLAlchemy()
migrate = Migrate()

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