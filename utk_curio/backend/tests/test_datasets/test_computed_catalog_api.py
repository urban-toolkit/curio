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
    """A computed dataset saved while the toggle was on must remain installed
    after a later save that omits it (i.e. the toggle was turned off), and be
    removable only by an explicit uninstall."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Save-toggle persistence")
    node_id = "node-keep"
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "keep_me.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    # Save with the output (toggle ON) — installs and records the ref.
    save_project_with_output(client, token, project_id, "keep_me.csv", node_id=node_id)
    assert expected_id in _dataflow_dataset_ids(client, token, project_id)

    # Save again as if the toggle were turned OFF: the client no longer tracks
    # the computed ref and no longer sends the output. It must NOT be removed.
    _save_spec(client, token, project_id, datasets=[], outputs=[])
    assert expected_id in _dataflow_dataset_ids(client, token, project_id), (
        "disabling the save toggle removed an already-saved computed dataset"
    )

    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    assert any(
        i["id"] == expected_id and i.get("installed") is True for i in catalog["items"]
    ), "saved computed dataset should still be installed in the catalog"

    # Explicit uninstall is the only way to remove it.
    resp = client.delete(
        f"/api/dataflows/{project_id}/datasets/{expected_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert expected_id not in _dataflow_dataset_ids(client, token, project_id)

    # A subsequent save must not resurrect the uninstalled dataset.
    _save_spec(client, token, project_id, datasets=[], outputs=[])
    assert expected_id not in _dataflow_dataset_ids(client, token, project_id), (
        "uninstalled computed dataset was resurrected by a later save"
    )


def _computed_catalog_item(client, token, project_id, dataset_id):
    catalog = client.get(
        f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        headers=auth_headers(token),
    ).get_json()
    return next((i for i in catalog["items"] if i["id"] == dataset_id), None)


def test_saved_computed_dataset_dir_survives_save_off_and_dies_on_uninstall(
    client, user_and_token
):
    """The on-disk dataset dir is the source of truth: a toggle-off save keeps
    it, only an explicit uninstall deletes it."""
    import os
    from pathlib import Path

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Dir lifecycle")
    node_id = "node-dir"
    dir_name = f"computed.{sanitize_node_id_segment(node_id)}@1"
    dataset_dir = (
        Path(os.environ["CURIO_LAUNCH_CWD"]) / ".curio" / "users" / "1" / "datasets" / dir_name
    )

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "dir_me.csv").write_text("c\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "dir_me.csv", node_id=node_id)
    assert dataset_dir.is_dir(), "save with toggle on should install the dataset dir"

    # Toggle off + save: dir must remain.
    _save_spec(client, token, project_id, datasets=[], outputs=[])
    assert dataset_dir.is_dir(), "disabling save removed an already-installed dataset dir"

    # Explicit uninstall: dir is deleted.
    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
    resp = client.delete(
        f"/api/dataflows/{project_id}/datasets/{expected_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert not dataset_dir.exists(), "uninstall should delete the dataset dir"


def test_installed_computed_parquet_loader_is_geoparquet_aware(
    client, user_and_token, monkeypatch
):
    """A Dataset node built from a computed parquet must reload it geo-first so a
    GeoDataFrame producer is reproduced faithfully (not flattened to a DataFrame)."""
    import os
    from pathlib import Path
    from unittest.mock import MagicMock

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

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

    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
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

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment
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

    expected_id = f"computed.{sanitize_node_id_segment(node_id)}"
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

    from utk_curio.backend.app.datasets.installer import sanitize_node_id_segment

    _, token = user_and_token
    project_id = create_project(client, token, name="Publish keeps install")
    node_id = "node-pub"
    dataset_id = f"computed.{sanitize_node_id_segment(node_id)}"

    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "pub_me.csv").write_text("c\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "pub_me.csv", node_id=node_id)

    before = _computed_catalog_item(client, token, project_id, dataset_id)
    assert before is not None and before.get("installed") is True
    assert not before.get("publishedToHub")

    # Simulate publish: the dataflow ref gains publishedToHub (the dataset dir is
    # untouched). This mirrors what publishDataset persists, without writing into
    # the repo's committed catalog root.
    published_ref = {
        "datasetId": dataset_id,
        "dirName": f"{dataset_id}@1",
        "origin": "computed",
        "producerNodeId": node_id,
        "publishedToHub": True,
    }
    _save_spec(client, token, project_id, datasets=[published_ref], outputs=[])

    after = _computed_catalog_item(client, token, project_id, dataset_id)
    assert after is not None, "published computed dataset vanished from the dataflow catalog"
    assert after.get("installed") is True, "published dataset must stay installed"
    assert after.get("publishedToHub") is True






