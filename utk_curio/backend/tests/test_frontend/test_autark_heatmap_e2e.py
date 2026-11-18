"""Heatmaps through Autark: a ``heatmap`` source drawn on a map and handed on.

A heatmap bins a table of the document's ``data`` into a grid, through
autk-grammar's own data adapter: the node's run builds it in the sandbox,
which loads the grammar's ``./data`` entry. Four readings at the corners of a
box about 1.1 km by 1.5 km in the Chicago Loop are binned into 3 columns by 2
rows over their extent, each cell counting the readings within 5 km of its
center, all four.

A map draws it as Autark draws any raster, from the node that builds it or
from a node it is handed on to, and a Python node receives it as a
``rasterio`` dataset on its grid, after the layers of the node that built it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_heatmap_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTARK_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/python-computation"

#: The readings, and their heatmap.
DATA = [
    {"type": "geojson", "outputTableName": "readings", "coordinateFormat": "EPSG:4326",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"db": db}}
         for lon, lat, db in ((-87.64, 41.87, 61), (-87.63, 41.87, 74), (-87.64, 41.88, 58), (-87.63, 41.88, 66))
     ]}},
    {"type": "heatmap", "joinDataRef": "readings", "outputTableName": "density",
     "near": {"distance": 5000}, "grid": {"rows": 2, "columns": 3},
     "groupBy": [{"column": "*", "aggregateFn": "count"}]},
]

#: The heatmap drawn by its band's aggregate and table.
MAP = {"layerRefs": [{"dataRef": "density", "getFnv": "count.readings", "colorMapInterpolator": "interpolateReds"}]}

#: The Python node checks what it was handed, so a wrong grid or count fails the node.
PYTHON_READS_HEATMAP = '''import rasterio

heat = [item for item in input_0 if isinstance(item, rasterio.io.DatasetReader)]
assert len(heat) == 1, input_0
heat = heat[0]
assert heat.crs.to_epsg() == 3395, heat.crs
assert (heat.width, heat.height) == (3, 2), (heat.width, heat.height)
counts = heat.read(1)
assert (counts == 4).all(), counts
layers = [item["name"] for item in input_0 if isinstance(item, dict)]
summary = f"heatmap {heat.width}x{heat.height} EPSG:{heat.crs.to_epsg()} of {int(counts.sum())} counts beside {layers}"
print(summary)
return summary
'''


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {
        "id": f"reactflow__edge-{source}out-{target}in",
        "source": source, "target": target, "sourceHandle": "out", "targetHandle": "in",
    }


def _spec(name: str, nodes: list[dict], edges: list[dict]) -> dict:
    return {"dataflow": {"name": name, "task": "", "nodes": nodes, "edges": edges}}


def _enter(page, app_frontend, current_server, *, username: str, spec: dict) -> list[str]:
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Heatmap",
        username=username,
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    return errors


def test_a_heatmap_the_document_builds_draws_on_its_map(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    drawer = "heatmap-own-map"
    errors = _enter(page, app_frontend, current_server, username="autark_heatmap_own", spec=_spec(
        "AutarkHeatmapOnItsMap",
        [_node(drawer, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA, "map": MAP}, indent=2))],
        [],
    ))

    # Fails with the node's own error text if the heatmap is not built or drawn.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a heatmap on its own node's map")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_heatmap_a_data_node_hands_on_draws_on_a_map_and_reaches_python_as_rasterio(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    builder, drawer, reader = "heatmap-data", "heatmap-map", "heatmap-python"
    errors = _enter(page, app_frontend, current_server, username="autark_heatmap_handed", spec=_spec(
        "AutarkHeatmapHandedOn",
        [
            _node(builder, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA}, indent=2)),
            _node(drawer, AUTARK_TYPE, 820, 40, json.dumps({"map": MAP}, indent=2)),
            _node(reader, PYTHON_TYPE, 820, 520, PYTHON_READS_HEATMAP),
        ],
        [_edge(builder, drawer), _edge(builder, reader)],
    ))

    # Plays the data node first, then the map.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a handed-on heatmap on an Autark map")

    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    assert "heatmap 3x2 EPSG:3395 of 24 counts beside ['readings']" in read_node_output_text(page, reader)
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
