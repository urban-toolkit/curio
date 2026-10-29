"""What an invited editor's runs load on the owner's dataflow.

alice owns a dataflow that lists one dataset of her Data Catalog (the street
trees) and not another (the salaries). bob is an editor she invited, erin was
one until alice took her off the list, and carol was never invited. A run that
names alice's dataflow resolves, for alice and for bob, the datasets the
dataflow lists, from alice's store; with them the shared catalog's datasets and
the runner's own. Nothing else of alice's store is read for anyone but alice:
not a dataset her dataflow does not list, not a file a dataflow's ref names by
a path, and none for erin or carol. An editor reads the owner's dataset and does
not publish it, and an editor's run writes nothing into the editor's store.

Names main lacks are imported inside the tests, so the module imports there and
each test fails on its own.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    store_sandbox_artifact,
)

TREES = b"tree,species\n1,elm\n2,oak\n"
SALARIES = b"name,salary\nalice,100\n"
BUS_STOPS = b"stop,routes\nClark,22\n"
LIGHTS = b"light,watts\n1,40\n"
SECRET = b"token\nnot-a-real-secret-for-tests\n"
HUB_ID = "data.test.street-lights"
TOKENS = {"bob": "bob-token-for-tests", "carol": "carol-token-for-tests", "erin": "erin-token-for-tests"}


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


def _import(client, token, name, body):
    resp = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(body), name)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _install(client, token, project_id, dataset_id, source_item=None):
    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": dataset_id, **({"sourceItem": source_item} if source_item else {})}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, which lists her street trees and not her salaries,
    with bob invited to edit it and erin invited, then taken off."""
    from utk_curio.backend.app.projects import access

    alice, alice_token = user_and_token
    people = SimpleNamespace(alice=alice, bob=_account(db, "bob"), carol=_account(db, "carol"),
                             erin=_account(db, "erin"))
    pid = create_project(client, alice_token, name="Street trees")
    listed = _import(client, alice_token, "trees.csv", TREES)
    _install(client, alice_token, pid, listed["id"])
    unlisted = _import(client, alice_token, "salaries.csv", SALARIES)
    access.add_editor(alice, pid, "bob")
    access.add_editor(alice, pid, "erin")
    access.remove_editor(alice, pid, people.erin.id)
    return SimpleNamespace(
        pid=pid, listed=listed["id"], unlisted=unlisted, people=people,
        tokens={"alice": alice_token, **TOKENS},
    )


@pytest.fixture()
def sandbox(monkeypatch):
    """The sandbox, answering every run with *reply*; each run's body, in order."""
    bodies: list = []
    state = SimpleNamespace(bodies=bodies, reply={"stdout": "", "stderr": "", "output": {}})

    def fake_call(method, path, **kwargs):
        bodies.append(json.loads(kwargs["data"]))
        resp = MagicMock()
        resp.json.return_value = state.reply
        return resp

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake_call)
    return state


def _run(client, token, project_id, *dataset_ids, **extra):
    """Run a node that loads *dataset_ids* on the dataflow *project_id*."""
    code = "".join(f'    d{i} = curio_load_data("{dataset_id}")\n' for i, dataset_id in enumerate(dataset_ids))
    resp = client.post("/processPythonCode", data=json.dumps({
        "code": code + "    return d0\n",
        "nodeType": "PYTHON_COMPUTATION",
        "dataflowId": project_id,
        "input": {"path": "", "dataType": "str"},
        "saveOutputDataset": False,
        **extra,
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp


def _paths(sandbox) -> dict:
    return sandbox.bodies[-1]["dataset_paths"]


def _hub_dataset(tmp_path, monkeypatch) -> Path:
    """A dataset of the shared catalog, which every account browses; its file."""
    from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest

    catalog = tmp_path / "catalog"
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    folder = catalog / f"{HUB_ID}@1"
    (folder / "data").mkdir(parents=True)
    data_file = folder / "data" / "lights.csv"
    data_file.write_bytes(LIGHTS)
    write_manifest(DatasetManifest(
        id=HUB_ID, name="Street lights", version="1.0.0", format="csv", description="",
        publisher="Curio", license="MIT", tags=["lights"], data_file="data/lights.csv", major=1,
    ), folder)
    return data_file


# ---------------------------------------------------------------------------
# Who loads the datasets the dataflow lists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("who", ["alice", "bob", "erin", "carol"],
                         ids=["owner", "editor", "removed-editor", "uninvited"])
def test_a_run_on_the_owners_dataflow_loads_the_dataset_it_lists_for_the_owner_and_an_editor(
    client, flow, sandbox, who,
):
    """alice's run and bob's load the street trees from alice's store, with
    how the sandbox reads them. erin, whom alice took off her editors, and
    carol, never invited, get nothing of alice's store, as before."""
    _run(client, flow.tokens[who], flow.pid, flow.listed)
    paths, formats = _paths(sandbox), sandbox.bodies[-1]["dataset_formats"]
    if who in ("alice", "bob"):
        assert set(paths) == {flow.listed}, f"{who}'s run resolved {paths}"
        assert Path(paths[flow.listed]).read_bytes() == TREES
        assert formats == {flow.listed: {"format": "csv"}}
    else:
        assert paths == {}, f"{who}, who does not edit the dataflow, resolved {paths}"
        assert formats == {}


def test_an_editors_own_dataset_loads_on_the_owners_dataflow_beside_a_shared_one(
    client, flow, sandbox, tmp_path, monkeypatch,
):
    """bob's own bus stops, which his dataset index resolves, and the shared
    catalog's street lights, which only the listing resolves, both load in his
    run on alice's dataflow."""
    hub_file = _hub_dataset(tmp_path, monkeypatch)
    own = _import(client, flow.tokens["bob"], "bus_stops.csv", BUS_STOPS)

    _run(client, flow.tokens["bob"], flow.pid, own["id"], HUB_ID)

    paths = _paths(sandbox)
    assert set(paths) == {own["id"], HUB_ID}, f"bob's run resolved {paths}"
    assert Path(paths[own["id"]]).read_bytes() == BUS_STOPS
    assert Path(paths[HUB_ID]).resolve() == hub_file.resolve()


def test_a_dataset_of_the_owners_catalog_her_dataflow_does_not_list_stays_hers(client, flow, sandbox):
    """bob's run loads the street trees, which alice's dataflow lists, and not
    her salaries, by id or through a ref of the dataflow that names their file
    by its path. His listing of the dataflow lists neither, and he cannot
    preview them. alice still reads both."""
    from utk_curio.backend.app.datasets.repositories.installed import InstalledDatasetRepository

    salaries_file = flow.unlisted["path"]
    # A ref with no folder, which names the salaries' file by its path.
    InstalledDatasetRepository(flow.people.alice).mutate_refs(flow.pid, lambda refs: [*refs, {
        "datasetId": "imported.xby-path", "title": "Salaries by path", "origin": "imported",
        "path": salaries_file, "format": "csv",
    }])
    bob = flow.tokens["bob"]

    _run(client, bob, flow.pid, flow.listed, flow.unlisted["id"], "imported.xby-path")
    paths = _paths(sandbox)
    assert set(paths) == {flow.listed}, f"bob's run resolved {paths}"

    listed = client.get(f"/api/datasets/catalog?dataflowId={flow.pid}", headers=auth_headers(bob))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    items = {item["id"]: item for item in listed.get_json()["items"]}
    assert flow.listed in items and flow.unlisted["id"] not in items
    assert items["imported.xby-path"]["path"] is None
    assert salaries_file not in listed.get_data(as_text=True)
    unlisted = client.get(f"/api/datasets/{flow.unlisted['id']}/preview?dataflowId={flow.pid}",
                          headers=auth_headers(bob))
    assert unlisted.status_code == 404, unlisted.get_data(as_text=True)[:200]
    by_path = client.get(f"/api/datasets/imported.xby-path/preview?dataflowId={flow.pid}", headers=auth_headers(bob))
    assert by_path.status_code == 200 and by_path.get_json()["rows"] == [], by_path.get_data(as_text=True)[:200]

    _run(client, flow.tokens["alice"], flow.pid, flow.unlisted["id"], "imported.xby-path")
    assert set(_paths(sandbox)) == {flow.unlisted["id"], "imported.xby-path"}


def test_an_editor_reads_the_owners_dataset_and_does_not_publish_it(client, flow, sandbox, tmp_path, monkeypatch):
    """bob's run loads the street trees; his Publish of them is refused before
    anything reaches the shared catalog."""
    catalog = tmp_path / "catalog"
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    _run(client, flow.tokens["bob"], flow.pid, flow.listed)
    assert set(_paths(sandbox)) == {flow.listed}

    from utk_curio.backend.app.datasets.application.mutations import OWNERS_DATASET_PUBLISH_REFUSAL

    resp = client.post("/api/datasets/publish", data=json.dumps({
        "datasetId": flow.listed, "dataflowId": flow.pid,
    }), headers=auth_headers(flow.tokens["bob"]))
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()["error"] == OWNERS_DATASET_PUBLISH_REFUSAL
    assert not (catalog / f"{flow.listed}@1").exists()
    assert not any(TREES == path.read_bytes() for path in catalog.rglob("*") if path.is_file())


def test_an_editors_run_of_the_owners_dataflow_saves_nothing_in_the_editors_store(client, flow, sandbox):
    """A run that saves its output joins the account's Data Catalog and the
    dataflow's runtime journal: alice's does, in her store. bob's run of the
    same node on her dataflow saves neither into his store, as a run that
    names no dataflow."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets
    from utk_curio.backend.app.projects import storage as projects_storage

    artifact = store_sandbox_artifact({"trees": 2})
    sandbox.reply = {"stdout": "", "stderr": "", "output": {"path": artifact, "dataType": "dict"}}

    owners = _run(client, flow.tokens["alice"], flow.pid, flow.listed, nodeId="count", saveOutputDataset=True)
    assert (owners.get_json().get("installedDataset") or {}).get("id"), owners.get_json()

    editors = _run(client, flow.tokens["bob"], flow.pid, flow.listed, nodeId="count", saveOutputDataset=True)
    bob_key = str(flow.people.bob.id)
    assert editors.get_json().get("installedDataset") is None, editors.get_json()
    assert [folder.name for folder in list_user_datasets(bob_key)] == []
    assert not projects_storage.project_dir(bob_key, flow.pid).exists()


# ---------------------------------------------------------------------------
# Also here: a dataflow's ref that names a file by its path
# ---------------------------------------------------------------------------

def test_a_ref_naming_a_file_outside_the_data_catalog_is_neither_listed_nor_published(
    client, user_and_token, sandbox, tmp_path, monkeypatch,
):
    """A dataflow's ref with no folder names its file by the path its spec
    carries, which a request may have written (here Add to project's item).
    Publishing it copied that file, wherever it was, into the shared catalog,
    where any account could download it. The file stays where it is: not
    published, not listed, not read by a run."""
    _, token = user_and_token
    catalog = tmp_path / "catalog"
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    secret = tmp_path / "outside" / "secret.csv"
    secret.parent.mkdir()
    secret.write_bytes(SECRET)
    pid = create_project(client, token, name="Outside")
    _install(client, token, pid, "imported.xoutside", source_item={
        "id": "imported.xoutside", "title": "Outside", "origin": "imported", "path": str(secret), "format": "csv",
    })

    resp = client.post("/api/datasets/publish", data=json.dumps({
        "datasetId": "imported.xoutside", "dataflowId": pid,
    }), headers=auth_headers(token))
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert not any(SECRET == path.read_bytes() for path in catalog.rglob("*") if path.is_file())

    listed = client.get(f"/api/datasets/catalog?dataflowId={pid}", headers=auth_headers(token))
    item = next(i for i in listed.get_json()["items"] if i["id"] == "imported.xoutside")
    assert item["path"] is None
    assert str(secret) not in listed.get_data(as_text=True)

    _run(client, token, pid, "imported.xoutside")
    assert _paths(sandbox) == {}
