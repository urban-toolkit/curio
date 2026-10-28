"""The canvas wears the top bar every other page wears, and its catalogs are
one click away.

What the owner saw: the canvas bar looked like nothing else in Curio, and its
features were hard to find. All five catalogs hid under a "Data" menu, the
Discovery Catalog could be reached no other way, and the canvas had neither API
Settings nor Monitor, which every section page shows in its bar.

So, on a fresh dataflow at the default 1280x720 viewport:

* the bar is the section pages' bar: the same height, the logo link, Monitor,
  API Settings and the account;
* it holds the dataflow's menus and the six catalogs in one row, then the
  Canvas | Notebook switch at the row's end, beside Monitor, with every control
  inside the bar, none overlapping the next, nothing overflowing its slot, and
  each catalog's label showing, even next to the widest account name the bar
  shows. Provenance is a View menu row, which left the room for the sixth;
* each catalog button opens its own drawer over the dataflow;
* Monitor and API Settings open as drawers over the dataflow, which stays
  where it was;
* the dataflow's title and the left rail start below the bar;
* a title long enough to reach the dock of canvas agents, centered beside
  it, never runs under the dock, also while it is renamed, and a title with
  room leaves the dock where it always was.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_header_e2e.py -v
"""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin

from .utils import (
    api_json,
    require_owner_view,
    require_project_page,
    require_user_auth,
    signup_e2e_user,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: (accessible name, drawer root attribute), in the section tabs' order.
CATALOGS = (
    ("Node Catalog", "data-curio-node-catalog-drawer"),
    ("Data Catalog", "data-curio-dataset-catalog-drawer"),
    ("Agent Catalog", "data-curio-agent-catalog-drawer"),
    ("Discovery Catalog", "data-curio-discovery-catalog-drawer"),
    ("Model Catalog", "data-curio-model-catalog-drawer"),
    ("Scenario Catalog", "data-curio-scenario-catalog-drawer"),
)

BAR = "header[data-curio-menu-bar]"

#: Longer than the account block shows (it ellipsizes at 110px), so the bar
#: is measured with the widest right-hand cluster it can have.
LONG_NAME = "Header Tester With A Long Account Name"

_MEASURE_SLOT = """(bar) => {
  // The slot holding the page's controls: the bar's child that holds File.
  const file = bar.querySelector('[aria-label="File menu"]');
  let slot = file;
  while (slot && slot.parentElement !== bar) slot = slot.parentElement;
  return slot ? { clientWidth: slot.clientWidth, scrollWidth: slot.scrollWidth } : null;
}"""

_MEASURE_BAR = """(bar) => {
  const box = bar.getBoundingClientRect();
  const controls = Array.from(bar.querySelectorAll('button, a'))
    .filter((el) => el.getClientRects().length > 0)
    .map((el) => ({
      name: el.getAttribute('aria-label') || el.textContent.trim() || el.tagName,
      rect: el.getBoundingClientRect(),
    }));
  const outside = controls
    .filter(({ rect }) =>
      rect.left < box.left - 0.5 || rect.right > box.right + 0.5 ||
      rect.top < box.top - 0.5 || rect.bottom > box.bottom + 0.5)
    .map(({ name }) => name);
  // In one row, left to right, no control may start before the previous one
  // ends: a wrapped or squeezed bar overlaps its own controls.
  const sorted = controls
    .filter(({ rect }) => rect.width > 0)
    .sort((a, b) => a.rect.left - b.rect.left);
  const overlapping = [];
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1].rect;
    const next = sorted[i].rect;
    const sameRow = Math.abs((prev.top + prev.bottom) - (next.top + next.bottom)) / 2 < prev.height;
    if (sameRow && next.left < prev.right - 0.5) {
      overlapping.push(sorted[i - 1].name + ' / ' + sorted[i].name);
    }
  }
  return { height: box.height, bottom: box.bottom, outside, overlapping };
}"""


def _fresh_canvas(page, base_url: str) -> None:
    page.goto(f"{base_url}/dataflow/new")
    page.wait_for_selector("#tools-menu", timeout=45000)
    require_owner_view(page)
    page.locator(BAR).wait_for(state="visible", timeout=20000)


def test_the_canvas_wears_the_shared_bar_with_the_catalogs_in_it(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_user_auth()
    require_project_page()

    signup_e2e_user(
        page, frontend_server, name=LONG_NAME,
        username=f"header_{uuid.uuid4().hex[:10]}",
    )
    wait_for_projects_page(page, timeout=30000)
    section_bar = page.locator(BAR)
    expect(section_bar).to_be_visible(timeout=20000)
    section_height = section_bar.evaluate("(b) => b.getBoundingClientRect().height")
    # A section page's Monitor and API Settings go to their pages.
    expect(section_bar.get_by_role("link", name="Monitor", exact=True)).to_have_attribute(
        "href", re.compile(r"/monitor$")
    )
    expect(section_bar.get_by_role("link", name="API Settings", exact=True)).to_have_attribute(
        "href", re.compile(r"/settings$")
    )

    _fresh_canvas(page, app_frontend.base_url)
    bar = page.locator(BAR)

    # The section pages' bar, not a look-alike: the same parts and height.
    # Monitor and API Settings are links on a section page and buttons that
    # open drawers here.
    expect(bar.get_by_role("link", name="Monitor", exact=True)).to_have_count(0)
    expect(bar.get_by_role("link", name="Curio", exact=True)).to_be_visible()
    expect(bar.get_by_role("button", name="Monitor", exact=True)).to_be_visible()
    expect(bar.get_by_role("button", name="API Settings", exact=True)).to_be_visible()
    expect(bar.get_by_test_id("user-menu")).to_be_visible()

    # The dataflow's own controls, and every catalog with its label showing.
    for name in ("File menu", "View menu", "Share menu"):
        expect(bar.get_by_role("button", name=name, exact=True)).to_be_visible()
    # The view switch, on the canvas: both views offered, the canvas checked.
    expect(bar.get_by_role("radiogroup", name="Dataflow view", exact=True)).to_be_visible()
    for name, checked in (("Canvas view", "true"), ("Notebook view", "false")):
        option = bar.get_by_role("radio", name=name, exact=True)
        expect(option).to_be_visible()
        expect(option).to_have_attribute("aria-checked", checked)
    # Provenance is one click into the View menu, and gone from the bar.
    expect(bar.get_by_role("button", name="Provenance", exact=True)).to_have_count(0)
    bar.get_by_role("button", name="View menu", exact=True).click()
    expect(bar.get_by_test_id("provenance-menu-item")).to_be_visible()
    page.keyboard.press("Escape")
    expect(bar.get_by_test_id("provenance-menu-item")).to_have_count(0)
    expect(bar.locator("[data-curio-save-state]")).to_be_visible()
    for name, _ in CATALOGS:
        button = bar.get_by_role("button", name=name, exact=True)
        expect(button).to_be_visible()
        label = button.locator("span")
        expect(label).to_be_visible()
        assert name.startswith(label.inner_text().strip()), (
            f"{name}: the visible label {label.inner_text()!r} is not its short name"
        )

    failures: list[str] = []
    m = bar.evaluate(_MEASURE_BAR)
    slot = bar.evaluate(_MEASURE_SLOT)
    print(f"canvas bar: {m}; slot {slot}; section bar height {section_height}")
    if slot is None:
        failures.append("the bar has no slot holding the File menu")
    elif slot["scrollWidth"] > slot["clientWidth"]:
        # Overflowing controls spill over the Monitor pill rather than wrap.
        failures.append(
            f"the bar's controls need {slot['scrollWidth']}px in a "
            f"{slot['clientWidth']}px slot"
        )
    if abs(m["height"] - section_height) > 0.5:
        failures.append(
            f"the canvas bar is {m['height']}px tall, the section pages' {section_height}px"
        )
    if m["outside"]:
        failures.append(f"controls drawn outside the bar: {m['outside']}")
    if m["overlapping"]:
        failures.append(f"controls overlapping in the bar: {m['overlapping']}")

    # The view switch closes the row: after the last catalog, and nothing
    # between it and Monitor but the bar's gap.
    switch_box = bar.get_by_role("radiogroup", name="Dataflow view", exact=True).bounding_box()
    monitor_box = bar.get_by_role("button", name="Monitor", exact=True).bounding_box()
    last_catalog = bar.get_by_role("button", name=CATALOGS[-1][0], exact=True).bounding_box()
    switch_right = switch_box["x"] + switch_box["width"]
    if switch_box["x"] < last_catalog["x"] + last_catalog["width"]:
        failures.append(f"the view switch (x={switch_box['x']}) is not after the {CATALOGS[-1][0]}")
    if not 0 <= monitor_box["x"] - switch_right <= 12:
        failures.append(
            f"the view switch ends {monitor_box['x'] - switch_right:.1f}px before Monitor, not beside it"
        )

    title_top = page.locator("[data-curio-canvas-title]").evaluate(
        "(el) => el.getBoundingClientRect().top"
    )
    rail_top = page.locator("#tools-palette-dock").evaluate(
        "(el) => el.getBoundingClientRect().top"
    )
    if title_top < m["bottom"]:
        failures.append(f"the dataflow title starts at y={title_top}, under the bar (y={m['bottom']})")
    if rail_top < m["bottom"]:
        failures.append(f"the left rail starts at y={rail_top}, under the bar (y={m['bottom']})")
    assert not failures, "\n".join(failures)


#: The Crown Heights example's name: at 1280 wide, long enough to reach the
#: dock of canvas agents centered beside it.
LONG_TITLE = "Crown Heights shade from 1550 Bedford Avenue"

DOCK = '[role="toolbar"][aria-label="Canvas agents"]'

#: The title as shown (its name, or the name's input while renaming) and the
#: dock, each as [left, top, right, bottom], whether they meet, and the
#: dock's own style attribute.
_TITLE_AND_DOCK = """(dock) => {
  const name = document.querySelector('[data-curio-canvas-title]').firstElementChild;
  const box = (el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const [a, b] = [box(name), box(document.querySelector(dock))];
  const meet = a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
  return { title: a, dock: b, meet, style: document.querySelector(dock).getAttribute('style') };
}"""


def _title_clear_of_dock(page, what: str) -> None:
    """The title and the dock come apart within a moment of *what*: the dock
    moves once fonts and sizes settle."""
    try:
        page.wait_for_function(f"(dock) => !({_TITLE_AND_DOCK})(dock).meet", arg=DOCK, timeout=5000)
    except PlaywrightTimeoutError:
        shown = page.evaluate(_TITLE_AND_DOCK, DOCK)
        raise AssertionError(
            f"{what}: the title {shown['title']} runs under the agents' dock {shown['dock']}"
        ) from None


def test_a_long_title_never_runs_under_the_agents_dock(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_user_auth()
    require_project_page()

    spec = {
        "name": LONG_TITLE,
        "dataflow": {"name": LONG_TITLE, "nodes": [], "edges": [], "task": "", "timestamp": 0},
    }
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Title Tester",
        username=f"title_{uuid.uuid4().hex[:10]}",
        project_name=LONG_TITLE,
        project_spec=spec,
    )
    require_owner_view(page)
    # A canvas agent puts the dock on the canvas.
    builder = next(m for m in builtin.list_builtin_manifests() if m.agent_id == "agent.curio.dataflow-builder")
    base = f"{current_server}/api/agents/projects/{session['project']['id']}"
    api_json(f"{base}/install", session["token"], method="POST", payload={"coord": builder.dir_name})
    api_json(
        f"{base}/attachments", session["token"], method="POST",
        payload={"coord": builder.dir_name, "target": {"kind": "canvas"}},
    )
    page.reload()
    expect(page.locator(DOCK)).to_be_visible(timeout=45000)
    name = page.locator("[data-curio-canvas-title] h1")
    expect(name).to_have_text(LONG_TITLE, timeout=20000)
    page.evaluate("() => document.fonts.ready.then(() => true)")
    _title_clear_of_dock(page, "the dataflow opened")

    # Renamed, the title is an input, and still clear of the dock.
    name.click()
    field = page.locator("[data-curio-canvas-title] input")
    expect(field).to_be_visible()
    _title_clear_of_dock(page, "the title opened for renaming")

    # A short name leaves the dock where its stylesheet centers it: no style
    # of its own (React leaves an empty one once it drops a style).
    field.fill("Short")
    field.press("Enter")
    expect(name).to_have_text("Short", timeout=10000)
    try:
        page.wait_for_function(
            f"(dock) => !({_TITLE_AND_DOCK})(dock).style", arg=DOCK, timeout=5000,
        )
    except PlaywrightTimeoutError:
        shown = page.evaluate(_TITLE_AND_DOCK, DOCK)
        raise AssertionError(f"with a short title the dock is moved: style {shown['style']!r}") from None


def test_each_catalog_button_opens_its_own_drawer(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_user_auth()
    require_project_page()

    signup_e2e_user(
        page, frontend_server, name="Catalog Buttons",
        username=f"catbtn_{uuid.uuid4().hex[:10]}",
    )
    wait_for_projects_page(page, timeout=30000)

    for name, attr in CATALOGS:
        # A fresh canvas per catalog: an open drawer covers the bar with its scrim.
        _fresh_canvas(page, app_frontend.base_url)
        page.locator(BAR).get_by_role("button", name=name, exact=True).click()
        drawer = page.locator(f'[{attr}="true"]')
        expect(drawer).to_have_attribute("aria-hidden", "false", timeout=20000)
        others = [a for n, a in CATALOGS if a != attr]
        for other in others:
            expect(page.locator(f'[{other}="true"][aria-hidden="false"]')).to_have_count(0)


def _open_header_drawer(page, name: str, attr: str):
    """Click a bar pill and return its drawer, checking the canvas stayed."""
    page.locator(BAR).get_by_role("button", name=name, exact=True).click()
    drawer = page.locator(f'[{attr}="true"]')
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=20000)
    path = urlparse(page.url).path
    assert path.startswith("/dataflow"), f"{name} left the dataflow for {page.url}"
    return drawer


def _close_header_drawer(page, drawer, name: str, attr: str) -> None:
    drawer.get_by_role("button", name=f"Close {name}", exact=True).click()
    wait_for_drawer_closed(page, f'[{attr}="true"]')
    # The marker set on the live canvas: a canvas rendered again after leaving
    # and coming back would not carry it.
    expect(page.locator('#tools-menu[data-e2e-kept="yes"]')).to_have_count(1)


def test_monitor_and_api_settings_open_as_drawers_over_the_canvas(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_user_auth()
    require_project_page()

    signup_e2e_user(
        page, frontend_server, name="Canvas Drawers",
        username=f"canvasdrw_{uuid.uuid4().hex[:10]}",
    )
    wait_for_projects_page(page, timeout=30000)
    _fresh_canvas(page, app_frontend.base_url)
    page.locator("#tools-menu").evaluate("(el) => { el.dataset.e2eKept = 'yes'; }")

    drawer = _open_header_drawer(page, "Monitor", "data-curio-monitor-drawer")
    expect(drawer.get_by_test_id("monitor-hardware")).to_be_visible(timeout=20000)
    _close_header_drawer(page, drawer, "Monitor", "data-curio-monitor-drawer")

    drawer = _open_header_drawer(page, "API Settings", "data-curio-settings-drawer")
    expect(drawer.get_by_role("heading", name="API Settings", level=2)).to_be_visible()
    for tab in ("API keys", "Agent configuration"):
        expect(drawer.get_by_role("tab", name=tab, exact=True)).to_be_visible()
    drawer.get_by_role("tab", name="Agent configuration", exact=True).click()
    expect(drawer.get_by_test_id("agent-models-section")).to_be_visible(timeout=15000)
    _close_header_drawer(page, drawer, "API Settings", "data-curio-settings-drawer")
