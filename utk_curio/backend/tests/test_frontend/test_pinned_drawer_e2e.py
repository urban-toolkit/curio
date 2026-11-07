"""Playwright E2E: a pinned drawer stays open, and the canvas and the top bar
keep working beside it (#1352).

The pin keeps a canvas drawer open while you browse it. It used to keep the
drawer's full-window scrim too, so the canvas, the palette and the top bar took
no pointer until you unpinned: the canvas could not be panned, no node could be
selected, and File did not open. For each drawer that has the pin, the six
catalogs from the top bar and Provenance from the View menu, on a dataflow with
one node:

* pinned, the empty canvas left of the panel is the canvas's own pane under the
  pointer, not the drawer's scrim;
* a click on the node's header selects the node;
* a mouse drag on the empty canvas pans it;
* File opens on a plain click, and the drawer stays open after its Escape;
* unpinned again, a click on the canvas lands on the scrim and closes the
  drawer, as before.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_pinned_drawer_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    CANVAS_DROP_TARGET,
    drag_builtin_to_canvas,
    require_owner_view,
    require_project_page,
    require_user_auth,
    set_canvas_zoom,
    settled_viewport,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

BAR = "header[data-curio-menu-bar]"

#: (what opens the drawer, its overlay root). A catalog opens from its button
#: in the top bar; Provenance from the View menu.
DRAWERS = (
    ("Node Catalog", '[data-curio-node-catalog-drawer="true"]'),
    ("Data Catalog", '[data-curio-dataset-catalog-drawer="true"]'),
    ("Agent Catalog", '[data-curio-agent-catalog-drawer="true"]'),
    ("Discovery Catalog", '[data-curio-discovery-catalog-drawer="true"]'),
    ("Model Catalog", '[data-curio-model-catalog-drawer="true"]'),
    ("Scenario Catalog", '[data-curio-scenario-catalog-drawer="true"]'),
    ("Provenance", '[data-curio-provenance-drawer="true"]'),
)

#: The canvas's zoom: a node is 525x350 at zoom 1, so at 0.6 it leaves room
#: for empty canvas between it and the 520 px panel of a 1280x720 window.
ZOOM = 0.6
#: Where the node is dropped, as an offset from the canvas's top-left corner:
#: right of the rail and under the dataflow's title.
NODE_AT = (150.0, 150.0)
#: Empty canvas, as an offset from the canvas's top-left corner: under the
#: node, and left of the panel.
EMPTY_AT = (330.0, 520.0)
#: How far the canvas is dragged.
PAN = (90.0, 50.0)

# What lies under a client point: whether it is the canvas's pane (and not a
# node on it), whether it is inside the drawer's root (its scrim or its
# panel), whether it is on the node *id*, and the element, named for a failure
# message.
_WHAT_IS_AT_JS = """([[x, y], root, id]) => {
    const hit = document.elementFromPoint(x, y);
    const label = hit && hit.getAttribute("aria-label");
    const cls = hit && typeof hit.className === "string" ? hit.className.split(" ")[0] : "";
    return {
        onPane: !!hit && !!hit.closest(".react-flow__pane") && !hit.closest(".react-flow__node"),
        inDrawer: !!hit && !!hit.closest(root),
        onNode: !!hit && !!id && !!hit.closest(`.react-flow__node[data-id="${id}"]`),
        hit: hit ? hit.tagName.toLowerCase() + (label ? `[aria-label="${label}"]` : cls ? `.${cls}` : "") : "nothing",
    };
}"""

# A point on the node's header strip, where a click selects the node: a
# fraction of its width in, clear of the icon buttons at its right end, and
# halfway down it. Everything under the header is the code editor, which
# keeps a click to itself. Null until the header is drawn.
_HEADER_POINT_JS = """(id) => {
    const header = document.querySelector(`[id="${id}resizable"] > .curio-node-header`);
    const box = header && header.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    return {x: box.left + box.width * 0.4, y: box.top + box.height / 2};
}"""

_VIEWPORT_JS = """() => ({
    transform: document.querySelector(".react-flow__viewport").style.transform,
    ...window.__curio_reactFlow.getViewport(),
})"""


def _client_point(page, at: tuple[float, float]) -> list[float]:
    box = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    return [box["x"] + at[0], box["y"] + at[1]]


def _what_is_at(page, point, root: str, node: str | None = None) -> dict:
    return page.evaluate(_WHAT_IS_AT_JS, [[point[0], point[1]], root, node])


def _header_point(page, node: str) -> list[float]:
    try:
        page.wait_for_function(f"(id) => !!({_HEADER_POINT_JS})(id)", arg=node, timeout=30000)
    except PlaywrightTimeoutError:
        raise AssertionError(f"the node {node} never drew its header") from None
    spot = page.evaluate(_HEADER_POINT_JS, node)
    return [spot["x"], spot["y"]]


def _open(page, opener: str, root: str):
    """Open the drawer *opener* names and return its root, once presented."""
    bar = page.locator(BAR)
    if opener == "Provenance":
        bar.get_by_role("button", name="View menu", exact=True).click()
        # Found by its test id: a node's header has a Provenance button too.
        page.get_by_test_id("provenance-menu-item").click()
    else:
        bar.get_by_role("button", name=opener, exact=True).click()
    drawer = page.locator(root)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=20000)
    return drawer


@pytest.mark.parametrize("opener,root", DRAWERS, ids=[opener for opener, _ in DRAWERS])
def test_a_pinned_drawer_leaves_the_canvas_and_the_top_bar_working(
    app_frontend: "FrontendPage", current_server: str, page, opener: str, root: str,
):
    require_project_page()
    require_user_auth()

    # Before navigating: the drawers slide in through useSlideDrawerPresentation,
    # which reads prefers-reduced-motion.
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Pin User",
        username=f"pin_{uuid.uuid4().hex[:10]}",
        project_name="Pinned drawer",
    )
    require_owner_view(page)
    page.locator(CANVAS_DROP_TARGET).wait_for(state="visible", timeout=45000)
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)

    set_canvas_zoom(page, ZOOM)
    node = drag_builtin_to_canvas(page, "#tile-python-computation", at=NODE_AT)
    settled_viewport(page)
    header = _header_point(page, node)
    empty = _client_point(page, EMPTY_AT)
    at = _what_is_at(page, empty, root)
    assert at["onPane"], f"{empty} is not empty canvas before any drawer opens, but {at['hit']}"
    at = _what_is_at(page, header, root, node)
    assert at["onNode"], f"the node's header at {header} is covered before any drawer opens: {at['hit']}"

    drawer = _open(page, opener, root)
    panel_left = drawer.locator(':scope > [role="dialog"]').bounding_box()["x"]
    assert empty[0] < panel_left and header[0] < panel_left, (
        f"the empty canvas at {empty} or the node's header at {header} is under the "
        f"{opener} panel, whose left edge is at {panel_left}"
    )
    # Unpinned, the scrim covers the canvas, as it always has.
    at = _what_is_at(page, empty, root)
    assert at["inDrawer"], f"unpinned, the {opener} drawer's scrim is not over {empty}: {at['hit']}"

    drawer.get_by_role("button", name="Pin drawer open", exact=True).click()
    expect(drawer.get_by_role("button", name="Unpin drawer", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )

    # Pinned, the pointer reaches the canvas beside the panel.
    at = _what_is_at(page, empty, root)
    assert at["onPane"] and not at["inDrawer"], (
        f"pinned, the empty canvas left of the {opener} panel is {at['hit']}, not the canvas"
    )

    # A click on the node's header selects it.
    at = _what_is_at(page, header, root, node)
    assert at["onNode"], f"pinned, the node's header at {header} is {at['hit']}, not the node"
    page.mouse.click(header[0], header[1])
    try:
        page.wait_for_function(
            "(id) => !!window.__curio_reactFlow.getNodes().find((n) => n.id === id)?.selected",
            arg=node, timeout=5000,
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"pinned, a click on the node's header at {header} left the node unselected"
        ) from None

    # A drag on the empty canvas pans it.
    before = page.evaluate(_VIEWPORT_JS)
    page.mouse.move(empty[0], empty[1])
    page.mouse.down()
    page.mouse.move(empty[0] + PAN[0], empty[1] + PAN[1], steps=12)
    page.mouse.up()
    after = settled_viewport(page)
    moved = (after["x"] - before["x"], after["y"] - before["y"])
    transform = page.evaluate(_VIEWPORT_JS)["transform"]
    assert transform != before["transform"], (
        f"pinned, a drag on the canvas left its viewport at {transform}"
    )
    assert moved[0] > PAN[0] / 2 and moved[1] > PAN[1] / 2, (
        f"pinned, a drag of {PAN} on the canvas moved its viewport by {moved}"
    )

    # File opens on a plain click: no force, so the click must reach the button.
    page.locator(BAR).get_by_role("button", name="File menu", exact=True).click(timeout=5000)
    save = page.get_by_role("button", name="Save dataflow", exact=True)
    expect(save).to_be_visible(timeout=5000)
    page.keyboard.press("Escape")
    expect(save).to_be_hidden(timeout=5000)
    # The pin kept the drawer open through all of it, Escape included.
    expect(drawer).to_have_attribute("aria-hidden", "false")

    # Unpinned again, the scrim is back over the canvas and a click on it
    # closes the drawer.
    drawer.get_by_role("button", name="Unpin drawer", exact=True).click()
    expect(drawer.get_by_role("button", name="Pin drawer open", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )
    at = _what_is_at(page, empty, root)
    assert at["inDrawer"], f"unpinned again, the {opener} drawer's scrim is not over {empty}: {at['hit']}"
    page.mouse.click(empty[0], empty[1])
    wait_for_drawer_closed(page, root)
