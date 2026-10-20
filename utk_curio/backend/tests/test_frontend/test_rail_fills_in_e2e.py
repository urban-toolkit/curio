"""Playwright E2E: the left rail's palettes while the package registry answers.

The regression guard for #994.

**What happened.** The left rail is drawn before the package registry answers
(``GET /api/packages``, ``registry/packagesClient.ts``), and the built-in
tiles are descriptors from that answer. While the tiles sat in the rail
itself, each load filled the rail in about 240 px after it was drawn, which
pushed the Node, Data, Agent and Model Catalog triggers down.
``open_tools_palette`` clicked its trigger with ``force=True``, which turns off
Playwright's stable and hit-target checks, so a press aimed at the Data Catalog
trigger just before the tiles landed pressed the Data Pool tile, and the
palette stayed closed. ``test_dataset_palette.py`` then timed out waiting for
the palette after its second reload.

The tiles are in the rail's Built-in palette, which opens beside the rail as
the catalog palettes do (owner, 2026-10-20). The registry's answer changes the
Built-in trigger's count, and moves no trigger.

**What these tests do.**

* The first holds the click to a trigger that moves between aiming and
  pressing. The rail moves the triggers 240 px down, as the tiles did, the
  moment the pointer reaches the Data Catalog trigger. The palette must still
  open, and the press that opens it must be on the trigger.
* The second holds the registry's answer back, opens the Data Catalog palette
  and lets the answer in: no trigger moves, and the palette stays open.
* The third opens the Built-in palette while the answer is held back: it says
  its nodes are loading, fills in with the tiles when the answer lands, and
  stays open.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_rail_fills_in_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from .utils import (
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The Data Catalog trigger while its palette is closed, and once it is open.
OPEN_TRIGGER = '#datasets-palette button[title="Open dataset palette"]'
CLOSE_TRIGGER = '#datasets-palette button[title="Close dataset palette"]'

#: The Built-in trigger, open or closed, and the Built-in palette's closing one.
BUILTIN_TRIGGER = '#builtin-palette button[title$="built-in palette"]'
BUILTIN_CLOSE_TRIGGER = '#builtin-palette button[title="Close built-in palette"]'

#: The Built-in trigger's text, its count then its label: no node until the
#: registry has answered, and some once it has.
UNANSWERED = re.compile(r"^\s*0\s*Built-in\s*$")
ANSWERED = re.compile(r"^\s*[1-9]\d*\s*Built-in\s*$")

#: Any built-in tile. There is none until ``GET /api/packages`` has answered and
#: the Built-in palette is open.
TILE = '#tools-menu [id^="tile-"]'

#: How far the triggers move when the pointer arrives: the height the tiles
#: added to the rail.
LATE_BLOCK_PX = 240

#: Moves the rail's triggers ``LATE_BLOCK_PX`` down on the first pointer move
#: over the Data Catalog trigger. Playwright's click moves the pointer, then
#: presses, so the triggers move after the aim and before the press, which is
#: the worst moment for a move. ``window.__curioRailRace`` records whether the
#: aimed point was still on the trigger once they had moved, and the title of
#: what each press landed on.
MOVE_THE_TRIGGERS_WHEN_THE_POINTER_ARRIVES_JS = """(px) => {
    const rail = document.querySelector('#tools-menu');
    const trigger = document.querySelector('#datasets-palette button[title="Open dataset palette"]');
    if (!rail || !trigger) return false;
    const race = { filled: false, aimStillOnTrigger: null, presses: [] };
    window.__curioRailRace = race;
    const fillIn = (event) => {
        if (!(event.target instanceof Node) || !trigger.contains(event.target)) return;
        window.removeEventListener('pointermove', fillIn, true);
        rail.style.paddingTop = px + 'px';
        race.filled = true;
        const now = document.elementFromPoint(event.clientX, event.clientY);
        race.aimStillOnTrigger = Boolean(now && trigger.contains(now));
    };
    window.addEventListener('pointermove', fillIn, true);
    window.addEventListener('pointerdown', (event) => {
        const named = event.target instanceof Element ? event.target.closest('[title]') : null;
        race.presses.push(named ? named.getAttribute('title') : String(event.target && event.target.nodeName));
    }, true);
    return true;
}"""

#: The top and height of each palette trigger and of Run all, by root.
TRIGGER_ROWS_JS = """() => {
    const rows = {};
    for (const sel of ['#builtin-palette', '#packages-palette', '#datasets-palette',
                       '#agents-palette', '#models-palette']) {
        const trigger = document.querySelector(sel + ' button[title*="palette"]');
        if (trigger) {
            const box = trigger.getBoundingClientRect();
            rows[sel] = [Math.round(box.top), Math.round(box.height)];
        }
    }
    const runAll = document.querySelector('#tools-menu button[aria-label="Run all nodes"]');
    if (runAll) {
        const box = runAll.getBoundingClientRect();
        rows['run all'] = [Math.round(box.top), Math.round(box.height)];
    }
    return rows;
}"""


def _enter_owner_canvas(page, app_frontend, current_server, *, name, username, project_name):
    require_user_auth()
    require_project_page()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=username,
        project_name=project_name,
    )
    require_owner_view(page)


class _ParkedRegistry:
    """Parks ``GET /api/packages`` until released, as
    test_package_palette_action_race_e2e does with the catalog, instead of
    delaying it by a fixed amount. Every call is parked until the release, and
    any call made after it goes straight through. Matched on the path, so
    ``/api/packages/catalog`` is never held."""

    def __init__(self, page):
        self.held: list = []
        self.released = False
        page.route(lambda url: urlparse(url).path.endswith("/api/packages"), self._hold)

    def _hold(self, route):
        if self.released:
            route.continue_()
        else:
            self.held.append(route)

    def release(self):
        self.released = True
        while self.held:
            route = self.held.pop()
            try:
                route.continue_()
            except Exception as exc:  # a request the page already abandoned
                print(f"[rail] parked route could not be continued: {exc}")


def _reload_with_the_registry_parked(page):
    """Reload with ``GET /api/packages`` parked, and wait for the rail.

    The caller has let the first load's registry calls finish, so every call
    parked here belongs to the reload."""
    parked = _ParkedRegistry(page)
    page.reload()
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator(OPEN_TRIGGER)).to_be_visible(timeout=30000)
    # The rail is drawn and the registry has not answered: no built-in node.
    expect(page.locator(BUILTIN_TRIGGER)).to_have_text(UNANSWERED)
    return parked


def test_the_data_catalog_opens_when_the_rail_fills_in_under_the_pointer(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The palette opens even when its trigger moves between aiming and pressing."""
    _enter_owner_canvas(
        page, app_frontend, current_server,
        name="Rail Racer", username="rail_racer", project_name="Rail Race",
    )

    # The registry has answered, so the rail's geometry is final.
    expect(page.locator(BUILTIN_TRIGGER)).to_have_text(ANSWERED, timeout=30000)
    trigger = page.locator(OPEN_TRIGGER)
    before = trigger.bounding_box()
    assert before, "the Data Catalog trigger has no layout box"
    # Start away from the rail, so the click's own move is the first to reach
    # the trigger.
    page.mouse.move(900, 500)

    assert page.evaluate(MOVE_THE_TRIGGERS_WHEN_THE_POINTER_ARRIVES_JS, LATE_BLOCK_PX), (
        "could not find the rail and its Data Catalog trigger"
    )

    try:
        panel = open_tools_palette(page, "datasets")
    except PlaywrightTimeoutError as error:
        race = page.evaluate("() => window.__curioRailRace")
        raise AssertionError(
            "the Dataset palette never opened: the triggers moved as the pointer "
            f"reached the Data Catalog trigger, and the press landed on {race['presses']}"
        ) from error

    # Prove the hazard was live: the triggers moved under the pointer and took
    # the trigger away from where the click had aimed.
    race = page.evaluate("() => window.__curioRailRace")
    assert race["filled"], (
        "the pointer never reached the trigger, so the triggers never moved under it"
    )
    assert race["aimStillOnTrigger"] is False, (
        "the triggers moved but the trigger was still under the aimed point, so "
        "this test raced nothing"
    )
    assert race["presses"] and race["presses"][-1] == "Open dataset palette", (
        f"the palette opened, but the presses landed on {race['presses']}"
    )
    expect(panel).to_be_visible()
    opened = page.locator(CLOSE_TRIGGER).bounding_box()
    assert opened and opened["y"] > before["y"] + LATE_BLOCK_PX - 40, (
        f"the trigger should be where the moved rail puts it, about "
        f"{LATE_BLOCK_PX} px below y {before['y']:.0f}, not at {opened}"
    )


def test_a_palette_opened_before_the_registry_answers_stays_open_and_no_trigger_moves(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The registry's answer under an open palette leaves it open, and moves no trigger."""
    _enter_owner_canvas(
        page, app_frontend, current_server,
        name="Rail Waiter", username="rail_waiter", project_name="Rail Fills In",
    )
    # Let this load's registry calls finish first, so every call parked below
    # belongs to the reload.
    expect(page.locator(BUILTIN_TRIGGER)).to_have_text(ANSWERED, timeout=30000)

    parked = None
    try:
        parked = _reload_with_the_registry_parked(page)
        before = page.evaluate(TRIGGER_ROWS_JS)
        assert len(before) == 6, f"expected five palette triggers and Run all, found {before}"

        panel = open_tools_palette(page, "datasets")
        assert parked.held, "no GET /api/packages was parked, so the registry may have answered already"

        parked.release()
        expect(page.locator(BUILTIN_TRIGGER)).to_have_text(ANSWERED, timeout=30000)

        after = page.evaluate(TRIGGER_ROWS_JS)
        moved = {
            sel: (before.get(sel), row) for sel, row in after.items()
            if before.get(sel) is None
            or abs(row[0] - before[sel][0]) > 1 or abs(row[1] - before[sel][1]) > 1
        }
        assert not moved, (
            f"the registry's answer moved the rail's triggers (before, after): {moved}"
        )
        expect(panel).to_be_visible()
        expect(page.locator(CLOSE_TRIGGER)).to_have_attribute("aria-expanded", "true")
    finally:
        if parked is not None:
            parked.release()


def test_the_built_in_palette_opened_before_the_registry_answers_fills_in_and_stays_open(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The tiles land in an open Built-in palette and leave it open."""
    _enter_owner_canvas(
        page, app_frontend, current_server,
        name="Rail Filler", username="rail_filler", project_name="Palette Fills In",
    )
    expect(page.locator(BUILTIN_TRIGGER)).to_have_text(ANSWERED, timeout=30000)

    parked = None
    try:
        parked = _reload_with_the_registry_parked(page)
        panel = open_tools_palette(page, "builtin")
        assert parked.held, "no GET /api/packages was parked, so the registry may have answered already"
        expect(panel).to_contain_text("Loading built-in nodes")
        expect(page.locator(TILE)).to_have_count(0)

        parked.release()
        expect(page.locator(TILE).first).to_be_visible(timeout=30000)
        expect(panel).to_be_visible()
        expect(page.locator(BUILTIN_CLOSE_TRIGGER)).to_have_attribute("aria-expanded", "true")
        expect(panel).not_to_contain_text("Loading built-in nodes")
        # Every tile is in the panel, none in the rail beside it.
        in_panel = panel.locator('[id^="tile-"]').count()
        assert in_panel > 0 and page.locator(TILE).count() == in_panel, (
            f"{page.locator(TILE).count()} tiles in the rail, {in_panel} of them in the Built-in panel"
        )
    finally:
        if parked is not None:
            parked.release()
