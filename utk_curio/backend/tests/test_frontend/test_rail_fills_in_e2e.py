"""Playwright E2E: the left rail's palettes open while the rail fills in.

The regression guard for #994.

**What happened.** The left rail is drawn before the package registry answers.
Its built-in tiles are descriptors from ``GET /api/packages``
(``registry/packagesClient.ts``), so after every load the tile block is only
its "Built-in" header for a moment. Then the tiles arrive and push the Node,
Data, Agent and Model Catalog triggers about 240 px down.

``open_tools_palette`` clicked its trigger with ``force=True``, which turns off
Playwright's stable and hit-target checks. When the tiles landed after
Playwright had aimed at the Data Catalog trigger but before it pressed, the
press landed on the Data Pool tile and the palette stayed closed.
``test_dataset_palette.py`` then timed out waiting for the palette after its
second reload. Both CI failure screenshots show every palette closed, with the
Data Pool tile's tooltip up under the resting pointer.

**What these tests do.**

* The first holds the built-in tiles back and lets them in the moment the
  pointer reaches the Data Catalog trigger. So the rail fills in between aiming
  and pressing on every run, on any machine. The palette must still open, and
  the press that opens it must be on the trigger.
* The second covers the other half. A palette opened while ``GET
  /api/packages`` is parked stays open once the tiles land. So the app keeps
  the palette's state, and the click alone was at fault.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_rail_fills_in_e2e.py -v
"""
from __future__ import annotations

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

#: Any built-in tile. There is none until ``GET /api/packages`` has answered.
TILE = '#tools-menu [id^="tile-"]'

#: Hides every built-in tile, which leaves the tile block as it is before the
#: registry answers, and lets the tiles back in on the first pointer move over
#: the Data Catalog trigger. Playwright's click moves the pointer, then presses,
#: so the rail fills in after the aim and before the press, which is the worst
#: moment the registry can land. ``window.__curioRailRace`` records whether the
#: aimed point was still on the trigger once the tiles were in, and the title of
#: what each press landed on.
HOLD_TILES_UNTIL_THE_POINTER_ARRIVES_JS = """() => {
    const rail = document.querySelector('#tools-menu');
    const tile = document.querySelector('#tools-menu [id^="tile-"]');
    const trigger = document.querySelector('#datasets-palette button[title="Open dataset palette"]');
    if (!rail || !tile || !trigger) return false;
    let block = tile;
    while (block.parentElement && block.parentElement !== rail) block = block.parentElement;
    if (block.parentElement !== rail) return false;
    // Everything in the tile block after its "Built-in" header comes with the registry.
    const late = Array.from(block.children).slice(1);
    late.forEach((el) => { el.style.display = 'none'; });
    const race = { filled: false, aimStillOnTrigger: null, presses: [] };
    window.__curioRailRace = race;
    const fillIn = (event) => {
        if (!(event.target instanceof Node) || !trigger.contains(event.target)) return;
        window.removeEventListener('pointermove', fillIn, true);
        late.forEach((el) => { el.style.display = ''; });
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


def test_the_data_catalog_opens_when_the_rail_fills_in_under_the_pointer(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The palette opens even when the tiles land between aiming and pressing."""
    _enter_owner_canvas(
        page, app_frontend, current_server,
        name="Rail Racer", username="rail_racer", project_name="Rail Race",
    )

    # The registry has answered, so the rail is whole and its geometry is final.
    expect(page.locator(TILE).first).to_be_visible(timeout=30000)
    trigger = page.locator(OPEN_TRIGGER)
    whole = trigger.bounding_box()
    # Start away from the rail, so the click's own move is the first to reach
    # the trigger.
    page.mouse.move(900, 500)

    assert page.evaluate(HOLD_TILES_UNTIL_THE_POINTER_ARRIVES_JS), (
        "could not find the rail's tile block through its built-in tiles"
    )
    bare = trigger.bounding_box()
    assert whole and bare
    assert bare["y"] < whole["y"] - 100, (
        "holding the tiles back did not move the Data Catalog trigger up "
        f"(y {whole['y']:.0f} -> {bare['y']:.0f}), so the rail has nothing to fill in"
    )

    try:
        panel = open_tools_palette(page, "datasets")
    except PlaywrightTimeoutError as error:
        race = page.evaluate("() => window.__curioRailRace")
        raise AssertionError(
            "the Dataset palette never opened: the rail filled in as the pointer "
            f"reached the Data Catalog trigger, and the press landed on {race['presses']}"
        ) from error

    # Prove the hazard was live: the tiles came in under the pointer and moved
    # the trigger away from where the click had aimed.
    race = page.evaluate("() => window.__curioRailRace")
    assert race["filled"], (
        "the pointer never reached the trigger, so the rail never filled in under it"
    )
    assert race["aimStillOnTrigger"] is False, (
        "the rail filled in but the trigger was still under the aimed point, so "
        "this test raced nothing"
    )
    assert race["presses"] and race["presses"][-1] == "Open dataset palette", (
        f"the palette opened, but the presses landed on {race['presses']}"
    )
    expect(panel).to_be_visible()
    opened = page.locator(CLOSE_TRIGGER).bounding_box()
    assert opened and abs(opened["y"] - whole["y"]) < 2, (
        f"the trigger should be back where the whole rail puts it, y {whole['y']:.0f}"
    )


def test_a_palette_opened_before_the_rail_fills_in_stays_open(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The tiles landing under an open palette leave it open."""
    _enter_owner_canvas(
        page, app_frontend, current_server,
        name="Rail Waiter", username="rail_waiter", project_name="Rail Fills In",
    )
    # Let this load's registry calls finish first, so every call parked below
    # belongs to the reload.
    expect(page.locator(TILE).first).to_be_visible(timeout=30000)

    # Park the registry's calls instead of delaying them by a fixed amount, as
    # test_package_palette_action_race_e2e does with the catalog. Every call is
    # parked until the release, and any call made after it goes straight
    # through. Matched on the path, so ``/api/packages/catalog`` is never held.
    held: list = []
    released = {"yes": False}

    def _hold_registry(route):
        if released["yes"]:
            route.continue_()
        else:
            held.append(route)

    def _release_registry():
        released["yes"] = True
        while held:
            route = held.pop()
            try:
                route.continue_()
            except Exception as exc:  # a request the page already abandoned
                print(f"[rail] parked route could not be continued: {exc}")

    page.route(
        lambda url: urlparse(url).path.endswith("/api/packages"),
        _hold_registry,
    )
    try:
        page.reload()
        page.wait_for_load_state("domcontentloaded")
        trigger = page.locator(OPEN_TRIGGER)
        expect(trigger).to_be_visible(timeout=30000)
        # The rail is drawn and the registry has not answered: no tile yet.
        expect(page.locator(TILE)).to_have_count(0)
        bare = trigger.bounding_box()

        panel = open_tools_palette(page, "datasets")
        assert held, "no GET /api/packages was parked, so the rail may have filled in already"

        _release_registry()
        expect(page.locator(TILE).first).to_be_visible(timeout=30000)

        opened = page.locator(CLOSE_TRIGGER)
        whole = opened.bounding_box()
        assert bare and whole
        assert whole["y"] > bare["y"] + 100, (
            "the tiles did not push the Data Catalog trigger down "
            f"(y {bare['y']:.0f} -> {whole['y']:.0f}), so nothing moved under the open palette"
        )
        expect(panel).to_be_visible()
        expect(opened).to_have_attribute("aria-expanded", "true")
    finally:
        _release_registry()
