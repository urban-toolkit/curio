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
- A compute step keeps three passes' results in autk-db: a clusters pass's
  blocks of four squares, a windows pass's windows of two towers, and a render
  pass's view from each square. SQL queries after compute count each block's
  squares, each tower's windows and the views, and a table it loads after
  compute is dropped after compute: the step hands on its tables, the passes'
  and the counts, and a Python node reads them.
- A node whose source after compute reads a table a pass writes without
  ``writeBack`` fails before anything runs, in the grammar's words.
- A data node of no compute pass, whose sources after compute come first in
  its data, runs on the server: its load runs them after the others, the run
  records its output, and the Data Pool below it shows each table.

The maps and the passes need WebGPU, so this test runs on CI's GPU job.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_write_back_e2e.py -v
"""
from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
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
#: Two towers north of the squares, and their heights.
TOWERS = [((150, 300), 30), ((550, 300), 45)]
#: A compute step whose passes keep their results in autk-db: the squares'
#: blocks, the towers' windows and what each square sees of the towers. SQL
#: queries after compute count each block's squares, each tower's windows and
#: the views; a table loaded after compute is dropped after compute. The area
#: around them all loads first: autk-db keeps in a workspace what lies in its
#: first table's box and first polygon table.
COMPUTE_STEP = {
    "data": [
        {"type": "geojson", "outputTableName": "area", "coordinateFormat": "EPSG:3395",
         "geojsonObject": {"type": "FeatureCollection", "features": [
             {"type": "Feature", "geometry": _square(LOOP[0] - 200, LOOP[1] - 200, 1200), "properties": {"name": "Loop"}},
         ]}},
        {"type": "geojson", "outputTableName": "squares", "coordinateFormat": "EPSG:3395",
         "geojsonObject": {"type": "FeatureCollection", "features": [
             {"type": "Feature", "geometry": _square(LOOP[0] + x, LOOP[1] + y, 100), "properties": {"square": i}}
             for i, (x, y) in enumerate(SQUARES)
         ]}},
        {"type": "geojson", "outputTableName": "towers", "coordinateFormat": "EPSG:3395", "layerType": "buildings",
         "geojsonObject": {"type": "FeatureCollection", "features": [
             {"type": "Feature", "geometry": _square(LOOP[0] + x, LOOP[1] + y, 40), "properties": {"height": height}}
             for (x, y), height in TOWERS
         ]}},
        {"type": "sql", "outputTableName": "block_sizes", "after": "compute",
         "query": "SELECT CAST(properties->'compute'->>'block' AS INTEGER) AS block, CAST(count(*) AS INTEGER) AS squares "
                  "FROM blocks GROUP BY block ORDER BY block"},
        {"type": "sql", "outputTableName": "window_counts", "after": "compute",
         "query": "SELECT CAST(properties->>'sourceFeatureIndex' AS INTEGER) AS tower, CAST(count(*) AS INTEGER) AS windows "
                  "FROM windows GROUP BY tower ORDER BY tower"},
        {"type": "sql", "outputTableName": "views", "after": "compute",
         "query": "SELECT CAST(count(*) AS INTEGER) AS seen FROM seen"},
        {"type": "csv", "outputTableName": "scratch", "csvObject": [["note"], ["read once"]], "after": "compute"},
        {"type": "drop", "dataRef": "scratch", "after": "compute"},
    ],
    "compute": [
        {"type": "clusters", "dataRef": "squares", "outputColumnName": "block", "outputTableName": "blocks",
         "layerType": "polygons", "writeBack": True},
        {"type": "windows", "dataRef": "towers", "floors": 2, "outputTableName": "windows", "writeBack": True},
        {"type": "render", "outputTableName": "seen", "writeBack": True,
         "layers": [{"id": "towers", "dataRef": "towers", "type": "buildings"}],
         "viewpoints": {"dataRef": "squares", "sampling": {"directions": 4}},
         "aggregation": {"type": "classes", "includeBackground": True}},
    ],
}

#: What the Python node reads of the step's tables: their names, each block's
#: squares from the counts, the blocks of the squares, the towers whose
#: windows were counted, whether the counts add up to every window the step
#: hands on, and the views counted against the views handed on.
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
counts = sorted((int(row["tower"]), int(row["windows"])) for row in rows_of(named["window_counts"]))
windows = len(rows_of(named["windows"]))
kept = windows > 0 and sum(count for _tower, count in counts) == windows
views = [int(row["seen"]) for row in rows_of(named["views"])]
summary = (
    f"tables {sorted(str(name) for name in named)}; sizes {sizes}; blocks {blocks}; "
    f"towers {[tower for tower, _count in counts]}; every window kept {kept}; views {views} of {len(rows_of(named['seen']))}"
)
print(summary)
return summary
'''

#: A join after compute of a table a pass writes without keeping it in autk-db.
NOT_KEPT = {
    "data": [
        next(source for source in COMPUTE_STEP["data"] if source.get("outputTableName") == "squares"),
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

#: A data node of no compute pass whose sources after compute come first in
#: its data: a SQL query of the zones with many riders, saved as a layer, and
#: a join of the stops onto the zones, then the zones and the stops they read.
ZONE_RIDERS = [4, 9]
STOP_ZONES = [0, 0, 1]
DATA_AFTER = {"data": [
    {"type": "sql", "outputTableName": "busy", "layerType": "polygons", "after": "compute",
     "query": "SELECT properties->>'zone' AS zone, geometry FROM zones WHERE CAST(properties->>'riders' AS INTEGER) > 5"},
    {"type": "join", "dataRef": "zones", "joinDataRef": "stops", "after": "compute",
     "groupBy": [{"column": "*", "aggregateFn": "count"}]},
    {"type": "geojson", "outputTableName": "zones", "coordinateFormat": "EPSG:3395",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": _square(LOOP[0] + 500 * i, LOOP[1], 400), "properties": {"zone": i, "riders": riders}}
         for i, riders in enumerate(ZONE_RIDERS)
     ]}},
    {"type": "geojson", "outputTableName": "stops", "coordinateFormat": "EPSG:3395",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LOOP[0] + 500 * zone + 100 + 50 * i, LOOP[1] + 200]},
          "properties": {"stop": i}}
         for i, zone in enumerate(STOP_ZONES)
     ]}},
]}
#: The tables the data node loads, in the order it loads them: its sources
#: before compute, then the SQL query's table.
DATA_AFTER_TABLES = ["zones", "stops", "busy"]

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

    # The compute step runs its passes, then its sources after compute, and hands its tables on.
    play_node(page, step)
    wait_for_node_done(page, step, node_type=AUTARK_TYPE, timeout_ms=180000)
    play_node(page, reader)
    wait_for_node_done(page, reader, node_type=PYTHON_TYPE)
    sizes = sorted((block, BLOCKS.count(block)) for block in set(BLOCKS))
    tables = ["area", "block_sizes", "blocks", "seen", "squares", "towers", "views", "window_counts", "windows"]
    said = read_node_output_text(page, reader)
    assert (
        f"tables {tables}; sizes {sizes}; blocks {BLOCKS}; towers [0, 1]; every window kept True; "
        f"views [{len(SQUARES)}] of {len(SQUARES)}"
    ) in said, said

    # A source after compute that reads a table no pass kept in autk-db: refused before anything runs.
    play_node(page, refused)
    status = wait_for_node_settled(page, refused, node_type=AUTARK_TYPE, timeout_ms=120000)
    error = read_node_error_text(node_locator(page, refused)) or ""
    assert status == "error" and NOT_KEPT_SAID in error, (
        f"the node whose join after compute reads what no pass kept ended {status!r}, saying {error!r}"
    )
    assert not [e for e in errors if "[autk-grammar] node error" in e and NOT_KEPT_SAID not in e], errors


def _latest_run(backend: str, token: str, project_id: str) -> dict:
    runs = api_json(f"{backend}/api/projects/{project_id}/runs?limit=1", token)["runs"]
    assert runs, "playing the data node started no run on the server"
    return api_json(f"{backend}/api/runs/{runs[0]['id']}", token, dataflow=project_id)


def _wait_for_run_to_end(backend: str, token: str, project_id: str, *, timeout_s: float = 180) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        run = _latest_run(backend, token, project_id)
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"the run did not end within {timeout_s} s: {run['status']}"
        time.sleep(0.5)


def test_a_server_run_loads_a_data_nodes_sources_after_compute_after_the_others_and_its_pool_shows_them(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    loader, pool = "wb-data-after", "wb-data-pool"
    spec = {"dataflow": {"name": "AutarkDataAfterCompute", "task": "", "nodes": [
        {**_node(loader, AUTARK_TYPE, 120, 160, json.dumps(DATA_AFTER, indent=2)), "saveOutputDataset": True},
        _node(pool, "curio.builtin/data-pool", 820, 160, ""),
    ], "edges": [_edge(loader, pool)]}}
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Autark Data After Compute",
        username="autark_data_after_compute",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    _wait_for_reactflow_ready(page)
    for node_id in (loader, pool):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    # The data node's load runs on the server, its sources after compute after the others.
    play_node(page, loader)
    wait_for_node_done(page, loader, node_type=AUTARK_TYPE, timeout_ms=180000)
    run = _wait_for_run_to_end(current_server, token, project_id)
    step = {s["nodeId"]: s for s in run["steps"]}[loader]
    assert (step["role"], step["status"], step["outputType"]) == ("run", "ok", "list"), step
    assert step["outputPath"], step
    assert run["status"] == "succeeded", run["status"]

    # Done, with the tables it loaded.
    node = node_locator(page, loader)
    node.locator('.nav-link[data-rr-ui-event-key="output"]').first.click()
    expect(node.locator('[data-curio-autk-summary="data"]')).to_have_text(
        "Loaded 3 tables: " + ", ".join(DATA_AFTER_TABLES), timeout=15000,
    )

    # The pool below it reads the run's output: a tab for each table.
    expect(node_locator(page, pool).locator('[data-testid="data-pool-tabs"] .nav-link')).to_have_text(
        DATA_AFTER_TABLES, timeout=60000,
    )

    # Recorded in the dataflow as a save records it.
    saved = api_json(f"{current_server}/api/projects/{project_id}", token)
    assert loader in {o["node_id"] for o in saved["outputs"]}, saved["outputs"]
