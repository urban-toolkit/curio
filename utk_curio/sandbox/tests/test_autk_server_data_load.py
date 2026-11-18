"""The JavaScript a run on the server sends for an Autark data node, run here.

A run on the server compiles an Autark node whose document only loads data
with the browser's own compiler (``utk_curio/common/autk_data_compiler.py``,
the frontend's ``dist/autk-data-compile.cjs``) and posts it to ``/execJs``, as
the node's own run in the browser does. This runs that compiled JavaScript for
the loaders of examples 06 (Back Bay), 07 (Chicago Loop), 08 (Niterói) and 11
(Lower Manhattan), and of the test dataflow ``lower-manhattan-park-shade``
(Lower Manhattan's parks and the buildings around them), through
``execute_js_code`` and pins what it hands on with autk-db 4.1.1: each layer's
name, type, feature count and CRS, its first feature's keys, and every
OpenStreetMap feature's id in ``osm_id``.

No socket: the extract is served from disk by a ``fetch`` placed before the
compiled code, which refuses every other request, at the address the sandbox
writes for the backend (an unreachable one here). DuckDB's extensions are
seeded from Curio's copy into a home of the test's own, as a launch seeds them.

A heatmap source is built by autk-grammar's own data adapter, which the
compiled code imports from the grammar's ``./data`` entry: its raster table is
handed on after the layers, in the envelope a raster travels in between nodes,
which a Python node receives as a ``rasterio`` dataset.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "docs" / "examples"
AUTK_DB_VERSION = "4.1.1"
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


AUTK_GRAMMAR_VERSION = "5.0.0"

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
