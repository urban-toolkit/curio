"""The left rail must fit a short screen, with Run all reachable.

The rail stacks the built-in tile block, then the Node, Data and Agent Catalog
triggers, then "Run all nodes". Nothing constrained its height, so on a short
viewport the Run-all button was simply drawn past the fold - and because no
ancestor scrolled, there was no way to reach it. A 1366x768 laptop leaves about
660px of viewport after browser chrome, which is where this test runs.

It was found by the feature-tour recorder, whose ``_play_all`` died on
"Element is outside of the viewport" in three separate scenes, and confirmed
independently of it: a single-scene run with none of the agent scenes loaded
reproduced it exactly.

Deliberately its own context rather than the suite's shared 1280x720 one: the
whole point is a height the rest of the suite never exercises.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_tools_rail_fits.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_login,
)

if TYPE_CHECKING:
    pass

#: ~1366x768 minus browser chrome: the smallest screen worth supporting, and
#: the one the bug made unusable.
SHORT_VIEWPORT = {"width": 1280, "height": 660}

RUN_ALL = '#tools-menu button[title="Run all nodes"]'

#: The built-in tile block, found through a tile rather than by class name:
#: CSS-Modules hashes `.menuStyle` into something opaque, so a `[class*=…]`
#: selector matches nothing in a real build.
TILE_BLOCK_JS = """() => {
    const tile = document.querySelector('#step-loading');
    const rail = document.querySelector('#tools-menu');
    if (!tile || !rail) return null;
    let el = tile;
    while (el.parentElement && el.parentElement !== rail) el = el.parentElement;
    return el.parentElement === rail ? el : null;
}"""


def _one_node_spec() -> dict:
    return {
        "dataflow": {
            "name": "RailFits",
            "task": "",
            "nodes": [
                {
                    "id": "rail-fits-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _canvas_at_short_viewport(browser, frontend_server: str, current_server: str):
    context = browser.new_context(viewport=SHORT_VIEWPORT)
    page = context.new_page()
    page.emulate_media(reduced_motion="reduce")
    session = stub_db_login(
        page,
        frontend_url=frontend_server,
        backend_url=current_server,
        username="rail_fits",
        name="Rail Fits",
        project_name="RailFits",
        project_spec=_one_node_spec(),
    )
    page.goto(f"{frontend_server}/dataflow/{session['project']['id']}")
    page.wait_for_load_state("domcontentloaded")
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    require_owner_view(page)
    return context, page


def test_run_all_is_reachable_on_a_short_screen(
    browser, frontend_server: str, current_server: str
):
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        button = page.locator(RUN_ALL)
        expect(button).to_be_visible(timeout=20000)

        # In the viewport, not merely in the DOM. This is the assertion the bug
        # would have failed: the button rendered, it just sat below the fold.
        box = button.bounding_box()
        assert box, "Run all has no layout box"
        assert box["y"] + box["height"] <= SHORT_VIEWPORT["height"], (
            f"Run all ends at y={box['y'] + box['height']:.0f}, past the "
            f"{SHORT_VIEWPORT['height']}px fold - the rail has outgrown the "
            "viewport again and nothing scrolls to it"
        )

        # And it is genuinely clickable, not just on screen. A real click (no
        # force, no dispatch) is what "outside of the viewport" used to refuse.
        button.click()
    finally:
        context.close()


def test_the_tile_block_absorbs_the_overflow(
    browser, frontend_server: str, current_server: str
):
    """The rail is capped, and the growing part is the part that scrolls."""
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        rail = page.locator("#tools-menu")
        rail_box = rail.bounding_box()
        assert rail_box, "#tools-menu has no layout box"
        assert rail_box["y"] + rail_box["height"] <= SHORT_VIEWPORT["height"], (
            "the whole rail should fit the viewport once it is capped"
        )

        # The tile block is the one element allowed to overflow, and it must do
        # so by scrolling rather than by pushing its siblings off screen.
        overflow = page.evaluate(
            "(find) => { const el = eval(find)(); return el ? {"
            " scrollable: el.scrollHeight > el.clientHeight,"
            " overflowY: getComputedStyle(el).overflowY } : null; }",
            TILE_BLOCK_JS,
        )
        assert overflow, "could not find the built-in tile block in the rail"
        assert overflow["overflowY"] == "auto", (
            f"the tile block should scroll, got overflow-y: {overflow['overflowY']}"
        )
    finally:
        context.close()


def test_opening_the_agent_palette_does_not_widen_the_rail(
    browser, frontend_server: str, current_server: str
):
    """The Agents panel opens beside the rail, like its two peers.

    Its CSS was never converted when the palettes moved into the rail, so the
    panel stayed an in-flow sibling: opening it stretched the rail from ~56px to
    ~444px and dragged the Built-in box and Run-all out to match, and the panel
    hung down from the lowest trigger so its own footer fell off screen.
    """
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        rail = page.locator("#tools-menu")
        before = rail.bounding_box()
        assert before, "#tools-menu has no layout box"

        open_tools_palette(page, "agents")
        after = rail.bounding_box()
        assert after, "#tools-menu lost its layout box"
        assert after["width"] <= before["width"] + 1, (
            f"opening the agent palette widened the rail from "
            f"{before['width']:.0f}px to {after['width']:.0f}px; its panel is "
            "in flow again instead of positioned against the dock"
        )

        # The footer is the palette's own way into the drawer, and it is what
        # sat below the fold while the panel hung off its trigger.
        footer = page.locator(
            '#agents-palette button:has-text("Browse Agent Catalog")'
        )
        expect(footer).to_be_visible(timeout=15000)
        box = footer.bounding_box()
        assert box, "the palette footer has no layout box"
        assert box["y"] + box["height"] <= SHORT_VIEWPORT["height"], (
            f"'Browse Agent Catalog +' ends at y={box['y'] + box['height']:.0f}, "
            f"past the {SHORT_VIEWPORT['height']}px fold"
        )
    finally:
        context.close()


#: The three palettes' roots. They are siblings of equal standing in the rail and
#: should be indistinguishable apart from their icon, label and count.
PALETTES = (
    ("Node Catalog", "#packages-palette"),
    ("Data Catalog", "#datasets-palette"),
    ("Agent Catalog", "#agents-palette"),
)

#: Measured through the rendered DOM rather than by class name: CSS-Modules
#: hashes every class, so `[class*="trigger"]` matches nothing in a real build.
#: The trigger is found by its `title`, which ToolsMenu gives all three.
TRIGGER_METRICS_JS = """(sel) => {
    const root = document.querySelector(sel);
    if (!root) return null;
    const trigger = root.querySelector('button[title*="palette"]');
    if (!trigger) return null;
    const cs = getComputedStyle(trigger);
    const box = trigger.getBoundingClientRect();
    const column = trigger.parentElement;
    return {
        width: Math.round(box.width),
        height: Math.round(box.height),
        padding: cs.padding,
        boxSizing: cs.boxSizing,
        borderRadius: cs.borderRadius,
        columnWidth: column ? Math.round(column.getBoundingClientRect().width) : null,
        columnGap: column ? getComputedStyle(column).gap : null,
        // Two rows - icon/count/chevron, then the label - not four stacked
        // children. This is what keeps all three the same height.
        rows: trigger.children.length,
    };
}"""


def test_the_three_palette_triggers_are_the_same_size(
    browser, frontend_server: str, current_server: str
):
    """Node, Data and Agent must look like one another in the rail.

    They drifted because each owns its own stylesheet: `paletteShell.module.css`
    calls itself the shared chrome but is composed by the Agents palette alone,
    and it still carried the geometry of the narrow icon-only rail it was written
    for. The Agent trigger rendered 56x102 against its peers' 102x50 - half the
    width, and taller because the label wrapped and its four children stacked
    where the peers group three of them into a row.
    """
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        measured = {}
        for name, sel in PALETTES:
            metrics = page.evaluate(TRIGGER_METRICS_JS, sel)
            assert metrics, f"no trigger found for {name} ({sel})"
            measured[name] = metrics

        reference_name, reference = next(iter(measured.items()))
        for name, metrics in measured.items():
            assert metrics == reference, (
                f"the {name} trigger differs from {reference_name}:\n"
                f"  {name}: {metrics}\n"
                f"  {reference_name}: {reference}"
            )
    finally:
        context.close()


def test_the_three_palette_panels_open_in_the_same_place(
    browser, frontend_server: str, current_server: str
):
    """Each panel opens beside the rail, anchored to the dock - not to its own
    trigger. The Agents panel used to hang off its trigger, which is the lowest
    of the three, so it started ~500px further down and ran off the bottom."""
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        boxes = {}
        for kind, sel in (
            ("packages", "#packages-palette"),
            ("datasets", "#datasets-palette"),
            ("agents", "#agents-palette"),
        ):
            open_tools_palette(page, kind)
            box = page.evaluate(
                """(sel) => {
                    const p = document.querySelector(sel + ' [role="region"]');
                    if (!p) return null;
                    const b = p.getBoundingClientRect();
                    return { x: Math.round(b.x), y: Math.round(b.y),
                             w: Math.round(b.width),
                             position: getComputedStyle(p).position };
                }""",
                sel,
            )
            assert box, f"the {kind} palette panel did not open"
            boxes[kind] = box

        reference_kind, reference = next(iter(boxes.items()))
        for kind, box in boxes.items():
            assert box == reference, (
                f"the {kind} panel opens somewhere else than {reference_kind}:\n"
                f"  {kind}: {box}\n"
                f"  {reference_kind}: {reference}"
            )
        assert reference["position"] == "absolute", (
            "panels must be positioned against the dock, not left in flow - an "
            f"in-flow panel widens the rail; got position: {reference['position']}"
        )
    finally:
        context.close()


def test_the_three_panel_headers_place_their_title_alike(
    browser, frontend_server: str, current_server: str
):
    """The panel title sits at the same inset in all three palettes.

    The shell centred it while both peers pinned theirs to the 10px left inset,
    so switching palettes slid the title ~150px sideways. Asserted on the title's
    measured offset from the panel's left edge, not on `justify-content` alone:
    the title is a shrink-to-fit flex item, so its own `text-align` is inert and
    changing only that would look like a fix while moving nothing.
    """
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        insets = {}
        for kind, sel in (
            ("packages", "#packages-palette"),
            ("datasets", "#datasets-palette"),
            ("agents", "#agents-palette"),
        ):
            open_tools_palette(page, kind)
            insets[kind] = page.evaluate(
                """(sel) => {
                    const panel = document.querySelector(sel + ' [role="region"]');
                    if (!panel) return null;
                    const header = panel.firstElementChild;
                    const title = header && header.firstElementChild;
                    if (!title) return null;
                    return {
                        inset: Math.round(
                            title.getBoundingClientRect().x
                            - panel.getBoundingClientRect().x
                        ),
                        justify: getComputedStyle(header).justifyContent,
                    };
                }""",
                sel,
            )
            assert insets[kind], f"no panel header found for {kind}"

        reference_kind, reference = next(iter(insets.items()))
        for kind, got in insets.items():
            assert got == reference, (
                f"the {kind} panel title sits differently from {reference_kind}:\n"
                f"  {kind}: {got}\n  {reference_kind}: {reference}"
            )
    finally:
        context.close()


def test_escape_does_not_close_any_palette(
    browser, frontend_server: str, current_server: str
):
    """A palette closes on its own trigger, not on Escape.

    Both peers refuse Escape in so many words - "No Escape / outside-click
    dismissal on purpose" - so that browsing the canvas never collapses the
    palette you are dragging out of. The Agents palette carried a listener that
    did close it, directly above a comment claiming it behaved like the other
    two.
    """
    require_project_page()
    require_user_auth()
    context, page = _canvas_at_short_viewport(
        browser, frontend_server, current_server
    )
    try:
        for kind, sel in (
            ("packages", "#packages-palette"),
            ("datasets", "#datasets-palette"),
            ("agents", "#agents-palette"),
        ):
            open_tools_palette(page, kind)
            panel = page.locator(f'{sel} [role="region"]')
            expect(panel).to_be_visible(timeout=15000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            expect(panel).to_be_visible(
                timeout=5000,
            ), f"Escape collapsed the {kind} palette"
    finally:
        context.close()
