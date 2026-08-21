"""Regression tests for issue #146(b) — JS nodes must persist a named dataset.

The Python exec path emits ``output['dataset']`` (a saved parquet filename) so the
backend can auto-install it; the JS path historically never did. These tests cover
the conversion of a JS node's plain-JSON result into a saveable frame, and the
round-trip through ``save_dataset_parquet``.
"""
from __future__ import annotations

import geopandas as gpd
import pytest

from utk_curio.sandbox.app.worker import _js_value_to_saveable_frame
from utk_curio.sandbox.util import parsers


def test_records_list_becomes_dataframe():
    kind, frame = _js_value_to_saveable_frame([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
    assert kind == "dataframe"
    assert list(frame["a"]) == [1, 2]


def test_feature_collection_becomes_geodataframe():
    kind, frame = _js_value_to_saveable_frame({
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"n": "A"},
             "geometry": {"type": "Point", "coordinates": [0, 0]}},
        ],
    })
    assert kind == "geodataframe"
    assert isinstance(frame, gpd.GeoDataFrame)
    assert list(frame["n"]) == ["A"]


@pytest.mark.parametrize("value", [5, 1.5, True, "text", {"a": 1}, [1, 2, 3], [], None])
def test_non_tabular_values_are_not_datasets(value):
    # Scalars, plain dicts, lists of scalars, empties → not a dataset.
    assert _js_value_to_saveable_frame(value) == (None, None)


def test_js_records_round_trip_through_save_dataset_parquet(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    kind, frame = _js_value_to_saveable_frame(
        [{"name": "A", "tags": {"k": "v"}}, {"name": "B", "tags": ["x", "y"]}]
    )
    filename = parsers.save_dataset_parquet(frame, kind)
    assert filename is not None
    assert (tmp_path / filename).is_file()

    restored = parsers.load_dataset_parquet(tmp_path / filename)
    assert restored["tags"].tolist()[0] == {"k": "v"}
    assert restored["tags"].tolist()[1] == ["x", "y"]
