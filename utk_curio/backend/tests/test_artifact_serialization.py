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


# ── geometry columns beyond the active one ─────────────────────────────────

def test_geodataframe_round_trips_two_geometry_columns():
    """Both geometry columns survive DuckDB, still typed as geometry.

    `gdf['centroid'] = gdf.centroid` produces a frame with two geometry columns.
    `parseOutput` used to raise `TypeError: Object of type Point is not JSON
    serializable` on it, so this round trip could never be observed.
    """
    gdf = gpd.GeoDataFrame(
        {"name": ["A", "B"]},
        geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)],
        crs="EPSG:4326",
    )
    gdf["centroid"] = gdf.geometry.representative_point()

    restored = load_from_duckdb(save_to_duckdb(gdf, node_id="TEST_TWO_GEOM"))

    assert isinstance(restored, gpd.GeoDataFrame)
    assert str(restored["geometry"].dtype) == "geometry"
    assert str(restored["centroid"].dtype) == "geometry"
    assert restored.crs == gdf.crs

    parsed = parsers.parseOutput(restored)["data"]
    assert parsed["geometry_name"] == "geometry"
    assert parsed["features"][0]["geometry"]["type"] == "Point"
    assert parsed["features"][0]["properties"]["centroid"]["type"] == "Point"


def test_geodataframe_with_no_active_geometry_round_trips():
    """A GeoDataFrame with no active geometry must not take the save path down.

    `.geometry.name` raised `AttributeError` here at save time, before
    `parseOutput` was ever reached. It now stores as ordinary tabular data --
    it has to, since GeoParquet cannot represent a frame with no primary
    geometry column and the file would not be readable back.
    """
    gdf = gpd.GeoDataFrame(pd.DataFrame({"name": ["A"], "pop": [2746]}))

    restored = load_from_duckdb(save_to_duckdb(gdf, node_id="TEST_NO_GEOM"))

    assert restored["name"].tolist() == ["A"]
    assert restored["pop"].tolist() == [2746]
    assert parsers.parseOutput(restored)["dataType"] == "dataframe"


def test_dataset_geoparquet_keeps_every_geometry_column(tmp_path, monkeypatch):
    """C4: a two-geometry-column dataset reloads as a GeoDataFrame, CRS intact."""
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    gdf = gpd.GeoDataFrame(
        {"name": ["A"]}, geometry=[Point(-87.62, 41.88)], crs="EPSG:4326"
    )
    gdf["centroid"] = gdf.geometry.representative_point()

    filename = parsers.save_dataset_parquet(gdf, "geodataframe")
    assert filename is not None

    restored = parsers.load_dataset_parquet(tmp_path / filename)

    assert isinstance(restored, gpd.GeoDataFrame)
    assert str(restored["geometry"].dtype) == "geometry"
    assert str(restored["centroid"].dtype) == "geometry"
    assert restored.crs == gdf.crs


def test_dataset_parquet_saves_a_geometryless_geodataframe(tmp_path, monkeypatch):
    """C5: the silent one.

    `save_dataset_parquet` raised on `output.geometry.name`, and its
    `except Exception` swallowed it and returned `None` -- so the dataset simply
    never appeared in the catalog and the only trace was one line on stderr.
    The assertion is on the *return value* for exactly that reason.
    """
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    gdf = gpd.GeoDataFrame(pd.DataFrame({"name": ["A"], "pop": [2746]}))

    filename = parsers.save_dataset_parquet(gdf, "geodataframe")

    assert filename is not None, "the dataset was dropped without an error"
    assert (tmp_path / filename).is_file()


def test_load_dataset_parquet_does_not_degrade_geoparquet(tmp_path, monkeypatch):
    """`load_dataset_parquet` caught the AttributeError from `.geometry.name`
    and fell back to `pd.read_parquet`, quietly turning a GeoDataFrame into a
    plain DataFrame. Pin that it stays geospatial."""
    monkeypatch.setattr(parsers, "_shared_data_dir", lambda: tmp_path)

    gdf = gpd.GeoDataFrame(
        {"name": ["A"]}, geometry=[Point(-87.62, 41.88)], crs="EPSG:4326"
    )
    filename = parsers.save_dataset_parquet(gdf, "geodataframe")

    restored = parsers.load_dataset_parquet(tmp_path / filename)

    assert isinstance(restored, gpd.GeoDataFrame)
    assert restored.crs == gdf.crs


def test_plain_dataframe_holding_geometry_columns_round_trips():
    """A plain DataFrame can still carry geometry-dtype columns.

    `pd.DataFrame(gdf)` keeps them, and assigning a GeoSeries onto an ordinary
    frame creates one. That frame takes the plain-parquet path, where duckdb has
    no geometry type and raised `Not implemented Error: Data type 'geometry' not
    recognized` at save time.
    """
    gdf = gpd.GeoDataFrame(
        {"name": ["A", "B"]},
        geometry=[Point(-87.62, 41.88), Point(-87.63, 41.89)],
        crs="EPSG:4326",
    )
    flat = pd.DataFrame(gdf.drop(columns="geometry"))
    flat["centroid"] = gdf.geometry.representative_point()
    assert str(flat["centroid"].dtype) == "geometry"
    assert not isinstance(flat, gpd.GeoDataFrame)

    restored = load_from_duckdb(save_to_duckdb(flat, node_id="TEST_FLAT_GEOM"))

    assert restored["name"].tolist() == ["A", "B"]
    # Decoded back as GeoJSON, which is what parseOutput would have emitted.
    assert restored["centroid"].tolist()[0]["type"] == "Point"
    assert parsers.parseOutput(restored)["dataType"] == "dataframe"
