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

OpenStreetMap writes every tag as text, and the load hands each numeric
building tag on as a number (``withOsmNumbers``): a plain number as that
number ("65.5"), a length with its unit in metres ("86 m"), and a value with
no number that can be read ("7-7") as none. A Map Editor node below such a
load edits what it hands on: its scale, offset, rule and expression read each
such tag as the number it is.
"""
from __future__ import annotations

import copy
import json
import math
import textwrap
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


def _run_example_load(example: str, node_id: str, extract: str, tmp_path, monkeypatch) -> dict:
    """What ``execute_js_code`` answers for the server-compiled load of the
    node *node_id* of *example*, its extract served from disk (``_run_load``,
    below, runs a document of the test's own with nothing served)."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.util.node_runtime import node_modules_dir

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
    return execute_js_code(
        serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(REPO_ROOT), session_id=None,
    )


@pytest.mark.parametrize("example, node_id, extract, layers", [
    ("06-back-bay-road-sunlight.json", "whatif-data", "docs/examples/data/back_bay.osm.pbf", BACK_BAY),
    ("07-autark-gpu-shader.json", "sh-data", "docs/examples/data/chicago_loop.osm.pbf", CHICAGO_LOOP),
    ("08-autark-spatial-join-regression.json", "niteroi-osm", "docs/examples/data/niteroi.osm.pbf", NITEROI),
    ("11-autark-pbf-loading.json", "pbf-load", "docs/examples/data/lower_mnt.osm.pbf", LOWER_MANHATTAN),
    ("dataflows/lower-manhattan-park-shade.json", "park-shade-layers", "docs/examples/data/lower_mnt.osm.pbf",
     LOWER_MANHATTAN_PARKS),
], ids=["back_bay", "chicago_loop", "niteroi", "lower_mnt", "lower_mnt_parks"])
def test_the_server_compiled_load_hands_on_the_layers(example, node_id, extract, layers, tmp_path, monkeypatch):
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = _run_example_load(example, node_id, extract, tmp_path, monkeypatch)

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


#: The keys an Autark map reads a building part's top from.
TOP_KEYS = ("height", "building:height", "levels", "building:levels")


def _number(value) -> float | None:
    """*value* as a number, when it is one or text that is one, else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def test_the_server_compiled_load_hands_on_a_building_part_with_no_height_with_none(tmp_path, monkeypatch):
    """The test dataflow lower-manhattan-park-shade's load hands its building
    parts on as OpenStreetMap has them: a part with no height (none of
    ``height``, ``building:height``, ``levels`` and ``building:levels`` holds a
    number) holds none, so a node that uses one takes the default where it
    uses it, and the others hold their own.

    So what reads the data sees the gap: a Map Editor node's scale of the
    heights leaves such a part as it is (``feature_edits``: a feature whose
    column holds no number), and the dataflow's Building heights node gives it
    its Default height widget's value, 10 m (``fillna``)."""
    import geopandas as gpd

    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.input_layers import curio_layer
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    example, node_id = "dataflows/lower-manhattan-park-shade.json", "park-shade-layers"
    result = _run_example_load(example, node_id, "docs/examples/data/lower_mnt.osm.pbf", tmp_path, monkeypatch)
    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    (buildings,) = [layer for layer in loaded if layer["name"] == "table_osm_buildings"]
    parts = [feature["properties"] for feature in buildings["geojson"]["features"]]
    # No number in any key of a top: the parts the load gives no height.
    bare = [index for index, properties in enumerate(parts)
            if all(_number(properties.get(key)) is None for key in TOP_KEYS)]
    tall = [index for index, properties in enumerate(parts) if (_number(properties.get("height")) or 0) > 0]
    assert bare, (
        f"none of the {len(parts)} building parts holds no height: a part OpenStreetMap gives none is handed on "
        "with one made for it"
    )
    assert tall, f"none of the {len(parts)} building parts holds a height of its own"

    # A Map Editor node's scale of the heights of up to five such parts'
    # buildings, and of one whose height it first sets to 20 m, which it doubles.
    bare_buildings = {parts[index]["building_id"] for index in bare}
    probe = next((index for index in tall if parts[index]["building_id"] not in bare_buildings), tall[0])
    others = [index for index in bare if parts[index]["building_id"] != parts[probe]["building_id"]][:5]
    assert others, f"every one of the {len(bare)} parts with no height is in the building of part {probe}"
    edits = [
        {"op": "set", "column": "height", "value": 20, "ids": [parts[probe]["building_id"]]},
        {"op": "scale", "column": "height", "value": 2,
         "ids": sorted({parts[index]["building_id"] for index in [probe, *others]})},
    ]
    edited = edit_features(loaded, edits, key="building_id", layer="table_osm_buildings")
    (layer,) = [item for item in edited["data"] if item.get("layerName") == "table_osm_buildings"]
    after = [feature["properties"] for feature in layer["data"]["features"]]
    assert _number(after[probe]["height"]) == 40, after[probe]
    assert [_number(after[index].get("height")) for index in others] == [None] * len(others), (
        [after[index] for index in others]
    )

    # The dataflow's Building heights node, its chips as its widgets set them.
    code = _loader_content(example, "park-shade-heights")
    for chip, value in (("[!! input_0:table_osm_buildings !!]", "frame"), ("[!! floor_height !!]", "3.4"),
                        ("[!! default_height !!]", "10")):
        assert chip in code, chip
        code = code.replace(chip, value)
    frame = curio_layer(loaded, "table_osm_buildings")
    assert isinstance(frame, gpd.GeoDataFrame) and len(frame) == len(parts)
    namespace: dict = {"frame": frame}
    exec("def node():\n" + textwrap.indent(code, "    "), namespace)  # noqa: S102  (the dataflow's own node code)
    heights = namespace["node"]()["height"].tolist()
    assert [heights[index] for index in bare] == [10.0] * len(bare)
    assert [heights[index] for index in tall[:5]] == [_number(parts[index]["height"]) for index in tall[:5]]


#: Example 07's loader: the Chicago Loop's OpenStreetMap layers, and its
#: building parts among them, about 250 of which OpenStreetMap gives a height.
LOOP_LOAD = ("07-autark-gpu-shader.json", "sh-data", "docs/examples/data/chicago_loop.osm.pbf")
#: Example 06's loader: Back Bay's OpenStreetMap layers.
BACK_BAY_LOAD = ("06-back-bay-road-sunlight.json", "whatif-data", "docs/examples/data/back_bay.osm.pbf")

#: OpenStreetMap's numeric building tags, which an Autark node hands on as
#: numbers (``withOsmNumbers`` in autkDataCompile.ts): the lengths, in metres,
#: then the levels.
NUMERIC_TAGS = (
    "height", "min_height", "building:height", "roof:height",
    "building:levels", "building:min_level", "levels", "min_level", "roof:levels", "building:levels:underground",
)
#: Each load's building parts, by OSM id, whose numeric tags OpenStreetMap
#: writes with a unit or with no number that can be read, and what the load
#: hands on for them, the text in the extract beside each.
WRITTEN_OTHERWISE = {
    "chicago_loop": {
        124873939: {"height": 133.5},  # "133.5 m"
        126982631: {"height": 86},  # "86 m"
        126982632: {"height": 67.7},  # "67.7 m"
        144846553: {"height": 91},  # "91 m"
        145625877: {"height": 61.5},  # "61.5 m"
        147478105: {"height": 87},  # "87 m"
        148164130: {"height": 86},  # "86m"
        1178203072: {"building:levels": None},  # "7-7", a range
    },
    "back_bay": {
        29623484: {"height": 241},  # "241m", 200 Clarendon's tower
        29869880: {"height": 228.6},  # "228.6m", the Prudential Tower
        117889600: {"height": 102},  # "102m"
        240278719: {"height": 64, "roof:height": 15},  # "64m", and "15"
    },
}
#: Each load's building parts, by OSM id, whose numeric tags OpenStreetMap
#: writes as plain numbers, and the numbers the load hands on.
WRITTEN_PLAIN = {
    "chicago_loop": {
        15930576: {"height": 42.3, "building:levels": 12},
        15937050: {"height": 261.8, "building:levels": 82},
        1179624203: {"height": 175, "building:levels": 44, "roof:levels": 1},
        1433561730: {"height": 240, "building:levels": 74, "building:min_level": 12},
    },
    "back_bay": {
        823008368: {"height": 6.8, "min_height": 3.4, "building:levels": 2, "building:min_level": 1},
        240711152: {"height": 45, "roof:height": 4, "building:levels": 9},
    },
}
#: How many of the Chicago Loop's building parts the load gives a height above
#: 100 m: 179 written as plain numbers, and one written "133.5 m".
LOOP_PARTS_ABOVE_100_M = 180


def _a_number(value) -> bool:
    """Whether *value* is a number, never a text or a bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _served_layers(example: str, node_id: str, extract: str, tmp_path, monkeypatch) -> list:
    """What the server-compiled load of *example*'s node *node_id* stores,
    *extract* served from disk, as the tests above run it
    (``_run_example_load``): a layer record ``{name, type, geojson}`` each."""
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    result = _run_example_load(example, node_id, extract, tmp_path, monkeypatch)
    assert result["output"]["path"], result["stderr"]
    return load_from_duckdb(result["output"]["path"], session_id=None)


def _as_stored(layers: list) -> dict:
    """*layers*, the records a load returned, as each place keeps them that a
    Map Editor reads them from: as a run on the server stores them, and as the
    canvas's Autark node stores them (``persistLayersToBackend``), an envelope
    a layer, which reach the Map Editor as tables."""
    return {
        "as a run on the server stores them": layers,
        "as the canvas stores them": {"dataType": "outputs", "data": [
            {"dataType": "geodataframe", "data": layer["geojson"],
             "layerName": layer["name"], "layerType": layer["type"]}
            for layer in layers
        ]},
    }


@pytest.mark.parametrize("load, extract", [(LOOP_LOAD, "chicago_loop"), (BACK_BAY_LOAD, "back_bay")],
                         ids=["chicago_loop", "back_bay"])
def test_the_server_compiled_load_hands_on_openstreetmaps_numeric_building_tags_as_numbers(
    load, extract, tmp_path, monkeypatch,
):
    """OpenStreetMap writes every tag as text, and autk-db keeps it so. The
    load hands each numeric building tag on as a number: a plain number as
    that number, a length with its unit in metres, and a value with no number
    that can be read, such as a range of levels, as none. No such tag of any
    building part is left as text."""
    layers = _served_layers(*load, tmp_path, monkeypatch)
    buildings = next(layer for layer in layers if layer["name"] == "table_osm_buildings")
    parts = [feature["properties"] for feature in buildings["geojson"]["features"]]
    texts = sorted({
        (key, repr(part[key])) for part in parts for key in NUMERIC_TAGS
        if key in part and part[key] is not None and not _a_number(part[key])
    })
    assert texts == [], (
        f"the load hands on {len(texts)} values of numeric building tags that are no numbers, such as {texts[:12]}"
    )
    by_id = {part["osm_id"]: part for part in parts}
    for expected in (WRITTEN_OTHERWISE[extract], WRITTEN_PLAIN[extract]):
        handed = {
            osm_id: {key: by_id[osm_id].get(key, "missing") for key in tags} if osm_id in by_id else "missing"
            for osm_id, tags in expected.items()
        }
        assert handed == expected


def test_a_map_editor_rule_picks_the_loops_tall_buildings_and_an_expression_halves_them(tmp_path, monkeypatch):
    """On the Chicago Loop's load, the rule ``height > 100``, the rule the
    Map Editor's guide gives, picks every building part the load gives a
    height above 100 m, a height written with its unit among them, and the
    expression ``height * 0.5`` halves each: on the layers as a run on the
    server stores them and as the canvas stores them, a table each. Every
    other part keeps its height."""
    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.stored_inputs import read_stored

    layers = _served_layers(*LOOP_LOAD, tmp_path, monkeypatch)
    buildings = next(layer for layer in layers if layer["name"] == "table_osm_buildings")
    before = [feature["properties"].get("height") for feature in buildings["geojson"]["features"]]
    tall = [at for at, height in enumerate(before) if _a_number(height) and height > 100]
    assert len(tall) == LOOP_PARTS_ABOVE_100_M, (
        f"the load gives {len(tall)} parts a height above 100 m as a number, not {LOOP_PARTS_ABOVE_100_M}"
    )
    osm_ids = [feature["properties"]["osm_id"] for feature in buildings["geojson"]["features"]]
    assert osm_ids.index(124873939) in tall, "the part OpenStreetMap writes as 133.5 m is not among them"
    edits = [{"op": "expr", "where": "height > 100", "column": "height", "value": "height * 0.5",
              "label": "Every part above 100 m at half its height"}]
    for how, value in _as_stored(layers).items():
        out = edit_features(
            read_stored(copy.deepcopy(value)), copy.deepcopy(edits), key="osm_id", layer="table_osm_buildings",
        )
        edited = next(item for item in out["data"] if item.get("layerName") == "table_osm_buildings")
        after = [feature["properties"].get("height") for feature in edited["data"]["features"]]
        assert [feature["properties"]["osm_id"] for feature in edited["data"]["features"]] == osm_ids, how
        picked = [at for at in range(len(before)) if after[at] != before[at]]
        assert picked == tall, (
            f"{how}: the rule height > 100 changed {len(picked)} parts, not the {len(tall)} above 100 m"
        )
        assert all(_a_number(after[at]) for at in tall), (how, [after[at] for at in tall[:5]])
        assert [after[at] for at in tall] == pytest.approx([before[at] * 0.5 for at in tall]), how


def test_a_map_editor_scales_and_offsets_the_heights_openstreetmap_writes_as_text(tmp_path, monkeypatch):
    """OpenStreetMap writes each height of the Chicago Loop's building parts
    as text ("42.3", "133.5 m"), and the load hands each on as the number it
    is. A Map Editor below the load scales and offsets three of them, one
    written with its unit among them: each becomes twice its height plus one,
    a number, on the layers as a run on the server stores them and as the
    canvas stores them, a table each."""
    from utk_curio.sandbox.util.feature_edits import edit_features
    from utk_curio.sandbox.util.stored_inputs import read_stored

    layers = _served_layers(*LOOP_LOAD, tmp_path, monkeypatch)
    buildings = next(layer for layer in layers if layer["name"] == "table_osm_buildings")
    heights = {
        feature["properties"]["osm_id"]: feature["properties"].get("height")
        for feature in buildings["geojson"]["features"]
    }
    # "42.3", "184" and "133.5 m" in the extract.
    picked = [15930576, 28951633, 124873939]
    before = {osm_id: heights.get(osm_id) for osm_id in picked}
    # The case: the load hands each height on as the number it is.
    assert all(_a_number(height) for height in before.values()), (
        f"the load hands on these heights as {before}, not as numbers"
    )
    edits = [
        {"op": "scale", "ids": picked, "column": "height", "value": 2},
        {"op": "offset", "ids": picked, "column": "height", "value": 1},
    ]
    for how, value in _as_stored(layers).items():
        out = edit_features(
            read_stored(copy.deepcopy(value)), copy.deepcopy(edits), key="osm_id", layer="table_osm_buildings",
        )
        edited = next(item for item in out["data"] if item.get("layerName") == "table_osm_buildings")
        after = {
            feature["properties"]["osm_id"]: feature["properties"].get("height")
            for feature in edited["data"]["features"]
            if feature["properties"].get("osm_id") in picked
        }
        assert sorted(after) == sorted(picked), (how, sorted(after))
        assert all(_a_number(after[osm_id]) for osm_id in picked), (how, before, after)
        assert after == pytest.approx(
            {osm_id: before[osm_id] * 2 + 1 for osm_id in picked}
        ), f"{how}: heights {before} became {after}, not twice them plus one"


AUTK_GRAMMAR_VERSION = "5.5.1"

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


def _run_load(document: dict, tmp_path, monkeypatch) -> dict:
    """*document* compiled as a run on the server compiles an Autark data node,
    run through ``execute_js_code``, with no socket and nothing in."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("FLASK_BACKEND_HOST", "curio-backend.invalid")
    monkeypatch.setenv("FLASK_BACKEND_PORT", "1")
    dependencies.seed_duckdb_extensions()
    _worker_init()
    return execute_js_code(
        _NO_SOCKET + compile_data_spec(json.dumps(document)), "", "AUTK_GRAMMAR", "",
        launch_dir=str(REPO_ROOT), session_id=None,
    )


def test_the_server_compiled_load_counts_the_rows_near_each_cell_of_a_heatmap_without_group_by(tmp_path, monkeypatch):
    """A heatmap that writes no ``groupBy`` has one band, which counts the
    readings near each cell's center, as one that writes a count does
    (autk-grammar 5.5.0 hands autk-db that count; left to itself, autk-db
    labelled the band a count and joined no aggregate, so every cell read 0)."""
    import numpy as np

    from utk_curio.sandbox.util.parsers import load_from_duckdb
    from utk_curio.sandbox.util.rasters import envelope_arrays

    readings, heatmap = LEVEL_HEATMAP["data"]
    without = {key: value for key, value in heatmap.items() if key != "groupBy"}
    result = _run_load({"data": [readings, without]}, tmp_path, monkeypatch)

    assert result["output"]["path"], result["stderr"]
    loaded = load_from_duckdb(result["output"]["path"], session_id=None)
    assert [(item.get("dataType"), item.get("layerName")) for item in loaded[1:]] == [("raster", "noise")]
    noise = loaded[1]
    _grid, bands, cells = envelope_arrays(noise)
    assert bands == ["band_1"]
    assert noise["data"]["features"][0]["properties"]["bands"] == [{"id": "band_1", "label": "count_levels"}]
    expected = _cells_from_the_levels()["count"]
    # Cells of none to four readings, so a band of zeros cannot pass.
    assert {value for row in expected for value in row} == {0.0, 1.0, 2.0, 3.0, 4.0}
    np.testing.assert_allclose(cells[0], expected, err_msg="the count of the readings near each cell")


def test_the_server_compiled_load_refuses_a_heatmap_entry_without_an_aggregate(tmp_path, monkeypatch):
    """A ``groupBy`` entry without ``aggregateFn`` combines nothing, and a cell
    holds one value: the load fails, in autk-grammar 5.5.1's words, and hands
    nothing on (autk-db built such a band, labelled ``value_levels``, of zeros)."""
    readings, heatmap = LEVEL_HEATMAP["data"]
    entries = [{"column": "*", "aggregateFn": "count"}, {"column": "db"}]
    result = _run_load({"data": [readings, {**heatmap, "groupBy": entries}]}, tmp_path, monkeypatch)

    assert not result["output"]["path"], "the load handed on a heatmap with a band that combines nothing"
    assert (
        'Heatmap "noise": the groupBy entry for column "db" has no aggregateFn to combine the rows near a cell, '
        "and a cell holds one value; use sum, avg, count, min, max or weighted."
    ) in result["stderr"], result["stderr"]


def test_the_server_compiled_load_refuses_a_source_whose_after_is_not_compute(tmp_path, monkeypatch):
    """A source runs after compute or before it: autk-grammar's ``dataPhases``,
    which the load asks before anything loads, refuses any other ``after``,
    in its words."""
    readings, _heatmap = LEVEL_HEATMAP["data"]
    result = _run_load({"data": [{**readings, "after": "map"}]}, tmp_path, monkeypatch)

    assert not result["output"]["path"], "the load handed on a source whose after names no phase"
    assert result["stderr"].startswith(
        "Data source 0 (geojson): after must be 'compute', the one phase a source runs after, not \"map\"."
    ), result["stderr"]


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
    source loads into its workspace through autk-grammar's own data adapter
    (``createDataAdapter``), which enters it, and each workspace's tables are
    read back in it, entered with the grammar's ``enterWorkspace``, both from
    its ``./data`` entry, so two workspaces hold a
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
    assert "import { createDataAdapter, enterWorkspace, tableKey } from '@urban-toolkit/autk-grammar/data';" in code
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
