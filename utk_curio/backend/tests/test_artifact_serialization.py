import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

from utk_curio.sandbox.util import parsers
from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb


def test_dataframe_round_trips_mixed_object_columns():
    df = pd.DataFrame(
        {
            "ZIP_CODE": ["60601", float("nan"), "60603", 60604.0],
            "BUILDING_NAME1": ["Tower", 101, None, "Plaza"],
            "payload": [{"a": 1}, ["x", "y"], "plain", None],
        }
    )

    artifact_id = save_to_duckdb(df, node_id="TEST_DF")
    restored = load_from_duckdb(artifact_id)

    assert restored["ZIP_CODE"].tolist()[0] == "60601"
    assert pd.isna(restored["ZIP_CODE"].tolist()[1])
    assert restored["ZIP_CODE"].tolist()[3] == 60604.0
    assert restored["BUILDING_NAME1"].tolist()[1] == 101
    assert pd.isna(restored["BUILDING_NAME1"].tolist()[2])
    assert restored["payload"].tolist()[0] == {"a": 1}
    assert restored["payload"].tolist()[1] == ["x", "y"]
    assert restored["payload"].tolist()[2] == "plain"


def test_geodataframe_round_trips_metadata_and_object_columns():
    gdf = gpd.GeoDataFrame(
        {
            "name": ["A", "B"],
            "tags": [{"amenity": "school"}, None],
        },
        geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)],
        crs="EPSG:4326",
    )
    gdf.__dict__["metadata"] = {"name": "schools"}

    artifact_id = save_to_duckdb(gdf, node_id="TEST_GDF")
    restored = load_from_duckdb(artifact_id)

    assert getattr(restored, "metadata", None) == {"name": "schools"}
    assert restored["tags"].tolist()[0] == {"amenity": "school"}
    assert pd.isna(restored["tags"].tolist()[1])
    assert restored.geometry.iloc[0].equals(gdf.geometry.iloc[0])


# ── save_dataset_parquet / load_dataset_parquet round-trip (#146a) ──────────

def test_dataset_parquet_round_trips_object_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    df = pd.DataFrame(
        {
            "name": ["A", "B", "C"],
            "payload": [{"a": 1}, ["x", "y"], None],
        }
    )
    filename = parsers.save_dataset_parquet(df, "dataframe")
    assert filename is not None
    # The decode sidecar is written next to the parquet.
    assert (tmp_path / (filename + ".decode.json")).is_file()

    restored = parsers.load_dataset_parquet(tmp_path / filename)
    assert restored["payload"].tolist()[0] == {"a": 1}
    assert restored["payload"].tolist()[1] == ["x", "y"]


def test_dataset_geoparquet_round_trips_object_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    gdf = gpd.GeoDataFrame(
        {"name": ["A", "B"], "tags": [{"k": "v"}, None]},
        geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)],
        crs="EPSG:4326",
    )
    filename = parsers.save_dataset_parquet(gdf, "geodataframe")
    assert filename is not None

    restored = parsers.load_dataset_parquet(tmp_path / filename)
    assert isinstance(restored, gpd.GeoDataFrame)
    assert restored["tags"].tolist()[0] == {"k": "v"}
    assert restored.geometry.iloc[0].equals(gdf.geometry.iloc[0])
