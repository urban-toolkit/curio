"""Playwright E2E: Inputs in a chart's header, one input per line (#662).

The owner's case, in the shipped test dataflow ``interaction-vega.json``: its
bar chart (``node12``, Vega-Lite) is fed from a Data Pool. With ``input_0``'s
columns open, the ``inputs`` tag went to the end of the header, below the
columns, where it read as one of them. Now each input is a line of its own:

1. The chain runs, so ``input_0`` holds the pool's rows, and the chart draws.
2. On the chart's Grammar tab, Inputs opens to ``input_0``'s line, then the
   line of ``inputs``. Opening Inputs reads ``input_0``'s columns, so its line
   says it comes from the Data Pool and how many columns it holds.
3. Opening ``input_0``'s list puts it under ``input_0``'s line, indented past
   its expander, and ``inputs`` keeps its left edge, on its own line below the
   list.
4. A close-up of the chart with ``input_0``'s list open.

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

# Where input_0's line, its expander, its open list and that list's columns,
# and the inputs tag sit on screen, all read at one moment.
_BOXES_JS = r"""(nodeId) => {
    const strip = Array.from(document.querySelectorAll(`.react-flow__node[data-id="${nodeId}"] [data-widget-strip]`))
        .find((el) => el.getClientRects().length > 0);
    const chips = strip && strip.querySelector('[data-strip-chips="inputs"]');
    if (!chips) return null;
    const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
    };
    const line = chips.querySelector('[data-input-line="0"]');
    const list = chips.querySelector('[data-input-columns="0"]');
    return {
        line: box(line),
        expander: box(line && line.querySelector("button[aria-expanded]")),
        list: box(list),
        columns: list ? Array.from(list.querySelectorAll("[data-column-tag]")).map(box) : [],
        inputs: box(chips.querySelector("[data-inputs-line] [data-inputs-tag]")),
    };
}"""


def _counted(lines) -> bool:
    """Whether every line says how much its input holds: a count after its source."""
    return bool(lines) and all(about and re.search(r": \d", about) for _, about in lines)


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
    """Open input *slot*'s list under its line, with a dispatched click as
    ``open_strip_category`` opens a category, so nothing scrolls."""
    strip = node_locator(page, node_id).locator("[data-widget-strip]:visible")
    strip.locator(f'[data-input-line="{slot}"]').get_by_role(
        "button", name=f"Show the columns of input_{slot}", exact=True,
    ).dispatch_event("click")
    strip.locator(f'[data-input-columns="{slot}"]').wait_for(state="visible", timeout=15000)


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

    # 2. Inputs: input_0's line, from the pool, with its count, then the line
    # of inputs.
    frame_nodes(page, [CHART])
    _open_tab(page, CHART, "grammar")
    open_strip_category(page, CHART, "inputs")
    lines = _wait_for_counts(page, CHART)
    assert [key for key, _ in lines] == ["input_0", "inputs"], lines
    assert re.fullmatch(r"from Data Pool: \d+ columns?", lines[0][1]), lines
    before = page.evaluate(_BOXES_JS, CHART)
    assert before["inputs"] and before["list"] is None, before

    # 3. input_0's list opens under its line, past its expander, and inputs
    # keeps its left edge, on its own line below the list.
    _open_list(page, CHART, 0)
    node_locator(page, CHART).locator(
        '[data-widget-strip]:visible [data-input-columns="0"] [data-column-tag]'
    ).first.wait_for(state="visible", timeout=15000)
    after = page.evaluate(_BOXES_JS, CHART)
    assert after["line"] and after["expander"] and after["list"] and after["columns"] and after["inputs"], after
    assert abs(after["inputs"]["left"] - before["inputs"]["left"]) <= EDGE_PX, (
        f"opening input_0's list moved the inputs tag's left edge from {before['inputs']['left']:.1f} "
        f"to {after['inputs']['left']:.1f}"
    )
    assert after["inputs"]["top"] >= after["list"]["bottom"] - EDGE_PX, (
        f"the inputs tag (top {after['inputs']['top']:.1f}) is not on a line below input_0's list "
        f"(bottom {after['list']['bottom']:.1f})"
    )
    assert after["list"]["top"] >= after["line"]["bottom"] - EDGE_PX, (
        f"input_0's list (top {after['list']['top']:.1f}) does not start below input_0's line "
        f"(bottom {after['line']['bottom']:.1f})"
    )
    indent = min(column["left"] for column in after["columns"])
    assert indent >= after["expander"]["right"] - EDGE_PX, (
        f"input_0's columns start at {indent:.1f}, not past its expander's right edge "
        f"{after['expander']['right']:.1f}"
    )

    # 4. The chart with input_0's list open.
    save_node_closeup(page, "interaction-vega-chart-header", CHART, test_name=TEST_NAME, sweep_toasts=True)
