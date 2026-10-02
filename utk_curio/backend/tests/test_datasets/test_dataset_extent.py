"""A dataset's extent, for the Discovery Catalog's "use the extent of a dataset"."""
from __future__ import annotations

import io
import json

import pytest

from utk_curio.backend.app.datasets.application.extent import dataset_extent

GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "properties": {"n": 1}, "geometry": {"type": "Point", "coordinates": [-87.64, 41.875]}},
        {"type": "Feature", "properties": {"n": 2}, "geometry": {"type": "Point", "coordinates": [-87.62, 41.89]}},
    ],
}


def _frame(crs="EPSG:4326"):
    import geopandas as gpd
    from shapely.geometry import Point

    frame = gpd.GeoDataFrame({"n": [1, 2]}, geometry=[Point(-87.64, 41.875), Point(-87.62, 41.89)], crs="EPSG:4326")
    return frame.to_crs(crs)


class TestTheExtent:
    def test_a_geojson_file(self, tmp_path):
        path = tmp_path / "points.geojson"
        path.write_text(json.dumps(GEOJSON))
        assert dataset_extent(path, "geojson") == [-87.64, 41.875, -87.62, 41.89]

    def test_a_geoparquet_is_read_from_its_metadata(self, tmp_path):
        path = tmp_path / "points.parquet"
        _frame().to_parquet(path)
        assert dataset_extent(path, "parquet") == [-87.64, 41.875, -87.62, 41.89]

    def test_a_projected_geoparquet_comes_back_in_wgs84(self, tmp_path):
        path = tmp_path / "mercator.parquet"
        _frame("EPSG:3857").to_parquet(path)
        box = dataset_extent(path, "parquet")
        assert box == pytest.approx([-87.64, 41.875, -87.62, 41.89], abs=1e-5)

    def test_a_geotiff(self, tmp_path):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        path = tmp_path / "tile.tif"
        with rasterio.open(
            path, "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8",
            crs="EPSG:4326", transform=from_bounds(-87.64, 41.875, -87.62, 41.89, 4, 4),
        ) as dst:
            dst.write(np.zeros((1, 4, 4), dtype="uint8"))
        assert dataset_extent(path, "geotiff") == pytest.approx([-87.64, 41.875, -87.62, 41.89], abs=1e-6)

    def test_no_geometry_is_no_extent(self, tmp_path):
        import pandas as pd

        csv = tmp_path / "plain.csv"
        csv.write_text("a,b\n1,2\n")
        plain = tmp_path / "plain.parquet"
        pd.DataFrame({"a": [1]}).to_parquet(plain)
        assert dataset_extent(csv, "csv") is None
        assert dataset_extent(plain, "parquet") is None

    def test_an_empty_layer_is_no_extent(self, tmp_path):
        path = tmp_path / "empty.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        assert dataset_extent(path, "geojson") is None


class TestTheRoute:
    def _import(self, client, token, body: bytes, name: str):
        return client.post(
            "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
            data={"file": (io.BytesIO(body), name)}, content_type="multipart/form-data",
        )

    def test_an_imported_geojson_has_its_box(self, client, user_and_token):
        _user, token = user_and_token
        made = self._import(client, token, json.dumps(GEOJSON).encode(), "points.geojson")
        assert made.status_code == 201, made.get_data(as_text=True)
        dataset_id = made.get_json()["id"]
        body = client.get(f"/api/datasets/{dataset_id}/extent",
                          headers={"Authorization": f"Bearer {token}"}).get_json()
        assert body["box"] == [-87.64, 41.875, -87.62, 41.89]
        assert body["datasetId"] == dataset_id

    def test_a_table_without_geometry_has_a_null_box(self, client, user_and_token):
        _user, token = user_and_token
        made = self._import(client, token, b"a,b\n1,2\n", "plain.csv")
        body = client.get(f"/api/datasets/{made.get_json()['id']}/extent",
                          headers={"Authorization": f"Bearer {token}"}).get_json()
        assert body["box"] is None

    def test_it_needs_a_signed_in_caller(self, client):
        assert client.get("/api/datasets/anything/extent").status_code == 401
