"""Playwright E2E: Compare Scenarios is gone (step 6.4 of the plan answering
komar41's review of the #914 merges).

* The Built-in palette has no Compare Scenarios tile.
* A dataflow saved with a Compare Scenarios node opens with that node as a
  type no installed package provides, as a node of any such type opens: the
  "Missing node package" card, titled with the type. Nothing aliases or
  migrates it. Its connections are drawn, since the card has a handle for
  each port its edges name, and every other node opens as it was saved.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_compare_scenarios_removed_e2e.py -v
"""
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    dismiss_toasts,
    node_locator,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The type a saved Compare Scenarios node carries.
COMPARE_TYPE = "curio.builtin/compare-scenarios"
#: A type of a package nothing provides, for the card any missing type gets.
NOWHERE_TYPE = "curio.nowhere/missing-node"

LOADER = "cmp-gone-loader"
COMPARE = "cmp-gone-compare"
CHART = "cmp-gone-chart"
NOWHERE = "cmp-gone-nowhere"

LOADER_CODE = (
    "import pandas as pd\n"
    "\n"
    "return pd.DataFrame({'category': ['a', 'b', 'c'], 'count': [3, 7, 5]})\n"
)
#: What a Compare Scenarios node saved: the code it wrote for its one input,
#: and that input's label.
COMPARE_CODE = (
    "# Compare Scenarios writes this code from its inputs: each input, under the\n"
    "# id and the name of its scenario. It is written again when they change.\n"
    "return curio_stack_scenarios([\n"
    '    (None, "Data Loading", [!! input_0 !!]),\n'
    "])\n"
)
COMPARE_SETTINGS = {
    "inputs": [{"name": "Data Loading", "color": "#9e9e9e"}],
    "chart": {"preset": "bar", "x": "category", "y": "count", "aggregate": "mean"},
}
CHART_SPEC = json.dumps({
    "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
    "mark": "bar",
    "encoding": {
        "x": {"field": "category", "type": "nominal"},
        "y": {"field": "count", "type": "quantitative"},
    },
}, indent=2)

#: The saved connections, by id: the loader into the Compare node, and the
#: Compare node into the chart.
EDGES = {
    f"reactflow__edge-{LOADER}out-{COMPARE}in": (LOADER, COMPARE),
    f"reactflow__edge-{COMPARE}out-{CHART}in": (COMPARE, CHART),
}

#: What a node opened as: its package's body, one of the two cards a node
#: whose type nothing provides gets, or null while it is still loading.
_OPENED_AS_JS = """(id) => {
    const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
    if (!node) return null;
    if (node.querySelector('[data-testid="unresolved-node"]')) return 'missing package';
    if (node.querySelector('[data-testid="unrecognized-node"]')) return 'unrecognized type';
    if (node.querySelector('[data-curio-node-status]')) return 'its own body';
    return null;
}"""


def _node(node_id: str, node_type: str, content: str, x: int, y: int = 0, metadata: dict | None = None) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": [], **(metadata or {})},
        "content": content,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Compare Scenarios removed e2e",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(LOADER, "curio.builtin/data-loading", LOADER_CODE, 0),
                _node(COMPARE, COMPARE_TYPE, COMPARE_CODE, 700, metadata={"compareScenarios": COMPARE_SETTINGS}),
                _node(CHART, "curio.builtin/vis-vega", CHART_SPEC, 1400),
                _node(NOWHERE, NOWHERE_TYPE, "", 700, 600),
            ],
            "edges": [
                {"id": edge_id, "source": source, "target": target}
                for edge_id, (source, target) in EDGES.items()
            ],
        },
    }


def _enter(page, app_frontend, current_server, *, prefix: str, spec: dict | None = None) -> None:
    """Sign in as a fresh owner, on the canvas of a fresh dataflow saved as
    *spec* (an empty one by default)."""
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Compare Gone",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name="Compare Scenarios removed e2e",
        project_spec=spec,
    )
    require_owner_view(page)
    dismiss_toasts(page)


def _opened_as(page, node_id: str, *, timeout_ms: int = 45000) -> str:
    """What *node_id* opened as, once it is no longer loading."""
    return page.wait_for_function(_OPENED_AS_JS, arg=node_id, timeout=timeout_ms).json_value()


def test_the_built_in_palette_has_no_compare_scenarios_tile(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="cmp_gone_palette")
    panel = open_tools_palette(page, "builtin")
    # The registry has answered once the Interaction node's tile is there.
    expect(panel.locator("#tile-edit-features")).to_be_visible(timeout=30000)
    tiles = panel.locator('[id^="tile-"]').evaluate_all("(tiles) => tiles.map((tile) => tile.id)")
    assert "tile-compare-scenarios" not in tiles, f"the Built-in palette holds Compare Scenarios: {tiles}"
    expect(panel.get_by_label("Compare Scenarios", exact=True)).to_have_count(0)


def test_a_dataflow_saved_with_a_compare_scenarios_node_opens_with_it_as_a_missing_type(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="cmp_gone_saved", spec=_spec())
    page.wait_for_selector(".react-flow__node", timeout=45000)

    opened = {node_id: _opened_as(page, node_id) for node_id in (LOADER, CHART, NOWHERE, COMPARE)}
    assert opened == {
        LOADER: "its own body",
        CHART: "its own body",
        NOWHERE: "missing package",
        COMPARE: "missing package",
    }, f"the saved Compare Scenarios node should open as a type no package provides, as {NOWHERE_TYPE} does: {opened}"

    card = node_locator(page, COMPARE).get_by_test_id("unresolved-node")
    expect(card).to_have_attribute("title", f"No installed package provides {COMPARE_TYPE}")
    expect(card).to_contain_text("Missing node package")
    expect(node_locator(page, COMPARE).get_by_role("tab", name="What differs")).to_have_count(0)

    # Its connections are drawn, from the loader and to the chart.
    for edge_id in EDGES:
        path = page.locator(f'.react-flow__edge[data-testid="rf__edge-{edge_id}"] path.react-flow__edge-path')
        expect(path).to_have_count(1, timeout=15000)
        assert (path.get_attribute("d") or "").strip(), f"the connection {edge_id} has no path"
