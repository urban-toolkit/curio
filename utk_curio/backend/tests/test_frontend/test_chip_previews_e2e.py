"""Playwright E2E: a chip's hover previews what the chip holds.

A header tag and the chip in the editor show one preview, in the one Curio
tooltip (``[role=tooltip]``): where the input comes from, its size and kind,
and its first rows. Three shipped dataflows, checked where jsdom has no layout
and no tooltip layer to read:

1. Example 26, Several inputs, with the nodes that feed its join run: the
   join's ``input_1`` tag under Inputs, then its ``[!! input_1 !!]`` chip in
   the code. Summarize's tuple: a tuple of 2 values, read in code as
   ``input_1[0]`` and ``input_1[1]``, each part's columns (``pm25_mean``,
   ``pm25_peak``) and first rows (``sensor_A``, its mean ``8.0417``). Both
   hovers say the same, the tag's with how to use it.
2. ``interaction-vega.json`` after Run All: the bar chart's ``input_0`` tag,
   the Data Pool's 79 rows of 3 columns, a GeoDataFrame in EPSG:3395 whose
   geometry is a MultiPolygon, first Adams; then the ``accessibility`` column
   in ``input_0``'s open list: float64, first 0.3124, and its range, 0 to 1,
   over all 79 rows.
3. ``chicago-loop-shadow-towers.json`` as it opens, with no run: the chart's
   ``[!! inputs !!]`` chip in its spec says it has not run, and the fields its
   rows begin with (``scenario_name``, ``scenario``, ``__input__``); its
   ``[!! scenario colors !!]`` chip shows each box's name and color (Existing
   #2a9d8f, Towers removed #e76f51).

The pointer is moved with ``page.mouse`` to an element's middle: a locator's
hover fails its actionability check under React Flow's pane. None of these
needs a GPU: the maps in example 26 and in Chicago Loop stay undrawn on a CPU
runner, and nothing here reads them.

TODO(frames): a frame of each preview, with its node, once the tooltip PR
("One Curio tooltip") has merged: its capture hides an open tooltip unless
asked to keep it (``keep_tooltip=True``), and clips a frame to the node and
its tooltip. Until then these tests take no frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_chip_previews_e2e.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_input_lines_e2e import _open_list, _wait_for_counts
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    _wait_for_no_node_running,
    api_json,
    assert_in_view,
    assert_vega_canvas_rendered,
    frame_nodes,
    node_locator,
    open_strip_category,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLES = Path(REPO_ROOT) / "docs" / "examples"
SEVERAL_INPUTS = EXAMPLES / "26-several-inputs.json"
INTERACTION_VEGA = EXAMPLES / "dataflows" / "interaction-vega.json"
CHICAGO_LOOP = EXAMPLES / "dataflows" / "chicago-loop-shadow-towers.json"

#: Example 26's join, and the nodes that feed it, in an order they can run in.
JOIN = "several-join"
JOIN_FEEDERS = ("several-readings", "several-stations", "several-zips", "several-summary")
#: interaction-vega's bar chart, and the Data Pool that feeds it.
VEGA_CHART = "node12"
VEGA_POOL = "3a98c743-bee9-492a-b1ce-dbc17be97f14"
#: Chicago Loop's chart, Scout's Bars, and the packages it needs.
LOOP_CHART = "d0e547ba-e7d6-52e1-9c0e-f047443b715c"
LOOP_PACKAGES = ("curio.scout@1", "model.scout.deep-umbra@1")

#: The line a header tag's preview ends with.
TAG_HOW = "Drag into the code, or click to insert it at the cursor"
#: How long a node of these examples may take to run, in ms.
RUN_MS = 120000
#: How long a preview may take to show and read its input, in ms: its 400 ms,
#: one read of the input, and a busy runner.
PREVIEW_MS = 15000

# The first element *selector* finds that is laid out, as a box.
_BOX_JS = r"""(selector) => {
    const el = Array.from(document.querySelectorAll(selector)).find((e) => e.getClientRects().length > 0);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
}"""

# The box of the chip `[!! inner !!]` in the editor *nodeId* shows, its line
# first scrolled to the editor's middle. Null until the line is drawn. The
# lines these tests hover hold that one chip.
_CHIP_JS = r"""({ nodeId, inner }) => {
    const card = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const host = card && Array.from(card.querySelectorAll(".monaco-editor")).find((el) => el.getClientRects().length > 0);
    if (!host) return null;
    const written = `[!! ${inner} !!]`;
    const editor = ((window.monaco && window.monaco.editor.getEditors()) || []).find((e) => host.contains(e.getDomNode()));
    if (editor) {
        const at = editor.getModel().getValue().split("\n").findIndex((line) => line.includes(written));
        if (at >= 0) editor.revealLineInCenter(at + 1);
    }
    for (const line of host.querySelectorAll(".view-line")) {
        if (!(line.textContent || "").replace(/ /g, " ").includes(written)) continue;
        const spans = Array.from(line.querySelectorAll(".curio-widget-ref, .curio-widget-ref-problem"))
            .filter((span) => span.getClientRects().length > 0);
        if (!spans.length) return null;
        const boxes = spans.map((span) => span.getBoundingClientRect());
        return {
            left: Math.min(...boxes.map((b) => b.left)),
            top: Math.min(...boxes.map((b) => b.top)),
            right: Math.max(...boxes.map((b) => b.right)),
            bottom: Math.max(...boxes.map((b) => b.bottom)),
        };
    }
    return null;
}"""

# A point on the canvas where the pointer rests on nothing that shows a
# tooltip: the bare pane when some is in view, else a part of a card that
# holds no control and no editor.
_QUIET_POINT_JS = r"""() => {
    const area = document.querySelector(".curio-canvas-drop-target") || document.body;
    const loud = '[data-tooltip], [title], [aria-describedby], button, a, input, select, textarea, '
        + '[role="button"], [role="tab"], [draggable="true"], .monaco-editor, .react-flow__handle, canvas';
    const r = area.getBoundingClientRect();
    let fallback = null;
    for (let fy = 0.05; fy < 1; fy += 0.1) {
        for (let fx = 0.05; fx < 1; fx += 0.1) {
            const x = r.left + fx * r.width;
            const y = r.top + fy * r.height;
            const el = document.elementFromPoint(x, y);
            if (!el || el.closest(loud)) continue;
            if (el.classList.contains("react-flow__pane")) return { x, y };
            fallback = fallback || { x, y };
        }
    }
    return fallback;
}"""

# What each tooltip on screen says, its white space run together.
_TOOLTIPS_JS = r"""() => Array.from(document.querySelectorAll('[role="tooltip"]')).filter((tip) => {
    const style = getComputedStyle(tip);
    const r = tip.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0
        && r.width > 0 && r.height > 0;
}).map((tip) => (tip.innerText || tip.textContent || "").replace(/\s+/g, " ").trim())"""


def _open(page, app_frontend, current_server: str, path: Path, *, username: str) -> tuple[dict, dict]:
    """Open the dataflow at *path* as a new dataflow and wait for its nodes.
    Returns its nodes by id, and the session."""
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(path.read_text(encoding="utf-8"))
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Chip Previews",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    nodes = {node["id"]: node for node in spec["dataflow"]["nodes"]}
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    return nodes, session


def _box(page, selector: str, *, timeout: float = 15000) -> dict:
    """The box of the first element *selector* finds that is laid out."""
    deadline = time.time() + timeout / 1000
    box = page.evaluate(_BOX_JS, selector)
    while box is None and time.time() < deadline:
        page.wait_for_timeout(200)
        box = page.evaluate(_BOX_JS, selector)
    assert box, f"nothing on the page matches {selector}"
    return box


def _chip(page, node_id: str, inner: str, *, timeout: float = 15000) -> dict:
    """The box of the chip ``[!! inner !!]`` in *node_id*'s editor, its line
    scrolled into the editor's view."""
    deadline = time.time() + timeout / 1000
    box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    while box is None and time.time() < deadline:
        page.wait_for_timeout(200)
        box = page.evaluate(_CHIP_JS, {"nodeId": node_id, "inner": inner})
    assert box, f"{node_id}'s editor shows no chip [!! {inner} !!]"
    return box


def _rest_away(page) -> None:
    """Rest the pointer where nothing shows a tooltip, and wait until none shows."""
    quiet = page.evaluate(_QUIET_POINT_JS)
    assert quiet, "the canvas has no point where nothing shows a tooltip"
    page.mouse.move(quiet["x"], quiet["y"])
    deadline = time.time() + 5
    while page.evaluate(_TOOLTIPS_JS) and time.time() < deadline:
        page.wait_for_timeout(100)
    assert page.evaluate(_TOOLTIPS_JS) == [], f"a tooltip stays on screen: {page.evaluate(_TOOLTIPS_JS)}"


def _preview(page, box: dict, what: str, expected: list[str]) -> str:
    """Rest the pointer on the middle of *box*, a fresh hover, and wait for its
    one tooltip to say each of *expected*, which a preview says once it has
    read its input. Returns what it says."""
    _rest_away(page)
    page.mouse.move(*assert_in_view(page, (box["left"] + box["right"]) / 2, (box["top"] + box["bottom"]) / 2, what))
    deadline = time.time() + PREVIEW_MS / 1000
    tips = page.evaluate(_TOOLTIPS_JS)
    while not (len(tips) == 1 and all(text in tips[0] for text in expected)) and time.time() < deadline:
        page.wait_for_timeout(200)
        tips = page.evaluate(_TOOLTIPS_JS)
    assert len(tips) == 1, f"{what}: {len(tips)} tooltips on screen, not one: {tips}"
    missing = [text for text in expected if text not in tips[0]]
    assert not missing, f"{what}: the preview does not say {missing}: {tips[0]!r}"
    return tips[0]


def _assert_same_preview(tag: str, chip: str) -> None:
    """A header tag's preview is its chip's, then how to use the tag."""
    assert tag.endswith(TAG_HOW), f"the tag's preview does not end with {TAG_HOW!r}: {tag!r}"
    assert tag[: -len(TAG_HOW)].strip() == chip, (
        f"the tag and the chip preview different things:\n  tag:  {tag!r}\n  chip: {chip!r}"
    )


def test_the_join_previews_its_tuple_input_in_its_header_and_its_code(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    nodes, _ = _open(page, app_frontend, current_server, SEVERAL_INPUTS, username="chip_previews_join")
    assert "return means, peaks" in nodes["several-summary"]["content"]
    assert "[!! input_1 !!]" in nodes[JOIN]["content"]

    # The join's inputs hold their values; the join itself does not run.
    for node_id in JOIN_FEEDERS:
        run_node_and_wait(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=RUN_MS)
    _wait_for_no_node_running(page)

    frame_nodes(page, [JOIN])
    _open_tab(page, JOIN, "code")
    open_strip_category(page, JOIN, "inputs")
    lines = _wait_for_counts(page, JOIN)
    assert lines[1][1] == "from Python Computation: 2 values, a tuple", lines

    # The tuple's parts, as code reads them, with their columns and rows.
    expected = ["A tuple of 2 values", "input_1[0]", "input_1[1]", "pm25_mean", "pm25_peak", "sensor_A", "8.0417"]
    tag_box = _box(page, f'.react-flow__node[data-id="{JOIN}"] [data-widget-strip] [data-input-tag="1"]')
    tag = _preview(page, tag_box, "the join's input_1 tag", expected + [TAG_HOW])
    assert "from Summarize" in tag, tag
    chip = _preview(page, _chip(page, JOIN, "input_1"), "the join's [!! input_1 !!] chip", expected)
    _assert_same_preview(tag, chip)
    # TODO(frames): the join with each preview, once the tooltip PR has merged.


def test_the_chart_previews_its_input_and_a_column_after_run_all(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    nodes, _ = _open(page, app_frontend, current_server, INTERACTION_VEGA, username="chip_previews_vega")
    assert nodes[VEGA_CHART]["type"] == "curio.builtin/vis-vega", nodes[VEGA_CHART]["type"]
    assert nodes[VEGA_POOL]["type"] == "curio.builtin/data-pool", nodes[VEGA_POOL]["type"]

    # The chain runs: the pool holds the rows, and the chart draws them.
    run_all_and_wait(page)
    node_locator(page, VEGA_POOL).locator("td.MuiTableCell-root").first.wait_for(state="visible", timeout=60000)
    wait_for_node_done(page, VEGA_CHART, node_type=nodes[VEGA_CHART]["type"], timeout_ms=60000)
    assert_vega_canvas_rendered(page, VEGA_CHART, timeout=60000)
    _wait_for_no_node_running(page)

    frame_nodes(page, [VEGA_CHART])
    _open_tab(page, VEGA_CHART, "grammar")
    open_strip_category(page, VEGA_CHART, "inputs")
    strip = f'.react-flow__node[data-id="{VEGA_CHART}"] [data-widget-strip]'

    # input_0: the pool's rows, their size, kind and coordinate system.
    _preview(
        page,
        _box(page, f'{strip} [data-input-tag="0"]'),
        "the chart's input_0 tag",
        ["from Data Pool", "79 rows", "3 columns", "GeoDataFrame", "EPSG:3395", "MultiPolygon", "Adams", TAG_HOW],
    )

    # A column of input_0, in its open list: its dtype, values and range.
    _open_list(page, VEGA_CHART, 0)
    _preview(
        page,
        _box(page, f'{strip} [data-input-columns="0"] [data-column-tag="accessibility"]'),
        "the accessibility column of input_0",
        ["float64", "0.3124", "range 0 to 1", "all 79 rows", TAG_HOW],
    )
    # TODO(frames): the chart with each preview, once the tooltip PR has merged.


def test_the_unrun_chart_previews_its_stacked_inputs_and_scenario_colors(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    nodes, session = _open(page, app_frontend, current_server, CHICAGO_LOOP, username="chip_previews_loop")
    assert nodes[LOOP_CHART]["type"] == "curio.scout/bars", nodes[LOOP_CHART]["type"]
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in LOOP_PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"

    frame_nodes(page, [LOOP_CHART])
    _open_tab(page, LOOP_CHART, "grammar")
    # The editor holds "{}" until the spec is written in.
    deadline = time.time() + 30
    spec = read_node_code(page, LOOP_CHART)
    while '"[!! inputs !!]"' not in spec and time.time() < deadline:
        page.wait_for_timeout(250)
        spec = read_node_code(page, LOOP_CHART)
    assert '"[!! inputs !!]"' in spec and "[!! scenario colors !!]" in spec, spec

    # Nothing has run: the stacked rows are to come, and begin with the
    # fields the stacking adds.
    _preview(
        page,
        _chip(page, LOOP_CHART, "inputs"),
        "the chart's [!! inputs !!] chip",
        ["Not run yet", "scenario_name", "scenario", "__input__"],
    )

    # The boxes' colors, which need no run.
    _preview(
        page,
        _chip(page, LOOP_CHART, "scenario colors"),
        "the chart's [!! scenario colors !!] chip",
        ["Existing", "#2a9d8f", "Towers removed", "#e76f51"],
    )
    # TODO(frames): the chart with each preview, once the tooltip PR has merged.
