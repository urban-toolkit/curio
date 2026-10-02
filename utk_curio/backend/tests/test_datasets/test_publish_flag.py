"""``--no-allow-publish`` refuses dataset publishing in the API, not only in the UI (#436).

The flag (``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``) hides the Data Catalog's
Publish and Unpublish buttons, and the package catalog's publish route answers
403 with it off. The dataset routes never read it, so a direct request still
wrote to the shared catalog. They read it the way the package routes do,
through ``packages.routes.common``, so one patch reaches every gate.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage
from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
from utk_curio.backend.app.packages.routes import common as routes_common
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    save_project_with_output,
)
from utk_curio.backend.tests.test_datasets.test_guest_catalog_writes import (
    _make_user,
    _publish_dir,
    _stub_publish_source,
)


@pytest.fixture()
def catalog_root(tmp_path, monkeypatch):
    root = tmp_path / "shared_catalog"
    root.mkdir()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: root)
    return root


@pytest.fixture()
def publish_off(monkeypatch):
    monkeypatch.setattr(routes_common, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", False)


def test_publish_is_refused_with_publishing_off(
    app, db, client, catalog_root, monkeypatch, tmp_path, publish_off
):
    _make_user(db, "alice", "alice-tok")
    src = tmp_path / "out.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    _stub_publish_source(monkeypatch, "computed.parcels", src)

    resp = client.post(
        "/api/datasets/publish",
        json={"datasetId": "computed.parcels", "title": "Parcels"},
        headers=auth_headers("alice-tok"),
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == routes_common.CATALOG_PUBLISH_DISABLED_MESSAGE
    assert list(catalog_root.iterdir()) == []


def test_unpublish_is_refused_with_publishing_off(app, db, client, catalog_root, publish_off):
    alice = _make_user(db, "alice", "alice-tok")
    pub_dir = _publish_dir(catalog_root, "computed.parcels", publisher=str(alice))

    resp = client.delete(
        "/api/datasets/publish/computed.parcels", headers=auth_headers("alice-tok")
    )
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert (pub_dir / "manifest.json").is_file()


def test_deleting_a_dataset_still_works_with_publishing_off(client, user_and_token, publish_off):
    """Delete cascades through the unpublish SERVICE, not the route, so the
    flag does not strand a user's own dataset."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Delete with publishing off")
    shared = Path(os.environ["CURIO_SHARED_DATA"])
    (shared / "off.csv").write_text("a\n1\n", encoding="utf-8")
    save_project_with_output(client, token, project_id, "off.csv", node_id="off-node")

    resp = client.delete(
        f"/api/datasets/{computed_dataset_id('off-node', project_id)}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["deleted"] is True
