"""An invited editor's own package or model reaches the owner's dataflow through her review.

alice owns a dataflow. bob is an editor she invited, whose store holds a
package of his own, ``test.bus-counts@1`` (one node, and the module it imports),
and a model of his own, ``test.bus-model@1`` (its weights in his store), each
installed as an import installs one; carol is signed in and only has the
dataflow's link. bob's Add to project of his package, and his drop of its card
on alice's canvas, each ask alice: a request in her review, a
``package.install`` of ``agentInstalls.json`` as an install an agent asks for
is, which only she applies or dismisses. Her review shows the package as her
Apply would install it: its name, version, publisher, what it may do, its
libraries and their conflicts with hers. Her Apply checks the package's files
against the record its install wrote, copies it from his store into hers, a
model with its weights, installs its libraries under her account and adds it
to her dataflow as her change, so bob's runs then read it from her store. A
package of the shared catalog is installed from the catalog for her. A package
whose files changed since its install, or whose libraries conflict with hers,
is refused, with the reason, and waits in her review. Her Dismiss leaves
nothing behind. carol cannot ask.

Each test goes through the routes alone, so on a base without them it fails at
its first assertion on what the base does not do.
"""
from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BUS = "test.bus-counts"
BUS_DIR = f"{BUS}@1"
BUS_NODE = f"{BUS}/count@1"
MODEL = "test.bus-model"
MODEL_DIR = f"{MODEL}@1"
WEIGHTS = b"bus-model-weights"
SHARED = "test.shared-counts"
SHARED_DIR = f"{SHARED}@1"
TOKENS = {"bob": "bob-token-for-tests", "carol": "carol-token-for-tests"}
REQUESTS_FILE = "dataset-requests.json"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=f"{username.title()} Test", email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


def _manifest(package_id: str, name: str, *, python: dict | None = None, model: bool = False) -> dict:
    manifest = {
        "id": package_id, "version": "1.0.0", "name": name, "publisher": "Bob Test", "license": "MIT",
        "description": f"{name}, of a test", "compatibility": {"major": 1}, "permissions": [],
        "dependencies": {"packages": {}, "python": python or {}, "js": {}},
        "templates": [{
            "id": "count", "label": "Count", "category": "computation", "engine": "python", "editor": "code",
            "hasCode": True, "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/count.py",
        }],
    }
    if model:
        manifest["kind"] = "model"
        manifest["templates"] = [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                                  "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["JSON"]}]}]
        manifest["model"] = {"type": "node-regression", "runtime": "onnx", "entry": "models/w.onnx",
                             "labels": [], "license": "MIT", "sizeBytes": len(WEIGHTS)}
    return manifest


def _archive(manifest: dict, files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _bus_counts(python: dict | None = None) -> bytes:
    return _archive(_manifest(BUS, "Bus counts", python=python), {
        "sources/count.py": "return 1\n",
        "sources/bus_helpers.py": "def count():\n    return 3\n",
    })


def _install(user_key: str, archive: bytes) -> None:
    """Install *archive* into the store *user_key*, as an import of it does."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive

    install_package_from_archive(user_key, archive)


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, with bob invited to edit it and carol, signed in, only
    its link; bob's package and model, which only his store holds."""
    from utk_curio.backend.app.projects import access

    alice, alice_token = user_and_token
    bob, carol = _account(db, "bob"), _account(db, "carol")
    resp = client.post("/api/projects", json={
        "name": "Bus plan", "spec": {"dataflow": {"name": "Bus plan", "nodes": [], "edges": []}}, "outputs": [],
    }, headers=_auth(alice_token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    pid = resp.get_json()["id"]
    access.add_editor(alice, pid, "bob")
    _install(_key(bob), _bus_counts())
    _install(_key(bob), _archive(_manifest(MODEL, "Bus model", model=True), {"models/w.onnx": WEIGHTS}))
    return SimpleNamespace(pid=pid, alice=alice, bob=bob, carol=carol,
                           tokens={"alice": alice_token, **TOKENS})


@pytest.fixture()
def sandbox(monkeypatch):
    """The sandbox, answering every run at once; each run's body, in order."""
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import node_exec

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    state = SimpleNamespace(bodies=[])

    def fake_call(method, path, **kwargs):
        state.bodies.append(json.loads(kwargs["data"]))
        resp = MagicMock()
        resp.json.return_value = {"stdout": "", "stderr": "", "output": {"path": "art", "dataType": "str"}}
        return resp

    monkeypatch.setattr(node_exec, "sandbox_request", fake_call)
    return state


# ---------------------------------------------------------------------------
# Requests, reviews and runs, through the routes
# ---------------------------------------------------------------------------

def _ask(client, flow, who: str, dir_name: str, **body):
    return client.post(f"/api/dataflows/{flow.pid}/packages/requests",
                       json={"dirName": dir_name, **body}, headers=_auth(flow.tokens[who]))


def _asked(client, flow, who: str, dir_name: str, **body) -> dict:
    """*who*'s request for *dir_name*, which the route made."""
    resp = _ask(client, flow, who, dir_name, **body)
    assert resp.status_code == 201, f"{who}'s request answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    answer = resp.get_json()
    assert answer["requested"] is True, answer
    return answer["request"]


def _review(client, flow, who: str = "alice") -> list:
    """The package requests alice's review shows, as *who* reads them."""
    resp = client.get(f"/api/dataflows/{flow.pid}/packages/requests", headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, f"{who}'s review answered {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    return resp.get_json()["requests"]


def _apply(client, flow, who: str, request_id: str):
    return client.post(f"/api/dataflows/{flow.pid}/packages/requests/{request_id}/apply",
                       headers=_auth(flow.tokens[who]))


def _dismiss(client, flow, who: str, request_id: str):
    return client.delete(f"/api/dataflows/{flow.pid}/packages/requests/{request_id}",
                         headers=_auth(flow.tokens[who]))


def _store(user) -> set:
    """The packages *user*'s store holds, by folder."""
    from utk_curio.backend.app.packages.repositories.store import list_user_packages

    return {folder.name for folder in list_user_packages(_key(user))}


def _lockfile(flow) -> list:
    from utk_curio.backend.app.projects import storage as projects_storage

    return (projects_storage.read_spec(_key(flow.alice), flow.pid) or {})["dataflow"].get("packages") or []


def _hers(flow) -> tuple:
    """What a request must not change: alice's store and her dataflow's lockfile."""
    return _store(flow.alice), _lockfile(flow)


def _sources(user, dir_name: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return str(package_dir(_key(user), dir_name) / "sources")


def _folder(user, dir_name: str):
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return package_dir(_key(user), dir_name)


def _play(client, flow, sandbox, who: str, node_type: str, code: str) -> dict:
    """*who*'s play of a node of *node_type* on alice's dataflow: what it sent the sandbox."""
    sent = len(sandbox.bodies)
    resp = client.post("/processPythonCode", json={
        "code": code, "nodeType": node_type, "dataflowId": flow.pid,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(sandbox.bodies) == sent + 1, "the play reached no sandbox"
    return sandbox.bodies[-1]


def _modules(client, flow, sandbox, who: str) -> dict | None:
    """The modules *who*'s play of a node of bob's package is handed."""
    return _play(client, flow, sandbox, who, BUS_NODE, "from bus_helpers import count\nreturn count()\n").get(
        "package_modules")


# ---------------------------------------------------------------------------
# Each way bob brings his package in asks alice, and installs nothing of hers
# ---------------------------------------------------------------------------

def test_an_editors_add_and_drop_of_his_own_package_ask_the_owner_once_and_install_nothing_of_hers(
    client, flow, sandbox,
):
    """bob's Add to project of his package asks alice, on the card an agent's
    package install has: its name, version, publisher and what it may do. A
    drop of its card onto her canvas names the node it made in the same
    request. Her store and her lockfile are as they were, and his play of the
    node still runs his own copy."""
    before = _hers(flow)

    request = _asked(client, flow, "bob", BUS_DIR, add=True)
    again = _asked(client, flow, "bob", BUS_DIR, nodeId="bus-node")

    assert request["tool"] == "package.install", request
    assert (request["dirName"], request["packageName"], request["version"], request["publisher"],
            request["permissions"], request["packageKind"], request["shared"]) == (
        BUS_DIR, "Bus counts", "1.0.0", "Bob Test", [], "node", False), request
    assert request["summary"] == "Add package · Bus counts"
    assert request["preview"] == "Bus counts · v1.0.0 · Bob Test · from Bob Test's Node Catalog"
    assert request["by"] == {"kind": "person", "account": str(flow.bob.id), "name": "Bob Test"}
    assert "store" not in request, "the request shows which store it copies from"
    assert again["proposalId"] == request["proposalId"] and again["nodeIds"] == ["bus-node"]
    assert [r["proposalId"] for r in _review(client, flow)] == [request["proposalId"]]
    assert [r["proposalId"] for r in _review(client, flow, "bob")] == [request["proposalId"]]
    assert _hers(flow) == before, "bob's ask wrote to alice's store or her lockfile"
    assert _modules(client, flow, sandbox, "bob") == {"root": _sources(flow.bob, BUS_DIR), "names": ["bus_helpers"]}


def test_the_owners_review_shows_his_package_as_her_apply_would_install_it(client, flow):
    """alice's review of bob's request reads his package where her Apply would
    take it from: its manifest, and no conflict with her packages. bob's read
    of it is refused, as his Apply is."""
    request = _asked(client, flow, "bob", BUS_DIR, add=True)
    path = f"/api/dataflows/{flow.pid}/packages/requests/{request['proposalId']}/review"

    resp = client.get(path, headers=_auth(flow.tokens["alice"]))
    refused = client.get(path, headers=_auth(flow.tokens["bob"]))

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    review = resp.get_json()
    package = review["package"]
    assert (package["dirName"], package["name"], package["version"], package["publisher"], package["permissions"]) == (
        BUS_DIR, "Bus counts", "1.0.0", "Bob Test", []), package
    assert review["conflicts"] == []
    assert refused.status_code == 403, refused.get_data(as_text=True)[:300]


# ---------------------------------------------------------------------------
# alice's Apply
# ---------------------------------------------------------------------------

def test_her_apply_copies_his_package_into_her_store_installs_its_libraries_and_adds_it_as_her_change(
    client, flow, sandbox, monkeypatch,
):
    """alice applies bob's request: his package is copied into her store, its
    files the ones his install recorded, its libraries installed under her
    account, and it is added to her lockfile as her change. Her play and his of
    its node then run her copy, his even once his own copy is gone."""
    from utk_curio.backend.app.collaboration import owner_uses
    from utk_curio.backend.app.packages.application import provisioning
    from utk_curio.backend.app.packages.application.store_install import remove_package

    provisioned: list = []
    real = provisioning.provision_python_deps

    def recorded(user_key, dir_name, manifest):
        provisioned.append((user_key, dir_name))
        return real(user_key, dir_name, manifest)

    monkeypatch.setattr(provisioning, "provision_python_deps", recorded)
    request = _asked(client, flow, "bob", BUS_DIR, nodeId="bus-node")

    resp = _apply(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    answer = resp.get_json()
    assert answer["status"] == "applied" and answer["installedPackage"]["dirName"] == BUS_DIR, answer
    assert BUS_DIR in _store(flow.alice)
    # Imported here, past the asks: a base without it fails at the first of them.
    from utk_curio.backend.app.packages.repositories.archive import integrity_mismatch

    assert integrity_mismatch(_folder(flow.alice, BUS_DIR)) is None
    assert BUS_DIR in _lockfile(flow)
    assert owner_uses.recorded(_key(flow.alice), flow.pid).package(BUS_DIR), "the lockfile entry is not hers"
    assert (_key(flow.alice), BUS_DIR) in provisioned, f"its libraries were installed for {provisioned}"
    assert _review(client, flow) == []
    hers = {"root": _sources(flow.alice, BUS_DIR), "names": ["bus_helpers"]}
    assert _modules(client, flow, sandbox, "alice") == hers
    remove_package(_key(flow.bob), BUS_DIR)
    assert _modules(client, flow, sandbox, "bob") == hers


def test_her_apply_names_his_package_in_a_lockfile_that_named_none_as_her_change(client, flow, sandbox):
    """alice's lockfile names no package, so her dataflow's packages are read
    from its nodes, and the node bob's drop made of his package counts it in.
    Her Apply still adds it to her lockfile as her change: her record of what
    the dataflow uses holds it, and bob's runs read her copy once his own is
    gone."""
    from utk_curio.backend.app.collaboration import dataflow_docs, owner_uses
    from utk_curio.backend.app.packages.application.store_install import remove_package

    alice, bob = _key(flow.alice), _key(flow.bob)
    with dataflow_docs.writing(alice, flow.pid, dataflow_docs.person(alice, "packages")) as spec:
        spec["dataflow"]["packages"] = []
    # bob's drop of his package's card: his change, which puts nothing of
    # alice's within his reach.
    with dataflow_docs.writing(alice, flow.pid, dataflow_docs.person(bob, "nodes")) as spec:
        spec["dataflow"]["nodes"].append({"id": "bus-node", "type": BUS_NODE, "content": "return 1\n", "in": "DEFAULT",
                                          "out": "DEFAULT", "goal": "", "x": 0, "y": 0})
    request = _asked(client, flow, "bob", BUS_DIR, nodeId="bus-node")
    assert _lockfile(flow) == []

    resp = _apply(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert BUS_DIR in _lockfile(flow), "her Apply left her lockfile naming no package"
    assert owner_uses.recorded(alice, flow.pid).package(BUS_DIR), "the lockfile entry is not hers"
    remove_package(bob, BUS_DIR)
    assert _modules(client, flow, sandbox, "bob") == {"root": _sources(flow.alice, BUS_DIR), "names": ["bus_helpers"]}


def test_his_own_model_comes_to_her_model_catalog_with_its_weights(client, flow, sandbox):
    """bob's own model asks alice as a package does. Her Apply copies it into
    her store with its weights and adds it to her dataflow, and his play of a
    node that loads it then loads her copy."""
    request = _asked(client, flow, "bob", MODEL_DIR, add=True)
    assert (request["packageKind"], request["summary"]) == ("model", "Add model · Bus model"), request
    assert request["preview"].endswith("from Bob Test's Model Catalog"), request["preview"]

    resp = _apply(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert (_folder(flow.alice, MODEL_DIR) / "models" / "w.onnx").read_bytes() == WEIGHTS
    assert MODEL_DIR in _lockfile(flow)
    body = _play(client, flow, sandbox, "bob", "curio.builtin/computation-analysis",
                 f'model = curio_load_model("{MODEL}")\nreturn 1\n')
    assert body.get("models") == {MODEL: str(_folder(flow.alice, MODEL_DIR))}, body.get("models")


def test_a_package_whose_files_changed_since_its_install_is_refused_with_the_reason_and_waits(client, flow):
    """A module of bob's package was changed in his store after its install,
    which no change of Curio's makes without recording it. alice's Apply is
    refused and says which file; nothing of it is in her store or her
    lockfile, and the request still waits in her review."""
    before = _hers(flow)
    request = _asked(client, flow, "bob", BUS_DIR, add=True)
    (_folder(flow.bob, BUS_DIR) / "sources" / "bus_helpers.py").write_text("def count():\n    return 4\n")

    resp = _apply(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 409, resp.get_data(as_text=True)[:300]
    error = resp.get_json()["error"]
    assert "its files are not the ones its install recorded" in error, error
    assert "sources/bus_helpers.py changed" in error, error
    assert _hers(flow) == before
    assert [r["proposalId"] for r in _review(client, flow)] == [request["proposalId"]]


def test_a_package_whose_libraries_conflict_with_hers_is_refused_and_nothing_of_it_stays(client, flow):
    """alice's store holds a package that needs pandas below 1; bob's needs 2
    or above. Her review names the conflict, and her Apply is refused naming
    the library: nothing of his is in her store or her lockfile."""
    from utk_curio.backend.app.packages.application.store_install import remove_package

    hers = _archive(_manifest("test.old-tables", "Old tables", python={"pandas": "<1"}),
                    {"sources/count.py": "return 1\n"})
    _install(_key(flow.alice), hers)
    remove_package(_key(flow.bob), BUS_DIR)
    _install(_key(flow.bob), _bus_counts(python={"pandas": ">=2"}))
    before = _hers(flow)
    request = _asked(client, flow, "bob", BUS_DIR, add=True)

    review = client.get(f"/api/dataflows/{flow.pid}/packages/requests/{request['proposalId']}/review",
                        headers=_auth(flow.tokens["alice"]))
    resp = _apply(client, flow, "alice", request["proposalId"])

    assert review.status_code == 200, review.get_data(as_text=True)[:300]
    assert "pandas" in [conflict["package"] for conflict in review.get_json()["conflicts"]], review.get_json()
    assert resp.status_code == 409, resp.get_data(as_text=True)[:300]
    assert "pandas" in resp.get_json()["error"]
    assert _hers(flow) == before


def test_a_package_of_the_shared_catalog_asks_her_on_a_drop_and_installs_from_the_catalog(
    client, flow, monkeypatch, tmp_path,
):
    """A package runs only from the store of an account that added it, so
    bob's drop of a card of the shared catalog asks alice too, though his store
    does not hold it. Her Apply installs it from the catalog, as her own Add to
    project does, and adds it to her dataflow."""
    catalog = tmp_path / "catalog"
    folder = catalog / SHARED_DIR
    folder.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(_archive(_manifest(SHARED, "Shared counts"),
                                             {"sources/count.py": "return 1\n"}))) as archive:
        archive.extractall(folder)
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))

    request = _asked(client, flow, "bob", SHARED_DIR, nodeId="shared-node")

    assert request["shared"] is True, request
    assert request["preview"].endswith("from the shared Node Catalog"), request["preview"]
    resp = _apply(client, flow, "alice", request["proposalId"])
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert SHARED_DIR in _store(flow.alice)
    assert SHARED_DIR in _lockfile(flow)


def test_a_package_the_dataflow_uses_and_the_built_in_one_ask_nothing(client, flow):
    """Once alice added bob's package, his next drop of it asks nothing, nor
    does a node of the built-in package."""
    request = _asked(client, flow, "bob", BUS_DIR, add=True)
    assert _apply(client, flow, "alice", request["proposalId"]).status_code == 200

    for dir_name in (BUS_DIR, "curio.builtin@1"):
        resp = _ask(client, flow, "bob", dir_name, nodeId="another-node")
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        assert resp.get_json() == {"requested": False, "reason": "listed"}
    assert _review(client, flow) == []


# ---------------------------------------------------------------------------
# Only alice reviews, her Dismiss, and no one else's ask
# ---------------------------------------------------------------------------

def test_the_owners_dismiss_leaves_nothing_behind_and_only_she_reviews(client, flow):
    """bob can neither apply nor dismiss his own request: it waits for alice.
    Her Dismiss takes it out of her review and leaves nothing behind: no
    package in her store, none in her lockfile, no requests file; bob's own
    package stays his."""
    from utk_curio.backend.app.projects import storage as projects_storage

    before = _hers(flow)
    request = _asked(client, flow, "bob", BUS_DIR, add=True)

    for refused in (_apply(client, flow, "bob", request["proposalId"]),
                    _dismiss(client, flow, "bob", request["proposalId"])):
        assert refused.status_code == 403, refused.get_data(as_text=True)[:300]
        assert refused.get_json()["error"] == (
            "This install waits for Alice, who owns this dataflow: an install changes their account, "
            "so they review it."
        )
    resp = _dismiss(client, flow, "alice", request["proposalId"])

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["status"] == "dismissed"
    assert _review(client, flow) == []
    assert _hers(flow) == before
    assert not (projects_storage.project_dir(_key(flow.alice), flow.pid) / REQUESTS_FILE).exists()
    assert BUS_DIR in _store(flow.bob)


def test_a_watcher_cannot_ask_for_a_package_nor_read_the_review(client, flow):
    """carol only has the dataflow's link: her ask and her read of the review
    are refused, and nothing of alice's changes."""
    _install(_key(flow.carol), _archive(_manifest("test.carols-counts", "Carol's counts"),
                                        {"sources/count.py": "return 1\n"}))
    before = _hers(flow)

    asked = _ask(client, flow, "carol", "test.carols-counts@1", add=True)
    read = client.get(f"/api/dataflows/{flow.pid}/packages/requests", headers=_auth(flow.tokens["carol"]))

    assert asked.status_code == 403, asked.get_data(as_text=True)[:300]
    assert read.status_code == 403, read.get_data(as_text=True)[:300]
    assert _hers(flow) == before
