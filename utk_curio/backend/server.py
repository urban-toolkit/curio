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


if __name__ == '__main__':
    from utk_curio.backend.config import ENABLE_COLLAB
    if ENABLE_COLLAB:
        # SocketIO requires its own .run() so the engineio server can attach.
        # The Werkzeug dev server is not officially supported but is fine for
        # local dev; allow_unsafe_werkzeug=True suppresses the refusal.
        from utk_curio.backend.extensions import socketio
        socketio.run(app, allow_unsafe_werkzeug=True, **_run_kwargs())
    else:
        app.run(
            threaded=True,
            exclude_patterns=RELOADER_EXCLUDE_PATTERNS,
            reloader_type=DEFAULT_RELOADER_TYPE,
            **_run_kwargs(),
        )

