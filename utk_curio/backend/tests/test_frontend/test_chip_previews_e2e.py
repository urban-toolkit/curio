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

A frame of each preview: the tooltip and what it describes, compared as
tightly as a node's close-up. The pointer is moved with ``page.mouse``
(utils/tooltips). None of these needs a GPU: the maps in example 26 and in
Chicago Loop stay undrawn on a CPU runner, and nothing here reads them.

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
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    REPO_ROOT,
    _wait_for_no_node_running,
    api_json,
    assert_vega_canvas_rendered,
    frame_nodes,
    hover_chip_until_tooltip_says,
    hover_until_tooltip_says,
    node_locator,
    open_strip_category,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    run_node_and_wait,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    tooltip_close_up,
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

#: The stem of this module's frames.
STEM = "chip-previews"
#: The line a header tag's preview ends with.
TAG_HOW = "Drag into the code, or click to insert it at the cursor"
#: How long a node of these examples may take to run, in ms.
RUN_MS = 120000
#: How long a preview may take to show and read its input, in ms: its 400 ms,
#: one read of the input, and a busy runner.
PREVIEW_MS = 15000


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


def _preview(
    page,
    what: str,
    expected: list[str],
    *,
    selector: str | None = None,
    chip: tuple[str, str] | None = None,
) -> dict:
    """A fresh hover of a header tag (*selector*) or of a chip in the code
    (*chip*: its node, and what stands in it), whose box is read only once no
    tooltip shows, and its one tooltip saying each of *expected*, which a
    preview says once it has read its input. A chip's says no tag's last line,
    which tells its tooltip from its tag's. Returns the tooltip, with the box
    the pointer rested on under ``hovered``; a failure says what lay under the
    pointer at each try."""
    if chip is not None:
        node_id, inner = chip
        return hover_chip_until_tooltip_says(
            page, node_id, inner, what, expected, absent=(TAG_HOW,), timeout=PREVIEW_MS,
        )
    assert selector is not None, f"{what}: a tag is hovered by its selector"
    page.locator(f"{selector}:visible").first.wait_for(state="visible", timeout=15000)
    return hover_until_tooltip_says(page, selector, what, expected, timeout=PREVIEW_MS)


def _frame(page, name: str, tip: dict, target: dict | None, failed: list[str]) -> None:
    """A frame of *tip* and what it describes, as tightly compared as a node's
    close-up. A frame that differs is noted in *failed*, so every preview is
    checked before the frames' verdict."""
    try:
        save_workflow_test_screenshot(
            page, STEM, test_name=name,
            fit_reactflow=False, keep_tooltip=True, clip_rect=tooltip_close_up(page, tip, target),
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            closeup=True,
        )
    except AssertionError as error:
        failed.append(f"{name}: {error}")


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
    failed: list[str] = []
    selector = f'.react-flow__node[data-id="{JOIN}"] [data-widget-strip] [data-input-tag="1"]'
    tag = _preview(page, "the join's input_1 tag", expected + [TAG_HOW], selector=selector)
    assert "from Summarize" in tag["text"], tag["text"]
    _frame(page, "26-join-input-1-tag", tag, None, failed)

    # With Inputs open the editor is a few lines tall, and finding the chip
    # scrolls its line into view: the hover reads its box once no tooltip
    # shows, and moves again until the pointer rests on it.
    chip = _preview(page, "the join's [!! input_1 !!] chip", expected, chip=(JOIN, "input_1"))
    _frame(page, "26-join-input-1-chip", chip, chip["hovered"], failed)
    _assert_same_preview(tag["text"], chip["text"])
    assert not failed, "\n".join(failed)


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
    failed: list[str] = []

    # input_0: the pool's rows, their size, kind and coordinate system.
    selector = f'{strip} [data-input-tag="0"]'
    tag = _preview(
        page,
        "the chart's input_0 tag",
        ["from Data Pool", "79 rows", "3 columns", "GeoDataFrame", "EPSG:3395", "MultiPolygon", "Adams", TAG_HOW],
        selector=selector,
    )
    _frame(page, "interaction-vega-input-0-tag", tag, None, failed)

    # A column of input_0, in its open list: its dtype, values and range.
    _open_list(page, VEGA_CHART, 0)
    selector = f'{strip} [data-input-columns="0"] [data-column-tag="accessibility"]'
    column = _preview(
        page,
        "the accessibility column of input_0",
        ["float64", "0.3124", "range 0 to 1", "all 79 rows", TAG_HOW],
        selector=selector,
    )
    _frame(page, "interaction-vega-accessibility-column", column, None, failed)
    assert not failed, "\n".join(failed)


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
    failed: list[str] = []

    # Nothing has run: the stacked rows are to come, and begin with the
    # fields the stacking adds.
    inputs = _preview(
        page,
        "the chart's [!! inputs !!] chip",
        ["Not run yet", "scenario_name", "scenario", "__input__"],
        chip=(LOOP_CHART, "inputs"),
    )
    _frame(page, "chicago-loop-inputs-chip", inputs, inputs["hovered"], failed)

    # The boxes' colors, which need no run.
    colors = _preview(
        page,
        "the chart's [!! scenario colors !!] chip",
        ["Existing", "#2a9d8f", "Towers removed", "#e76f51"],
        chip=(LOOP_CHART, "scenario colors"),
    )
    _frame(page, "chicago-loop-scenario-colors-chip", colors, colors["hovered"], failed)
    assert not failed, "\n".join(failed)
