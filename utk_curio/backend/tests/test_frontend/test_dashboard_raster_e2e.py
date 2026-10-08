"""A standalone dashboard draws a pinned Autark map over a raster.

An Autark map loads a Python node's raster as GeoTIFF bytes it asks the server
for (``GET /raster``, ``adapters/node/autkRasters.ts``), and a dashboard page
carries its own data, so that it draws with no server at all. So the page
carries the raster's GeoTIFF as well, and the map reads it there.

The page is served by the production static server on the real built bundle,
host-side, as in ``test_dashboard_standalone_e2e.py``: only that server inlines
the payload. The CI stack's own static server runs inside its container, where
the backend address it was given is the host's, so its dashboards are ordinary
fetching pages. This one is pointed at this worker's backend, so the payload it
inlines is the one the backend builds for the dataflow this test saved. The
page then opens with every data route refused and counted.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_dashboard_raster_e2e.py -v
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .test_autark_raster_e2e import MAP_SPEC, PYTHON_RASTER
from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    REPO_ROOT,
    activate_header_icon,
    assert_autark_map_drawn,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DIST = os.path.join(REPO_ROOT, "utk_curio", "frontend", "urban-workflows", "dist")

MAP_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/computation-analysis"
RASTER = "dash-raster"
MAP = "dash-raster-map"

SCREENSHOT_STEM = "dashboard-raster-map"

#: Every route a page asks the server for data on. A standalone page asks none.
DATA_ROUTES = ("**/api/**", "**/get?**", "**/get-preview?**", "**/raster?**", "**/live", "**/starters")


def _spec() -> dict:
    def node(node_id: str, node_type: str, x: int, content: str) -> dict:
        return {
            "id": node_id, "type": node_type, "x": x, "y": 160, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        }

    return {
        "dataflow": {
            "name": "Dashboard raster",
            "task": "",
            "nodes": [
                node(RASTER, PYTHON_TYPE, 120, PYTHON_RASTER),
                node(MAP, MAP_TYPE, 820, json.dumps(MAP_SPEC, indent=2)),
            ],
            "edges": [{
                "id": f"reactflow__edge-{RASTER}out-{MAP}in",
                "source": RASTER, "target": MAP, "sourceHandle": "out", "targetHandle": "in",
            }],
        },
    }


def _pin(page, node_id: str) -> None:
    node = node_locator(page, node_id)
    activate_header_icon(node.locator('[title="Pin to dashboard"]').first)
    expect(node.locator('[title="Unpin from dashboard"]')).to_have_count(1, timeout=10000)


def _save(page) -> None:
    """Save through the status icon and wait until the dataflow is on disk."""
    page.locator("[data-curio-save-state]").first.click(force=True)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )


def _free_port() -> int:
    probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = probe.server_address[1]
    probe.server_close()
    return port


def _serve_dashboards(backend_url: str) -> str:
    """The production static server on the built bundle, asking *backend_url*
    for each dashboard's payload, as a deployed Curio's does."""
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        pytest.fail(
            "no built frontend at utk_curio/frontend/urban-workflows/dist. Only the "
            "production static server inlines a dashboard's payload, so without a "
            "build there is no standalone page to open."
        )
    from utk_curio.cli.static_server import run_spa_static_server

    port = _free_port()
    threading.Thread(
        target=run_spa_static_server, args=(DIST, port, "", backend_url), daemon=True,
    ).start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}/", method="HEAD"), timeout=2):
                return url
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def test_a_standalone_dashboard_draws_a_pinned_raster_map(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dashboard Raster",
        username=f"dash_raster_{uuid.uuid4().hex[:8]}",
        project_name="Dashboard raster",
        project_spec=_spec(),
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    # The editor draws the raster first, from the server: what the page must
    # then draw without one.
    play_node(page, MAP)
    wait_for_node_done(page, MAP, node_type=MAP_TYPE)
    assert_autark_map_drawn(page, MAP, timeout=60000)
    _pin(page, MAP)
    _save(page)

    standalone = _serve_dashboards(current_server)

    asked: list[str] = []

    def refuse(route, request):
        asked.append(request.url)
        route.abort()

    for pattern in DATA_ROUTES:
        page.route(pattern, refuse)
    # DuckDB's spatial extension is part of the app, not data: the backend
    # serves it from vendor/, and a failure to get it would read as a map that
    # did not draw for some other reason.
    extension_failures: list[str] = []
    page.on(
        "requestfailed",
        lambda request: extension_failures.append(f"{request.url} ({request.failure})")
        if "duckdb-extensions" in request.url else None,
    )

    page.goto(f"{standalone}/dashboard/{project_id}", wait_until="domcontentloaded")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    assert page.locator("script#curio-dashboard-payload").count() == 1, (
        "the page server inlined no payload, so this is an ordinary page that fetches for itself"
    )

    drawn_problem = None
    try:
        assert_autark_map_drawn(page, MAP, timeout=120000, attach_as="a raster map on a standalone dashboard")
    except AssertionError as exc:
        drawn_problem = str(exc)
    assert asked == [], (
        "the standalone dashboard asked the server for data: " + ", ".join(asked)
        + f". The map: {drawn_problem or 'drew'}"
    )
    assert drawn_problem is None, (
        f"{drawn_problem}. DuckDB extension requests that failed: {extension_failures or 'none'}"
    )

    save_workflow_test_screenshot(
        page,
        SCREENSHOT_STEM,
        test_name="test_a_standalone_dashboard_draws_a_pinned_raster_map",
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD,
        max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
        clip_selector=f'.react-flow__node[data-id="{MAP}"]',
        sweep_toasts=True,
        closeup=True,
    )
