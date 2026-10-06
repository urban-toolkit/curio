"""A layer chip in code (#662): ``[!! input 0:table_osm_roads !!]`` runs as
``curio_layer(arg, "table_osm_roads", 0)``, the layer of that name among the
ones input 0 carries, found by its name exactly as an Autark spec finds it.

Python's helper is ``util/input_layers.py``; JavaScript's twin is defined in
``util/js_wrapper.mjs``. Both are reached by name from node code, in process
and under isolation, and both say the same when the layer is missing: the
input, by its circle, and the layers it has.

Every test imports what it needs itself, so a checkout without the helper
fails test by test.
"""
from __future__ import annotations

import json

import pytest

#: Autark names its workspace's coordinate system on each layer it hands on.
CRS_3395 = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}}


def _fc(rows, crs=CRS_3395):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": properties, "geometry": {"type": "LineString", "coordinates": [[i, i], [i + 1, i]]}}
            for i, properties in enumerate(rows)
        ],
    }
    if crs is not None:
        fc["crs"] = crs
    return fc


def records():
    """What an Autark node with a data section hands on (its backend load in
    ``autkDataCompile.ts``): a list of ``{name, type, geojson}``."""
    return [
        {"name": "table_osm_roads", "type": "roads", "geojson": _fc([{"highway": "primary"}, {"highway": "service"}])},
        {"name": "table_osm_buildings", "type": "buildings", "geojson": _fc([{"height": 12.0}])},
    ]


def envelopes():
    """What an Autark compute step hands on: every layer in one ``outputs``
    envelope, each under its ``layerName``."""
    return {
        "dataType": "outputs",
        "data": [
            {"dataType": "geodataframe", "layerName": "table_osm_roads", "layerType": "roads",
             "data": _fc([{"highway": "primary"}, {"highway": "service"}])},
            {"dataType": "geodataframe", "layerName": "table_osm_buildings", "layerType": "buildings",
             "data": _fc([{"height": 12.0}])},
        ],
    }


def _layer(value, name, slot=0):
    from utk_curio.sandbox.util.input_layers import curio_layer

    return curio_layer(value, name, slot)


class TestTheLayerIsFoundByItsName:
    def test_an_autark_data_nodes_layer_array(self):
        import geopandas as gpd

        roads = _layer(records(), "table_osm_roads")
        assert isinstance(roads, gpd.GeoDataFrame)
        assert roads["highway"].tolist() == ["primary", "service"]
        assert roads.crs.to_epsg() == 3395, "the layer's own coordinate system was lost"
        assert roads.metadata == {"name": "table_osm_roads", "layerType": "roads"}

    def test_an_autark_compute_steps_envelope(self):
        import geopandas as gpd

        buildings = _layer(envelopes(), "table_osm_buildings")
        assert isinstance(buildings, gpd.GeoDataFrame)
        assert buildings["height"].tolist() == [12.0]
        assert buildings.crs.to_epsg() == 3395
        assert buildings.metadata == {"name": "table_osm_buildings", "layerType": "buildings"}

    def test_one_layer_on_its_own(self):
        roads = _layer(envelopes()["data"][0], "table_osm_roads")
        assert roads["highway"].tolist() == ["primary", "service"]
        roads = _layer(records()[0], "table_osm_roads")
        assert roads["highway"].tolist() == ["primary", "service"]

    def test_frames_that_carry_their_name(self):
        import geopandas as gpd
        from shapely.geometry import Point

        a = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        a.__dict__["metadata"] = {"name": "parks"}
        b.__dict__["metadata"] = {"name": "water"}
        assert _layer((a, b), "water") is b
        assert _layer([a, b], "parks") is a
        assert _layer(a, "parks") is a

    def test_a_column_named_metadata_is_not_a_name(self):
        import pandas as pd

        frames = [pd.DataFrame({"metadata": ["parks"]}), pd.DataFrame({"metadata": ["water"]})]
        with pytest.raises(LookupError, match="It carries no named layers"):
            _layer(frames, "parks")


class TestOneFrameWithNoName:
    """An input that carries exactly one frame with no layer name is that
    layer, whatever the chip calls it: a roads GeoDataFrame a Python node
    returns or Data Loading reads reaches a template that reads
    ``[!! input 0:table_osm_roads !!]`` as it reached one that read ``arg``."""

    def test_a_frame_on_its_own(self):
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import Point

        roads = gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[Point(0, 0)], crs="EPSG:3395")
        assert _layer(roads, "table_osm_roads") is roads
        assert _layer([roads], "table_osm_roads") is roads
        assert _layer((roads,), "anything") is roads
        table = pd.DataFrame({"a": [1]})
        assert _layer(table, "roads") is table

    def test_one_unnamed_layer_record_or_envelope(self):
        import geopandas as gpd

        record = {"type": "roads", "geojson": _fc([{"highway": "primary"}, {"highway": "service"}])}
        roads = _layer([record], "table_osm_roads")
        assert isinstance(roads, gpd.GeoDataFrame) and roads.crs.to_epsg() == 3395
        assert roads["highway"].tolist() == ["primary", "service"]
        envelope = {"dataType": "geodataframe", "data": _fc([{"height": 12.0}])}
        assert _layer(envelope, "table_osm_buildings")["height"].tolist() == [12.0]

    def test_several_frames_still_need_the_name(self):
        import geopandas as gpd
        from shapely.geometry import Point

        a = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        b = gpd.GeoDataFrame({"v": [2]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        with pytest.raises(LookupError) as raised:
            _layer([a, b], "table_osm_roads", 2)
        assert str(raised.value) == (
            "[!! input 2:table_osm_roads !!]: input 2 has no layer table_osm_roads. It carries no named layers."
        )

    def test_one_frame_named_otherwise_is_not_it(self):
        import geopandas as gpd
        from shapely.geometry import Point

        parks = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        parks.__dict__["metadata"] = {"name": "table_osm_parks"}
        with pytest.raises(LookupError) as raised:
            _layer(parks, "table_osm_roads", 0)
        assert str(raised.value).endswith("has no layer table_osm_roads. Its layers are table_osm_parks.")

    def test_the_envelope_an_input_circle_is_expanded_from_keeps_the_names(self):
        """A single input holding a compute step's envelope reaches node code
        expanded, a frame per layer: each keeps its layer name."""
        from utk_curio.sandbox.app.worker import _expand_outputs_wrapper

        frames = _expand_outputs_wrapper(envelopes())
        assert [frame.metadata for frame in frames] == [
            {"name": "table_osm_roads", "layerType": "roads"},
            {"name": "table_osm_buildings", "layerType": "buildings"},
        ]
        assert _layer(frames, "table_osm_buildings") is frames[1]

    def test_the_name_is_the_table_name_exactly(self):
        """``roads`` is the layer's type; Autark reads it as ``table_osm_roads``."""
        with pytest.raises(LookupError, match=r"has no layer roads\."):
            _layer(records(), "roads")


class TestAMissingLayer:
    def test_it_names_the_input_and_the_layers_it_has(self):
        with pytest.raises(LookupError) as raised:
            _layer(records(), "table_osm_water", 2)
        assert str(raised.value) == (
            "[!! input 2:table_osm_water !!]: input 2 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        )

    def test_an_input_with_no_named_layers(self):
        import pandas as pd

        for value in (None, [pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})], [1, 2], {"a": 1}):
            with pytest.raises(LookupError) as raised:
                _layer(value, "roads", 1)
            assert str(raised.value) == "[!! input 1:roads !!]: input 1 has no layer roads. It carries no named layers."


class TestNodeCodeReachesIt:
    """The node's code calls it by name, in process and under isolation."""

    CODE = (
        "    roads = curio_layer(arg, \"table_osm_roads\", 0)\n"
        "    return f\"{len(roads)} {roads.crs.to_epsg()} {roads.metadata['name']}\"\n"
    )

    def _store(self):
        from utk_curio.sandbox.app.worker import _worker_init
        from utk_curio.sandbox.util.db import init_db

        _worker_init()
        init_db()

    def test_an_in_process_node_reads_an_autark_data_nodes_layer(self):
        """The Autark data node's load runs in the sandbox's Node, which stores
        its layer array; a Python node reads one layer of it."""
        from utk_curio.sandbox.app.worker import execute_code, execute_js_code
        from utk_curio.sandbox.util.parsers import load_from_duckdb

        self._store()
        produced = execute_js_code(f"return {json.dumps(records())};", "", "AUTK_GRAMMAR", "", save_dataset=False)
        assert produced["stderr"] == "", produced["stderr"]
        output = produced["output"]
        result = execute_code(self.CODE, output["path"], "curio.builtin/computation-analysis", output["dataType"],
                              save_dataset=False)
        assert result["stderr"] == "", result["stderr"]
        assert load_from_duckdb(result["output"]["path"]) == "2 3395 table_osm_roads"

    def test_an_in_process_node_names_the_missing_layer(self):
        from utk_curio.sandbox.app.worker import execute_code, execute_js_code

        self._store()
        produced = execute_js_code(f"return {json.dumps(records())};", "", "AUTK_GRAMMAR", "", save_dataset=False)
        output = produced["output"]
        result = execute_code("    return curio_layer(arg, \"table_osm_water\", 0)\n", output["path"],
                              "curio.builtin/computation-analysis", output["dataType"], save_dataset=False)
        assert (
            "[!! input 0:table_osm_water !!]: input 0 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        ) in result["stderr"]

    def _isolated(self, tmp_path, code):
        from utk_curio.sandbox.isolation import child, zygote

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        (scratch / "layers.json").write_text(json.dumps(records()), encoding="utf-8")
        request = {
            "code": code,
            "node_type": "curio.builtin/computation-analysis", "data_type": "",
            "scratch_dir": str(scratch), "input": {"kind": "json", "file": "layers.json"},
            "session_imports": [], "limits": {},
        }
        return child.run_node(request, zygote.build_namespace_template)

    def test_an_isolated_node(self, tmp_path):
        result = self._isolated(tmp_path, self.CODE)
        assert result["ok"], result["stderr"]
        assert result["output"]["value"] == "2 3395 table_osm_roads"

    def test_an_isolated_node_names_the_missing_layer(self, tmp_path):
        result = self._isolated(tmp_path, "    return curio_layer(arg, \"table_osm_water\", 3)\n")
        assert not result["ok"]
        assert (
            "[!! input 3:table_osm_water !!]: input 3 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        ) in result["stderr"]


class TestTheJavaScriptTwin:
    """``curio_layer`` in ``js_wrapper.mjs`` finds the same layers and says
    the same when one is missing."""

    def _run(self, code, value):
        from utk_curio.sandbox.app.worker import run_js_script

        result, _logs, stderr = run_js_script(code, value, cwd=".", node_type="curio.builtin/js-computation")
        assert result is not None, "\n".join(stderr)
        return json.loads(result)

    def test_it_reads_a_layer_array_an_envelope_and_a_named_frame(self):
        import geopandas as gpd
        from shapely.geometry import Point

        code = "const roads = curio_layer(arg, \"table_osm_roads\", 0);\nreturn roads.features.map((f) => f.properties.highway);"
        for value in (records(), envelopes()):
            run = self._run(code, value)
            assert run["success"], run.get("error")
            assert run["value"] == ["primary", "service"]
        # A frame that carries its name reaches JavaScript as a
        # FeatureCollection that does too.
        parks = gpd.GeoDataFrame({"v": [7]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        parks.__dict__["metadata"] = {"name": "parks"}
        run = self._run("return curio_layer(arg, \"parks\", 0).features[0].properties.v;", [parks])
        assert run["success"], run.get("error")
        assert run["value"] == 7

    def test_one_frame_with_no_name_is_the_layer_and_several_still_need_it(self):
        import geopandas as gpd
        from shapely.geometry import Point

        from utk_curio.sandbox.util.input_layers import missing_layer_message

        roads = gpd.GeoDataFrame({"v": [7]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        run = self._run("return curio_layer(arg, \"table_osm_roads\", 0).features[0].properties.v;", roads)
        assert run["success"], run.get("error")
        assert run["value"] == 7
        other = gpd.GeoDataFrame({"v": [8]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        run = self._run("return curio_layer(arg, \"table_osm_roads\", 0);", [roads, other])
        assert not run["success"]
        assert run["error"].startswith(missing_layer_message(0, "table_osm_roads", []) + "\n"), run["error"]

    def test_a_missing_layer_says_what_python_says(self):
        from utk_curio.sandbox.util.input_layers import missing_layer_message

        run = self._run("return curio_layer(arg, \"table_osm_water\", 2);", records())
        assert not run["success"]
        message = missing_layer_message(2, "table_osm_water", ["table_osm_roads", "table_osm_buildings"])
        assert run["error"].startswith(message + "\n"), run["error"]
        run = self._run("return curio_layer(arg, \"roads\", 1);", {"a": 1})
        assert run["error"].startswith(missing_layer_message(1, "roads", []) + "\n"), run["error"]
