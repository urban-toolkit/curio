"""Regression tests for issue #146(b) — JS nodes must persist a named dataset.

A JS node's value is JSON in the store. With Save on, a table it returns is
stored once more as a frame artifact of its own, which ``output['dataset']``
names so the backend can install its Parquet, as it installs a Python node's
artifact; the JS path historically never saved one. These tests cover the
conversion of a JS node's plain-JSON result into a saveable frame, and the
round-trip through the store.
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


def test_js_records_round_trip_through_the_store_as_a_frame(app):
    kind, frame = _js_value_to_saveable_frame(
        [{"name": "A", "tags": {"k": "v"}}, {"name": "B", "tags": ["x", "y"]}]
    )
    assert kind == "dataframe"
    art_id = parsers.save_to_duckdb(frame, node_id="js-node")
    assert (parsers._shared_data_dir() / "artifacts" / f"{art_id}.parquet").is_file()

    restored = parsers.load_from_duckdb(art_id)
    assert restored["tags"].tolist()[0] == {"k": "v"}
    assert restored["tags"].tolist()[1] == ["x", "y"]
