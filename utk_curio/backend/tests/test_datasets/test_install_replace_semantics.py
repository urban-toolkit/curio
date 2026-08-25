"""Install fully replaces the existing dataflow ref (dev/81 Fix 3).

A (re)install's persisted ref is exactly ``_ref_from_item``'s output — nothing
is inherited from the old ref via dict-merge. These tests pin:

- a legacy "fat ref" (inline title/path/format/…) converges to the lean form
  on reinstall, with stale flags (``publishedToHub``/``sourceOrigin``) dropped;
- repeated installs stay idempotent — exactly one ref per dataset id;
- ``installedAt`` is always the new install's timestamp;
- the Published badge is NOT lost by the ref-field drop: it derives from the
  hub registry row at listing time, and an explicit unpublish stays suppressed.
"""

from __future__ import annotations

import io
import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)

# The lean ref shape emitted by ``_ref_from_item`` for folder-backed datasets.
LEAN_REF_KEYS = {
    "datasetId",
    "dirName",
    "origin",
    "producerNodeId",
    "consumerNodeIds",
    "installedAt",
}


def _import(client, token, *, name="cities.csv", body=b"a,b\n1,2\n"):
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _install(client, token, project_id, dataset_id, source_item=None):
    body = {"datasetId": dataset_id}
    if source_item is not None:
        body["sourceItem"] = source_item
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps(body),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _spec_refs(client, token, project_id):
    resp = client.get(f"/api/projects/{project_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    spec = resp.get_json()["spec"] or {}
    dataflow = spec.get("dataflow") or {}
    return dataflow.get("datasets") or []


def _seed_refs(user, project_id, refs):
    """Write refs through the datasets-domain writer (the only legitimate one)."""
    from utk_curio.backend.app.datasets.repositories.installed import (
        InstalledDatasetRepository,
    )

    InstalledDatasetRepository(user).replace_refs(project_id, refs)


def test_reinstall_converges_fat_ref_to_lean(client, user_and_token):
    """A legacy fat ref (inline metadata + stale flags) becomes the lean
    ``_ref_from_item`` shape on reinstall; nothing from the old ref survives."""
    user, token = user_and_token
    project_id = create_project(client, token, name="Fat ref convergence")
    imported = _import(client, token)
    dataset_id, dir_name = imported["id"], imported["dirName"]

    stale_installed_at = "2020-01-01T00:00:00+00:00"
    _seed_refs(user, project_id, [{
        "datasetId": dataset_id,
        "dirName": dir_name,
        "origin": "imported",
        "title": "Stale inline title",
        "path": "/stale/old/path.csv",
        "format": "csv",
        "sizeBytes": 12345,
        "publishedToHub": True,
        "sourceOrigin": "imported",
        "producerNodeId": None,
        "consumerNodeIds": ["ghost-node"],
        "installedAt": stale_installed_at,
    }])

    _install(client, token, project_id, dataset_id)

    refs = _spec_refs(client, token, project_id)
    assert [r["datasetId"] for r in refs] == [dataset_id]
    ref = refs[0]
    assert set(ref.keys()) == LEAN_REF_KEYS
    assert ref["dirName"] == dir_name
    assert ref["origin"] == "imported"
    assert ref["installedAt"] != stale_installed_at


def test_repeated_install_is_idempotent_single_ref(client, user_and_token):
    """Installing the same dataset twice yields exactly one ref."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Idempotent install")
    imported = _import(client, token, name="pois.csv")

    _install(client, token, project_id, imported["id"])
    _install(client, token, project_id, imported["id"])

    refs = _spec_refs(client, token, project_id)
    assert [r["datasetId"] for r in refs] == [imported["id"]]
    assert set(refs[0].keys()) == LEAN_REF_KEYS


def test_published_badge_survives_reinstall_via_hub_row(
    client, user_and_token, tmp_path, monkeypatch
):
    """Reinstall drops ``publishedToHub`` from the ref, but the listing still
    shows Published — the badge derives from the hub registry row merge."""
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    project_id = create_project(client, token, name="Badge survives reinstall")
    imported = _import(client, token, name="trees.csv")

    _install(client, token, project_id, imported["id"])
    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({"datasetId": imported["id"], "dataflowId": project_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    catalog_id = resp.get_json()["id"]

    # Publish stamped the flag onto the (possibly id-remapped) ref.
    published_ref = next(
        r for r in _spec_refs(client, token, project_id)
        if r["datasetId"] == catalog_id
    )
    assert published_ref.get("publishedToHub") is True

    _install(client, token, project_id, catalog_id)

    ref = next(
        r for r in _spec_refs(client, token, project_id)
        if r["datasetId"] == catalog_id
    )
    assert "publishedToHub" not in ref  # replaced, not merged

    listed = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}&includeHub=true",
        headers=auth_headers(token),
    ).get_json()["items"]
    item = next(i for i in listed if i["id"] == catalog_id)
    assert item.get("installed") is True
    assert item.get("publishedToHub") is True


def test_explicit_unpublish_stays_suppressed_after_reinstall(
    client, user_and_token, tmp_path, monkeypatch
):
    """After an explicit unpublish, a reinstall must not resurrect the badge."""
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    project_id = create_project(client, token, name="Unpublish stays suppressed")
    imported = _import(client, token, name="lots.csv")

    _install(client, token, project_id, imported["id"])
    resp = client.post(
        "/api/datasets/publish",
        data=json.dumps({"datasetId": imported["id"], "dataflowId": project_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    catalog_id = resp.get_json()["id"]

    resp = client.delete(
        f"/api/datasets/publish/{catalog_id}?dataflowId={project_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)

    _install(client, token, project_id, catalog_id)

    listed = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}&includeHub=true",
        headers=auth_headers(token),
    ).get_json()["items"]
    item = next(i for i in listed if i["id"] == catalog_id)
    assert item.get("installed") is True
    assert not item.get("publishedToHub")
