"""autk-grammar 5.5.0's ``writeBack`` and sources ``after: 'compute'``, run by
Autark nodes.

A pass with ``writeBack`` keeps its result in autk-db, and a source with
``after: 'compute'`` runs once every pass has run, so it reads what the passes
kept there. A node loads its sources before compute where it loads its data
section, and runs those after compute in the browser once its passes have run:
a map node in the grammar's own run, a compute step on a database of its own.

- A map node's data section loads sound levels in a box 3 km by 2 km at the
  Chicago Loop, in EPSG:3395 metres, a GPGPU pass copies each reading into a
  table of its own and keeps it in autk-db, and a heatmap after compute, which
  writes no ``groupBy``, counts the readings of that table near each cell of 3
  columns by 2 rows of 1 km (autk-grammar 5.5.0 hands autk-db the count). The
  map draws the heatmap alone, a raster the grammar's run made, which no
  outline of Curio's places: autk-grammar 5.5.1 places a map that starts with
  a raster at the raster's middle. Its cells follow their counts, Curio frames
  it, and its R key frames it again after a drag.
- A compute step's clusters pass keeps the blocks of four squares in autk-db,
  a SQL query after compute counts each block's squares, and a table it loads
  after compute is dropped after compute: the step hands on the squares, the
  blocks and the counts, and a Python node reads them.
- A node whose source after compute reads a table a pass writes without
  ``writeBack`` fails before anything runs, in the grammar's words.

The maps and the passes need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_write_back_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING

from .utils import (
    assert_autark_map_drawn,
    assert_raster_cells_follow_their_values,
    node_locator,
    play_node,
    read_node_error_text,
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

AUTARK_TYPE = "curio.builtin/autk-grammar"
PYTHON_TYPE = "curio.builtin/python-computation"

#: The box's south-west corner, in EPSG:3395 metres, and each reading's place
#: east and north of it, then its level in decibels. The two at the box's
#: corners give the workspace its extent and lie 707 m from every cell's center.
LOOP = (-9755000.0, 5106000.0)
LEVELS = [
    (0, 0, 40), (3000, 2000, 95),
    (500, 500, 50),
    (1500, 500, 60), (1600, 500, 70),
    (500, 1500, 55), (600, 1500, 58), (400, 1500, 61),
    (1500, 1500, 62), (1600, 1500, 66), (1400, 1500, 70), (1500, 1600, 74),
    (2500, 1500, 80), (2500, 1600, 84),
]
#: How far a cell's center reaches, and the grid's rows, columns and cell size.
REACH, ROWS, COLUMNS, CELL = 600.0, 2, 3, 1000.0


def _counts() -> list[list[float]]:
    """The readings within ``REACH`` of each cell's center, north row first."""
    cells = [[0.0] * COLUMNS for _ in range(ROWS)]
    for row in range(ROWS):
        for column in range(COLUMNS):
            center = ((column + 0.5) * CELL, (ROWS - row - 0.5) * CELL)
            cells[row][column] = float(sum(
                1 for east, north, _db in LEVELS if math.dist((east, north), center) <= REACH
            ))
    return cells


COUNTS = _counts()

#: The readings, a GPGPU pass that keeps a copy of them in autk-db, and a
#: heatmap after compute of that copy, with no groupBy, drawn alone.
HEATMAP_AFTER_COMPUTE = {
    "data": [
        {"type": "heatmap", "joinDataRef": "copied", "outputTableName": "noise",
         "near": {"distance": REACH}, "grid": {"rows": ROWS, "columns": COLUMNS}, "after": "compute"},
        {"type": "geojson", "outputTableName": "levels", "coordinateFormat": "EPSG:3395",
         "geojsonObject": {"type": "FeatureCollection", "features": [
             {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LOOP[0] + east, LOOP[1] + north]},
              "properties": {"db": db}}
             for east, north, db in LEVELS
         ]}},
    ],
    "compute": [{
        "dataRef": "levels", "attributes": {"db": "db"}, "wgslFunction": "return db;",
        "outputColumnName": "level", "outputTableName": "copied", "layerType": "points", "writeBack": True,
    }],
    "map": {"layerRefs": [{"dataRef": "noise", "getFnv": "count.copied", "colorMapInterpolator": "interpolateReds"}]},
}


def _square(x: float, y: float, side: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[x, y], [x + side, y], [x + side, y + side], [x, y + side], [x, y]]]}


#: Four squares, the first two sharing a wall: three blocks.
SQUARES = [(0, 0), (100, 0), (400, 0), (700, 0)]
BLOCKS = [0, 0, 1, 2]
#: A compute step: the squares' blocks kept in autk-db, counted after compute
#: by a SQL query, and a table loaded after compute, then dropped.
COMPUTE_STEP = {
    "data": [
        {"type": "geojson", "outputTableName": "squares", "coordinateFormat": "EPSG:3395",
         "geojsonObject": {"type": "FeatureCollection", "features": [
             {"type": "Feature", "geometry": _square(LOOP[0] + x, LOOP[1] + y, 100), "properties": {"square": i}}
             for i, (x, y) in enumerate(SQUARES)
         ]}},
        {"type": "sql", "outputTableName": "block_sizes", "after": "compute",
         "query": "SELECT CAST(properties->'compute'->>'block' AS INTEGER) AS block, CAST(count(*) AS INTEGER) AS squares "
                  "FROM blocks GROUP BY block ORDER BY block"},
        {"type": "csv", "outputTableName": "scratch", "csvObject": [["note"], ["read once"]], "after": "compute"},
        {"type": "drop", "dataRef": "scratch", "after": "compute"},
    ],
    "compute": [{"type": "clusters", "dataRef": "squares", "outputColumnName": "block", "outputTableName": "blocks",
                 "layerType": "polygons", "writeBack": True}],
}

#: What the Python node reads of the step's tables: their names, each block's
#: squares from the counts, and the blocks of the squares, each a line.
PYTHON_READS_THE_STEP = '''items = input_0 if isinstance(input_0, list) else [input_0]


def name_of(item):
    if isinstance(item, dict):
        return item.get("name") or item.get("layerName")
    metadata = getattr(item, "metadata", None)
    return metadata.get("name") if isinstance(metadata, dict) else None


def rows_of(item):
    if isinstance(item, dict):
        held = item.get("geojson") or item.get("data") or {}
        return [feature.get("properties") or {} for feature in held.get("features", [])]
    return item.drop(columns=["geometry"], errors="ignore").to_dict("records")


named = {name_of(item): item for item in items}
sizes = sorted((int(row["block"]), int(row["squares"])) for row in rows_of(named["block_sizes"]))
blocks = [int(row["block"]) for row in rows_of(named["blocks"])]
summary = f"tables {sorted(str(name) for name in named)}; sizes {sizes}; blocks {blocks}"
print(summary)
return summary
'''

#: A join after compute of a table a pass writes without keeping it in autk-db.
NOT_KEPT = {
    "data": [
        COMPUTE_STEP["data"][0],
        {"type": "join", "dataRef": "squares", "joinDataRef": "blocks", "after": "compute"},
    ],
    "compute": [{"type": "clusters", "dataRef": "squares", "outputColumnName": "block", "outputTableName": "blocks"}],
    "map": {"layerRefs": [{"dataRef": "squares"}]},
}
#: What the grammar's run says of it before anything runs.
NOT_KEPT_SAID = (
    'Data source 1 (join) runs after compute and reads "blocks", which compute pass 0 writes without writeBack, '
    "so autk-db holds \"blocks\" without that pass's result. Set writeBack: true on the pass."
)

_VIEWS_JS = "(id) => typeof window.__curio_mapViews === 'function' ? window.__curio_mapViews(id) : null"


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


def _open(page, app_frontend, current_server: str, name: str, nodes: list, edges: list) -> list[str]:
    """Open a dataflow of *nodes* and *edges* as its owner; return the console's errors as they come."""
    spec = {"dataflow": {"name": name.replace(" ", ""), "task": "", "nodes": nodes, "edges": edges}}
    require_project_page()
    require_user_auth()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=name,
        username=name.lower().replace(" ", "_"),
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    return errors


def _one_view(page, node_id: str, holds, what: str, *, timeout_ms: float = 30000) -> dict:
    """The view of the one map *node_id* drew once *holds* is true of it."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        views = page.evaluate(_VIEWS_JS, node_id) or []
        view = views[0] if len(views) == 1 else None
        if view is not None and holds(view):
            return view
        assert time.monotonic() < deadline, f"{what}: Autark node {node_id}'s views are {views}"
        page.wait_for_timeout(250)


def _apart(a: list, b: list) -> float:
    return max(abs(x - y) for x, y in zip(a, b))


def test_a_heatmap_after_compute_bins_what_a_pass_kept_and_its_map_draws_it_alone(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    drawer = "wb-heatmap-after"
    errors = _open(page, app_frontend, current_server, "Autark Heatmap After Compute", [
        _node(drawer, AUTARK_TYPE, 120, 160, json.dumps(HEATMAP_AFTER_COMPUTE, indent=2)),
    ], [])
    # Cells of none to four readings, so a band of zeros, or one cell's colour, cannot pass.
    assert {value for row in COUNTS for value in row} == {0.0, 1.0, 2.0, 3.0, 4.0}

    play_node(page, drawer)
    wait_for_node_done(page, drawer, node_type=AUTARK_TYPE)
    assert_autark_map_drawn(page, drawer, timeout=60000, attach_as="a heatmap after compute drawn alone")
    assert_raster_cells_follow_their_values(page, drawer, COUNTS, attach_as="the readings a pass kept, counted")

    # The map is placed at the raster's middle, the readings' box's, which autk-db keeps on its grid.
    middle = (LOOP[0] + 1500.0, LOOP[1] + 1000.0)
    framed = _one_view(page, drawer, lambda view: view.get("origin") is not None, "a framed map with an origin")
    origin = framed["origin"]
    assert math.dist(origin[:2], middle) < 1, (
        f"the map's origin is {origin}, {math.dist(origin[:2], middle):.1f} units from the raster's middle {middle}"
    )

    # A drag moves the view; R frames the raster again.
    canvas = page.locator(f"#autk-grammar-map-{drawer}")
    box = canvas.bounding_box()
    assert box, "the heatmap's map has no layout box"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    for step in range(1, 9):
        page.mouse.move(x + 12 * step, y + 8 * step)
        page.wait_for_timeout(20)
    page.mouse.up()
    _one_view(page, drawer, lambda view: _apart(view["lookAt"], framed["lookAt"]) > 1, "a drag did not move the map")
    canvas.press("r")
    _one_view(
        page, drawer,
        lambda view: _apart(view["lookAt"], framed["lookAt"]) < 1 and _apart(view["eye"], framed["eye"]) < 1,
        "the R key did not frame the raster again",
    )
    assert_raster_cells_follow_their_values(page, drawer, COUNTS, attach_as="the heatmap framed again by its R key")
    assert not [e for e in errors if "[autk-grammar] node error" in e], errors


def test_a_compute_step_runs_its_sources_after_compute_and_hands_on_what_they_made(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    step, reader, refused = "wb-step", "wb-reader", "wb-not-kept"
    errors = _open(page, app_frontend, current_server, "Autark Compute Step After Compute", [
        _node(step, AUTARK_TYPE, 120, 160, json.dumps(COMPUTE_STEP, indent=2)),
        _node(reader, PYTHON_TYPE, 820, 160, PYTHON_READS_THE_STEP),
        _node(refused, AUTARK_TYPE, 120, 760, json.dumps(NOT_KEPT, indent=2)),
    ], [_edge(step, reader)])

    # Plays the compute step first, which hands its tables on.
    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    sizes = sorted((block, BLOCKS.count(block)) for block in set(BLOCKS))
    said = read_node_output_text(page, reader)
    assert f"tables ['block_sizes', 'blocks', 'squares']; sizes {sizes}; blocks {BLOCKS}" in said, said

    # A source after compute that reads a table no pass kept in autk-db: refused before anything runs.
    play_node(page, refused)
    status = wait_for_node_settled(page, refused, node_type=AUTARK_TYPE, timeout_ms=120000)
    error = read_node_error_text(node_locator(page, refused)) or ""
    assert status == "error" and NOT_KEPT_SAID in error, (
        f"the node whose join after compute reads what no pass kept ended {status!r}, saying {error!r}"
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e and NOT_KEPT_SAID not in e], errors
