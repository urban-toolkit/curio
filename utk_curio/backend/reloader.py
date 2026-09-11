"""Dev-server reloader settings shared by the backend and the sandbox.

A leaf module on purpose: ``sandbox/server.py`` used to import these two
names from ``backend/server.py``, and importing THAT module builds the
backend Flask app and queries the database -- so every sandbox boot
constructed a second backend just to read two constants, and when the
sandbox started before the backend had migrated a fresh DB (the parallel
e2e driver starts both launchers at once) it logged
``OperationalError: no such column: user.username`` tracebacks at boot.
Nothing here imports Flask or touches a database.
"""

import os

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
