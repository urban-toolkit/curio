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

The collections the dataflow lists (``curio_load_collection``) load the same
way: for bob, from alice's store, their files where her store keeps them,
beside his own collections and the shared ones; for erin and carol, none of
alice's.

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
# The collections the dataflow lists
# ---------------------------------------------------------------------------

#: The repository, whose ``datasets/``, ``discovery/`` and ``docs/examples/``
#: the unit tests read.
REPO = Path(__file__).resolve().parents[4]
#: The shipped collection whose index the collections below copy: three noise
#: recordings, kept in a folder of the example storage source.
NOISE = REPO / "datasets" / "data.curio.storage-noise@1"
#: A collection of the shared catalog, which every account reads.
SHARED_COLLECTION = "data.curio.storage-orthos"
#: A service source: the images of a collection added from it are kept in the
#: media folder of the store that holds the collection.
SERVICE = "source.mapillary.imagery@1"


@pytest.fixture()
def shipped_discovery(monkeypatch):
    """The committed Discovery Catalog, pinned as ``test_discovery`` pins it."""
    from utk_curio.backend.app.discovery.infrastructure import storage

    monkeypatch.setenv(storage.ENV_ROOT, str(REPO / "discovery"))


def _a_collection(user, tmp_path, *, source_id: str | None = None) -> str:
    """A collection of *user*'s Data Catalog, added as the Discovery Catalog
    adds one (``StorageAcquire._add_collection``), its index the noise
    recordings'; its id. *source_id* names another source its files are of."""
    import shutil
    import uuid

    from utk_curio.backend.app.datasets.service import DatasetCatalogService

    manifest = json.loads((NOISE / "manifest.json").read_text(encoding="utf-8"))
    source = {"sourceId": source_id} if source_id else {}
    staged = tmp_path / f"index-{uuid.uuid4().hex}.parquet"
    shutil.copyfile(NOISE / "data" / "index.parquet", staged)
    item = DatasetCatalogService(user)._mutations._install_imported_path(
        staged, "index.parquet", "collection", title=manifest["name"],
        discovery_source={**manifest["discoverySource"], **source},
        row_count=manifest["rowCount"], collection={**manifest["collection"], **source},
    )
    return item["id"]


def _load_collections(client, sandbox, token, project_id, *collection_ids) -> dict:
    """Run a node that loads *collection_ids* on the dataflow *project_id*;
    what the sandbox was sent for it."""
    code = "".join(f'    c{i} = curio_load_collection("{c}")\n' for i, c in enumerate(collection_ids))
    resp = client.post("/processPythonCode", data=json.dumps({
        "code": code + "    return c0\n",
        "nodeType": "PYTHON_COMPUTATION",
        "dataflowId": project_id,
        "input": {"path": "", "dataType": "str"},
        "saveOutputDataset": False,
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return sandbox.bodies[-1]


def _rows(body: dict, collection_id: str):
    """The rows a run sent *body* gets from ``curio_load_collection``, built
    by the sandbox's own helper."""
    from utk_curio.sandbox.util.collections import make_collection_helpers

    helpers = make_collection_helpers(
        lambda dataset_id: body["dataset_paths"][dataset_id], body["collections"], body["media_dir"],
    )
    return helpers["curio_load_collection"](collection_id)


@pytest.mark.parametrize("source", ["folder", "service"])
def test_an_editors_run_loads_a_collection_the_owners_dataflow_lists(
    client, flow, sandbox, shipped_discovery, tmp_path, source,
):
    """alice adds a collection to her dataflow. bob's run of a node that loads
    it on her dataflow gets its index from her store and its files: a folder's
    where its source keeps them, a service's where alice's store keeps them.
    The node reads them, and what it derives goes to bob's own media folder."""
    import pandas as pd

    from utk_curio.backend.app.discovery.application import cache_collection
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    alice_key, bob_key = str(flow.people.alice.id), str(flow.people.bob.id)
    collection = _a_collection(flow.people.alice, tmp_path, source_id=SERVICE if source == "service" else None)
    _install(client, flow.tokens["alice"], flow.pid, collection)
    if source == "service":
        # Its first recording came down with it, into alice's media folder.
        first = pd.read_parquet(NOISE / "data" / "index.parquet").iloc[0]
        cached = cache_collection.objects_dir(alice_key, collection) / f"{first.file_id}.{first.ext}"
        cached.write_bytes(b"RIFF")

    body = _load_collections(client, sandbox, flow.tokens["bob"], flow.pid, collection)

    assert set(body["collections"]) == {collection}, f"bob's run resolved the collections {body['collections']}"
    rows = _rows(body, collection)
    readable = [path for path in rows["path"] if path and Path(path).is_file()]
    if source == "folder":
        assert len(readable) == len(rows) == 3, list(rows["path"])
    else:
        assert body["collections"][collection]["objects"] == str(
            cache_collection.objects_dir(alice_key, collection, create=False)
        )
        assert readable == [str(cached)], list(rows["path"])
        assert not (media_dirs.media_work_root(bob_key) / "objects" / collection).exists()
    assert body["media_dir"] == str(media_dirs.media_work_root(bob_key))


def test_an_editors_own_collection_and_a_shared_one_load_beside_the_dataflows(
    client, flow, sandbox, shipped_discovery, tmp_path,
):
    """bob's run on alice's dataflow loads, beside the collection her dataflow
    lists, his own collection and the shared catalog's."""
    listed = _a_collection(flow.people.alice, tmp_path)
    _install(client, flow.tokens["alice"], flow.pid, listed)
    own = _a_collection(flow.people.bob, tmp_path)

    body = _load_collections(client, sandbox, flow.tokens["bob"], flow.pid, listed, own, SHARED_COLLECTION)

    loaded = {listed, own, SHARED_COLLECTION}
    assert set(body["collections"]) == loaded, f"bob's run resolved the collections {body['collections']}"
    assert set(body["dataset_paths"]) == loaded, body["dataset_paths"]
    for collection in loaded:
        rows = _rows(body, collection)
        assert all(path and Path(path).is_file() for path in rows["path"]), (collection, list(rows["path"]))


def test_a_collection_of_the_owners_her_dataflow_does_not_list_stays_hers(
    client, flow, sandbox, shipped_discovery, tmp_path,
):
    """bob's run loads the collection alice's dataflow lists and not another
    of hers that it does not list: neither its files nor its index. alice's
    run on her dataflow loads both."""
    listed = _a_collection(flow.people.alice, tmp_path)
    _install(client, flow.tokens["alice"], flow.pid, listed)
    unlisted = _a_collection(flow.people.alice, tmp_path)

    bobs = _load_collections(client, sandbox, flow.tokens["bob"], flow.pid, listed, unlisted)
    assert set(bobs["collections"]) == {listed}, f"bob's run resolved the collections {bobs['collections']}"
    assert set(bobs["dataset_paths"]) == {listed}, bobs["dataset_paths"]

    alices = _load_collections(client, sandbox, flow.tokens["alice"], flow.pid, listed, unlisted)
    assert set(alices["collections"]) == {listed, unlisted}, alices["collections"]
    assert set(alices["dataset_paths"]) == {listed, unlisted}, alices["dataset_paths"]


def test_a_watcher_and_an_uninvited_account_get_nothing_from_the_owners_store(
    client, flow, sandbox, shipped_discovery, tmp_path,
):
    """One node on alice's dataflow loads the collection her dataflow lists
    and a collection of the runner's own. bob, her editor, reads both. erin,
    an editor she took off her list and so a watcher, and carol, never
    invited, read their own and nothing of alice's store: neither the
    collection nor its index, as in a run that names no dataflow."""
    listed = _a_collection(flow.people.alice, tmp_path)
    _install(client, flow.tokens["alice"], flow.pid, listed)
    owns = {who: _a_collection(getattr(flow.people, who), tmp_path) for who in ("bob", "erin", "carol")}

    read = {}
    for who, own in owns.items():
        body = _load_collections(client, sandbox, flow.tokens[who], flow.pid, listed, own)
        read[who] = {"collections": sorted(body["collections"]), "indexes": sorted(body["dataset_paths"])}

    assert read == {
        "bob": {"collections": sorted([listed, owns["bob"]]), "indexes": sorted([listed, owns["bob"]])},
        "erin": {"collections": [owns["erin"]], "indexes": [owns["erin"]]},
        "carol": {"collections": [owns["carol"]], "indexes": [owns["carol"]]},
    }


def test_an_editors_solve_runs_the_collection_the_owners_dataflow_lists(
    client, flow, shipped_discovery, tmp_path, monkeypatch,
):
    """Solve checks the code an agent writes in bob's chat by running it on a
    thread of its own (``validation.validate_candidate``). That run gets the
    collection alice's dataflow lists, as bob's Play does."""
    from utk_curio.backend.app.agents.domain import validation
    from utk_curio.backend.app.execution import runner

    listed = _a_collection(flow.people.alice, tmp_path)
    _install(client, flow.tokens["alice"], flow.pid, listed)
    sent: dict = {}

    def run_through_node(*_args, **kwargs):
        sent.update(kwargs)
        return {"ok": False, "order": [], "nodes": {}, "infrastructure": "the sandbox is not asked here"}

    monkeypatch.setattr(runner, "run_through_node", run_through_node)
    bob = flow.people.bob
    spec = {"dataflow": {"nodes": [{"id": "photos", "type": "curio.builtin/data-loading", "content": ""}], "edges": []}}
    validation.validate_candidate(
        str(flow.people.alice.id), flow.pid, spec, "photos",
        f'photos = curio_load_collection("{listed}")\nreturn photos',
        exec_user_key=str(bob.id), acting_user=bob,
    )

    assert set(sent.get("collections") or {}) == {listed}, (
        f"Solve's run of bob's node resolved the collections {sent.get('collections')}"
    )


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
