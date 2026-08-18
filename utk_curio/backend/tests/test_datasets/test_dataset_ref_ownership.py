"""``spec.dataflow.datasets`` is backend-owned on update (dev/81 Fix 2).

A canvas save (client ``update_project`` with a spec) can neither resurrect an
uninstalled ref nor drop a fresh install: the on-disk section overwrites
whatever the client sent. The client-sent section still seeds ``create()``
("Save a copy" / trill import), and the dataset endpoints write the section
through a dedicated writer that touches nothing else in the spec.
"""

from __future__ import annotations

import io
import json

import pytest

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


def _install(client, token, project_id, dataset_id):
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _uninstall(client, token, project_id, dataset_id):
    resp = client.delete(
        f"/api/dataflows/{project_id}/datasets/{dataset_id}",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _get_project(client, token, project_id):
    resp = client.get(f"/api/projects/{project_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _spec_refs(client, token, project_id):
    spec = _get_project(client, token, project_id)["spec"] or {}
    return (spec.get("dataflow") or {}).get("datasets") or []


def _client_save(client, token, project_id, spec):
    """A canvas-style save: PUT the full spec, as TrillGenerator output would."""
    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"spec": spec}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_client_save_cannot_resurrect_uninstalled_ref(client, user_and_token):
    """Uninstall in one tab, save a stale mirror in another: stays removed."""
    _, token = user_and_token
    project_id = create_project(client, token, name="No resurrection")
    imported = _import(client, token)
    _install(client, token, project_id, imported["id"])
    stale_refs = _spec_refs(client, token, project_id)
    assert stale_refs, "precondition: install persisted a ref"

    _uninstall(client, token, project_id, imported["id"])

    # The other tab's save still carries the pre-uninstall mirror.
    detail = _client_save(client, token, project_id, {
        "dataflow": {"name": "No resurrection", "nodes": [], "edges": [],
                     "datasets": stale_refs},
    })
    assert _spec_refs(client, token, project_id) == []
    # The save's own response already reflects the authoritative section, so
    # the client mirror re-syncs from it.
    assert ((detail["spec"] or {}).get("dataflow") or {}).get("datasets") == []


def test_client_save_cannot_drop_fresh_install(client, user_and_token):
    """Install in one tab, save a mirror that never saw it: stays installed."""
    _, token = user_and_token
    project_id = create_project(client, token, name="No drop")
    imported = _import(client, token, name="pois.csv")
    _install(client, token, project_id, imported["id"])

    # A save with no datasets section at all…
    _client_save(client, token, project_id, {
        "dataflow": {"name": "No drop", "nodes": [], "edges": []},
    })
    assert [r["datasetId"] for r in _spec_refs(client, token, project_id)] == [imported["id"]]

    # …and a save with an explicitly empty section: both are inert on update.
    _client_save(client, token, project_id, {
        "dataflow": {"name": "No drop", "nodes": [], "edges": [], "datasets": []},
    })
    assert [r["datasetId"] for r in _spec_refs(client, token, project_id)] == [imported["id"]]


def test_outputs_only_update_leaves_refs_untouched(client, user_and_token):
    """An outputs-only PUT (no spec) never touches the section."""
    _, token = user_and_token
    project_id = create_project(client, token, name="Outputs only")
    imported = _import(client, token, name="trees.csv")
    _install(client, token, project_id, imported["id"])

    resp = client.put(
        f"/api/projects/{project_id}",
        data=json.dumps({"outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert [r["datasetId"] for r in _spec_refs(client, token, project_id)] == [imported["id"]]


def test_create_seeds_client_datasets_section(client, user_and_token):
    """``create()`` accepts the client section — the Save-a-copy / import seed."""
    _, token = user_and_token
    imported = _import(client, token, name="lots.csv")
    seed_ref = {
        "datasetId": imported["id"],
        "dirName": imported["dirName"],
        "origin": "imported",
        "producerNodeId": None,
        "consumerNodeIds": [],
        "installedAt": "2026-08-18T00:00:00+00:00",
    }
    resp = client.post(
        "/api/projects",
        data=json.dumps({
            "name": "Copied dataflow",
            "spec": {"dataflow": {"name": "Copied dataflow", "nodes": [], "edges": [],
                                  "datasets": [seed_ref]}},
            "outputs": [],
        }),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    project_id = resp.get_json()["id"]

    refs = _spec_refs(client, token, project_id)
    assert [r["datasetId"] for r in refs] == [imported["id"]]
    listed = client.get(
        f"/api/datasets/catalog?dataflowId={project_id}&includeHub=false",
        headers=auth_headers(token),
    ).get_json()["items"]
    item = next(i for i in listed if i["id"] == imported["id"])
    assert item.get("installed") is True


def test_section_writer_touches_only_datasets(client, user_and_token):
    """Install replaces the datasets section; every other spec section is
    byte-identical, and the project row's timestamp does not go backwards."""
    _, token = user_and_token
    spec = {
        "dataflow": {
            "name": "Writer isolation",
            "nodes": [{"id": "n1", "type": "curio.builtin/df-compute", "data": {"x": 1}}],
            "edges": [{"id": "e1", "source": "n1", "target": "n1"}],
            "agents": [{"agentId": "it.urbanlab/example@1"}],
        },
    }
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": "Writer isolation", "spec": spec, "outputs": []}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    project_id = resp.get_json()["id"]
    before = _get_project(client, token, project_id)
    before_df = dict(before["spec"]["dataflow"])
    before_updated = before["project"]["updated_at"]

    imported = _import(client, token, name="grid.csv")
    _install(client, token, project_id, imported["id"])

    after = _get_project(client, token, project_id)
    after_df = dict(after["spec"]["dataflow"])
    datasets = after_df.pop("datasets")
    before_df.pop("datasets", None)
    assert after_df == before_df
    assert [r["datasetId"] for r in datasets] == [imported["id"]]
    assert after["project"]["updated_at"] >= before_updated


def test_replace_refs_404s_when_spec_is_missing(client, user_and_token, app):
    """The section writer surfaces a catalog 404 instead of minting a spec."""
    from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError
    from utk_curio.backend.app.datasets.repositories.installed import (
        InstalledDatasetRepository,
    )
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = create_project(client, token, name="Spec goes missing")
    spec_path = storage.project_dir(_user_dir_key(user), project_id) / "spec.trill.json"
    spec_path.unlink()

    with pytest.raises(DatasetCatalogError) as excinfo:
        InstalledDatasetRepository(user).replace_refs(project_id, [])
    assert excinfo.value.status == 404
