"""Regression tests for publish_dataset (review findings B2, B5)."""
from __future__ import annotations

import json

import pytest

from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.service import DatasetCatalogService


def _bundle_source(tmp_path):
    src = tmp_path / "src" / "computed.x@1"
    (src / "data" / "parts").mkdir(parents=True)
    (src / "data" / "bundle.json").write_text(
        json.dumps({"version": 1, "parts": [{"index": 0, "file": "data/parts/00_array.json"}]}),
        encoding="utf-8",
    )
    (src / "data" / "parts" / "00_array.json").write_text("[1, 2, 3]", encoding="utf-8")
    return src / "data" / "bundle.json"


def test_publish_bundle_copies_parts_subtree(tmp_path, monkeypatch):
    bundle_json = _bundle_source(tmp_path)
    cat_root = tmp_path / "catalog"
    cat_root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user=None)
    monkeypatch.setattr(svc, "get_dataset", lambda *a, **k: {
        "id": "computed.x", "title": "Bundle", "format": "bundle",
        "path": bundle_json.as_posix(), "origin": "computed", "producerNodeId": "x",
    })

    svc.publish_dataset("computed.x", {})

    pub = cat_root / "computed.x@1"
    assert (pub / "data" / "bundle.json").is_file()
    # B2: the parts subtree must be copied, not just bundle.json.
    assert (pub / "data" / "parts" / "00_array.json").is_file()


def test_publish_rejects_missing_local_file(tmp_path, monkeypatch):
    cat_root = tmp_path / "catalog"
    cat_root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user=None)
    monkeypatch.setattr(svc, "get_dataset", lambda *a, **k: {
        "id": "computed.y", "title": "Ghost", "format": "csv",
        "path": "curio://datasets/ghost", "origin": "computed", "producerNodeId": "y",
    })

    # B5: no on-disk file → raise rather than write a manifest pointing at nothing.
    with pytest.raises(DatasetCatalogError):
        svc.publish_dataset("computed.y", {})


def test_publish_persists_producer_lineage_in_hub_manifest(tmp_path, monkeypatch):
    """#170: the committed hub manifest must carry producer/upstream lineage —
    it is the only copy other users and fresh checkouts ever see."""
    data_file = tmp_path / "out.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    cat_root = tmp_path / "catalog"
    cat_root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: cat_root)

    svc = DatasetCatalogService(user=None)
    monkeypatch.setattr(svc, "get_dataset", lambda *a, **k: {
        "id": "computed.flow-1.n1", "title": "Lineaged", "format": "csv",
        "path": data_file.as_posix(), "origin": "computed",
        "producerNodeId": "n1",
        "producerNodeType": "curio.builtin/data-transformation",
        "producerDataflowId": "flow-1",
        "producerDataflowName": "My Flow",
        "upstreamInputs": [{"nodeId": "up1", "nodeType": "DATA_LOADING"}],
    })

    svc.publish_dataset("computed.flow-1.n1", {})

    manifest = json.loads(
        (cat_root / "computed.flow-1.n1@1" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["producerNodeId"] == "n1"
    assert manifest["producerNodeType"] == "curio.builtin/data-transformation"
    assert manifest["producerDataflowId"] == "flow-1"
    assert manifest["producerDataflowName"] == "My Flow"
    assert manifest["upstreamInputs"] == [{"nodeId": "up1", "nodeType": "DATA_LOADING"}]


def test_a_published_list_column_installs_as_lists(client, db, user_and_token, tmp_path, monkeypatch):
    """#700: a node output's list column survives publishing. Parquet holds the
    lists as JSON text, and the ``<file>.decode.json`` beside the file names the
    columns to decode. Publish copies it with the file, so another account that
    installs the published dataset loads the column as lists, not as strings."""
    import pandas as pd

    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.app.users.models import User, UserSession
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        auth_headers,
        create_project,
        save_project_with_output,
    )
    from utk_curio.sandbox.util.catalog_helpers import read_dataset
    from utk_curio.sandbox.util.parsers import save_dataset_parquet

    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _alice, token = user_and_token

    # Saved as a node run saves it: the lists encoded, the sidecar beside them.
    filename = save_dataset_parquet(
        pd.DataFrame({"stop": ["Clark", "State"], "routes": [["22", "36"], ["2"]]}), "dataframe"
    )
    assert filename, "the sandbox writer saved no Parquet file"
    project_id = create_project(client, token, name="Routes per stop")
    save_project_with_output(client, token, project_id, filename, node_id="node-routes")

    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({"datasetId": computed_dataset_id("node-routes", project_id), "dataflowId": project_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    catalog_id = resp.get_json()["id"]

    # Another account installs the published dataset into one of its dataflows.
    bob = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(bob)
    db.session.flush()
    db.session.add(UserSession(user_id=bob.id, token="bob-token-700"))
    db.session.commit()
    bob_project = create_project(client, "bob-token-700", name="Transit")
    resp = client.post(
        f"/api/dataflows/{bob_project}/datasets/install",
        data=json.dumps({"datasetId": catalog_id}),
        headers=auth_headers("bob-token-700"),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    installed = resp.get_json()

    # Read as ``curio_load_data`` reads it in a node.
    frame = read_dataset(installed["path"], "parquet")
    assert frame["routes"].tolist() == [["22", "36"], ["2"]], (
        f"the installed copy of {catalog_id} at {installed['path']} reads its list "
        f"column as {frame['routes'].tolist()!r}"
    )


def test_catalog_root_env_override(tmp_path, monkeypatch):
    """CURIO_CATALOG_ROOT relocates the hub/publish target for pip/Docker
    deployments where the package dir is read-only/ephemeral (review B10)."""
    from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage

    monkeypatch.delenv("CURIO_CATALOG_ROOT", raising=False)
    default_root = ds_storage.catalog_root()
    assert default_root.name == "datasets"  # unchanged default

    override = tmp_path / "writable_catalog"
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(override))
    assert ds_storage.catalog_root() == override.resolve()
