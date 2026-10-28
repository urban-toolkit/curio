"""Playwright E2E: the dashboard is a page of its own, at ``/dashboard/<id>``.

It used to be a mode of the canvas. That had three consequences this file
exists to keep from coming back: there was no URL to hand anyone; a reload
showed empty boxes, because a chart only drew when Play was pressed; and even a
restored output was unreadable outside the session that ran it, because the
artifact store is session-tagged.

What replaced it, and what each test below pins:

* pinning a node makes the outputs FEEDING it save to the Data Catalog, so the
  tile has something to draw from later;
* a load hands those saved outputs back to the nodes (for the canvas too), and
  a chart compiles against them without a Play;
* the sandbox ``/get`` serves a saved output by name when the session-tagged
  store cannot, which is what makes a visitor's view, or the owner's next
  sign-in, work at all;
* the page's layout is the owner's alone, the page cannot delete anything, and
  its one write (Save layout) leaves the dataflow's recorded outputs alone;
* a visitor changes a pinned control and the tiles show a run of that value on
  the server, which never changes the dataflow; the next visitor who picks the same value
  gets the output kept from that run, and nothing runs again (#1117);
* a step only a browser runs (a GPU step) is run by each visitor's page, and
  what a page sends, and what is made from it, is kept for that page alone
  (#1117);
* a dataflow's scenarios each get a column of tiles under a header in their
  color, and Arrange by scenario puts the tiles back in them (#662);
* a pinned node's own widgets are its tile's controls: a code node's in place
  of its code, a chart's above it. A pick on a code node's tile runs it on the
  server for the tiles below; a chart draws again with its own new value in
  the page. A tile's code is read-only (#1117);
* a tile's chart is laid out for the axis labels it draws, whether the page
  drew it fresh, gave it new rows in place or fitted it again after a resize.

The dataflow is built here rather than borrowed from ``docs/examples``: three
nodes, no datasets, so a failure is about this feature and not about a seed.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_dashboard_page_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from .utils import (
    VIEWPORT_SETTLE_WAIT_MS,
    _wait_for_no_node_running,
    activate_header_icon,
    allow_guest_login_env,
    api_json,
    assert_vega_canvas_rendered,
    dismiss_toasts,
    empty_pane_point,
    node_locator,
    park_pointer,
    play_node,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    save_workflow_test_screenshot,
    serve_built_frontend,
    stub_db_login,
    stub_login_and_enter_workflow,
    viewport_hints,
    viewport_will_change,
    wait_for_node_done,
    watch_viewport_hint,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PRODUCER = "dash-producer"
POOL = "dash-pool"
CHART = "dash-chart"

#: What the chart plots. Three bars, so "the chart drew" and "the chart drew the
#: saved rows" are the same assertion.
PRODUCER_CODE = (
    "import pandas as pd\n\n"
    "return pd.DataFrame({'category': ['a', 'b', 'c'], 'count': [3, 7, 5]})\n"
)
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}, indent=2)

#: Every route a page asks the server for data on.
DATA_ROUTES = ("**/api/**", "**/get?**", "**/get-preview?**", "**/raster?**", "**/live", "**/starters")


def _node(node_id: str, node_type: str, x: int, content: str = "") -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": 0,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
        "content": content,
    }


def _spec() -> dict:
    """Producer -> Data Pool -> Vega chart: the shape most dashboards have."""
    return {
        "dataflow": {
            "name": "Dashboard e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(PRODUCER, "curio.builtin/data-loading", 0, PRODUCER_CODE),
                _node(POOL, "curio.builtin/data-pool", 700),
                _node(CHART, "curio.builtin/vis-vega", 1400, CHART_SPEC),
            ],
            "edges": [
                {"id": f"reactflow__edge-{PRODUCER}out-{POOL}in", "source": PRODUCER, "target": POOL},
                {"id": f"reactflow__edge-{POOL}out-{CHART}in", "source": POOL, "target": CHART},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Steps shared by the scenarios
# ---------------------------------------------------------------------------

def _enter(page, app_frontend, current_server, *, prefix: str, spec: dict | None = None) -> dict:
    """Sign in as a fresh owner, on the canvas of a fresh copy of the dataflow
    (*spec*, by default the chart's)."""
    spec = spec or _spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dashboard Owner",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    return session


def _run_the_chart(page) -> None:
    """Play the chart, which runs the chain behind it, and prove it drew."""
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    play_node(page, CHART)
    wait_for_node_done(page, CHART, node_type="vis-vega", timeout_ms=180000)
    assert_vega_canvas_rendered(page, CHART, timeout=60000)


def _pin(page, node_id: str) -> None:
    node = node_locator(page, node_id)
    activate_header_icon(node.locator('[data-tooltip="Pin to dashboard"]').first)
    expect(node.locator('[data-tooltip="Unpin from dashboard"]')).to_have_count(1, timeout=10000)


def _save(page) -> None:
    """Save through the status icon and wait until the dataflow is on disk."""
    page.locator("[data-curio-save-state]").first.click(force=True)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )


def _pinned_and_saved(page, app_frontend, current_server, *, prefix: str, spec: dict | None = None) -> dict:
    """The common starting point: the chart ran, is pinned, and is saved."""
    session = _enter(page, app_frontend, current_server, prefix=prefix, spec=spec)
    _run_the_chart(page)
    _pin(page, CHART)
    _save(page)
    return session


def _chart_drew(page, *, timeout: float = 90000) -> None:
    """The chart's canvas exists and has marks on it."""
    assert_vega_canvas_rendered(page, CHART, timeout=timeout)


def _open_dashboard(page, base: str, project_id: str) -> None:
    page.goto(f"{base}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)


def _starts_a_run(request) -> bool:
    """A viewer's run started (``POST /api/projects/<id>/dashboard/runs``)."""
    return request.method == "POST" and urlsplit(request.url).path.endswith("/dashboard/runs")


def _runs_started_on(page) -> list[str]:
    """Every viewer's run *page* starts from now on."""
    started: list[str] = []
    page.on("request", lambda request: started.append(request.url) if _starts_a_run(request) else None)
    return started


def _project(current_server: str, token: str, project_id: str) -> dict:
    return api_json(f"{current_server}/api/projects/{project_id}", token)


def _node_in_spec(project: dict, node_id: str) -> dict:
    return next(n for n in project["spec"]["dataflow"]["nodes"] if n["id"] == node_id)


# ---------------------------------------------------------------------------
# The owner
# ---------------------------------------------------------------------------

def test_the_owner_opens_a_dashboard_that_draws_without_a_run(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_owner")
    project_id = session["project"]["id"]

    # Pinning is what made the producer's output a saved one: the pool passes
    # data through and the chart only draws it, so the producer is the node a
    # reload needs. It is recorded on the project and in the Data Catalog.
    project = _project(current_server, session["token"], project_id)
    recorded = [o["node_id"] for o in project["outputs"]]
    assert recorded == [PRODUCER], (
        f"the save recorded {recorded!r}; the dashboard needs the output feeding "
        f"its pinned chart, and nothing else"
    )
    catalog = api_json(
        f"{current_server}/api/datasets/catalog?dataflowId={project_id}", session["token"],
    )
    items = catalog.get("items", catalog) if isinstance(catalog, dict) else catalog
    producers = {item.get("producerNodeId") for item in items}
    assert PRODUCER in producers, (
        "the output behind the pinned chart is not in the Data Catalog, so nothing "
        "durable would be left to draw from once the scratch cache is cleared"
    )

    # A full load of the page: nothing from the canvas session comes along,
    # and nothing runs, since the tile has its saved output.
    started = _runs_started_on(page)
    _open_dashboard(page, app_frontend.base_url, project_id)
    _chart_drew(page)
    assert started == [], f"opening the dashboard started a run: {started!r}"

    # A page, not the canvas.
    assert page.locator("#tools-menu").count() == 0, "the editor's palette is on the dashboard"
    assert page.get_by_role("button", name="Pin to dashboard").count() == 0
    assert page.get_by_test_id("edit-layout-btn").is_visible()
    # Every node is loaded, pinned or not: the pool behind the chart has to run.
    count = page.evaluate("() => window.__curio_reactFlow.getNodes().length")
    assert count == 3, f"the dashboard loaded {count} nodes of 3"
    visible = page.evaluate(
        "() => window.__curio_reactFlow.getNodes()"
        ".filter((n) => n.style?.display !== 'none').map((n) => n.id)"
    )
    assert visible == [CHART], f"tiles on the page: {visible!r}"


def _serve_hosted(app_frontend: "FrontendPage", current_server: str, monkeypatch) -> str:
    """The production page server on the built bundle, started the hosted way.

    The hosted stacks start Curio with ``--backend-url /api``: the backend is a
    path on whichever host serves the page, behind a proxy. The page server
    asks the backend the launcher started for a dashboard's data, at the
    address the launcher hands its children (FLASK_BACKEND_HOST/PORT), here
    this worker's backend. The dashboards the other tests here open come from
    this stack's own page server, which was given an address on the runner
    that does not answer inside its container, so they fetch their data.

    It is opened on the app's own host, as a hosted stack serves both from one
    origin, so a browser signed in to the app is signed in on the page too.
    """
    backend = urlsplit(current_server)
    monkeypatch.setenv("FLASK_BACKEND_HOST", backend.hostname)
    monkeypatch.setenv("FLASK_BACKEND_PORT", str(backend.port))
    return serve_built_frontend("/api", host=urlsplit(app_frontend.base_url).hostname)


def test_a_dashboard_served_as_the_hosted_stacks_serve_it_carries_its_data(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """The page draws with every data request refused, because it carries its data.

    Opened by a visitor with no session, in a browser of its own: nothing at
    all is asked of the server.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_hosted")
    project_id = session["project"]["id"]
    # Off the canvas: it can still save on its way out.
    page.goto("about:blank")
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor_ctx = browser.new_context()
    try:
        visitor = visitor_ctx.new_page()
        asked: list[str] = []

        def refuse(route, request):
            asked.append(f"{request.method} {request.url}")
            route.abort()

        for pattern in DATA_ROUTES:
            visitor.route(pattern, refuse)

        visitor.goto(f"{hosted}/dashboard/{project_id}", wait_until="domcontentloaded")
        assert visitor.locator("script#curio-dashboard-payload").count() == 1, (
            "the page server, given --backend-url /api as the hosted stacks are, served "
            "the dashboard without its data, so the page fetches it from the server"
        )
        visitor.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
        drawn_problem = None
        try:
            _chart_drew(visitor)
        except (AssertionError, PlaywrightTimeoutError) as exc:
            drawn_problem = str(exc)
        assert asked == [], (
            "the dashboard asked the server for data: " + ", ".join(asked)
            + f". The chart: {drawn_problem or 'drew'}"
        )
        assert drawn_problem is None, drawn_problem
    finally:
        visitor_ctx.close()


#: The one thing a page served with its data asks when the browser holds a
#: session: whether that session may edit the dashboard's layout.
EDIT_CHECK_PATH = "/dashboard/can-edit"


def test_the_owner_of_a_dashboard_served_with_its_data_edits_its_layout(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """Served with its data, the dashboard still knows its owner.

    A page served complete has no session of its own and names no account. A
    browser that holds a session asks whether it may edit the layout
    (``GET /api/projects/<id>/dashboard/can-edit``). The owner gets Edit layout
    and Save layout as on a page that fetches. A viewer signed in on another
    account gets the read-only page, its data from the page, having asked that
    one question and nothing else.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_hosted_owner")
    project_id = session["project"]["id"]
    before = _project(current_server, session["token"], project_id)
    page.goto("about:blank")
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    # The owner, signed in on this browser.
    page.goto(f"{hosted}/dashboard/{project_id}", wait_until="domcontentloaded")
    assert page.locator("script#curio-dashboard-payload").count() == 1, (
        "the page server served the dashboard without its data"
    )
    edit = page.get_by_test_id("edit-layout-btn")
    try:
        edit.wait_for(state="visible", timeout=45000)
    except PlaywrightTimeoutError:
        pytest.fail(
            "the owner, signed in on this browser, got the page served with its data "
            "read-only: it offers no Edit layout"
        )
    _chart_drew(page)
    edit.click()
    handle = page.locator(
        f'.react-flow__node[data-id="{CHART}"] .curio-dashboard-tile-handle'
    ).first
    box = handle.bounding_box()
    assert box, "the tile's title band has no box to grab"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 140, y + 70, steps=10)
    page.mouse.up()
    page.get_by_test_id("save-layout-btn").click()
    page.get_by_test_id("save-layout-btn").wait_for(state="detached", timeout=20000)

    after = _project(current_server, session["token"], project_id)
    chart_before = _node_in_spec(before, CHART)
    chart_after = _node_in_spec(after, CHART)
    assert (chart_after.get("dashboardX"), chart_after.get("dashboardY")) != (
        chart_before.get("dashboardX"), chart_before.get("dashboardY"),
    ), "the owner's new layout was not saved"

    # A viewer signed in on another account, in a browser of its own.
    viewer_ctx = browser.new_context()
    try:
        viewer = viewer_ctx.new_page()
        stub_db_login(
            viewer,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            username=f"dash_viewer_{uuid.uuid4().hex[:8]}",
            name="Someone Else",
        )
        checked: list[str] = []
        asked: list[str] = []

        def only_the_check(route, request):
            if urlsplit(request.url).path.endswith(EDIT_CHECK_PATH):
                checked.append(request.url)
                route.continue_()
                return
            asked.append(f"{request.method} {request.url}")
            route.abort()

        for pattern in DATA_ROUTES:
            viewer.route(pattern, only_the_check)

        viewer.goto(f"{hosted}/dashboard/{project_id}", wait_until="domcontentloaded")
        viewer.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
        assert_vega_canvas_rendered(viewer, CHART, timeout=90000)
        assert viewer.get_by_test_id("edit-layout-btn").count() == 0
        # Nor is a visitor told the page is read-only: nothing lies over the tiles.
        assert viewer.get_by_test_id("shared-view-banner").count() == 0
        # The session asked once, was told no, and asked nothing else.
        assert len(checked) == 1, f"the viewer's page asked whether it may edit {len(checked)} times"
        assert asked == [], "the viewer's page asked the server for more: " + ", ".join(asked)
    finally:
        viewer_ctx.close()


def test_the_editor_restores_saved_outputs_on_reload(
    app_frontend: "FrontendPage", current_server, page,
):
    """The canvas gets the same restore: a reloaded chain shows its data."""
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_editor")
    project_id = session["project"]["id"]

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)

    # Without a Play: the producer's saved output reached the pool, the pool
    # rendered it, and the chart drew it.
    _chart_drew(page)
    pool_table = node_locator(page, POOL).locator("table").first
    pool_table.wait_for(state="visible", timeout=45000)
    rows = pool_table.locator("tbody tr")
    assert rows.count() == 3, (
        f"the Data Pool shows {rows.count()} rows of the producer's 3, so the "
        f"saved output did not reach it"
    )


# ---------------------------------------------------------------------------
# Someone else
# ---------------------------------------------------------------------------

def test_a_visitor_with_no_account_sees_the_dashboard_read_only(
    app_frontend: "FrontendPage", current_server, browser, page,
):
    """A link opened in a browser with no cookie at all.

    The visitor is signed in as the shared guest with a NEW session, so the
    owner's artifact rows are not theirs to read: every byte they see came
    from the saved outputs' own files, read in place on the dataflow's route.
    """
    require_project_page()
    # The owner half of this needs a real account: `_pinned_and_saved` runs and
    # saves a dataflow, and a stack booted without user auth opens every project
    # read-only as the shared guest.
    require_user_auth()
    if not allow_guest_login_env():
        pytest.skip("A visitor with no account needs guest sign-in (ALLOW_GUEST_LOGIN)")
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_share")
    project_id = session["project"]["id"]

    visitor_ctx = browser.new_context()
    try:
        visitor = visitor_ctx.new_page()
        visitor.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
        visitor.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
        assert_vega_canvas_rendered(visitor, CHART, timeout=90000)
        assert visitor.get_by_test_id("edit-layout-btn").count() == 0
        # A visitor is not told the page is shared or read-only: nothing lies over the tiles.
        assert visitor.get_by_test_id("shared-view-banner").count() == 0
    finally:
        visitor_ctx.close()


def test_another_user_reloading_the_dataflow_sees_its_data(
    app_frontend: "FrontendPage", current_server, browser, page,
):
    """The editor restore works across sessions too, not only for the owner."""
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_cross")
    project_id = session["project"]["id"]

    other_ctx = browser.new_context()
    try:
        other = other_ctx.new_page()
        stub_db_login(
            other,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            username=f"dash_other_{uuid.uuid4().hex[:8]}",
            name="Someone Else",
        )
        other.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
        other.get_by_test_id("shared-view-banner").wait_for(timeout=45000)
        assert_vega_canvas_rendered(other, CHART, timeout=90000)
    finally:
        other_ctx.close()


# ---------------------------------------------------------------------------
# A visitor's own values (#1117)
# ---------------------------------------------------------------------------

SHAPER = "dash-shaper"
VIEWER_RUN_STEM = "dashboard-viewer-run"

#: How many rows the producer makes, by a Rows choice of its own: the three
#: the owner saved, or five.
ROWS_PRODUCER_CODE = (
    "import pandas as pd\n\n"
    "rows = [!! rows !!]\n"
    "counts = {'three': [3, 7, 5], 'five': [3, 7, 5, 9, 4]}[rows]\n"
    "return pd.DataFrame({'category': list('abcde')[:len(counts)], 'count': counts})\n"
)

#: The producer's rows scaled by a Scale choice of its own: a second Python
#: step, which reads what the first one made.
SHAPER_CODE = (
    "scale = [!! scale !!]\n"
    "factor = {'one': 1, 'ten': 10}[scale]\n"
    "return input_0.assign(count=input_0['count'] * factor)\n"
)

#: What a dashboard asks of the backend for a viewer's run: the run, its
#: stream, what the page made of a step the run left to it, and what it made.
_VIEWER_ROUTE_RE = re.compile(
    r"^(POST /api/projects/[^/?]+/dashboard/runs"
    r"|GET /api/projects/[^/?]+/dashboard/runs/[^/?]+/stream"
    r"|POST /api/projects/[^/?]+/dashboard/runs/[^/?]+/steps/[^/?]+"
    r"|GET /api/projects/[^/?]+/dashboard/outputs/(get|get-preview|raster)\?.*)$"
)

#: Where a page reports a browser error to the monitor (clientErrorReporter.ts).
CLIENT_ERROR_PATH = "/api/monitor/errors/client"


def _client_error_report(body: str | None) -> str:
    """One browser error report as the page sent it: its message, the first
    lines of its stack and the page it came from."""
    try:
        report = json.loads(body or "")
    except ValueError:
        return f"not JSON: {str(body)[:600]}"
    if not isinstance(report, dict):
        return str(report)[:600]
    stack = " / ".join(str(report.get("stack") or "").strip().splitlines()[:3])
    return f"{report.get('message')!r} at {stack or 'no stack'} on {report.get('url')}"[:1200]

#: Each node's run status (``data-curio-node-status``), how often a run
#: triggered it and whether an input reached it, and for a node in error what
#: it says (its text, the code editors left out), then every toast on the page.
_NODES_STANDING_JS = """() => {
    const rows = [];
    const flow = window.__curio_reactFlow;
    const says = (element) => {
        const copy = element.cloneNode(true);
        copy.querySelectorAll('.monaco-editor, script, style').forEach((part) => part.remove());
        return copy.textContent.replace(/\\s+/g, ' ').trim().slice(0, 400);
    };
    for (const node of flow ? flow.getNodes() : []) {
        const element = document.querySelector('.react-flow__node[data-id="' + node.id + '"]');
        const marked = element && element.querySelector('[data-curio-node-status]');
        const status = marked ? marked.getAttribute('data-curio-node-status') : 'no status';
        rows.push(node.id + ': ' + status + ', triggered ' + (node.data?.triggerExec ?? 0)
            + ', input ' + (node.data?.input ? 'yes' : 'no')
            + (status === 'error' && element ? ', says: ' + says(element) : ''));
    }
    for (const toast of document.querySelectorAll('.toast')) {
        rows.push('toast: ' + toast.textContent.trim().slice(0, 240));
    }
    return rows;
}"""

_CHART_PIXELS_JS = """(id) => {
    const canvas = document.querySelector('#vega' + id + ' canvas');
    return canvas ? canvas.toDataURL('image/png') : null;
}"""


def _with_choice(node: dict, name: str, label: str, choices: list) -> dict:
    """*node* pinned with one choice of its own, shown as radio buttons: its
    tile's control."""
    node = {**node, "dashboardPinned": True}
    node["metadata"]["widgets"] = [{
        "name": name, "type": "choice", "label": label, "default": choices[0],
        "options": {"choices": choices, "display": "radio"},
    }]
    return node


def _controls_spec() -> dict:
    """Two Python steps, the second reading what the first made, then a Data
    Pool and the chart; each step pinned with a choice of its own, which its
    code reads. The pool is pinned too: its table shows the rows a value made."""
    def edge(source: str, target: str) -> dict:
        return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}

    return {
        "dataflow": {
            "name": "Dashboard controls e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _with_choice(_node(PRODUCER, "curio.builtin/data-loading", 0, ROWS_PRODUCER_CODE),
                             "rows", "Rows", ["three", "five"]),
                _with_choice(_node(SHAPER, "curio.builtin/computation-analysis", 700, SHAPER_CODE),
                             "scale", "Scale", ["one", "ten"]),
                {**_node(POOL, "curio.builtin/data-pool", 1400), "dashboardPinned": True},
                _node(CHART, "curio.builtin/vis-vega", 2100, CHART_SPEC),
            ],
            "edges": [edge(PRODUCER, SHAPER), edge(SHAPER, POOL), edge(POOL, CHART)],
        },
    }


def _runs_started(asked: list[str]) -> list[str]:
    return [line for line in asked if line.startswith("POST ") and line.endswith("/dashboard/runs")]


def _files_read(asked: list[str]) -> set[str]:
    """The artifacts the page read on the dashboard's output routes."""
    names: set[str] = set()
    for line in asked:
        target = urlsplit(line.partition(" ")[2])
        if "/dashboard/outputs/" in target.path:
            names.update(parse_qs(target.query).get("fileName", []))
    return names


def _not_a_viewer_route(asked: list[str]) -> list[str]:
    return [line for line in asked if not _VIEWER_ROUTE_RE.match(line)]


class _Visitor:
    """A browser of its own, with no session, on a dashboard as the hosted
    stacks serve it: the page server, with the dashboard's data inside it.

    What the page asks of the backend goes through :meth:`_to_backend`, which
    notes what the page asked, what it was answered and what it logged, for a
    failure to report. The harness points every page at this worker's backend
    (``window.__CURIO_BACKEND_URL__``, conftest.py), so a request reaches it as
    the page addressed it. A page that asks ``/api`` on its own host, as a
    hosted stack's pages do, is passed on the way that stack's proxy passes it,
    with ``/api`` taken off. A run's stream reaches the page whole, once the
    run is over, and is kept whole in :attr:`streams`. A CORS preflight is
    passed on and not counted as asked. What the page reports to the monitor
    as a browser error, and each error it leaves uncaught, are kept whole for
    a failure to name, where its last messages may start after them.
    """

    def __init__(self, browser, current_server: str):
        self.backend = current_server.rstrip("/")
        backend = urlsplit(self.backend)
        self.backend_origin = f"{backend.scheme}://{backend.netloc}"
        self.ctx = browser.new_context()
        self.page = self.ctx.new_page()
        self.asked: list[str] = []
        self.answered: list[str] = []
        #: Each run's stream, whole, in the order the runs ended.
        self.streams: list[str] = []
        #: What the page sent of each step a run left to it, and its size.
        self.sent: list[str] = []
        self.console: list[str] = []
        #: Each browser error the page reported to the monitor, from its report.
        self.reported: list[str] = []
        #: Each error the page left uncaught.
        self.page_errors: list[str] = []
        self.page.on("console", lambda message: self.console.append(f"[{message.type}] {message.text}"))
        self.page.on("pageerror", self._uncaught)
        self.page.route(f"{self.backend_origin}/**", self._to_backend)
        self.page.route("**/api/api/**", self._to_backend)

    def _uncaught(self, error) -> None:
        self.page_errors.append(str(error))
        self.console.append(f"[pageerror] {error}")

    def _to_backend(self, route, request) -> None:
        parts = urlsplit(request.url)
        query = f"?{parts.query}" if parts.query else ""
        on_backend = f"{parts.scheme}://{parts.netloc}" == self.backend_origin
        path = parts.path if on_backend else parts.path[len("/api"):]
        line = f"{request.method} {path}{query}"
        if request.method != "OPTIONS":
            self.asked.append(line)
        if request.method == "POST" and path == CLIENT_ERROR_PATH:
            self.reported.append(_client_error_report(request.post_data))
        if request.method == "POST" and "/steps/" in path:
            self.sent.append(f"{line}: {len(request.post_data_buffer or b'')} bytes")
        target = request.url if on_backend else f"{self.backend}{path}{query}"
        try:
            response = route.fetch(url=target, timeout=180000)
        except Exception as exc:  # noqa: BLE001 - the page gets an answer, and the failure says why
            self.answered.append(f"{line} -> the backend did not answer: {exc}")
            route.fulfill(status=502, body=str(exc))
            return
        kind = response.headers.get("content-type", "")
        said = response.text()[:3000] if ("json" in kind or "event-stream" in kind) else f"{len(response.body())} bytes"
        if "event-stream" in kind:
            self.streams.append(response.text())
        self.answered.append(f"{line} -> {response.status} {said}")
        route.fulfill(response=response)

    def opens(self, hosted: str, project_id: str) -> None:
        self.page.goto(f"{hosted}/dashboard/{project_id}", wait_until="domcontentloaded")
        assert self.page.locator("script#curio-dashboard-payload").count() == 1, (
            "the page server served the dashboard without its data"
        )
        self.page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)

    def story(self) -> str:
        """What the page asked and was answered, where each node stands and
        what the page says, every browser error it reported or left uncaught,
        and what it logged last."""
        try:
            standing = self.page.evaluate(_NODES_STANDING_JS)
        except Exception as exc:  # noqa: BLE001 - the story is told with what can be read
            standing = [f"could not be read: {exc}"]
        return (
            "\nAsked and answered:\n  " + "\n  ".join(self.answered or ["nothing"])
            + "\nWhat the page sent of the steps left to it:\n  " + "\n  ".join(self.sent or ["nothing"])
            + "\nThe page's nodes and notices:\n  " + "\n  ".join(standing or ["none"])
            + "\nWhat the page reported to the monitor as browser errors:\n  "
            + "\n  ".join(self.reported or ["nothing"])
            + "\nThe page's uncaught errors:\n  " + "\n  ".join(self.page_errors or ["none"])
            + "\nThe page's last messages:\n  " + "\n  ".join(self.console[-60:] or ["none"])
        )

    def waits_for(self, what: str, check) -> None:
        """*check*, which waits for *what*; a failure tells the visitor's story."""
        try:
            check()
        except (AssertionError, PlaywrightTimeoutError) as exc:
            raise AssertionError(f"{what}: {exc}{self.story()}") from None

    def runs_ended(self) -> int:
        """How many viewer's runs started here are over: each one's stream
        answered, or its start answered with no run to follow."""
        ended = 0
        for line in self.answered:
            asked, _, answer = line.partition(" -> ")
            method, _, path = asked.partition(" ")
            if method == "GET" and urlsplit(path).path.endswith("/stream"):
                ended += 1
            elif method == "POST" and path.endswith("/dashboard/runs"):
                # A run to follow answers 202 with its id; one that needs no
                # run answers 200 with none, and a refusal names none either.
                status, _, body = answer.partition(" ")
                try:
                    run_id = json.loads(body).get("runId") if status in ("200", "202") else None
                except ValueError:
                    run_id = None
                if not run_id:
                    ended += 1
        return ended

    def waits_for_runs(self, count: int, *, timeout_ms: int = 90000) -> None:
        """Until *count* viewer's runs started here are over, so a count of
        the runs started is not taken while one is still to come."""
        waited = 0
        while self.runs_ended() < count:
            if waited >= timeout_ms:
                raise AssertionError(f"waited {timeout_ms} ms for {count} viewer's runs to end{self.story()}")
            self.page.wait_for_timeout(250)
            waited += 250

    def close(self) -> None:
        self.ctx.close()


def _step_outputs(visitor: "_Visitor") -> list[dict[str, str]]:
    """Each run the visitor's page followed, in order: the output of every
    step it finished, by node id. A step whose output was kept from an earlier
    run hands on that run's output again."""
    runs = []
    for stream in visitor.streams:
        outputs = {}
        for block in stream.strip().split("\n\n"):
            kind = block.split("\n", 1)[0].removeprefix("event: ")
            if kind != "step_finished" or "data: " not in block:
                continue
            payload = json.loads(block.split("data: ", 1)[1])
            if payload.get("status") == "ok":
                outputs[payload["nodeId"]] = (payload.get("output") or {}).get("path")
        runs.append(outputs)
    return runs


def _pool_shows(page, rows: int, *, timeout: float = 90000) -> None:
    """The pinned Data Pool's table holds *rows* rows."""
    table = node_locator(page, POOL).locator("table").first
    expect(table.locator("tbody tr")).to_have_count(rows, timeout=timeout)


def _first_row_has_cell(page, text: str, *, timeout: float = 90000) -> None:
    """The pinned Data Pool's first row has a cell that reads *text*, whole."""
    row = node_locator(page, POOL).locator("table").first.locator("tbody tr").first
    expect(row.locator("td").filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$"))).to_have_count(
        1, timeout=timeout,
    )


def _saved_tiles_drew(page) -> None:
    """The chart and the pool show the three rows the owner saved."""
    _chart_drew(page)
    _pool_shows(page, 3)


def _pick(page, node_id: str, choice: str):
    """The radio button of *choice* on the tile of the pinned node *node_id*."""
    return node_locator(page, node_id).get_by_role("radio", name=choice)


def _chart_redrew(page, saved_pixels: str) -> None:
    """The chart drew again, and not what it drew before."""
    page.wait_for_function(
        "([id, saved]) => {"
        " const canvas = document.querySelector('#vega' + id + ' canvas');"
        " return !!canvas && canvas.toDataURL('image/png') !== saved; }",
        arg=[CHART, saved_pixels],
        timeout=90000,
        polling=500,
    )
    _chart_drew(page)


def _catalog_ids(current_server: str, token: str, project_id: str) -> list[str]:
    catalog = api_json(f"{current_server}/api/datasets/catalog?dataflowId={project_id}", token)
    items = catalog.get("items", catalog) if isinstance(catalog, dict) else catalog
    return sorted(str(item.get("id")) for item in items)


def test_a_visitor_changes_a_pinned_control_and_the_next_one_gets_the_kept_output(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A visitor with no account picks another value and the tiles redraw.

    The page is served as the hosted stacks serve it, with its data, to
    browsers with no session. On open the tiles show the saved outputs and
    nothing runs. Picking another Rows runs both Python steps on the server,
    the second reading what the first made, through the dashboard's own
    routes. The next visitor who picks the same value gets the outputs kept
    from that run, so nothing runs again; another Scale then runs only the
    second step, on the first step's kept output. The owner's dataflow, its
    recorded outputs and the Data Catalog stay as they were.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(
        page, app_frontend, current_server, prefix="dash_ctrl", spec=_controls_spec(),
    )
    project_id = session["project"]["id"]
    # Off the canvas first: it can still save on its way out.
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    catalog_before = _catalog_ids(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    first = _Visitor(browser, current_server)
    try:
        first.opens(hosted, project_id)
        first.waits_for("the saved tiles", lambda: _saved_tiles_drew(first.page))
        five = _pick(first.page, PRODUCER, "five")
        expect(five).to_be_enabled(timeout=10000)
        # The visitor changes the controls with no notice that the changes are not saved.
        expect(first.page.get_by_test_id("shared-view-banner")).to_have_count(0)
        assert _runs_started(first.asked) == [], (
            "opening the dashboard started a run, though every tile has its saved output" + first.story()
        )
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, VIEWER_RUN_STEM, test_name="opened", sweep_toasts=True)
        saved_pixels = first.page.evaluate(_CHART_PIXELS_JS, CHART)

        five.check()
        first.waits_for("the pool's five rows", lambda: _pool_shows(first.page, 5))
        first.waits_for("the chart of five rows", lambda: _chart_redrew(first.page, saved_pixels))
        # Off the control the click left it on.
        park_pointer(first.page)
        save_workflow_test_screenshot(first.page, VIEWER_RUN_STEM, test_name="changed", sweep_toasts=True)

        first.waits_for_runs(1)
        started = _runs_started(first.asked)
        assert len(started) == 1, f"one change started {len(started)} runs" + first.story()
        made = _files_read(first.asked)
        assert made, "the tiles show the visitor's value without reading what its run made" + first.story()
        assert _not_a_viewer_route(first.asked) == [], (
            "the dashboard asked the server for more than a viewer's run" + first.story()
        )
    finally:
        first.close()

    second = _Visitor(browser, current_server)
    try:
        second.opens(hosted, project_id)
        second.waits_for("the saved tiles", lambda: _saved_tiles_drew(second.page))
        saved_pixels = second.page.evaluate(_CHART_PIXELS_JS, CHART)
        _pick(second.page, PRODUCER, "five").check()
        second.waits_for("the pool's five rows", lambda: _pool_shows(second.page, 5))
        second.waits_for("the chart of five rows", lambda: _chart_redrew(second.page, saved_pixels))
        second.waits_for_runs(1)
        # A run of its own would have made artifacts of its own.
        assert _files_read(second.asked) == made, (
            f"the second visitor read {sorted(_files_read(second.asked))!r}, not the outputs "
            f"kept from the first visitor's run of the same value {sorted(made)!r}" + second.story()
        )

        # Only the second step reads Scale: the first step's output is the kept one.
        _pick(second.page, SHAPER, "ten").check()
        second.waits_for("the rows scaled ten times", lambda: _first_row_has_cell(second.page, "30"))
        second.waits_for_runs(2)
        assert len(_runs_started(second.asked)) == 2, "two changes, two runs" + second.story()
        assert _files_read(second.asked) - made, (
            "the tiles show the new Scale without reading what its run made" + second.story()
        )
        assert _not_a_viewer_route(second.asked) == [], (
            "the dashboard asked the server for more than a viewer's run" + second.story()
        )
    finally:
        second.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's run changed the owner's dataflow"
    assert after["outputs"] == before["outputs"], "a visitor's run changed the dataflow's recorded outputs"
    assert _catalog_ids(current_server, session["token"], project_id) == catalog_before, (
        "a visitor's run added to the Data Catalog"
    )


def _chart_drew_from_nothing(page) -> None:
    """The chart, which had nothing to draw, drew."""
    node_locator(page, CHART).locator(f"#vega{CHART} canvas").first.wait_for(
        state="visible", timeout=180000,
    )
    _chart_drew(page)


def test_a_tile_with_no_saved_output_runs_the_nodes_before_it_when_the_page_opens(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A tile whose nodes never ran gets its data from a run on open, and the
    next visitor gets what that run kept.

    The chart is pinned and the dataflow saved without a run, so nothing is
    saved for it. A visitor with no session opens the dashboard as the hosted
    stacks serve it: the page starts one viewer's run with the saved values,
    and the chart draws what it made. A second visitor's page gets the same
    outputs, kept for 7 days, with nothing run again (owner, 10-25). The
    dataflow stays as it was.
    """
    require_project_page()
    require_user_auth()
    session = _enter(page, app_frontend, current_server, prefix="dash_unrun")
    project_id = session["project"]["id"]
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    _pin(page, CHART)
    _save(page)
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    assert before["outputs"] == [], f"the dataflow saved outputs it never ran: {before['outputs']!r}"
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for("the chart from the run on open", lambda: _chart_drew_from_nothing(visitor.page))
        visitor.waits_for_runs(1)
        started = _runs_started(visitor.asked)
        assert len(started) == 1, f"opening the dashboard started {len(started)} runs" + visitor.story()
        assert _files_read(visitor.asked), (
            "the chart drew without reading what the run made" + visitor.story()
        )
        assert _not_a_viewer_route(visitor.asked) == [], (
            "the dashboard asked the server for more than a viewer's run" + visitor.story()
        )
        made = _step_outputs(visitor)
        assert made and made[0], f"the run on open handed on no output: {made!r}" + visitor.story()
    finally:
        visitor.close()

    # The next visitor: the same outputs, kept, with nothing run again. A step
    # run again would make an artifact of its own.
    second = _Visitor(browser, current_server)
    try:
        second.opens(hosted, project_id)
        second.waits_for("the chart from what the first visit kept", lambda: _chart_drew_from_nothing(second.page))
        second.waits_for_runs(1)
        assert len(_runs_started(second.asked)) == 1, "the second visit started other than one run" + second.story()
        again = _step_outputs(second)
        assert again[:1] == made[:1], (
            f"the second visit's run handed on {again!r}, not what the first one kept {made!r}" + second.story()
        )
    finally:
        second.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "the run on open changed the owner's dataflow"
    assert after["outputs"] == [], "the run on open saved outputs to the dataflow"


#: The request whose route call the probe visitor holds: a JSON answer, which
#: :meth:`_Visitor._to_backend` reads with ``response.text()``, as it was
#: reading one when its visitor was closed in run 40721143993.
_HELD_PROBE = "/api/config/public?route-call-held=1"

#: How long, at most, the probe's route call waits between the backend's
#: answer and its reading for the visitor's page to close.
_HOLD_MS = 5000


class _HeldRoute:
    """The probe's route, as :meth:`_Visitor._to_backend` uses it: its
    ``fetch`` hands back the backend's answer only once the visitor's page
    has closed or :data:`_HOLD_MS` have passed, so that the visitor can be
    closed in between."""

    def __init__(self, visitor: "_ProbeVisitor", route):
        self._visitor = visitor
        self._route = route

    def fetch(self, *args, **kwargs):
        answer = self._route.fetch(*args, **kwargs)
        visitor = self._visitor
        visitor.holding = True
        try:
            visitor.page.wait_for_event("close", timeout=_HOLD_MS)
            page_closed = True
        except PlaywrightTimeoutError:
            page_closed = False
        visitor.held.append({"after the close began": visitor.closing, "the page closed": page_closed})
        return answer

    def fulfill(self, *args, **kwargs) -> None:
        self._route.fulfill(*args, **kwargs)


class _ProbeVisitor(_Visitor):
    """A visitor whose route call for :data:`_HELD_PROBE` holds between the
    backend's answer and its reading (:class:`_HeldRoute`). Every request
    goes through :meth:`_Visitor._to_backend` as it is."""

    def __init__(self, browser, current_server: str):
        #: Whether the probe's route call has the backend's answer and holds.
        self.holding = False
        #: Whether the test has begun to close the visitor.
        self.closing = False
        #: How each hold ended.
        self.held: list[dict[str, bool]] = []
        super().__init__(browser, current_server)

    def _to_backend(self, route, request) -> None:
        if request.url.endswith(_HELD_PROBE):
            route = _HeldRoute(self, route)
        super()._to_backend(route, request)


def test_closing_a_visitor_waits_for_a_route_call_still_reading_its_answer(current_server, browser):
    """A visitor's close lets the calls of its routes that are still running
    end first.

    In run 40721143993 a visitor's page asked for a JSON answer as its test
    closed it. :meth:`_Visitor._to_backend` had the backend's answer, the
    context closed, which disposes of every answer its ``route.fetch()``
    calls got, and reading the answer raised "Response has been disposed".
    Playwright's sync API raises a route call's error at the worker's next
    call, so the next visitor's ``browser.new_context()`` failed, after every
    check of the first visitor had passed. Here the probe's route call holds
    at that moment, between the answer and its reading, while its visitor is
    closed. The next visitor opens and loads a page, and the held call read
    its answer whole, after the close began and with the page still open.
    """
    visitor = _ProbeVisitor(browser, current_server)
    try:
        visitor.page.goto(f"{current_server}/live")
        visitor.page.evaluate("probe => { fetch(probe); }", _HELD_PROBE)
        waited = 0
        while not visitor.holding:
            assert waited < 30000, f"the probe never reached the visitor's route{visitor.story()}"
            visitor.page.wait_for_timeout(50)
            waited += 50
        visitor.closing = True
    finally:
        visitor.close()

    following = _Visitor(browser, current_server)
    try:
        answer = following.page.goto(f"{current_server}/live")
        assert answer is not None and answer.ok, f"the next visitor's page did not load{following.story()}"
        expect(following.page.locator("body")).to_have_text("Backend is live.")
    finally:
        following.close()

    assert visitor.held == [{"after the close began": True, "the page closed": False}], (
        f"the probe's route call held {visitor.held!r}: it should have read its answer after "
        "the close began, with the page still open"
    )
    probe = f"GET {_HELD_PROBE} -> 200 "
    assert any(line.startswith(probe) for line in visitor.answered), (
        f"the probe's route call did not read its answer whole: {visitor.answered!r}"
    )


#: A producer whose run fails on the server.
FAILING_PRODUCER_CODE = "raise ValueError('The table this step reads is gone.')\n"


def test_tiles_below_a_step_that_fails_name_it_with_no_node_to_open(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A viewer's run that fails at a server step leaves the tiles below it
    saying which step failed (owner, 10-25).

    The producer raises; the pool and the chart below it are pinned and the
    dataflow saved without a run. A visitor's page runs them on open, and the
    run ends at the producer. Each tile says "No results" and names the step:
    not "Open it to see the error", as a visitor opens no node, and not
    "Computing...", as the run is over.
    """
    require_project_page()
    require_user_auth()
    spec = _spec()
    spec["dataflow"]["nodes"][0]["content"] = FAILING_PRODUCER_CODE
    session = _enter(page, app_frontend, current_server, prefix="dash_failing", spec=spec)
    project_id = session["project"]["id"]
    node_locator(page, CHART).wait_for(state="visible", timeout=45000)
    _pin(page, POOL)
    _pin(page, CHART)
    _save(page)
    page.goto("about:blank")
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for_runs(1)
        for tile in (POOL, CHART):
            stopped = node_locator(visitor.page, tile).locator('[data-curio-node-empty="upstream-stopped"]')
            visitor.waits_for(
                f"{tile} naming the step that failed",
                lambda stopped=stopped: expect(stopped).to_contain_text(
                    re.compile(r'No results\s*"[^"]+" failed\.'), timeout=60000,
                ),
            )
            expect(node_locator(visitor.page, tile)).not_to_contain_text("Open it")
        assert len(_runs_started(visitor.asked)) == 1, "the failed run started again" + visitor.story()
    finally:
        visitor.close()


# ---------------------------------------------------------------------------
# A pinned node's own widgets are its tile's controls (#1117)
# ---------------------------------------------------------------------------

TILE_CONTROLS_STEM = "dashboard-tile-controls"

#: The chart's bars, as opaque as its own Opacity slider says.
OWN_OPACITY_CHART_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "mark": {"type": "bar", "opacity": [!! opacity !!]},
  "encoding": {
    "x": {"field": "category", "type": "nominal"},
    "y": {"field": "count", "type": "quantitative"}
  }
}"""


def _own_rows_spec() -> dict:
    """The chart's dataflow, its producer pinned with a Rows choice of its own,
    shown as radio buttons."""
    spec = _spec()
    spec["dataflow"]["name"] = "Dashboard code node controls e2e"
    nodes = spec["dataflow"]["nodes"]
    nodes[0] = _with_choice({**nodes[0], "content": ROWS_PRODUCER_CODE}, "rows", "Rows", ["three", "five"])
    return spec


def _own_opacity_spec() -> dict:
    """The chart's dataflow, the chart with an Opacity slider of its own."""
    spec = _spec()
    spec["dataflow"]["name"] = "Dashboard chart controls e2e"
    chart = spec["dataflow"]["nodes"][2]
    chart["content"] = OWN_OPACITY_CHART_SPEC
    chart["metadata"]["widgets"] = [{
        "name": "opacity", "type": "slider", "label": "Opacity", "default": 1,
        "options": {"min": 0.1, "max": 1, "step": 0.1},
    }]
    return spec


def test_a_pick_on_a_pinned_code_nodes_tile_runs_it_and_the_chart_below_draws_again(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A pinned code node's widgets are its tile's controls, in place of its
    code.

    The producer is pinned with a Rows choice of its own, as radio buttons,
    and the chart below it is pinned. A visitor's page shows the producer's
    tile as that control, with no code. Picking five runs the producer on the
    server with it, and the chart draws five bars, laid out for the axis labels
    it draws whichever of its redraws came last. The owner's dataflow stays as
    it was.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(
        page, app_frontend, current_server, prefix="dash_own_rows", spec=_own_rows_spec(),
    )
    project_id = session["project"]["id"]
    # Off the canvas first: it can still save on its way out.
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    visitor.page.add_init_script(_KEEP_VEGA_VIEWS_JS)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for("the saved chart", lambda: _chart_drew(visitor.page))
        tile = node_locator(visitor.page, PRODUCER)
        five = _pick(visitor.page, PRODUCER, "five")
        visitor.waits_for("the producer's Rows on its tile", lambda: expect(five).to_be_enabled(timeout=10000))
        expect(tile.locator("[data-widget-controls]")).to_be_visible()
        expect(tile.locator(".monaco-editor")).to_be_hidden()
        assert _runs_started(visitor.asked) == [], (
            "opening the dashboard started a run, though every tile has its saved output" + visitor.story()
        )
        park_pointer(visitor.page)
        save_workflow_test_screenshot(
            visitor.page, TILE_CONTROLS_STEM, test_name="code_node_opened", sweep_toasts=True,
        )
        saved_pixels = visitor.page.evaluate(_CHART_PIXELS_JS, CHART)

        five.check()
        five.blur()
        visitor.waits_for("the chart of five rows", lambda: _chart_redrew(visitor.page, saved_pixels))
        visitor.waits_for_runs(1)
        assert len(_runs_started(visitor.asked)) == 1, "one pick started other than one run" + visitor.story()
        ran = _step_outputs(visitor)
        assert ran and ran[0].get(PRODUCER), f"the run did not run the producer: {ran!r}" + visitor.story()
        assert _files_read(visitor.asked), "the chart drew without reading what the run made" + visitor.story()
        park_pointer(visitor.page)
        save_workflow_test_screenshot(
            visitor.page, TILE_CONTROLS_STEM, test_name="code_node_changed", sweep_toasts=True,
        )
        _assert_chart_fits_its_labels(visitor.page, "the chart of five rows after the pick")
    finally:
        visitor.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's pick changed the owner's dataflow"


def test_a_pinned_charts_own_slider_draws_it_again_with_no_run(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A pinned chart's widgets are its tile's controls, above the chart.

    The server never runs a pinned node: moving the chart's Opacity to its
    least draws the chart again in the visitor's page, fainter, and the run
    the change asks for has nothing to run. The owner's dataflow stays as it
    was.
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(
        page, app_frontend, current_server, prefix="dash_own_slider", spec=_own_opacity_spec(),
    )
    project_id = session["project"]["id"]
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for("the saved chart", lambda: _chart_drew(visitor.page))
        opacity = node_locator(visitor.page, CHART).get_by_role("slider", name="Opacity")
        visitor.waits_for("the chart's Opacity on its tile", lambda: expect(opacity).to_be_enabled(timeout=10000))
        controls = node_locator(visitor.page, CHART).locator("[data-widget-controls]").bounding_box()
        drawn = visitor.page.locator(f"#vega{CHART} canvas").first.bounding_box()
        assert controls and drawn, "the tile has no controls or no chart to measure"
        assert controls["y"] + controls["height"] <= drawn["y"] + 1, (
            f"the controls {controls!r} are not above the chart {drawn!r}"
        )
        park_pointer(visitor.page)
        save_workflow_test_screenshot(
            visitor.page, TILE_CONTROLS_STEM, test_name="chart_opened", sweep_toasts=True,
        )
        saved_pixels = visitor.page.evaluate(_CHART_PIXELS_JS, CHART)

        opacity.press("Home")
        visitor.waits_for("the chart's fainter bars", lambda: _chart_redrew(visitor.page, saved_pixels))
        opacity.blur()
        visitor.waits_for_runs(1)
        assert len(_runs_started(visitor.asked)) == 1, "one change started other than one run" + visitor.story()
        assert _step_outputs(visitor) == [], "the server ran a node for the chart's own value" + visitor.story()
        assert _files_read(visitor.asked) == set(), (
            "the chart drew its own value from what a run made, not in the page" + visitor.story()
        )
        park_pointer(visitor.page)
        save_workflow_test_screenshot(
            visitor.page, TILE_CONTROLS_STEM, test_name="chart_changed", sweep_toasts=True,
        )
    finally:
        visitor.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's value changed the owner's dataflow"


# ---------------------------------------------------------------------------
# A chart laid out for the axis labels it draws
# ---------------------------------------------------------------------------

# Before the app's scripts: every Vega view the page builds, kept where a test
# finds it. useVega.ts sets the app's vega module on the page as
# ``window.__curio_vega`` when it loads, which this traps.
_KEEP_VEGA_VIEWS_JS = """(() => {
    window.__curioTestVegaViews = [];
    let vega;
    Object.defineProperty(window, '__curio_vega', {
        configurable: true,
        get() { return vega; },
        set(value) {
            vega = value;
            const initialize = value.View.prototype.initialize;
            value.View.prototype.initialize = function (...args) {
                window.__curioTestVegaViews.push(this);
                return initialize.apply(this, args);
            };
        },
    });
})();"""

# The chart's view as the page drew it, then after one more of Vega's own fit
# passes, which lays the plot out for the axis labels the view holds now. A
# layout that fits the labels it draws does not move. Null when the chart holds
# no view on the page.
_FIT_AGAIN_JS = """async (id) => {
    const mount = document.getElementById('vega' + id);
    const live = (window.__curioTestVegaViews || []).filter((view) => view.container() === mount
        && view._renderer && view._renderer.canvas() && view._renderer.canvas().isConnected);
    const view = live[live.length - 1];
    if (!view) return null;
    const layout = () => ({ width: view.width(), height: view.height(), origin: view.origin() });
    const drawn = layout();
    await view.resize().runAsync();
    return { views: live.length, drawn, again: layout() };
}"""


# One read of the chart's layout, as the page drew it, for a wait on a timer:
# true once it read the same *reads* times in a row.
_CHART_LAYOUT_HOLDS_JS = """([id, reads]) => {
    const mount = document.getElementById('vega' + id);
    const live = (window.__curioTestVegaViews || []).filter((view) => view.container() === mount
        && view._renderer && view._renderer.canvas() && view._renderer.canvas().isConnected);
    const view = live[live.length - 1];
    if (!view) return false;
    const layout = JSON.stringify([view.width(), view.height(), view.origin()]);
    const hold = window.__curioTestChartHold = window.__curioTestChartHold || { layout: null, reads: 0 };
    hold.reads = layout === hold.layout ? hold.reads + 1 : 1;
    hold.layout = layout;
    return hold.reads >= reads;
}"""


def _wait_for_chart_layout_to_hold(page, *, reads: int = 5, timeout: float = 30000) -> None:
    """Until the chart's layout reads the same *reads* times, 100 ms apart."""
    page.evaluate("() => { delete window.__curioTestChartHold; }")
    page.wait_for_function(_CHART_LAYOUT_HOLDS_JS, arg=[CHART, reads], polling=100, timeout=timeout)


def _assert_chart_fits_its_labels(page, when: str) -> None:
    """The chart's plot is laid out for the axis labels it draws: one more fit
    pass of Vega's leaves it where it is."""
    fit = page.evaluate(_FIT_AGAIN_JS, CHART)
    assert fit, f"{when}: the chart holds no Vega view on the page, so its layout cannot be read"
    drawn, again = fit["drawn"], fit["again"]
    assert drawn == again, (
        f"{when}: the chart is laid out for other axis labels than the ones it draws. One more "
        f"of Vega's fit passes moves its plot from x {drawn['origin'][0]}, {drawn['width']} px wide, "
        f"to x {again['origin'][0]}, {again['width']} px wide (drawn {drawn}, fitted again {again})"
    )


def test_a_tile_chart_drawn_from_saved_rows_is_laid_out_for_the_labels_it_draws(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A chart the page draws fresh fills its tile, its plot laid out for the
    axis labels it shows.

    Vega fits a chart's plot to its tile in one pass, from the axis labels it
    makes at the tile's full height, then draws the labels the plot's own,
    shorter height makes. The y axis asks for about a tick per 40 px, so for
    these five rows (up to 9) the full tile gets a tick every 0.5, "0.0" to
    "9.0", and the plot one every 1, "0" to "9": the plot kept the room of the
    wider labels, an empty band beside the narrower ones. A chart that gets
    new rows in place starts from its plot's height and fits. So after a pick
    on the producer's tile the chart ended in one layout or the other, by
    which of its two redraws came last, and the code node's changed frame read
    0.83% against its baseline about every other run.

    The producer is saved at five rows, so the visitor's page draws the chart
    fresh from them every time. A window resize fits it again from its tile
    (vega-lite's own refit), so it is laid out again after one too.
    """
    require_project_page()
    require_user_auth()
    spec = _own_rows_spec()
    spec["dataflow"]["nodes"][0]["metadata"]["widgets"][0]["default"] = "five"
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_fit", spec=spec)
    project_id = session["project"]["id"]
    page.goto("about:blank")
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    visitor = _Visitor(browser, current_server)
    visitor.page.add_init_script(_KEEP_VEGA_VIEWS_JS)
    try:
        visitor.opens(hosted, project_id)
        visitor.waits_for("the saved chart", lambda: _chart_drew(visitor.page))
        _wait_for_no_node_running(visitor.page)
        assert _runs_started(visitor.asked) == [], (
            "opening the dashboard started a run, though every tile has its saved output" + visitor.story()
        )
        _assert_chart_fits_its_labels(visitor.page, "the chart of the five saved rows")

        visitor.page.evaluate("() => window.dispatchEvent(new Event('resize'))")
        _wait_for_chart_layout_to_hold(visitor.page)
        _assert_chart_fits_its_labels(visitor.page, "the chart after a window resize")
    finally:
        visitor.close()


# ---------------------------------------------------------------------------
# A step only a browser runs (#1117)
# ---------------------------------------------------------------------------

GPU_LOAD = "dash-gpu-load"
GPU_STEP = "dash-gpu-step"
GPU_AFTER = "dash-gpu-after"

#: As many points as its own Rows choice says, each with a count.
GPU_LOAD_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n\n"
    "rows = [!! rows !!]\n"
    "counts = {'three': [3, 7, 5], 'five': [3, 7, 5, 9, 4]}[rows]\n"
    "points = [Point(-87.63 + 0.001 * i, 41.88) for i in range(len(counts))]\n"
    "return gpd.GeoDataFrame({'count': counts}, geometry=points, crs='EPSG:4326')\n"
)

#: Each point's count doubled on the GPU: a step only a browser runs.
GPU_COMPUTE_SPEC = json.dumps({"compute": [{
    "dataRef": "input_0",
    "attributes": {"v": "properties.count"},
    "outputColumnName": "doubled",
    "wglsFunction": ["return v * 2.0;"],
}]}, indent=2)

#: What the GPU made, read back in Python as the table shows it. An Autark
#: node hands its layer on as ``{dataType, data}``, the data a FeatureCollection,
#: on the canvas and on a dashboard alike.
GPU_AFTER_CODE = (
    "import geopandas as gpd\n"
    "import pandas as pd\n\n"
    "frame = gpd.GeoDataFrame.from_features(input_0['data']['features'])\n"
    "return pd.DataFrame({\n"
    "    'count': [int(v) for v in frame['count']],\n"
    "    'doubled': [int(round(float(v))) for v in frame['doubled']],\n"
    "})\n"
)


def _gpu_spec() -> dict:
    """Python, then an Autark compute only a browser runs, then Python, then
    the table, a Data Pool the test pins. The first step is pinned with a Rows
    choice of its own, so another Rows runs all three."""
    def edge(source: str, target: str) -> dict:
        return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}

    return {
        "dataflow": {
            "name": "Dashboard browser step e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _with_choice(_node(GPU_LOAD, "curio.builtin/data-loading", 0, GPU_LOAD_CODE),
                             "rows", "Rows", ["three", "five"]),
                _node(GPU_STEP, "curio.builtin/autk-grammar", 700, GPU_COMPUTE_SPEC),
                _node(GPU_AFTER, "curio.builtin/computation-analysis", 1400, GPU_AFTER_CODE),
                _node(POOL, "curio.builtin/data-pool", 2100),
            ],
            "edges": [edge(GPU_LOAD, GPU_STEP), edge(GPU_STEP, GPU_AFTER), edge(GPU_AFTER, POOL)],
        },
    }


def _a_cell_reads(page, text: str, *, timeout: float = 120000) -> None:
    """A cell of the Data Pool's table reads *text*, whole."""
    table = node_locator(page, POOL).locator("table").first
    cell = table.locator("td").filter(has_text=re.compile(rf"^\s*{re.escape(text)}\s*$"))
    expect(cell.first).to_be_visible(timeout=timeout)


def _five_doubled_rows(page, *, timeout: float = 120000) -> None:
    """The table holds the five rows Rows "five" makes, each count doubled on
    the GPU: 9 doubled is 18, a cell only those five rows have."""
    _pool_shows(page, 5, timeout=timeout)
    _a_cell_reads(page, "18", timeout=timeout)


def _steps_sent(asked: list[str]) -> list[str]:
    """What the page sent of the steps a run left to it (``POST .../steps/<nodeId>``)."""
    return [line for line in asked if line.startswith("POST ") and "/steps/" in line]


def _sent_results(visitor: "_Visitor") -> set[str]:
    """The artifacts the server kept of what *visitor*'s page sent, from its answers."""
    names: set[str] = set()
    for line in visitor.answered:
        asked, _, answer = line.partition(" -> ")
        status, _, body = answer.partition(" ")
        if not (asked.startswith("POST ") and "/steps/" in asked) or status != "200":
            continue
        kept = json.loads(body)
        names.add(kept["output"]["path"])
        names.update(kept.get("artifactIds") or [])
    return names


def test_a_step_only_a_browser_runs_is_run_by_each_visitors_page_for_it_alone(
    app_frontend: "FrontendPage", current_server, page, browser, monkeypatch,
):
    """A GPU step in a viewer's run is the visitor's page's to run.

    Picking another Rows runs the first Python step on the server. The run
    leaves the Autark compute to the page, which doubles the counts on its own
    GPU and sends what it made, and its next start runs the Python after it on
    that. The next visitor who picks the same Rows gets the first step kept,
    but runs the GPU step in its own page: what the first page sent, and what
    was made from it, are that page's alone. The owner's dataflow, its
    recorded outputs and the Data Catalog stay as they were.
    """
    require_project_page()
    require_user_auth()
    from .utils import run_all_and_wait

    session = _enter(page, app_frontend, current_server, prefix="dash_gpu", spec=_gpu_spec())
    require_webgpu(page)
    run_all_and_wait(page, timeout_ms=300000)
    # The canvas ran the chain: its table shows the three counts doubled on
    # the GPU (7 doubled is 14).
    _pool_shows(page, 3, timeout=120000)
    _a_cell_reads(page, "14")
    # Pinning is what saves the output the table reads.
    _pin(page, POOL)
    _save(page)
    project_id = session["project"]["id"]
    # Off the canvas first: it can still save on its way out.
    page.goto("about:blank")
    before = _project(current_server, session["token"], project_id)
    recorded = [o["node_id"] for o in before["outputs"]]
    assert GPU_AFTER in recorded, f"the save recorded {recorded!r}, not the output the pinned table reads"
    catalog_before = _catalog_ids(current_server, session["token"], project_id)
    hosted = _serve_hosted(app_frontend, current_server, monkeypatch)

    first = _Visitor(browser, current_server)
    try:
        first.opens(hosted, project_id)
        first.waits_for("the saved table", lambda: _pool_shows(first.page, 3))
        assert _runs_started(first.asked) == [], (
            "opening the dashboard started a run, though its tile has its saved output" + first.story()
        )
        _pick(first.page, GPU_LOAD, "five").check()
        first.waits_for("the five rows doubled on this page's GPU", lambda: _five_doubled_rows(first.page))
        first.waits_for_runs(2)
        started = _runs_started(first.asked)
        assert len(started) == 2, (
            f"the change started {len(started)} runs, not the run and the start going on "
            f"from the step it left to the page" + first.story()
        )
        assert len(_steps_sent(first.asked)) == 1, "the page did not send what it made of the GPU step" + first.story()
        first_sent = _sent_results(first)
        assert first_sent, "the server kept nothing of what the page sent" + first.story()
        first_read = _files_read(first.asked)
        assert _not_a_viewer_route(first.asked) == [], (
            "the dashboard asked the server for more than a viewer's run" + first.story()
        )
    finally:
        first.close()

    second = _Visitor(browser, current_server)
    try:
        second.opens(hosted, project_id)
        second.waits_for("the saved table", lambda: _pool_shows(second.page, 3))
        _pick(second.page, GPU_LOAD, "five").check()
        second.waits_for("the five rows doubled on this page's GPU", lambda: _five_doubled_rows(second.page))
        second.waits_for_runs(2)
        # Its own page ran the GPU step: the first page's result was not handed to it.
        assert len(_steps_sent(second.asked)) == 1, "the second page did not run the GPU step itself" + second.story()
        second_read = _files_read(second.asked)
        assert not second_read & first_sent, (
            f"the second page read {sorted(second_read & first_sent)!r}, what the first page sent" + second.story()
        )
        assert second_read - first_read, (
            "the second page's table shows nothing made from its own GPU step" + second.story()
        )
        assert _not_a_viewer_route(second.asked) == [], (
            "the dashboard asked the server for more than a viewer's run" + second.story()
        )
    finally:
        second.close()

    after = _project(current_server, session["token"], project_id)
    assert after["spec"] == before["spec"], "a visitor's run changed the owner's dataflow"
    assert after["outputs"] == before["outputs"], "a visitor's run changed the dataflow's recorded outputs"
    assert _catalog_ids(current_server, session["token"], project_id) == catalog_before, (
        "a visitor's run added to the Data Catalog"
    )


# ---------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------

def test_a_dashboard_with_nothing_pinned_says_so(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _enter(page, app_frontend, current_server, prefix="dash_empty")
    project_id = session["project"]["id"]

    _open_dashboard(page, app_frontend.base_url, project_id)

    empty = page.get_by_test_id("dashboard-empty")
    empty.wait_for(state="visible", timeout=45000)
    expect(empty).to_contain_text("Nothing is pinned to this dashboard yet.")
    link = empty.get_by_role("link", name="Open the dataflow")
    assert link.get_attribute("href").endswith(f"/dataflow/{project_id}")


def test_share_opens_the_dashboard_in_a_new_tab_and_copies_links(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_menu")
    project_id = session["project"]["id"]
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    editor_url = page.url

    page.get_by_test_id("share-menu-btn").click(force=True)
    with page.context.expect_page() as popup_info:
        page.get_by_test_id("open-dashboard-link").click()
    dashboard = popup_info.value
    # A brand-new page reports an empty URL until it has navigated, so wait on
    # the URL rather than on a load state.
    dashboard.wait_for_url(re.compile(rf"/dashboard/{project_id}$"), timeout=30000)
    dashboard.wait_for_load_state("domcontentloaded")
    assert_vega_canvas_rendered(dashboard, CHART, timeout=90000)
    # The editor tab stayed where it was.
    assert page.url == editor_url
    assert page.locator("#tools-menu").is_visible()
    dashboard.close()

    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dashboard link", exact=True).click()
    copied = page.evaluate("() => navigator.clipboard.readText()")
    assert copied == f"{app_frontend.base_url}/dashboard/{project_id}", copied

    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_text("Copy dataflow link", exact=True).click()
    copied = page.evaluate("() => navigator.clipboard.readText()")
    assert copied == f"{app_frontend.base_url}/dataflow/{project_id}", copied


def test_share_on_an_unsaved_dataflow_says_to_save_first(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Unsaved",
        username=f"dash_new_{uuid.uuid4().hex[:8]}",
    )
    # Let the first canvas finish booting before leaving it. `stub_login_and_enter_workflow`
    # returns on `domcontentloaded`, so navigating straight off it cancels the
    # session bootstrap mid-flight and the blank dataflow lands on the sign-in
    # form instead of the canvas.
    page.wait_for_selector("#tools-menu", timeout=45000)
    page.goto(f"{app_frontend.base_url}/dataflow/new")
    require_owner_view(page)
    page.wait_for_selector("#tools-menu", timeout=45000)
    dismiss_toasts(page)

    page.get_by_test_id("share-menu-btn").click(force=True)
    page.get_by_test_id("open-dashboard-link").click()

    expect(page.get_by_text("Save the dataflow first to share it.").first).to_be_visible(timeout=10000)
    assert "/dataflow/new" in page.url, "the page navigated away from an unsaved dataflow"


def test_editing_the_layout_moves_tiles_and_nothing_else(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_layout")
    project_id = session["project"]["id"]
    before = _project(current_server, session["token"], project_id)

    _open_dashboard(page, app_frontend.base_url, project_id)
    _chart_drew(page)
    page.get_by_test_id("edit-layout-btn").click()

    handle = page.locator(
        f'.react-flow__node[data-id="{CHART}"] .curio-dashboard-tile-handle'
    ).first
    box = handle.bounding_box()
    assert box, "the tile's title band has no box to grab"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 140, y + 70, steps=10)
    page.mouse.up()

    # Backspace on a selected tile must not delete the node out of the dataflow.
    page.locator(f'.react-flow__node[data-id="{CHART}"]').click(position={"x": 20, "y": 8})
    page.keyboard.press("Backspace")
    page.keyboard.press("Delete")
    count = page.evaluate("() => window.__curio_reactFlow.getNodes().length")
    assert count == 3, "a key press deleted a node from the dashboard"

    page.get_by_test_id("save-layout-btn").click()
    page.get_by_test_id("save-layout-btn").wait_for(state="detached", timeout=20000)

    after = _project(current_server, session["token"], project_id)
    chart_before = _node_in_spec(before, CHART)
    chart_after = _node_in_spec(after, CHART)
    assert "dashboardX" in chart_after and "dashboardY" in chart_after, chart_after
    assert (chart_after.get("dashboardX"), chart_after.get("dashboardY")) != (
        chart_before.get("dashboardX"), chart_before.get("dashboardY"),
    ), "the tile's new slot was not saved"
    # The canvas layout is untouched: the dashboard only ever writes its own
    # fields, even though it saved the whole spec.
    for node_id in (PRODUCER, POOL, CHART):
        assert (
            _node_in_spec(after, node_id)["x"], _node_in_spec(after, node_id)["y"]
        ) == (
            _node_in_spec(before, node_id)["x"], _node_in_spec(before, node_id)["y"]
        ), f"the dashboard moved {node_id} on the canvas"
    # And the recorded outputs are the canvas's business, not this page's.
    assert after["outputs"] == before["outputs"]


SCN_LOAD = "dsc-load"
SCN_FACTOR = "dsc-factor"
SCN_BASE = "dsc-base"
SCN_TALL = "dsc-tall"
SCN_COMPARE = "dsc-compare"
SCENARIO_COLORS = {"base": "rgb(42, 157, 143)", "tall": "rgb(232, 106, 60)"}


def _scenario_spec() -> dict:
    """A loader and a value node, the scenarios' context, two scenarios of one
    node each, the second reading the value too, and a node reading both
    outcomes; every node pinned. The canvas puts the two scenarios' nodes in one
    column, as the distance layout would too."""
    def pinned(node: dict) -> dict:
        return {**node, "dashboardPinned": True}

    factor = {**_node(SCN_FACTOR, "curio.builtin/computation-analysis", 0, "return [!! factor !!]\n"), "y": 700}
    factor["metadata"]["widgets"] = [{"name": "factor", "type": "number", "default": 2}]
    edge = lambda source, target, handle="in": {  # noqa: E731
        "id": f"e-{source}-{target}", "source": source, "target": target,
        "sourceHandle": "out", "targetHandle": handle,
    }
    return {
        "dataflow": {
            "name": "Dashboard by scenario",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                pinned(_node(SCN_LOAD, "curio.builtin/data-loading", 0, PRODUCER_CODE)),
                pinned(factor),
                pinned(_node(SCN_BASE, "curio.builtin/computation-analysis", 700, "return input_0\n")),
                pinned({**_node(SCN_TALL, "curio.builtin/computation-analysis", 700,
                                "factor = input_1\nreturn input_0\n"), "y": 700}),
                pinned(_node(SCN_COMPARE, "curio.builtin/computation-analysis", 1400, "return input_0\n")),
            ],
            "edges": [
                edge(SCN_LOAD, SCN_BASE),
                edge(SCN_LOAD, SCN_TALL),
                edge(SCN_FACTOR, SCN_TALL, "in_1"),
                edge(SCN_BASE, SCN_COMPARE),
                edge(SCN_TALL, SCN_COMPARE, "in_1"),
            ],
            "scenarios": [
                {"id": "base", "name": "Baseline", "color": "#2a9d8f", "nodes": [SCN_BASE]},
                {"id": "tall", "name": "Twice as tall", "color": "#e86a3c", "nodes": [SCN_TALL]},
            ],
        },
    }


_TILE_POSITIONS_JS = """() => Object.fromEntries(window.__curio_reactFlow.getNodes()
    .filter((n) => n.style?.display !== 'none')
    .map((n) => [n.id, [n.position.x, n.position.y]]))"""


def _tiles_settle(page, node_id: str, *, at=None, away_from=None) -> dict:
    """The tiles' positions once *node_id* is *at* a place, or *away_from* one
    (React Flow takes a move a render later). On a timeout the caller's
    assertion says what the positions were."""
    try:
        page.wait_for_function(
            """([id, at, away]) => {
                const node = window.__curio_reactFlow.getNode(id);
                if (!node) return false;
                const same = (p) => p[0] === node.position.x && p[1] === node.position.y;
                return at ? same(at) : !same(away);
            }""",
            arg=[node_id, at, away_from],
            timeout=10000,
        )
    except PlaywrightTimeoutError:
        pass
    return page.evaluate(_TILE_POSITIONS_JS)


def test_scenarios_get_a_column_each_under_a_header_in_their_color(
    app_frontend: "FrontendPage", current_server, page,
):
    """The dashboard by scenario (#662): the shared tiles first, a column per
    scenario under its header, then what reads their outcomes. Arrange by
    scenario puts a dragged tile back, and Save layout records the columns."""
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dashboard Owner",
        username=f"dash_scn_{uuid.uuid4().hex[:8]}",
        project_name="Dashboard by scenario",
        project_spec=_scenario_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    project_id = session["project"]["id"]
    before = _project(current_server, session["token"], project_id)

    _open_dashboard(page, app_frontend.base_url, project_id)
    for node_id in (SCN_LOAD, SCN_FACTOR, SCN_BASE, SCN_TALL, SCN_COMPARE):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    opened = page.evaluate(_TILE_POSITIONS_JS)
    x = {node_id: at[0] for node_id, at in opened.items()}
    assert x[SCN_LOAD] == x[SCN_FACTOR] < x[SCN_BASE] < x[SCN_TALL] < x[SCN_COMPARE], (
        f"tile columns {x!r}: the loader and the value node first, then "
        f"one column per scenario, then the node reading both"
    )

    # The bar floats over the top of the canvas, so a header must be below it.
    canvas = page.locator(".react-flow").first.bounding_box()
    bar = page.locator("[data-curio-menu-bar]").first.bounding_box()
    assert canvas and bar, "the dashboard has no canvas or no bar"
    top = max(canvas["y"], bar["y"] + bar["height"])
    for scenario_id, name, member in (("base", "Baseline", SCN_BASE), ("tall", "Twice as tall", SCN_TALL)):
        header = page.locator(f'[data-scenario-header="{scenario_id}"]')
        expect(header).to_have_text(name, timeout=20000)
        chip = header.locator("span").first
        color = chip.evaluate("(el) => getComputedStyle(el).backgroundColor")
        assert color == SCENARIO_COLORS[scenario_id], f"{name}'s header is {color}"
        box = header.bounding_box()
        tile = node_locator(page, member).bounding_box()
        assert box and tile, f"{name}'s header or tile has no box"
        assert top <= box["y"] and box["y"] + box["height"] <= tile["y"], (
            f"{name}'s header {box!r} is not in view above its tile {tile!r} (view starts at {top})"
        )
        assert header.get_by_role("button").count() == 0, "a dashboard header offers a button"
    assert page.locator("[data-scenario-frame]").count() == 2

    # A code node with no widget shows its code on its tile, read-only (#1117):
    # Save layout below would save a stray edit.
    code = "return input_0\n"
    assert read_node_code(page, SCN_BASE) == code, "the tile does not show its node's code"
    editor = node_locator(page, SCN_BASE).locator(".monaco-editor").first
    editor.locator(".view-lines").first.click()
    assert editor.evaluate("(el) => el.contains(document.activeElement)"), "the click did not reach the tile's editor"
    page.keyboard.type("x = 1")
    assert read_node_code(page, SCN_BASE) == code, "a tile's code took an edit"

    # Drag a scenario's tile away, then put every tile back in its column.
    page.get_by_test_id("edit-layout-btn").click()
    handle = page.locator(
        f'.react-flow__node[data-id="{SCN_BASE}"] .curio-dashboard-tile-handle'
    ).first
    grab = handle.bounding_box()
    assert grab, "the tile's title band has no box to grab"
    gx, gy = grab["x"] + grab["width"] / 2, grab["y"] + grab["height"] / 2
    page.mouse.move(gx, gy)
    page.mouse.down()
    page.mouse.move(gx + 140, gy + 70, steps=10)
    page.mouse.up()
    dragged = _tiles_settle(page, SCN_BASE, away_from=opened[SCN_BASE])
    assert dragged[SCN_BASE] != opened[SCN_BASE], "the drag did not move the tile"

    page.get_by_test_id("arrange-by-scenario-btn").click()
    arranged = _tiles_settle(page, SCN_BASE, at=opened[SCN_BASE])
    assert arranged == opened, f"Arrange by scenario left {arranged!r}, not the columns {opened!r}"

    page.get_by_test_id("save-layout-btn").click()
    page.get_by_test_id("save-layout-btn").wait_for(state="detached", timeout=20000)
    after = _project(current_server, session["token"], project_id)
    for node_id, (tx, ty) in opened.items():
        saved = _node_in_spec(after, node_id)
        assert (saved.get("dashboardX"), saved.get("dashboardY")) == (tx, ty), (
            f"{node_id} saved at {saved.get('dashboardX')!r}, {saved.get('dashboardY')!r}, not its column's {tx}, {ty}"
        )
        assert (saved["x"], saved["y"]) == (
            _node_in_spec(before, node_id)["x"], _node_in_spec(before, node_id)["y"],
        ), f"the dashboard moved {node_id} on the canvas"


def test_the_dashboard_is_a_layer_only_while_it_is_panned(
    app_frontend: "FrontendPage", current_server, page,
):
    """The canvas's rule on this page too (#533): no ``will-change`` at rest.

    Chrome keeps a ``will-change: transform`` layer painted at the zoom it was
    rasterized at, so a page fitted after its first paint could show its tiles
    as a scaled bitmap. The page takes the hint while a drag pans it, the way
    the canvas does (``useViewportMotionHint``).
    """
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="dash_layer")

    _open_dashboard(page, app_frontend.base_url, session["project"]["id"])
    _chart_drew(page)
    page.wait_for_timeout(VIEWPORT_SETTLE_WAIT_MS)
    at_rest = viewport_will_change(page)
    assert at_rest == "auto", f"the fitted dashboard's viewport has will-change {at_rest!r}, not 'auto'"

    # Panning is for the owner editing the layout; a locked page does not move.
    page.get_by_test_id("edit-layout-btn").click()
    # Beside the tile, on the bare pane: a press on the tile would move it.
    x, y = empty_pane_point(page, CHART)
    watch_viewport_hint(page)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 30, steps=8)
    during = viewport_hints(page)
    page.mouse.up()
    page.wait_for_timeout(VIEWPORT_SETTLE_WAIT_MS)

    assert "transform" in during, f"the viewport took no will-change hint while it was panned (saw {during!r})"
    settled = viewport_will_change(page)
    assert settled == "auto", f"once the pan settled the viewport's will-change is {settled!r}, not 'auto'"


# ---------------------------------------------------------------------------
# Autark (needs a WebGPU adapter: the GPU runner in CI)
# ---------------------------------------------------------------------------

AUTARK_EXAMPLE = "07-autark-gpu-shader.json"
AUTARK_MAP = "sh-map"


#: How long WebGPU takes to answer the first time the dashboard asks, in the
#: test below: the tile's rows land in that time. Well under the probe's own
#: limit (``WEBGPU_PROBE_TIMEOUT_MS``, 8 s), past which the map rightly says
#: WebGPU did not answer.
WEBGPU_ANSWER_MS = 4000

# Before the page's own scripts. The first ``requestAdapter`` answers after
# WEBGPU_ANSWER_MS, and so does every call made while it is out; later calls,
# autk-map's own among them, answer at once. The page notes that it held one.
_WEBGPU_ANSWERS_LATE_JS = """(() => {
    if (typeof GPU === "undefined" || !navigator.gpu) return;
    const request = GPU.prototype.requestAdapter;
    let answered = null;
    GPU.prototype.requestAdapter = function (...args) {
        if (!answered) {
            window.__curioTestWebGpuHeld = true;
            answered = new Promise((resolve) => setTimeout(resolve, %d));
        }
        return answered.then(() => request.apply(this, args));
    };
})();""" % WEBGPU_ANSWER_MS


def _autark_tile_pinned_and_saved(page, app_frontend: "FrontendPage", current_server) -> str:
    """Example 07 run once on the canvas, its map pinned and saved; its project id."""
    require_project_page()
    require_user_auth()
    from .walkthroughs import load_example_spec
    from .utils import run_all_and_wait

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Owner",
        username=f"dash_autk_{uuid.uuid4().hex[:8]}",
        project_name="Autark dashboard",
        project_spec=load_example_spec(AUTARK_EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    require_webgpu(page)
    project_id = session["project"]["id"]

    run_all_and_wait(page, timeout_ms=300000)
    _pin(page, AUTARK_MAP)
    _save(page)
    return project_id


def _the_tile_draws_without_a_run(page, base: str, project_id: str) -> None:
    """Open the dashboard: the map draws, and no node code goes to the sandbox,
    from the page or from a viewer's run."""
    executions: list[str] = []
    page.on(
        "request",
        lambda request: executions.append(request.url)
        if "/processJavaScriptCode" in request.url or "/processPythonCode" in request.url
        or _starts_a_run(request)
        else None,
    )
    _open_dashboard(page, base, project_id)
    canvas = page.locator(f"#autk-grammar-map-{AUTARK_MAP}")
    canvas.wait_for(state="visible", timeout=120000)
    assert canvas.evaluate("c => c.width > 0 && c.height > 0"), "the map tile has no drawing surface"
    assert executions == [], (
        f"opening the dashboard executed node code in the sandbox or started a run: "
        f"{executions!r}; the map's layers should have come from the Data Catalog"
    )


def test_an_autark_map_tile_draws_from_saved_layers_without_rerunning(
    app_frontend: "FrontendPage", current_server, page,
):
    """The map is the only thing that runs on the page, and only in the browser.

    Its data and compute nodes are upstream, and their layers come back from the
    Data Catalog. So opening the dashboard must not send a single JavaScript
    execution to the sandbox: that is where the data load would go.
    """
    project_id = _autark_tile_pinned_and_saved(page, app_frontend, current_server)
    _the_tile_draws_without_a_run(page, app_frontend.base_url, project_id)


def test_an_autark_map_tile_draws_when_webgpu_answers_after_its_rows(
    app_frontend: "FrontendPage", current_server, page,
):
    """The tile draws when its rows land before WebGPU answers.

    A map asks for WebGPU when its input lands and draws once the answer is
    yes. The Data Pool feeding this map hands its rows on with every fetch
    that lands, so the map can get a second input while it waits. On a GPU
    that is slow to answer (the arcade runners, which share one GPU; a GPU
    process still starting) both inputs could land before the answer, both
    draws then ran in one tick, and two ``sendCode``
    calls in one tick cancel each other: the map sat at "running" under "Not
    drawn yet" until the wait below ran out. Here WebGPU takes
    ``WEBGPU_ANSWER_MS`` to answer on every runner.
    """
    project_id = _autark_tile_pinned_and_saved(page, app_frontend, current_server)
    page.add_init_script(_WEBGPU_ANSWERS_LATE_JS)
    _the_tile_draws_without_a_run(page, app_frontend.base_url, project_id)
    assert page.evaluate("() => window.__curioTestWebGpuHeld === true"), (
        "the dashboard never asked for WebGPU, so no answer came late"
    )
