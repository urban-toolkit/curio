"""Root pytest conftest for the backend suite.

The very first thing this file does is set the environment variables that
wire the backend to a dedicated, wiped-clean test database — *before* any
``utk_curio.backend`` module is imported, because ``config.py`` resolves
``SQLALCHEMY_DATABASE_URI`` at class-definition time.

This keeps dev and test state separate. Every pytest invocation — unit or
E2E — starts against an empty database, and the dev
``urban_workflow.db`` file is never touched.
"""

import os
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

# ---------------------------------------------------------------------------
# Phase 1: wire env vars BEFORE any backend import.
# ---------------------------------------------------------------------------

# Resolve the workspace that holds .curio/test/*.db. Three cases:
#   1. CURIO_TEST_WORKSPACE=<path> — caller pins it (CI, debugging).
#   2. CURIO_E2E_USE_EXISTING=1    — the backend is already running in a
#      sibling terminal. We MUST point at the same workspace it sees
#      (``CURIO_LAUNCH_CWD`` from that process, defaulting to the repo root,
#      which matches what ``curio start`` sees in normal local/docker use)
#      or the subprocess will read a different sqlite file and every
#      query will fail with "no such table: user".
#   3. Otherwise — a fresh temp dir, owned and cleaned up by this session.
_PERSISTENT_WS = os.environ.get("CURIO_TEST_WORKSPACE")
_USE_EXISTING = os.environ.get("CURIO_E2E_USE_EXISTING")
if _PERSISTENT_WS:
    os.makedirs(_PERSISTENT_WS, exist_ok=True)
    _TEST_WORKSPACE = os.path.abspath(_PERSISTENT_WS)
    _OWNS_WORKSPACE = False
elif _USE_EXISTING:
    _TEST_WORKSPACE = os.path.abspath(
        os.environ.get("CURIO_LAUNCH_CWD") or _REPO_ROOT
    )
    _OWNS_WORKSPACE = False
else:
    _TEST_WORKSPACE = tempfile.mkdtemp(prefix="curio-test-ws-")
    _OWNS_WORKSPACE = True

_TEST_DB_DIR = os.path.join(_TEST_WORKSPACE, ".curio", "test")
os.makedirs(_TEST_DB_DIR, exist_ok=True)

_TEST_SQLA_DB = os.path.join(_TEST_DB_DIR, "urban_workflow_test.db")

# Wipe stale files so the session always starts on an empty DB, matching the
# isolation Django's test runner provides. We skip the wipe when attaching to
# an already-running backend (CURIO_E2E_USE_EXISTING=1) or a caller-provided
# workspace — those own the DB lifecycle and the running backend is holding
# sqlite connections we shouldn't yank.
if _OWNS_WORKSPACE:
    try:
        os.remove(_TEST_SQLA_DB)
    except FileNotFoundError:
        pass

os.environ["CURIO_TESTING"] = "1"
os.environ["CURIO_LAUNCH_CWD"] = _TEST_WORKSPACE
os.environ.setdefault("CURIO_SHARED_DATA", os.path.join(
    _TEST_WORKSPACE, ".curio", "data",
))
os.makedirs(os.environ["CURIO_SHARED_DATA"], exist_ok=True)

# Point the backend (and any subprocess that inherits this env — e.g. the
# ``curio start`` child spawned by test_frontend/fixtures.py) at the test
# DB. DATABASE_URL_TEST takes precedence inside config._resolve_database_uri
# so leave DATABASE_URL alone for code paths that still read it directly.
_default_test_url = f"sqlite:///{_TEST_SQLA_DB}"
os.environ.setdefault("DATABASE_URL_TEST", _default_test_url)
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL_TEST"]


# ---------------------------------------------------------------------------
# Phase 2: imports (now safe — config.py sees the test env).
# ---------------------------------------------------------------------------

from .test_frontend.fixtures import *  # noqa: E402,F401,F403
import pytest  # noqa: E402

from utk_curio.backend.app import create_app  # noqa: E402
from utk_curio.backend.extensions import db as _db  # noqa: E402


sys.dont_write_bytecode = True


# ---------------------------------------------------------------------------
# Phase 3: create both schemas once, so the ``curio start`` subprocess
# (and any in-process Flask test client) boots against a ready-to-use,
# migrated-but-empty DB.
# ---------------------------------------------------------------------------

def _bootstrap_schemas() -> None:
    bootstrap_app = create_app()
    with bootstrap_app.app_context():
        _db.create_all()


_bootstrap_schemas()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Configure browser context for all tests."""
    return {
        **browser_context_args,
    }


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Configure browser launch options - headless by default unless --headed is passed.

    Note on AUTK fixtures: Autark renders via WebGPU, and Playwright's
    bundled Chromium binaries do not ship WebGPU on Windows/Linux/macOS
    (verified against ``HeadlessChrome/145.0.0.0`` and
    ``chrome-headless-shell``). AUTK_MAP nodes therefore set
    ``code: 'error'`` in headless runs because ``await map.init()`` rejects
    when ``navigator.gpu`` is undefined. The Playwright assertions still
    pass — AUTK_MAP is a ``passive`` node so ``test_node_execution`` does
    not inspect its status. To actually exercise rendering, run the suite
    with ``--headed`` against your real Chrome (which has WebGPU).
    """
    return {
        **browser_type_launch_args,
        # headless will be False only if --headed is explicitly passed
        "headless": browser_type_launch_args.get("headless", True),
    }


def pytest_addoption(parser):
    parser.addoption(
        "--longrun",
        action="store_true",
        dest="longrun",
        default=False,
        help="enable longrundecorated tests",
    )


def pytest_configure(config):
    if not config.option.longrun:
        setattr(config.option, "markexpr", "not externalapi")


@pytest.fixture(scope="session")
def test_workspace():
    """Absolute path of the per-session test workspace.

    Inside this directory live ``.curio/test/urban_workflow_test.db`` and
    ``.curio/test/urban_workflow_test.db`` — the DB that replaces the dev
    ``urban_workflow.db`` for every backend-booting test.
    Created by the module-level bootstrap above.
    """
    return _TEST_WORKSPACE


@pytest.fixture(scope="session")
def test_db_paths(test_workspace):
    """Absolute path of the test DB file. Useful for e2e cleanup."""
    return {
        "sqla": _TEST_SQLA_DB,
        "dir": _TEST_DB_DIR,
    }


@pytest.fixture(scope="session", autouse=True)
def test_databases_cleanup(request):
    """Tear down the temp workspace at the end of the session.

    The schemas are created at import time (see ``_bootstrap_schemas``),
    so this fixture only owns the teardown side of the lifecycle — the
    session has always booted against an empty DB by the time any test
    runs.
    """
    yield
    if _OWNS_WORKSPACE:
        shutil.rmtree(_TEST_WORKSPACE, ignore_errors=True)


@pytest.fixture(scope="session")
def session_app():
    """Session-scoped Flask app for E2E server orchestration (ports, etc.).

    Named ``session_app`` so it is not shadowed by function-scoped ``app``
    fixtures in ``test_projects`` / ``test_users`` (those would break
    session-scoped ``curio_servers`` if this fixture were still called
    ``app``).

    Uses the default production ``Config`` — which, because
    ``CURIO_TESTING=1`` is set in phase 1, resolves
    ``SQLALCHEMY_DATABASE_URI`` to the test URL via
    ``config._resolve_database_uri``.
    """
    application = create_app()
    application.config.update(
        {
            "TESTING": True,
            "LIVESERVER_PORT": 5002,
            # Use 5002 so frontend (dotenv .env / default) finds the backend
            "BACKEND_PORT": 5002,
            "SANDBOX_PORT": 2000,
            "FRONTEND_PORT": 8080,
        }
    )
    return application


@pytest.fixture(scope="session")
def app(session_app):
    """Alias of ``session_app`` for pytest-flask (autouse ``_configure_application``).

    ``test_projects`` / ``test_users`` define a function-scoped ``app`` that
    overrides this for tests in those packages.  E2E fixtures use
    ``session_app`` directly in ``curio_servers`` so they never resolve to a
    function-scoped ``app``.
    """
    return session_app
