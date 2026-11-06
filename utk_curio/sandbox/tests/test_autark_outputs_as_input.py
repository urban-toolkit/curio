"""What a node reads as plain ``input_0`` after an Autark node.

An Autark compute node hands its layers on through the sandbox's Node: its
JavaScript returns the wrapper ``persistLayersToBackend`` builds
(``adapters/node/autkLayerMaterialize.ts``), which the store keeps as a
``dict`` output:

- one layer: ``{dataType: 'geodataframe', data: <FeatureCollection>,
  layerName, layerType}``;
- several: ``{dataType: 'outputs', data: [one such layer each]}``.

A Python node reads one layer as its GeoDataFrame and several as the list of
them, each keeping its layer's name and type in ``metadata`` and the
coordinate system its FeatureCollection names, in process and in an isolated
child alike. A JavaScript node reads each as its FeatureCollection, under its
layer name. A layer chip finds each layer on both paths. An Autark data
node's layer array, and a dict a node returned, are read as they are stored.

Every test imports what it needs itself, as ``test_input_layers.py`` does.
"""
from __future__ import annotations

import json
import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

SESSION = "a-sign-in-token"
CRS_3395 = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}
CRS_3395_NAME = "urn:ogc:def:crs:EPSG::3395"
REPO_ROOT = Path(__file__).resolve().parents[3]
MAP_EDITOR_CASES = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/utils/editFeatures/editFeaturesCode.cases.json"
PYTHON_NODE = "curio.builtin/computation-analysis"
JS_NODE = "curio.builtin/js-computation"
AUTARK_NODE = "curio.builtin/autk-grammar"


def _roads():
    return {
        "type": "FeatureCollection",
        "crs": CRS_3395,
        "features": [
            {"type": "Feature", "properties": {"highway": "primary"},
             "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}},
            {"type": "Feature", "properties": {"highway": "service"},
             "geometry": {"type": "LineString", "coordinates": [[1, 1], [2, 1]]}},
        ],
    }


def _buildings():
    """Building 1 in two parts, buildings 2 and 3 in one each."""
    parts = [(1, 10.0, 0), (1, 12.0, 1), (2, 30.0, 2), (3, 5.0, 3)]
    return {
        "type": "FeatureCollection",
        "crs": CRS_3395,
        "features": [
            {"type": "Feature", "properties": {"building_id": building, "height": height},
             "geometry": {"type": "Polygon", "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]}}
            for building, height, x in parts
        ],
    }


def _layer(name, layer_type, fc):
    """One layer as ``layersToPoolWrapper`` wraps it."""
    return {"dataType": "geodataframe", "data": fc, "layerName": name, "layerType": layer_type}


def one_layer():
    """What an Autark compute node that hands on one layer stores."""
    return _layer("table_osm_buildings", "buildings", _buildings())


def several_layers():
    """What an Autark compute node that hands on several layers stores."""
    return {
        "dataType": "outputs",
        "data": [_layer("table_osm_roads", "roads", _roads()), _layer("table_osm_buildings", "buildings", _buildings())],
    }


def layer_array():
    """What an Autark data node's backend load stores: ``{name, type, geojson}``
    records, which example 08's JavaScript node reads as they are."""
    return [
        {"name": "table_osm_roads", "type": "roads", "geojson": _roads()},
        {"name": "table_osm_buildings", "type": "buildings", "geojson": _buildings()},
    ]


#: What the Python nodes below say of a frame: its class, its rows without the
#: geometry, the geometry's types, its CRS and its ``metadata``.
ROADS_READ = {
    "type": "GeoDataFrame",
    "rows": [{"highway": "primary"}, {"highway": "service"}],
    "geometry": ["LineString", "LineString"],
    "crs": 3395,
    "metadata": {"name": "table_osm_roads", "layerType": "roads"},
}
BUILDINGS_READ = {
    "type": "GeoDataFrame",
    "rows": [
        {"building_id": 1, "height": 10.0}, {"building_id": 1, "height": 12.0},
        {"building_id": 2, "height": 30.0}, {"building_id": 3, "height": 5.0},
    ],
    "geometry": ["Polygon"] * 4,
    "crs": 3395,
    "metadata": {"name": "table_osm_buildings", "layerType": "buildings"},
}

DESCRIBED = '''\
import json


def described(value):
    if isinstance(value, (list, tuple)):
        return {"container": type(value).__name__, "items": [described(item) for item in value]}
    if isinstance(value, dict):
        return {"dict": value}
    return {
        "type": type(value).__name__,
        "rows": json.loads(value.drop(columns="geometry").to_json(orient="records")),
        "geometry": [str(kind) for kind in value.geom_type],
        "crs": value.crs.to_epsg() if value.crs is not None else None,
        "metadata": value.__dict__.get("metadata"),
    }
'''


def _python(last_line):
    """A Python node's code: ``described`` above, then *last_line*."""
    return textwrap.indent(f"{DESCRIBED}\n\n{last_line}\n", "    ")


READ_INPUT_0 = _python("return json.dumps(described(input_0), sort_keys=True)")
READ_THREE_INPUTS = _python("return json.dumps([described(input_0), described(input_1), described(input_2)], sort_keys=True)")

JS_DESCRIBED = (
    "const described = (fc) => ({\n"
    "  type: fc.type,\n"
    "  name: fc.name ?? null,\n"
    "  crs: fc.crs ? fc.crs.properties.name : null,\n"
    "  rows: fc.features.map((feature) => feature.properties),\n"
    "});\n"
)
JS_ROADS = {
    "type": "FeatureCollection", "name": "table_osm_roads", "crs": CRS_3395_NAME,
    "rows": ROADS_READ["rows"],
}
JS_BUILDINGS = {
    "type": "FeatureCollection", "name": "table_osm_buildings", "crs": CRS_3395_NAME,
    "rows": BUILDINGS_READ["rows"],
}


class AutarkOutputsAsInputTestCase(unittest.TestCase):
    """Each wrapper stored as an Autark node stores it, read by the next
    node's plain ``input_0`` in process and in an isolated child."""

    def setUp(self):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db, release_connection

        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {
            "CURIO_LAUNCH_CWD": self._tmp.name,
            "CURIO_SHARED_DATA": "./.curio/data/",
        })
        env.start()
        self.addCleanup(env.stop)
        (Path(self._tmp.name) / ".curio" / "data").mkdir(parents=True, exist_ok=True)
        release_connection()
        self.addCleanup(release_connection)
        init_db()
        _worker_init()
        self._runs = 0

    # -- storing, as the sandbox's Node stores what an Autark node hands on --

    def _stored_by_autark(self, value):
        """*value* stored as ``persistLayersToBackend`` stores it: JavaScript
        that returns it, whose answer is the output's ``{path, dataType}``."""
        from utk_curio.sandbox.app.worker import execute_js_code

        produced = execute_js_code(f"return {json.dumps(value)};", "", AUTARK_NODE, "",
                                   session_id=SESSION, save_dataset=False)
        self.assertEqual(produced["stderr"], "", produced["stderr"])
        self.assertTrue(produced["output"]["path"], produced)
        return produced["output"]

    # -- reading, as each runner reads a node's input --

    def _in_process(self, code, file_path, data_type, *, slots=(0,), saved_paths=None):
        from utk_curio.sandbox.app.worker import execute_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        result = execute_code(code, file_path, PYTHON_NODE, data_type, session_id=SESSION,
                              save_dataset=False, input_slots=list(slots), saved_paths=saved_paths)
        self.assertEqual(result["stderr"], "", result["stderr"])
        return json.loads(load_from_duckdb(result["output"]["path"], session_id=SESSION))

    def _isolated(self, code, file_path, data_type, *, slots=(0,), saved_paths=None):
        """The input staged as ``runner.execute_isolated`` stages it, then the
        node run as the forked child runs it."""
        from utk_curio.sandbox.isolation import child, runner, zygote

        self._runs += 1
        scratch = Path(self._tmp.name) / f"scratch-{self._runs}"
        scratch.mkdir()
        spec = runner._build_input_spec(file_path, data_type, str(scratch), SESSION, saved_paths)
        result = child.run_node({
            "code": code, "node_type": PYTHON_NODE, "data_type": data_type,
            "scratch_dir": str(scratch), "input": spec, "input_slots": list(slots),
            "session_imports": [], "limits": {},
        }, zygote.build_namespace_template)
        self.assertTrue(result["ok"], result["stderr"])
        return json.loads(result["output"]["value"])

    def _both(self, code, file_path, data_type, **kwargs):
        """What the node says of its input in process and isolated: one
        reading, which both paths must give."""
        in_process = self._in_process(code, file_path, data_type, **kwargs)
        isolated = self._isolated(code, file_path, data_type, **kwargs)
        self.assertEqual(in_process, isolated, "the isolated child read the input otherwise")
        return in_process

    def _javascript(self, code, output, data_type=None):
        from utk_curio.sandbox.app.worker import execute_js_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        result = execute_js_code(code, output["path"], JS_NODE, data_type or output["dataType"],
                                 session_id=SESSION, save_dataset=False, input_slots=[0])
        self.assertEqual(result["stderr"], "", result["stderr"])
        return load_from_duckdb(result["output"]["path"], session_id=SESSION)

    # -- one layer --

    def test_one_layer_reads_as_its_geodataframe(self):
        output = self._stored_by_autark(one_layer())
        self.assertEqual(output["dataType"], "dict")

        for data_type in ("dict", ""):
            with self.subTest(data_type=data_type):
                self.assertEqual(self._both(READ_INPUT_0, output["path"], data_type), BUILDINGS_READ)

    def test_a_javascript_node_reads_one_layer_as_its_feature_collection(self):
        output = self._stored_by_autark(one_layer())

        read = self._javascript(f"{JS_DESCRIBED}return described(input_0);", output)

        self.assertEqual(read, JS_BUILDINGS)

    # -- several layers --

    def test_several_layers_read_as_the_list_of_their_geodataframes(self):
        output = self._stored_by_autark(several_layers())
        self.assertEqual(output["dataType"], "dict")

        for data_type in ("dict", ""):
            with self.subTest(data_type=data_type):
                self.assertEqual(
                    self._both(READ_INPUT_0, output["path"], data_type),
                    {"container": "list", "items": [ROADS_READ, BUILDINGS_READ]},
                )

    def test_a_javascript_node_reads_several_layers_as_the_list_of_their_feature_collections(self):
        output = self._stored_by_autark(several_layers())

        read = self._javascript(f"{JS_DESCRIBED}return input_0.map(described);", output)

        self.assertEqual(read, [JS_ROADS, JS_BUILDINGS])

    # -- a saved output, read in place after a reopen --

    def test_a_saved_output_read_from_its_file_reads_the_same(self):
        """After a reopen under a new sign-in the store has no row for the
        output: both paths read the file the dataflow saved."""
        saved_dir = Path(self._tmp.name) / "saved"
        saved_dir.mkdir()
        for value, expected in (
            (one_layer(), BUILDINGS_READ),
            (several_layers(), {"container": "list", "items": [ROADS_READ, BUILDINGS_READ]}),
        ):
            with self.subTest(dataType=value["dataType"]):
                name = f"1787698132616_{value['dataType'][:8]}"
                path = saved_dir / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                saved = {name: {"path": str(path), "dataType": "dict"}}

                self.assertEqual(self._both(READ_INPUT_0, name, "dict", saved_paths=saved), expected)

    # -- a wrapper that names outputs, and the circles of a node with several inputs --

    def test_a_wrapper_that_names_stored_outputs_reads_as_the_outputs_it_names(self):
        """A node's one input that is a wrapper of references reads each
        output it names, an Autark layer among them as its frame."""
        import geopandas as gpd

        from utk_curio.sandbox.util.parsers import save_to_duckdb

        layer = self._stored_by_autark(_layer("table_osm_roads", "roads", _roads()))
        frame = gpd.GeoDataFrame.from_features(_buildings()["features"], crs="EPSG:3395")
        frame.__dict__["metadata"] = {"name": "table_osm_buildings", "layerType": "buildings"}
        table = save_to_duckdb(frame, node_id="a-python-node", session_id=SESSION)
        output = self._stored_by_autark({"dataType": "outputs", "data": [{"path": layer["path"]}, table]})

        self.assertEqual(
            self._both(READ_INPUT_0, output["path"], "dict"),
            {"container": "list", "items": [ROADS_READ, BUILDINGS_READ]},
        )

    def test_each_circle_of_a_node_with_several_inputs_reads_by_the_same_rule(self):
        """One layer on a circle is its frame, several are the list of them;
        a wrapper that names other outputs, on one circle of several, is read
        as it is stored, since only a node's one input reads the outputs its
        wrapper names."""
        one = self._stored_by_autark(one_layer())
        several = self._stored_by_autark(several_layers())
        naming = {"dataType": "outputs", "data": [{"path": one["path"]}]}
        named = self._stored_by_autark(naming)
        refs = str([{"path": one["path"]}, {"path": several["path"]}, {"path": named["path"]}])

        self.assertEqual(
            self._both(READ_THREE_INPUTS, refs, "outputs", slots=(0, 1, 2)),
            [BUILDINGS_READ, {"container": "list", "items": [ROADS_READ, BUILDINGS_READ]}, {"dict": naming}],
        )

    # -- layer chips --

    def test_a_layer_chip_finds_each_layer(self):
        for value in (one_layer(), several_layers()):
            output = self._stored_by_autark(value)
            with self.subTest(dataType=value["dataType"]):
                code = _python('return json.dumps(described(curio_layer(input_0, "table_osm_buildings", 0)), sort_keys=True)')
                self.assertEqual(self._both(code, output["path"], "dict"), BUILDINGS_READ)
        roads = _python('return json.dumps(described(curio_layer(input_0, "table_osm_roads", 0)), sort_keys=True)')
        output = self._stored_by_autark(several_layers())
        self.assertEqual(self._both(roads, output["path"], "dict"), ROADS_READ)

    def test_a_javascript_layer_chip_finds_each_layer(self):
        code = f"{JS_DESCRIBED}const {{ name, ...found }} = described(curio_layer(input_0, \"table_osm_buildings\", 0));\nreturn found;"
        expected = {key: value for key, value in JS_BUILDINGS.items() if key != "name"}
        for value in (one_layer(), several_layers()):
            with self.subTest(dataType=value["dataType"]):
                self.assertEqual(self._javascript(code, self._stored_by_autark(value)), expected)

    # -- what is read as it is stored --

    def test_an_autark_data_nodes_layer_array_is_read_as_it_is_stored(self):
        output = self._stored_by_autark(layer_array())
        self.assertEqual(output["dataType"], "list")

        for data_type in ("list", ""):
            with self.subTest(data_type=data_type):
                self.assertEqual(
                    self._both(READ_INPUT_0, output["path"], data_type),
                    {"container": "list", "items": [{"dict": record} for record in layer_array()]},
                )
        read = self._javascript(
            "return input_0.map((layer) => [layer.name, layer.type, layer.geojson.type, layer.geojson.features.length]);",
            output,
        )
        self.assertEqual(read, [["table_osm_roads", "roads", "FeatureCollection", 2],
                                ["table_osm_buildings", "buildings", "FeatureCollection", 4]])

    def test_a_dict_a_node_returned_is_read_as_it_is_stored(self):
        """A plain dict, one whose ``dataType`` holds no frame, and one that
        says geodataframe but holds no FeatureCollection."""
        for value in (
            {"a": 1, "b": [1, 2]},
            {"dataType": "dict", "data": {"a": 1}},
            {"dataType": "geodataframe", "data": {"rows": []}},
        ):
            output = self._stored_by_autark(value)
            with self.subTest(value=value):
                self.assertEqual(self._both(READ_INPUT_0, output["path"], "dict"), {"dict": value})
                self.assertEqual(self._javascript("return input_0;", output), value)

    # -- the Map Editor --

    def test_the_map_editor_edits_the_one_layer_its_input_0_reads(self):
        """The shipped Map Editor code, on one Autark layer through plain
        ``input_0``: its edit lands on the layer it names, and the next node
        reads the edited layer under its name."""
        from utk_curio.sandbox.app.worker import execute_code

        case = json.loads(MAP_EDITOR_CASES.read_text(encoding="utf-8"))["cases"][1]
        self.assertEqual(case["settings"]["layer"], "table_osm_buildings")
        output = self._stored_by_autark(one_layer())

        edited = execute_code(textwrap.indent(case["code"], "    "), output["path"], "curio.builtin/edit-features",
                              output["dataType"], session_id=SESSION, save_dataset=False, input_slots=[0])

        self.assertEqual(edited["stderr"], "", edited["stderr"])
        self.assertIn("features matched on building_id: 3 removed.", "\n".join(edited["stdout"]))
        read = self._in_process(READ_INPUT_0, edited["output"]["path"], edited["output"]["dataType"])
        self.assertEqual(read, {**BUILDINGS_READ, "rows": [{"building_id": 2, "height": 30.0}], "geometry": ["Polygon"]})


if __name__ == "__main__":
    unittest.main()
