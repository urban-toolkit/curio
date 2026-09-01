import os
from utk_curio.backend.app import create_app
from utk_curio.backend.config import CURIO_SEED_EXAMPLES

app = create_app()


# fnmatch patterns the dev-server stat reloader must NEVER treat as
# reload triggers (see :func:`werkzeug._reloader._find_stat_paths`).
#
# ``.curio/`` is user **runtime** data — package stores, staging dirs,
# lockfiles, the SQLite DB — and must not restart the backend when
# sources/starters are written during a package install.
#
# **Important:** Werkzeug's default ``reloader_type="auto"`` prefers
# Watchdog, which applies ``exclude_patterns`` via ``pathlib.Path.match``
# — that API does **not** reliably exclude deep paths under ``.curio/``
# (e.g. ``…/.curio/users/…/packages/…/starters/foo.py``), so installs still
# killed the worker with ``ERR_EMPTY_RESPONSE``. Curio therefore defaults
# ``FLASK_RELOADER_TYPE`` to ``"stat"``, where excludes use :mod:`fnmatch`
# on full paths and work for arbitrary depth. Set ``FLASK_RELOADER_TYPE=watchdog``
# only if you accept that limitation.
# `*starters*`: dynamically read per-request, not imported; also dodges
# Windows atime-bump reload storms that drop in-flight /processPythonCode.
RELOADER_EXCLUDE_PATTERNS = [
    '*.duckdb', '*.duckdb.wal', '*.duckdb-shm', '*.duckdb-wal',
    '*/.curio/*', '*/.curio', '*starters*',
    # The Data Catalog writes computed dataset bundles (``manifest.json`` +
    # ``data/*.parquet``) into ``<repo_root>/datasets/`` at node-execution
    # time (catalog auto-install). Like ``.curio/`` above, these are runtime
    # data writes, not source changes — without this exclude, a node that
    # produces a dataset trips the stat reloader and SIGTERMs the worker
    # mid-request, dropping the in-flight /processJavaScriptCode (the autk
    # data node then falls back to an in-browser load that fails).
    '*/datasets/*', '*\\datasets\\*',
    '*/datasets', '*\\datasets',
    # Synchronous catalog installs run ``pip install`` from inside the
    # backend (see ``packages/pip_runner.py``); pip writes ~thousands of
    # files into ``site-packages/`` for a heavy package like ``torch``,
    # which would otherwise trip the stat reloader mid-install and SIGTERM
    # the worker, dropping the in-flight install request. The sandbox
    # shares this exclude list (sandbox/server.py imports it) so its
    # equivalent ``/install`` endpoint is protected the same way.
    '*/site-packages/*', '*\\site-packages\\*',
    '*/site-packages', '*\\site-packages',
]

DEFAULT_RELOADER_TYPE = os.getenv('FLASK_RELOADER_TYPE', 'stat')

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

