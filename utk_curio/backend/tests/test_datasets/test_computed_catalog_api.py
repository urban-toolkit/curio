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
    assert installed, "save should install into the user datasets store"

    spec = client.get(f"/api/projects/{project_id}", headers=auth_headers(token)).get_json()
    datasets = (spec.get("spec") or {}).get("dataflow", {}).get("datasets") or []
    assert any(d.get("producerNodeId") == "node-save" and d.get("dirName") for d in datasets)


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

    # Fetch catalog scoped to this dataflow
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
    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Missing computed output")
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
        headers=auth_headers(token),
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
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
    assert inst["id"] == expected_id
    assert inst["format"] == "bundle"

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    item = next(i for i in catalog["items"] if i["id"] == expected_id)
    assert item.get("installed") is True
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

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

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
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
    assert inst["id"] == expected_id
    assert inst["dirName"] == f"{expected_id}@1"


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






