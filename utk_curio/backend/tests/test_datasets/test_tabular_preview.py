from __future__ import annotations

from pathlib import Path

import pandas as pd

from utk_curio.backend.app.datasets.service import DatasetPreviewService
from utk_curio.sandbox.util.parsers import parseOutput
from utk_curio.sandbox.util.tabular_preview import preview_parquet_file, rows_from_parse_output


def test_rows_from_parse_output_dataframe():
    parsed = parseOutput(pd.DataFrame({"zone": ["North", "South"], "pm25": [12.1, 9.8]}))
    rows = rows_from_parse_output(parsed)
    assert rows == [{"zone": "North", "pm25": 12.1}, {"zone": "South", "pm25": 9.8}]


def test_preview_parquet_file_paginates(tmp_path: Path):
    path = tmp_path / "metrics.parquet"
    pd.DataFrame(
        {"id": [1, 2, 3], "label": ["a", "b", "c"]},
    ).to_parquet(path, index=False)

    rows, total, _ = preview_parquet_file(path, row_limit=2, offset=1)
    assert total == 3
    assert rows == [{"id": 2, "label": "b"}, {"id": 3, "label": "c"}]


def test_preview_parquet_file_geometry_renders_as_wkt(tmp_path: Path):
    """GeoParquet geometry must render as readable WKT, not raw WKB bytes (#138)."""
    import geopandas as gpd
    from shapely.geometry import Point, Polygon

    path = tmp_path / "geo.parquet"
    gpd.GeoDataFrame(
        {
            "name": ["A", "B", "C"],
            "geometry": [
                Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]),
                Point(2, 3),
                None,
            ],
        },
        crs="EPSG:4326",
    ).to_parquet(path)

    rows, total, _ = preview_parquet_file(path, row_limit=10, offset=0)

    assert total == 3
    assert rows[0] == {"name": "A", "geometry": "POLYGON ((0 0, 1 0, 1 1, 0 0))"}
    assert rows[1] == {"name": "B", "geometry": "POINT (2 3)"}
    assert rows[2]["name"] == "C"
    # No cell should contain raw WKB bytes / replacement characters.
    for row in rows:
        geom = row.get("geometry")
        assert geom is None or "\ufffd" not in str(geom)


def test_dataset_preview_service_parquet(tmp_path: Path):
    path = tmp_path / "output.parquet"
    pd.DataFrame({"gid": ["x1"], "name": ["Loop"]}).to_parquet(path, index=False)

    service = DatasetPreviewService()
    payload = service.preview(
        {
            "format": "parquet",
            "path": path.as_posix(),
            "schema": {"fields": []},
        },
        row_limit=10,
        offset=0,
    )

    assert payload.get("unsupported") is not True
    assert payload["rows"][0]["gid"] == "x1"
    assert payload["totalRows"] == 1


def test_rows_from_parse_output_renders_secondary_geometry_as_wkt():
    """A secondary geometry column previews as WKT, matching the parquet path (C6).

    ``gdf['centroid'] = gdf.centroid`` used to crash ``parseOutput`` outright.
    Now that it serializes, the cell arrives as a GeoJSON dict and would render
    as ``{'type': 'Point', 'coordinates': [...]}`` in a table -- which is not a
    good resting state either. The parquet preview already renders geometry as
    WKT, so both paths must agree or the catalog browser and the Data Pool table
    show the same dataset differently.
    """
    import geopandas as gpd
    from shapely.geometry import Polygon

    gdf = gpd.GeoDataFrame(
        {"name": ["A"]},
        geometry=[Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])],
        crs="EPSG:4326",
    )
    gdf["centroid"] = gdf.geometry.representative_point()

    rows = rows_from_parse_output(parseOutput(gdf))

    assert rows[0]["name"] == "A"
    assert rows[0]["centroid"].startswith("POINT (")


def test_parse_output_and_parquet_previews_agree_on_geometry(tmp_path: Path):
    """The two preview paths render the same geometry the same way."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])
    gdf = gpd.GeoDataFrame({"name": ["A"]}, geometry=[polygon], crs="EPSG:4326")

    path = tmp_path / "agree.parquet"
    gdf.to_parquet(path)
    parquet_rows, _, _ = preview_parquet_file(path, row_limit=10, offset=0)

    # Same geometry, but reached through the parseOutput path as a secondary
    # column, where it arrives as a GeoJSON dict rather than a geometry dtype.
    as_secondary = gpd.GeoDataFrame(
        {"name": ["A"]}, geometry=[polygon], crs="EPSG:4326"
    )
    as_secondary["other"] = [polygon]
    parsed_rows = rows_from_parse_output(parseOutput(as_secondary))

    assert parsed_rows[0]["other"] == parquet_rows[0]["geometry"]
