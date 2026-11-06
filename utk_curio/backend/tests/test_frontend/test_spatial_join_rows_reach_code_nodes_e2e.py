"""Playwright E2E: a Spatial Join's pairs reach the code nodes it feeds (#1333).

A node that hands on rows as they are, ``{data, dataType}``, reaches a chart or
a Simple View, which read them in the browser, but never a Python or JS node:
the run sends the backend only a stored output, so the code read nothing and
failed with "nothing arrived on input circle 0". komar41's #1333 found it on
a package node with its own interface; the Spatial Join, a built-in node, did
the same.

Two Data Loading nodes feed a Spatial Join (intersects, pairs), which feeds a
Python Computation, a JS Computation and a Simple View. Each code node prints
what arrived on input_0.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_spatial_join_rows_reach_code_nodes_e2e.py -v
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    dismiss_toasts,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

POINTS = "sjr-points"
SQUARE = "sjr-square"
JOIN = "sjr-join"
PYTHON = "sjr-python"
JS = "sjr-js"
VIEW = "sjr-view"

POINTS_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    "    {\"name\": [\"inside\", \"outside\"]},\n"
    "    geometry=[Point(0.5, 0.5), Point(5, 5)],\n"
    "    crs=\"EPSG:4326\",\n"
    ")\n"
)

SQUARE_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import box\n"
    "\n"
    "return gpd.GeoDataFrame({\"zone\": [\"square\"]}, geometry=[box(0, 0, 1, 1)], crs=\"EPSG:4326\")\n"
)

PYTHON_CODE = (
    "print(f\"<<P {type(input_0).__name__} {len(input_0)} \"\n"
    "      f\"{sorted(input_0['name'])} {sorted(input_0['zone'])}>>\")\n"
    "return input_0\n"
)

JS_CODE = (
    "const rows = input_0.features.map(f => `${f.properties.name}/${f.properties.zone}`);\n"
    "console.log(`<<J ${rows.length} ${rows.join(',')}>>`);\n"
    "return input_0;\n"
)


def _node(node_id: str, node_type: str, x: int, y: int, content: str = "") -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "out": "DEFAULT", "in": "DEFAULT", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str, handle: str = "in") -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}{handle}",
        "source": source, "sourceHandle": "out", "target": target, "targetHandle": handle,
    }


def _spec() -> dict:
    return {
        "dataflow": {
            "nodes": [
                _node(POINTS, "curio.builtin/data-loading", 0, 0, POINTS_CODE),
                _node(SQUARE, "curio.builtin/data-loading", 0, 450, SQUARE_CODE),
                _node(JOIN, "curio.builtin/spatial-join", 620, 200),
                _node(PYTHON, "curio.builtin/computation-analysis", 1240, 0, PYTHON_CODE),
                _node(JS, "curio.builtin/js-computation", 1240, 450, JS_CODE),
                _node(VIEW, "curio.builtin/vis-simple", 1240, 900),
            ],
            "edges": [
                _edge(POINTS, JOIN, "in"),
                _edge(SQUARE, JOIN, "in_1"),
                _edge(JOIN, PYTHON),
                _edge(JOIN, JS),
                _edge(JOIN, VIEW),
            ],
            "name": "Spatial Join rows reach code nodes",
            "task": "Pairs points with a square and reads the pairs in Python and JavaScript.",
            "packages": [],
        }
    }


@pytest.fixture()
def join_canvas(app_frontend: "FrontendPage", current_server, page):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Spatial Join Rows",
        username=f"sjr_{uuid.uuid4().hex[:10]}",
        project_name="Spatial Join rows reach code nodes",
        project_spec=_spec(),
    )
    require_owner_view(page)
    node_locator(page, PYTHON).wait_for(state="visible", timeout=45000)
    dismiss_toasts(page)
    return page


def _wait_for_output(page, node_id: str, node_type: str, needle: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(node_type),
        )
    except Exception:
        raise AssertionError(
            f"{node_id} never printed {needle!r}; its output reads {read_node_output_text(page, node_id)!r}"
        ) from None


def test_a_spatial_joins_pairs_reach_python_and_javascript(join_canvas):
    """#1333: input_0 is the join's one pair, in Python as a GeoDataFrame and
    in JavaScript as its features, as the Simple View shows it."""
    page = join_canvas

    play_node(page, PYTHON)
    wait_for_node_done(page, JOIN, node_type="SPATIAL_JOIN", timeout_ms=240000)
    status = node_locator(page, JOIN).locator("[data-curio-spatial-join-status]")
    status.wait_for(state="visible", timeout=30000)
    assert status.inner_text() == "1 pair: 1 of 2 input_0 rows matched.", status.inner_text()
    _wait_for_output(page, PYTHON, "COMPUTATION_ANALYSIS", "<<P GeoDataFrame 1 ['inside'] ['square']>>")
    wait_for_node_done(page, PYTHON, node_type="COMPUTATION_ANALYSIS", timeout_ms=120000)

    play_node(page, JS)
    _wait_for_output(page, JS, "JS_COMPUTATION", "<<J 1 inside/square>>")
    wait_for_node_done(page, JS, node_type="JS_COMPUTATION", timeout_ms=120000)

    wait_for_node_settled(page, VIEW, node_type="VIS_SIMPLE", timeout_ms=120000)
    node_locator(page, VIEW).get_by_text("inside", exact=True).first.wait_for(state="visible", timeout=30000)
    assert "outside" not in node_locator(page, VIEW).inner_text()
