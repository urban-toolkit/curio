"""The claim this whole feature makes: a dashboard page needs no server.

Everything else about the standalone dashboard can be true while the page still
quietly calls out once, and a single call is the difference between a page that
works on a train and one that does not. Nobody notices in development, because
the server is always there. So this test takes the server away.

It runs against the PRODUCTION static server on the real built bundle, because
that is the only mode that inlines the payload: the development server compiles
the app in memory and cannot inject anything, so the dashboard there is always
the fetching fallback and proves nothing about this.

The method is to abort every request the page makes to anything but its own
assets, counting them, and then assert the count is zero and the app booted
anyway. Aborting rather than merely counting matters: a page that fetches and
tolerates a failure would pass a counting test by looking fine, and fail a real
viewer whose network answers slowly instead of not at all.
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
DIST = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "dist")

PROJECT_ID = "11111111-2222-3333-4444-555555555555"

#: What the page server will inline. A dashboard with nothing pinned: enough to
#: boot the app, read its spec and render the empty state, which is all this
#: test is about. Whether a chart paints is covered against a live stack by
#: test_dashboard_page_e2e.py.
PAYLOAD = {
    "meta": {"projectId": PROJECT_ID, "name": "Standalone"},
    "spec": {
        "dataflow": {
            "name": "Standalone",
            "nodes": [],
            "edges": [],
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "standalone-e2e",
        }
    },
    "outputs": {},
    "outputRefs": [],
    "registry": {"packages": [], "starters": [], "behaviorScripts": {}},
}


def _free_port() -> int:
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    return port


@pytest.fixture(scope="module")
def standalone_server():
    """The production static server, serving a dashboard with its data inside it."""
    index = os.path.join(DIST, "index.html")
    if not os.path.isfile(index):
        pytest.fail(
            "no built frontend at utk_curio/frontend/urban-workflows/dist. "
            "This test covers the production static server, the one a deployed "
            "Curio runs, so without a build there is nothing to serve."
        )

    backend_port = _free_port()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps(PAYLOAD).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", backend_port), Handler)
    threading.Thread(target=backend.serve_forever, daemon=True).start()

    from utk_curio.main import run_spa_static_server

    port = _free_port()
    threading.Thread(
        target=run_spa_static_server,
        args=(DIST, port, "", f"http://127.0.0.1:{backend_port}"),
        daemon=True,
    ).start()
    yield f"http://127.0.0.1:{port}"
    backend.shutdown()
    backend.server_close()


def test_the_page_boots_with_the_server_taken_away(page, standalone_server):
    """Open the dashboard with every call refused, and watch it work anyway."""
    blocked: list[str] = []

    def refuse(route, request):
        blocked.append(request.url)
        route.abort()

    # Everything that is not this page's own assets. The payload travels in the
    # document, so a page that needs nothing will not notice any of this.
    for pattern in ("**/api/**", "**/get?**", "**/get-preview?**", "**/live", "**/starters"):
        page.route(pattern, refuse)

    page.goto(f"{standalone_server}/dashboard/{PROJECT_ID}", wait_until="domcontentloaded")

    # The dashboard's own bar is the proof the app booted and routed, rather
    # than stalling on a spinner or bouncing to a form.
    page.wait_for_selector("[data-testid='open-dataflow-link']", timeout=45000)

    assert blocked == [], (
        "a standalone dashboard reached the network: " + ", ".join(blocked)
    )


def test_it_does_not_ask_a_viewer_to_sign_in(page, standalone_server):
    """A page served complete must never put a login form in front of its reader.

    The page has no session and cannot get one with the server refused, so the
    sign-in form is exactly what would appear if the viewer were not synthesised
    for a standalone page.
    """
    page.route("**/api/**", lambda route, request: route.abort())

    page.goto(f"{standalone_server}/dashboard/{PROJECT_ID}", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid='open-dataflow-link']", timeout=45000)

    assert page.locator("input[type='password']").count() == 0


def test_the_page_renders_what_the_payload_said(page, standalone_server):
    """Proof the app READ the payload, not merely that one was in the document.

    A page could carry its data, make no requests, and still be showing nothing
    of it: the two tests above would both pass. The dataflow's name only exists
    in the embedded spec, so seeing it on screen is the end of the chain, from
    the server inlining it to the loader reading it instead of fetching.
    """
    page.route("**/api/**", lambda route, request: route.abort())

    page.goto(f"{standalone_server}/dashboard/{PROJECT_ID}", wait_until="domcontentloaded")
    page.wait_for_selector("[data-testid='open-dataflow-link']", timeout=45000)

    assert page.get_by_text("Standalone").count() > 0, (
        "the page did not show the name from its own embedded spec"
    )
