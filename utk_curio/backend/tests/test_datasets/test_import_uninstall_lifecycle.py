"""Imported-dataset lifecycle: fresh re-import + full-cleanup uninstall + timestamps.

Covers three guarantees:
- Re-importing a byte-identical file is a **new** dataset (unique id/folder);
  content is never used to reuse a prior import's directory.
- Uninstalling an imported dataset removes **all traces** from the account-level
  store (folder, manifest, data file, counts sidecar) — but only when no other
  dataflow still references it.
- The source file's last-modified date is recorded distinctly from the Curio
  record's created/updated dates.
"""

from __future__ import annotations

import io
import json


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _import(client, token, *, name="cities.csv", body=b"a,b\n1,2\n", extra=None):
    data = {"file": (io.BytesIO(body), name)}
    if extra:
        data.update(extra)
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


# ── Installer unit: identical bytes → distinct datasets ──────────────────────

def test_install_imported_file_identical_bytes_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    from utk_curio.backend.app.datasets.install.installer import install_imported_file

    a = install_imported_file("1", b"same,bytes\n1,2\n", "one.csv", "csv")
    b = install_imported_file("1", b"same,bytes\n1,2\n", "two.csv", "csv")

    assert a.manifest.id != b.manifest.id
    assert a.dest != b.dest
    assert a.dest.is_dir() and b.dest.is_dir()
    assert a.replaced is False and b.replaced is False


def test_install_imported_file_records_source_updated_at(tmp_path, monkeypatch):
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    from utk_curio.backend.app.datasets.install.installer import install_imported_file
    from utk_curio.backend.app.datasets.domain.manifest import load_dataset_manifest

    result = install_imported_file(
        "1", b"a\n1\n", "x.csv", "csv", source_updated_at="2020-01-02T03:04:05Z"
    )
    reloaded = load_dataset_manifest(result.dest)
    assert reloaded.source_updated_at == "2020-01-02T03:04:05Z"
    # The record dates are the import time, not the source date.
    assert reloaded.created_at and reloaded.created_at != reloaded.source_updated_at


# ── Route: fresh re-import ───────────────────────────────────────────────────

def test_reimport_identical_file_creates_new_dataset(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    first = _import(client, token, body=b"a,b\n1,2\n")
    second = _import(client, token, body=b"a,b\n1,2\n")

    assert first["id"] != second["id"], "identical content must not reuse the id"

    listed = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
    ids = {i["id"] for i in listed}
    assert first["id"] in ids and second["id"] in ids


# ── Route: install time is persisted and surfaced, distinct from import ──────

def test_installed_dataset_surfaces_installed_at(client, user_and_token, tmp_path, monkeypatch):
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    project_id = create_project(client, token, name="Install-time flow")
    imported = _import(client, token, name="places.csv")
    imported_id = imported["id"]

    # Before install: no install time; import time (createdAt) is set.
    assert imported.get("installedAt") is None
    assert imported.get("createdAt")

    inst = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        headers=_auth(token),
        data=json.dumps({"datasetId": imported_id}),
    )
    assert inst.status_code in (200, 201), inst.get_data(as_text=True)

    listed = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}", headers=_auth(token)
    ).get_json()["items"]
    row = next((i for i in listed if i["id"] == imported_id), None)
    assert row is not None
    # Install time is persisted metadata surfaced on the item, kept separate from
    # the import/record-creation time.
    assert row["installedAt"], "installed dataset must carry a persisted installedAt"
    assert row["createdAt"], "import time (createdAt) must remain populated"


# ── Route: full-cleanup uninstall ────────────────────────────────────────────

def test_uninstall_imported_removes_all_traces(client, user_and_token, tmp_path, monkeypatch):
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    user_key = str(user.id)

    project_id = create_project(client, token, name="Cleanup flow")
    imported = _import(client, token, name="roads.csv")
    imported_id = imported["id"]
    dir_name = imported["dirName"]
    store_dir = dataset_dir(user_key, dir_name)
    assert store_dir.is_dir()

    # Install then uninstall.
    inst = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        headers=_auth(token),
        data=json.dumps({"datasetId": imported_id}),
    )
    assert inst.status_code in (200, 201), inst.get_data(as_text=True)

    un = client.delete(
        f"/api/dataflows/{project_id}/datasets/{imported_id}",
        headers=_auth(token),
    )
    assert un.status_code == 200, un.get_data(as_text=True)

    # All traces gone: store folder removed and no longer listed anywhere.
    assert not store_dir.exists(), "imported store folder must be removed on uninstall"
    listed = client.get("/api/datasets/catalog", headers=_auth(token)).get_json()["items"]
    assert imported_id not in {i["id"] for i in listed}


def test_uninstall_keeps_dataset_used_by_another_dataflow(
    client, user_and_token, tmp_path, monkeypatch
):
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))
    user_key = str(user.id)

    flow_a = create_project(client, token, name="Flow A")
    flow_b = create_project(client, token, name="Flow B")
    imported = _import(client, token, name="shared.csv")
    imported_id = imported["id"]
    store_dir = dataset_dir(user_key, imported["dirName"])

    for flow in (flow_a, flow_b):
        inst = client.post(
            f"/api/dataflows/{flow}/datasets/install",
            headers=_auth(token),
            data=json.dumps({"datasetId": imported_id}),
        )
        assert inst.status_code in (200, 201), inst.get_data(as_text=True)

    # Uninstall from A only — B still uses it, so the folder must survive.
    un = client.delete(
        f"/api/dataflows/{flow_a}/datasets/{imported_id}", headers=_auth(token)
    )
    assert un.status_code == 200, un.get_data(as_text=True)
    assert store_dir.is_dir(), "folder still referenced by Flow B must be kept"

    b_items = client.get(
        f"/api/datasets/catalog?dataflowId={flow_b}", headers=_auth(token)
    ).get_json()["items"]
    row = next((i for i in b_items if i["id"] == imported_id), None)
    assert row is not None and row["installed"] is True


# ── Route: distinct timestamps ───────────────────────────────────────────────

def test_import_records_source_updated_at_distinct_from_created(
    client, user_and_token, tmp_path, monkeypatch
):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    # 2020-01-02T03:04:05Z in epoch milliseconds (as File.lastModified sends).
    epoch_ms = "1577934245000"
    imported = _import(client, token, extra={"sourceUpdatedAt": epoch_ms})

    assert imported["sourceUpdatedAt"] is not None
    assert imported["sourceUpdatedAt"].startswith("2020-01-02")
    assert imported["createdAt"] is not None
    # The Curio record date is the import time, not the source file date.
    assert imported["createdAt"] != imported["sourceUpdatedAt"]


def test_import_without_source_updated_at_is_none(client, user_and_token, tmp_path, monkeypatch):
    _, token = user_and_token
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(tmp_path))

    imported = _import(client, token)
    assert imported["sourceUpdatedAt"] is None
    assert imported["createdAt"] is not None
