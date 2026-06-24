from __future__ import annotations

import json


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def test_dataset_catalog_lists_hub_datasets(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get("/api/datasets/catalog", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.get_json()
    titles = {item["title"] for item in body["items"]}
    assert "Chicago Community Areas" in titles
    assert body["facets"]["origin"]["hub"] >= 1


def test_install_hub_dataset_copies_to_user_store(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    create = client.post(
        "/api/projects",
        data=json.dumps({
            "name": "Hub install test",
            "spec": {"dataflow": {"name": "Hub install test", "nodes": [], "edges": []}},
            "outputs": [],
        }),
        headers=_auth(token),
    )
    assert create.status_code == 201, create.get_data(as_text=True)
    project_id = create.get_json()["id"]

    catalog = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "Chicago Community Areas")

    install = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset["id"]}),
        headers=_auth(token),
    )
    assert install.status_code == 200, install.get_data(as_text=True)
    body = install.get_json()
    assert body["installed"] is True
    assert body["path"]
    assert "datasets/data.urbanlab.chicago-community-areas@1" in body["path"]

    user_store = tmp_path / ".curio" / "users"
    copied = list(user_store.rglob("community-areas.geojson"))
    assert copied, "hub install should copy payload into the user dataset store"


def test_download_hub_dataset_streams_data_file(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    catalog = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "Chicago Community Areas")

    resp = client.get(f"/api/datasets/{dataset['id']}/download", headers=_auth(token))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    disposition = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disposition
    assert ".geojson" in disposition
    assert len(resp.get_data()) > 0


def test_download_name_falls_back_to_format_extension(tmp_path, monkeypatch):
    """A resolved file without an extension still gets the format's extension."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    # The resolved path must sit under an allowed read root (#143): point the
    # shared-data dir at tmp_path so this synthetic artifact passes containment.
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path))
    artifact = tmp_path / "abc123_artifact"  # no suffix, like a computed output id
    artifact.write_text("a,b\n1,2\n")

    service = DatasetCatalogService(user=None)
    service.get_dataset = lambda *a, **k: {  # type: ignore[assignment]
        "id": "ds",
        "title": "My Output",
        "format": "csv",
        "path": str(artifact),
        "uri": str(artifact),
    }

    target = service.download_target("ds")
    assert target["download_name"] == "My Output.csv"
    assert target["mimetype"] == "text/csv"
    assert target["path"] == str(artifact)


def test_download_name_preserves_friendly_title():
    """The export name keeps the readable title, only stripping illegal chars."""
    from utk_curio.backend.app.datasets.services.catalog_listing import _download_name

    assert _download_name("Chicago Community Areas", ".geojson") == (
        "Chicago Community Areas.geojson"
    )
    # Reserved/path characters collapse to spaces; whitespace is normalized.
    assert _download_name("Traffic / Speed: 2026", ".csv") == "Traffic Speed 2026.csv"
    # An empty/whitespace title falls back to a sensible default.
    assert _download_name("   ", ".parquet") == "dataset.parquet"
    # Dots in the title are stripped so the only dot is the extension separator.
    assert _download_name("export.csv", ".csv") == "export csv.csv"
    assert _download_name("computed.n13351a78-885b", ".parquet") == (
        "computed n13351a78-885b.parquet"
    )


def test_download_tabular_parquet_exports_as_csv(tmp_path, monkeypatch):
    """A plain-DataFrame parquet is exported as CSV, not parquet."""
    import io

    import pandas as pd

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path))  # allowed read root (#143)
    artifact = tmp_path / "abc123_artifact"  # no suffix, like a computed output id
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    frame.to_parquet(artifact)

    service = DatasetCatalogService(user=None)
    service.get_dataset = lambda *a, **k: {  # type: ignore[assignment]
        "id": "ds",
        "title": "My Output",
        "format": "parquet",
        "path": str(artifact),
        "uri": str(artifact),
    }

    target = service.download_target("ds")
    assert target["download_name"] == "My Output.csv"
    assert target["mimetype"] == "text/csv"
    assert "path" not in target

    exported = pd.read_csv(io.BytesIO(target["data"]))
    pd.testing.assert_frame_equal(exported, frame)


def test_download_geo_parquet_exports_as_geojson(tmp_path, monkeypatch):
    """A GeoParquet dataset is exported as GeoJSON."""
    import geopandas as gpd
    from shapely.geometry import Point

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path))  # allowed read root (#143)
    artifact = tmp_path / "geo_artifact"  # no suffix
    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )
    gdf.to_parquet(artifact)

    service = DatasetCatalogService(user=None)
    service.get_dataset = lambda *a, **k: {  # type: ignore[assignment]
        "id": "ds",
        "title": "Geo Output",
        "format": "parquet",
        "path": str(artifact),
        "uri": str(artifact),
    }

    target = service.download_target("ds")
    assert target["download_name"] == "Geo Output.geojson"
    assert target["mimetype"] == "application/geo+json"
    assert "path" not in target

    payload = json.loads(target["data"])
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    assert payload["features"][0]["geometry"]["type"] == "Point"


def test_download_geo_parquet_with_timestamp_exports_as_geojson(tmp_path, monkeypatch):
    """GeoParquet carrying datetime columns exports to GeoJSON.

    Regression: ``to_json`` serializes properties via ``json.dumps`` and used
    to raise "Object of type Timestamp is not JSON serializable" for temporal
    columns.
    """
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path))  # allowed read root (#143)
    artifact = tmp_path / "geo_ts_artifact"  # no suffix
    gdf = gpd.GeoDataFrame(
        {
            "name": ["a", "b"],
            "created": pd.to_datetime(["2026-06-17 13:51:00", "2026-06-17 14:00:00"]),
        },
        geometry=[Point(0, 0), Point(1, 1)],
        crs="EPSG:4326",
    )
    gdf.to_parquet(artifact)

    service = DatasetCatalogService(user=None)
    service.get_dataset = lambda *a, **k: {  # type: ignore[assignment]
        "id": "ds",
        "title": "Geo Output",
        "format": "parquet",
        "path": str(artifact),
        "uri": str(artifact),
    }

    target = service.download_target("ds")
    assert target["download_name"] == "Geo Output.geojson"
    assert target["mimetype"] == "application/geo+json"

    payload = json.loads(target["data"])
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 2
    assert payload["features"][0]["properties"]["created"] == "2026-06-17 13:51:00"


def test_download_missing_dataset_returns_404(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    resp = client.get("/api/datasets/does-not-exist/download", headers=_auth(token))

    assert resp.status_code == 404


def test_hub_dataset_preview_reads_catalog_payload(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    catalog = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()
    dataset = next(item for item in catalog["items"] if item["title"] == "ACS Neighborhood Profile")

    resp = client.get(f"/api/datasets/{dataset['id']}/preview?rowLimit=2", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0]["tract_id"] == "17031010100"
    assert body.get("unsupported") is not True


def test_catalog_surfaces_workspace_data_without_dataflow(client, user_and_token, tmp_path, monkeypatch):
    """Workspace data (<launch>/data) must appear in the browse catalog even with
    no open dataflow (review #145a / dead LocalDatasetRepository)."""
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "workspace_blocks.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    resp = client.get("/api/datasets/catalog", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    workspace = [i for i in body["items"] if i.get("sourceLabel") == "Workspace data"]
    assert any("blocks" in (i.get("title") or "").lower() for i in workspace), body["items"]
