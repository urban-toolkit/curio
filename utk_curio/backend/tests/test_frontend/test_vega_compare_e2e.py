"""SCOUT's three examples, their charts drawn by plain Vega-Lite nodes comparing the scenarios.

The shipped test dataflows ``FloodScenarios.json``, ``WhatIfShadows.json`` and
``WeatherRouting.json`` chart their scenarios with Vega-Lite nodes whose spec
reads all their inputs stacked, the dataset ``inputs`` (each row's
``__input__`` its circle, ``utils/vegaDatasets.ts``), and names each circle's
scenario and color itself. Flood's is a table, WhatIfShadows' a pie, and
WeatherRouting's four bar charts. Run All drives each, and every chart draws
each scenario's mark in its scenario's color.

A two-input node shows the same without a shipped dataflow: a spec over
``inputs`` draws both inputs, and one naming no data reads its first input.

The dataflows draw their Autark maps too, so this runs where WebGPU is.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_vega_compare_e2e.py -v
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    assert_vega_canvas_rendered,
    frame_nodes,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOWS = Path(REPO_ROOT) / "docs" / "examples" / "dataflows"
VEGA_TYPE = "curio.builtin/vis-vega"

#: Per copy, what its Vega-Lite nodes' specs read of every scenario.
COPIES = {
    "FloodScenarios": ["median flood depth", "mean flood depth"],
    "WhatIfShadows": ["Mean Acc shadow"],
    "WeatherRouting": ["duration", "distance", "rain_exposure", "wind_exposure"],
}

#: How many of the canvas's pixels are within a few levels of *color*.
_PIXELS_OF_JS = """
([nodeId, color]) => {
  const canvas = document.querySelector(`#vega${CSS.escape(nodeId)} canvas`);
  if (!canvas) return -1;
  const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  let n = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (Math.abs(data[i] - r) < 6 && Math.abs(data[i + 1] - g) < 6 && Math.abs(data[i + 2] - b) < 6) n += 1;
  }
  return n;
}
"""


def _scenario_colors(spec: dict) -> dict[str, str]:
    return {scenario["name"]: scenario["color"] for scenario in spec["dataflow"]["scenarios"]}


@pytest.mark.parametrize("name", list(COPIES))
def test_vega_lite_nodes_compare_the_scenarios(
    name: str, app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads((DATAFLOWS / f"{name}.json").read_text(encoding="utf-8"))
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=f"vega_compare_{name.lower()}",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    vegas = [node for node in spec["dataflow"]["nodes"] if node["type"].split("@")[0] == VEGA_TYPE]
    assert len(vegas) == (4 if name == "WeatherRouting" else 1)
    assert all(json.loads(node["content"])["data"] == {"name": "inputs"} for node in vegas)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)
    colors = _scenario_colors(spec)

    # 1. Run All: every chart draws, each scenario in its color.
    run_all_and_wait(page, timeout_ms=300000)
    for node in vegas:
        status = wait_for_node_settled(page, node["id"], node_type=VEGA_TYPE, timeout_ms=120000)
        assert status == "done", f"{node['title']} did not draw: {read_node_error_text(node_locator(page, node['id']))}"
        frame_nodes(page, [node["id"]])
        assert_vega_canvas_rendered(page, node["id"])
        for scenario, color in colors.items():
            assert page.evaluate(_PIXELS_OF_JS, [node["id"], color]) > 50, f"{node['title']}: nothing in {scenario}'s {color}"


def _two_scenario_flow(spec: dict) -> dict:
    """Two tables of one number each, into one Vega-Lite node drawing *spec*."""
    a, b, vega = "11111111-0000-4000-8000-00000000000a", "11111111-0000-4000-8000-00000000000b", "11111111-0000-4000-8000-00000000000c"

    def table(node_id: str, value: int, y: int) -> dict:
        return {
            "id": node_id, "type": "curio.builtin/data-loading", "x": 0, "y": y,
            "content": f"import pandas as pd\nreturn pd.DataFrame({{'v': [{value}]}})",
            "out": "DEFAULT", "in": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        }

    return {"dataflow": {
        "categories": {}, "name": "VegaTwoInputs", "task": "", "timestamp": 0, "provenance_id": "VegaTwoInputs",
        "nodes": [
            table(a, 3, 0), table(b, 5, 400),
            {"id": vega, "type": VEGA_TYPE, "x": 700, "y": 100, "content": json.dumps(spec, indent=2),
             "out": "DEFAULT", "in": "DEFAULT", "goal": "", "metadata": {"keywords": []}},
        ],
        "edges": [
            {"id": f"reactflow__edge-{a}out-{vega}in", "source": a, "target": vega, "sourceHandle": "out", "targetHandle": "in"},
            {"id": f"reactflow__edge-{b}out-{vega}in_1", "source": b, "target": vega, "sourceHandle": "out", "targetHandle": "in_1"},
        ],
        "scenarios": [
            {"id": "low", "name": "Low", "color": "#e76f51", "nodes": [a]},
            {"id": "high", "name": "High", "color": "#2a9d8f", "nodes": [b]},
        ],
    }}


#: Bars of each input's number, colored by the scenario the spec names from
#: the circle each row came in on.
_SCENARIO_BARS = {
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "data": {"name": "inputs"},
    "transform": [{"calculate": "['Low', 'High'][datum.__input__]", "as": "scenario_name"}],
    "mark": "bar",
    "encoding": {
        "x": {"field": "scenario_name", "type": "nominal"},
        "y": {"field": "v", "type": "quantitative"},
        "color": {"field": "scenario_name", "type": "nominal", "legend": None,
                  "scale": {"domain": ["Low", "High"], "range": ["#e76f51", "#2a9d8f"]}},
    },
}


@pytest.mark.parametrize("over_inputs", [True, False])
def test_a_spec_names_its_scenarios_over_the_stacked_inputs(
    over_inputs: bool, app_frontend: "FrontendPage", current_server: str, page,
):
    """Over ``inputs``, both inputs draw, each in the color its spec names;
    naming no data, the spec reads its first input only."""
    require_project_page()
    require_user_auth()
    chart = dict(_SCENARIO_BARS)
    if not over_inputs:
        chart.pop("data")
        chart["transform"] = [{"calculate": "'Low'", "as": "scenario_name"}]
    spec = _two_scenario_flow(chart)
    name = f"VegaTwoInputs{'Stacked' if over_inputs else 'First'}"
    stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server, name=name,
        username=f"vega_two_inputs_{int(over_inputs)}", project_name=name, project_spec=spec,
    )
    require_owner_view(page)
    vega = spec["dataflow"]["nodes"][2]["id"]
    node_locator(page, vega).wait_for(state="visible", timeout=45000)
    run_all_and_wait(page, timeout_ms=120000)
    status = wait_for_node_settled(page, vega, node_type=VEGA_TYPE, timeout_ms=60000)
    assert status == "done", read_node_error_text(node_locator(page, vega))
    frame_nodes(page, [vega])
    assert_vega_canvas_rendered(page, vega)
    assert page.evaluate(_PIXELS_OF_JS, [vega, "#e76f51"]) > 50
    second = page.evaluate(_PIXELS_OF_JS, [vega, "#2a9d8f"])
    assert (second > 50) if over_inputs else (second == 0)
