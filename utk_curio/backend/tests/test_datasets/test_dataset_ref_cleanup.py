"""Usage scans across every project + node-level ref cleanup on delete (#176).

``dataset_usage`` once scanned only non-archived projects, so uninstall's
orphan-dir gate could rmtree a store folder another project still referenced,
and delete left specs — and every node-level ``metadata.datasetRefs`` binding —
pointing at the removed dir.

Archive was removed in #261 and its migration purged every archived row, so the
``include_archived`` widening the fix originally needed is gone. **The property
it protected is not**: a dataset the user still references anywhere must survive
an uninstall elsewhere, and deleting it must strip its refs everywhere. These
cases assert exactly that, now against ordinary projects. If a soft-deleted or
otherwise hidden project state is ever reintroduced, these scans must see it.
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


def test_usage_sees_every_project_that_holds_a_ref(app, db, client, user_and_token):
    user, token = user_and_token
    flow_a = create_project(client, token, name="First consumer")
    flow_b = create_project(client, token, name="Second consumer")
    imported = _import(client, token, name="scoped.csv")
    for flow in (flow_a, flow_b):
        _install(client, token, flow, imported["id"])

    rows = client.get(
        f"/api/datasets/{imported['id']}/usage", headers=auth_headers(token)
    ).get_json()["dataflows"]
    assert {r["dataflowId"] for r in rows} == {flow_a, flow_b}

    # The scan the destructive gates use agrees with the public endpoint. They
    # diverged while Archive existed, which is what made #176 possible.
    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )
    with app.app_context():
        svc = DatasetCatalogService(user)
        assert {u["dataflowId"] for u in svc.dataset_usage(imported["id"])} == {
            flow_a,
            flow_b,
        }


def test_uninstall_keeps_store_dir_referenced_by_another_project(
    app, db, client, user_and_token
):
    """The data-loss regression: uninstalling from one project must not delete
    the store folder another project still references."""
    user, token = user_and_token
    user_key = str(user.id)
    flow_a = create_project(client, token, name="Uninstaller")
    flow_b = create_project(client, token, name="Holder")
    imported = _import(client, token, name="held.csv")
    for flow in (flow_a, flow_b):
        _install(client, token, flow, imported["id"])

    store_dir = dataset_dir(user_key, imported["dirName"])
    assert store_dir.is_dir()

    resp = client.delete(
        f"/api/dataflows/{flow_a}/datasets/{imported['id']}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert store_dir.is_dir(), "folder referenced by another project must survive"


def test_delete_strips_refs_and_node_bindings_everywhere(app, db, client, user_and_token):
    user, token = user_and_token
    user_key = str(user.id)
    flow_a = create_project(client, token, name="First consumer")
    flow_b = create_project(client, token, name="Second consumer")
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

    resp = client.delete(f"/api/datasets/{dataset_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["deleted"] is True
    assert set(body["removedFrom"]) == {flow_a, flow_b}

    with app.app_context():
        updated = project_storage.read_spec(user_key, flow_b)
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
        assert svc.dataset_usage(dataset_id) == []
