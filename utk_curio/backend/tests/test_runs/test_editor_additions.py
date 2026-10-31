"""What an invited editor's change to the owner's dataflow puts within reach of
his runs: nothing of hers.

alice owns a dataflow that uses, of her store, her street trees (its
``datasets`` list them), her package ``ai.test.flood-tools@1`` (its lockfile
names it, and its ``helpers`` node imports the module the package ships) and her
model ``ai.test.flood-model@1`` (bound to its ``flood`` node). Her store also
holds what the dataflow does not use: her salaries, Scout (``curio.scout@1``)
and a second model, ``ai.test.private-model@1``, which the code of its
``private`` and ``private-2`` nodes names though no node is bound to it. bob is
an editor she invited; his store holds his bus stops, his package
``ai.test.bobs-tools@1`` and his model ``ai.test.bobs-model@1``.

A change of bob's that puts another item of alice's in the dataflow's lists
(its datasets, collections among them, its lockfile, a node of a package, a
model bound to a node),
made in his tab or by an agent run he asked for, does not put it within reach
of his runs: a play, a run on the server and his agent's run read it from his
own store, which does not hold it, and his chat holds none of the skills of a
package of hers he added. Once alice puts it in herself (her tab, Add to
project or to all projects, an agent run she asked for), his runs read it from
her store, a package his node already counted in or his change named in her
lockfile among them. Her add of another package, her removal of one and a
script's save of the whole dataflow write out a lockfile that read as the
packages of the nodes, his node's among them, and put none of those within
his reach. His own items and the shared catalog's load as before, and alice's
runs read all of hers.

A tab is a pycrdt doc syncing over a Flask-SocketIO test client
(``test_collaboration/_ydoc_client.py``). Each change it makes is written into
the server's doc over its socket, and the doc is then written to the spec, as
the server does a second after the change. The sandbox is a fake behind
``node_exec.sandbox_request``, and an agent's run reaches a fake behind
``runner._http_exec``. The module is here, beside the other runs' tests, for
their database in a file: a run on the server writes from threads of its own.
"""
from __future__ import annotations

import copy
import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[4]
TOOLS = "ai.test.flood-tools"
TOOLS_DIR = f"{TOOLS}@1"
BOBS_TOOLS = "ai.test.bobs-tools"
BOBS_DIR = f"{BOBS_TOOLS}@1"
GAUGES = "ai.test.gauge-tools"
GAUGES_DIR = f"{GAUGES}@1"
RAIN = "ai.test.rain-tools"
RAIN_DIR = f"{RAIN}@1"
FLOOD_MODEL = "ai.test.flood-model"
PRIVATE_MODEL = "ai.test.private-model"
BOBS_MODEL = "ai.test.bobs-model"
SCOUT_DIR = "curio.scout@1"
BUILTIN = "curio.builtin/computation-analysis"
COORD = "agent.curio.node-builder@1"
ATTACHMENT = "att-editor-additions"
HUB_ID = "data.test.street-lights"
TREES = b"tree,species\n1,elm\n2,oak\n"
SALARIES = b"name,salary\nalice,100\n"
BUS_STOPS = b"stop,routes\nClark,22\n"
LIGHTS = b"light,watts\n1,40\n"
BOB_TOKEN = "bob-token-for-tests"
#: Each node a test runs: its type, and its code after a first line that names
#: it in what the sandbox is sent.
NODES = {
    "helpers": (f"{TOOLS}/depth", "from flood_helpers import depth\nreturn depth(2)\n"),
    "flood": (BUILTIN, f'model = curio_load_model("{FLOOD_MODEL}")\nreturn 1\n'),
    "private": (BUILTIN, f'model = curio_load_model("{PRIVATE_MODEL}")\nreturn 1\n'),
    "private-2": (BUILTIN, f'model = curio_load_model("{PRIVATE_MODEL}")\nreturn 2\n'),
    "calc": ("curio.scout/raster-calculator@1", "return 1\n"),
    "calc-2": ("curio.scout/raster-calculator@1", "return 2\n"),
    "bobs": (f"{BOBS_TOOLS}/count@1", "from bobs_helpers import count\nreturn count()\n"),
    "bobs-model": (BUILTIN, f'model = curio_load_model("{BOBS_MODEL}")\nreturn 1\n'),
    "gauge": (f"{GAUGES}/reading@1", "from gauge_helpers import reading\nreturn reading()\n"),
    "rain": (f"{RAIN}/rainfall@1", "from rain_helpers import rainfall\nreturn rainfall()\n"),
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _code(node_id: str) -> str:
    return f"# node {node_id}\n{NODES[node_id][1]}"


def _node(node_id: str, **metadata) -> dict:
    """The node *node_id* as a dataflow's Trill holds it."""
    node = {"id": node_id, "type": NODES[node_id][0], "content": _code(node_id), "in": "DEFAULT",
            "out": "DEFAULT", "goal": "", "x": 0, "y": 0}
    if metadata:
        node["metadata"] = metadata
    return node


def _key(user) -> str:
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


def _account(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


def _write(folder: Path, files: dict) -> None:
    for relative, text in files.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _package(key: str, package_id: str, template: str, module: str, source: str) -> None:
    """A package of the store *key* as an install leaves it: one Python node
    and the module beside it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir

    _write(user_packages_dir(key) / f"{package_id}@1", {
        "manifest.json": json.dumps({
            "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test", "license": "MIT",
            "compatibility": {"major": 1}, "dependencies": {"packages": {}, "python": {}, "js": {}},
            "templates": [{
                "id": template, "label": template.title(), "category": "computation", "engine": "python",
                "editor": "code", "behavior": "code", "hasCode": True, "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}], "source": f"sources/{template}.py",
            }],
        }),
        f"sources/{template}.py": "return 1\n",
        f"sources/{module}.py": source,
    })


def _model_package(key: str, package_id: str) -> None:
    """A model package of the store *key*, holding its weights."""
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


def _import(client, token: str, name: str, body: bytes) -> dict:
    """A file imported into the Data Catalog of the account *token* signs in."""
    resp = client.post("/api/datasets/import", headers=_auth(token),
                       data={"file": (io.BytesIO(body), name)}, content_type="multipart/form-data")
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _ref(item: dict, installed_at: str = "2000-01-01T00:00:00Z") -> dict:
    """A ref of a dataflow's ``datasets`` to the dataset *item*, as Add to
    project writes one, *installed_at* a time no install of a test writes."""
    return {"datasetId": item["id"], "dirName": item["dirName"], "origin": "imported",
            "producerNodeId": None, "consumerNodeIds": [], "installedAt": installed_at}


def _dataflow(client, key: str, token: str, *, packages: list, datasets: list) -> str:
    """alice's dataflow, as her tab and her Data Catalog leave it: the
    ``helpers`` node of her package, the ``flood`` node her model is bound
    to, the ``private`` and ``private-2`` nodes whose code names her second
    model, the lockfile *packages*, the refs *datasets*, and an agent
    attached to ``flood``; its id."""
    from utk_curio.backend.app.projects import storage as projects_storage

    resp = client.post("/api/projects", json={
        "name": "Flood check", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": [],
    }, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    pid = resp.get_json()["id"]
    spec = projects_storage.read_spec(key, pid)
    dataflow = spec["dataflow"]
    dataflow["nodes"] = [_node("helpers"), _node("flood", modelRefs=[{"id": FLOOD_MODEL}]),
                         _node("private"), _node("private-2")]
    dataflow["edges"] = []
    dataflow["packages"] = packages
    dataflow["datasets"] = datasets
    dataflow["agentAttachments"] = [{
        "attachmentId": ATTACHMENT, "coord": COORD, "target": {"kind": "node", "targetId": "flood"},
    }]
    projects_storage.write_spec(key, pid, spec)
    return pid


@pytest.fixture(autouse=True)
def _rooms():
    from utk_curio.backend.app.collaboration import room_state

    room_state.reset_for_tests()
    yield
    room_state.reset_for_tests()


@pytest.fixture()
def flow(client, db, user_and_token):
    """alice's dataflow, which uses her street trees, her package and her
    first model, the rest of her store and bob's own items, and bob invited
    to edit it."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir
    from utk_curio.backend.app.projects import access

    alice, alice_token = user_and_token
    bob = _account(db, "bob", BOB_TOKEN)
    key, bob_key = _key(alice), _key(bob)
    _package(key, TOOLS, "depth", "flood_helpers", "def depth(value):\n    return value * 2\n")
    _package(bob_key, BOBS_TOOLS, "count", "bobs_helpers", "def count():\n    return 3\n")
    for store, model in ((key, FLOOD_MODEL), (key, PRIVATE_MODEL), (bob_key, BOBS_MODEL)):
        _model_package(store, model)
    shutil.copytree(REPO / "packages" / SCOUT_DIR, user_packages_dir(key) / SCOUT_DIR)
    trees = _import(client, alice_token, "trees.csv", TREES)
    salaries = _import(client, alice_token, "salaries.csv", SALARIES)
    bus_stops = _import(client, BOB_TOKEN, "bus_stops.csv", BUS_STOPS)
    pid = _dataflow(client, key, alice_token, packages=[TOOLS_DIR], datasets=[_ref(trees)])
    access.add_editor(alice, pid, "bob")
    return SimpleNamespace(
        pid=pid, key=key, bob_key=bob_key, alice=alice, bob=bob,
        tokens={"alice": alice_token, "bob": BOB_TOKEN},
        trees=trees, salaries=salaries, bus_stops=bus_stops,
    )


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


# ---------------------------------------------------------------------------
# Tabs, runs and what they read
# ---------------------------------------------------------------------------

def _tab(app, flow, who: str):
    """A tab of alice's dataflow signed in as *who*, synced with its doc."""
    from utk_curio.backend.tests.test_collaboration._ydoc_client import synced_tab

    return synced_tab(app, flow.tokens[who], flow.pid)


def _edit(tab, edit) -> None:
    """The tab's change to the dataflow: *edit*, a function of the Trill
    dataflow the tab holds, written into its doc as a canvas writes what
    changed (``doc_mapping.apply_dataflow``) and sent over its socket. The
    server's doc is then written to the spec."""
    from utk_curio.backend.app.collaboration import dataflow_docs, doc_mapping

    tab.pump()

    def change(doc):
        base = doc_mapping.doc_to_dataflow(doc)
        target = copy.deepcopy(base)
        edit(target)
        doc_mapping.apply_dataflow(doc, base, target)

    acks = tab.edit(change)
    assert acks and all(ack.get("ok") is True for ack in acks), acks
    assert dataflow_docs.flush(tab.project_id), "the server's doc held no change to write"


def _with_node(*nodes: dict):
    def edit(dataflow: dict) -> None:
        dataflow["nodes"] = [*dataflow.get("nodes", []), *nodes]

    return edit


def _bound(node_id: str, model: str):
    """A change that binds *model* to the node *node_id*, as a model dropped
    onto the node does."""

    def edit(dataflow: dict) -> None:
        node = next(node for node in dataflow["nodes"] if node["id"] == node_id)
        node.setdefault("metadata", {})["modelRefs"] = [{"id": model}]

    return edit


def _on_disk(flow) -> dict:
    from utk_curio.backend.app.projects import storage as projects_storage

    return projects_storage.read_spec(flow.key, flow.pid)["dataflow"]


def _play(client, flow, sandbox, who: str, node_id: str) -> dict:
    """*who*'s play of the node *node_id* of alice's dataflow: what it sent the
    sandbox."""
    sent = len(sandbox.sent)
    resp = client.post("/processPythonCode", json={
        "code": _code(node_id), "nodeType": NODES[node_id][0], "dataflowId": flow.pid,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(sandbox.sent) == sent + 1, "the play reached no sandbox"
    return sandbox.sent[-1]


def _loaded(client, flow, sandbox, who: str, *items: dict) -> dict:
    """The datasets *items* that *who*'s run of a node loading each one on
    alice's dataflow resolved, by id: ``{id: file}``."""
    code = "".join(f'    d{i} = curio_load_data("{item["id"]}")\n' for i, item in enumerate(items))
    sent = len(sandbox.sent)
    resp = client.post("/processPythonCode", json={
        "code": code + "    return d0\n", "nodeType": "PYTHON_COMPUTATION", "dataflowId": flow.pid,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(sandbox.sent) == sent + 1, "the run reached no sandbox"
    return sandbox.sent[-1]["dataset_paths"]


def _server_run(client, flow, sandbox, who: str, *node_ids: str) -> dict:
    """*who*'s run on the server of the nodes *node_ids* of alice's dataflow,
    to its end: what each node sent the sandbox, by its id."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    for node_id in node_ids:
        sandbox.bodies.pop(node_id, None)
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


def _agents_change(app, flow, who: str, edit) -> None:
    """A change the agent attached to alice's dataflow makes for *who*, who
    asked for it: *edit*, written through the dataflow's doc by the agent, as
    the account the agents' code names who asks (``spec_reads._agent_actor``)."""
    from flask import g

    from utk_curio.backend.app.agents.application import spec_reads
    from utk_curio.backend.app.collaboration import dataflow_docs

    with app.test_request_context():
        g.user = getattr(flow, who)
        spec = dataflow_docs.live(flow.key, flow.pid)
        edit(spec["dataflow"])
        actor = spec_reads._agent_actor(flow.key, spec, ATTACHMENT, "plan")
        assert dataflow_docs.write(flow.key, flow.pid, spec, actor).wrote


def _owners_model(client, flow) -> None:
    """alice's LLM configuration, which her agents answer with whoever asks
    them; its key is a stand-in, no real key."""
    resp = client.post("/api/agents/llm/configs", json={
        "label": "Owner's model", "apiType": "openai_compatible", "baseUrl": "https://llm.example.test/v1",
        "apiKey": "not-a-real-llm-key-alice", "model": "owners-model",
    }, headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    resp = client.put("/api/agents/llm/default", json={"configId": resp.get_json()["config"]["id"]},
                      headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _chat_skills(client, flow, who: str) -> list:
    """The skills *who*'s next chat run on alice's dataflow lists, by name."""
    resp = client.get(f"/api/agents/projects/{flow.pid}/attachments/{ATTACHMENT}/skills",
                      headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [skill["name"] for skill in resp.get_json()["skills"]]


def _strings(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _told(client, flow, monkeypatch, who: str) -> str:
    """What the model is told in *who*'s chat run on alice's dataflow, the
    owner's model answering with a scripted reply: every text of each call's
    messages and options. As in the agents' suite (``test_agents/conftest.py``),
    the endpoint is never asked whether it calls tools natively: the run
    speaks the fenced protocol, whose system turn lists the chat's skills."""
    from utk_curio.backend.app.agents.application.turns import titles
    from utk_curio.backend.app.agents.infrastructure import providers

    calls: list = []

    def _model(config, messages, **kwargs):
        if messages and messages[0].get("content") == titles.title_prompt():
            return "Title"
        calls.append("\n".join(_strings([messages, kwargs])))
        return "Here is what the node does."

    monkeypatch.setattr(providers, "probe_native_tools",
                        lambda config, usage_out=None: (None, "not asked in the test suite"))
    monkeypatch.setattr(providers, "run_chat_turn", _model)
    resp = client.post(f"/api/agents/projects/{flow.pid}/attachments/{ATTACHMENT}/run",
                       json={"message": "What does this node do?"}, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert calls, "the chat asked its model nothing"
    return "\n".join(calls)


def _scout_skill(flow):
    """A skill alice's copy of Scout ships, as a run reads it."""
    from utk_curio.backend.app.agents.domain import skills as skill_format
    from utk_curio.backend.app.packages.repositories.store import package_dir

    folders = sorted(path for path in (package_dir(flow.key, SCOUT_DIR) / "skills").iterdir() if path.is_dir())
    assert folders, "Scout ships no skill"
    return skill_format.parse(folders[0])


def _sources(key: str, dir_name: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return str(package_dir(key, dir_name) / "sources")


def _folder(key: str, dir_name: str) -> str:
    from utk_curio.backend.app.packages.repositories.store import package_dir

    return str(package_dir(key, dir_name))


def _collection(user, tmp_path, monkeypatch) -> dict:
    """A collection of *user*'s Data Catalog, added as the Discovery Catalog
    adds one (``StorageAcquire._add_collection``), its index the shipped
    noise recordings', its source the committed Discovery Catalog's; the
    catalog item."""
    import uuid

    from utk_curio.backend.app.datasets.service import DatasetCatalogService
    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(REPO / "discovery"))
    noise = REPO / "datasets" / "data.curio.storage-noise@1"
    manifest = json.loads((noise / "manifest.json").read_text(encoding="utf-8"))
    staged = tmp_path / f"index-{uuid.uuid4().hex}.parquet"
    shutil.copyfile(noise / "data" / "index.parquet", staged)
    return DatasetCatalogService(user)._mutations._install_imported_path(
        staged, "index.parquet", "collection", title=manifest["name"],
        discovery_source=manifest["discoverySource"], row_count=manifest["rowCount"],
        collection=manifest["collection"],
    )


def _collection_run(client, flow, sandbox, who: str, item: dict) -> dict:
    """*who*'s run of a node that loads the collection *item* on alice's
    dataflow: what it sent the sandbox."""
    sent = len(sandbox.sent)
    resp = client.post("/processPythonCode", json={
        "code": f'    c0 = curio_load_collection("{item["id"]}")\n    return c0\n',
        "nodeType": "PYTHON_COMPUTATION", "dataflowId": flow.pid,
        "input": {"path": "", "dataType": "str"}, "saveOutputDataset": False,
    }, headers=_auth(flow.tokens[who]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(sandbox.sent) == sent + 1, "the run reached no sandbox"
    return sandbox.sent[-1]


def _hub_dataset(tmp_path, monkeypatch) -> dict:
    """A dataset of the shared catalog, which every account browses."""
    from utk_curio.backend.app.datasets.domain.manifest import DatasetManifest, write_manifest

    catalog = tmp_path / "catalog"
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    folder = catalog / f"{HUB_ID}@1"
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "lights.csv").write_bytes(LIGHTS)
    write_manifest(DatasetManifest(
        id=HUB_ID, name="Street lights", version="1.0.0", format="csv", description="",
        publisher="Curio", license="MIT", tags=["lights"], data_file="data/lights.csv", major=1,
    ), folder)
    return {"id": HUB_ID}


# ---------------------------------------------------------------------------
# Each kind of item an editor's tab puts in, and the owner after him
# ---------------------------------------------------------------------------

def test_a_dataset_of_hers_an_editor_lists_loads_in_his_runs_only_once_she_adds_it(
    app, client, flow, sandbox, tmp_path, monkeypatch,
):
    """bob's tab lists alice's salaries in her dataflow's datasets. His run
    loads her street trees, his own bus stops and the shared catalog's street
    lights, and not her salaries, which his listing of the dataflow does not
    show either; alice's run loads them. Once alice adds them herself, with
    Add to project, bob's run loads them from her store."""
    hub = _hub_dataset(tmp_path, monkeypatch)
    bob = _tab(app, flow, "bob")
    _edit(bob, lambda dataflow: dataflow["datasets"].append(_ref(flow.salaries)))
    assert _ref(flow.salaries) in _on_disk(flow)["datasets"]

    paths = _loaded(client, flow, sandbox, "bob", flow.trees, flow.bus_stops, hub, flow.salaries)
    assert set(paths) == {flow.trees["id"], flow.bus_stops["id"], HUB_ID}, f"bob's run resolved {paths}"
    listed = client.get(f"/api/datasets/catalog?dataflowId={flow.pid}", headers=_auth(BOB_TOKEN))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert flow.salaries["id"] not in {item["id"] for item in listed.get_json()["items"]}
    assert set(_loaded(client, flow, sandbox, "alice", flow.salaries)) == {flow.salaries["id"]}

    resp = client.post(f"/api/dataflows/{flow.pid}/datasets/install", json={"datasetId": flow.salaries["id"]},
                       headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    paths = _loaded(client, flow, sandbox, "bob", flow.salaries)
    assert set(paths) == {flow.salaries["id"]}, f"bob's run resolved {paths}"
    assert Path(paths[flow.salaries["id"]]).read_bytes() == SALARIES


def test_a_collection_of_hers_an_editor_lists_loads_in_his_runs_only_once_she_adds_it(
    app, client, flow, sandbox, tmp_path, monkeypatch,
):
    """bob's tab lists a collection of alice's Data Catalog in her dataflow's
    datasets. His run of a node that loads it gets neither its index nor its
    files, while alice's run gets both. Once alice adds it herself, with Add
    to project, bob's run gets it from her store."""
    collection = _collection(flow.alice, tmp_path, monkeypatch)
    _edit(_tab(app, flow, "bob"), lambda dataflow: dataflow["datasets"].append(_ref(collection)))
    assert _ref(collection) in _on_disk(flow)["datasets"]

    body = _collection_run(client, flow, sandbox, "bob", collection)
    assert body["collections"] == {}, f"bob's run resolved the collections {body['collections']}"
    assert collection["id"] not in body["dataset_paths"]
    assert set(_collection_run(client, flow, sandbox, "alice", collection)["collections"]) == {collection["id"]}

    resp = client.post(f"/api/dataflows/{flow.pid}/datasets/install", json={"datasetId": collection["id"]},
                       headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = _collection_run(client, flow, sandbox, "bob", collection)
    assert set(body["collections"]) == {collection["id"]}, f"bob's run resolved the collections {body['collections']}"
    assert collection["id"] in body["dataset_paths"]


def test_a_package_of_hers_an_editor_adds_runs_from_her_store_only_once_she_adds_it(
    app, client, flow, sandbox, monkeypatch,
):
    """bob's tab adds a node of alice's Scout and Scout to the lockfile, and a
    node of his own package. His play, his run on the server and his agent's
    run of the Scout node get none of her Scout's modules, and his own node
    gets his package's; her play of it gets hers. Once alice adds a node of
    Scout herself, bob's play of his Scout node gets her Scout's modules."""
    bob = _tab(app, flow, "bob")

    def edit(dataflow: dict) -> None:
        dataflow["nodes"].extend([_node("calc"), _node("bobs")])
        dataflow["packages"] = [*dataflow["packages"], SCOUT_DIR]

    _edit(bob, edit)
    assert SCOUT_DIR in _on_disk(flow)["packages"]

    assert _play(client, flow, sandbox, "bob", "calc").get("package_modules") is None
    assert _server_run(client, flow, sandbox, "bob", "calc")["calc"].get("package_modules") is None
    assert _agent_run(client, flow, monkeypatch, "bob", "calc").get("package_modules") is None
    assert _play(client, flow, sandbox, "bob", "bobs").get("package_modules") == {
        "root": _sources(flow.bob_key, BOBS_DIR), "names": ["bobs_helpers"],
    }
    hers = _sources(flow.key, SCOUT_DIR)
    assert _play(client, flow, sandbox, "alice", "calc")["package_modules"]["root"] == hers

    _edit(_tab(app, flow, "alice"), _with_node(_node("calc-2")))
    assert _play(client, flow, sandbox, "bob", "calc")["package_modules"]["root"] == hers


def test_a_node_of_a_package_only_she_holds_runs_without_her_modules_when_an_editor_adds_it(
    app, client, flow, sandbox,
):
    """On a dataflow of alice's whose lockfile is empty, so it uses the
    package of each node on its canvas, bob's tab adds a node of her Scout. His
    play of it gets none of her Scout's modules, while his play of her
    ``helpers`` node gets her package's; her play of his node gets her
    Scout's."""
    from utk_curio.backend.app.projects import access

    flow.pid = _dataflow(client, flow.key, flow.tokens["alice"], packages=[], datasets=[])
    access.add_editor(flow.alice, flow.pid, "bob")
    _edit(_tab(app, flow, "bob"), _with_node(_node("calc")))
    assert not _on_disk(flow).get("packages"), "the dataflow's lockfile names a package"

    assert _play(client, flow, sandbox, "bob", "calc").get("package_modules") is None
    assert _play(client, flow, sandbox, "bob", "helpers").get("package_modules") == {
        "root": _sources(flow.key, TOOLS_DIR), "names": ["flood_helpers"],
    }
    assert _play(client, flow, sandbox, "alice", "calc")["package_modules"]["root"] == _sources(flow.key, SCOUT_DIR)


def _counted_in_by_his_node(app, client, flow, sandbox) -> None:
    """alice's gauge package, which her store alone holds, and a dataflow of
    hers whose lockfile is empty, so it uses the package of each node on its
    canvas. bob's tab adds a node of the package: the dataflow then reads as
    using it already, while bob's play of his node gets none of its modules."""
    from utk_curio.backend.app.projects import access

    _package(flow.key, GAUGES, "reading", "gauge_helpers", "def reading():\n    return 4\n")
    flow.pid = _dataflow(client, flow.key, flow.tokens["alice"], packages=[], datasets=[])
    access.add_editor(flow.alice, flow.pid, "bob")
    _edit(_tab(app, flow, "bob"), _with_node(_node("gauge")))
    assert not _on_disk(flow).get("packages"), "the dataflow's lockfile names a package"
    listed = client.get(f"/api/packages/projects/{flow.pid}", headers=_auth(flow.tokens["alice"]))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert GAUGES_DIR in listed.get_json()["packages"], "his node does not count her package in"
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") is None


def test_a_package_she_adds_to_a_dataflow_his_node_counted_it_in_runs_from_her_store(app, client, flow, sandbox):
    """bob's node counts alice's gauge package in on a dataflow whose lockfile
    is empty. Her Add to project of the package is her change all the same:
    her lockfile names it beside the package her ``helpers`` node uses, her
    record of what the dataflow uses holds it, and bob's play of his node gets
    her package's modules, while his play of ``helpers`` still gets hers."""
    from utk_curio.backend.app.collaboration import owner_uses

    _counted_in_by_his_node(app, client, flow, sandbox)

    resp = client.post(f"/api/packages/projects/{flow.pid}/install", json={"dirName": GAUGES_DIR},
                       headers=_auth(flow.tokens["alice"]))

    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert GAUGES_DIR in (_on_disk(flow).get("packages") or []), "her Add left her lockfile naming no package"
    assert TOOLS_DIR in _on_disk(flow)["packages"], "her Add took the package of her helpers node out"
    assert owner_uses.recorded(flow.key, flow.pid).package(GAUGES_DIR), "her Add is not on her record"
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == {
        "root": _sources(flow.key, GAUGES_DIR), "names": ["gauge_helpers"],
    }
    assert _play(client, flow, sandbox, "bob", "helpers").get("package_modules") == {
        "root": _sources(flow.key, TOOLS_DIR), "names": ["flood_helpers"],
    }


def test_a_package_she_adds_to_all_projects_runs_from_her_store_where_his_node_counted_it_in(
    app, client, flow, sandbox,
):
    """The same with Add to all projects, on the Node Catalog page: the
    dataflow whose lockfile was empty names her gauge package, and bob's play
    of his node gets her package's modules."""
    _counted_in_by_his_node(app, client, flow, sandbox)

    resp = client.post("/api/packages/defaults", json={"dirName": GAUGES_DIR}, headers=_auth(flow.tokens["alice"]))

    assert resp.status_code == 201, resp.get_data(as_text=True)
    assert GAUGES_DIR in (_on_disk(flow).get("packages") or []), (
        "her Add to all projects left this dataflow's lockfile naming no package"
    )
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == {
        "root": _sources(flow.key, GAUGES_DIR), "names": ["gauge_helpers"],
    }


def _gauges(key: str) -> dict:
    """What a play of the ``gauge`` node gets from the copy of the gauge
    package the store *key* holds."""
    return {"root": _sources(key, GAUGES_DIR), "names": ["gauge_helpers"]}


def _gauges_in_both_stores(flow) -> None:
    """The gauge package in alice's store and in bob's, each copy with a
    module of its own, and alice's rain package, which no node of hers uses."""
    _package(flow.key, GAUGES, "reading", "gauge_helpers", "def reading():\n    return 4\n")
    _package(flow.bob_key, GAUGES, "reading", "gauge_helpers", "def reading():\n    return 5\n")
    _package(flow.key, RAIN, "rainfall", "rain_helpers", "def rainfall():\n    return 7\n")


def _counted_in_from_his_own_copy(app, client, flow, sandbox, *hers: dict) -> None:
    """The gauge and rain packages (:func:`_gauges_in_both_stores`) and a
    dataflow of alice's whose lockfile is empty, so it uses the package of
    each node on its canvas: her nodes *hers*, which her tab adds, and a node
    of the gauge package, which bob's tab adds. The dataflow reads as using
    the gauge package, while bob's play of his node gets his own copy's
    modules."""
    from utk_curio.backend.app.projects import access

    _gauges_in_both_stores(flow)
    flow.pid = _dataflow(client, flow.key, flow.tokens["alice"], packages=[], datasets=[])
    access.add_editor(flow.alice, flow.pid, "bob")
    if hers:
        _edit(_tab(app, flow, "alice"), _with_node(*hers))
    _edit(_tab(app, flow, "bob"), _with_node(_node("gauge")))
    assert not _on_disk(flow).get("packages"), "the dataflow's lockfile names a package"
    listed = client.get(f"/api/packages/projects/{flow.pid}", headers=_auth(flow.tokens["alice"]))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert GAUGES_DIR in listed.get_json()["packages"], "his node does not count the gauge package in"
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)


def _add_to_project(client, flow, dir_name: str) -> None:
    """alice's Add to project of the package *dir_name*, in her canvas's
    Node Catalog drawer."""
    resp = client.post(f"/api/packages/projects/{flow.pid}/install", json={"dirName": dir_name},
                       headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)


def _add_to_all_projects(client, flow, dir_name: str) -> None:
    """alice's Add to all projects of the package *dir_name*, on the Node
    Catalog page."""
    resp = client.post("/api/packages/defaults", json={"dirName": dir_name}, headers=_auth(flow.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)


def test_her_add_of_another_package_leaves_the_one_his_node_counted_in_off_her_record(app, client, flow, sandbox):
    """bob's node counts the gauge package in on a dataflow of alice's whose
    lockfile is empty, and his store holds a copy of it as hers does. Her Add
    to project of her rain package names the gauge package in her lockfile
    too, as the lockfile read, but only the rain package goes on her record of
    what the dataflow uses: bob's play of his node still gets his own copy's
    modules. Once she adds the gauge package herself, his play gets hers."""
    from utk_curio.backend.app.collaboration import owner_uses

    _counted_in_from_his_own_copy(app, client, flow, sandbox)

    _add_to_project(client, flow, RAIN_DIR)

    assert {TOOLS_DIR, GAUGES_DIR, RAIN_DIR} <= set(_on_disk(flow).get("packages") or []), (
        "her Add left out of her lockfile a package it read as"
    )
    record = owner_uses.recorded(flow.key, flow.pid)
    assert record.package(RAIN_DIR), "her Add is not on her record"
    assert not record.package(GAUGES_DIR), "her Add of the rain package put the package his node counted in on her record"
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)

    _add_to_project(client, flow, GAUGES_DIR)

    assert owner_uses.recorded(flow.key, flow.pid).package(GAUGES_DIR), "her Add of the gauge package is not on her record"
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.key)


def test_her_add_to_all_projects_of_another_package_leaves_the_one_his_node_counted_in_off_her_record(
    app, client, flow, sandbox,
):
    """The same with Add to all projects, on the Node Catalog page: the rain
    package goes on her record of the dataflow whose lockfile was empty, the
    gauge package his node counted in does not, and bob's play of his node
    gets his own copy's modules until she adds the gauge package too."""
    from utk_curio.backend.app.collaboration import owner_uses

    _counted_in_from_his_own_copy(app, client, flow, sandbox)

    _add_to_all_projects(client, flow, RAIN_DIR)

    assert {TOOLS_DIR, GAUGES_DIR, RAIN_DIR} <= set(_on_disk(flow).get("packages") or []), (
        "her Add to all projects left out of this dataflow's lockfile a package it read as"
    )
    record = owner_uses.recorded(flow.key, flow.pid)
    assert record.package(RAIN_DIR), "her Add to all projects is not on her record"
    assert not record.package(GAUGES_DIR), (
        "her Add to all projects of the rain package put the package his node counted in on her record"
    )
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)

    _add_to_all_projects(client, flow, GAUGES_DIR)

    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.key)


def test_a_package_he_named_in_her_lockfile_runs_from_her_store_once_she_adds_it(app, client, flow, sandbox):
    """bob's tab adds a node of the gauge package to alice's dataflow and
    names the package in its lockfile, beside her flood tools; his store
    holds a copy of the package as hers does, and his play of his node gets
    his own. Her Add to project of the package, which her lockfile names
    already, is her change all the same: her record of what the dataflow uses
    holds it, and bob's play of his node gets her copy's modules."""
    from utk_curio.backend.app.collaboration import owner_uses

    _gauges_in_both_stores(flow)

    def edit(dataflow: dict) -> None:
        dataflow["nodes"].append(_node("gauge"))
        dataflow["packages"] = [*dataflow["packages"], GAUGES_DIR]

    _edit(_tab(app, flow, "bob"), edit)
    assert GAUGES_DIR in _on_disk(flow)["packages"]
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)

    _add_to_project(client, flow, GAUGES_DIR)

    assert owner_uses.recorded(flow.key, flow.pid).package(GAUGES_DIR), (
        "her Add of a package her lockfile named already is not on her record"
    )
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.key)


def test_her_removal_of_a_package_leaves_the_one_his_node_counted_in_off_her_record(app, client, flow, sandbox):
    """On a dataflow of alice's whose lockfile is empty, her node of her rain
    package and bob's node of the gauge package count both in. Her removal of
    the rain package from her account takes it out of her lockfile, which then
    names the other packages it read as, the gauge package among them: none
    of them goes on her record of what the dataflow uses, and bob's play of
    his node still gets his own copy's modules."""
    from utk_curio.backend.app.collaboration import owner_uses

    _counted_in_from_his_own_copy(app, client, flow, sandbox, _node("rain"))

    resp = client.delete(f"/api/packages/{RAIN_DIR}", headers=_auth(flow.tokens["alice"]))

    assert resp.status_code == 204, resp.get_data(as_text=True)
    packages = _on_disk(flow).get("packages") or []
    assert GAUGES_DIR in packages and RAIN_DIR not in packages, f"her removal left her lockfile naming {packages}"
    assert not owner_uses.recorded(flow.key, flow.pid).package(GAUGES_DIR), (
        "her removal of the rain package put the package his node counted in on her record"
    )
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)


def test_her_save_of_the_whole_dataflow_leaves_the_package_his_node_counted_in_off_her_record(
    app, client, flow, sandbox,
):
    """A save that sends the whole dataflow, as a script's does (a tab sends
    none: the dataflow's doc keeps it), writes out alice's lockfile as it
    read, the gauge package bob's node counted in among its packages: none of
    them goes on her record of what the dataflow uses, and bob's play of his
    node still gets his own copy's modules."""
    from utk_curio.backend.app.collaboration import owner_uses
    from utk_curio.backend.app.projects import storage as projects_storage

    _counted_in_from_his_own_copy(app, client, flow, sandbox)

    resp = client.put(f"/api/projects/{flow.pid}", json={"spec": projects_storage.read_spec(flow.key, flow.pid)},
                      headers=_auth(flow.tokens["alice"]))

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert GAUGES_DIR in (_on_disk(flow).get("packages") or []), "her save left her lockfile naming no package"
    assert not owner_uses.recorded(flow.key, flow.pid).package(GAUGES_DIR), (
        "her save put the package his node counted in on her record"
    )
    assert _play(client, flow, sandbox, "bob", "gauge").get("package_modules") == _gauges(flow.bob_key)


def test_a_model_of_hers_an_editor_binds_to_a_node_loads_in_his_runs_only_once_she_binds_it(
    app, client, flow, sandbox,
):
    """bob's tab binds alice's second model to her ``private`` node, and his
    own model to a node he adds. His play of ``private`` loads no model of
    hers, his own node loads his model, and her play of ``private`` loads
    hers. Once alice binds the model to her ``private-2`` node herself, bob's
    play of ``private`` loads it from her store."""
    bob = _tab(app, flow, "bob")
    _edit(bob, _bound("private", PRIVATE_MODEL))
    _edit(bob, _with_node(_node("bobs-model", modelRefs=[{"id": BOBS_MODEL}])))

    assert _play(client, flow, sandbox, "bob", "private").get("models") is None
    assert _play(client, flow, sandbox, "bob", "bobs-model").get("models") == {
        BOBS_MODEL: _folder(flow.bob_key, f"{BOBS_MODEL}@1"),
    }
    hers = {PRIVATE_MODEL: _folder(flow.key, f"{PRIVATE_MODEL}@1")}
    assert _play(client, flow, sandbox, "alice", "private").get("models") == hers

    _edit(_tab(app, flow, "alice"), _bound("private-2", PRIVATE_MODEL))
    assert _play(client, flow, sandbox, "bob", "private").get("models") == hers


# ---------------------------------------------------------------------------
# Agents, and what the owner takes out
# ---------------------------------------------------------------------------

def test_what_an_agent_run_adds_is_within_an_editors_reach_only_when_the_owner_asked_for_it(
    app, client, flow, sandbox,
):
    """An agent run bob asked for adds a node of alice's Scout, Scout to the
    lockfile, and her salaries to the datasets: his runs get neither from her
    store. An agent run alice asked for adds another node of Scout and lists
    the salaries again: bob's runs then get both from her store."""

    def bobs(dataflow: dict) -> None:
        dataflow["nodes"].append(_node("calc"))
        dataflow["packages"] = [*dataflow["packages"], SCOUT_DIR]
        dataflow["datasets"] = [*dataflow["datasets"], _ref(flow.salaries)]

    _agents_change(app, flow, "bob", bobs)
    assert _play(client, flow, sandbox, "bob", "calc").get("package_modules") is None
    assert _loaded(client, flow, sandbox, "bob", flow.salaries) == {}

    def alices(dataflow: dict) -> None:
        dataflow["nodes"].append(_node("calc-2"))
        dataflow["datasets"] = [ref for ref in dataflow["datasets"] if ref.get("datasetId") != flow.salaries["id"]]
        dataflow["datasets"].append(_ref(flow.salaries, installed_at="2000-01-02T00:00:00Z"))

    _agents_change(app, flow, "alice", alices)
    assert _play(client, flow, sandbox, "bob", "calc")["package_modules"]["root"] == _sources(flow.key, SCOUT_DIR)
    assert set(_loaded(client, flow, sandbox, "bob", flow.salaries)) == {flow.salaries["id"]}


def test_an_item_she_takes_out_stays_out_of_an_editors_reach_when_he_puts_it_back(app, client, flow, sandbox):
    """bob's tab takes alice's street trees out of her dataflow and puts them
    back, as his Undo does: his run still loads them. Once alice takes them
    out herself, bob's tab putting them back leaves them out of his runs,
    while hers load them."""
    bob = _tab(app, flow, "bob")
    trees = _ref(flow.trees)

    def without_trees(dataflow: dict) -> None:
        dataflow["datasets"] = [ref for ref in dataflow["datasets"] if ref.get("datasetId") != flow.trees["id"]]

    def with_trees(dataflow: dict) -> None:
        dataflow["datasets"] = [*dataflow["datasets"], trees]

    _edit(bob, without_trees)
    _edit(bob, with_trees)
    assert set(_loaded(client, flow, sandbox, "bob", flow.trees)) == {flow.trees["id"]}

    _edit(_tab(app, flow, "alice"), without_trees)
    _edit(bob, with_trees)
    assert trees in _on_disk(flow)["datasets"]
    assert _loaded(client, flow, sandbox, "bob", flow.trees) == {}
    assert set(_loaded(client, flow, sandbox, "alice", flow.trees)) == {flow.trees["id"]}


# ---------------------------------------------------------------------------
# The skills of her packages in an editor's chat
# ---------------------------------------------------------------------------

def test_a_package_an_editor_adds_to_her_lockfile_brings_no_skill_into_his_chat_until_she_adds_it(
    app, client, flow, monkeypatch,
):
    """bob's tab adds alice's Scout to her dataflow's lockfile. His chat
    neither lists the skill her Scout ships nor tells its model the skill's
    words, while alice's chat does both. Once alice adds a node of Scout
    herself, bob's chat lists the skill and tells its model too."""
    from xml.sax.saxutils import escape

    scout = _scout_skill(flow)
    words = escape(scout.description)
    _owners_model(client, flow)
    _edit(_tab(app, flow, "bob"), lambda dataflow: dataflow.__setitem__(
        "packages", [*dataflow["packages"], SCOUT_DIR],
    ))
    assert SCOUT_DIR in _on_disk(flow)["packages"]

    assert scout.name not in _chat_skills(client, flow, "bob")
    assert words not in _told(client, flow, monkeypatch, "bob")
    assert scout.name in _chat_skills(client, flow, "alice")
    assert words in _told(client, flow, monkeypatch, "alice")

    _edit(_tab(app, flow, "alice"), _with_node(_node("calc-2")))
    assert scout.name in _chat_skills(client, flow, "bob")
    assert words in _told(client, flow, monkeypatch, "bob")
