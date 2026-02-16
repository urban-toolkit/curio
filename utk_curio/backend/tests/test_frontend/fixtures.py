import os
import sys
import time
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
)


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
def curio_servers(app, request):
    """Start all Curio servers (backend, sandbox, frontend) together via curio start.
    Backend port must match frontend's BACKEND_URL (default 5002 from .env) so the app can reach the API.
    Set CURIO_E2E_USE_EXISTING=1 to use already-running servers (e.g. in CI with docker compose).
    """
    if os.environ.get("CURIO_E2E_USE_EXISTING"):
        yield e2e_existing_servers()
        return

    backend_port = int(app.config["BACKEND_PORT"])
    sandbox_port = int(app.config["SANDBOX_PORT"])
    frontend_port = int(app.config["FRONTEND_PORT"])

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

    process = subprocess.Popen(
        [
            "python", "curio.py", "start",
            "--backend-port", str(backend_port),
            "--sandbox-port", str(sandbox_port),
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
def current_server(curio_servers, app):
    """Backend URL (servers already started by curio_servers or existing stack)."""
    yield base_url(curio_servers, "backend_port")


@pytest.fixture(scope="session")
def sandbox_server(curio_servers, app):
    """Sandbox URL (servers already started by curio_servers or existing stack)."""
    yield base_url(curio_servers, "sandbox_port")


@pytest.fixture(scope="session")
def frontend_server(curio_servers, app):
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


@pytest.fixture(scope="session")
def workflow_files():
    """Session-scoped fixture exposing the list of workflow file paths."""
    from .conftest import load_workflow_files_from_folder
    return load_workflow_files_from_folder()


# ---------------------------------------------------------------------------
# Class-scoped fixtures – one browser page per parametrized workflow
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def workflow_page(browser):
    """Class-scoped page: one browser tab shared by every test method."""
    context = browser.new_context()
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


@pytest.fixture(scope="class")
def loaded_workflow(request, workflow_frontend, workflow_page):
    """Upload the workflow once and expose spec + page to the class."""
    from .test_workflows import parse_workflow

    workflow_file = request.param
    spec = parse_workflow(workflow_file)
    debug_log(
        "fixtures.py:loaded_workflow",
        "About to upload_workflow",
        {
            "workflow_file": workflow_file,
            "nodes_count": spec.nodes_count,
            "page_is_closed": workflow_page.is_closed(),
            "page_url": str(workflow_page.url),
        },
        "H3,H4",
    )
    upload_workflow(workflow_page, workflow_frontend, workflow_file, spec.nodes_count)
    request.cls.spec = spec
    request.cls.page = workflow_page
    yield
    # Pause 10 s after all tests for this workflow (visible in --headed mode)
    # only in development mode
    if os.environ.get("FLASK_ENV") == "testing":
        time.sleep(3)
