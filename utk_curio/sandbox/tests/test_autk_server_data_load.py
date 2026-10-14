"""The JavaScript a run on the server sends for an Autark data node, run here.

A run on the server compiles an Autark node whose document only loads data
with the browser's own compiler (``utk_curio/common/autk_data_compiler.py``,
the frontend's ``dist/autk-data-compile.cjs``) and posts it to ``/execJs``, as
the node's own run in the browser does. This runs that compiled JavaScript for
the loaders of examples 06 (Back Bay), 07 (Chicago Loop), 08 (Niterói) and 11
(Lower Manhattan) through ``execute_js_code`` and pins what it hands on with
autk-db 4.1.0: each layer's name, type, feature count and CRS, and its first
feature's keys.

No socket: the extract is served from disk by a ``fetch`` placed before the
compiled code, which refuses every other request, at the address the sandbox
writes for the backend (an unreachable one here). DuckDB's extensions are
seeded from Curio's copy into a home of the test's own, as a launch seeds them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "docs" / "examples"
AUTK_DB_VERSION = "4.1.0"
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
    ("table_osm_buildings", "buildings", 2120, EPSG_3395, WITHOUT_ID),
]
CHICAGO_LOOP = [
    ("table_osm_surface", "surface", 1, EPSG_3395, WITHOUT_ID),
    ("table_osm_parks", "parks", 275, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 52, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 2098, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 1507, EPSG_3395, WITHOUT_ID),
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
    ("table_osm_parks", "parks", 284, EPSG_3395, WITH_ID),
    ("table_osm_water", "water", 41, EPSG_3395, WITH_ID),
    ("table_osm_roads", "roads", 766, EPSG_3395, WITH_ID),
    ("table_osm_buildings", "buildings", 2321, EPSG_3395, WITHOUT_ID),
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
    ("06-autark-what-if-shadow-study.json", "whatif-data", "docs/examples/data/back_bay.osm.pbf", BACK_BAY),
    ("07-autark-gpu-shader.json", "sh-data", "docs/examples/data/chicago_loop.osm.pbf", CHICAGO_LOOP),
    ("08-autark-spatial-join-regression.json", "niteroi-osm", "docs/examples/data/niteroi.osm.pbf", NITEROI),
    ("11-autark-pbf-loading.json", "pbf-load", "docs/examples/data/lower_mnt.osm.pbf", LOWER_MANHATTAN),
], ids=["back_bay", "chicago_loop", "niteroi", "lower_mnt"])
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
