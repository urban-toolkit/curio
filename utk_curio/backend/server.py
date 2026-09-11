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

if __name__ == '__main__':
    from utk_curio.backend.config import ENABLE_COLLAB
    if ENABLE_COLLAB:
        # SocketIO requires its own .run() so the engineio server can attach.
        # The Werkzeug dev server is not officially supported but is fine for
        # local dev; allow_unsafe_werkzeug=True suppresses the refusal.
        from utk_curio.backend.extensions import socketio
        socketio.run(
            app,
            host=os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
            port=int(os.getenv('FLASK_BACKEND_PORT', 5002)),
            debug=True,
            use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
            allow_unsafe_werkzeug=True,
        )
    else:
        app.run(
            host=os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
            port=int(os.getenv('FLASK_BACKEND_PORT', 5002)),
            threaded=True,
            debug=True,
            use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
            exclude_patterns=RELOADER_EXCLUDE_PATTERNS,
            reloader_type=DEFAULT_RELOADER_TYPE,
        )

