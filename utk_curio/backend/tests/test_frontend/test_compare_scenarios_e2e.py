"""Playwright E2E: two scenarios compared by a Compare Scenarios node (#662).

A loader of road segments feeds two scenarios. "Baseline" is one node that
divides the sunlight by its factor widget, 1. "Twice as tall" is a copy of that
node, with factor 2 and one more line, followed by a node only it has. A
Compare Scenarios node, pinned to the dashboard, stands beside them with no
input yet. This drives the whole path in a browser:

1. The palette offers the node.
2. Both outcomes are wired into its circles: each input is labelled by its
   scenario, and the node writes its code, one chip per input.
3. Run All stacks them: the node's output is one table under the scenario
   columns, and its chart draws it in the two scenarios' colors.
4. What differs lists the factor, 1 against 2, the line only the copy has, and
   the node only "Twice as tall" has; the node warns about nothing.
5. Another chart and a save: its labels, its code and its chart are saved, and
   so is its output, which its pinned tile draws.
6. The dashboard draws the tile from that output, with no run.
7. A reopen: the labels and the code come back as they were, and the chart
   draws from the saved output with no run.
8. A second loader wired into the copy: the node warns that the two inputs read
   different context, and names them. Its close-up is the frame.

A second test charts two scenarios of four rows and of two (#819's Chart
extras): Combine's None plots each row as it is, so the bars stack each
scenario's rows, and a pie writes each slice's value on it. Its close-ups are
the chart before and after each change.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_compare_scenarios_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .test_multi_input_e2e import _wait_for_circles
from .utils import (
    api_json,
    assert_vega_canvas_rendered,
    close_tools_palette,
    connect_nodes,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    open_tools_palette,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    save_node_closeup,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

COMPARE_TYPE = "curio.builtin/compare-scenarios"
LOAD = "cmp-load"
LOAD_2050 = "cmp-load-2050"
BASE = "cmp-base"
TALL = "cmp-tall"
CLIP = "cmp-clip"
COMPARE = "cmp-compare"
BASELINE = {"scenario": "s-base", "name": "Baseline", "color": "#2a9d8f"}
TWICE = {"scenario": "s-tall", "name": "Twice as tall", "color": "#e76f51"}

LOAD_CODE = (
    "import pandas as pd\n"
    'return pd.DataFrame({"segment": ["r1", "r2", "r3", "r4"], "sunlight": [6.0, 5.0, 7.0, 4.0]})\n'
)
SHADE_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\nreturn df\n'
TALL_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\ndf = df.round(2)\nreturn df\n'
CLIP_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"].clip(lower=0)\nreturn df\n'

# The lines the node writes for its two inputs (utils/compare/compareCode.ts).
ENTRY_LINES = (
    '    ("s-base", "Baseline", [!! input_0 !!]),',
    '    ("s-tall", "Twice as tall", [!! input_1 !!]),',
)


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _node(node_id, node_type, x, y, content, title=None, metadata=None, **fields) -> dict:
    saved = {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": [], **(metadata or {})}, **fields,
    }
    if title:
        saved["title"] = title
    return saved


def _spec() -> dict:
    node = _node
    return {
        "dataflow": {
            "name": "Compare Scenarios",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Compare Scenarios",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, 0, LOAD_CODE, "Roads"),
                node(LOAD_2050, "curio.builtin/data-loading", 0, 500, LOAD_CODE, "Roads 2050"),
                node(BASE, "curio.builtin/computation-analysis", 700, 0, SHADE_CODE, "Shade", _factor(1)),
                node(TALL, "curio.builtin/computation-analysis", 700, 500, TALL_CODE, "Shade",
                     {**_factor(2), "copiedFrom": [BASE]}),
                node(CLIP, "curio.builtin/computation-analysis", 1400, 500, CLIP_CODE, "Clip"),
                node(COMPARE, COMPARE_TYPE, 2100, 0, "", dashboardPinned=True),
            ],
            "edges": [
                {"id": "e-load-base", "source": LOAD, "target": BASE, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-load-tall", "source": LOAD, "target": TALL, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-tall-clip", "source": TALL, "target": CLIP, "sourceHandle": "out", "targetHandle": "in"},
            ],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL, CLIP]},
            ],
        }
    }


def _wait_for_code(page, node_id: str, lines, timeout_s: float = 15.0) -> str:
    deadline = time.time() + timeout_s
    code = ""
    while time.time() < deadline:
        code = read_node_code(page, node_id)
        if all(line in code for line in lines):
            return code
        page.wait_for_timeout(250)
    raise AssertionError(f"the Compare Scenarios node did not write its code for both inputs:\n{code}")


_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""


# How many opaque pixels of the chart's canvas are each color, give or take.
_COLOR_PIXELS_JS = """([id, colors]) => {
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!canvas || !canvas.width || !canvas.height) return null;
    const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
    const targets = colors.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)));
    const counts = targets.map(() => 0);
    for (let p = 0; p < data.length; p += 4) {
        if (data[p + 3] < 200) continue;
        targets.forEach((t, k) => {
            if (Math.abs(data[p] - t[0]) <= 12 && Math.abs(data[p + 1] - t[1]) <= 12
                && Math.abs(data[p + 2] - t[2]) <= 12) counts[k] += 1;
        });
    }
    return counts;
}"""


# Where the chart's compile stands: "drawing", "drawn" or "problem", once the
# body shows *preset* (the pane and the chart render together).
_CHART_STATE_JS = """([id, preset]) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    const pane = node && node.querySelector("[data-compare-preset]");
    const chart = node && node.querySelector("[data-compare-chart-state]");
    if (!pane || !chart) return null;
    if (pane.getAttribute("data-compare-preset") !== preset) return "another preset";
    return chart.getAttribute("data-compare-chart-state");
}"""


def _assert_chart_drew(page, node_id: str, preset: str) -> None:
    """The chart of *preset* compiled with no problem, and its canvas holds both
    scenarios' colors."""
    deadline = time.time() + 60
    state = None
    while time.time() < deadline:
        state = page.evaluate(_CHART_STATE_JS, [node_id, preset])
        if state in ("drawn", "problem"):
            break
        page.wait_for_timeout(250)
    problem = node_locator(page, node_id).locator("[data-compare-chart-problem]").all_inner_texts()
    assert state == "drawn", f"the {preset} chart's compile ended {state!r}: {problem}"
    assert_vega_canvas_rendered(page, node_id, timeout=30000)
    _assert_scenario_colors_drawn(page, node_id)


def _assert_scenario_colors_drawn(page, node_id: str) -> None:
    colors = [BASELINE["color"], TWICE["color"]]
    counts = None
    deadline = time.time() + 15
    while time.time() < deadline:
        counts = page.evaluate(_COLOR_PIXELS_JS, [node_id, colors])
        if counts and all(count >= 30 for count in counts):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"the chart does not draw both scenarios' colors {colors}: pixels {counts}")


def test_two_scenarios_are_stacked_charted_and_compared(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Compare Scenarios",
        username="compare_scenarios_e2e",
        project_name="Compare Scenarios",
        project_spec=spec,
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    # 1. The palette offers it: the rail's Built-in palette, closed again so
    #    its panel covers none of the canvas the next steps wire.
    open_tools_palette(page, "builtin")
    page.locator("#tile-compare-scenarios").wait_for(state="visible", timeout=15000)
    close_tools_palette(page, "builtin")

    # 2. Both outcomes into its circles: the node labels them and writes its code.
    _wait_for_circles(page, COMPARE, ["in"])
    frame_nodes(page, [BASE, COMPARE])
    connect_nodes(page, BASE, COMPARE)
    _wait_for_circles(page, COMPARE, ["in", "in_1"])
    frame_nodes(page, [CLIP, COMPARE])
    connect_nodes(page, CLIP, COMPARE, target_handle="in_1")
    _wait_for_circles(page, COMPARE, ["in", "in_1", "in_2"])
    _wait_for_code(page, COMPARE, ENTRY_LINES)

    # 3. Run All stacks them, and the chart draws them in their colors.
    run_all_and_wait(page, timeout_ms=240000)
    compare = node_locator(page, COMPARE)
    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "done", f"Compare Scenarios did not stack its inputs: {read_node_error_text(compare)}"
    frame_nodes(page, [COMPARE])
    _assert_chart_drew(page, COMPARE, "bar")
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, COMPARE)
    assert artifact, "Compare Scenarios shows no saved output"
    stacked = load_artifact_as_dict(artifact)
    assert stacked["dataType"] == "dataframe", stacked["dataType"]
    assert list(stacked["data"]) == ["scenario", "scenario_name", "segment", "sunlight"], list(stacked["data"])
    assert stacked["data"]["scenario"] == ["s-base"] * 4 + ["s-tall"] * 4
    assert stacked["data"]["scenario_name"] == ["Baseline"] * 4 + ["Twice as tall"] * 4
    assert stacked["data"]["sunlight"] == [6.0, 5.0, 7.0, 4.0, 3.0, 2.5, 3.5, 2.0]

    # 4. What differs: the factor, the copy's extra line, and the node only one
    #    scenario has. The two read the same context, so nothing is warned.
    compare.get_by_role("tab", name="What differs", exact=True).click()
    factor = compare.locator('[data-compare-widget="factor"]')
    factor.wait_for(state="visible", timeout=10000)
    shown = factor.inner_text()
    assert "Baseline: 1" in shown and "Twice as tall: 2" in shown, shown
    added = [line.inner_text() for line in compare.locator("[data-compare-code-added]").all()]
    assert added == ["+ df = df.round(2)"], added
    assert compare.locator("[data-compare-code-removed]").count() == 0
    only = compare.locator(f'[data-compare-lever="{CLIP}"] [data-compare-only-in]')
    assert only.inner_text() == "only in Twice as tall", only.inner_text()
    assert compare.locator("[data-compare-warning]").count() == 0

    # 5. Another chart, and a save. The node is pinned and draws its own output,
    #    so the save records that output.
    compare.get_by_role("tab", name="Chart", exact=True).click()
    frame_nodes(page, [COMPARE])
    compare.locator('select[aria-label="Chart"]').select_option("lollipop")
    _assert_chart_drew(page, COMPARE, "lollipop")
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[COMPARE]["metadata"]["compareScenarios"] == {
        "inputs": [BASELINE, TWICE],
        "chart": {"preset": "lollipop"},
    }, saved[COMPARE]["metadata"]
    content = saved[COMPARE]["content"]
    assert all(line in content for line in ENTRY_LINES), content
    recorded = {output["node_id"] for output in project["outputs"]}
    assert COMPARE in recorded, f"the save recorded the outputs of {sorted(recorded)}, not the pinned node's own"

    # 6. The dashboard draws the tile from that output, with no run.
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("open-dataflow-link").wait_for(state="visible", timeout=45000)
    node_locator(page, COMPARE).wait_for(state="visible", timeout=45000)
    _assert_chart_drew(page, COMPARE, "lollipop")

    # 7. Reopened, it reads its labels and code back and writes nothing, and the
    #    chart draws from the saved output with no run.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    compare = node_locator(page, COMPARE)
    compare.wait_for(state="visible", timeout=45000)
    assert _wait_for_code(page, COMPARE, ENTRY_LINES) == content
    frame_nodes(page, [COMPARE])
    compare.locator('.nav-link[data-rr-ui-event-key="output"]').click()
    _assert_chart_drew(page, COMPARE, "lollipop")
    assert compare.locator('select[aria-label="Chart"]').input_value() == "lollipop"
    assert compare.locator("[data-compare-warning]").count() == 0
    assert page.locator("[data-curio-save-state]").first.get_attribute("data-curio-save-state") == "saved"

    # 8. A second loader into the copy: now the scenarios read different context.
    frame_nodes(page, [LOAD_2050, TALL])
    connect_nodes(page, LOAD_2050, TALL, target_handle="in_1")
    warning = node_locator(page, COMPARE).locator("[data-compare-warning]")
    warning.first.wait_for(state="attached", timeout=10000)
    assert warning.all_inner_texts() == [
        "input_1 (Twice as tall) and input_0 (Baseline) read different context: only input_1 reads Roads 2050."
    ], warning.all_inner_texts()
    _assert_chart_drew(page, COMPARE, "lollipop")

    save_node_closeup(
        page, "compare-scenarios", COMPARE,
        test_name="test_two_scenarios_are_stacked_charted_and_compared",
        sweep_toasts=True,
    )


#: "Twice as tall" keeps its first two rows, so the two scenarios have four
#: rows (6, 5, 7, 4) and two (3, 2.5): their means are 5.5 and 2.75, their sums
#: 22 and 5.5.
HEAD_CODE = 'df = input_0.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\nreturn df.head(2)\n'
CHART_CLOSEUPS = "compare-chart-extras"


def _chart_spec() -> dict:
    return {
        "dataflow": {
            "name": "Compare Chart Extras",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Compare Chart Extras",
            "nodes": [
                _node(LOAD, "curio.builtin/data-loading", 0, 0, LOAD_CODE, "Roads"),
                _node(BASE, "curio.builtin/computation-analysis", 700, 0, SHADE_CODE, "Shade", _factor(1)),
                _node(TALL, "curio.builtin/computation-analysis", 700, 500, HEAD_CODE, "Shade",
                      {**_factor(2), "copiedFrom": [BASE]}),
                _node(COMPARE, COMPARE_TYPE, 1400, 0, ""),
            ],
            "edges": [
                {"id": "e-load-base", "source": LOAD, "target": BASE, "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-load-tall", "source": LOAD, "target": TALL, "sourceHandle": "out", "targetHandle": "in"},
            ],
            "scenarios": [
                {"id": "s-base", "name": "Baseline", "color": "#2a9d8f", "nodes": [BASE]},
                {"id": "s-tall", "name": "Twice as tall", "color": "#e76f51", "nodes": [TALL]},
            ],
        }
    }


# The height of each color's tallest column of pixels in the chart's canvas:
# a bar's height, for the legend's swatches are far shorter.
_BAR_HEIGHTS_JS = """([id, colors]) => {
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!canvas || !canvas.width || !canvas.height) return null;
    const { width, height } = canvas;
    const { data } = canvas.getContext("2d").getImageData(0, 0, width, height);
    const targets = colors.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)));
    return targets.map((t) => {
        let tallest = 0;
        for (let x = 0; x < width; x++) {
            let top = -1, bottom = -1;
            for (let y = 0; y < height; y++) {
                const p = (y * width + x) * 4;
                if (data[p + 3] < 200) continue;
                if (Math.abs(data[p] - t[0]) <= 12 && Math.abs(data[p + 1] - t[1]) <= 12
                    && Math.abs(data[p + 2] - t[2]) <= 12) {
                    if (top < 0) top = y;
                    bottom = y;
                }
            }
            if (top >= 0) tallest = Math.max(tallest, bottom - top + 1);
        }
        return tallest;
    });
}"""


# How many white pixels each color holds closed in on the left, the right, above
# and below: letters written on its slice. The chart's white background is
# never closed in by one color on all four sides, and a dark pixel (the legend's
# text) on the way out stops the search.
_WRITTEN_ON_JS = """([id, colors]) => {
    const canvas = document.querySelector(`#vega${id} canvas`);
    if (!canvas || !canvas.width || !canvas.height) return null;
    const { width, height } = canvas;
    const { data } = canvas.getContext("2d").getImageData(0, 0, width, height);
    const targets = colors.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)));
    const at = (x, y) => (y * width + x) * 4;
    const white = (p) => data[p + 3] >= 200 && data[p] >= 235 && data[p + 1] >= 235 && data[p + 2] >= 235;
    const dark = (p) => data[p + 3] >= 200 && data[p] + data[p + 1] + data[p + 2] < 300;
    const is = (p, t) => data[p + 3] >= 200 && Math.abs(data[p] - t[0]) <= 24
        && Math.abs(data[p + 1] - t[1]) <= 24 && Math.abs(data[p + 2] - t[2]) <= 24;
    const reaches = (x, y, dx, dy, t) => {
        for (let k = 1; k <= 16; k++) {
            const nx = x + dx * k, ny = y + dy * k;
            if (nx < 0 || ny < 0 || nx >= width || ny >= height) return false;
            const p = at(nx, ny);
            if (is(p, t)) return true;
            if (dark(p)) return false;
        }
        return false;
    };
    return targets.map((t) => {
        let count = 0;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                if (!white(at(x, y))) continue;
                if (reaches(x, y, -1, 0, t) && reaches(x, y, 1, 0, t)
                    && reaches(x, y, 0, -1, t) && reaches(x, y, 0, 1, t)) count += 1;
            }
        }
        return count;
    });
}"""


def _bar_ratio(page, node_id: str, expected: float) -> float:
    """Baseline's bar over the other's, once it is *expected*, give or take."""
    colors = [BASELINE["color"], TWICE["color"]]
    heights = None
    deadline = time.time() + 30
    while time.time() < deadline:
        heights = page.evaluate(_BAR_HEIGHTS_JS, [node_id, colors])
        if heights and min(heights) > 0 and abs(heights[0] / heights[1] - expected) <= 0.25:
            return heights[0] / heights[1]
        page.wait_for_timeout(250)
    raise AssertionError(f"Baseline's bar is not {expected} times the other's: heights {heights} for {colors}")


def _written_on(page, node_id: str) -> list:
    return page.evaluate(_WRITTEN_ON_JS, [node_id, [BASELINE["color"], TWICE["color"]]])


def test_a_chart_combines_nothing_and_a_pie_writes_its_values(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _chart_spec()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Compare Chart Extras",
        username="compare_chart_extras_e2e",
        project_name="Compare Chart Extras",
        project_spec=spec,
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    # Both outcomes into the node's circles, and Run All: bars of the means.
    _wait_for_circles(page, COMPARE, ["in"])
    frame_nodes(page, [BASE, COMPARE])
    connect_nodes(page, BASE, COMPARE)
    _wait_for_circles(page, COMPARE, ["in", "in_1"])
    frame_nodes(page, [TALL, COMPARE])
    connect_nodes(page, TALL, COMPARE, target_handle="in_1")
    _wait_for_code(page, COMPARE, ENTRY_LINES)
    run_all_and_wait(page, timeout_ms=240000)
    compare = node_locator(page, COMPARE)
    status = wait_for_node_settled(page, COMPARE, node_type=COMPARE_TYPE, timeout_ms=120000)
    assert status == "done", f"Compare Scenarios did not stack its inputs: {read_node_error_text(compare)}"
    frame_nodes(page, [COMPARE])
    _assert_chart_drew(page, COMPARE, "bar")

    # Combine offers None, after the aggregates.
    combine = compare.locator('select[aria-label="Combine"]')
    assert combine.input_value() == "mean"
    offered = combine.locator("option").evaluate_all("(options) => options.map((o) => [o.value, o.textContent])")
    assert offered[-1] == ["none", "None"], offered
    # The means, 5.5 and 2.75: one bar twice the other.
    _bar_ratio(page, COMPARE, 2.0)
    save_node_closeup(page, CHART_CLOSEUPS, COMPARE, test_name="bars_of_the_means", sweep_toasts=True)

    # None: each scenario's rows stack as they are, 22 against 5.5.
    combine.select_option("none")
    _bar_ratio(page, COMPARE, 4.0)
    _assert_chart_drew(page, COMPARE, "bar")
    assert _written_on(page, COMPARE) == [0, 0], "a bar chart has nothing written on its bars"
    save_node_closeup(page, CHART_CLOSEUPS, COMPARE, test_name="bars_of_each_row", sweep_toasts=True)
    save_dataflow(page)
    project = api_json(f"{current_server}/api/projects/{project_id}", session["token"])
    saved = {n["id"]: n for n in project["spec"]["dataflow"]["nodes"]}
    assert saved[COMPARE]["metadata"]["compareScenarios"] == {
        "inputs": [BASELINE, TWICE],
        "chart": {"preset": "bar", "y": "sunlight", "aggregate": "none"},
    }, saved[COMPARE]["metadata"]

    # A pie of the sums, each slice's value written on it in white.
    compare.locator('select[aria-label="Chart"]').select_option("pie")
    _assert_chart_drew(page, COMPARE, "pie")
    assert combine.input_value() == "sum"
    written = None
    deadline = time.time() + 15
    while time.time() < deadline:
        written = _written_on(page, COMPARE)
        if written and min(written) >= 10:
            break
        page.wait_for_timeout(250)
    assert written and min(written) >= 10, f"the pie's slices hold {written} white pixels of writing, not its values"
    save_node_closeup(page, CHART_CLOSEUPS, COMPARE, test_name="pie_with_its_values", sweep_toasts=True)
