"""Archived-aware usage scans + node-level ref cleanup on delete (#176).

``dataset_usage`` scanned only non-archived projects, so uninstall's
orphan-dir gate could rmtree a store folder an archived project still
references (restoring the project degraded to a placeholder), and delete left
archived specs — and every node-level ``metadata.datasetRefs`` binding —
pointing at the removed dir. The public ``/usage`` endpoint intentionally stays
active-only.
"""
from __future__ import annotations

import io
import json

from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
)


def _import(client, token, *, name="cities.csv", body=b"a,b\n1,2\n"):
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _install(client, token, flow_id, dataset_id):
    resp = client.post(
        f"/api/dataflows/{flow_id}/datasets/install",
        headers=auth_headers(token),
        data=json.dumps({"datasetId": dataset_id}),
    )
    assert resp.status_code in (200, 201), resp.get_data(as_text=True)


def _archive(db, user, project_id):
    from utk_curio.backend.app.projects import repositories as projects_repo

    projects_repo.soft_delete(project_id, user.id)
    db.session.commit()


def test_usage_scopes_and_public_endpoint(app, db, client, user_and_token):
    user, token = user_and_token
    flow_a = create_project(client, token, name="Active flow")
    flow_b = create_project(client, token, name="Soon archived")
    imported = _import(client, token, name="scoped.csv")
    for flow in (flow_a, flow_b):
        _install(client, token, flow, imported["id"])
    _archive(db, user, flow_b)

    # Public endpoint stays active-only (archived rows would link to
    # un-openable projects in the UI).
    rows = client.get(
        f"/api/datasets/{imported['id']}/usage", headers=auth_headers(token)
    ).get_json()["dataflows"]
    assert {r["dataflowId"] for r in rows} == {flow_a}

    # The archived-inclusive scan used by the destructive gates sees both.
    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    with app.app_context():
        svc = DatasetCatalogService(user)
        wide = svc.dataset_usage(imported["id"], include_archived=True)
        assert {u["dataflowId"] for u in wide} == {flow_a, flow_b}


def test_uninstall_keeps_store_dir_referenced_by_archived_project(
    app, db, client, user_and_token
):
    """The data-loss regression: uninstalling from the last ACTIVE project must
    not delete the store folder an archived project still references."""
    user, token = user_and_token
    user_key = str(user.id)
    flow_a = create_project(client, token, name="Active uninstaller")
    flow_b = create_project(client, token, name="Archived holder")
    imported = _import(client, token, name="held.csv")
    for flow in (flow_a, flow_b):
        _install(client, token, flow, imported["id"])
    _archive(db, user, flow_b)

    store_dir = dataset_dir(user_key, imported["dirName"])
    assert store_dir.is_dir()

    resp = client.delete(
        f"/api/dataflows/{flow_a}/datasets/{imported['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert store_dir.is_dir(), "folder referenced by an archived project must survive"


def test_delete_strips_archived_refs_and_node_bindings(app, db, client, user_and_token):
    user, token = user_and_token
    user_key = str(user.id)
    flow_a = create_project(client, token, name="Active consumer")
    flow_b = create_project(client, token, name="Archived consumer")
    imported = _import(client, token, name="doomed.csv")
    dataset_id = imported["id"]
    for flow in (flow_a, flow_b):
        _install(client, token, flow, dataset_id)

    # Node-level bindings in B: one node keeps another dataset, one only this.
    from utk_curio.backend.app.projects import storage as project_storage
    with app.app_context():
        spec = project_storage.read_spec(user_key, flow_b)
        spec["dataflow"]["nodes"] = [
            {"id": "n1", "type": "PYTHON_COMPUTATION",
             "metadata": {"datasetRefs": [dataset_id, "imported.other-kept"]}},
            {"id": "n2", "type": "PYTHON_COMPUTATION",
             "metadata": {"datasetRefs": [dataset_id]}},
        ]
        project_storage.write_spec(user_key, flow_b, spec)
    _archive(db, user, flow_b)

    resp = client.delete(f"/api/datasets/{dataset_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["deleted"] is True
    assert set(body["removedFrom"]) == {flow_a, flow_b}

    with app.app_context():
        updated = project_storage.read_spec(user_key, flow_b)
        # dataflow.datasets ref gone from the ARCHIVED spec too.
        assert all(
            r.get("datasetId") != dataset_id
            for r in updated["dataflow"].get("datasets") or []
            if isinstance(r, dict)
        )
        nodes = {n["id"]: n for n in updated["dataflow"]["nodes"]}
        assert nodes["n1"]["metadata"]["datasetRefs"] == ["imported.other-kept"]
        assert "datasetRefs" not in nodes["n2"].get("metadata", {})

        # Nothing anywhere still claims to use it.
        from utk_curio.backend.app.datasets.application.catalog_service import (
            DatasetCatalogService,
        )
        svc = DatasetCatalogService(user)
        assert svc.dataset_usage(dataset_id, include_archived=True) == []
