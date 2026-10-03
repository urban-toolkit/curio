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

    def test_a_collection_is_its_index(self, tmp_path):
        index = tmp_path / "index.parquet"
        pd.DataFrame({
            "file_id": ["f1"], "relpath": ["a.jpg"], "ext": ["jpg"], "kind": ["image"], "name": ["a.jpg"],
        }).to_parquet(index)
        frame = _helpers(
            {"c": index}, {"c": {"format": "collection"}}, collections={"c": {"root": "/srv/media"}},
        )["curio_load_data"]("c")
        assert frame["path"].iloc[0] == "/srv/media/a.jpg"

    def test_without_a_declared_format_the_extension_decides(self, tmp_path):
        path = tmp_path / "t.csv"
        path.write_text("a\n3\n", encoding="utf-8")
        assert int(_helpers({"d": path})["curio_load_data"]("d")["a"].iloc[0]) == 3

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
