"""The catalog helpers a node's code calls: ``curio_load_data``,
``curio_data_path``, ``curio_load_collection`` and ``curio_load_model``.

``curio_load_data`` reads a dataset the way its format is read, the reading the
Data Catalog's loader snippets used to spell out in each node. The names these
replaced are not aliases: each raises an error naming its replacement.
"""

from __future__ import annotations

import json
import zlib

import pandas as pd
import pytest

from utk_curio.backend.tests._support.model_files import (
    ADDEND,
    NETCDF_SIGNATURES,
    netcdf_file,
    tiny_onnx_model,
)
from utk_curio.sandbox.util.catalog_helpers import CurioModel, install_catalog_helpers


def _helpers(paths, formats=None, *, collections=None, models=None, media_dir=None):
    namespace: dict = {}

    def data_path(dataset_id):
        path = paths.get(dataset_id)
        if path is None:
            raise RuntimeError(f"Dataset '{dataset_id}' is not available in this environment")
        return str(path)

    install_catalog_helpers(
        namespace, data_path=data_path, formats=formats, collections=collections,
        media_dir=media_dir, models=models,
    )
    return namespace


BUNDLE_FILES = "frame.csv, count.json, depth.tif"


def _bundle_dataset(root):
    """A dataset of several files, as a shipped one is laid out: its files side
    by side in ``data/`` and ``data/bundle.json`` listing them. The GeoTIFF is
    4 by 4 cells of 1 degree from (0, 0), valued 0 to 15."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    data = root / "data"
    data.mkdir(parents=True)
    pd.DataFrame({"x": [1, 2]}).to_csv(data / "frame.csv", index=False)
    (data / "count.json").write_text(json.dumps({"value": 7}), encoding="utf-8")
    with rasterio.open(
        data / "depth.tif", "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
        crs="EPSG:4326", transform=from_origin(0, 4, 1, 1),
    ) as raster:
        raster.write(np.arange(16, dtype="float32").reshape(1, 4, 4))
    (root / "manifest.json").write_text("{}", encoding="utf-8")
    (data / "bundle.json").write_text(json.dumps({"parts": [
        {"index": 0, "label": "Frame", "kind": "dataframe", "format": "csv", "file": "data/frame.csv"},
        {"index": 1, "label": "Count", "kind": "int", "format": "json", "file": "data/count.json"},
        {"index": 2, "label": "Depth", "kind": "raster", "format": "geotiff", "file": "data/depth.tif"},
    ]}), encoding="utf-8")
    return data / "bundle.json"


class TestLoadData:
    def test_a_csv_is_a_table(self, tmp_path):
        path = tmp_path / "t.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        frame = _helpers({"d": path}, {"d": {"format": "csv"}})["curio_load_data"]("d")
        assert list(frame.columns) == ["a", "b"] and int(frame["a"].iloc[0]) == 1

    def test_a_geojson_is_a_geodataframe_with_its_autark_layer(self, tmp_path):
        import geopandas as gpd

        path = tmp_path / "b.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
            "type": "Feature", "properties": {"height": 10},
            "geometry": {"type": "Point", "coordinates": [0, 0]},
        }]}), encoding="utf-8")
        frame = _helpers({"d": path}, {"d": {"format": "geojson", "layerType": "buildings"}})["curio_load_data"]("d")
        assert isinstance(frame, gpd.GeoDataFrame)
        assert frame.metadata == {"layerType": "buildings"}

    def test_a_parquet_restores_its_json_encoded_columns(self, tmp_path):
        path = tmp_path / "t.parquet"
        pd.DataFrame({"id": [1], "tags": ['{"k": "v"}']}).to_parquet(path)
        (tmp_path / "t.parquet.decode.json").write_text(
            json.dumps({"encoded_object_columns": ["tags"]}), encoding="utf-8"
        )
        frame = _helpers({"d": path}, {"d": {"format": "parquet"}})["curio_load_data"]("d")
        assert frame["tags"].iloc[0] == {"k": "v"}

    def test_a_parquet_restores_the_metadata_it_was_saved_with(self, tmp_path):
        """A saved frame's name and Autark layer type sit in the same sidecar,
        and come back on the frame, as a saved scenario context needs (#662)."""
        import geopandas as gpd
        from shapely.geometry import Point

        path = tmp_path / "roads.parquet"
        gpd.GeoDataFrame({"n": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326").to_parquet(path)
        (tmp_path / "roads.parquet.decode.json").write_text(
            json.dumps({"frame_metadata": {"name": "table_osm_roads", "layerType": "roads"}}), encoding="utf-8"
        )
        load = _helpers({"d": path}, {"d": {"format": "parquet"}})["curio_load_data"]
        assert load("d").metadata == {"name": "table_osm_roads", "layerType": "roads"}

    def test_a_geoparquet_is_a_geodataframe_and_a_plain_one_a_table(self, tmp_path):
        """A computed geo dataset reloads with the type the producing node
        emitted; a table without geometry stays a DataFrame."""
        import geopandas as gpd
        from shapely.geometry import Point

        geo, plain = tmp_path / "g.parquet", tmp_path / "p.parquet"
        gpd.GeoDataFrame({"n": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326").to_parquet(geo)
        pd.DataFrame({"n": [2]}).to_parquet(plain)
        load = _helpers(
            {"g": geo, "p": plain}, {"g": {"format": "parquet"}, "p": {"format": "parquet"}},
        )["curio_load_data"]
        frame = load("g")
        assert isinstance(frame, gpd.GeoDataFrame) and frame.crs.to_epsg() == 4326
        assert not isinstance(load("p"), gpd.GeoDataFrame)

    def test_a_geoparquet_download_is_a_geodataframe_with_its_autark_layer(self, tmp_path):
        """An Overture Maps download is GeoParquet: it loads as its layer, as an
        OpenStreetMap GeoJSON download does."""
        import geopandas as gpd
        from shapely.geometry import Point

        path = tmp_path / "overture_buildings.parquet"
        gpd.GeoDataFrame({"height": [10.0]}, geometry=[Point(0, 0)], crs="EPSG:4326").to_parquet(path)
        frame = _helpers({"d": path}, {"d": {"format": "parquet", "layerType": "buildings"}})["curio_load_data"]("d")
        assert isinstance(frame, gpd.GeoDataFrame)
        assert frame.metadata == {"layerType": "buildings"}

    def test_json_is_read_compressed_or_plain(self, tmp_path):
        packed, plain = tmp_path / "a.json.zlib", tmp_path / "b.json"
        packed.write_bytes(zlib.compress(b'{"n": 1}'))
        plain.write_text('{"n": 2}', encoding="utf-8")
        load = _helpers({"a": packed, "b": plain}, {"a": {"format": "json"}, "b": {"format": "json"}})["curio_load_data"]
        assert load("a") == {"n": 1} and load("b") == {"n": 2}

    def test_a_bundle_is_its_parts_in_order(self, tmp_path):
        data = tmp_path / "data"
        (data / "parts").mkdir(parents=True)
        pd.DataFrame({"x": [1]}).to_csv(data / "parts" / "0.csv", index=False)
        (data / "parts" / "1.json").write_text(json.dumps({"value": 7}), encoding="utf-8")
        (data / "bundle.json").write_text(json.dumps({"parts": [
            {"index": 1, "format": "json", "kind": "int", "file": "data/parts/1.json"},
            {"index": 0, "format": "csv", "kind": "dataframe", "file": "data/parts/0.csv"},
        ]}), encoding="utf-8")
        frame, number = _helpers({"d": data / "bundle.json"}, {"d": {"format": "bundle"}})["curio_load_data"]("d")
        assert int(frame["x"].iloc[0]) == 1 and number == 7

    @staticmethod
    def _keyed_bundle(root, container, keys):
        """A bundle of a table and a number whose ``bundle.json`` records
        *container* and gives the parts *keys*, listed out of index order."""
        data = root / "data"
        (data / "parts").mkdir(parents=True)
        pd.DataFrame({"x": [1]}).to_csv(data / "parts" / "0.csv", index=False)
        (data / "parts" / "1.json").write_text(json.dumps({"value": 7}), encoding="utf-8")
        table = {"index": 0, "format": "csv", "kind": "dataframe", "file": "data/parts/0.csv"}
        count = {"index": 1, "format": "json", "kind": "int", "file": "data/parts/1.json"}
        for part, key in zip((table, count), keys):
            if key is not None:
                part["key"] = key
        (data / "bundle.json").write_text(
            json.dumps({"container": container, "parts": [count, table]}), encoding="utf-8",
        )
        return _helpers({"d": data / "bundle.json"}, {"d": {"format": "bundle"}})["curio_load_data"]

    def test_a_bundle_is_the_list_its_bundle_json_records(self, tmp_path):
        loaded = self._keyed_bundle(tmp_path, "list", (None, None))("d")
        assert type(loaded) is list, f"read a {type(loaded).__name__}"
        assert int(loaded[0]["x"].iloc[0]) == 1 and loaded[1] == 7

    def test_a_bundle_is_the_dict_its_bundle_json_records_keyed_in_index_order(self, tmp_path):
        loaded = self._keyed_bundle(tmp_path, "dict", ("table", "count"))("d")
        assert type(loaded) is dict, f"read a {type(loaded).__name__}"
        assert list(loaded) == ["table", "count"]
        assert int(loaded["table"]["x"].iloc[0]) == 1 and loaded["count"] == 7

    @pytest.mark.parametrize(
        "container,keys",
        [("set", ("table", "count")), ("dict", ("table", None)), ("dict", ("table", "table"))],
        ids=["no-such-container", "a-part-without-its-key", "one-key-twice"],
    )
    def test_a_bundle_that_records_no_container_it_can_be_is_refused(self, tmp_path, container, keys):
        load = self._keyed_bundle(tmp_path, container, keys)
        with pytest.raises(ValueError, match="a bundle is a tuple, a list, or a dict"):
            load("d")

    def test_a_part_of_a_bundle_is_the_value_the_whole_read_gives_for_it(self, tmp_path):
        """``part=`` names one file of a bundle by its file name or its label,
        and reads it as the whole bundle's tuple holds it."""
        load = _helpers({"d": _bundle_dataset(tmp_path)}, {"d": {"format": "bundle"}})["curio_load_data"]
        frame, count, raster = load("d")
        assert list(load("d", part="frame.csv")["x"]) == list(frame["x"]) == [1, 2]
        assert list(load("d", part="Frame")["x"]) == [1, 2]
        assert load("d", part="count.json") == load("d", part="Count") == count == 7
        with load("d", part="Depth") as depth:
            assert (depth.width, depth.height) == (raster.width, raster.height) == (4, 4)
        raster.close()

    def test_a_geotiff_part_reads_a_window(self, tmp_path):
        load = _helpers(
            {"d": _bundle_dataset(tmp_path)}, {"d": {"format": "bundle"}}, media_dir=str(tmp_path / "media"),
        )["curio_load_data"]
        with load("d", part="depth.tif", bounds=(0, 0, 2, 2)) as window:
            assert (window.width, window.height) == (2, 2)
            assert window.read(1).tolist() == [[8.0, 9.0], [12.0, 13.0]]

    @pytest.mark.parametrize("part", ["missing.csv", "../manifest.json", "data/frame.csv", "/etc/hosts"])
    def test_a_part_the_bundle_does_not_list_is_refused_with_its_files(self, tmp_path, part):
        load = _helpers({"d": _bundle_dataset(tmp_path)}, {"d": {"format": "bundle"}})["curio_load_data"]
        with pytest.raises(ValueError, match=f"d has no file .*; its files are {BUNDLE_FILES}\\."):
            load("d", part=part)

    def test_a_listed_file_outside_the_dataset_is_not_a_part(self, tmp_path):
        """A ``bundle.json`` entry that leaves the dataset's folder, or is a
        link, is not read: the same rule staging stages parts by."""
        bundle = _bundle_dataset(tmp_path / "ds")
        (tmp_path / "outside.csv").write_text("secret\n1\n", encoding="utf-8")
        (bundle.parent / "link.csv").symlink_to(tmp_path / "outside.csv")
        spec = json.loads(bundle.read_text(encoding="utf-8"))
        spec["parts"] += [
            {"index": 3, "label": "Out", "format": "csv", "file": "../outside.csv"},
            {"index": 4, "label": "Link", "format": "csv", "file": "data/link.csv"},
        ]
        bundle.write_text(json.dumps(spec), encoding="utf-8")
        load = _helpers({"d": bundle}, {"d": {"format": "bundle"}})["curio_load_data"]
        for part in ("outside.csv", "Out", "link.csv", "Link"):
            with pytest.raises(ValueError, match=f"its files are {BUNDLE_FILES}\\."):
                load("d", part=part)

    def test_part_is_refused_where_there_is_one_file_or_a_collection(self, tmp_path):
        path = tmp_path / "t.csv"
        path.write_text("a\n1\n", encoding="utf-8")
        load = _helpers(
            {"d": path, "c": tmp_path / "index.parquet"}, {"d": {"format": "csv"}, "c": {"format": "collection"}},
            collections={"c": {"root": str(tmp_path)}},
        )["curio_load_data"]
        with pytest.raises(ValueError, match=r'd is one csv: load it without part, curio_load_data\("d"\)'):
            load("d", part="t.csv")
        with pytest.raises(ValueError, match="c is a collection"):
            load("c", part="a.jpg")

    def test_a_collection_is_its_index(self, tmp_path):
        index = tmp_path / "index.parquet"
        pd.DataFrame({
            "file_id": ["f1"], "relpath": ["a.jpg"], "ext": ["jpg"], "kind": ["image"], "name": ["a.jpg"],
        }).to_parquet(index)
        frame = _helpers(
            {"c": index}, {"c": {"format": "collection"}}, collections={"c": {"root": "/srv/media"}},
        )["curio_load_data"]("c")
        assert frame["path"].iloc[0] == "/srv/media/a.jpg"

    def test_a_collection_is_its_index_even_without_a_declared_format(self, tmp_path):
        """Solve's validation sends no formats; the collections map says it."""
        index = tmp_path / "index.parquet"
        pd.DataFrame({
            "file_id": ["f1"], "relpath": ["a.jpg"], "ext": ["jpg"], "kind": ["image"], "name": ["a.jpg"],
        }).to_parquet(index)
        frame = _helpers({"c": index}, collections={"c": {"root": "/srv/media"}})["curio_load_data"]("c")
        assert frame["path"].iloc[0] == "/srv/media/a.jpg"

    def test_without_a_declared_format_the_extension_decides(self, tmp_path):
        path = tmp_path / "t.csv"
        path.write_text("a\n3\n", encoding="utf-8")
        assert int(_helpers({"d": path})["curio_load_data"]("d")["a"].iloc[0]) == 3

    def test_an_onnx_model_is_a_session_that_runs(self, tmp_path):
        import numpy as np
        import onnxruntime as ort

        path = tmp_path / "tiny.onnx"
        path.write_bytes(tiny_onnx_model())
        session = _helpers({"m": path}, {"m": {"format": "onnx"}})["curio_load_data"]("m")
        assert isinstance(session, ort.InferenceSession)
        (answer,) = session.run(None, {session.get_inputs()[0].name: np.full((1, 3), 10, dtype=np.float32)})
        assert answer.tolist() == [[10 + value for value in ADDEND]]

    @pytest.mark.parametrize("fmt", list(NETCDF_SIGNATURES))
    def test_a_netcdf_file_is_an_xarray_dataset(self, tmp_path, fmt):
        import xarray as xr

        path = netcdf_file(tmp_path / "RAIN.nc", "RAIN", fmt=fmt, offset=5)
        ds = _helpers({"w": path}, {"w": {"format": "netcdf"}})["curio_load_data"]("w")
        assert isinstance(ds, xr.Dataset)
        assert {"RAIN", "XLAT", "XLONG"} <= set(ds.data_vars)
        assert dict(ds["RAIN"].sizes) == {"Time": 2, "south_north": 3, "west_east": 4}
        assert float(ds["RAIN"][1, 2, 3]) == 5 + 23

    def test_without_a_declared_format_a_model_and_a_netcdf_file_are_read_by_extension(self, tmp_path):
        import onnxruntime as ort
        import xarray as xr

        model = tmp_path / "tiny.onnx"
        model.write_bytes(tiny_onnx_model())
        weather = netcdf_file(tmp_path / "T2.nc", "T2")
        load = _helpers({"m": model, "w": weather})["curio_load_data"]
        assert isinstance(load("m"), ort.InferenceSession)
        assert isinstance(load("w"), xr.Dataset)

    def test_an_unreadable_format_points_at_curio_data_path(self, tmp_path):
        path = tmp_path / "t.bin"
        path.write_bytes(b"\0")
        with pytest.raises(RuntimeError, match="curio_data_path"):
            _helpers({"d": path}, {"d": {"format": "osm"}})["curio_load_data"]("d")

    def test_a_missing_dataset_says_so(self):
        with pytest.raises(RuntimeError, match="not available"):
            _helpers({})["curio_load_data"]("gone")


def test_curio_data_path_is_the_file(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a\n", encoding="utf-8")
    assert _helpers({"d": path})["curio_data_path"]("d") == str(path)


def test_curio_data_path_gives_a_netcdf_file_to_code_that_reads_it_its_own_way(tmp_path):
    """SCOUT's weather routing opens each WRF file with netCDF4 and reads one
    hour of one variable, with ``XLAT`` and ``XLONG`` beside it."""
    import netCDF4

    path = netcdf_file(tmp_path / "WSPD10.nc", "WSPD10", offset=1)
    with netCDF4.Dataset(_helpers({"w": path}, {"w": {"format": "netcdf"}})["curio_data_path"]("w")) as ds:
        hour = ds.variables["WSPD10"][1, :, :]
        assert hour.shape == (3, 4) and float(hour[0, 0]) == 1 + 12
        assert ds.variables["XLAT"].shape == ds.variables["XLONG"].shape == (2, 3, 4)


@pytest.mark.parametrize("old, replacement", [
    ("curio_dataset_path", 'curio_load_data("<id>")'),
    ("curio_collection", 'curio_load_collection("<id>")'),
    ("curio_model", 'curio_load_model("<id>")'),
])
def test_an_old_name_raises_and_names_its_replacement(old, replacement):
    with pytest.raises(RuntimeError) as raised:
        _helpers({})[old]("anything")
    assert "was renamed" in str(raised.value) and replacement in str(raised.value)


class TestLoadModel:
    def _model(self, tmp_path, manifest):
        folder = tmp_path / "model.example.tiny@1"
        folder.mkdir()
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return folder

    def test_a_model_is_loaded_from_its_folder(self, tmp_path):
        folder = self._model(tmp_path, {"runtime": "onnx", "labels": ["road", "sky"]})
        model = _helpers({}, models={"m": str(folder)})["curio_load_model"]("m")
        assert isinstance(model, CurioModel)
        assert model.folder == str(folder) and model.labels == ["road", "sky"]

    def test_a_folder_without_a_manifest_is_refused_when_loaded(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        with pytest.raises(RuntimeError, match="no readable manifest"):
            _helpers({}, models={"m": str(folder)})["curio_load_model"]("m")

    def test_a_missing_model_says_so(self):
        with pytest.raises(RuntimeError, match="not available"):
            _helpers({})["curio_load_model"]("gone")

    def test_an_image_to_image_model_is_run_with_its_own_inputs(self, tmp_path):
        """``model.run`` feeds the graph the arrays the node made, by input
        name, and hands back its outputs in order (onnxruntime is imported,
        not skipped, as ``test_vision.py`` imports it)."""
        import numpy as np

        folder = self._model(tmp_path, {
            "runtime": "onnx", "task": "image-to-image", "labels": [], "entry": "files/m.onnx",
        })
        (folder / "files").mkdir()
        (folder / "files" / "m.onnx").write_bytes(tiny_onnx_model())
        model = _helpers({}, models={"m": str(folder)})["curio_load_model"]("m")
        (out,) = model.run({"X": np.zeros((1, 3), dtype=np.float32)})
        assert out.tolist() == [list(ADDEND)]
        (again,) = model.run({"X": np.ones((1, 3), dtype=np.float32)})
        assert again.tolist() == [[value + 1 for value in ADDEND]]
        with pytest.raises(ValueError, match="needs the inputs X; missing X"):
            model.run({"Y": np.zeros((1, 3), dtype=np.float32)})

    def test_only_an_onnx_model_has_a_graph_to_run(self, tmp_path):
        folder = self._model(tmp_path, {"runtime": "transformers", "entry": "files"})
        model = _helpers({}, models={"m": str(folder)})["curio_load_model"]("m")
        with pytest.raises(RuntimeError, match="not an ONNX model"):
            model.run({})

    def test_curio_segment_refuses_an_image_to_image_model(self, tmp_path):
        folder = self._model(tmp_path, {"runtime": "onnx", "task": "image-to-image", "labels": []})
        helpers = _helpers({}, models={"m": str(folder)})
        with pytest.raises(ValueError, match="does not label pixels"):
            helpers["curio_segment"](pd.DataFrame({"path": []}), helpers["curio_load_model"]("m"))

    def test_curio_segment_runs_a_loaded_model_not_a_folder(self, tmp_path):
        segment = _helpers({})["curio_segment"]
        with pytest.raises(TypeError, match="curio_load_model"):
            segment(pd.DataFrame({"path": []}), str(tmp_path))


def test_an_in_process_node_loads_by_format(tmp_path):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    result = execute_code(
        '    return curio_load_data("imported.xabc")\n', "", "PYTHON_COMPUTATION", "",
        save_dataset=False, dataset_paths={"imported.xabc": str(path)},
        dataset_formats={"imported.xabc": {"format": "csv"}},
    )
    assert result["stderr"] == ""
    assert result["output"]["dataType"] == "dataframe"


@pytest.mark.parametrize("fmt, code", [
    ("onnx", 'session = curio_load_data("imported.xdata")'),
    ("netcdf", 'ds = curio_load_data("imported.xdata")'),
])
def test_a_node_dropped_from_a_model_or_a_netcdf_file_runs(tmp_path, fmt, code):
    """The loader the Data Catalog writes for these formats (the code the
    backend's ``loader_snippet`` gives, pinned in
    ``test_onnx_netcdf_datasets.py``) loads the value and returns nothing: a
    node's output cannot carry a model session or an xarray Dataset. The node
    runs, and its own code uses what it loaded."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    path = tmp_path / ("tiny.onnx" if fmt == "onnx" else "RAIN.nc")
    if fmt == "onnx":
        path.write_bytes(tiny_onnx_model())
    else:
        netcdf_file(path, "RAIN")
    result = execute_code(
        f"    {code}\n", "", "PYTHON_COMPUTATION", "",
        save_dataset=False, dataset_paths={"imported.xdata": str(path)},
        dataset_formats={"imported.xdata": {"format": fmt}},
    )
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "null"


def test_an_isolated_node_reads_a_netcdf_file_and_runs_a_model(tmp_path):
    """Under isolation the child reads both from staged copies, with the
    libraries the shared environment holds."""
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    model = tmp_path / "tiny.onnx"
    model.write_bytes(tiny_onnx_model())
    weather = netcdf_file(tmp_path / "RAIN.nc", "RAIN", offset=2)
    request = {
        "code": (
            '    session = curio_load_data("imported.xmodel")\n'
            '    rain = curio_load_data("imported.xweather")["RAIN"].values[0, 0, :3].reshape(1, 3)\n'
            '    (answer,) = session.run(None, {session.get_inputs()[0].name: rain.astype(np.float32)})\n'
            '    return ",".join(str(float(v)) for v in answer[0])\n'
        ),
        "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"},
        "dataset_paths": staging.stage_dataset_paths(
            {"imported.xmodel": str(model), "imported.xweather": str(weather)}, scratch,
        ),
        "dataset_formats": {
            "imported.xmodel": {"format": "onnx"}, "imported.xweather": {"format": "netcdf"},
        },
        "session_imports": [], "limits": {},
    }

    def namespace():
        import numpy as np

        return {"np": np, "pd": pd}

    result = child.run_node(request, namespace)
    assert result["ok"], result["stderr"]
    # The first hour's first three cells are 2, 3 and 4.
    expected = [2 + ADDEND[0], 3 + ADDEND[1], 4 + ADDEND[2]]
    assert result["output"]["value"] == ",".join(str(v) for v in expected)


def test_an_isolated_node_loads_by_format(tmp_path):
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    path = tmp_path / "t.csv"
    path.write_text("a\n5\n", encoding="utf-8")
    staged = staging.stage_dataset_paths({"imported.xabc": str(path)}, scratch)
    request = {
        "code": '    return int(curio_load_data("imported.xabc")["a"].iloc[0])\n',
        "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"},
        "dataset_paths": staged, "dataset_formats": {"imported.xabc": {"format": "csv"}},
        "session_imports": [], "limits": {},
    }

    def namespace():
        import numpy as np

        return {"np": np, "pd": pd}

    result = child.run_node(request, namespace)
    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == 5


PART_CODE = (
    '    frame = curio_load_data("data.x.bundle", part="frame.csv")\n'
    '    return int(frame["x"].sum()) + curio_load_data("data.x.bundle", part="Count")\n'
)
OUTSIDE_CODE = '    return curio_load_data("data.x.bundle", part="../manifest.json")\n'


def test_an_in_process_node_reads_one_part_of_a_bundle(tmp_path):
    """The part is found through the same dataset-path map as the dataset."""
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    bundle = _bundle_dataset(tmp_path / "data.x.bundle@1")

    def run(code):
        return execute_code(
            code, "", "PYTHON_COMPUTATION", "", save_dataset=False,
            dataset_paths={"data.x.bundle": str(bundle)}, dataset_formats={"data.x.bundle": {"format": "bundle"}},
        )

    result = run(PART_CODE)
    assert result["stderr"] == "", result["stderr"]
    assert result["output"]["dataType"] == "int"
    refused = run(OUTSIDE_CODE)
    assert f"data.x.bundle has no file '../manifest.json'; its files are {BUNDLE_FILES}." in refused["stderr"]


def test_an_isolated_node_reads_one_part_of_a_staged_bundle(tmp_path):
    """Under isolation the bundle and its parts are staged into the scratch
    folder, and the part is read from there."""
    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    bundle = _bundle_dataset(tmp_path / "data.x.bundle@1")
    staged = staging.stage_dataset_paths({"data.x.bundle": str(bundle)}, scratch)

    def run(code):
        return child.run_node({
            "code": code, "node_type": "curio.builtin/computation-analysis", "data_type": "",
            "scratch_dir": str(scratch), "input": {"kind": "none"},
            "dataset_paths": staged, "dataset_formats": {"data.x.bundle": {"format": "bundle"}},
            "session_imports": [], "limits": {},
        }, lambda: {"pd": pd})

    result = run(PART_CODE)
    assert result["ok"], result["stderr"]
    assert result["output"]["value"] == 10
    refused = run(OUTSIDE_CODE)
    assert not refused["ok"]
    assert f"data.x.bundle has no file '../manifest.json'; its files are {BUNDLE_FILES}." in refused["stderr"]


def test_an_isolated_node_reads_a_shipped_dataset_as_in_process(tmp_path):
    """#596: the shipped chicago-labels keeps its list columns JSON-encoded and
    names them in ``chicago-labels.parquet.decode.json``. An isolated node got
    the parquet without that file, so its ``tags`` came back as JSON strings,
    where a node run in process gets lists."""
    from pathlib import Path

    from utk_curio.sandbox.isolation import child
    from utk_curio.sandbox.util import staging
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    dataset_id = "data.projectsidewalk.chicago-labels"
    source = (Path(__file__).resolve().parents[3] / "datasets" / f"{dataset_id}@1"
              / "data" / "chicago-labels.parquet")
    in_process = sorted({type(v).__name__ for v in read_dataset(str(source), "parquet")["tags"]})
    assert "str" not in in_process, in_process

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    request = {
        "code": (
            f'    frame = curio_load_data("{dataset_id}")\n'
            '    return ",".join(sorted({type(v).__name__ for v in frame["tags"]}))\n'
        ),
        "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(scratch), "input": {"kind": "none"},
        "dataset_paths": staging.stage_dataset_paths({dataset_id: str(source)}, scratch),
        "dataset_formats": {dataset_id: {"format": "parquet"}},
        "session_imports": [], "limits": {},
    }

    def namespace():
        import numpy as np

        return {"np": np, "pd": pd}

    result = child.run_node(request, namespace)
    assert result["ok"], result["stderr"]
    assert result["output"]["value"].split(",") == in_process
