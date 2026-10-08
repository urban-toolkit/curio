"""A dashboard that cannot travel as a page of its own says why, and loads nothing.

A dashboard at ``/dashboard/<id>`` carries its data in its page. The backend
refuses to build a page over the 25 MB limit, in words that name the heaviest
node (a 413). The page then shows those words and asks the server for nothing:
fetching the data instead would make a page that looks standalone and is not,
which is what the limit is there to rule out.

The page is served by the production static server on the built bundle,
host-side, pointed at this worker's backend (``serve_built_frontend``), as in
``test_dashboard_raster_e2e.py``. The CI stack's own page server runs inside
its container, where the backend address it was given does not answer, so its
dashboards never carry anything.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_dashboard_refusal_e2e.py -v
"""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    serve_built_frontend,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NAME = "Trips over the limit"
PRODUCER = "dash-heavy-rows"
CHART = "dash-heavy-chart"

#: 30,000 rows of about 1 KB each: about 30 MB once they travel as JSON, over
#: the 25 MB a dashboard page may carry, for a chart of three bars.
PRODUCER_CODE = (
    "import pandas as pd\n\n"
    "rows = 30000\n"
    "return pd.DataFrame({\n"
    "    'category': ['a', 'b', 'c'] * (rows // 3),\n"
    "    'count': list(range(rows)),\n"
    "    'note': ['x' * 1000] * rows,\n"
    "})\n"
)
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"aggregate": "sum", "field": "count", "type": "quantitative"},
    },
}, indent=2)

#: Every route a page asks the server for data on.
DATA_ROUTES = ("**/api/**", "**/get?**", "**/get-preview?**", "**/raster?**", "**/live", "**/starters")


def _node(node_id: str, node_type: str, x: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": NAME,
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(PRODUCER, "curio.builtin/data-loading", 0, PRODUCER_CODE),
                _node(CHART, "curio.builtin/vis-vega", 700, CHART_SPEC),
            ],
            "edges": [
                {"id": f"reactflow__edge-{PRODUCER}out-{CHART}in", "source": PRODUCER, "target": CHART},
            ],
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


def test_a_dashboard_over_the_size_limit_says_why_and_asks_for_nothing(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dashboard Owner",
        username=f"dash_refused_{uuid.uuid4().hex[:8]}",
        project_name=NAME,
        project_spec=_spec(),
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    # The chart runs its producer, and pinning the chart saves the producer's
    # rows: what its dashboard would have to carry.
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    play_node(page, CHART)
    wait_for_node_done(page, CHART, node_type="vis-vega", timeout_ms=180000)
    _pin(page, CHART)
    _save(page)
    # Off the canvas before anything is refused: it can still save on its way
    # out, and that request is the canvas's, not the dashboard's.
    page.goto("about:blank")

    standalone = serve_built_frontend(current_server)

    asked: list[str] = []

    def refuse(route, request):
        asked.append(f"{request.method} {request.url}")
        route.abort()

    for pattern in DATA_ROUTES:
        page.route(pattern, refuse)

    page.goto(f"{standalone}/dashboard/{project_id}", wait_until="domcontentloaded")
    assert page.locator("script#curio-dashboard-payload").count() == 1, (
        "the backend refused this dashboard (over the 25 MB limit) and the page "
        "server carried nothing in its place, so the page is an ordinary one that "
        "fetches the data itself"
    )

    failed = page.get_by_test_id("dashboard-load-failed")
    # The limit's own words, which name the node to aggregate.
    expect(failed).to_contain_text("over the 25.0 MB limit", timeout=45000)
    expect(failed).to_contain_text(PRODUCER)
    expect(page.get_by_role("heading", name=NAME)).to_be_visible()
    assert asked == [], "the refused dashboard asked the server for data: " + ", ".join(asked)

    save_workflow_test_screenshot(
        page,
        "dashboard-refused",
        test_name="test_a_dashboard_over_the_size_limit_says_why_and_asks_for_nothing",
        fit_reactflow=False,
        sweep_toasts=True,
    )
