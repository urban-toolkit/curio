import os
import sys
import time
import pytest
import subprocess
from signal import SIGINT
from urllib.request import urlopen, Request
from urllib.error import URLError
from playwright.sync_api import Page
from .utils import FrontendPage


def _project_root():
    """Project root (curio-main) when pytest is run from utk_curio/backend."""
    return os.path.abspath(os.path.join(os.getcwd(), "..", ".."))


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
        cwd=_project_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    _wait_for_port(backend_port, timeout=20.0)
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
    yield _base_url(curio_servers, "frontend_port")


@pytest.fixture()
def app_frontend(frontend_server, page: Page):
    return FrontendPage(frontend_server, page)
