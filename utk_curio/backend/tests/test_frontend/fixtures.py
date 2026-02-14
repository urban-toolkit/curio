import os
import re
import sys
import time
import pytest
import subprocess
from signal import SIGINT
from urllib.request import urlopen, Request
from urllib.error import URLError
from playwright.sync_api import Page
from .utils import FrontendPage


# Repo root is 4 levels up from this file (test_frontend -> tests -> backend -> utk_curio)
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
TEST_WORKFLOWS_PATH = os.path.join(_REPO_ROOT, "tests")


def is_port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def _wait_for_port(port: int, timeout: float = 30.0, interval: float = 0.5) -> None:
    """Wait until something is listening on port or timeout."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(interval)
    raise TimeoutError(f"Port {port} did not become ready within {timeout}s")


def _wait_for_http_ready(
    base_url: str,
    path: str = "/live",
    timeout: float = 30.0,
    interval: float = 0.5,
) -> None:
    """Wait until GET base_url + path returns 200 or timeout."""
    url = f"{base_url.rstrip('/')}{path}"
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            req = Request(url, method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.getcode() == 200:
                    return
        except (URLError, OSError) as e:
            last_err = e
        time.sleep(interval)
    raise TimeoutError(
        f"HTTP GET {url} did not return 200 within {timeout}s (last error: {last_err})"
    )


def _e2e_existing_servers():
    """When CURIO_E2E_USE_EXISTING=1, use already-running servers (e.g. docker compose).
    Waits for backend and sandbox /live to respond before returning."""
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    backend_port = int(os.environ.get("CURIO_E2E_BACKEND_PORT", "5002"))
    sandbox_port = int(os.environ.get("CURIO_E2E_SANDBOX_PORT", "2000"))
    frontend_port = int(os.environ.get("CURIO_E2E_FRONTEND_PORT", "8080"))
    base = f"http://{host}"
    _wait_for_http_ready(f"{base}:{backend_port}", timeout=60.0)
    _wait_for_http_ready(f"{base}:{sandbox_port}", timeout=60.0)
    return {"backend_port": backend_port, "sandbox_port": sandbox_port, "frontend_port": frontend_port, "_host": host}


@pytest.fixture(scope="session")
def curio_servers(app, request):
    """Start all Curio servers (backend, sandbox, frontend) together via curio start.
    Backend port must match frontend's BACKEND_URL (default 5002 from .env) so the app can reach the API.
    Set CURIO_E2E_USE_EXISTING=1 to use already-running servers (e.g. in CI with docker compose).
    """
    if os.environ.get("CURIO_E2E_USE_EXISTING"):
        yield _e2e_existing_servers()
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
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    _wait_for_port(backend_port, timeout=40.0)
    _wait_for_port(sandbox_port, timeout=45.0)
    _wait_for_port(frontend_port, timeout=90.0)

    # Ensure backend and sandbox respond to /live before tests run
    host = "127.0.0.1"
    _wait_for_http_ready(f"http://{host}:{backend_port}", timeout=15.0)
    _wait_for_http_ready(f"http://{host}:{sandbox_port}", timeout=15.0)

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
    yield {"backend_port": backend_port, "sandbox_port": sandbox_port, "frontend_port": frontend_port, "_host": "127.0.0.1"}


def _base_url(servers: dict, port_key: str) -> str:
    host = servers.get("_host", "127.0.0.1")
    port = servers[port_key]
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def current_server(curio_servers, app):
    """Backend URL (servers already started by curio_servers or existing stack)."""
    yield _base_url(curio_servers, "backend_port")


@pytest.fixture(scope="session")
def sandbox_server(curio_servers, app):
    """Sandbox URL (servers already started by curio_servers or existing stack)."""
    yield _base_url(curio_servers, "sandbox_port")


@pytest.fixture(scope="session")
def frontend_server(curio_servers, app):
    """Frontend URL (servers already started by curio_servers or existing stack)."""
    url = _base_url(curio_servers, "frontend_port")
    # #region agent log
    import json as _json, time as _time
    _DBG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".curio", "playwright.log")
    try:
        with open(_DBG, "a") as _f:
            _f.write(_json.dumps({"timestamp": int(_time.time()*1000), "location": "fixtures.py:frontend_server", "message": "Frontend server URL resolved", "data": {"url": url, "curio_servers": {k: v for k, v in curio_servers.items()}}, "hypothesisId": "H2"}) + "\n")
    except Exception:
        pass
    # #endregion
    yield url


@pytest.fixture()
def app_frontend(frontend_server, page: Page):
    return FrontendPage(frontend_server, page)


# ---------------------------------------------------------------------------
# Workflow file discovery
# ---------------------------------------------------------------------------

def load_workflow_files_from_folder():
    """Load all workflow JSON files from the specified folder.

    Returns a list of absolute paths.  This is a plain function (not a
    fixture) because ``@pytest.mark.parametrize`` evaluates its arguments
    at **collection time**, before fixtures are resolved.
    """
    workflow_files = [
        "DefaultWorkflow.json",

        "DataPool_df.json",
        "DataPool_gdf.json",

        "DataPool_Vega_2.json",
        "DataPool_Vega.json",
        "DataPool_UTK.json",

        "Image.json",
        "Merge.json",
        "MergeFlowDataPool.json",

        "Interaction.json",
        "Interaction_UTK.json",
        "Interaction_Vega.json",

#         "NewMerge.json",
        "Number Multiplier (Widget).json",

        "Vega.json",

        "UTK.json",
    ]

    # append the path to the folder path
    workflow_files = [os.path.join(TEST_WORKFLOWS_PATH, filename) for filename in workflow_files]

    return workflow_files


@pytest.fixture(scope="session")
def workflow_files():
    """Session-scoped fixture exposing the list of workflow file paths.

    Wraps :func:`load_workflow_files_from_folder` so that test functions
    can receive the file list via dependency injection instead of calling
    the helper directly.
    """
    return load_workflow_files_from_folder()


# ---------------------------------------------------------------------------
# Reusable upload helper
# ---------------------------------------------------------------------------

def upload_workflow(page, app_frontend, workflow_file: str, expected_node_count: int):
    """Navigate to the app, open the File menu, upload a workflow JSON,
    and wait until the expected number of nodes appear on the canvas."""
    # #region agent log
    import json as _json, time as _time
    _DBG = os.path.join(_REPO_ROOT, ".curio", "playwright.log")
    def _dl(loc, msg, data=None, hid=""):
        try:
            with open(_DBG, "a") as _f:
                _f.write(_json.dumps({"timestamp": int(_time.time()*1000), "location": loc, "message": msg, "data": data or {}, "hypothesisId": hid}) + "\n")
        except Exception:
            pass
    _dl("test_workflows.py:upload_workflow", "upload_workflow called", {"page_type": type(page).__name__, "app_frontend_type": type(app_frontend).__name__, "workflow_file": workflow_file, "expected_node_count": expected_node_count, "page_is_closed": page.is_closed(), "page_url": str(page.url)}, "H1,H2,H3")
    # #endregion
    app_frontend.goto_page("/")
    page.wait_for_load_state("domcontentloaded")

    # Open the File dropdown in the menu bar
    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=15000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the ReactFlow canvas layer on top
    file_menu_btn.click(force=True)

    # Click "Load specification" and upload the JSON file
    load_spec = page.get_by_role("button", name="Load specification")
    load_spec.wait_for(state="visible", timeout=5000)
    assert load_spec.is_visible()

    with page.expect_file_chooser() as fc_info:
        page.get_by_text("Load specification").click()
    fc_info.value.set_files(workflow_file)

    # Wait until all expected nodes have rendered on the ReactFlow canvas
    page.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= {expected_node_count}",
        timeout=15000,
    )


# ---------------------------------------------------------------------------
# Class-scoped fixtures – one browser page per parametrized workflow
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def workflow_page(browser):
    """Class-scoped page: one browser tab shared by every test method."""
    # #region agent log
    import json as _json, time as _time
    _DBG = os.path.join(_REPO_ROOT, ".curio", "playwright.log")
    def _dl(loc, msg, data=None, hid=""):
        try:
            with open(_DBG, "a") as _f:
                _f.write(_json.dumps({"timestamp": int(_time.time()*1000), "location": loc, "message": msg, "data": data or {}, "hypothesisId": hid}) + "\n")
        except Exception:
            pass
    _dl("test_workflows.py:workflow_page", "Creating workflow_page", {"browser_type": type(browser).__name__, "browser_connected": browser.is_connected()}, "H3")
    # #endregion
    context = browser.new_context()
    page = context.new_page()
    # #region agent log
    _dl("test_workflows.py:workflow_page", "Page created", {"page_url": str(page.url), "page_is_closed": page.is_closed()}, "H3")
    # #endregion
    yield page
    page.close()
    context.close()


@pytest.fixture(scope="class")
def workflow_frontend(frontend_server, workflow_page):
    """Class-scoped FrontendPage wrapper."""
    # #region agent log
    import json as _json, time as _time
    _DBG = os.path.join(_REPO_ROOT, ".curio", "playwright.log")
    def _dl(loc, msg, data=None, hid=""):
        try:
            with open(_DBG, "a") as _f:
                _f.write(_json.dumps({"timestamp": int(_time.time()*1000), "location": loc, "message": msg, "data": data or {}, "hypothesisId": hid}) + "\n")
        except Exception:
            pass
    _dl("test_workflows.py:workflow_frontend", "Creating workflow_frontend", {"frontend_server": frontend_server, "page_url": str(workflow_page.url), "page_is_closed": workflow_page.is_closed()}, "H2,H3")
    # #endregion
    return FrontendPage(frontend_server, workflow_page)


@pytest.fixture(scope="class")
def loaded_workflow(request, workflow_frontend, workflow_page):
    """Upload the workflow once and expose spec + page to the class."""
    from .test_workflows import parse_workflow

    workflow_file = request.param
    spec = parse_workflow(workflow_file)
    # #region agent log
    import json as _json, time as _time
    _DBG = os.path.join(_REPO_ROOT, ".curio", "playwright.log")
    def _dl(loc, msg, data=None, hid=""):
        try:
            with open(_DBG, "a") as _f:
                _f.write(_json.dumps({"timestamp": int(_time.time()*1000), "location": loc, "message": msg, "data": data or {}, "hypothesisId": hid}) + "\n")
        except Exception:
            pass
    _dl("test_workflows.py:loaded_workflow", "About to upload_workflow", {"workflow_file": workflow_file, "nodes_count": spec.nodes_count, "page_is_closed": workflow_page.is_closed(), "page_url": str(workflow_page.url)}, "H3,H4")
    # #endregion
    upload_workflow(workflow_page, workflow_frontend, workflow_file, spec.nodes_count)
    request.cls.spec = spec
    request.cls.page = workflow_page
    yield
    # Pause 10 s after all tests for this workflow (visible in --headed mode)
    # time.sleep(10)

