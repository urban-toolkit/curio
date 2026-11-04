import os
from utk_curio.backend.app import create_app
from utk_curio.backend.config import CURIO_SEED_EXAMPLES

app = create_app()


# Shared with sandbox/server.py; see utk_curio/backend/reloader.py.
from utk_curio.backend.reloader import (  # noqa: E402,F401  (re-exported)
    DEFAULT_RELOADER_TYPE,
    RELOADER_EXCLUDE_PATTERNS,
)

with app.app_context():
    try:
        from utk_curio.backend.app.users.services import _shared_guest_user
        from utk_curio.backend.app.projects.services import (
            _user_dir_key,
            reconcile_guest_projects,
        )
        guest = _shared_guest_user()
        # The hosted guests' copies go, as their examples are put back.
        from utk_curio.backend.app.projects import visitor_copies
        dropped = visitor_copies.drop_all()
        if dropped:
            app.logger.info("Dropped %d hosted guest copy(ies) of dataflows", dropped)
        n = reconcile_guest_projects(guest)
        if n:
            app.logger.info("Reconciled %d guest project(s) from filesystem", n)
        if CURIO_SEED_EXAMPLES:
            from utk_curio.backend.app.projects.seed import seed_example_projects
            s = seed_example_projects(guest)
            app.logger.info("Seeded %d example project(s)", s)
            # After the projects exist, provision the datasets their
            # ``dataflow.datasets`` refs declare - the dataset counterpart to
            # the node-package seeding in ``app/__init__.py``. Without the
            # store copy the refs still resolve for execution (the hub row wins
            # the catalog dedupe) but the Data palette has no title, format or
            # count to show.
            from utk_curio.backend.app.datasets.seed import seed_example_datasets
            d = seed_example_datasets(_user_dir_key(guest))
            if d:
                app.logger.info(
                    "Provisioned %d example dataset(s): %s", len(d), ", ".join(d)
                )
    except Exception:
        app.logger.warning("Could not ensure guest user on startup", exc_info=True)

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

def _run_kwargs():
    """The arguments both server flavours share, resolved from the environment.

    A function rather than two literal argument lists because ``debug`` has to
    be the same on both paths and neither path can be exercised by a test that
    starts a server. ``CURIO_BACKEND_DEBUG`` is read here rather than left to
    Flask's own ``FLASK_DEBUG``: the explicit ``debug=`` argument to ``run()``
    overrides that variable, and socketio.run has to be handed the value
    regardless, so honouring FLASK_DEBUG would mean reimplementing its parsing
    in two places.

    Note that ``use_reloader`` is separate and unchanged, so turning debug off
    does not turn auto-reload off with it.
    """
    from utk_curio.backend.config import CURIO_BACKEND_DEBUG

    return {
        'host': os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
        'port': int(os.getenv('FLASK_BACKEND_PORT', 5002)),
        'debug': CURIO_BACKEND_DEBUG,
        'use_reloader': os.getenv('FLASK_USE_RELOADER', '1') != '0',
    }


def _socketio_run_kwargs():
    """What ``socketio.run`` is handed: ``_run_kwargs``, and the reloader's
    exclusions, which Flask-SocketIO passes on to Werkzeug's reloader only as
    ``reloader_options``. Without them a package install, which writes under
    ``.curio/`` and ``site-packages/``, restarts a dev backend mid-request.

    The Werkzeug server is the one Flask-SocketIO's threading mode runs on (a
    thread per request and per WebSocket); ``allow_unsafe_werkzeug`` lets it
    start without a terminal, as the launcher and the Docker image start it.
    """
    return {
        'allow_unsafe_werkzeug': True,
        'reloader_options': {
            'exclude_patterns': RELOADER_EXCLUDE_PATTERNS,
            'reloader_type': DEFAULT_RELOADER_TYPE,
        },
        **_run_kwargs(),
    }


def serve():
    """Serve the backend, Socket.IO included, until it is stopped."""
    # The connection DuckDB 1.x's import opens holds a thread per core and
    # serves nothing here (2.0 opens it on first use only). Imported now, so a
    # later import opens no pool of its own.
    from utk_curio.sandbox.util.duckdb_threads import release_default_connection
    release_default_connection(
        "[backend]", "so its threads stay idle in this process", import_first=True,
    )

    # The app's own SocketIO server (extensions.init_socketio), which
    # Flask-SocketIO keeps on the app.
    app.extensions["socketio"].run(app, **_socketio_run_kwargs())


if __name__ == '__main__':
    serve()

