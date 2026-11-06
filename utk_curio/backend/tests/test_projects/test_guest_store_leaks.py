"""What one hosted guest does in the Data Catalog reaches no other guest.

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account. Every guest reads that account's dataset store,
and every guest's next dataflow starts with its list of datasets for all
projects. These tests sign two visitors, A and B, in to that account, as
``test_guest_copy_leaks.py`` does, and have A act in the Data Catalog:

- A's delete of a dataset, its Add to all projects and its Remove from all
  projects are refused (``capabilities.catalog_entry_refusal``), as a hosted
  guest's import or removal of an agent is;
- a node's output A adds to an example is saved under A's own copy of it
  (``projects/visitor_copies.py``), listed for A alone, and dropped with the
  copy when the server starts.

Each ends with the example's spec and manifest, and every file of the guest
dataset store, byte for byte as they were. Without ``--deploy`` the shared
guest is the one local user, which deletes datasets and adds them to all
projects as any account does.
"""
from __future__ import annotations

import base64
import json

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_projects.test_guest_copy_leaks import (  # noqa: F401  (fixtures)
    SHIPPED,
    VISITOR_A,
    VISITOR_B,
    _computed_in_the_store,
    _copy_of,
    _digests,
    _in_the_dataflow,
    _listed_as_installed,
    _open,
    _play,
    app,
    datasets,
    example,
    sandbox,
)

#: What a hosted guest is told when it would *action* in the Data Catalog.
REFUSAL = (
    "Guests on this Curio cannot {action}, because every guest shares one account. "
    "Sign in with an account to {action}."
)


def _copy_made(token: str, project_id: str) -> bool:
    """Whether the visitor signed in as *token* has a copy of *project_id*."""
    return (storage.project_dir(GUEST_KEY, _copy_of(token, project_id)) / storage.SPEC_FILE).is_file()


def _for_all_projects() -> bytes | None:
    """The guest account's list of datasets for all projects, which every
    guest's next dataflow starts with: its file's bytes, None while there is
    none."""
    from utk_curio.backend.app.common.user_storage import user_key_segment, users_base

    path = users_base() / user_key_segment(GUEST_KEY) / "default-datasets.json"
    return path.read_bytes() if path.is_file() else None


@pytest.fixture()
def in_the_example(client, example, datasets, monkeypatch):
    """The upload of ``datasets``, which the example lists too: the local
    guest adds it, as it added the dataset the example ships with, and each
    visitor opens the example again before anything is measured. Its id."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": datasets}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    for token in (VISITOR_A, VISITOR_B):
        _open(client, token, example)
    return datasets


@pytest.fixture()
def in_all_projects(client, example, datasets, monkeypatch):
    """The upload of ``datasets``, which the local guest adds to all
    projects: the account's list for all projects names it, and the example
    lists it. Each visitor opens the example again before anything is
    measured. Its id."""
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    added = client.post("/api/datasets/defaults", data=json.dumps({"datasetId": datasets}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert added.get_json()["datasets"] == [datasets]
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    for token in (VISITOR_A, VISITOR_B):
        _open(client, token, example)
    return datasets


def test_a_hosted_guests_delete_of_a_dataset_is_refused(client, example, in_the_example):
    uploaded = in_the_example
    before = _digests(example)

    resp = client.delete(f"/api/datasets/{uploaded}", headers=auth_headers(VISITOR_A))

    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == REFUSAL.format(action="delete datasets")
    # The upload stays in the store every guest reads, and in the example.
    for token in (VISITOR_A, VISITOR_B):
        assert _in_the_dataflow(client, token, example) == [SHIPPED, uploaded]
        assert _listed_as_installed(client, token, example, uploaded)
    assert not _copy_made(VISITOR_A, example)
    assert _digests(example) == before


def test_a_hosted_guests_add_to_all_projects_is_refused(client, example, datasets):
    uploaded = datasets
    before, listed = _digests(example), _for_all_projects()

    resp = client.post("/api/datasets/defaults", data=json.dumps({"datasetId": uploaded}),
                       headers=auth_headers(VISITOR_A))

    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == REFUSAL.format(action="add datasets to all projects")
    # The list every guest's next dataflow starts with is as it was, A has
    # no copy of the example, and every guest opens it as it ships.
    assert _for_all_projects() == listed
    assert not _copy_made(VISITOR_A, example)
    for token in (VISITOR_A, VISITOR_B):
        assert _in_the_dataflow(client, token, example) == [SHIPPED]
    assert _digests(example) == before


def test_a_hosted_guests_remove_from_all_projects_is_refused(client, example, in_all_projects):
    uploaded = in_all_projects
    before, listed = _digests(example), _for_all_projects()

    resp = client.delete(f"/api/datasets/defaults/{uploaded}", headers=auth_headers(VISITOR_A))

    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == REFUSAL.format(action="remove datasets from all projects")
    assert _for_all_projects() == listed
    assert not _copy_made(VISITOR_A, example)
    for token in (VISITOR_A, VISITOR_B):
        assert _in_the_dataflow(client, token, example) == [SHIPPED, uploaded]
    assert _digests(example) == before


def _live(node: str, made: str) -> str:
    """The canvas's output of *node*, the artifact *made*, as a listing's
    ``liveOutputs`` carries it."""
    return base64.b64encode(json.dumps([{"node_id": node, "filename": made, "data_type": "dataframe"}]).encode()).decode()


def _listing(client, token, **query) -> list[dict]:
    """The Data Catalog's datasets as *token*'s visitor lists them with
    *query*."""
    resp = client.get("/api/datasets/catalog", query_string={"includeHub": "true", **query},
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["items"]


def _listings_of(example: str) -> list[dict]:
    """What each listing a visitor's canvas of *example* reads asks: the
    Data Catalog page's, the drawer's, and the dataset palette's, whose
    "Saved outputs" are the dataflow's outputs among its datasets."""
    return [{}, {"dataflowId": example, "groupOsm": "true"}, {"dataflowId": example, "sort": "recent"}]


def test_a_hosted_guests_added_output_is_theirs_alone(client, example, sandbox):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id
    from utk_curio.backend.app.projects import visitor_copies

    # Each visitor's Data Catalog lists the store once, as their canvases do,
    # before anything is measured.
    for token in (VISITOR_A, VISITOR_B):
        _listing(client, token, dataflowId=example)
    before = _digests(example)
    made = sandbox["artifacts"]["a"]
    _play(client, VISITOR_A, example, "a")
    # A adds a's output to the dataflow from the Data Catalog, as the
    # listing gives it while A's canvas holds it.
    live = next(item for item in _listing(client, VISITOR_A, dataflowId=example, liveOutputs=_live("a", made))
                if item.get("producerNodeId") == "a")
    added = client.post(f"/api/dataflows/{example}/datasets/install",
                        data=json.dumps({"datasetId": live["id"], "sourceItem": live, "nodeTitle": "a"}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)

    # It is saved under A's own copy of the example, which lists it.
    mine = computed_dataset_id("a", _copy_of(VISITOR_A, example))
    assert added.get_json()["id"] == mine
    assert _computed_in_the_store() == [f"{mine}@1"]
    assert _in_the_dataflow(client, VISITOR_A, example) == [mine]
    assert _listed_as_installed(client, VISITOR_A, example, mine)
    assert mine in [item["id"] for item in _listing(client, VISITOR_A)]
    # B's canvas, Data Catalog page, drawer and palette name none of it, and
    # its details are not B's to read.
    assert _in_the_dataflow(client, VISITOR_B, example) == []
    for query in _listings_of(example):
        outputs = [item["id"] for item in _listing(client, VISITOR_B, **query) if item["id"].startswith("computed.")]
        assert outputs == [], query
    shown = client.get(f"/api/datasets/{mine}", query_string={"dataflowId": example}, headers=auth_headers(VISITOR_B))
    assert shown.status_code == 404, shown.get_data(as_text=True)

    # It goes with A's copy when the server starts.
    assert visitor_copies.drop_all() == 1
    assert _computed_in_the_store() == []
    assert _digests(example) == before


def test_without_deploy_the_local_guest_still_deletes_and_adds_to_all_projects(
    client, example, datasets, monkeypatch,
):
    """Without ``--deploy`` the shared guest is the one local user, whose Data
    Catalog is its own."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    uploaded = datasets
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)

    added = client.post("/api/datasets/defaults", data=json.dumps({"datasetId": uploaded}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)
    assert added.get_json()["datasets"] == [uploaded]
    assert _in_the_dataflow(client, VISITOR_A, example) == [SHIPPED, uploaded]

    deleted = client.delete(f"/api/datasets/{uploaded}", headers=auth_headers(VISITOR_A))
    assert deleted.status_code == 200, deleted.get_data(as_text=True)
    assert (deleted.get_json()["deleted"], deleted.get_json()["removedFrom"]) == (True, [example])
    assert _in_the_dataflow(client, VISITOR_A, example) == [SHIPPED]
    assert [p.name for p in list_user_datasets(GUEST_KEY) if p.name.split("@")[0] == uploaded] == []

    removed = client.delete(f"/api/datasets/defaults/{uploaded}", headers=auth_headers(VISITOR_A))
    assert removed.status_code == 200, removed.get_data(as_text=True)
    assert removed.get_json()["datasets"] == []
