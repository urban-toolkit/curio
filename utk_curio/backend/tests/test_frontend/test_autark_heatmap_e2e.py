"""Heatmaps through Autark: a ``heatmap`` source drawn on a map and handed on.

A heatmap bins a table of the document's ``data`` into a grid, through
autk-grammar's own data adapter: the node's run builds it in the sandbox,
which loads the grammar's ``./data`` entry. Sound levels in a box 3 km by 2 km
at the Chicago Loop, in EPSG:3395 metres, are binned into 3 columns by 2 rows
of 1 km over their extent. Each cell aggregates the readings within 600 m of
its center: the two at the box's corners lie 707 m from every center, and the
others lie within 100 m of their own cell's center, none to four a cell. One
heatmap builds a band per aggregate (``count``, ``weighted``, ``sum``,
``avg``, ``min`` and ``max``), whose cells this module computes from the
readings.

A map draws it as Autark draws any raster, from the node that builds it or
from a node it is handed on to, its cells in colours that follow their values;
and a Python node receives it as a ``rasterio`` dataset on its grid, a band
per aggregate named by its label, after the layers of the node that built it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_heatmap_e2e.py -v
"""
from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    assert_raster_cells_follow_their_values,
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

#: The box's south-west corner, in EPSG:3395 metres, and each reading's place
#: east and north of it, then its level in decibels.
LOOP = (-9755000.0, 5106000.0)
LEVELS = [
    (0, 0, 40), (3000, 2000, 95),
    (500, 500, 50),
    (1500, 500, 60), (1600, 500, 70),
    (500, 1500, 55), (600, 1500, 58), (400, 1500, 61),
    (1500, 1500, 62), (1600, 1500, 66), (1400, 1500, 70), (1500, 1600, 74),
    (2500, 1500, 80), (2500, 1600, 84),
]
AGGREGATES = ["count", "weighted", "sum", "avg", "min", "max"]
#: How far a cell's center reaches, and the grid's rows, columns and cell size.
REACH, ROWS, COLUMNS, CELL = 600.0, 2, 3, 1000.0


def _cells_from_the_levels() -> dict[str, list[list[float]]]:
    """Each aggregate's cells, the north row first, computed from ``LEVELS``:
    the readings within ``REACH`` of a cell's center, counted, weighted
    1 / (distance + 1) each, or their levels summed, averaged, or their least
    and greatest; 0 for a cell none reaches."""
    cells = {fn: [[0.0] * COLUMNS for _ in range(ROWS)] for fn in AGGREGATES}
    for row in range(ROWS):
        for column in range(COLUMNS):
            center = ((column + 0.5) * CELL, (ROWS - row - 0.5) * CELL)
            near = [(math.dist((east, north), center), db) for east, north, db in LEVELS]
            near = [(distance, db) for distance, db in near if distance <= REACH]
            if not near:
                continue
            levels = [db for _distance, db in near]
            cells["count"][row][column] = len(near)
            cells["weighted"][row][column] = sum(1 / (distance + 1) for distance, _db in near)
            cells["sum"][row][column] = sum(levels)
            cells["avg"][row][column] = sum(levels) / len(levels)
            cells["min"][row][column] = min(levels)
            cells["max"][row][column] = max(levels)
    return cells


CELLS = _cells_from_the_levels()

#: The readings, and their heatmap, a band per aggregate.
DATA = [
    {"type": "geojson", "outputTableName": "levels", "coordinateFormat": "EPSG:3395",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LOOP[0] + east, LOOP[1] + north]},
          "properties": {"db": db}}
         for east, north, db in LEVELS
     ]}},
    {"type": "heatmap", "joinDataRef": "levels", "outputTableName": "noise",
     "near": {"distance": REACH}, "grid": {"rows": ROWS, "columns": COLUMNS},
     "groupBy": [{"column": "*" if fn in ("count", "weighted") else "db", "aggregateFn": fn} for fn in AGGREGATES]},
]


def _map(aggregate: str) -> dict:
    """A map of the heatmap's band for *aggregate*, named by its aggregate and table."""
    return {"layerRefs": [{"dataRef": "noise", "getFnv": f"{aggregate}.levels", "colorMapInterpolator": "interpolateReds"}]}


#: The Python node checks what it was handed, so a wrong grid, band or cell fails the node.
PYTHON_READS_HEATMAP = f'''import numpy as np
import rasterio

heat = [item for item in input_0 if isinstance(item, rasterio.io.DatasetReader)]
assert len(heat) == 1, input_0
heat = heat[0]
assert heat.crs.to_epsg() == 3395, heat.crs
assert (heat.count, heat.width, heat.height) == ({len(AGGREGATES)}, {COLUMNS}, {ROWS}), (heat.count, heat.width, heat.height)
labels = {tuple(f"{fn}_levels" for fn in AGGREGATES)!r}
expected = {json.dumps({f"{fn}_levels": cells for fn, cells in CELLS.items()})}
for index, label in enumerate(labels, start=1):
    assert np.allclose(heat.read(index), expected[label], rtol=1e-6), (label, heat.read(index).tolist())
assert heat.descriptions == labels, heat.descriptions


def layer_name(item):
    if isinstance(item, dict):
        return item.get("name")
    metadata = getattr(item, "metadata", None)
    return metadata.get("name") if isinstance(metadata, dict) else None


layers = [layer_name(item) for item in input_0 if not isinstance(item, rasterio.io.DatasetReader)]
summary = f"heatmap {{heat.width}}x{{heat.height}} EPSG:{{heat.crs.to_epsg()}}, avg {{heat.read(4).tolist()}} beside {{layers}}"
print(summary)
return summary
'''


#: The readings as a Python node returns them: a GeoDataFrame in EPSG:3395,
#: the table its Autark node reads as ``input_0``.
PYTHON_RETURNS_THE_LEVELS = f'''import geopandas as gpd
from shapely.geometry import Point

levels = {json.dumps([[LOOP[0] + east, LOOP[1] + north, db] for east, north, db in LEVELS])}
return gpd.GeoDataFrame(
    {{"db": [db for _x, _y, db in levels]}},
    geometry=[Point(x, y) for x, y, _db in levels],
    crs="EPSG:3395",
)
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


def test_a_heatmap_the_document_builds_draws_its_cells_by_their_values_on_its_map(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    drawer = "heatmap-own-map"
    errors = _enter(page, app_frontend, current_server, username="autark_heatmap_own", spec=_spec(
        "AutarkHeatmapOnItsMap",
        [_node(drawer, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA, "map": _map("avg")}, indent=2))],
        [],
    ))

    # Fails with the node's own error text if the heatmap is not built or drawn.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a heatmap on its own node's map")
    # Each reading's level averaged in its cell: every cell a value of its own.
    assert_raster_cells_follow_their_values(page, drawer, CELLS["avg"], attach_as="a heatmap's avg cells")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_heatmap_a_data_node_hands_on_draws_by_its_values_and_reaches_python_as_rasterio(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    builder, drawer, reader = "heatmap-data", "heatmap-map", "heatmap-python"
    errors = _enter(page, app_frontend, current_server, username="autark_heatmap_handed", spec=_spec(
        "AutarkHeatmapHandedOn",
        [
            _node(builder, AUTARK_TYPE, 120, 160, json.dumps({"data": DATA}, indent=2)),
            _node(drawer, AUTARK_TYPE, 820, 40, json.dumps({"map": _map("count")}, indent=2)),
            _node(reader, PYTHON_TYPE, 820, 520, PYTHON_READS_HEATMAP),
        ],
        [_edge(builder, drawer), _edge(builder, reader)],
    ))

    # Plays the data node first, then the map.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a handed-on heatmap on an Autark map")
    # The readings counted in each cell: two cells count 2 and share a colour.
    assert_raster_cells_follow_their_values(page, drawer, CELLS["count"], attach_as="a handed-on heatmap's count cells")

    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    assert (
        f"heatmap {COLUMNS}x{ROWS} EPSG:3395, avg {CELLS['avg']} beside ['levels']"
        in read_node_output_text(page, reader)
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_heatmap_of_the_points_a_python_node_returns_draws_their_cells_by_their_values(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The heatmap bins the node's input, the readings a Python node returns,
    as ``input_0``: the node loads them into its data section's database and
    bins them there, so each cell averages the readings near it."""
    maker, drawer = "heatmap-readings", "heatmap-of-the-input"
    heatmap = {**DATA[1], "joinDataRef": "input_0"}
    # The band of the readings' average, the fourth aggregate.
    layer = {"dataRef": "noise", "getFnv": f"band_{AGGREGATES.index('avg') + 1}", "colorMapInterpolator": "interpolateReds"}
    errors = _enter(page, app_frontend, current_server, username="autark_heatmap_input", spec=_spec(
        "AutarkHeatmapOfItsInput",
        [
            _node(maker, PYTHON_TYPE, 120, 160, PYTHON_RETURNS_THE_LEVELS),
            _node(drawer, AUTARK_TYPE, 820, 160, json.dumps({"data": [heatmap], "map": {"layerRefs": [layer]}}, indent=2)),
        ],
        [_edge(maker, drawer)],
    ))

    # Plays the Python node first, then the map.
    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a heatmap of a Python node's readings")
    # Each reading's level averaged in its cell: every cell a value of its own.
    assert_raster_cells_follow_their_values(page, drawer, CELLS["avg"], attach_as="a heatmap of the input's avg cells")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors
