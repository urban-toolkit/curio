import os
from utk_curio.backend.app import create_app

app = create_app()


# fnmatch patterns the dev-server stat reloader must NEVER treat as
# reload triggers (see :func:`werkzeug._reloader._find_stat_paths`).
#
# ``.curio/`` is user **runtime** data — pack stores, staging dirs,
# lockfiles, the SQLite DB — and must not restart the backend when
# templates are written during a pack install.
#
# **Important:** Werkzeug's default ``reloader_type="auto"`` prefers
# Watchdog, which applies ``exclude_patterns`` via ``pathlib.Path.match``
# — that API does **not** reliably exclude deep paths under ``.curio/``
# (e.g. ``…/.curio/users/…/packs/…/templates/foo.py``), so installs still
# killed the worker with ``ERR_EMPTY_RESPONSE``. Curio therefore defaults
# ``FLASK_RELOADER_TYPE`` to ``"stat"``, where excludes use :mod:`fnmatch`
# on full paths and work for arbitrary depth. Set ``FLASK_RELOADER_TYPE=watchdog``
# only if you accept that limitation.
# `*templates*`: dynamically read per-request, not imported; also dodges
# Windows atime-bump reload storms that drop in-flight /processPythonCode.
RELOADER_EXCLUDE_PATTERNS = [
    '*.duckdb', '*.duckdb.wal', '*.duckdb-shm', '*.duckdb-wal',
    '*/.curio/*', '*/.curio', '*templates*',
]

DEFAULT_RELOADER_TYPE = os.getenv('FLASK_RELOADER_TYPE', 'stat')

with app.app_context():
    try:
        from utk_curio.backend.app.users.services import _shared_guest_user
        from utk_curio.backend.app.projects.services import reconcile_guest_projects
        guest = _shared_guest_user()
        n = reconcile_guest_projects(guest)
        if n:
            app.logger.info("Reconciled %d guest project(s) from filesystem", n)
        if os.environ.get("CURIO_SEED_EXAMPLES", "").lower() in ("1", "true", "yes"):
            from utk_curio.backend.app.projects.seed import seed_example_projects
            s = seed_example_projects(guest)
            app.logger.info("Seeded %d example project(s)", s)
    except Exception:
        app.logger.warning("Could not ensure guest user on startup", exc_info=True)

@app.route('/health', methods=['GET'])
def health():
    return 'OK', 200

if __name__ == '__main__':
    app.run(
        host=os.getenv('FLASK_BACKEND_HOST', '127.0.0.1'),
        port=int(os.getenv('FLASK_BACKEND_PORT', 5002)),
        threaded=True,
        debug=True,
        use_reloader=os.getenv('FLASK_USE_RELOADER', '1') != '0',
        exclude_patterns=RELOADER_EXCLUDE_PATTERNS,
        reloader_type=DEFAULT_RELOADER_TYPE,
    )

