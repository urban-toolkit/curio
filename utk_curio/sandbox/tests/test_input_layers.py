"""A layer chip in code (#662): ``[!! input_0:table_osm_roads !!]`` runs as
``curio_layer(input_0, "table_osm_roads", 0)``, the layer of that name among the
ones input_0 carries, found by its name exactly as an Autark spec finds it.

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


def heatmap():
    """The heatmap example 34's data node builds, ``park_access``, in the
    envelope a raster is handed on in (``rasterEnvelope`` in
    ``autkDataCompile.ts``): 3 by 2 cells and one band, the parks within reach
    of each cell, labelled as autk-db labels a ``count`` over ``tip_parks``.
    Its cells are 0, 1, 4 on the south row and 2, 7, 12 on the north one,
    base64 of little-endian float32."""
    return {
        "dataType": "raster",
        "layerName": "park_access",
        "data": {
            "type": "FeatureCollection",
            "bbox": [-8239800, 4968800, -8239500, 4969000],
            "grid": {"crs": "EPSG:3395", "width": 3, "height": 2, "originX": -8239800, "originY": 4969000,
                     "resX": 100, "resY": -100},
            "features": [{
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "rasterResX": 3,
                    "rasterResY": 2,
                    "bands": [{"id": "band_1", "label": "count_tip_parks"}],
                    "band_1": {"float32le": "AAAAAAAAgD8AAIBAAAAAQAAA4EAAAEBB"},
                },
            }],
        },
    }


def elevation(folder, name="elevation.tif", width=4, height=3):
    """A Python node's raster: a GeoTIFF of two bands, the first described."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    path = str(folder / name)
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=2, dtype="float32",
                       crs="EPSG:3395", transform=from_origin(0, height * 10, 10, 10)) as target:
        target.write(np.ones((2, height, width), dtype="float32"))
        target.set_band_description(1, "elevation_m")
    return rasterio.open(path)


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
    ``[!! input_0:table_osm_roads !!]`` as it reached one that read ``input_0`` alone."""

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
            "[!! input_2:table_osm_roads !!]: input_2 has no layer table_osm_roads. It carries no named layers."
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
            "[!! input_2:table_osm_water !!]: input_2 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        )

    def test_an_input_with_no_named_layers(self):
        import pandas as pd

        for value in (None, [pd.DataFrame({"a": [1]}), pd.DataFrame({"a": [2]})], [1, 2], {"a": 1}):
            with pytest.raises(LookupError) as raised:
                _layer(value, "roads", 1)
            assert str(raised.value) == "[!! input_1:roads !!]: input_1 has no layer roads. It carries no named layers."


class TestARasterIsALayer:
    """A raster an input carries is one of its layers, found by its name as a
    table is (the editor lists it among them): example 34's heatmap reaches a
    Python node as a rasterio dataset that keeps its table's name, and a
    raster on its own with no layer name is that layer, as one frame is."""

    def _handed_on(self):
        """Example 34's data node's tables and its heatmap: as a run in the
        browser hands them on, one ``outputs`` envelope, and as a run on the
        server does, a list of layer records then the heatmap's envelope."""
        return (
            {"dataType": "outputs", "data": [*envelopes()["data"], heatmap()]},
            [*records(), heatmap()],
        )

    def test_a_heatmap_handed_on_with_tables_is_found_by_its_name(self, tmp_path):
        import rasterio

        from utk_curio.sandbox.app.worker import _expand_outputs_wrapper
        from utk_curio.sandbox.util.rasters import rasters_for_python

        for handed_on in self._handed_on():
            value = rasters_for_python(_expand_outputs_wrapper(handed_on), tmp_path)
            heat = _layer(value, "park_access")
            assert isinstance(heat, rasterio.io.DatasetReader)
            assert heat.descriptions == ("count_tip_parks",)
            assert heat.read(1).tolist() == [[2.0, 7.0, 12.0], [0.0, 1.0, 4.0]]
            assert heat.metadata == {"name": "park_access"}
            # Its tables are found as before.
            assert _layer(value, "table_osm_roads")["highway"].tolist() == ["primary", "service"]

    def test_a_missing_layer_names_the_heatmap_among_the_layers(self, tmp_path):
        from utk_curio.sandbox.app.worker import _expand_outputs_wrapper
        from utk_curio.sandbox.util.rasters import rasters_for_python

        value = rasters_for_python(_expand_outputs_wrapper(self._handed_on()[0]), tmp_path)
        with pytest.raises(LookupError) as raised:
            _layer(value, "table_osm_water", 0)
        assert str(raised.value) == (
            "[!! input_0:table_osm_water !!]: input_0 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings, park_access."
        )

    def test_a_raster_on_its_own_with_no_layer_name_is_the_layer(self, tmp_path):
        dem = elevation(tmp_path)
        try:
            assert _layer(dem, "elevation") is dem
            assert _layer([dem], "anything") is dem
            assert _layer((dem,), "table_osm_roads") is dem
        finally:
            dem.close()

    def test_a_raster_named_otherwise_is_not_it(self, tmp_path):
        from utk_curio.sandbox.util.rasters import rasters_for_python

        heat = rasters_for_python(heatmap(), tmp_path)
        assert _layer(heat, "park_access") is heat
        with pytest.raises(LookupError) as raised:
            _layer(heat, "elevation", 1)
        assert str(raised.value).endswith("has no layer elevation. Its layers are park_access.")


class TestADictOfFrames:
    """A Python node's dict of frames, as the next Python node gets it: each
    frame or raster it holds is a layer named after its key, as the editor
    lists it (``keyedFramesAsOutputs``). A JSON dict carries no layers."""

    def test_a_layer_chip_reads_a_frame_or_a_raster_by_its_key(self, tmp_path):
        import geopandas as gpd
        from shapely.geometry import Point

        parks = gpd.GeoDataFrame({"leisure": ["park"]}, geometry=[Point(0, 0)], crs="EPSG:3395")
        roads = gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[Point(1, 1)], crs="EPSG:3395")
        dem = elevation(tmp_path)
        try:
            value = {"tip_parks": parks, "tip_roads": roads, "elevation": dem}
            assert _layer(value, "tip_roads") is roads
            assert _layer(value, "elevation") is dem
            # One table and a raster are two layers too.
            assert _layer({"tip_parks": parks, "elevation": dem}, "tip_parks") is parks
        finally:
            dem.close()

    def test_a_key_it_does_not_have_names_the_ones_that_are_layers(self, tmp_path):
        import pandas as pd

        dem = elevation(tmp_path)
        try:
            value = {"means": pd.DataFrame({"a": [1]}), "elevation": dem, "count": 3}
            with pytest.raises(LookupError) as raised:
                _layer(value, "count", 2)
            assert str(raised.value) == (
                "[!! input_2:count !!]: input_2 has no layer count. Its layers are means, elevation."
            )
        finally:
            dem.close()


class TestNodeCodeReachesIt:
    """The node's code calls it by name, in process and under isolation."""

    CODE = (
        "    roads = curio_layer(input_0, \"table_osm_roads\", 0)\n"
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
        result = execute_code(self.CODE, output["path"], "curio.builtin/python-computation", output["dataType"],
                              save_dataset=False)
        assert result["stderr"] == "", result["stderr"]
        assert load_from_duckdb(result["output"]["path"]) == "2 3395 table_osm_roads"

    def test_an_in_process_node_names_the_missing_layer(self):
        from utk_curio.sandbox.app.worker import execute_code, execute_js_code

        self._store()
        produced = execute_js_code(f"return {json.dumps(records())};", "", "AUTK_GRAMMAR", "", save_dataset=False)
        output = produced["output"]
        result = execute_code("    return curio_layer(input_0, \"table_osm_water\", 0)\n", output["path"],
                              "curio.builtin/python-computation", output["dataType"], save_dataset=False)
        assert (
            "[!! input_0:table_osm_water !!]: input_0 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        ) in result["stderr"]

    def _isolated(self, tmp_path, code):
        from utk_curio.sandbox.isolation import child, zygote

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        (scratch / "layers.json").write_text(json.dumps(records()), encoding="utf-8")
        request = {
            "code": code,
            "node_type": "curio.builtin/python-computation", "data_type": "",
            "scratch_dir": str(scratch), "input": {"kind": "json", "file": "layers.json"},
            "input_slots": [0], "session_imports": [], "limits": {},
        }
        return child.run_node(request, zygote.build_namespace_template)

    def test_an_isolated_node(self, tmp_path):
        result = self._isolated(tmp_path, self.CODE)
        assert result["ok"], result["stderr"]
        assert result["output"]["value"] == "2 3395 table_osm_roads"

    def test_an_isolated_node_names_the_missing_layer(self, tmp_path):
        result = self._isolated(tmp_path, "    return curio_layer(input_0, \"table_osm_water\", 3)\n")
        assert not result["ok"]
        assert (
            "[!! input_3:table_osm_water !!]: input_3 has no layer table_osm_water. "
            "Its layers are table_osm_roads, table_osm_buildings."
        ) in result["stderr"]


class TestTheJavaScriptTwin:
    """``curio_layer`` in ``js_wrapper.mjs`` finds the same layers and says
    the same when one is missing."""

    def _run(self, code, value):
        from utk_curio.sandbox.app.worker import run_js_script

        result, _logs, stderr = run_js_script(code, {"input_0": value}, cwd=".", node_type="curio.builtin/js-computation")
        assert result is not None, "\n".join(stderr)
        return json.loads(result)

    def test_it_reads_a_layer_array_an_envelope_and_a_named_frame(self):
        import geopandas as gpd
        from shapely.geometry import Point

        code = "const roads = curio_layer(input_0, \"table_osm_roads\", 0);\nreturn roads.features.map((f) => f.properties.highway);"
        for value in (records(), envelopes()):
            run = self._run(code, value)
            assert run["success"], run.get("error")
            assert run["value"] == ["primary", "service"]
        # A frame that carries its name reaches JavaScript as a
        # FeatureCollection that does too.
        parks = gpd.GeoDataFrame({"v": [7]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        parks.__dict__["metadata"] = {"name": "parks"}
        run = self._run("return curio_layer(input_0, \"parks\", 0).features[0].properties.v;", [parks])
        assert run["success"], run.get("error")
        assert run["value"] == 7

    def test_one_frame_with_no_name_is_the_layer_and_several_still_need_it(self):
        import geopandas as gpd
        from shapely.geometry import Point

        from utk_curio.sandbox.util.input_layers import missing_layer_message

        roads = gpd.GeoDataFrame({"v": [7]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        run = self._run("return curio_layer(input_0, \"table_osm_roads\", 0).features[0].properties.v;", roads)
        assert run["success"], run.get("error")
        assert run["value"] == 7
        other = gpd.GeoDataFrame({"v": [8]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        run = self._run("return curio_layer(input_0, \"table_osm_roads\", 0);", [roads, other])
        assert not run["success"]
        assert run["error"].startswith(missing_layer_message(0, "table_osm_roads", []) + "\n"), run["error"]

    def test_a_missing_layer_says_what_python_says(self):
        from utk_curio.sandbox.util.input_layers import missing_layer_message

        run = self._run("return curio_layer(input_0, \"table_osm_water\", 2);", records())
        assert not run["success"]
        message = missing_layer_message(2, "table_osm_water", ["table_osm_roads", "table_osm_buildings"])
        assert run["error"].startswith(message + "\n"), run["error"]
        run = self._run("return curio_layer(input_0, \"roads\", 1);", {"a": 1})
        assert run["error"].startswith(missing_layer_message(1, "roads", []) + "\n"), run["error"]

    def test_a_dict_of_frames_is_read_by_its_keys(self):
        """As in Python: each frame of a Python node's dict is a layer named
        after its key, a GeoDataFrame's as a FeatureCollection and a
        DataFrame's as its rows, as a JavaScript node gets them."""
        import geopandas as gpd
        import pandas as pd
        from shapely.geometry import Point

        from utk_curio.sandbox.util.input_layers import missing_layer_message

        parks = gpd.GeoDataFrame({"v": [7]}, geometry=[Point(0, 0)], crs="EPSG:4326")
        roads = gpd.GeoDataFrame({"v": [8]}, geometry=[Point(1, 1)], crs="EPSG:4326")
        value = {"tip_parks": parks, "tip_roads": roads}
        run = self._run("return curio_layer(input_0, \"tip_roads\", 0).features[0].properties.v;", value)
        assert run["success"], run.get("error")
        assert run["value"] == 8
        run = self._run("return curio_layer(input_0, \"tip_water\", 1);", value)
        assert not run["success"]
        message = missing_layer_message(1, "tip_water", ["tip_parks", "tip_roads"])
        assert run["error"].startswith(message + "\n"), run["error"]
        tables = {"means": pd.DataFrame({"a": [1, 2]}), "peaks": pd.DataFrame({"a": [3, 4]})}
        run = self._run("return curio_layer(input_0, \"peaks\", 0).map((row) => row.a);", tables)
        assert run["success"], run.get("error")
        assert run["value"] == [3, 4]
