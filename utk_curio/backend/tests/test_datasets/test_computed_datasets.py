"""Tests for computed dataset indexing, path resolution, and install."""
from __future__ import annotations

import json


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(client, token, name="Computed test project"):
    resp = client.post(
        "/api/projects",
        data=json.dumps({
            "name": name,
            "spec": {"dataflow": {"name": name, "nodes": [], "edges": []}},
            "outputs": [],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _save_project_with_output(client, token, project_id, output_filename, node_id="node-1"):
    """Update a project so it records an output ref in its manifest."""
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "outputs": [{"node_id": node_id, "filename": output_filename}],
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


# ---------------------------------------------------------------------------
# Unit-level: ComputedDatasetIndexer
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Unit-level: _resolve_computed_output_path
# ---------------------------------------------------------------------------

def test_resolve_computed_output_path_present(app):
    """A file present in the shared-data dir should be resolved correctly."""
    import os
    from pathlib import Path

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    output_file = shared / "my_output.csv"
    output_file.write_text("a,b\n1,2\n", encoding="utf-8")

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/my_output.csv",
        "path": "my_output.csv",
    }
    resolved = svc._resolve_computed_output_path(item)
    assert resolved == str(output_file)


def test_resolve_computed_output_path_missing(app):
    """If the output file does not exist, None is returned (no exception)."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/ghost.csv",
        "path": "ghost.csv",
    }
    assert svc._resolve_computed_output_path(item) is None


def test_resolve_item_path_delegates_for_computed(app):
    """_resolve_item_path routes curio://outputs/ URIs through the computed resolver."""
    import os
    from pathlib import Path

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "scores.csv").write_text("id,score\n1,99\n", encoding="utf-8")

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    svc = DatasetCatalogService()
    item = {
        "origin": "computed",
        "uri": "curio://outputs/scores.csv",
        "path": "curio://outputs/scores.csv",
    }
    result = svc._resolve_item_path(item)
    assert result is not None
    assert result.endswith("scores.csv")


# ---------------------------------------------------------------------------
# Integration: catalog lists computed datasets
# ---------------------------------------------------------------------------

def test_save_installs_to_user_store_not_project_data(client, user_and_token):
    """Saving a project must not copy outputs into project/data/."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = _create_project(client, token)
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "persist_me.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    _save_project_with_output(client, token, project_id, "persist_me.csv", node_id="node-save")

    launch = Path(os.environ["CURIO_LAUNCH_CWD"])
    proj_data = launch / ".curio" / "users" / "1" / "projects" / project_id / "data"
    assert not (proj_data / "persist_me.csv").exists()

    user_datasets = launch / ".curio" / "users" / "1" / "datasets"
    installed = list(user_datasets.rglob("persist_me.csv"))
    assert installed, "save should install into the user datasets store"

    spec = client.get(f"/api/projects/{project_id}", headers=_auth(token)).get_json()
    datasets = (spec.get("spec") or {}).get("dataflow", {}).get("datasets") or []
    assert any(d.get("producerNodeId") == "node-save" and d.get("dirName") for d in datasets)


def test_catalog_lists_computed_datasets_for_dataflow(client, user_and_token):
    """Computed datasets from the project manifest appear in the catalog."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = _create_project(client, token)

    # Write output file to shared-data dir (already created by the app fixture)
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "node_output.csv").write_text("city,count\nChicago,10\n", encoding="utf-8")

    # Update project with output ref
    _save_project_with_output(client, token, project_id, "node_output.csv", node_id="node-42")

    # Fetch catalog scoped to this dataflow
    resp = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()

    computed = [item for item in body["items"] if item["origin"] == "computed"]
    assert len(computed) == 1
    item = computed[0]
    assert item["producerNodeId"] == "node-42"
    # Project save auto-installs computed outputs into the user store.
    assert item.get("installed") is True
    assert item.get("dirName")
    assert "node_output.csv" in (item.get("path") or "")
    assert item["format"] == "csv"
    assert body["facets"]["origin"]["computed"] == 1


# ---------------------------------------------------------------------------
# Integration: preview computed dataset
# ---------------------------------------------------------------------------

def test_preview_computed_dataset(client, user_and_token):
    """Preview of a computed CSV reads rows from the shared-data directory."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = _create_project(client, token, name="Preview computed")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "metrics.csv").write_text("zone,pm25\nNorth,12.1\nSouth,9.8\n", encoding="utf-8")

    _save_project_with_output(client, token, project_id, "metrics.csv")

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    computed_id = next(i["id"] for i in catalog["items"] if i["origin"] == "computed")

    resp = client.get(
        f"/api/datasets/{computed_id}/preview?dataflowId={project_id}",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0]["zone"] == "North"
    assert body["totalRows"] == 2


# ---------------------------------------------------------------------------
# Unit-level: catalog dedupe keeps auto-installed copy
# ---------------------------------------------------------------------------

def test_dedupe_prefers_installed_copy_over_live_output(tmp_path):
    """When the same computed id appears as an installed folder and a live
    output row, dedupe must keep the installed record (dirName + user path)."""
    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    user_file = tmp_path / "store.parquet"
    user_file.write_bytes(b"PAR1")
    svc = DatasetCatalogService()
    installed = {
        "id": "computed.node-abc",
        "origin": "computed",
        "dirName": "computed.node-abc@1",
        "path": user_file.as_posix(),
        "installed": True,
        "producerNodeId": "node-abc",
    }
    live = {
        "id": "computed.node-abc",
        "origin": "computed",
        "uri": "curio://outputs/live.parquet",
        "path": "live.parquet",
        "producerNodeId": "node-abc",
    }
    merged = svc._dedupe_items([installed, live])
    assert len(merged) == 1
    assert merged[0]["dirName"] == "computed.node-abc@1"
    assert merged[0]["path"] == user_file.as_posix()


# ---------------------------------------------------------------------------
# Integration: install computed dataset → persisted in user store
# ---------------------------------------------------------------------------

def test_install_computed_dataset_copies_to_user_store(client, user_and_token):
    """Installing a computed dataset copies the output file into the user store
    and returns an item with origin='imported'."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = _create_project(client, token, name="Install computed")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "analysis.csv").write_text("id,value\n1,42\n2,7\n", encoding="utf-8")

    _save_project_with_output(client, token, project_id, "analysis.csv", node_id="node-compute")

    # Find the computed item in the catalog
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    computed = next(i for i in catalog["items"] if i["origin"] == "computed")

    # Install it
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": computed["id"]}),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    # Should be installed in the user store and keep computed provenance.
    assert body["installed"] is True
    assert body["origin"] == "computed"
    assert body["path"]
    assert "analysis" in body["path"]
    # Producer linkage should be preserved
    assert body.get("producerNodeId") == "node-compute"

    # The file should exist in the user store
    launch_cwd = Path(os.environ["CURIO_LAUNCH_CWD"])
    user_store = launch_cwd / ".curio" / "users"
    copied = list(user_store.rglob("analysis.csv"))
    assert copied, "compute install should copy payload into user dataset store"


def test_install_computed_dataset_404_when_file_missing(client, user_and_token):
    """Installing a computed dataset whose ephemeral output file is gone returns 404
    when it was never auto-installed into the user store."""
    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    project_id = _create_project(client, token, name="Missing computed output")
    node_id = "node-ghost"
    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"
    source_item = {
        "id": dataset_id,
        "origin": "computed",
        "uri": "curio://outputs/ghost_output.csv",
        "producerNodeId": node_id,
        "path": "ghost_output.csv",
        "format": "csv",
        "title": "Ghost Output",
    }

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id, "sourceItem": source_item}),
        headers=_auth(token),
    )
    assert resp.status_code == 404
    body = resp.get_json()
    assert "available" in body.get("error", "").lower() or "available" in body.get("message", "").lower()


def test_process_python_code_auto_installs_outputs_bundle(client, user_and_token, monkeypatch):
    """Tuple (outputs) installs as a multi-part bundle dataset."""
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
    from utk_curio.sandbox.util.db import release_connection
    from utk_curio.sandbox.util.parsers import init_db, save_to_duckdb

    _, token = user_and_token
    project_id = _create_project(client, token, name="Bundle auto install")
    node_id = "node-utci"

    release_connection()
    init_db()
    parent_id = save_to_duckdb(([1, 2, 3], [10, 20]), node_id=node_id)
    release_connection()

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "",
        "stderr": "",
        "output": {"path": parent_id, "dataType": "outputs"},
    }
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: mock_response,
    )

    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return ([1,2,3], [10,20])\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": node_id,
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    inst = body.get("installedDataset")
    assert inst is not None, body
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
    assert inst["id"] == expected_id
    assert inst["format"] == "bundle"

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    item = next(i for i in catalog["items"] if i["id"] == expected_id)
    assert item.get("installed") is True
    assert item["format"] == "bundle"

    preview = client.get(
        f"/api/datasets/{expected_id}/preview?dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    assert preview.get("bundle") is True
    assert len(preview.get("parts") or []) >= 2


def test_process_python_code_auto_installs_dataset(client, user_and_token, monkeypatch):
    """Tabular node output with output.dataset is installed immediately."""
    import os
    from pathlib import Path
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    parquet_name = "1718000000000_abcd1234_output.parquet"
    (shared / parquet_name).write_bytes(b"PAR1")

    project_id = _create_project(client, token, name="Auto install on exec")
    node_id = "node-abc"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "",
        "stderr": "",
        "output": {"path": "art-1", "dataType": "dataframe", "dataset": parquet_name},
    }
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: mock_response,
    )

    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return df\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": node_id,
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    inst = body.get("installedDataset")
    assert inst is not None, body
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
    assert inst["id"] == expected_id
    assert inst["dirName"] == f"{expected_id}@1"


def test_process_python_code_skips_auto_install_when_save_disabled(client, user_and_token, monkeypatch):
    from unittest.mock import MagicMock

    _, token = user_and_token
    project_id = _create_project(client, token, name="Save off")
    node_id = "node-save-off"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "",
        "stderr": "",
        "output": {"path": "art-1", "dataType": "dataframe"},
    }
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: mock_response,
    )

    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return df\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": node_id,
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": False,
        }),
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get("installedDataset") is None


def test_installed_computed_dataset_appears_in_dataflow_catalog(client, user_and_token):
    """After installing a computed dataset it shows up as installed in the
    dataflow-scoped catalog (origin=imported, installed=True)."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = _create_project(client, token, name="Post-install catalog check")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "results.csv").write_text("col\nA\nB\n", encoding="utf-8")
    _save_project_with_output(client, token, project_id, "results.csv")

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    computed_id = next(i["id"] for i in catalog["items"] if i["origin"] == "computed")

    install = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": computed_id}),
        headers=_auth(token),
    )
    assert install.status_code == 200

    # Reload the catalog — the installed copy should be listed as installed
    catalog_after = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=_auth(token),
    ).get_json()
    installed = [
        i for i in catalog_after["items"]
        if i.get("installed") is True and i.get("origin") == "computed"
    ]
    assert any("results" in (i.get("path") or "") or "results" in (i.get("title") or "").lower() for i in installed), (
        f"Installed results.csv not found in catalog. Items: {[i.get('title') for i in catalog_after['items']]}"
    )






