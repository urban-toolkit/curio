"""Index write-through at the dataset mutation sites.

Every path that creates or removes an account-store dir keeps the index in step,
so a dataset is queryable immediately after it is written and its row is gone
once its dir is. All of it is best-effort by design: indexing must never turn a
successful dataset write into an error — ``reconcile`` repairs what write-through
misses.
"""

from __future__ import annotations

import io
import json
import shutil
import types

import pytest

from utk_curio.backend.app.datasets.repositories import index as index_repo
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


@pytest.fixture()
def store(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    return tmp_path


# ── Creation paths ─────────────────────────────────────────────────────────

def test_computed_installers_index_their_dirs(store):
    from utk_curio.backend.app.datasets.install.installer import (
        install_computed_file,
        install_computed_file_for_node,
    )

    for_node = install_computed_file_for_node(
        "1", b"{}", "a.json", "json", node_id="n-1", dataflow_id="flow-a"
    )
    legacy = install_computed_file("1", b"{}", "b.json", "json")

    assert index_repo.get("1", for_node.manifest.id) is not None
    assert index_repo.get("1", legacy.manifest.id) is not None
    assert index_repo.get("1", for_node.manifest.id).origin == "computed"


def test_bundle_installer_indexes_its_dir(store, tmp_path):
    from utk_curio.backend.app.datasets.install.bundle import (
        BundlePart,
        install_computed_bundle_for_node,
    )

    # A part backed by a real file, so the installer copies it rather than
    # reaching into the sandbox DuckDB for a scalar value.
    part_src = tmp_path / "part0.json"
    part_src.write_text(json.dumps({"k": "v"}), encoding="utf-8")

    result = install_computed_bundle_for_node(
        "1",
        [BundlePart(index=0, artifact_id="a1", kind="dict", format="json",
                    label="Object · part 1", source_path=part_src)],
        node_id="n-bundle",
        parent_artifact_id="parent-1",
        dataflow_id="flow-a",
    )

    row = index_repo.get("1", result.manifest.id)
    assert row is not None
    assert row.format == "bundle"
    assert row.data_file == "data/bundle.json"


def test_catalog_install_indexes_the_user_store_copy(store):
    """Installing a hub dataset into a user's store indexes the copy."""
    from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root
    from utk_curio.backend.app.datasets.install.installer import (
        install_dataset_from_catalog,
    )

    hub_dir = catalog_root() / "imported.xhubcopy1@1"
    (hub_dir / "data").mkdir(parents=True, exist_ok=True)
    (hub_dir / "data" / "x.csv").write_text("a\n1\n", encoding="utf-8")
    (hub_dir / "manifest.json").write_text(
        json.dumps({
            "id": "imported.xhubcopy1", "name": "Hub Copy", "version": "1.0.0",
            "format": "csv", "dataFile": "data/x.csv", "compatibility": {"major": 1},
        }),
        encoding="utf-8",
    )
    try:
        install_dataset_from_catalog("1", "imported.xhubcopy1@1")
        row = index_repo.get("1", "imported.xhubcopy1")
        assert row is not None
        assert row.title == "Hub Copy"
    finally:
        shutil.rmtree(hub_dir, ignore_errors=True)


def test_http_import_indexes_the_dataset(store, client, user_and_token):
    _, token = user_and_token

    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"a,b\n1,2\n"), "cities.csv")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)

    dataset_id = resp.get_json()["id"]
    assert index_repo.get("1", dataset_id) is not None


# ── Removal paths ──────────────────────────────────────────────────────────

def test_delete_dataset_drops_the_row(store, client, user_and_token):
    _, token = user_and_token
    imported = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"a\n1\n"), "gone.csv")},
        content_type="multipart/form-data",
    ).get_json()
    assert index_repo.get("1", imported["id"]) is not None

    resp = client.delete(
        f"/api/datasets/{imported['id']}", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    assert index_repo.get("1", imported["id"]) is None


def test_uninstall_of_orphaned_import_drops_the_row(store, client, user_and_token):
    """Uninstalling an imported dataset no other project uses removes the store
    dir — and with it the index row."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Index uninstall")
    imported = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(b"a\n1\n"), "temp.csv")},
        content_type="multipart/form-data",
    ).get_json()
    client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": imported["id"]}),
        headers=auth_headers(token),
    )

    resp = client.delete(
        f"/api/dataflows/{project_id}/datasets/{imported['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    assert index_repo.get("1", imported["id"]) is None


# ── Legacy-id migration ────────────────────────────────────────────────────

def test_legacy_id_migration_moves_the_row(store, app, client, user_and_token):
    """The migration renames the dir and rewrites the manifest id; the index must
    follow rather than keep a row for a dir that no longer exists."""
    from utk_curio.backend.app.datasets.application import migrations
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.app.projects import storage as project_storage
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
        write_legacy_computed_dir,
    )

    _, token = user_and_token
    project_id = create_project(client, token, name="Legacy migration")
    node_id = "n-legacy"
    legacy_id = write_legacy_computed_dir("1", node_id)

    # The migration only moves a dir it can attribute to one dataflow, so give
    # the project a spec that owns this legacy dataset.
    project_storage.write_spec("1", project_id, {
        "dataflow": {
            "name": "Owner",
            "nodes": [{"id": node_id, "type": "PYTHON_COMPUTATION", "x": 0, "y": 0}],
            "edges": [],
            "datasets": [{
                "datasetId": legacy_id,
                "dirName": f"{legacy_id}@1",
                "origin": "computed",
                "producerNodeId": node_id,
            }],
        }
    })

    index_repo.upsert_from_dir("1", dataset_dir("1", f"{legacy_id}@1"))
    assert index_repo.get("1", legacy_id) is not None

    migrations._migrated_users.discard("1")
    assert migrations.migrate_computed_dataset_ids("1") == 1

    # Old row gone; the new namespaced row points at the dir that now exists.
    new_id = computed_dataset_id(node_id, project_id)
    assert index_repo.get("1", legacy_id) is None
    row = index_repo.get("1", new_id)
    assert row is not None
    assert row.dir_name == f"{new_id}@1"
    assert dataset_dir("1", row.dir_name).is_dir()


# ── Degradation ────────────────────────────────────────────────────────────

def test_index_failure_does_not_break_the_dataset_write(store, monkeypatch):
    """A DB failure during write-through must leave the install successful — the
    files are already on disk and reconcile will pick the row up later."""
    from utk_curio.backend.app.datasets.install.installer import install_imported_file

    def boom(*_args, **_kwargs):
        raise RuntimeError("index is down")

    monkeypatch.setattr(index_repo, "upsert_from_dir", boom)

    result = install_imported_file("1", b"a\n1\n", "resilient.csv", "csv")

    assert (result.dest / result.manifest.data_file).is_file()
    assert index_repo.get("1", result.manifest.id) is None

    # And the listing still shows it (disk wins), then reconcile repairs the row.
    monkeypatch.undo()
    from utk_curio.backend.app.datasets.repositories.user_store import (
        UserDatasetRepository,
    )

    user = types.SimpleNamespace(id=1, is_guest=False, username="alice")
    items = UserDatasetRepository(user).list_items()
    assert any(item["id"] == result.manifest.id for item in items)
    assert index_repo.get("1", result.manifest.id) is not None
