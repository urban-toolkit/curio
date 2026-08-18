"""Integration tests for computed datasets via HTTP API."""
from __future__ import annotations

import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)

def test_save_installs_to_user_store_not_project_data(client, user_and_token):
    """Saving a project must not copy outputs into project/data/."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = create_project(client, token)
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "persist_me.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    save_project_with_output(client, token, project_id, "persist_me.csv", node_id="node-save")

    launch = Path(os.environ["CURIO_LAUNCH_CWD"])
    proj_data = launch / ".curio" / "users" / "1" / "projects" / project_id / "data"
    assert not (proj_data / "persist_me.csv").exists()

    user_datasets = launch / ".curio" / "users" / "1" / "datasets"
    installed = list(user_datasets.rglob("persist_me.csv"))
    assert installed, "save should persist the output into the account dataset store"

    # Saving is account-level only: it must NOT write a project spec ref
    # (no auto-install into the palette). Installing is an explicit action.
    spec = client.get(f"/api/projects/{project_id}", headers=auth_headers(token)).get_json()
    datasets = (spec.get("spec") or {}).get("dataflow", {}).get("datasets") or []
    assert not any(d.get("producerNodeId") == "node-save" for d in datasets)


def test_catalog_lists_computed_datasets_for_dataflow(client, user_and_token):
    """Computed datasets from the project manifest appear in the catalog."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = create_project(client, token)

    # Write output file to shared-data dir (already created by the app fixture)
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "node_output.csv").write_text("city,count\nChicago,10\n", encoding="utf-8")

    # Update project with output ref
    save_project_with_output(client, token, project_id, "node_output.csv", node_id="node-42")

    # Scoped to this dataflow: its own computed output is surfaced from the
    # account store with full metadata + lineage (no project ref needed).
    resp = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()

    computed = [item for item in body["items"] if item["origin"] == "computed"]
    assert len(computed) == 1
    item = computed[0]
    assert item["producerNodeId"] == "node-42"
    # Saving does NOT auto-install the dataset into the project — it stays an
    # available (not installed) account-level asset until explicitly installed.
    assert item.get("installed") is False
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
    project_id = create_project(client, token, name="Preview computed")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "metrics.csv").write_text("zone,pm25\nNorth,12.1\nSouth,9.8\n", encoding="utf-8")

    save_project_with_output(client, token, project_id, "metrics.csv")

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed_id = next(i["id"] for i in catalog["items"] if i["origin"] == "computed")

    resp = client.get(
        f"/api/datasets/{computed_id}/preview?dataflowId={project_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0]["zone"] == "North"
    assert body["totalRows"] == 2


# ---------------------------------------------------------------------------
# Unit-level: catalog dedupe keeps auto-installed copy
# ---------------------------------------------------------------------------

def test_install_computed_dataset_copies_to_user_store(client, user_and_token):
    """Installing a computed dataset copies the output file into the user store
    and returns an item with origin='imported'."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = create_project(client, token, name="Install computed")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "analysis.csv").write_text("id,value\n1,42\n2,7\n", encoding="utf-8")

    save_project_with_output(client, token, project_id, "analysis.csv", node_id="node-compute")

    # Find the computed item in the catalog
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed = next(i for i in catalog["items"] if i["origin"] == "computed")

    # Install it
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": computed["id"]}),
        headers=auth_headers(token),
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
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Missing computed output")
    node_id = "node-ghost"
    dataset_id = computed_dataset_id(node_id, project_id)
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
        headers=auth_headers(token),
    )
    assert resp.status_code == 404
    body = resp.get_json()
    assert "available" in body.get("error", "").lower() or "available" in body.get("message", "").lower()


def test_process_python_code_auto_installs_outputs_bundle(client, user_and_token, monkeypatch):
    """Tuple (outputs) installs as a multi-part bundle dataset."""
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment
    from utk_curio.sandbox.util.db import release_connection
    from utk_curio.sandbox.util.parsers import init_db, save_to_duckdb

    _, token = user_and_token
    project_id = create_project(client, token, name="Bundle auto install")
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
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    inst = body.get("installedDataset")
    assert inst is not None, body
    expected_id = computed_dataset_id(node_id, project_id)
    assert inst["id"] == expected_id
    assert inst["format"] == "bundle"

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    item = next(i for i in catalog["items"] if i["id"] == expected_id)
    # Execution saves the bundle to the account store (surfaced here) but does
    # NOT install it into the project — it's available, not installed.
    assert item.get("installed") is False
    assert item["format"] == "bundle"

    preview = client.get(
        f"/api/datasets/{expected_id}/preview?dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    assert preview.get("bundle") is True
    assert len(preview.get("parts") or []) >= 2


def test_process_python_code_auto_installs_dataset(client, user_and_token, monkeypatch):
    """Tabular node output with output.dataset is installed immediately."""
    import os
    from pathlib import Path
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    parquet_name = "1718000000000_abcd1234_output.parquet"
    (shared / parquet_name).write_bytes(b"PAR1")

    project_id = create_project(client, token, name="Auto install on exec")
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
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    inst = body.get("installedDataset")
    assert inst is not None, body
    expected_id = computed_dataset_id(node_id, project_id)
    assert inst["id"] == expected_id
    assert inst["dirName"] == f"{expected_id}@1"


def test_process_python_code_titles_computed_dataset_with_node_name(client, user_and_token, monkeypatch):
    """When the frontend sends nodeName, the computed dataset's title is the
    node's name and the generated filename moves to the ``fileName`` field."""
    import os
    from pathlib import Path
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.infrastructure.catalog_utils import title_from_filename
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    parquet_name = "1782498496720_ef610da8_output.parquet"
    (shared / parquet_name).write_bytes(b"PAR1")

    project_id = create_project(client, token, name="Node-named output")
    node_id = "node-named"

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
            "nodeName": "Data Transformation",
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    expected_id = computed_dataset_id(node_id, project_id)
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    item = next(i for i in catalog["items"] if i["id"] == expected_id)
    assert item["title"] == "Data Transformation"
    assert item["fileName"] == title_from_filename(parquet_name)


def test_reinstall_computed_dataset_recovers_node_title_from_node_title_param(client, user_and_token):
    """Reinstalling a computed dataset (e.g. after publish → uninstall) titles it
    by the client-resolved node label sent as ``nodeTitle`` — never the raw
    generated filename carried by the post-uninstall session item."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.infrastructure.catalog_utils import title_from_filename
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Reinstall with node title")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    filename = "1782498496720_ef610da8.json"
    (shared / filename).write_text('{"a": 1}', encoding="utf-8")

    node_id = "node-reinstall"
    dataset_id = computed_dataset_id(node_id, project_id)
    # After uninstall the dataset reappears as a session output whose title is the
    # generated filename (the original manifest was deleted on uninstall).
    source_item = {
        "id": dataset_id,
        "origin": "computed",
        "uri": f"curio://outputs/{filename}",
        "producerNodeId": node_id,
        "format": "json",
        "title": title_from_filename(filename),
        "fileName": title_from_filename(filename),
    }

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({
            "datasetId": dataset_id,
            "sourceItem": source_item,
            "nodeTitle": "Data Transformation",
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["title"] == "Data Transformation"
    assert body["fileName"] == title_from_filename(filename)


def test_reinstall_computed_dataset_without_node_title_never_uses_filename(client, user_and_token):
    """With no ``nodeTitle`` and no captured node name (the session item's title
    is the generated filename), reinstall falls back to the store-folder name —
    never the raw filename."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.infrastructure.catalog_utils import title_from_filename
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Reinstall without node title")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    filename = "1782498496720_ef610da8.json"
    (shared / filename).write_text('{"a": 1}', encoding="utf-8")

    node_id = "node-reinstall-noname"
    dataset_id = computed_dataset_id(node_id, project_id)
    filename_title = title_from_filename(filename)
    source_item = {
        "id": dataset_id,
        "origin": "computed",
        "uri": f"curio://outputs/{filename}",
        "producerNodeId": node_id,
        "format": "json",
        "title": filename_title,
        "fileName": filename_title,
    }

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id, "sourceItem": source_item}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["title"] != filename_title, "reinstall must not title the dataset with the raw filename"
    assert body["title"] == f"{dataset_id}@1"


def test_process_python_code_skips_auto_install_when_save_disabled(client, user_and_token, monkeypatch):
    from unittest.mock import MagicMock

    _, token = user_and_token
    project_id = create_project(client, token, name="Save off")
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
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json().get("installedDataset") is None


def test_installed_computed_dataset_appears_in_dataflow_catalog(client, user_and_token):
    """After installing a computed dataset it shows up as installed in the
    dataflow-scoped catalog (origin=imported, installed=True)."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = create_project(client, token, name="Post-install catalog check")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "results.csv").write_text("col\nA\nB\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "results.csv")

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed_id = next(i["id"] for i in catalog["items"] if i["origin"] == "computed")

    install = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": computed_id}),
        headers=auth_headers(token),
    )
    assert install.status_code == 200

    # Reload the catalog — the installed copy should be listed as installed
    catalog_after = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    installed = [
        i for i in catalog_after["items"]
        if i.get("installed") is True and i.get("origin") == "computed"
    ]
    assert any("results" in (i.get("path") or "") or "results" in (i.get("title") or "").lower() for i in installed), (
        f"Installed results.csv not found in catalog. Items: {[i.get('title') for i in catalog_after['items']]}"
    )


def _dataflow_dataset_ids(client, token, project_id):
    spec = client.get(f"/api/projects/{project_id}", headers=auth_headers(token)).get_json()
    datasets = (spec.get("spec") or {}).get("dataflow", {}).get("datasets") or []
    return {d.get("datasetId") for d in datasets if isinstance(d, dict)}


def _save_spec(client, token, project_id, datasets, outputs):
    """Mimic a frontend save: full spec (with whatever datasets the client
    tracked) plus the toggle-filtered output refs."""
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({
            "spec": {"dataflow": {"name": "x", "nodes": [], "edges": [], "datasets": datasets}},
            "outputs": outputs,
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_saved_computed_dataset_survives_disabling_save_toggle(client, user_and_token):
    """A computed dataset saved while the toggle was on is an account-level asset
    (no project ref) and must remain browsable after a later save that omits it
    (the toggle was turned off)."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Save-toggle persistence")
    node_id = "node-keep"
    expected_id = computed_dataset_id(node_id, project_id)

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "keep_me.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    # Save with the output (toggle ON) — saved to the account store, NOT installed
    # into the project (no spec ref).
    save_project_with_output(client, token, project_id, "keep_me.csv", node_id=node_id)
    assert expected_id not in _dataflow_dataset_ids(client, token, project_id)

    def _is_available():
        catalog = client.get(
            f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
            headers=auth_headers(token),
        ).get_json()
        return any(
            i["id"] == expected_id and i.get("installed") is False
            for i in catalog["items"]
        )

    assert _is_available(), "saved computed dataset should be browsable (not installed)"

    # Save again as if the toggle were turned OFF: the client no longer sends the
    # output. The account-level dataset must NOT vanish.
    _save_spec(client, token, project_id, datasets=[], outputs=[])
    assert _is_available(), "disabling the save toggle removed an account-level dataset"
    assert expected_id not in _dataflow_dataset_ids(client, token, project_id)


def _computed_catalog_item(client, token, project_id, dataset_id):
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    return next((i for i in catalog["items"] if i["id"] == dataset_id), None)


def test_saved_computed_dataset_dir_survives_save_off(
    client, user_and_token
):
    """The account-store dataset dir is the source of truth: it is created on
    save and a later toggle-off save keeps it (it's an account-level asset,
    independent of the project spec)."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Dir lifecycle")
    node_id = "node-dir"
    dir_name = f"{computed_dataset_id(node_id, project_id)}@1"
    dataset_dir = (
        Path(os.environ["CURIO_LAUNCH_CWD"]) / ".curio" / "users" / "1" / "datasets" / dir_name
    )

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "dir_me.csv").write_text("c\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "dir_me.csv", node_id=node_id)
    assert dataset_dir.is_dir(), "save should write the account-store dataset dir"

    # Toggle off + save: the account-level dir must remain.
    _save_spec(client, token, project_id, datasets=[], outputs=[])
    assert dataset_dir.is_dir(), "disabling save removed an account-level dataset dir"


def test_installed_computed_parquet_loader_is_geoparquet_aware(
    client, user_and_token, monkeypatch
):
    """A Dataset node built from a computed parquet must reload it geo-first so a
    GeoDataFrame producer is reproduced faithfully (not flattened to a DataFrame)."""
    import os
    from pathlib import Path
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Loader snippet parquet")
    node_id = "node-geo"

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    parquet_name = "1718000000111_dead0001_output.parquet"
    (shared / parquet_name).write_bytes(b"PAR1")  # only the ref matters here

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "",
        "stderr": "",
        "output": {"path": "art-geo", "dataType": "geodataframe", "dataset": parquet_name},
    }
    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes._sandbox_call",
        lambda *args, **kwargs: mock_response,
    )

    resp = client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": "    return gdf\n",
            "nodeType": "PYTHON_COMPUTATION",
            "nodeId": node_id,
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    expected_id = computed_dataset_id(node_id, project_id)
    item = _computed_catalog_item(client, token, project_id, expected_id)
    assert item is not None
    snippet = item.get("loaderSnippet") or {}
    assert "import geopandas as gpd" in (snippet.get("imports") or [])
    assert "gpd.read_parquet" in (snippet.get("code") or "")
    assert "pd.read_parquet" in (snippet.get("code") or "")


def test_installed_bundle_loader_returns_tuple(client, user_and_token, monkeypatch):
    """A Dataset node built from a tuple (bundle) output must reload it as a tuple
    so the sandbox re-detects the same ``outputs`` envelope."""
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment
    from utk_curio.sandbox.util.db import release_connection
    from utk_curio.sandbox.util.parsers import init_db, save_to_duckdb

    _, token = user_and_token
    project_id = create_project(client, token, name="Loader snippet bundle")
    node_id = "node-bundle-loader"

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
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    expected_id = computed_dataset_id(node_id, project_id)
    item = _computed_catalog_item(client, token, project_id, expected_id)
    assert item is not None
    assert item["format"] == "bundle"
    snippet = item.get("loaderSnippet") or {}
    assert snippet.get("returnVariable") == "bundle"
    assert "return tuple(items)" in (snippet.get("code") or "")
    assert "bundle.json" in (snippet.get("code") or "")


def test_published_computed_dataset_stays_installed_in_dataflow_catalog(
    client, user_and_token
):
    """Publishing a computed dataset must not uninstall its local copy: the
    dataflow catalog still reports it ``installed`` (origin computed,
    publishedToHub), which is the state the dataset palette filters on (#140).
    """
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id, sanitize_node_id_segment

    from utk_curio.backend.app.datasets.repositories.installed import (
        InstalledDatasetRepository,
    )

    user, token = user_and_token
    project_id = create_project(client, token, name="Publish keeps install")
    node_id = "node-pub"
    dataset_id = computed_dataset_id(node_id, project_id)

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "pub_me.csv").write_text("c\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "pub_me.csv", node_id=node_id)

    # Saved account-level: available, not installed, not published.
    before = _computed_catalog_item(client, token, project_id, dataset_id)
    assert before is not None and before.get("installed") is False
    assert not before.get("publishedToHub")

    # Simulate explicit install + publish: a dataflow ref with publishedToHub
    # (the dataset dir is untouched), persisted through the datasets-domain
    # section writer — the only writer of ``dataflow.datasets`` since dev/81
    # (a client-style save's section is inert on update). This mirrors what
    # publishDataset persists, without writing into the committed catalog root.
    published_ref = {
        "datasetId": dataset_id,
        "dirName": f"{dataset_id}@1",
        "origin": "computed",
        "producerNodeId": node_id,
        "publishedToHub": True,
    }
    InstalledDatasetRepository(user).replace_refs(project_id, [published_ref])

    after = _computed_catalog_item(client, token, project_id, dataset_id)
    assert after is not None, "published computed dataset vanished from the dataflow catalog"
    assert after.get("installed") is True, "published dataset must stay installed"
    assert after.get("publishedToHub") is True


def test_install_computed_dataset_carries_decode_sidecar(client, user_and_token):
    """Manual install must copy the <file>.decode.json object-column decode
    sidecar into the user store (review finding B8). The install always replaces
    the dataset dir via the file_bytes branch, so the final sidecar is present
    only if the install path copies it."""
    import os
    from pathlib import Path

    import pandas as pd

    _, token = user_and_token
    project_id = create_project(client, token, name="Install sidecar")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    shared.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"a": [1, 2], "tags": ['["x"]', '["y"]']}).to_parquet(shared / "withobj.parquet")
    (shared / "withobj.parquet.decode.json").write_text(
        json.dumps({"encoded_object_columns": ["tags"]}), encoding="utf-8"
    )

    save_project_with_output(client, token, project_id, "withobj.parquet", node_id="node-obj")

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed = next(i for i in catalog["items"] if i["origin"] == "computed")

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": computed["id"]}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    launch_cwd = Path(os.environ["CURIO_LAUNCH_CWD"])
    user_store = launch_cwd / ".curio" / "users"
    sidecars = list(user_store.rglob("withobj.parquet.decode.json"))
    assert sidecars, "manual install should copy the decode sidecar into the user store"


def test_two_nodes_sharing_output_file_both_appear_in_catalog(client, user_and_token):
    """Two producer nodes whose outputs resolve to the same data-file basename are
    two distinct saved records and must BOTH appear in the catalog — they are no
    longer collapsed by filename. (Same scenario that hid Autark map outputs beside
    their baseline-/modified-compute siblings.) Duplicate titles are acceptable;
    hiding a distinct saved dataset is not."""
    import os
    from pathlib import Path

    _, token = user_and_token
    project_id = create_project(client, token, name="Shared output")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    shared.mkdir(parents=True, exist_ok=True)
    fn = "1781903321396_c8572ee7.parquet"
    (shared / fn).write_bytes(b"PAR1")

    # Two distinct nodes report the same output file.
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"outputs": [
            {"node_id": "11111111-aaaa-0001", "filename": fn},
            {"node_id": "22222222-bbbb-0002", "filename": fn},
        ]}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    computed = [i for i in catalog["items"] if i.get("origin") == "computed"]
    # Both distinct records are present (one per producer node), not collapsed.
    assert len(computed) == 2, [i.get("id") for i in computed]
    assert len({i["id"] for i in computed}) == 2


def test_process_python_code_skips_unresolvable_output_artifact(client, user_and_token, monkeypatch):
    """When the output references an artifact that can't be resolved on disk,
    auto-install skips gracefully — no install, no crash — and reports a
    ``skipped`` diagnostic instead of failing silently.

    (Execution now persists JSON/path outputs in parity with the project-save
    installer, keyed on node id; only genuinely unresolvable artifacts skip.)"""
    from unittest.mock import MagicMock

    _, token = user_and_token
    project_id = create_project(client, token, name="No dataset emitted")

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "stdout": "",
        "stderr": "",
        # No 'dataset' key and the 'path' artifact id resolves to no file on disk.
        "output": {"path": "1781903321396_c8572ee7", "dataType": "dataframe"},
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
            "nodeId": "node-no-dataset",
            "dataflowId": project_id,
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": True,
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body.get("installedDataset") is None
    assert body.get("datasetDiagnostic", {}).get("status") == "skipped"
