"""Network and server helpers: ports, readiness and the servers of a running stack."""

import os
import time
from urllib.request import urlopen, Request
from urllib.error import URLError


# ---------------------------------------------------------------------------
# Network / server helpers
# ---------------------------------------------------------------------------

def is_port_in_use(port: int) -> bool:
    """Return ``True`` if *port* is already listening on localhost."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def wait_for_http_ready(
    base_url: str,
    path: str = "/live",
    timeout: float = 30.0,
    interval: float = 0.5,
) -> None:
    """Wait until ``GET base_url + path`` returns 200 or raise ``TimeoutError``."""
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
        f"HTTP GET {url} did not return 200 within {timeout}s "
        f"(last error: {last_err})"
    )


def wait_for_port(
    port: int, timeout: float = 30.0, interval: float = 0.5
) -> None:
    """Wait until something is listening on *port* or raise ``TimeoutError``."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(interval)
    raise TimeoutError(
        f"Port {port} did not become ready within {timeout}s"
    )


def e2e_existing_servers():
    """When ``CURIO_E2E_USE_EXISTING=1``, use already-running servers.

    Waits for backend and sandbox ``/live`` to respond before returning.
    """
    host = os.environ.get("CURIO_E2E_HOST", "localhost")
    backend_port = int(os.environ.get("CURIO_E2E_BACKEND_PORT", "5002"))
    sandbox_port = int(os.environ.get("CURIO_E2E_SANDBOX_PORT", "2000"))
    frontend_port = int(os.environ.get("CURIO_E2E_FRONTEND_PORT", "8080"))
    base = f"http://{host}"
    wait_for_http_ready(f"{base}:{backend_port}", timeout=60.0)
    wait_for_http_ready(f"{base}:{sandbox_port}", timeout=60.0)
    return {
        "backend_port": backend_port,
        "sandbox_port": sandbox_port,
        "frontend_port": frontend_port,
        "_host": host,
    }


def base_url(servers: dict, port_key: str) -> str:
    """Build an ``http://host:port`` URL from the *servers* dict."""
    host = servers.get("_host", "127.0.0.1")
    port = servers[port_key]
    return f"http://{host}:{port}"


def serve_built_frontend(backend_url: str) -> str:
    """Start the production page server on the built bundle, host-side; returns its URL.

    It is the server a deployed Curio runs (``run_spa_static_server``), the one
    that serves a dashboard's page with its data, which it asks *backend_url*
    (its ``--backend-url``) for. The CI stack's own page server runs inside its
    container, where the address it was given does not answer, so its dashboard
    pages carry nothing; a test that opens one that does serves it here. The
    server runs in a daemon thread for the rest of the worker's life.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import pytest

    from utk_curio.cli.static_server import run_spa_static_server

    from .environment import REPO_ROOT

    dist = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "dist")
    if not os.path.isfile(os.path.join(dist, "index.html")):
        pytest.fail(
            "no built frontend at utk_curio/frontend/urban-workflows/dist. Only the "
            "production page server serves a dashboard with its data, so without a "
            "build there is no such page to open."
        )
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    threading.Thread(
        target=run_spa_static_server, args=(dist, port, "", backend_url), daemon=True,
    ).start()
    url = f"http://127.0.0.1:{port}"
    wait_for_http_ready(url, path="/", timeout=15.0)
    return url
