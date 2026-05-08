import os
import sys
import json
import time
import sqlite3
import tempfile
import pytest
import subprocess
from signal import SIGINT
from playwright.sync_api import Page
from .utils import (
    FrontendPage,
    debug_log,
    REPO_ROOT,
    is_port_in_use,
    wait_for_port,
    wait_for_http_ready,
    e2e_existing_servers,
    base_url,
    upload_workflow,
    seed_node_code,
    stub_login_and_enter_workflow,
)
from .workflow_spec import CODE_TYPES


# ---------------------------------------------------------------------------
# Tables truncated between E2E tests.
#
# Django's ``TestCase`` can rely on transaction rollback; in Curio we do it
# explicitly since the backend is a real subprocess that holds its own
# SQLAlchemy connections against the shared sqlite file.
# ---------------------------------------------------------------------------

_SQLA_MUTABLE_TABLES = (
    "exec_cache_entry",
    "project",
    "auth_attempt",
    "user_session",
    "user",
)

_PROV_MUTABLE_TABLES = (
    "attributeValueChange",
    "interaction",
    "visualization",
    "activityExecution",
    "attributeValue",
    "relationInstance",
    "workflowExecution",
    "activity",
    "attributeRelation",
    "relation",
    "workflow",
    "versionedElement",
    "version",
    "versionTransaction",
    "user",
)


def _truncate_sqlite(db_path: str, tables: tuple) -> None:
    """Delete all rows from *tables* in the sqlite file at *db_path*.

    Silently skips a missing file or a missing table so the fixture stays
    resilient to partially-bootstrapped DBs.
    """
    if not os.path.isfile(db_path):
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in tables:
            try:
                conn.execute(f'DELETE FROM "{table}"')
            except sqlite3.OperationalError:
                # Table doesn't exist yet (e.g. fresh session, pre-migration)
                continue
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session-scoped fixtures – shared across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def repo_root():
    """Session-scoped fixture exposing the repository root path.

    Wraps the module-level ``REPO_ROOT`` constant so that test functions
    and other fixtures can receive it via dependency injection.
    """
    return REPO_ROOT


@pytest.fixture(scope="session")
def curio_servers(session_app, request):
    """Start all Curio servers (backend, sandbox, frontend) together via curio start.
    Backend port must match frontend's BACKEND_URL (default 5002 from .env) so the app can reach the API.
    Set CURIO_E2E_USE_EXISTING=1 to use already-running servers (e.g. in CI with docker compose).
    """
    if os.environ.get("CURIO_E2E_USE_EXISTING"):
        yield e2e_existing_servers()
        return

    backend_port = int(session_app.config["BACKEND_PORT"])
    sandbox_port = int(session_app.config["SANDBOX_PORT"])
    frontend_port = int(session_app.config["FRONTEND_PORT"])

    for port in (backend_port, sandbox_port, frontend_port):
        if is_port_in_use(port):
            if sys.platform == "win32":
                subprocess.run([f"npx kill-port {port}"], capture_output=True, shell=True)
            else:
                subprocess.run(["npx", "kill-port", str(port)], capture_output=True)

    env = os.environ.copy()
    env["FLASK_ENV"] = "testing"
    env["SECRET_KEY"] = "mysecretkey"
    env["CURIO_DEV"] = "1"
    env["PORT"] = str(frontend_port)
    env["BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"
    env["DONT_REWRITE_URLS"] = "false"
    env["CURIO_NO_OPEN"] = "1"
    # Disable Flask reloader so it doesn't restart the backend mid-suite when
    # pytest imports or tempfiles trigger inotify events.
    env["FLASK_USE_RELOADER"] = "0"
    # E2E tests exercise backend auth/project flows — PYODIDE_ENABLED would
    # bypass auth in the frontend (systemvars=true lets this override .env).
    env["PYODIDE_ENABLED"] = "false"
    # Ensure the backend child uses the dedicated test DB (session fixture in
    # tests/conftest.py wipes + bootstraps it). These are already in
    # os.environ via the copy above; set them explicitly so CI overrides are
    # obvious in the subprocess env.
    for key in (
        "CURIO_TESTING",
        "CURIO_LAUNCH_CWD",
        "CURIO_SHARED_DATA",
        "DATABASE_URL",
        "DATABASE_URL_TEST",
    ):
        if key in os.environ:
            env[key] = os.environ[key]

    # The E2E suite exercises the real signup / signin / guest flows, so the
    # backend must run with user auth enabled. ``curio.py start`` defaults to
    # ``CURIO_NO_AUTH=1`` (auto-guest mode, no login UI), which would send the
    # browser straight to ``/projects`` and make every auth-gated test time
    # out looking for ``Sign In`` / ``Create an account`` / ``Continue as
    # Guest``. ``--auth`` flips ``CURIO_NO_AUTH=0`` so the login UI renders;
    # tests that opt out (e.g. ``test_frontend_server``) branch on
    # ``auth_enabled_env()`` and will follow the no-auth path only when the
    # caller sets ``CURIO_NO_AUTH=1`` in the pytest process env as well.
    extra_args: list[str] = []
    if env.get("CURIO_NO_AUTH", "0") not in ("1", "true", "yes", "on"):
        extra_args.append("--auth")
    if env.get("CURIO_NO_PROJECT", "0") in ("1", "true", "yes", "on"):
        extra_args.append("--no-project")

    process = subprocess.Popen(
        [
            "python", "curio.py", "start",
            "--backend-port", str(backend_port),
            "--sandbox-port", str(sandbox_port),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    wait_for_port(backend_port, timeout=40.0)
    wait_for_port(sandbox_port, timeout=45.0)
    wait_for_port(frontend_port, timeout=90.0)

    # Ensure backend and sandbox respond to /live before tests run
    host = "127.0.0.1"
    wait_for_http_ready(f"http://{host}:{backend_port}", timeout=15.0)
    wait_for_http_ready(f"http://{host}:{sandbox_port}", timeout=15.0)

    def shutdown():

        time.sleep(2)
        if sys.platform != "win32":
            process.send_signal(SIGINT)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        for port in (backend_port, sandbox_port, frontend_port):
            if is_port_in_use(port):
                if sys.platform == "win32":
                    subprocess.run([f"npx kill-port {port}"], capture_output=True, shell=True)
                else:
                    subprocess.run(["npx", "kill-port", str(port)], capture_output=True)

    request.addfinalizer(shutdown)
    yield {
        "backend_port": backend_port,
        "sandbox_port": sandbox_port,
        "frontend_port": frontend_port,
        "_host": "127.0.0.1",
    }


@pytest.fixture(scope="session")
def current_server(curio_servers):
    """Backend URL (servers already started by curio_servers or existing stack)."""
    yield base_url(curio_servers, "backend_port")


@pytest.fixture(scope="session")
def sandbox_server(curio_servers):
    """Sandbox URL (servers already started by curio_servers or existing stack)."""
    yield base_url(curio_servers, "sandbox_port")


@pytest.fixture(scope="session")
def frontend_server(curio_servers):
    """Frontend URL (servers already started by curio_servers or existing stack)."""
    url = base_url(curio_servers, "frontend_port")
    debug_log(
        "fixtures.py:frontend_server",
        "Frontend server URL resolved",
        {"url": url, "curio_servers": {k: v for k, v in curio_servers.items()}},
        "H2",
    )
    yield url


@pytest.fixture()
def app_frontend(frontend_server, page: Page):
    return FrontendPage(frontend_server, page)


def _reset_db_via_http(backend_url: str) -> None:
    """POST to ``/api/testing/reset-db`` so the *running* backend truncates
    its own mutable tables.  Used when ``CURIO_E2E_USE_EXISTING=1`` because
    the pytest process may not share the same sqlite file as the backend.
    """
    from urllib.request import Request, urlopen
    import json as _json

    req = Request(
        f"{backend_url}/api/testing/reset-db",
        data=_json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:  # noqa: S310
        resp.read()


def _e2e_backend_base_url() -> str:
    """Backend base URL when attaching to an existing stack (no fixtures).

    Must match ``e2e_existing_servers`` / ``CURIO_E2E_*`` env vars so
    ``e2e_clean_db`` does not depend on ``current_server`` (which would
    force session ``app`` resolution and clash with package-local ``app``).
    """
    host = os.environ.get("CURIO_E2E_HOST", "127.0.0.1")
    port = int(os.environ.get("CURIO_E2E_BACKEND_PORT", "5002"))
    return f"http://{host}:{port}"


def _clean_db(request, test_db_paths) -> None:
    """Truncate mutable tables in the backend's DB.

    When ``CURIO_E2E_USE_EXISTING=1`` the backend may use a different sqlite
    file than the one ``conftest.py`` resolved, so we call
    ``/api/testing/reset-db`` over HTTP instead of touching the file directly.

    Skipped for ``TestWorkflowCanvas`` (class-scoped ``loaded_workflow`` /
    ``workflow_page``) so tests share one DB-backed session and canvas; a
    reset between methods would invalidate the stub user's token while the
    browser still holds the cookie, and the File menu never appears.

    We skip by class name as well as ``fixturenames`` because some pytest
    versions/paths do not list indirect fixtures in ``request.fixturenames``
    early enough for autouse ordering.
    """
    if getattr(request, "cls", None) and request.cls.__name__ == (
        "TestWorkflowCanvas"
    ):
        return
    if (
        "loaded_workflow" in request.fixturenames
        or "workflow_page" in request.fixturenames
    ):
        return
    if os.environ.get("CURIO_E2E_USE_EXISTING"):
        _reset_db_via_http(_e2e_backend_base_url())
    else:
        _truncate_sqlite(test_db_paths["sqla"], _SQLA_MUTABLE_TABLES)


@pytest.fixture(scope="session")
def workflow_files():
    """Session-scoped fixture exposing the list of workflow file paths."""
    from .conftest import load_workflow_files_from_folder
    return load_workflow_files_from_folder()


# ---------------------------------------------------------------------------
# Class-scoped fixtures – one browser page per parametrized workflow
# ---------------------------------------------------------------------------

VIEWPORT = {"width": 1280, "height": 720}

@pytest.fixture(scope="class")
def workflow_page(browser):
    """Class-scoped page: one browser tab shared by every test method."""
    context = browser.new_context(viewport=VIEWPORT)
    page = context.new_page()
    debug_log(
        "fixtures.py:workflow_page",
        "Page created",
        {"page_url": str(page.url), "page_is_closed": page.is_closed()},
        "H3",
    )
    yield page
    page.close()
    context.close()


@pytest.fixture(scope="class")
def workflow_frontend(frontend_server, workflow_page):
    """Class-scoped FrontendPage wrapper."""
    debug_log(
        "fixtures.py:workflow_frontend",
        "Creating workflow_frontend",
        {
            "frontend_server": frontend_server,
            "page_url": str(workflow_page.url),
            "page_is_closed": workflow_page.is_closed(),
        },
        "H2,H3",
    )
    return FrontendPage(frontend_server, workflow_page)


def _workflow_test_username(workflow_file: str) -> str:
    """Derive a deterministic, valid username (3-32 ``[a-zA-Z0-9_]``) from a
    workflow filename so every parametrized ``TestWorkflowCanvas`` instance
    signs up as its own user.

    Uses a short hash suffix so long/unicode filenames still fit the
    ``USERNAME_RE`` constraint enforced by ``app/users/schemas.py``.
    """
    import hashlib
    import re as _re

    stem = os.path.splitext(os.path.basename(workflow_file))[0]
    slug = _re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_") or "wf"
    slug = slug[:20]
    digest = hashlib.sha1(workflow_file.encode("utf-8")).hexdigest()[:8]
    return f"wf_{slug}_{digest}"


@pytest.fixture(scope="class")
def loaded_workflow(
    request, workflow_frontend, workflow_page, current_server,
):
    """Stub a fresh user in the DB, open a new workflow canvas, upload the
    workflow JSON once, and expose spec + page to the class.

    Every workflow/project route is gated by ``RequireAuth`` in the SPA, so
    the class-scoped browser must authenticate before it can reach the
    ReactFlow canvas. Instead of driving the signup form (slow and
    brittle), we use DB stubs: ``/api/testing/stub-login`` creates the user
    and issues a session token, and
    :func:`stub_login_and_enter_new_workflow` installs it as the
    ``session_token`` cookie on the Playwright context before navigating
    into a fresh workflow canvas. A deterministic username derived from
    the workflow filename keeps each parametrized class isolated even
    though ``e2e_clean_db`` does not truncate between the test methods of
    a single workflow class.

    The uploaded JSON has deterministic random seeds injected into every
    node's code so that browser-side execution matches the programmatic
    expected-data generation (see ``execute_workflow_programmatically``).
    The original *spec* (un-seeded) is kept for content assertions — they
    use a substring check so the seed prefix doesn't break them.
    """
    from .workflow_spec import parse_workflow

    workflow_file = request.param
    spec = parse_workflow(workflow_file)

    # Build a seeded copy of the workflow JSON for the browser upload
    with open(workflow_file, "r") as f:
        wf_data = json.load(f)
    for node_json in wf_data["dataflow"]["nodes"]:
        content = node_json.get("content", "")
        if content.strip() and node_json.get("type") in CODE_TYPES:
            node_json["content"] = seed_node_code(content)
    seeded_tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w",
    )
    json.dump(wf_data, seeded_tmp)
    seeded_tmp.close()

    # DB-stub login + DB-stubbed empty project, then navigate *directly* to
    # /workflow/<project_id> — no signup form, no "+ New Workflow" click on
    # /projects. The stub endpoints are available in any non-production
    # environment (CURIO_ENV != 'prod'); see backend/app/testing/routes.py.
    # upload_workflow then imports the seeded JSON onto that canvas.
    # test_project_* tests still exercise the real /auth/signup UI via
    # utils.signup_and_enter_new_workflow.
    username = _workflow_test_username(workflow_file)
    stub_result = stub_login_and_enter_workflow(
        workflow_page,
        frontend_url=workflow_frontend.base_url,
        backend_url=current_server,
        name=f"Workflow Tester ({username})",
        username=username,
        project_name=f"stub_{username}",
    )

    debug_log(
        "fixtures.py:loaded_workflow",
        "About to upload_workflow",
        {
            "workflow_file": workflow_file,
            "nodes_count": spec.nodes_count,
            "page_is_closed": workflow_page.is_closed(),
            "page_url": str(workflow_page.url),
            "stub_username": username,
            "stub_project_id": stub_result["project"]["id"],
        },
        "H3,H4",
    )
    upload_workflow(
        workflow_page, workflow_frontend, seeded_tmp.name, spec.nodes_count,
    )
    request.cls.spec = spec
    request.cls.page = workflow_page
    yield
    os.unlink(seeded_tmp.name)
    if os.environ.get("CURIO_PAUSE_AFTER"):
        input("Tests done — press Enter to close the browser...")
