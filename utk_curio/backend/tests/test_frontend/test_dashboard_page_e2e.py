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
* the page is read-only for everyone but the owner, cannot delete anything, and
  its one write (Save layout) leaves the dataflow's recorded outputs alone.

The dataflow is built here rather than borrowed from ``docs/examples``: three
nodes, no datasets, so a failure is about this feature and not about a seed.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_dashboard_page_e2e.py -v
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    allow_guest_login_env,
    api_json,
    assert_vega_canvas_rendered,
    dismiss_toasts,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_login,
    stub_login_and_enter_workflow,
    wait_for_node_done,
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

def _enter(page, app_frontend, current_server, *, prefix: str) -> dict:
    """Sign in as a fresh owner, on the canvas of a fresh copy of the dataflow."""
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dashboard Owner",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name="Dashboard e2e",
        project_spec=_spec(),
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


def _pinned_and_saved(page, app_frontend, current_server, *, prefix: str) -> dict:
    """The common starting point: the chart ran, is pinned, and is saved."""
    session = _enter(page, app_frontend, current_server, prefix=prefix)
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

    # A full load of the page: nothing from the canvas session comes along.
    _open_dashboard(page, app_frontend.base_url, project_id)
    _chart_drew(page)

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
    through the sandbox's by-name fallback to the hydrated file.
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
        banner = visitor.get_by_test_id("shared-view-banner")
        banner.wait_for(timeout=45000)
        assert "read-only" in (banner.inner_text() or "").lower()
        assert_vega_canvas_rendered(visitor, CHART, timeout=90000)
        assert visitor.get_by_test_id("edit-layout-btn").count() == 0
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


# ---------------------------------------------------------------------------
# Autark (needs a WebGPU adapter: the GPU runner in CI)
# ---------------------------------------------------------------------------

AUTARK_EXAMPLE = "07-autark-gpu-shader.json"
AUTARK_MAP = "sh-map"


def _webgpu_adapter(page) -> bool:
    return bool(page.evaluate(
        "async () => !!(navigator.gpu && await navigator.gpu.requestAdapter())"
    ))


def test_an_autark_map_tile_draws_from_saved_layers_without_rerunning(
    app_frontend: "FrontendPage", current_server, page,
):
    """The map is the only thing that runs on the page, and only in the browser.

    Its data and compute nodes are upstream, and their layers come back from the
    Data Catalog. So opening the dashboard must not send a single JavaScript
    execution to the sandbox: that is where the data load would go.
    """
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
    if not _webgpu_adapter(page):
        if os.environ.get("CURIO_REQUIRE_HARDWARE_WEBGPU") == "1":
            pytest.fail("CURIO_REQUIRE_HARDWARE_WEBGPU=1 but this browser has no WebGPU adapter")
        pytest.skip("Autark tiles need a WebGPU adapter; this browser has none")
    project_id = session["project"]["id"]

    run_all_and_wait(page, timeout_ms=300000)
    _pin(page, AUTARK_MAP)
    _save(page)

    executions: list[str] = []
    page.on(
        "request",
        lambda request: executions.append(request.url)
        if "/processJavaScriptCode" in request.url or "/processPythonCode" in request.url
        else None,
    )
    _open_dashboard(page, app_frontend.base_url, project_id)
    canvas = page.locator(f"#autk-grammar-map-{AUTARK_MAP}")
    canvas.wait_for(state="visible", timeout=120000)
    assert canvas.evaluate("c => c.width > 0 && c.height > 0"), "the map tile has no drawing surface"
    assert executions == [], (
        f"opening the dashboard executed node code in the sandbox: {executions!r}; "
        f"the map's layers should have come from the Data Catalog"
    )
