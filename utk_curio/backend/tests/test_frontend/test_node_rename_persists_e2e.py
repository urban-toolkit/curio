"""Playwright E2E: a node's data survives a save, a reopen and the dashboard's
layout save.

The node's data is checked through its name: a node renamed from its header
keeps the name in its data (``title``, its one name), which a save writes to
the spec. Two paths write a node's data to disk: the canvas's own save, and the
dashboard page's Save layout, which saves the whole spec from the nodes the
PAGE loaded. The name has to come through both.

Reopening the project is how the round trip is closed, rather than a reload in
place: it forces a full remount from the persisted spec, so the test cannot
pass on component state that never unmounted.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_node_rename_persists_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

NEW_NAME = "Rainfall by district"

#: The lightest curated example with more than one node, so the scene has a
#: real node to rename rather than an empty canvas.
EXAMPLE = "01-vega-lite-chained-transforms.json"


def _load_example(name: str) -> dict:
    import json
    import os

    from .utils import REPO_ROOT

    path = os.path.join(REPO_ROOT, "docs", "examples", name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _rightmost_node_id(page) -> str:
    """The node with the greatest x on the canvas: example 01's chart, which
    the dashboard shows as a tile once it is pinned."""
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    return page.evaluate(
        """() => window.__curio_reactFlow.getNodes()
            .slice()
            .sort((a, b) => b.position.x - a.position.x)[0].id"""
    )


def _node(page, node_id: str):
    return page.locator(f'.react-flow__node[data-id="{node_id}"]')


def _header_title(page, node_id: str, name: str):
    """The node's header title, once it reads *name*."""
    return _node(page, node_id).locator(f'button[aria-label="Edit node title: {name}"]')


def _rename(page, node_id: str, name: str) -> None:
    """Rename a node from its header, as a user does: its title, then Enter."""
    node = _node(page, node_id)
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()
    # The header's controls swallow the native click so press-and-drag still
    # moves the node; activate_header_icon dispatches the pointer pair instead.
    activate_header_icon(node.locator('button[aria-label^="Edit node title:"]'))
    # Not get_by_label("Node title"): that substring-matches the title button's
    # own "Edit node title: ..." label as well.
    field = node.locator('input[aria-label="Node title"]')
    field.fill(name)
    field.press("Enter")
    expect(_header_title(page, node_id, name)).to_be_visible(timeout=10000)


def _node_data_name(page, node_id: str):
    """The name the canvas node itself carries (``data.title``).

    This, not the header, is what a save writes: a name shown from component
    state alone would pass a look at the header and still be lost. Waits for
    the node to be on the canvas, never for its name.
    """
    page.wait_for_function(
        """(nodeId) => !!(window.__curio_reactFlow
            && window.__curio_reactFlow.getNodes().some((n) => n.id === nodeId))""",
        arg=node_id,
        timeout=30000,
    )
    return page.evaluate(
        """(nodeId) => {
            const rf = window.__curio_reactFlow;
            const node = rf ? rf.getNodes().find((n) => n.id === nodeId) : null;
            return node && node.data ? (node.data.title ?? null) : null;
        }""",
        node_id,
    )


def test_a_renamed_node_survives_save_and_reopen(
    app_frontend: "FrontendPage", current_server, page
):
    require_project_page()
    require_user_auth()

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Rename Tester",
        username=f"rnm_{uuid.uuid4().hex[:10]}",
        project_name="Renamed node",
        project_spec=_load_example(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    node_id = _rightmost_node_id(page)
    _rename(page, node_id, NEW_NAME)
    stored = _node_data_name(page, node_id)
    assert stored == NEW_NAME, (
        f"the header shows the new name but the node's data does not carry it, "
        f"so a save has nothing to write; node.data.title = {stored!r}"
    )

    save_dataflow(page)

    # Leave and come back, rather than reloading in place: a reload could pass
    # on nothing more than component state that never unmounted.
    project_id = session["project"]["id"]
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    reopened = _node_data_name(page, node_id)
    assert reopened == NEW_NAME, (
        f"the name is gone from the node after save and reopen; "
        f"node.data.title = {reopened!r}"
    )
    expect(_header_title(page, node_id, NEW_NAME)).to_be_visible(timeout=15000)


def _drag_tile(page, node_id: str, dx: int, dy: int) -> None:
    """Drag a dashboard tile by its title band, the only part that moves it."""
    handle = page.locator(
        f'.react-flow__node[data-id="{node_id}"] .curio-dashboard-tile-handle'
    ).first
    handle.wait_for(state="visible", timeout=30000)
    box = handle.bounding_box()
    assert box, "the tile's title band has no box to grab"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=10)
    page.mouse.up()


def test_a_renamed_node_survives_a_dashboard_layout_save(
    app_frontend: "FrontendPage", current_server, page
):
    """The name is carried by the node, so saving a dashboard cannot lose it.

    The dashboard is a page of its own, and its one write, Save layout, saves
    the whole dataflow spec from the nodes the PAGE loaded: every one of them,
    pinned or not, rewritten with tile geometry. That is a second path by which
    a node's data reaches disk, and the name has to come through it intact.

    The round trip is two full page loads, dataflow to dashboard and back, so
    nothing can survive in component state: whatever the second canvas shows
    was read from the spec the dashboard wrote.
    """
    require_project_page()
    require_user_auth()

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Rename Tester",
        username=f"rnmdash_{uuid.uuid4().hex[:8]}",
        project_name="Renamed node dashboard",
        project_spec=_load_example(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    project_id = session["project"]["id"]

    node_id = _rightmost_node_id(page)
    _rename(page, node_id, NEW_NAME)
    stored = _node_data_name(page, node_id)
    assert stored == NEW_NAME, (
        f"the header shows the new name but the node's data does not carry it; "
        f"node.data.title = {stored!r}"
    )

    # Pin the renamed node and save, so the dashboard has it as a tile.
    node = _node(page, node_id)
    activate_header_icon(node.locator('[data-tooltip="Pin to dashboard"]').first)
    expect(node.locator('[data-tooltip="Unpin from dashboard"]')).to_have_count(1, timeout=10000)
    save_dataflow(page)

    # Onto the dashboard, move the tile, and save the layout.
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("edit-layout-btn").wait_for(state="visible", timeout=45000)
    tile = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    tile.wait_for(state="visible", timeout=45000)
    # The node header is not rendered on a tile, so the name cannot be edited
    # here: whatever reaches disk came from the node's data, not from this page.
    assert tile.locator('button[aria-label^="Edit node title:"]').count() == 0, (
        "the tile is rendering the canvas node header; this test's assumptions "
        "about what is reachable on the dashboard no longer hold"
    )
    # The tile's title band reads the name the canvas saved.
    expect(tile.locator(".curio-dashboard-tile-handle").first).to_have_attribute(
        "data-tooltip", NEW_NAME, timeout=15000
    )
    page.get_by_test_id("edit-layout-btn").click()
    before = page.evaluate(
        "(id) => window.__curio_reactFlow.getNode(id).position", node_id,
    )
    _drag_tile(page, node_id, 120, 60)
    after = page.evaluate(
        "(id) => window.__curio_reactFlow.getNode(id).position", node_id,
    )
    assert after != before, "the tile did not move, so the layout save has nothing to write"
    page.get_by_test_id("save-layout-btn").click()
    page.get_by_test_id("save-layout-btn").wait_for(state="detached", timeout=20000)

    # Back to the dataflow, from disk.
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    survived = _node_data_name(page, node_id)
    assert survived == NEW_NAME, (
        f"the dashboard's layout save dropped the name from the node, so the "
        f"spec on disk no longer has it; node.data.title = {survived!r}"
    )
    expect(_header_title(page, node_id, NEW_NAME)).to_be_visible(timeout=15000)
