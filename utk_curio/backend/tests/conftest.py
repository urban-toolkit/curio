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

_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)

# ---------------------------------------------------------------------------
# Phase 1: wire env vars BEFORE any backend import.
# ---------------------------------------------------------------------------

# Two separate concerns, one variable each — never re-couple them.
#
# _TEST_WORKSPACE: where the sandbox subprocess will chdir
# (``CURIO_LAUNCH_CWD``). Workflows that read relative paths like
# ``docs/examples/data/access_score.geojson`` need this to be the repo
# root.
#
# _TEST_OWNED_DIR: the *only* directory the cleanup fixture is allowed to
# rmtree. Must be a path we exclusively own and that is gitignored — never
# the repo root itself. (A previous bug pointed the rmtree target at the
# workspace and wiped the working tree when the workspace was the repo
# root. That's why these are decoupled now.)
#
# CURIO_TEST_WORKSPACE / CURIO_E2E_USE_EXISTING let callers override the
# workspace; in those cases the caller owns its lifecycle and we don't
# clean anything up.
_PERSISTENT_WS = os.environ.get("CURIO_TEST_WORKSPACE")
_USE_EXISTING = os.environ.get("CURIO_E2E_USE_EXISTING")
if _PERSISTENT_WS:
    os.makedirs(_PERSISTENT_WS, exist_ok=True)
    _TEST_WORKSPACE = os.path.abspath(_PERSISTENT_WS)
    _TEST_OWNED_DIR = None
elif _USE_EXISTING:
    _TEST_WORKSPACE = os.path.abspath(
        os.environ.get("CURIO_LAUNCH_CWD") or _REPO_ROOT
    )
    _TEST_OWNED_DIR = None
else:
    _TEST_WORKSPACE = _REPO_ROOT
    # ``.curio/`` is gitignored and used only by curio for runtime artifacts
    # (test sqlite, duckdb data). Safe to wipe at session end.
    _TEST_OWNED_DIR = os.path.join(_REPO_ROOT, ".curio")

_TEST_DB_DIR = os.path.join(_TEST_WORKSPACE, ".curio", "test")
os.makedirs(_TEST_DB_DIR, exist_ok=True)

_TEST_SQLA_DB = os.path.join(_TEST_DB_DIR, "urban_workflow_test.db")

# Wipe stale files so the session always starts on an empty DB. Skip when
# attaching to an already-running backend or a caller-provided workspace —
# those own the DB lifecycle and the running backend is holding sqlite
# connections we shouldn't yank.
if _TEST_OWNED_DIR is not None:
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
        # Release the sqlite handle so curio's subprocess can os.remove the
        # test DB on Windows (POSIX unlink-while-open silently works).
        _db.session.remove()
        _db.engine.dispose()


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


def _find_system_chrome() -> str | None:
    """Locate the system-installed Google Chrome executable.

    Playwright's ``channel='chrome'`` silently falls back to bundled
    Chromium when its registry resolution fails — we hit this on
    Windows and the bundled binary lacks WebGPU on this platform. The
    fix is to point ``executable_path`` directly at the real Chrome
    binary, bypassing channel resolution entirely.

    Returns ``None`` when Chrome is not found, in which case the
    caller falls back to bundled Chromium.
    """
    candidates: list[str] = []
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
        local_app_data = os.environ.get(
            "LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")
        )
        candidates += [
            os.path.join(program_files, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(program_files_x86, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local_app_data, r"Google\Chrome\Application\chrome.exe"),
        ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:  # Linux / CI
        candidates += [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Configure browser launch options.

    Points ``executable_path`` at the system Google Chrome instead of
    Playwright's bundled Chromium. Playwright's bundled Chromium on
    Windows ships without a working Dawn/WebGPU runtime — verified
    empirically: ``requestAdapter()`` returns null in the
    ``headless-shell`` variant, the full Chromium binary, headed
    *and* headless, with every documented flag combination
    (``--enable-unsafe-webgpu``, ``--enable-unsafe-swiftshader``,
    ``WebGPUService``, ``--use-angle=vulkan``). Real Chrome 113+ on
    the same host returns a hardware adapter immediately. The earlier
    attempt at ``channel='chrome'`` was silently ignored by Playwright
    and continued launching bundled Chromium; ``executable_path``
    bypasses channel resolution.

    Falls back to bundled Chromium when Chrome cannot be found, in
    which case AUTK_MAP/PLOT/COMPUTE will hit
    ``_tolerate_webgpu_error`` and skip with a warning rather than
    failing the suite. All GitHub-hosted runners
    (``ubuntu-latest`` / ``windows-latest`` / ``macos-latest``) have
    Chrome preinstalled.

    Flag set is intentionally minimal: ``--enable-unsafe-webgpu`` lets
    Dawn expose adapters in non-secure contexts and on unstable
    configs, ``--enable-unsafe-swiftshader`` lets Dawn fall back to a
    software adapter on hosts without a hardware GPU (e.g. CI
    runners). We deliberately do *not* pass
    ``--use-angle=*`` or ``--enable-features=Vulkan,VulkanFromANGLE,
    DefaultANGLEVulkan,WebGPUService``: those are the flags
    urban-toolkit/autark uses on macOS to force Metal/Vulkan paths,
    but on Windows they make Dawn ask for a Vulkan adapter the host
    doesn't have and ``requestAdapter()`` returns null. Real Chrome on
    Windows defaults to D3D12 and works correctly when left alone.
    Verified empirically on Chrome 148 / Windows 11 against
    https://example.com — adapter is created with the minimal flags
    and disappears the moment either of the autark flags is added.
    """
    launch_args = {
        **browser_type_launch_args,
        "headless": browser_type_launch_args.get("headless", True),
        "args": [
            "--enable-unsafe-webgpu",
            "--enable-unsafe-swiftshader",
            *browser_type_launch_args.get("args", []),
        ],
    }

    chrome_path = _find_system_chrome()
    if chrome_path:
        launch_args["executable_path"] = chrome_path

    return launch_args


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
    """Tear down test runtime artifacts at the end of the session.

    Only ever rmtrees ``_TEST_OWNED_DIR`` — never ``_TEST_WORKSPACE``,
    which can legitimately point at the repo root (see the workspace
    setup at the top of this file). Skipped when no owned dir was
    allocated (caller-provided workspace or existing-backend mode).
    """
    yield
    if _TEST_OWNED_DIR is not None:
        shutil.rmtree(_TEST_OWNED_DIR, ignore_errors=True)


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
