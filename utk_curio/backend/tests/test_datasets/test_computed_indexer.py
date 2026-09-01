"""Unit tests for ComputedDatasetIndexer."""
from __future__ import annotations

def test_computed_indexer_empty_manifest():
    """Empty / missing manifest produces an empty item list."""
    from utk_curio.backend.app.datasets.service import ComputedDatasetIndexer

    indexer = ComputedDatasetIndexer()
    assert indexer.list_items(manifest=None) == []
    assert indexer.list_items(manifest={}) == []
    assert indexer.list_items(manifest={"outputs": []}) == []


def test_computed_indexer_produces_items():
    """Outputs in the project manifest become catalog items with correct fields."""
    from utk_curio.backend.app.datasets.service import ComputedDatasetIndexer

    manifest = {
        "outputs": [
            {"node_id": "node-abc", "filename": "result.csv"},
            {"node_id": "node-xyz", "filename": "polygons.geojson"},
        ]
    }
    indexer = ComputedDatasetIndexer()
    items = indexer.list_items(manifest=manifest)

    assert len(items) == 2
    csv_item = next(i for i in items if i["format"] == "csv")
    geo_item = next(i for i in items if i["format"] == "geojson")

    # Origin and URI shape
    assert csv_item["origin"] == "computed"
    assert csv_item["uri"] == "curio://outputs/result.csv"
    assert csv_item["producerNodeId"] == "node-abc"

    assert geo_item["origin"] == "computed"
    assert geo_item["uri"] == "curio://outputs/polygons.geojson"
    assert geo_item["producerNodeId"] == "node-xyz"

    # IDs should be stable (deterministic)
    assert csv_item["id"] == ComputedDatasetIndexer().list_items(manifest=manifest)[0]["id"]


def test_computed_indexer_outputs_bundle_datatype():
    """Tuple / multi-output bundles use catalog format ``bundle``."""
    from utk_curio.backend.app.datasets.service import ComputedDatasetIndexer

    indexer = ComputedDatasetIndexer()
    items = indexer.list_items(live_outputs=[
        {"node_id": "utci-node", "filename": "1780604607968_abc", "data_type": "outputs"},
        {"node_id": "zonal-node", "filename": "1780604607999_out.parquet", "data_type": "geodataframe"},
    ])
    assert len(items) == 2
    bundle_item = next(i for i in items if i["producerNodeId"] == "utci-node")
    assert bundle_item["format"] == "bundle"
    assert items[1]["format"] == "parquet"


def test_computed_indexer_uses_data_type_for_extensionless_artifacts():
    """Bare DuckDB artifact IDs should not default to JSON when data_type is known."""
    from utk_curio.backend.app.datasets.service import ComputedDatasetIndexer

    indexer = ComputedDatasetIndexer()
    items = indexer.list_items(live_outputs=[
        {"node_id": "load-raster", "filename": "1780602628735_abc", "data_type": "raster"},
        {"node_id": "load-csv", "filename": "1780602588331_def", "data_type": "dataframe"},
        {"node_id": "compute", "filename": "1780602590219_out.parquet", "data_type": "dataframe"},
    ])

    assert len(items) == 3
    raster = next(i for i in items if i["producerNodeId"] == "load-raster")
    table = next(i for i in items if i["producerNodeId"] == "load-csv")
    parquet = next(i for i in items if i["producerNodeId"] == "compute")

    assert raster["format"] == "geotiff"
    assert table["format"] == "parquet"
    assert parquet["format"] == "parquet"

