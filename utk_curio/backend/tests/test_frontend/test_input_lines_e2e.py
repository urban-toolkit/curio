"""Playwright E2E: Inputs in a chart's header, one input per line (#662).

The owner's case, in the shipped test dataflow ``interaction-vega.json``: its
bar chart (``node12``, Vega-Lite) is fed from a Data Pool. With ``input_0``'s
columns open, the ``inputs`` tag went to the end of the header, below the
columns, where it read as one of them. Now each input is a line of its own:

1. The chain runs, so ``input_0`` holds the pool's rows, and the chart draws.
2. On the chart's Grammar tab, with Inputs open, opening ``input_0``'s list
   leaves the ``inputs`` tag at its left edge, on its own line below the list,
   and puts the list under ``input_0``'s tag, past its expander. These are
   read with the hooks the header had before its lines (the ``inputs`` tag,
   ``input_0``'s tag and list, and the expander named after ``input_0``'s
   columns), so on the header the owner reviewed the test fails where the
   owner saw the bug: at the ``inputs`` tag's left edge.
3. The header, and every box measured in it, lies inside the chart's card: the
   header takes at most half the card's editor, and its chips scroll.
4. Opening Inputs read ``input_0``'s columns, so its line says it comes from
   the Data Pool and how many columns it holds, and the line of ``inputs``
   follows; the list is under ``input_0``'s whole line.
5. A close-up of the chart with ``input_0``'s list open, its spec in its
   editor and its Grammar tab still shown.

jsdom has no layout, so where the lines and the lists land is checked here;
their order and their texts are in ``referenceStripLists.test.tsx``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_input_lines_e2e.py -v
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    _wait_for_no_node_running,
    assert_vega_canvas_rendered,
    frame_nodes,
    node_locator,
    open_strip_category,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "interaction-vega.json"
TEST_NAME = "test_an_open_list_sits_under_its_line_and_inputs_keeps_a_line_of_its_own"
#: The bar chart, and the Data Pool that feeds it.
CHART = "node12"
POOL = "3a98c743-bee9-492a-b1ce-dbc17be97f14"
#: How far apart two edges may be on screen and still be one edge, in px.
EDGE_PX = 1.0

# What each line under Inputs says its input holds, in the lines' order:
# [["input_0", "from Data Pool: 3 columns"], ["inputs", ...]]. Null while
# Inputs is closed. Read from the header the node shows: its code's or its
# spec's.
_LINES_JS = r"""(nodeId) => {
    const strip = Array.from(document.querySelectorAll(`.react-flow__node[data-id="${nodeId}"] [data-widget-strip]`))
        .find((el) => el.getClientRects().length > 0);
    const chips = strip && strip.querySelector('[data-strip-chips="inputs"]');
    if (!chips) return null;
    return Array.from(chips.querySelectorAll("[data-input-line], [data-inputs-line]")).map((line) => [
        line.hasAttribute("data-inputs-line") ? "inputs" : `input_${line.getAttribute("data-input-line")}`,
        line.querySelector("[data-input-about]")?.textContent ?? null,
    ]);
}"""

# Where the chart's card, its header, input_0's tag, line, expander, open list
# and that list's columns, and the inputs tag sit on screen, all read at one
# moment. All but the line are found by hooks the header had before its lines.
_BOXES_JS = r"""(nodeId) => {
    const card = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const strip = card && Array.from(card.querySelectorAll("[data-widget-strip]"))
        .find((el) => el.getClientRects().length > 0);
    const chips = strip && strip.querySelector('[data-strip-chips="inputs"]');
    if (!chips) return null;
    const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    };
    const list = chips.querySelector('[data-input-columns="0"]');
    const expander = Array.from(chips.querySelectorAll("button"))
        .find((el) => /^(Show|Hide) the columns of input_0$/.test(el.getAttribute("aria-label") || ""));
    return {
        card: box(card),
        strip: box(strip),
        tag: box(chips.querySelector('[data-input-tag="0"]')),
        line: box(chips.querySelector('[data-input-line="0"]')),
        expander: box(expander),
        list: box(list),
        columns: list ? Array.from(list.querySelectorAll("[data-column-tag]")).map(box) : [],
        inputs: box(chips.querySelector("[data-inputs-tag]")),
    };
}"""


def _counted(lines) -> bool:
    """Whether every line says how much its input holds: a count, or none, after its source."""
    return bool(lines) and all(about and re.search(r": (\d|no )", about) for _, about in lines)


def _wait_for_counts(page, node_id: str, *, timeout: float = 30000) -> list:
    """Wait until every line under *node_id*'s Inputs shows its input's count,
    read when Inputs opened, and return what the lines say."""
    deadline = time.time() + timeout / 1000
    lines = page.evaluate(_LINES_JS, node_id)
    while not _counted(lines) and time.time() < deadline:
        page.wait_for_timeout(250)
        lines = page.evaluate(_LINES_JS, node_id)
    assert _counted(lines), (
        f"not every line under {node_id}'s Inputs says how much its input holds "
        f"{timeout / 1000:.0f} s after Inputs opened: {lines}"
    )
    return lines


def _open_list(page, node_id: str, slot: int) -> None:
    """Open input *slot*'s list with its expander, named after its columns, by a
    dispatched click as ``open_strip_category`` opens a category, so nothing
    scrolls."""
    strip = node_locator(page, node_id).locator("[data-widget-strip]:visible")
    strip.get_by_role("button", name=f"Show the columns of input_{slot}", exact=True).dispatch_event("click")
    strip.locator(f'[data-input-columns="{slot}"]').wait_for(state="visible", timeout=15000)


def _inside(outer: dict, inner: dict, *, across_only: bool = False) -> bool:
    """Whether *inner* lies inside *outer*, to within EDGE_PX; *across_only*
    checks its left and right edges alone."""
    across = inner["left"] >= outer["left"] - EDGE_PX and inner["right"] <= outer["right"] + EDGE_PX
    if across_only:
        return across
    return across and inner["top"] >= outer["top"] - EDGE_PX and inner["bottom"] <= outer["bottom"] + EDGE_PX


def _ready_for_closeup(page, node_id: str, tab: str, text: str, *, timeout: float = 30000) -> None:
    """Before a close-up of *node_id*: its editor holds its code or spec (*text*
    in it), *tab* is still the tab it shows, and input_0's list is open. An
    editor holds "{}" until its spec is written in, and a late redraw turns a
    card to its output."""
    deadline = time.time() + timeout / 1000
    code = read_node_code(page, node_id)
    while text not in code and time.time() < deadline:
        page.wait_for_timeout(250)
        code = read_node_code(page, node_id)
    assert text in code, f"{node_id}'s editor holds no {text!r} before its close-up: {code!r}"
    pill = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{tab}"]').first
    assert "active" in (pill.get_attribute("class") or ""), f"{node_id} no longer shows its {tab} tab"
    node_locator(page, node_id).locator('[data-widget-strip]:visible [data-input-columns="0"]').wait_for(
        state="visible", timeout=5000,
    )


def test_an_open_list_sits_under_its_line_and_inputs_keeps_a_line_of_its_own(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    assert nodes[CHART]["type"] == "curio.builtin/vis-vega", nodes[CHART]["type"]
    assert nodes[POOL]["type"] == "curio.builtin/data-pool", nodes[POOL]["type"]

    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Input Lines",
        username="input_lines_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    # 1. The chain runs: the pool holds the rows, and the chart draws them. A
    # draw shows the chart's output pane, so the Grammar tab opens only once
    # nothing runs.
    run_all_and_wait(page)
    node_locator(page, POOL).locator("td.MuiTableCell-root").first.wait_for(state="visible", timeout=60000)
    wait_for_node_done(page, CHART, node_type=nodes[CHART]["type"], timeout_ms=60000)
    assert_vega_canvas_rendered(page, CHART, timeout=60000)
    _wait_for_no_node_running(page)

    # 2. The owner's case: input_0's list opens, and the inputs tag keeps its
    # left edge, on a line of its own below the list.
    frame_nodes(page, [CHART])
    _open_tab(page, CHART, "grammar")
    open_strip_category(page, CHART, "inputs")
    node_locator(page, CHART).locator("[data-widget-strip]:visible [data-inputs-tag]").wait_for(
        state="visible", timeout=15000,
    )
    before = page.evaluate(_BOXES_JS, CHART)
    assert before["inputs"] and before["list"] is None, before
    _open_list(page, CHART, 0)
    node_locator(page, CHART).locator(
        '[data-widget-strip]:visible [data-input-columns="0"] [data-column-tag]'
    ).first.wait_for(state="visible", timeout=30000)
    after = page.evaluate(_BOXES_JS, CHART)
    assert after["tag"] and after["expander"] and after["list"] and after["columns"] and after["inputs"], after
    assert abs(after["inputs"]["left"] - before["inputs"]["left"]) <= EDGE_PX, (
        f"opening input_0's list moved the inputs tag's left edge from {before['inputs']['left']:.1f} "
        f"to {after['inputs']['left']:.1f}"
    )
    assert after["inputs"]["top"] >= after["list"]["bottom"] - EDGE_PX, (
        f"the inputs tag (top {after['inputs']['top']:.1f}) is not on a line below input_0's list "
        f"(bottom {after['list']['bottom']:.1f})"
    )
    assert after["list"]["top"] >= after["tag"]["bottom"] - EDGE_PX, (
        f"input_0's list (top {after['list']['top']:.1f}) does not start below input_0's tag "
        f"(bottom {after['tag']['bottom']:.1f})"
    )
    indent = min(column["left"] for column in after["columns"])
    assert indent >= after["expander"]["right"] - EDGE_PX, (
        f"input_0's columns start at {indent:.1f}, not past its expander's right edge "
        f"{after['expander']['right']:.1f}"
    )

    # 3. The header and every box measured in it lie inside the card.
    assert _inside(after["card"], after["strip"]), f"the header {after['strip']} runs out of its card {after['card']}"
    for name in ("tag", "expander", "list", "inputs"):
        assert _inside(after["card"], after[name]), f"{name} {after[name]} runs out of the card {after['card']}"
    for column in after["columns"]:
        assert _inside(after["card"], column), f"a column {column} runs out of the card {after['card']}"

    # 4. The lines: input_0's from the pool, with its count, then the line of
    # inputs, and the list under input_0's whole line.
    lines = _wait_for_counts(page, CHART)
    assert [key for key, _ in lines] == ["input_0", "inputs"], lines
    assert re.fullmatch(r"from Data Pool: \d+ columns?", lines[0][1]), lines
    after = page.evaluate(_BOXES_JS, CHART)
    assert after["line"] and after["list"]["top"] >= after["line"]["bottom"] - EDGE_PX, (
        f"input_0's list (top {after['list']['top']:.1f}) does not start below input_0's line: {after['line']}"
    )

    # 5. The chart with input_0's list open.
    _ready_for_closeup(page, CHART, "grammar", '"neighborhood_name"')
    save_node_closeup(page, "interaction-vega-chart-header", CHART, test_name=TEST_NAME, sweep_toasts=True)
