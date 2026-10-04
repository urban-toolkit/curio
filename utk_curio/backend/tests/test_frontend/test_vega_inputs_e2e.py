"""Playwright E2E: a Vega-Lite chart drawn from two inputs (#662).

Two loaders feed one Vega-Lite node, the second edge on the circle the first
one made. The spec layers a bar per zone of the first input under a red point
per zone of the second, which it reads through the chip ``[!! input 1 !!]``;
the bars name their columns through column chips. In the browser the chips are
``"input_1"`` and the column names, and each input is the Vega dataset
``input_0`` or ``input_1``.

Before, a Vega-Lite node held one input, injected as the dataset ``data``: a
second edge was refused and pointed at a Merge Flow node.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_vega_inputs_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .utils import (
    assert_vega_canvas_rendered,
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

POP_ID = "vega-inputs-pop"
INCOME_ID = "vega-inputs-income"
CHART_ID = "vega-inputs-chart"

POP_LOADER = (
    "import pandas as pd\n"
    "\n"
    'return pd.DataFrame({"zone": ["n", "s", "e"], "pop": [3, 5, 4]})\n'
)
INCOME_LOADER = (
    "import pandas as pd\n"
    "\n"
    'return pd.DataFrame({"zone": ["n", "s", "e"], "income": [2, 4, 1]})\n'
)
# A chip outside quotes stands for a quoted name.
LAYERED = """{
  "layer": [
    {
      "mark": "bar",
      "encoding": {
        "x": {"field": [!! input 0.zone !!], "type": "nominal"},
        "y": {"field": [!! input 0.pop !!], "type": "quantitative"}
      }
    },
    {
      "data": {"name": [!! input 1 !!]},
      "mark": {"type": "point", "filled": true, "size": 400, "color": "#ff0000", "opacity": 1},
      "encoding": {
        "x": {"field": "zone", "type": "nominal"},
        "y": {"field": "income", "type": "quantitative"}
      }
    }
  ]
}"""

# Pixels of each layer's colour on the chart's canvas: the bars are Vega-Lite's
# default blue (#4c78a8), the points pure red.
_LAYER_PIXELS_JS = """(containerId) => {
    const canvas = document.querySelector(`#${containerId} canvas`);
    if (!canvas || !canvas.width || !canvas.height) return null;
    const { data } = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height);
    let bar = 0, point = 0;
    for (let i = 0; i < data.length; i += 4) {
        const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]];
        if (a < 200) continue;
        if (Math.abs(r - 76) < 12 && Math.abs(g - 120) < 12 && Math.abs(b - 168) < 12) bar += 1;
        if (r > 220 && g < 40 && b < 40) point += 1;
    }
    return { bar, point };
}"""


def _spec() -> dict:
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Vega-Lite inputs",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Vega-Lite inputs",
            "nodes": [
                node(POP_ID, "curio.builtin/data-loading", 0, 0, POP_LOADER),
                node(INCOME_ID, "curio.builtin/data-loading", 0, 520, INCOME_LOADER),
                node(CHART_ID, "curio.builtin/vis-vega", 645, 0, LAYERED),
            ],
            "edges": [
                {"id": f"reactflow__edge-{POP_ID}out-{CHART_ID}in",
                 "source": POP_ID, "target": CHART_ID, "targetHandle": "in"},
                {"id": f"reactflow__edge-{INCOME_ID}out-{CHART_ID}in_1",
                 "source": INCOME_ID, "target": CHART_ID, "targetHandle": "in_1"},
            ],
        }
    }


def test_a_layered_chart_draws_one_layer_from_each_input(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = _spec()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Vega Inputs",
        username="vega_inputs_layered",
        project_name="Vega-Lite inputs",
        project_spec=spec,
    )
    require_owner_view(page)
    for node in spec["dataflow"]["nodes"]:
        node_locator(page, node["id"]).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    status = wait_for_node_settled(page, CHART_ID, node_type="vis-vega", timeout_ms=120000)
    detail = read_node_error_text(node_locator(page, CHART_ID)) if status == "error" else ""
    assert status == "done", f"the chart did not draw: {detail}"

    assert_vega_canvas_rendered(page, CHART_ID)
    # Three bars and three points, each well past a stray anti-aliased edge.
    deadline = time.monotonic() + 30
    while True:
        counts = page.evaluate(_LAYER_PIXELS_JS, f"vega{CHART_ID}")
        drawn = bool(counts) and counts["bar"] > 300 and counts["point"] > 100
        if drawn or time.monotonic() >= deadline:
            break
        page.wait_for_timeout(500)
    assert drawn, f"each input's layer should show on the canvas: {counts}"
