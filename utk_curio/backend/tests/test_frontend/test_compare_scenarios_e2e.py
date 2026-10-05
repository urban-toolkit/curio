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
    connect_nodes,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
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
SHADE_CODE = 'df = arg.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\nreturn df\n'
TALL_CODE = 'df = arg.copy()\ndf["sunlight"] = df["sunlight"] / [!! factor !!]\ndf = df.round(2)\nreturn df\n'
CLIP_CODE = 'df = arg.copy()\ndf["sunlight"] = df["sunlight"].clip(lower=0)\nreturn df\n'

# The lines the node writes for its two inputs (utils/compare/compareCode.ts).
ENTRY_LINES = (
    '    ("s-base", "Baseline", [!! input 0 !!]),',
    '    ("s-tall", "Twice as tall", [!! input 1 !!]),',
)


def _factor(value: int) -> dict:
    return {"widgets": [{"name": "factor", "type": "number", "default": 1, "value": value}]}


def _spec() -> dict:
    def node(node_id, node_type, x, y, content, title=None, metadata=None, **fields):
        saved = {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": [], **(metadata or {})}, **fields,
        }
        if title:
            saved["title"] = title
        return saved

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

    # 1. The palette offers it.
    page.locator("#tile-compare-scenarios").wait_for(state="visible", timeout=15000)

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
        "Input 1 (Twice as tall) and input 0 (Baseline) read different context: only input 1 reads Roads 2050."
    ], warning.all_inner_texts()
    _assert_chart_drew(page, COMPARE, "lollipop")

    save_node_closeup(
        page, "compare-scenarios", COMPARE,
        test_name="test_two_scenarios_are_stacked_charted_and_compared",
        sweep_toasts=True,
    )
