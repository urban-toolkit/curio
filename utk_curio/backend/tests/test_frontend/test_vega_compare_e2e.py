"""SCOUT's three examples, their charts drawn by Vega-Lite nodes comparing the scenarios.

The shipped test dataflows ``FloodScenarios.json``, ``WhatIfShadows.json`` and
``WeatherRouting.json`` chart their scenarios with Vega-Lite nodes whose
Compare scenarios switch is on (``metadata.vegaCompare``):
each input circle one scenario, read as the stacked table ``scenarios``
(``utils/vegaCompare.ts``). Flood's is a table, WhatIfShadows' a pie, and
WeatherRouting's four bar charts. Run All drives each:

1. The Vega-Lite nodes draw, each scenario's mark in its scenario's color.
2. Each node's strip ticks every scenario, its input having what the spec
   reads; the Compare scenarios switch, in Node settings, is on.
3. A spec reading a column no scenario has: the strip crosses every scenario,
   and each input circle names the column.

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
    set_node_code,
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
    assert all(node["metadata"]["vegaCompare"] == {"enabled": True} for node in vegas)
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

        # 2. The strip: each scenario, and every column the spec reads of it, there.
        strip = node_locator(page, node["id"]).locator("[data-vega-compare-strip]")
        strip.wait_for(state="visible", timeout=15000)
        rows = strip.locator("[data-vega-compare-row]")
        assert rows.count() == len(colors)
        assert sorted(rows.nth(i).inner_text().replace("✓", "").strip() for i in range(rows.count())) == sorted(colors)
        assert strip.locator('[data-ok="true"]').count() == len(colors)

    # The switch is in the node's settings, on.
    frame_nodes(page, [vegas[0]["id"]])
    node_locator(page, vegas[0]["id"]).get_by_role("button", name="Node settings", exact=False).first.click()
    toggle = page.locator("[data-vega-compare-toggle]")
    toggle.wait_for(state="visible", timeout=10000)
    assert toggle.is_checked()
    page.get_by_role("button", name="Cancel", exact=True).click()

    # 3. A spec reading a column no scenario has: every scenario lacks it, and
    #    each circle says so.
    first = vegas[0]
    # Every place the spec reads its first value, whatever its chart.
    broken = first["content"].replace(COPIES[name][0], "no such column")
    assert broken != first["content"]
    frame_nodes(page, [first["id"]])
    _open_tab(page, first["id"], "grammar")
    set_node_code(page, first["id"], broken)
    # The strip is above the chart, on the Output tab.
    _open_tab(page, first["id"], "output")
    node = node_locator(page, first["id"])
    strip = node.locator("[data-vega-compare-strip]")
    crossed = strip.locator('[data-ok="false"][data-missing="no such column"]')
    crossed.first.wait_for(state="visible", timeout=10000)
    assert crossed.count() == len(colors)
    for slot in range(len(colors)):
        handle = node.locator(f'.react-flow__handle[data-handleid="{"in" if slot == 0 else f"in_{slot}"}"]')
        assert "missing: no such column" in (handle.get_attribute("title") or "")
        assert "rgb(192, 57, 43)" in handle.evaluate("el => getComputedStyle(el).boxShadow")


def _two_scenario_flow() -> dict:
    """Two scenarios, each a table of one number, into one Vega-Lite node comparing them."""
    a, b, vega = "11111111-0000-4000-8000-00000000000a", "11111111-0000-4000-8000-00000000000b", "11111111-0000-4000-8000-00000000000c"

    def table(node_id: str, value: int, y: int) -> dict:
        return {
            "id": node_id, "type": "curio.builtin/data-loading", "x": 0, "y": y,
            "content": f"import pandas as pd\nreturn pd.DataFrame({{'v': [{value}]}})",
            "out": "DEFAULT", "in": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        }

    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "mark": "bar",
        "encoding": {
            "x": {"field": "scenario_name", "type": "nominal"},
            "y": {"field": "v", "type": "quantitative"},
            "color": {"field": "scenario_name", "type": "nominal", "legend": None},
        },
    }
    return {"dataflow": {
        "categories": {}, "name": "VegaCompareToggle", "task": "", "timestamp": 0, "provenance_id": "VegaCompareToggle",
        "nodes": [
            table(a, 3, 0), table(b, 5, 400),
            {"id": vega, "type": VEGA_TYPE, "x": 700, "y": 100, "content": json.dumps(spec, indent=2),
             "out": "DEFAULT", "in": "DEFAULT", "goal": "", "metadata": {"keywords": [], "vegaCompare": {"enabled": True}}},
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


def _open_tab(page, node_id: str, key: str) -> None:
    tab = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{key}"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")


def _set_compare(page, node_id: str, on: bool) -> None:
    frame_nodes(page, [node_id])
    node_locator(page, node_id).get_by_role("button", name="Node settings", exact=False).first.click()
    toggle = page.locator("[data-vega-compare-toggle]")
    toggle.wait_for(state="visible", timeout=10000)
    if toggle.is_checked() != on:
        toggle.click()
    page.get_by_role("button", name="Cancel", exact=True).click()


def test_compare_switched_off_and_on_again(app_frontend: "FrontendPage", current_server: str, page):
    """Off, the node is a plain Vega-Lite node over its first input; on again,
    and run again, it compares the scenarios as before."""
    require_project_page()
    require_user_auth()
    spec = _two_scenario_flow()
    stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server, name="VegaCompareToggle",
        username="vega_compare_toggle", project_name="VegaCompareToggle", project_spec=spec,
    )
    require_owner_view(page)
    vega = spec["dataflow"]["nodes"][2]["id"]
    node_locator(page, vega).wait_for(state="visible", timeout=45000)

    def drawn(color: str) -> int:
        return page.evaluate(_PIXELS_OF_JS, [vega, color])

    def run():
        run_all_and_wait(page, timeout_ms=120000)
        status = wait_for_node_settled(page, vega, node_type=VEGA_TYPE, timeout_ms=60000)
        assert status == "done", read_node_error_text(node_locator(page, vega))
        frame_nodes(page, [vega])
        assert_vega_canvas_rendered(page, vega)

    run()
    assert drawn("#e76f51") > 50 and drawn("#2a9d8f") > 50
    assert node_locator(page, vega).locator("[data-vega-compare-strip]").count() == 1

    _set_compare(page, vega, False)
    run()
    assert node_locator(page, vega).locator("[data-vega-compare-strip]").count() == 0
    assert drawn("#2a9d8f") == 0, "switched off, the chart still draws the second scenario"

    _set_compare(page, vega, True)
    run()
    assert drawn("#e76f51") > 50 and drawn("#2a9d8f") > 50, "switched on again, the chart does not compare"
    assert node_locator(page, vega).locator('[data-vega-compare-strip] [data-ok="true"]').count() == 2
