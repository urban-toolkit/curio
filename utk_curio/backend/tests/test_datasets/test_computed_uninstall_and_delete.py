"""Uninstall keeps the account-level computed asset; an explicit
Delete permanently removes it (cascading unpublish + ref removal)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)


def _account_dir(node_id: str, project_id: str) -> Path:
    dir_name = f"{computed_dataset_id(node_id, project_id)}@1"
    return (
        Path(os.environ["CURIO_LAUNCH_CWD"]) / ".curio" / "users" / "1" / "datasets" / dir_name
    )


def _dataflow_dataset_ids(client, token, project_id):
    spec = client.get(f"/api/projects/{project_id}", headers=auth_headers(token)).get_json()
    datasets = (spec.get("spec") or {}).get("dataflow", {}).get("datasets") or []
    return {d.get("datasetId") for d in datasets if isinstance(d, dict)}


def _install(client, token, project_id, dataset_id):
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_uninstall_computed_keeps_account_dir(client, user_and_token):
    _, token = user_and_token
    project_id = create_project(client, token, name="Uninstall keeps asset")
    node_id = "keep-node"
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "keep.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "keep.csv", node_id=node_id)

    dataset_id = computed_dataset_id(node_id, project_id)
    account_dir = _account_dir(node_id, project_id)
    assert account_dir.is_dir()

    # Explicitly install into the project, then uninstall.
    _install(client, token, project_id, dataset_id)
    assert dataset_id in _dataflow_dataset_ids(client, token, project_id)

    resp = client.delete(
        f"/api/dataflows/{project_id}/datasets/{dataset_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    # Ref removed, but the account-level asset survives (installable again).
    assert dataset_id not in _dataflow_dataset_ids(client, token, project_id)
    assert account_dir.is_dir(), "uninstall must not delete the account-level dataset"


def test_delete_computed_removes_account_dir_and_refs(client, user_and_token):
    _, token = user_and_token
    project_id = create_project(client, token, name="Delete asset")
    node_id = "del-node"
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "del.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "del.csv", node_id=node_id)

    dataset_id = computed_dataset_id(node_id, project_id)
    account_dir = _account_dir(node_id, project_id)
    assert account_dir.is_dir()

    # Install it, then delete from the catalog.
    _install(client, token, project_id, dataset_id)
    assert dataset_id in _dataflow_dataset_ids(client, token, project_id)

    resp = client.delete(
        f"/api/datasets/{dataset_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["deleted"] is True
    assert body["failedDirs"] == []
    assert project_id in body["removedFrom"]

    # Account dir gone AND the project ref removed.
    assert not account_dir.exists(), "delete must remove the account-store folder"
    assert dataset_id not in _dataflow_dataset_ids(client, token, project_id)

    # No longer browsable account-level.
    catalog = client.get(
        "/api/datasets/catalog?includeHub=true", headers=auth_headers(token)
    ).get_json()
    assert not any(i["id"] == dataset_id for i in catalog["items"])


def test_delete_missing_dataset_404(client, user_and_token):
    _, token = user_and_token
    resp = client.delete(
        "/api/datasets/computed.nope.ghost", headers=auth_headers(token)
    )
    assert resp.status_code == 404


def test_delete_reports_leftover_dirs(client, user_and_token, monkeypatch):
    """#173: when rmtree can't actually remove the folder (a locked/mmapped file
    on Windows), the API must say so instead of a hardcoded success."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Locked delete")
    node_id = "locked-node"
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "locked.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "locked.csv", node_id=node_id)

    dataset_id = computed_dataset_id(node_id, project_id)
    account_dir = _account_dir(node_id, project_id)
    assert account_dir.is_dir()
    _install(client, token, project_id, dataset_id)

    # Portable stand-in for a Windows file lock: rmtree silently removes nothing.
    from utk_curio.backend.app.datasets.application import mutations
    monkeypatch.setattr(mutations.shutil, "rmtree", lambda *a, **k: None)

    resp = client.delete(f"/api/datasets/{dataset_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["deleted"] is False
    assert body["failedDirs"] == [f"{dataset_id}@1"]
    # The ref strip already committed — the response still reports it.
    assert project_id in body["removedFrom"]
    assert account_dir.is_dir()
