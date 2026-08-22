"""Regression tests for issue #165: a missing catalog root must not 500.

``catalog_root()`` never creates the directory, so a pip install (the repo's
``datasets/`` tree is not shipped into site-packages) or a not-yet-created
``CURIO_CATALOG_ROOT`` leaves it absent until the first publish. Unpublish used
to call ``root.iterdir()`` unguarded, so the resulting ``FileNotFoundError``
escaped ``_map_catalog_errors`` and surfaced as an opaque HTTP 500 — from both
``DELETE /api/datasets/publish/<id>`` and the ``delete_dataset`` cascade.
"""
from __future__ import annotations

from utk_curio.backend.app.datasets.infrastructure import storage as ds_storage
from utk_curio.backend.app.projects.services import _user_dir_key
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers


def _missing_root(tmp_path, monkeypatch):
    root = tmp_path / "catalog-root-that-does-not-exist"
    assert not root.exists()
    monkeypatch.setattr(ds_storage, "catalog_root", lambda: root)
    return root


def test_unpublish_with_missing_catalog_root_is_404_not_500(
    client, user_and_token, tmp_path, monkeypatch
):
    _, token = user_and_token
    _missing_root(tmp_path, monkeypatch)

    resp = client.delete(
        "/api/datasets/publish/computed.never-published", headers=auth_headers(token)
    )
    assert resp.status_code == 404, resp.get_data(as_text=True)
    body = resp.get_json()
    assert "not in the Data Catalog" in body["error"]


def test_delete_store_only_dataset_with_missing_catalog_root_succeeds(
    app, client, user_and_token, tmp_path, monkeypatch
):
    user, token = user_and_token
    _missing_root(tmp_path, monkeypatch)

    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file_for_node,
    )

    with app.app_context():
        user_key = _user_dir_key(user)
        result = install_computed_file_for_node(
            user_key, b'{"v": 1}', "out.json", "json",
            node_id="node-165", dataflow_id="flow-165",
        )
        dataset_id = result.manifest.id
        store_dir = result.dest

    resp = client.delete(f"/api/datasets/{dataset_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["deleted"] is True
    assert not store_dir.exists()
