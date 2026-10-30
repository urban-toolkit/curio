"""What an invited editor's runs use of the owner's packages and models.

alice owns a dataflow that uses two things of her store: her package
``ai.test.flood-tools@1``, which its lockfile names and whose node imports the
module ``flood_helpers`` the package ships, and her model
``ai.test.flood-model@1``, dropped onto its ``flood`` node. Her store also
holds Scout (``curio.scout@1``) and a second model, ``ai.test.private-model@1``,
which the dataflow does not use, though a node of Scout's and a node whose code
names that model are on it, as a tab could write them. bob is an editor she
invited, erin was one until alice took her off and now watches, and carol was
never invited.

A run of bob's on alice's dataflow, a play, a run on the server or one an
agent makes, runs the package node with the modules of alice's copy and the
model with her weights, as her own run does. Scout and the second model stay
hers: bob's runs get neither. erin's and carol's runs get nothing of her store.
The agents bob drives hold the skills of the dataflow's packages. Nothing is
added to bob's store, and he cannot publish, export or remove her package.

The sandbox is a fake behind ``node_exec.sandbox_request``, and an agent's run
reaches a fake behind ``runner._http_exec``. The module is here, beside the
other runs' tests, for their database in a file: a run on the server writes
from threads of its own (``conftest.py``).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[4]
TOOLS = "ai.test.flood-tools"
TOOLS_DIR = f"{TOOLS}@1"
FLOOD_MODEL = "ai.test.flood-model"
PRIVATE_MODEL = "ai.test.private-model"
SCOUT_DIR = "curio.scout@1"
SKILL = "flood-depths"
ATTACHMENT = "att-editor-packages"
TOKENS = {"bob": "bob-token-for-tests", "erin": "erin-token-for-tests", "carol": "carol-token-for-tests"}
#: alice's dataflow: a node of her package, a node her model was dropped
#: onto, a node of Scout's and a node whose code names her second model. The
#: first line of each node's code names it in what the sandbox is sent.
NODES = {
    "helpers": ("ai.test.flood-tools/depth", "from flood_helpers import depth\nreturn depth(2)\n"),
    "flood": ("curio.builtin/computation-analysis", f'model = curio_load_model("{FLOOD_MODEL}")\nreturn 1\n'),
    "calc": ("curio.scout/raster-calculator", "return 1\n"),
    "private": ("curio.builtin/computation-analysis", f'model = curio_load_model("{PRIVATE_MODEL}")\nreturn 1\n'),
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _code(node_id: str) -> str:
    return f"# node {node_id}\n{NODES[node_id][1]}"


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _write(folder: Path, files: dict) -> None:
    for relative, text in files.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _tools_package(key: str) -> None:
    """alice's package as an install leaves it: one Python node, the module
    beside it, and one skill for the agents."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    _write(user_packages_dir(key) / TOOLS_DIR, {
        "manifest.json": json.dumps({
            "id": TOOLS, "version": "1.0.0", "name": "Flood tools", "publisher": "Test", "license": "MIT",
            "compatibility": {"major": 1}, "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": "depth", "label": "Depth", "category": "computation", "engine": "python", "editor": "code",
                "behavior": "code", "hasCode": True, "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}], "source": "sources/depth.py",
            }],
        }),
        "sources/depth.py": "return 1\n",
        "sources/flood_helpers.py": "def depth(value):\n    return value * 2\n",
        f"skills/{SKILL}/SKILL.md": (
            f"---\nname: {SKILL}\ndescription: Use this skill when a node works on flood depths.\n"
            "license: MIT\nmetadata:\n  author: test\n---\nRead a flood's depths with flood_helpers.depth.\n"
        ),
    })


def _model_package(key: str, package_id: str) -> None:
    """A model package of alice's own, holding its weights."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    folder = user_packages_dir(key) / f"{package_id}@1"
    _write(folder, {"manifest.json": json.dumps({
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model",
        "templates": [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["JSON"]}]}],
        "model": {"type": "node-regression", "runtime": "onnx", "entry": "models/w.onnx",
                  "labels": [], "license": "MIT", "sizeBytes": 16},
    })})
    (folder / "models").mkdir()
    (folder / "models" / "w.onnx").write_bytes(b"not-a-real-model")


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, its packages and models in her store, an agent
    attached to it, bob invited to edit it, and erin invited, then taken off."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir
    from utk_curio.backend.app.projects import access
    from utk_curio.backend.app.projects import storage as projects_storage

    alice, alice_token = user_and_token
    people = SimpleNamespace(alice=alice, bob=_account(db, "bob"), erin=_account(db, "erin"),
                             carol=_account(db, "carol"))
    key = _key(alice)
    _tools_package(key)
    _model_package(key, FLOOD_MODEL)
    _model_package(key, PRIVATE_MODEL)
    shutil.copytree(REPO / "packages" / SCOUT_DIR, user_packages_dir(key) / SCOUT_DIR)

    resp = client.post("/api/projects", json={
        "name": "Flood check", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
    }, headers=_auth(alice_token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    pid = resp.get_json()["id"]
    spec = projects_storage.read_spec(key, pid)
    dataflow = spec["dataflow"]
    dataflow["nodes"] = [
        {"id": node_id, "type": node_type, "content": _code(node_id), "in": "DEFAULT", "out": "DEFAULT",
         "goal": "", "x": 0, "y": 0,
         "metadata": {"modelRefs": [{"id": FLOOD_MODEL}]} if node_id == "flood" else {}}
        for node_id, (node_type, _content) in NODES.items()
    ]
    dataflow["edges"] = []
    dataflow["packages"] = [TOOLS_DIR]
    dataflow["agentAttachments"] = [{
        "attachmentId": ATTACHMENT, "coord": "agent.curio.node-builder@1",
        "target": {"kind": "node", "targetId": "flood"},
    }]
    projects_storage.write_spec(key, pid, spec)
    access.add_editor(alice, pid, "bob")
    access.add_editor(alice, pid, "erin")
    access.remove_editor(alice, pid, people.erin.id)
    return SimpleNamespace(pid=pid, key=key, people=people, tokens={"alice": alice_token, **TOKENS})


@pytest.fixture()
def sandbox(monkeypatch):
    """The sandbox: every request's body, in order (``sent``), and the last
    one of each node, by the name its code's first line gives (``bodies``).
    Each run is answered at once, with an output."""
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import jobs

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    state = SimpleNamespace(sent=[], bodies={})

    def fake_call(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        state.sent.append(body)
        if "# node " in body["code"]:
            state.bodies[body["code"].split("# node ", 1)[1].split("\n", 1)[0]] = body
        resp = MagicMock()
        resp.json.return_value = {"stdout": [], "stderr": "", "output": {"path": "art", "dataType": "str"}}
        return resp

    monkeypatch.setattr(node_exec, "sandbox_request", fake_call)
    return state


def _play(client, flow, sandbox, who: str, node_id: str) -> dict:
    """*who*'s play of the node *node_id* of alice's dataflow: what it sent the
    sandbox."""
    resp = client.post("/processPythonCode", json={
        "code": _code(node_id), "nodeType": NODES[node_id][0], "dataflowId": flow.pid,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return sandbox.sent[-1]


def _server_run(client, flow, sandbox, who: str, *node_ids: str) -> dict:
    """*who*'s run on the server of the nodes *node_ids* of alice's dataflow,
    to its end: what each node sent the sandbox, by its id."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    resp = client.post(f"/api/projects/{flow.pid}/runs", json={"targets": list(node_ids)},
                       headers=_auth(flow.tokens[who]))
    assert resp.status_code == 202, resp.get_data(as_text=True)
    job = jobs.REGISTRY.get_job(resp.get_json()["id"])
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    # End this thread's read, so it sees what the run's threads committed.
    db.session.rollback()
    missing = set(node_ids) - set(sandbox.bodies)
    assert not missing, f"the run sent the sandbox nothing for {sorted(missing)}; it ran {sorted(sandbox.bodies)}"
    return {node_id: sandbox.bodies[node_id] for node_id in node_ids}


def _agent_run(client, flow, monkeypatch, who: str, node_id: str) -> dict:
    """*who*'s agent runs alice's dataflow through the node *node_id*, as its
    chat's Run node does, on the run's own thread: what that node sent the
    sandbox."""
    sent: list = []

    def _exec(_endpoint, payload):
        sent.append(payload)
        return {"stdout": [], "stderr": "", "output": {"path": f"art-{len(sent)}", "dataType": "str"}}

    monkeypatch.setattr("utk_curio.backend.app.execution.runner._http_exec", _exec)
    resp = client.post(f"/api/agents/projects/{flow.pid}/attachments/{ATTACHMENT}/run-node",
                       json={"nodeId": node_id}, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    name, done = events[-1]
    assert name == "done" and done["ok"] is True, events
    (payload,) = [p for p in sent if f"# node {node_id}\n" in p["code"]]
    return payload


def _sources(key: str, dir_name: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return str(package_dir(key, dir_name) / "sources")


def _folder(key: str, dir_name: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return str(package_dir(key, dir_name))


# ---------------------------------------------------------------------------
# What the dataflow uses runs from the owner's store, for her and her editors
# ---------------------------------------------------------------------------

def test_her_package_node_imports_her_copys_modules_for_her_and_the_editor_she_invited_only(client, flow, sandbox):
    """A play of the node of alice's package, which her dataflow's lockfile
    names, imports the module her copy ships, for alice and for bob, whose
    store does not hold the package. erin, whom she took off her editors, and
    carol, never invited, get nothing of her store, as before."""
    handed = {who: _play(client, flow, sandbox, who, "helpers").get("package_modules")
              for who in ("alice", "bob", "erin", "carol")}

    hers = {"root": _sources(flow.key, TOOLS_DIR), "names": ["flood_helpers"]}
    assert handed == {"alice": hers, "bob": hers, "erin": None, "carol": None}


def test_the_model_her_dataflow_uses_runs_from_her_store_for_her_and_the_editor_she_invited_only(
    client, flow, sandbox,
):
    """A play of the node alice's model was dropped onto loads her weights,
    for alice and for bob, who never added the model. erin and carol get no
    model of hers, as before."""
    models = {who: _play(client, flow, sandbox, who, "flood").get("models")
              for who in ("alice", "bob", "erin", "carol")}

    hers = {FLOOD_MODEL: _folder(flow.key, f"{FLOOD_MODEL}@1")}
    assert models == {"alice": hers, "bob": hers, "erin": None, "carol": None}


def test_an_editors_run_on_the_server_runs_her_package_and_her_model_and_nothing_else_of_hers(
    client, flow, sandbox,
):
    """bob's run on the server of alice's dataflow runs each node as his play
    does: the node of her package with her copy's module, the node her model
    was dropped onto with her weights, and Scout's node and the node naming
    her second model with nothing of hers."""
    bodies = _server_run(client, flow, sandbox, "bob", "helpers", "flood", "calc", "private")

    assert bodies["helpers"].get("package_modules") == {
        "root": _sources(flow.key, TOOLS_DIR), "names": ["flood_helpers"],
    }
    assert bodies["flood"].get("models") == {FLOOD_MODEL: _folder(flow.key, f"{FLOOD_MODEL}@1")}
    assert bodies["calc"].get("package_modules") is None
    assert bodies["private"].get("models") is None
    assert all(body["user_key"] == _key(flow.people.bob) for body in bodies.values())


def test_an_editors_agent_holds_her_dataflows_package_skills_and_runs_its_model_from_her_store(
    client, flow, monkeypatch,
):
    """bob's chat on alice's dataflow lists the skill her package ships, as
    hers does, and not Scout's, which the dataflow does not use; and his
    agent's run of the node her model was dropped onto loads her weights."""
    listed = {}
    for who in ("alice", "bob"):
        resp = client.get(f"/api/agents/projects/{flow.pid}/attachments/{ATTACHMENT}/skills",
                          headers=_auth(flow.tokens[who]))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        listed[who] = [skill["name"] for skill in resp.get_json()["skills"]]
    assert SKILL in listed["alice"] and "scout" not in listed["alice"], listed
    assert listed["bob"] == listed["alice"]

    payload = _agent_run(client, flow, monkeypatch, "bob", "flood")
    assert payload.get("models") == {FLOOD_MODEL: _folder(flow.key, f"{FLOOD_MODEL}@1")}, payload


def test_a_package_and_a_model_of_hers_the_dataflow_does_not_use_stay_hers(client, flow, sandbox, monkeypatch):
    """Scout and alice's second model are in her store and not in what her
    dataflow uses: bob's agent's runs and bob's plays of their nodes get
    neither, from her store or his. alice's plays get both."""
    assert _agent_run(client, flow, monkeypatch, "bob", "calc").get("package_modules") is None
    assert _agent_run(client, flow, monkeypatch, "bob", "private").get("models") is None
    assert _play(client, flow, sandbox, "bob", "calc").get("package_modules") is None
    assert _play(client, flow, sandbox, "bob", "private").get("models") is None

    assert _play(client, flow, sandbox, "alice", "calc")["package_modules"]["root"] == _sources(flow.key, SCOUT_DIR)
    assert _play(client, flow, sandbox, "alice", "private")["models"] == {
        PRIVATE_MODEL: _folder(flow.key, f"{PRIVATE_MODEL}@1"),
    }


# ---------------------------------------------------------------------------
# The editor runs with her package; it stays hers
# ---------------------------------------------------------------------------

def test_an_editor_runs_her_package_and_cannot_publish_export_or_remove_it(
    client, flow, sandbox, tmp_curio, monkeypatch,
):
    """bob's plays run with alice's package and model, and add neither to his
    store. His Publish, Export and Remove of her package are refused, and her
    copy, her dataflow's lockfile and the shared catalog stay as they were."""
    from utk_curio.backend.app.packages.repositories.store import list_user_packages, package_dir
    from utk_curio.backend.app.packages.routes import common as routes_common
    from utk_curio.backend.app.projects import storage as projects_storage

    catalog = tmp_curio / "catalog"
    catalog.mkdir()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    monkeypatch.setattr(routes_common, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", True)
    assert _play(client, flow, sandbox, "bob", "helpers").get("package_modules") == {
        "root": _sources(flow.key, TOOLS_DIR), "names": ["flood_helpers"],
    }
    assert _play(client, flow, sandbox, "bob", "flood").get("models") == {
        FLOOD_MODEL: _folder(flow.key, f"{FLOOD_MODEL}@1"),
    }

    bob = _auth(flow.tokens["bob"])
    for method, path, body in (
        ("post", "/api/packages/factory/publish-catalog", {"dirName": TOOLS_DIR}),
        ("get", f"/api/packages/{TOOLS_DIR}/archive", None),
        ("delete", f"/api/packages/{TOOLS_DIR}", None),
        ("delete", f"/api/packages/{TOOLS_DIR}?unusedOnly=true", None),
        ("delete", f"/api/packages/projects/{flow.pid}/{TOOLS_DIR}", None),
    ):
        resp = getattr(client, method)(path, json=body, headers=bob)
        assert resp.status_code == 404, f"{method} {path}: {resp.status_code} {resp.get_data(as_text=True)[:200]}"

    assert (package_dir(flow.key, TOOLS_DIR) / "sources" / "flood_helpers.py").is_file()
    assert TOOLS_DIR in projects_storage.read_spec(flow.key, flow.pid)["dataflow"]["packages"]
    assert list(catalog.iterdir()) == []
    hers = {TOOLS_DIR, f"{FLOOD_MODEL}@1", f"{PRIVATE_MODEL}@1", SCOUT_DIR}
    assert not hers & {folder.name for folder in list_user_packages(_key(flow.people.bob))}
