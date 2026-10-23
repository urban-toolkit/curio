"""Playwright E2E: one Curio tooltip for every hover.

Every hover in Curio is one tooltip, drawn over the page in a portal on
``document.body`` (``components/tooltip/TooltipLayer.tsx``) and placed from its
target's box on screen. So it is the same size at every canvas zoom, no card
clips it, and nothing else draws one: no native ``title``, no Bootstrap
tooltip, no Monaco hover. Checked where jsdom has no layout to read:

1. Example 26's join at canvas zoom 0.5, 1 and 2: its Delete node button, its
   ``input_1`` tag under Inputs, and the avatar of an agent attached to it.
   Each time one ``[role=tooltip]`` shows, outside the canvas's viewport and
   the app's root, 6 px above its target and centered on it (below it when
   there is no room above), with the same width and height at every zoom. A
   close-up frame of each: the tooltip and its target, with a margin.
2. A chip in the join's code and one in the chart's spec, both
   ``[!! input_1 !!]``, at zoom 1 and 2: the same tooltip box at both, and no
   Monaco hover on screen. The same chips when Monaco draws their line again
   as the pointer lands on them, which Monaco reports as a leave: the
   tooltip shows all the same.
3. The keyboard: Tab onto Delete node shows its tooltip, Escape hides it, and
   a mouse click on a button shows none after it.
4. A bar of example 02's zip chart: the tooltip at the pointer says what the
   chart element's ``data-tooltip`` says, the bar's fields, and the chart
   carries no ``title``.
5. No element with a ``title`` and no SVG ``<title>``: on the canvas with 26
   open, its editors, their Inputs and the tool rail's palettes open; on the
   Data Catalog and Node Catalog pages, a card's details open; on a
   dashboard; on API Settings. A title a library draws and Curio cannot take
   off goes in ``LIBRARY_TITLES``, with its reason.

The pointer is moved with ``page.mouse`` to an element's middle: a locator's
hover fails its actionability check under React Flow's pane. No test here
needs a GPU: the map in example 26 stays undrawn on a CPU runner, and nothing
reads it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_tooltips_e2e.py -v
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

from .test_dashboard_page_e2e import _chart_drew, _open_dashboard, _pinned_and_saved
from .test_selection_tags_e2e import ZIP_BARS_ID, ZIPS_EXAMPLE, _UNSCROLL_JS
from .test_widget_tags_e2e import _open_tab
from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    NODE_ONLY_AGENT_NAME,
    REPO_ROOT,
    _wait_for_reactflow_ready,
    api_json,
    assert_in_view,
    box_middle,
    drawing_selector,
    editor_chip_box,
    element_box,
    ensure_node_only_agent,
    frame_node,
    hover_chip_until_tooltip_says,
    mark_point,
    monaco_hovers,
    move_pointer_away,
    no_tooltip,
    node_locator,
    one_tooltip,
    open_strip_category,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    rest_pointer_on,
    run_all_and_wait,
    save_workflow_test_screenshot,
    stub_db_login,
    stub_login_and_enter_workflow,
    tooltip_close_up,
    tooltip_saying,
    tooltips_on_screen,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

SEVERAL_INPUTS = Path(REPO_ROOT) / "docs" / "examples" / "26-several-inputs.json"
#: Example 26's join, which reads three inputs, the second a tuple, and the
#: chart that reads the join as its input_1.
JOIN = "several-join"
CHART = "several-chart"
#: The canvas zooms a tooltip has to look the same at.
ZOOMS = (0.5, 1.0, 2.0)
#: The stem of this module's frames.
STEM = "tooltips"
#: How far apart two sizes may be and still be one, in px.
EDGE_PX = 1.0
#: How far a tooltip may sit from where its rules put it, in px: its box and
#: its target's are each rounded to the pixel on their own.
PLACE_PX = 2.0
#: The gap between a tooltip and its target, or the pointer, in px.
GAP_PX = 6.0
#: How long example 02 may take to run, in ms.
RUN_MS = 180000

#: The join's targets, by name: what the pointer rests on.
TARGETS = {
    "delete-node": f'.react-flow__node[data-id="{JOIN}"] button[aria-label="Delete node"]',
    "input-tag": f'.react-flow__node[data-id="{JOIN}"] [data-widget-strip] [data-input-tag="1"]',
    "agent-badge": f'.react-flow__node[data-id="{JOIN}"] button[aria-label^="Open chat with"]',
}
#: The editors whose ``[!! input_1 !!]`` chip is hovered: (node, tab). The
#: join's code unpacks it; the chart's spec names it as a dataset.
CHIPS = {"code": (JOIN, "code"), "spec": (CHART, "grammar")}
#: Monaco's ``editor.MouseTargetType.CONTENT_TEXT``: the pointer on text.
CONTENT_TEXT = 6

#: Titles a library draws that Curio cannot take off: (a selector the element
#: matches or sits in, why it stays).
LIBRARY_TITLES: list[tuple[str, str]] = [
    (
        ".monaco-editor .cldr",
        "Monaco's own folding control, titled 'Click to collapse the range.' by Monaco: "
        "an editor on a dashboard tile keeps Monaco's look by design (nodeEditorLook), folding included",
    ),
]


# Pan and zoom the canvas so the page point (x, y) lands at the middle of the
# pane, at *zoom*. Returns the view asked for.
_CENTER_JS = r"""({ x, y, zoom }) => {
    const flow = window.__curio_reactFlow;
    const viewport = document.querySelector(".curio-canvas-drop-target .react-flow__viewport");
    if (!flow || !viewport) return null;
    const pane = viewport.parentElement.getBoundingClientRect();
    const at = flow.getViewport();
    // The point in flow units, then the view that puts it at the pane's middle.
    const fx = (x - pane.left - at.x) / at.zoom;
    const fy = (y - pane.top - at.y) / at.zoom;
    const view = { x: pane.width / 2 - fx * zoom, y: pane.height / 2 - fy * zoom, zoom };
    flow.setViewport(view);
    return view;
}"""

# One read of _center's wait: true once React Flow reports the view asked for
# and the canvas draws it, for *reads* reads in a row. A view that got there
# and was moved off is set again, as set_canvas_zoom does.
_VIEW_HELD_JS = r"""({ x, y, zoom, reads }) => {
    const flow = window.__curio_reactFlow;
    const viewport = document.querySelector(".curio-canvas-drop-target .react-flow__viewport");
    if (!flow || !viewport) return false;
    const wait = window.__curio_tooltipView = window.__curio_tooltipView || { held: 0 };
    const at = flow.getViewport();
    const drawn = new DOMMatrixReadOnly(getComputedStyle(viewport).transform);
    const near = (a, b) => Math.abs(a - b) < 0.01;
    const there = near(at.x, x) && near(at.y, y) && near(at.zoom, zoom)
        && near(drawn.e, x) && near(drawn.f, y) && near(drawn.a, zoom) && near(drawn.d, zoom);
    if (there) {
        wait.held += 1;
        return wait.held >= reads;
    }
    if (wait.held > 0) flow.setViewport({ x, y, zoom });
    wait.held = 0;
    return false;
}"""


# Focus the element just before the one *selector* finds among the page's
# focusable elements, in document order, so a Tab reaches it next. Returns
# what was focused, or null.
_FOCUS_BEFORE_JS = r"""(selector) => {
    const target = Array.from(document.querySelectorAll(selector)).find((e) => e.getClientRects().length > 0);
    if (!target) return null;
    const focusable = Array.from(document.querySelectorAll(
        'a[href], button, input, select, textarea, summary, [tabindex], [contenteditable]:not([contenteditable="false"])'))
        .filter((el) => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length > 0);
    const index = focusable.indexOf(target);
    if (index <= 0) return null;
    const before = focusable[index - 1];
    before.focus();
    return before.getAttribute("aria-label") || (before.textContent || "").trim().slice(0, 40) || before.tagName;
}"""

# The chart element's data-tooltip, where Curio's Vega handler writes the
# hovered mark's tooltip, and every title on it or in it.
_CHART_JS = r"""(nodeId) => {
    const el = document.getElementById("vega" + nodeId);
    if (!el) return null;
    const titled = [el, ...el.querySelectorAll("[title]")]
        .filter((e) => e.hasAttribute("title"))
        .map((e) => `${e.tagName.toLowerCase()} title=${JSON.stringify(e.getAttribute("title"))}`);
    return { tooltip: el.getAttribute("data-tooltip"), titled };
}"""

# Every element that would draw a native tooltip, a title attribute or an SVG
# <title>, outside the elements the selectors in *allowed* find; each as a
# line that says what and where it is.
_TITLES_JS = r"""(allowed) => {
    const skip = (el) => allowed.some((selector) => el.closest(selector));
    const name = (el) => {
        const bits = [el.tagName.toLowerCase()];
        if (el.id) bits.push(`#${el.id}`);
        for (const attr of ["class", "data-testid", "aria-label", "data-tooltip"]) {
            if (el.hasAttribute(attr)) bits.push(`${attr}=${JSON.stringify(el.getAttribute(attr).slice(0, 60))}`);
        }
        const node = el.closest(".react-flow__node");
        if (node) bits.push(`in node ${node.getAttribute("data-id")}`);
        return bits.join(" ");
    };
    const found = [];
    for (const el of document.body.querySelectorAll("[title]")) {
        if (!skip(el)) found.push(`${name(el)}: title=${JSON.stringify(el.getAttribute("title"))}`);
    }
    for (const el of document.querySelectorAll("svg title")) {
        if (!skip(el)) found.push(`${name(el.parentElement || el)}: <title>${JSON.stringify((el.textContent || "").trim())}`);
    }
    return found;
}"""

# For the first move onto a span of the chip `[!! inner !!]` in the editor of
# the node *nodeId*: a decoration on the chip's line, added in the move's
# capture on the document, which Monaco holds to draw in its next frame. Its
# hit test of that same move draws it first (view.js), so the line is drawn
# again under the pointer and the move's span leaves the page, as when any
# change lands on the line as the pointer does. Records what Monaco reports
# from then on. Returns the chip's line, or 0 with no such editor or chip.
_REDRAW_ON_ARRIVAL_JS = r"""({ nodeId, inner }) => {
    const card = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const host = card && Array.from(card.querySelectorAll(".monaco-editor")).find((el) => el.getClientRects().length > 0);
    const editor = host && ((window.monaco && window.monaco.editor.getEditors()) || []).find((e) => host.contains(e.getDomNode()));
    if (!editor) return 0;
    const written = `[!! ${inner} !!]`;
    const line = editor.getModel().getValue().split("\n").findIndex((text) => text.includes(written)) + 1;
    if (line < 1) return 0;
    const chipOf = (el) => (el && el.closest ? el.closest(".curio-widget-ref, .curio-widget-ref-problem") : null);
    const seen = { span: null, decorated: false, moves: [], leaves: 0, leftAfterMove: false };
    const onMove = (event) => {
        const span = chipOf(event.target);
        if (seen.span || !span || !host.contains(span)) return;
        seen.span = span;
        editor.createDecorationsCollection([{
            range: { startLineNumber: line, startColumn: 1, endLineNumber: line, endColumn: 2 },
            options: { inlineClassName: "curio-test-redrawn" },
        }]);
        seen.decorated = true;
    };
    document.addEventListener("mousemove", onMove, { capture: true });
    const subscriptions = [
        editor.onMouseMove((e) => {
            if (seen.span) seen.moves.push({ type: e.target.type, line: e.target.position ? e.target.position.lineNumber : null });
        }),
        editor.onMouseLeave(() => {
            seen.leaves += 1;
            if (seen.moves.length) seen.leftAfterMove = true;
        }),
    ];
    window.__curio_redrawOnArrival = {
        read: ({ x, y }) => {
            const under = document.elementFromPoint(x, y);
            return {
                line,
                decorated: seen.decorated,
                moves: seen.moves,
                leaves: seen.leaves,
                leftAfterMove: seen.leftAfterMove,
                spanOffPage: seen.span ? !seen.span.isConnected : null,
                pointerOnChip: !!(under && host.contains(under) && chipOf(under)),
            };
        },
        stop: () => {
            document.removeEventListener("mousemove", onMove, { capture: true });
            subscriptions.forEach((s) => s.dispose());
        },
    };
    return line;
}"""

# What the redraw armed by _REDRAW_ON_ARRIVAL_JS saw, the pointer at (x, y),
# and it stops.
_REDRAW_READ_JS = r"""({ x, y }) => {
    const armed = window.__curio_redrawOnArrival;
    if (!armed) return null;
    const seen = armed.read({ x, y });
    armed.stop();
    return seen;
}"""


def _open_26(page, app_frontend, current_server: str, *, username: str, agent: bool = False) -> dict:
    """Open example 26 as a new dataflow and wait for every node; with *agent*,
    the node-only agent is attached to the join first. Returns the dataflow."""
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(SEVERAL_INPUTS.read_text(encoding="utf-8"))
    login = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username=username,
        name="Tooltips",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    project_id = login["project"]["id"]
    if agent:
        # Installed and attached over HTTP, as test_agent_chat_e2e.py does:
        # the browser's part starts at the badge.
        coord = ensure_node_only_agent(current_server, login["token"])
        base = f"{current_server}/api/agents/projects/{project_id}"
        api_json(f"{base}/install", login["token"], method="POST", payload={"coord": coord})
        api_json(
            f"{base}/attachments", login["token"], method="POST",
            payload={"coord": coord, "target": {"kind": "node", "targetId": JOIN}},
        )
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="attached", timeout=45000)
    _wait_for_reactflow_ready(page)
    return spec["dataflow"]


def _center(page, point: tuple[float, float], zoom: float, *, timeout: float = 15000) -> None:
    """Pan and zoom the canvas so the page point *point* lands at the middle
    of the pane, at *zoom*, and wait until the canvas draws that view."""
    page.evaluate("() => { delete window.__curio_tooltipView; }")
    view = page.evaluate(_CENTER_JS, {"x": point[0], "y": point[1], "zoom": zoom})
    assert view, "the page has no canvas to move"
    try:
        page.wait_for_function(_VIEW_HELD_JS, arg={**view, "reads": 3}, polling=100, timeout=timeout)
    except PlaywrightTimeoutError:
        now = page.evaluate("() => window.__curio_reactFlow && window.__curio_reactFlow.getViewport()")
        raise AssertionError(f"the canvas did not settle at {view} within {timeout:.0f} ms: it shows {now}") from None


def _center_on(page, selector: str, zoom: float) -> dict:
    """The canvas at *zoom*, with the element *selector* finds at the middle
    of the pane; returns its box there."""
    # Twice, in case anything moved once the canvas did.
    for _ in range(2):
        _center(page, box_middle(element_box(page, selector)), zoom)
    return element_box(page, selector)


def _assert_beside_target(tip: dict, what: str) -> None:
    """6 px above its target and centered on it, or below it when there is no
    room above."""
    box, target = tip["box"], tip["target"]
    off = abs(box_middle(box)[0] - box_middle(target)[0])
    above, below = target["top"] - box["bottom"], box["top"] - target["bottom"]
    assert off <= PLACE_PX, f"{what}: the tooltip is {off:.1f} px off its target's middle: {tip}"
    assert min(abs(above - GAP_PX), abs(below - GAP_PX)) <= PLACE_PX, (
        f"{what}: the tooltip is not {GAP_PX:.0f} px above or below its target "
        f"(gap above {above:.1f}, below {below:.1f}): {tip}"
    )


def _assert_at_pointer(tip: dict, point: tuple[float, float], what: str) -> None:
    """Over the pointer's x and 6 px above it, or below it when there is no
    room above: a chart's tooltip goes where the pointer is."""
    (x, y), box = point, tip["box"]
    assert box["left"] - PLACE_PX <= x <= box["right"] + PLACE_PX, (
        f"{what}: the tooltip {box} is not over the pointer's x, {x:.1f}"
    )
    assert min(abs(y - box["bottom"] - GAP_PX), abs(box["top"] - y - GAP_PX)) <= PLACE_PX, (
        f"{what}: the tooltip {box} is not {GAP_PX:.0f} px above or below the pointer's y, {y:.1f}"
    )


def _assert_no_titles(page, where: str) -> None:
    found = page.evaluate(_TITLES_JS, [selector for selector, _ in LIBRARY_TITLES])
    assert not found, (
        f"{where}: {len(found)} element(s) would draw the browser's own tooltip. Each one writes "
        "data-tooltip instead, or, when a library draws it, goes in LIBRARY_TITLES with its reason:\n  "
        + "\n  ".join(found[:80])
    )


def _open_first_details(page, card: str) -> None:
    """Open the first *card*'s details with its View details button."""
    page.locator(card).first.get_by_role("button", name="View details").click(timeout=20000)
    expect(page.get_by_role("dialog").first).to_be_visible(timeout=10000)


@pytest.mark.parametrize("target", list(TARGETS))
def test_a_tooltip_is_the_same_at_every_canvas_zoom(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    target: str,
):
    require_project_page()
    require_user_auth()
    _open_26(
        page, app_frontend, current_server,
        username=f"tooltips_{target.replace('-', '_')}", agent=target == "agent-badge",
    )
    selector = TARGETS[target]
    if target == "input-tag":
        frame_node(page, JOIN, zoom=1.0)
        _open_tab(page, JOIN, "code")
        open_strip_category(page, JOIN, "inputs")
    page.locator(f"{selector}:visible").first.wait_for(state="visible", timeout=30000)

    sizes: list[tuple[float, dict]] = []
    frames_failed: list[str] = []
    for zoom in ZOOMS:
        what = f"{target} at zoom {zoom}"
        box = _center_on(page, selector, zoom)
        rest_pointer_on(page, box, what, avoid=selector)
        tip = one_tooltip(page, what, selector)
        _assert_beside_target(tip, what)
        if target == "delete-node":
            assert tip["text"] == "Delete node", f"{what}: {tip['text']!r}"
        if target == "agent-badge":
            assert NODE_ONLY_AGENT_NAME in tip["text"], f"{what}: {tip['text']!r}"
        sizes.append((zoom, tip["box"]))
        try:
            # The tooltip and its target are the subject: a close-up of them,
            # compared as tightly as a node's.
            save_workflow_test_screenshot(
                page, STEM, test_name=f"{target}-zoom-{round(zoom * 100):03d}",
                fit_reactflow=False, keep_tooltip=True, clip_rect=tooltip_close_up(page, tip),
                pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
                closeup=True,
            )
        except AssertionError as error:
            # Every zoom is measured all the same; the frames' verdict comes last.
            frames_failed.append(f"zoom {zoom}: {error}")

    (first_zoom, first), *rest = sizes
    for zoom, box in rest:
        assert abs(box["width"] - first["width"]) <= EDGE_PX and abs(box["height"] - first["height"]) <= EDGE_PX, (
            f"{target}: the tooltip is {box['width']:.1f} x {box['height']:.1f} px at zoom {zoom}, "
            f"and {first['width']:.1f} x {first['height']:.1f} px at zoom {first_zoom}"
        )
    assert not frames_failed, "\n".join(frames_failed)


@pytest.mark.parametrize("editor", list(CHIPS))
def test_a_chip_in_an_editor_shows_the_same_tooltip_at_zoom_1_and_2(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    editor: str,
):
    require_project_page()
    require_user_auth()
    node_id, tab = CHIPS[editor]
    _open_26(page, app_frontend, current_server, username=f"tooltips_chip_{editor}")
    frame_node(page, node_id, zoom=1.0)
    _open_tab(page, node_id, tab)
    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(state="visible", timeout=30000)

    sizes: list[tuple[float, dict]] = []
    for zoom in (1.0, 2.0):
        what = f"the chip [!! input_1 !!] in {node_id}'s {editor} at zoom {zoom}"
        _center(page, box_middle(editor_chip_box(page, node_id, "input_1")), zoom)
        # The chip's box is read once no tooltip shows, and the pointer moved
        # again until it rests on the chip.
        tip = hover_chip_until_tooltip_says(page, node_id, "input_1", what, ["input_1"])
        assert "input_1" in tip["text"], f"{what}: {tip['text']!r}"
        assert monaco_hovers(page) == 0, f"{what}: Monaco's own hover is on screen too"
        sizes.append((zoom, tip["box"]))

    (_, one), (_, two) = sizes
    assert abs(two["width"] - one["width"]) <= EDGE_PX and abs(two["height"] - one["height"]) <= EDGE_PX, (
        f"the {editor} chip's tooltip is {one['width']:.1f} x {one['height']:.1f} px at zoom 1 "
        f"and {two['width']:.1f} x {two['height']:.1f} px at zoom 2"
    )


@pytest.mark.parametrize("editor", list(CHIPS))
def test_a_chip_whose_line_monaco_draws_again_as_the_pointer_lands_shows_its_tooltip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    editor: str,
):
    # Monaco takes a move whose element is not in the editor for a leave
    # (mouseHandler.js), and its hit test of the move first draws what it
    # holds to draw. So a change that lands on the chip's line as the pointer
    # does takes the move's span off the page, Monaco reports a leave, and the
    # resting pointer sends no move to come back. The tooltip shows all the same.
    require_project_page()
    require_user_auth()
    node_id, tab = CHIPS[editor]
    _open_26(page, app_frontend, current_server, username=f"tooltips_redrawn_{editor}")
    frame_node(page, node_id, zoom=1.0)
    _open_tab(page, node_id, tab)
    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(state="visible", timeout=30000)
    what = f"the chip [!! input_1 !!] in {node_id}'s {editor}, its line drawn again as the pointer lands on it"
    _center(page, box_middle(editor_chip_box(page, node_id, "input_1")), 1.0)

    move_pointer_away(page)
    no_tooltip(page, f"{what}, before the pointer moves onto it", timeout=5000)
    box = editor_chip_box(page, node_id, "input_1")
    assert page.evaluate(_REDRAW_ON_ARRIVAL_JS, {"nodeId": node_id, "inner": "input_1"}), (
        f"{what}: {node_id}'s editor shows no chip [!! input_1 !!]"
    )
    point = assert_in_view(page, *box_middle(box), what)
    page.mouse.move(*point)
    # Monaco's leave comes in the move's own handling: less than the 400 ms
    # a tooltip waits is room enough.
    page.wait_for_timeout(200)
    seen = page.evaluate(_REDRAW_READ_JS, {"x": point[0], "y": point[1]})
    on_text = bool(seen) and any(move["type"] == CONTENT_TEXT and move["line"] == seen["line"] for move in seen["moves"])
    assert on_text and seen["decorated"] and seen["spanOffPage"] and seen["leftAfterMove"] and seen["pointerOnChip"], (
        f"{what}: the setup did not reproduce. The move onto the chip was to draw its line again, take the move's "
        f"span off the page, and have Monaco report a move on the chip's text, then a leave, with the pointer "
        f"still on the chip: {seen}"
    )

    tip = tooltip_saying(page, what, ["input_1"])
    assert monaco_hovers(page) == 0, f"{what}: Monaco's own hover is on screen too: {tip}"


def test_tab_shows_a_tooltip_escape_hides_it_and_a_click_shows_none(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    _open_26(page, app_frontend, current_server, username="tooltips_keyboard")
    delete = TARGETS["delete-node"]
    _center_on(page, delete, 1.0)
    move_pointer_away(page, delete)

    # The control before Delete node takes the focus, and Tab moves it on: a
    # few presses at most, in case the page holds a stop the list above missed.
    before = page.evaluate(_FOCUS_BEFORE_JS, delete)
    assert before is not None, "nothing comes before the join's Delete node in the tab order"
    reached: list[str | None] = []
    for _ in range(5):
        page.keyboard.press("Tab")
        reached.append(page.evaluate("() => document.activeElement && document.activeElement.getAttribute('aria-label')"))
        if reached[-1] == "Delete node":
            break
    assert reached[-1] == "Delete node", f"Tab from {before!r} went to {reached}, never to Delete node"
    tip = one_tooltip(page, "Delete node, reached with Tab", delete)
    assert tip["text"] == "Delete node", tip
    _assert_beside_target(tip, "Delete node, reached with Tab")

    page.keyboard.press("Escape")
    no_tooltip(page, "after Escape on Delete node")

    # A click's focus shows nothing: the join's Code tab, clicked with the
    # mouse, which then rests on it for longer than a tooltip waits.
    tab = element_box(page, f'.react-flow__node[data-id="{JOIN}"] .nav-link[data-rr-ui-event-key="code"]')
    page.mouse.click(*assert_in_view(page, *box_middle(tab), "the join's Code tab"))
    page.wait_for_timeout(1000)
    assert tooltips_on_screen(page) == [], "a tooltip showed after a click on the join's Code tab"


def test_a_chart_mark_shows_its_data_at_the_pointer_and_no_title(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Chart Tooltips",
        username="tooltips_chart",
        project_name="Chart tooltips",
        project_spec=load_example_spec(ZIPS_EXAMPLE),
    )
    require_owner_view(page)
    node_locator(page, ZIP_BARS_ID).wait_for(state="visible", timeout=45000)
    run_all_and_wait(page, timeout_ms=RUN_MS)

    page.evaluate(_UNSCROLL_JS, ZIP_BARS_ID)
    frame_node(page, ZIP_BARS_ID)
    page.locator(f"#vega{ZIP_BARS_ID} canvas").first.wait_for(state="attached", timeout=60000)
    selector = drawing_selector(page, ZIP_BARS_ID)
    assert selector, "the zip chart drew nothing"

    # Down the left end of the bars, where every bar is drawn, until one shows
    # its fields: "zip: 60614", then the rest of its tooltip encoding.
    seen: list[str] = []
    for down in (0.05, 0.2, 0.12, 0.28, 0.36, 0.44):
        mark = mark_point(page, selector, (0.1, down))
        if not mark:
            seen.append(f"{down:.0%} down: no bar")
            continue
        point = assert_in_view(page, mark["x"], mark["y"], f"the bar {down:.0%} down the zip chart")
        move_pointer_away(page, f"#vega{ZIP_BARS_ID}")
        page.mouse.move(*point)
        try:
            tip = one_tooltip(page, f"the bar {down:.0%} down the zip chart", timeout=3000)
        except AssertionError as error:
            seen.append(f"{down:.0%} down: {error}")
            continue
        if re.search(r"(^| )zip: \S", tip["text"]):
            break
        seen.append(f"{down:.0%} down: {tip['text']!r}")
    else:
        raise AssertionError(f"no bar of the zip chart showed its fields in a tooltip: {seen}")

    chart = page.evaluate(_CHART_JS, ZIP_BARS_ID)
    assert chart, "the zip chart has no element"
    assert chart["titled"] == [], f"the zip chart still writes a native title: {chart['titled']}"
    assert " ".join((chart["tooltip"] or "").split()) == tip["text"], (
        f"the tooltip says {tip['text']!r}; the chart's data-tooltip, {chart['tooltip']!r}"
    )
    _assert_at_pointer(tip, point, "the zip chart's tooltip")


def test_the_canvas_draws_no_native_tooltip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    dataflow = _open_26(page, app_frontend, current_server, username="tooltips_canvas_titles")
    for node in dataflow["nodes"]:
        card = node_locator(page, node["id"])
        for tab in ("code", "grammar"):
            if card.locator(f'.nav-link[data-rr-ui-event-key="{tab}"]').count():
                _open_tab(page, node["id"], tab)
                break
        if card.locator('[data-widget-strip]:visible [data-strip-category="inputs"]').count():
            open_strip_category(page, node["id"], "inputs")
    _assert_no_titles(page, "the canvas, example 26 open with every editor and its Inputs open")

    for kind in ("builtin", "packages", "datasets", "agents", "models"):
        open_tools_palette(page, kind)
        _assert_no_titles(page, f"the canvas, with the tool rail's {kind} palette open")


@pytest.mark.parametrize(
    "path, heading, card",
    [
        ("/catalog/data", "Data Catalog", "article[data-dataset-id]"),
        ("/catalog/nodes", "Node Catalog", "article[data-pkg-dir]"),
    ],
    ids=["data-catalog", "node-catalog"],
)
def test_a_catalog_page_draws_no_native_tooltip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    path: str,
    heading: str,
    card: str,
):
    require_project_page()
    require_user_auth()
    # The canvas first, which also waits out the page's first build.
    _open_26(page, app_frontend, current_server, username=f"tooltips_{heading.split()[0].lower()}_catalog")
    page.goto(f"{app_frontend.base_url}{path}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name=heading, level=1)).to_be_visible(timeout=30000)
    page.locator(card).first.wait_for(state="visible", timeout=30000)
    _assert_no_titles(page, f"the {heading} page")

    _open_first_details(page, card)
    _assert_no_titles(page, f"the {heading} page, a card's details open")


def test_a_dashboard_draws_no_native_tooltip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    session = _pinned_and_saved(page, app_frontend, current_server, prefix="tooltips_dashboard")
    _open_dashboard(page, app_frontend.base_url, session["project"]["id"])
    _chart_drew(page)
    _assert_no_titles(page, "a dashboard, its chart drawn")


def test_api_settings_draws_no_native_tooltip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username="tooltips_settings",
        name="Tooltip Settings",
        project_name="Tooltip settings",
    )
    # A configuration, so a row and its buttons are on the page.
    api_json(
        f"{current_server}/api/agents/llm/configs", login["token"], method="POST",
        payload={"label": "Scripted A", "apiType": "testing", "model": "scripted-a"},
    )
    page.goto(f"{app_frontend.base_url}/settings/keys")
    expect(page.get_by_role("heading", name="API Settings", level=1)).to_be_visible(timeout=90000)
    expect(page.get_by_test_id("api-keys-tab").get_by_text("Scripted A").first).to_be_visible(timeout=15000)
    _assert_no_titles(page, "API Settings, its API keys")

    page.get_by_role("tab", name="Agent configuration", exact=True).click()
    expect(page.get_by_role("tab", name="Agent configuration", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    _assert_no_titles(page, "API Settings, its Agent configuration")
