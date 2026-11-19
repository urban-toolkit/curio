"""The JavaScript a run on the server sends for an Autark data node, run here.

A run on the server compiles an Autark node whose document only loads data
with the browser's own compiler (``utk_curio/common/autk_data_compiler.py``,
the frontend's ``dist/autk-data-compile.cjs``) and posts it to ``/execJs``, as
the node's own run in the browser does. This runs that compiled JavaScript for
the loaders of examples 06 (Back Bay), 07 (Chicago Loop), 08 (Niterói) and 11
(Lower Manhattan), and of the test dataflow ``lower-manhattan-park-shade``
(Lower Manhattan's parks and the buildings around them), through
``execute_js_code`` and pins what it hands on with autk-db 4.1.1-curio.2
(release 4.1.1 with urban-toolkit/autark#132, which changes only how a heatmap
reads and labels its bands): each layer's name, type, feature count and CRS, its first
feature's keys, and every OpenStreetMap feature's id in ``osm_id``.

No socket: the extract is served from disk by a ``fetch`` placed before the
compiled code, which refuses every other request, at the address the sandbox
writes for the backend (an unreachable one here). DuckDB's extensions are
seeded from Curio's copy into a home of the test's own, as a launch seeds them.

A heatmap source is built by autk-grammar's own data adapter, which the
compiled code imports from the grammar's ``./data`` entry: its raster table is
handed on after the layers, in the envelope a raster travels in between nodes,
which a Python node receives as a ``rasterio`` dataset.

A geotiff source is loaded by the same adapter, from a file of the repository
the document names by its path, which the compiled code fetches from the
backend's ``/file/`` route (served from disk here, as an extract is). Its
raster table is handed on as a heatmap's is: the file's cells, laid over its
corners in the workspace's CRS.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "docs" / "examples"
AUTK_DB_VERSION = "4.1.1-curio.2"
EPSG_3395 = "urn:ogc:def:crs:EPSG::3395"
#: A feature's keys: autk-db gives an OSM element's id, not a surface's or a
#: building part's.
WITH_ID = ["geometry", "id", "properties", "type"]
WITHOUT_ID = ["geometry", "properties", "type"]

BACK_BAY = [
    ("table_osm_surface", "surface", 1, EPSG_3395, WITHOUT_ID),
    ("table_osm_parks", "parks", 116, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 8, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 736, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 2102, EPSG_3395, WITHOUT_ID),
]
CHICAGO_LOOP = [
    ("table_osm_surface", "surface", 1, EPSG_3395, WITHOUT_ID),
    ("table_osm_parks", "parks", 280, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 52, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 2120, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 1501, EPSG_3395, WITHOUT_ID),
]
#: The land of Niterói: its coastline splits the surface.
NITEROI = [
    ("table_osm_surface", "surface", 14, EPSG_3395, WITHOUT_ID),
    ("table_osm_parks", "parks", 755, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 88, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 8604, EPSG_3395, WITH_ID),
]
#: Battery Park City and the Financial District, a surface each.
LOWER_MANHATTAN = [
    ("table_osm_surface", "surface", 2, EPSG_3395, WITHOUT_ID),
    ("table_osm_parks", "parks", 287, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 42, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 767, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 2326, EPSG_3395, WITHOUT_ID),
]
#: Two loads of the same extract into one table name (the park shade test
#: dataflow): the parks of a box, the Financial District to City Hall, and
#: the building parts of a box about 300 m larger on every side, up to the
#: extract's edge.
LOWER_MANHATTAN_PARKS = [
    ("table_osm_parks", "parks", 215, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 2688, EPSG_3395, WITHOUT_ID),
]

#: Put before the compiled code: serves the one extract the document loads,
#: from disk, as the backend's ``/file/`` route would, says so on stdout, and
#: refuses any other request. The sandbox writes its backend address for the
#: token, here and in the compiled code alike.
_FETCH_FROM_DISK = """{
  const __fs = require('fs');
  const __path = require('path');
  const __prefix = '__CURIO_BACKEND_URL__/file/';
  globalThis.fetch = async (url) => {
    const href = typeof url === 'string' ? url : (url && url.url) || String(url);
    const rel = href.startsWith(__prefix) ? decodeURIComponent(href.slice(__prefix.length)) : null;
    if (rel !== EXTRACT) throw new Error('no socket in this test: ' + href);
    console.log('[served] ' + rel);
    return new Response(__fs.readFileSync(__path.join(ROOT, rel)), { status: 200 });
  };
}
"""


def _loader_content(example: str, node_id: str) -> str:
    dataflow = json.loads((EXAMPLES / example).read_text(encoding="utf-8"))["dataflow"]
    return next(node["content"] for node in dataflow["nodes"] if node["id"] == node_id)


@pytest.mark.parametrize("example, node_id, extract, layers", [
    ("06-back-bay-road-sunlight.json", "whatif-data", "docs/examples/data/back_bay.osm.pbf", BACK_BAY),
    ("07-autark-gpu-shader.json", "sh-data", "docs/examples/data/chicago_loop.osm.pbf", CHICAGO_LOOP),
    ("08-autark-spatial-join-regression.json", "niteroi-osm", "docs/examples/data/niteroi.osm.pbf", NITEROI),
    ("11-autark-pbf-loading.json", "pbf-load", "docs/examples/data/lower_mnt.osm.pbf", LOWER_MANHATTAN),
    ("dataflows/lower-manhattan-park-shade.json", "park-shade-layers", "docs/examples/data/lower_mnt.osm.pbf",
     LOWER_MANHATTAN_PARKS),
], ids=["back_bay", "chicago_loop", "niteroi", "lower_mnt", "lower_mnt_parks"])
def test_the_server_compiled_load_hands_on_the_layers(example, node_id, extract, layers, tmp_path, monkeypatch):
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.node_runtime import node_modules_dir
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    installed = json.loads(
        (node_modules_dir() / "@urban-toolkit" / "autk-db" / "package.json").read_text(encoding="utf-8")
    )
    assert installed["version"] == AUTK_DB_VERSION, (
        f"these layers are autk-db {AUTK_DB_VERSION}'s; the sandbox has {installed['version']}"
    )

    code = compile_data_spec(_loader_content(example, node_id))
    assert f'"pbfFileUrl":"__CURIO_BACKEND_URL__/file/{extract}"' in code
    serve = (_FETCH_FROM_DISK
             .replace("EXTRACT", json.dumps(extract))
             .replace("ROOT", json.dumps(str(REPO_ROOT))))

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # An address nothing answers at: the fetch above is the only way in.
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    assert result["output"]["dataType"] == "list"
    assert f"[served] {extract}" in result["stdout"], result["stdout"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert all(sorted(layer) == ["geojson", "name", "type"] for layer in loaded), loaded[:1]
    assert [
        (
            layer["name"],
            layer["type"],
            len(layer["geojson"]["features"]),
            layer["geojson"]["crs"]["properties"]["name"],
            sorted(layer["geojson"]["features"][0]),
        )
        for layer in loaded
    ] == layers
    for layer in loaded:
        _assert_osm_ids(layer)


AUTK_GRAMMAR_VERSION = "5.2.0"

#: Four readings at the corners of a box about 1.1 km by 1.5 km in the Chicago
#: Loop, binned twice into 3 columns by 2 rows over their extent: each cell of
#: `density` counts the readings within 5 km of its center, all four, and each
#: cell of `nearby` those within 1 m, none.
HEATMAPS = {"data": [
    {"type": "geojson", "outputTableName": "readings", "coordinateFormat": "EPSG:4326",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": {"db": db}}
         for lon, lat, db in ((-87.64, 41.87, 61), (-87.63, 41.87, 74), (-87.64, 41.88, 58), (-87.63, 41.88, 66))
     ]}},
    {"type": "heatmap", "joinDataRef": "readings", "outputTableName": "density",
     "near": {"distance": 5000}, "grid": {"rows": 2, "columns": 3},
     "groupBy": [{"column": "*", "aggregateFn": "count"}]},
    {"type": "heatmap", "joinDataRef": "readings", "outputTableName": "nearby",
     "near": {"distance": 1}, "grid": {"rows": 2, "columns": 3},
     "groupBy": [{"column": "*", "aggregateFn": "count"}]},
]}

#: Put before the compiled code: no request leaves the run.
_NO_SOCKET = """globalThis.fetch = async (url) => {
  throw new Error('no socket in this test: ' + (typeof url === 'string' ? url : String(url)));
};
"""


def test_the_server_compiled_load_builds_a_heatmap_and_hands_it_on_as_a_raster(tmp_path, monkeypatch):
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.node_runtime import node_modules_dir, resolve_pkg_entry_url
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    grammar = node_modules_dir() / "@urban-toolkit" / "autk-grammar"
    installed = json.loads((grammar / "package.json").read_text(encoding="utf-8"))
    assert installed["version"] == AUTK_GRAMMAR_VERSION, (
        f"this heatmap is autk-grammar {AUTK_GRAMMAR_VERSION}'s; the sandbox has {installed['version']}"
    )

    code = compile_data_spec(json.dumps(HEATMAPS))
    assert code.splitlines()[:2] == [
        "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';",
        "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';",
    ]
    # The sandbox loads the entry the grammar's exports give "./data", which
    # imports autk-db alone, not its main entry.
    assert resolve_pkg_entry_url("@urban-toolkit/autk-grammar/data", node_modules_dir()) == (
        (grammar / "dist" / "data" / "autk-grammar-data.js").resolve().as_uri()
    )

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        _NO_SOCKET + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    assert result["output"]["dataType"] == "list"
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("name"), item.get("type")) for item in loaded[:1]] == [("readings", "points")]
    assert [(item.get("dataType"), item.get("layerName")) for item in loaded[1:]] == [
        ("raster", "density"), ("raster", "nearby"),
    ]
    density, nearby = loaded[1:]
    grid, bands, counts = envelope_arrays(density)
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", 3, 2), grid
    assert bands == ["band_1"]
    assert density["data"]["features"][0]["properties"]["bands"] == [{"id": "band_1", "label": "count_readings"}]
    assert counts.tolist() == [[[4.0, 4.0, 4.0], [4.0, 4.0, 4.0]]]
    assert envelope_arrays(nearby)[2].tolist() == [[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]]

    # A Python node downstream receives each as a rasterio dataset on its grid.
    handed = rasters_for_python(loaded, tmp_path / "rasters")
    try:
        heat = handed[1]
        assert (heat.width, heat.height, heat.crs.to_epsg()) == (3, 2, 3395)
        assert tuple(heat.transform)[:6] == (
            grid["resX"], 0.0, grid["originX"], 0.0, grid["resY"], grid["originY"],
        )
        assert heat.read(1).tolist() == [[4.0, 4.0, 4.0], [4.0, 4.0, 4.0]]
    finally:
        for item in handed[1:]:
            item.close()


#: Sound levels in decibels, in EPSG:3395 metres: a box 3 km by 2 km at the
#: Chicago Loop, its south-west corner at ``LOOP``, binned into 3 by 2 cells of
#: 1 km. The two readings at the box's corners give the workspace its extent
#: and lie 707 m from every cell's center, past the 600 m a cell reaches; every
#: other one lies within 100 m of its own cell's center, and the cells hold
#: none to four of them. Each is (east, north) of the corner, then its level.
LOOP = (-9755000.0, 5106000.0)
LEVELS = [
    (0, 0, 40), (3000, 2000, 95),
    (500, 500, 50),
    (1500, 500, 60), (1600, 500, 70),
    (500, 1500, 55), (600, 1500, 58), (400, 1500, 61),
    (1500, 1500, 62), (1600, 1500, 66), (1400, 1500, 70), (1500, 1600, 74),
    (2500, 1500, 80), (2500, 1600, 84),
]
#: Every aggregate a heatmap builds, one band each, in this order.
AGGREGATES = ["count", "weighted", "sum", "avg", "min", "max"]
#: How far a cell's center reaches, and the grid's rows, columns and cell size.
REACH, ROWS, COLUMNS, CELL = 600.0, 2, 3, 1000.0

LEVEL_HEATMAP = {"data": [
    {"type": "geojson", "outputTableName": "levels", "coordinateFormat": "EPSG:3395",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LOOP[0] + east, LOOP[1] + north]},
          "properties": {"db": db}}
         for east, north, db in LEVELS
     ]}},
    {"type": "heatmap", "joinDataRef": "levels", "outputTableName": "noise",
     "near": {"distance": REACH}, "grid": {"rows": ROWS, "columns": COLUMNS},
     "groupBy": [{"column": "*" if fn in ("count", "weighted") else "db", "aggregateFn": fn} for fn in AGGREGATES]},
]}


def _cells_from_the_levels() -> dict[str, list[list[float]]]:
    """Each aggregate's cells, the north row first as rasterio reads them,
    computed from ``LEVELS``: the readings within ``REACH`` of a cell's
    center, counted, weighted 1 / (distance + 1) each, or their levels summed,
    averaged, or their least and greatest; 0 for a cell none reaches."""
    import math

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


def test_the_server_compiled_load_builds_every_heatmap_aggregate_from_the_readings(tmp_path, monkeypatch):
    """One heatmap with a band per aggregate: each cell holds the aggregate of
    the readings near its center, as computed here from the readings, in the
    envelope it is handed on in and in the rasterio dataset a Python node gets."""
    import numpy as np

    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    expected = _cells_from_the_levels()
    # The readings make every aggregate a grid of its own, none of them flat.
    assert len({json.dumps(cells) for cells in expected.values()}) == len(AGGREGATES)
    assert all(len({value for row in cells for value in row}) >= 4 for cells in expected.values())

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        _NO_SOCKET + compile_data_spec(json.dumps(LEVEL_HEATMAP)), "", "AUTK_GRAMMAR", "",
        launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("dataType"), item.get("layerName")) for item in loaded[1:]] == [("raster", "noise")]
    noise = loaded[1]
    grid, bands, cells = envelope_arrays(noise)
    # The grid lies over the readings' extent, the box.
    assert grid == {"crs": "EPSG:3395", "width": COLUMNS, "height": ROWS, "originX": LOOP[0],
                    "originY": LOOP[1] + ROWS * CELL, "resX": CELL, "resY": -CELL}
    assert noise["data"]["features"][0]["properties"]["bands"] == [
        {"id": f"band_{index}", "label": f"{fn}_levels"} for index, fn in enumerate(AGGREGATES, start=1)
    ]
    for fn, band in zip(AGGREGATES, cells):
        np.testing.assert_allclose(band, expected[fn], rtol=1e-6, err_msg=f"the {fn} band's cells")

    # A Python node downstream receives it as one rasterio dataset with a band per aggregate.
    handed = rasters_for_python(loaded, tmp_path / "rasters")
    try:
        heat = handed[1]
        assert (heat.count, heat.width, heat.height, heat.crs.to_epsg()) == (len(AGGREGATES), COLUMNS, ROWS, 3395)
        for index, fn in enumerate(AGGREGATES, start=1):
            np.testing.assert_allclose(heat.read(index), expected[fn], rtol=1e-6, err_msg=f"band {index}, {fn}")
        # Each band is named as the heatmap labels it, so a node can find an aggregate's band.
        assert heat.descriptions == tuple(f"{fn}_levels" for fn in AGGREGATES)
    finally:
        for item in handed[1:]:
            item.close()


def test_the_server_compiled_load_bins_a_table_of_the_nodes_input(tmp_path, monkeypatch):
    """A heatmap that bins ``input_0``, the node's input: the readings a Python
    node returned, stored as their GeoDataFrame is, which the sandbox gives the
    run as ``input_0``, as it gives a JavaScript node its input. The load finds
    them there, loads them first, so they give the workspace its extent as a
    table the section loads first does, bins them, and hands on the heatmap
    alone, not the readings again."""
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    readings = gpd.GeoDataFrame(
        {"db": [db for _east, _north, db in LEVELS]},
        geometry=[Point(LOOP[0] + east, LOOP[1] + north) for east, north, _db in LEVELS],
        crs="EPSG:3395",
    )
    stored = save_to_duckdb(readings, node_id="readings", session_id=None)
    of_the_input = {"data": [{**LEVEL_HEATMAP["data"][1], "joinDataRef": "input_0"}]}
    result = execute_js_code(
        _NO_SOCKET + compile_data_spec(json.dumps(of_the_input)), stored, "AUTK_GRAMMAR", "geodataframe",
        launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("dataType"), item.get("layerName")) for item in loaded] == [("raster", "noise")]
    grid, _bands, cells = envelope_arrays(loaded[0])
    assert grid == {"crs": "EPSG:3395", "width": COLUMNS, "height": ROWS, "originX": LOOP[0],
                    "originY": LOOP[1] + ROWS * CELL, "resX": CELL, "resY": -CELL}
    assert [band["label"] for band in loaded[0]["data"]["features"][0]["properties"]["bands"]] == [
        f"{fn}_input_0" for fn in AGGREGATES
    ]
    expected = _cells_from_the_levels()
    for fn, band in zip(AGGREGATES, cells):
        np.testing.assert_allclose(band, expected[fn], rtol=1e-6, err_msg=f"the {fn} band's cells")


def test_the_server_compiled_load_fails_on_a_table_its_input_does_not_carry(tmp_path, monkeypatch):
    """A heatmap of a table neither the section loads nor the input carries
    fails the load, naming it, before anything loads."""
    import geopandas as gpd
    from shapely.geometry import Point

    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    stored = save_to_duckdb(
        gpd.GeoDataFrame({"db": [61]}, geometry=[Point(LOOP[0], LOOP[1])], crs="EPSG:3395"),
        node_id="readings", session_id=None,
    )
    of_another = {"data": [{**LEVEL_HEATMAP["data"][1], "joinDataRef": "labels"}]}
    result = execute_js_code(
        _NO_SOCKET + compile_data_spec(json.dumps(of_another)), stored, "AUTK_GRAMMAR", "geodataframe",
        launch_dir=str(REPO_ROOT), session_id=None,
    )
    assert not result["output"]["path"]
    assert result["stderr"].startswith(
        'The heatmap "noise" bins "labels", a table its data section does not load '
        "and the node's input does not carry."
    ), result["stderr"]


#: Each reading's peak, this many decibels above its level.
PEAK = 10

#: Two averages of different columns, and two bands rescaled from 0 to 1.
LABELLED_HEATMAP = {"data": [
    {"type": "geojson", "outputTableName": "levels", "coordinateFormat": "EPSG:3395",
     "geojsonObject": {"type": "FeatureCollection", "features": [
         {"type": "Feature", "geometry": {"type": "Point", "coordinates": [LOOP[0] + east, LOOP[1] + north]},
          "properties": {"db": db, "peak": db + PEAK}}
         for east, north, db in LEVELS
     ]}},
    {"type": "heatmap", "joinDataRef": "levels", "outputTableName": "noise",
     "near": {"distance": REACH}, "grid": {"rows": ROWS, "columns": COLUMNS},
     "groupBy": [
         {"column": "db", "aggregateFn": "avg"},
         {"column": "peak", "aggregateFn": "avg"},
         {"column": "db", "aggregateFn": "avg", "normalize": True},
         {"column": "*", "aggregateFn": "count", "normalize": True},
     ]},
]}


def _rescaled(cells: list[list[float]]) -> list[list[float]]:
    """*cells* from 0 at their least to 1 at their greatest, as the join
    rescales a normalized aggregate across the cells."""
    values = [value for row in cells for value in row]
    low, high = min(values), max(values)
    return [[(value - low) / (high - low) for value in row] for row in cells]


def test_the_server_compiled_load_labels_each_band_apart_and_rescales_the_normalized_ones(tmp_path, monkeypatch):
    """Two averages of different columns each name their column, and a band
    that asks to be normalized holds its cells rescaled from 0 to 1, under a
    label that ends in ``_norm``: every label names one band, in the envelope
    and in the rasterio dataset a Python node gets."""
    import numpy as np

    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    cells = _cells_from_the_levels()
    peaks = [[average + PEAK if count else 0.0 for average, count in zip(averages, counts)]
             for averages, counts in zip(cells["avg"], cells["count"])]
    expected = {
        "avg_levels_db": cells["avg"],
        "avg_levels_peak": peaks,
        "avg_levels_norm": _rescaled(cells["avg"]),
        "count_levels_norm": _rescaled(cells["count"]),
    }

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        _NO_SOCKET + compile_data_spec(json.dumps(LABELLED_HEATMAP)), "", "AUTK_GRAMMAR", "",
        launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    noise = load_from_duckdb(result["output"]["path"], session_id=None)[1]
    assert [band["label"] for band in noise["data"]["features"][0]["properties"]["bands"]] == list(expected)
    _grid, _bands, values = envelope_arrays(noise)
    for (label, band_cells), band in zip(expected.items(), values):
        np.testing.assert_allclose(band, band_cells, rtol=1e-6, atol=1e-6, err_msg=f"the {label} band's cells")

    handed = rasters_for_python([noise], tmp_path / "rasters")
    try:
        (heat,) = handed
        assert heat.descriptions == tuple(expected)
        for index, (label, band_cells) in enumerate(expected.items(), start=1):
            np.testing.assert_allclose(heat.read(index), band_cells, rtol=1e-6, atol=1e-6, err_msg=label)
    finally:
        for item in handed:
            item.close()


def _line(x0: float, y0: float) -> dict:
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[x0, y0], [x0 + 0.001, y0 + 0.001]]},
            "properties": {"x": x0}}


def _point(x: float, y: float) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]}, "properties": {"x": x}}


def _collection(*features: dict) -> dict:
    return {"type": "FeatureCollection", "features": list(features)}


#: ``lines`` in the default workspace (one, in the Loop) and in ``east`` (three,
#: 8 km east, inside ``zones``, which east's join counts them in), and
#: ``points`` in ``autk``, the default workspace named.
WORKSPACES_SPEC = {"data": [
    {"type": "geojson", "outputTableName": "lines", "geojsonObject": _collection(_line(-87.600, 41.880))},
    {"type": "geojson", "outputTableName": "zones", "workspace": "east", "geojsonObject": _collection({
        "type": "Feature", "properties": {"zone": 1},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-87.51, 41.87], [-87.47, 41.87], [-87.47, 41.89], [-87.51, 41.89], [-87.51, 41.87],
        ]]},
    })},
    {"type": "geojson", "outputTableName": "lines", "workspace": "east",
     "geojsonObject": _collection(_line(-87.500, 41.880), _line(-87.490, 41.880), _line(-87.480, 41.880))},
    {"type": "geojson", "outputTableName": "points", "workspace": "autk",
     "geojsonObject": _collection(_point(-87.5998, 41.8802), _point(-87.5995, 41.8805))},
    {"type": "join", "workspace": "east", "dataRef": "zones", "joinDataRef": "lines",
     "groupBy": [{"column": "*", "aggregateFn": "count"}]},
]}


def _numbers(value) -> list:
    """Every number *value* holds, however deep."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [value]
    if isinstance(value, dict):
        return [n for inner in value.values() for n in _numbers(inner)]
    if isinstance(value, list):
        return [n for inner in value for n in _numbers(inner)]
    return []


def test_the_server_compiled_load_keeps_each_table_in_its_workspace(tmp_path, monkeypatch):
    """A server run's data load (autk-grammar 5.0.0's ``workspace``): each
    source loads into its workspace, entered with autk-grammar's own
    ``enterWorkspace`` from its ``./data`` entry, so two workspaces hold a
    ``lines`` each and east's join counts east's three. Each table is handed
    on with its workspace, one of the default workspace as before. The tables
    the sandbox reads back are keyed with the grammar's ``tableKey`` and checked
    against the ones the browser's compiler expects, keyed by its own copy of
    that rule, so a mismatch fails the load as a short one."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    code = compile_data_spec(json.dumps(WORKSPACES_SPEC))
    assert "import { enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';" in code
    assert 'const __expectedTables = ["lines","east/zones","east/lines","points"];' in code

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None)

    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [
        (layer["name"], layer.get("workspace"), len(layer["geojson"]["features"])) for layer in loaded
    ] == [("lines", None, 1), ("points", None, 2), ("zones", "east", 1), ("lines", "east", 3)]
    # A table of the default workspace is handed on as before.
    assert [sorted(layer) for layer in loaded[:2]] == [["geojson", "name", "type"]] * 2
    assert all(sorted(layer) == ["geojson", "name", "type", "workspace"] for layer in loaded[2:])
    # East's join counted east's lines, the three inside its zone.
    zone = loaded[2]["geojson"]["features"][0]["properties"]
    assert 3 in _numbers(zone), zone


def _assert_osm_ids(layer: dict) -> None:
    """Every feature of *layer* carries its OpenStreetMap id in ``osm_id``: a
    road's, a park's or a water's the id autk-db gives its feature, a building
    part's its own part's, which the parts of one building never share. The
    surface, the area's land, is no OpenStreetMap element and has none."""
    name, features = layer["name"], layer["geojson"]["features"]
    ids = [feature["properties"].get("osm_id") for feature in features]
    if layer["type"] == "surface":
        assert ids == [None] * len(features), (name, ids[:5])
        return
    assert all(type(osm_id) is int and osm_id > 0 for osm_id in ids), (
        name, [osm_id for osm_id in ids if type(osm_id) is not int or osm_id <= 0][:5],
    )
    if layer["type"] != "buildings":
        assert ids == [feature.get("id") for feature in features], name
        return
    parts: dict = {}
    for feature, osm_id in zip(features, ids):
        parts.setdefault(feature["properties"].get("building_id"), []).append(osm_id)
    assert any(len(own) > 1 for own in parts.values()), f"{name} has no building of several parts"
    shared = {building: own for building, own in parts.items() if len(set(own)) < len(own)}
    assert not shared, (name, dict(list(shared.items())[:3]))


#: GeoTIFFs of the repository, as a document's geotiff source names them, each
#: with the CRS the file is in and what autk-db reads of it (columns, rows,
#: bands): Niterói's summer surface temperature, a band a summer from 2001 to
#: 2024, whole, and shrunk to at most 200 cells with nearest resampling, as
#: the grammar's gallery loads it; and a raster in UTM zone 16N with no-data
#: cells.
NITEROI_LST = "docs/examples/data/niteroi_lst_verao_2001_2024.tif"
UTM_RASTER = "utk_curio/backend/tests/test_frontend/data/autark_raster_utm16n.tif"
GEOTIFFS = [
    pytest.param({"type": "geotiff", "geotiffFileUrl": NITEROI_LST, "outputTableName": "lst",
                  "resampleMethod": "nearest"},
                 "EPSG:4326", (22, 15, 24), id="niteroi"),
    pytest.param({"type": "geotiff", "geotiffFileUrl": NITEROI_LST, "outputTableName": "lst",
                  "coordinateFormat": "EPSG:4326", "maxRasterCells": 200, "resampleMethod": "nearest"},
                 "EPSG:4326", (17, 11, 24), id="niteroi-in-200-cells"),
    pytest.param({"type": "geotiff", "geotiffFileUrl": UTM_RASTER, "outputTableName": "heat",
                  "coordinateFormat": "EPSG:32616"},
                 "EPSG:32616", (40, 30, 1), id="utm16n-with-no-data"),
]


@pytest.mark.parametrize("source, crs, size", GEOTIFFS)
def test_the_server_compiled_load_reads_a_geotiff_of_the_repository_and_hands_it_on_as_a_raster(
        source, crs, size, tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from pyproj import Transformer

    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    path = source["geotiffFileUrl"]
    code = compile_data_spec(json.dumps({"data": [source]}))
    assert code.splitlines()[:2] == [
        "import { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT } from '@urban-toolkit/autk-db';",
        "import { createDataAdapter } from '@urban-toolkit/autk-grammar/data';",
    ]
    # The file is named by its path in the repository, as an extract is, and
    # fetched from the backend's /file/ route.
    assert f'"geotiffFileUrl":"__CURIO_BACKEND_URL__/file/{path}"' in code
    serve = (_FETCH_FROM_DISK
             .replace("EXTRACT", json.dumps(path))
             .replace("ROOT", json.dumps(str(REPO_ROOT))))

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    assert result["output"]["dataType"] == "list"
    assert f"[served] {path}" in result["stdout"], result["stdout"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("dataType"), item.get("layerName")) for item in loaded] == [("raster", source["outputTableName"])]
    (raster,) = loaded
    grid, bands, values = envelope_arrays(raster)
    width, height, count = size
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", width, height), grid
    assert bands == [f"band_{n}" for n in range(1, count + 1)]
    assert raster["data"]["features"][0]["properties"]["bands"] == [{"id": band, "label": band} for band in bands]

    with rasterio.open(REPO_ROOT / path) as tif:
        assert f"EPSG:{tif.crs.to_epsg()}" == crs
        held = tif.read(masked=True).astype("float32").filled(np.nan)
        left, bottom, right, top = tif.bounds
    if (held.shape[2], held.shape[1]) == (width, height):
        # The file's own cells, every band, north up, no data as NaN.
        assert np.array_equal(values, held, equal_nan=True)
    else:
        # Shrunk with nearest resampling: each cell is one of the file's, never a blend.
        for read, own in zip(values, held):
            assert set(read.ravel().tolist()) <= set(own.ravel().tolist())
    # Placed where autk-db places it: over the file's corners in the workspace's CRS.
    xs, ys = Transformer.from_crs(crs, "EPSG:3395", always_xy=True).transform(
        [left, left, right, right], [bottom, top, bottom, top])
    corners = (min(xs), min(ys), max(xs), max(ys))

    # A Python node downstream receives it as a rasterio dataset on that grid.
    handed = rasters_for_python(loaded, tmp_path / "rasters")
    try:
        (dataset,) = handed
        assert (dataset.width, dataset.height, dataset.count, dataset.crs.to_epsg()) == (width, height, count, 3395)
        assert tuple(dataset.bounds) == pytest.approx(corners, abs=0.05)
        assert np.array_equal(dataset.read(), values, equal_nan=True)
    finally:
        for item in handed:
            item.close()


#: The readings of ``HEATMAPS`` and their ``density`` heatmap, both in the
#: workspace ``east``: a heatmap bins the table of its own workspace.
EAST_HEATMAP = {"data": [
    {**HEATMAPS["data"][0], "workspace": "east"},
    {**HEATMAPS["data"][1], "workspace": "east"},
]}


def test_the_server_compiled_load_builds_a_heatmap_in_its_workspace_and_hands_it_on_there(tmp_path, monkeypatch):
    """A heatmap in a workspace (autk-grammar 5.0.0's ``workspace``) bins the
    readings of its own workspace on a run on the server, and is handed on in
    it: the raster's envelope names the workspace, as the readings' table
    does, and a Python node downstream finds it in the dataset's ``metadata``
    beside the raster's name."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays, rasters_for_python

    code = compile_data_spec(json.dumps(EAST_HEATMAP))
    assert "import { createDataAdapter, enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';" in code

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    result = execute_js_code(
        _NO_SOCKET + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None,
    )

    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("name"), item.get("type"), item.get("workspace")) for item in loaded[:1]] == [
        ("readings", "points", "east"),
    ]
    assert [(item.get("dataType"), item.get("layerName"), item.get("workspace")) for item in loaded[1:]] == [
        ("raster", "density", "east"),
    ]
    grid, bands, counts = envelope_arrays(loaded[1])
    assert (grid["crs"], grid["width"], grid["height"]) == ("EPSG:3395", 3, 2), grid
    assert bands == ["band_1"]
    assert counts.tolist() == [[[4.0, 4.0, 4.0], [4.0, 4.0, 4.0]]]

    handed = rasters_for_python(loaded, tmp_path / "rasters")
    try:
        heat = handed[1]
        assert heat.__dict__["metadata"] == {"name": "density", "workspace": "east"}
        assert heat.read(1).tolist() == [[4.0, 4.0, 4.0], [4.0, 4.0, 4.0]]
    finally:
        handed[1].close()
