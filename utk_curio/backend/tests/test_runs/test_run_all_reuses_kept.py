"""A Run All reuses what its steps kept, as a dashboard visitor's step does
(dataflow audit step 6, step 9).

A dashboard viewer's step builds its key (``kept.step_call``,
``kept.call_key``), looks for an output kept under it (``kept.kept_output``)
and, when one is there, answers with it and runs nothing. The reused output
keeps its names, so the steps below it key the same and are reused too. The
owner's and an invited editor's runs on the server ask the same, of what the
runs of their maker kept of the same node, unless the run was asked for that
node: a Play's node, the nodes of an automatic run. A request of the
browser's Run All asks it too, saying ``reuseKept``.

- two Run Alls with nothing changed: the second sends the sandbox no node run,
  keeps no new output, replaces none, writes no folder, and each of its steps
  hands on the first run's output, saying when that was made;
- a Run All after one node's code changed runs that node and the nodes below
  it, and reuses the ones above;
- a Play runs its node and reuses the nodes above it that it runs; so does an
  automatic run of named nodes;
- an editor's first Run All reuses none of the owner's outputs, and his second
  reuses his first one's;
- a reused output is saved as a run's is: a Save turned on since the first
  run, or a node played with other code in between and set back;
- an editor's key holds the owner's packages: once she installs one, his
  reopen shows none of his results and his next Run All runs every node;
- a reused step counts no node run and adds no runtime journal entry;
- the key a step looks up is the key its run kept, for a node that reads a
  dataset, a layer group or a collection, a JavaScript node and an Autark
  node that only loads data;
- ``/processPythonCode`` with ``reuseKept`` runs a node once and answers the
  second request from what it kept; without it, it runs twice; with it, a
  replaced output and one past its 7 days are not reused, and a JavaScript
  node that saves reuses no output its run did not save;
- ``reset-db`` empties the kept outputs.

The sandbox is a fake behind ``node_exec.sandbox_request``: each run of a node
answers an artifact named after its node and its turn, as the store names
every run's output anew, and a node whose code says ``# derive`` first writes
a file in its run's folder, as a node that derives a frame does. The database
is a file (``test_runs/conftest.py``). Names main lacks are read inside the
tests, so the module imports there and each test fails on its own.
"""
from __future__ import annotations

import io
import json
import re
import threading
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

CODE = "curio.builtin/python-computation"
JS = "curio.builtin/js-computation"
AUTARK = "curio.builtin/autk-grammar"
REPO = Path(__file__).resolve().parents[4]
#: The committed street survey: a collection every account's Data Catalog holds.
SURVEY = "data.curio.storage-survey"
TOKENS = {"bob": "bob-token-for-run-all-reuse"}
TREES = b"tree,species\n1,elm\n2,oak\n"
#: An Autark document that only loads data: Back Bay's roads.
ROADS = {"data": [{"type": "osm", "pbfFileUrl": "docs/examples/data/back_bay.osm.pbf",
                   "outputTableName": "table_osm", "autoLoadLayers": {"layers": ["surface", "roads"]}}]}
#: What names a node in the code the sandbox is sent, which carries no id.
NODE_MARK = re.compile(r"(?:#|//) node (\S+)")
CHAIN = ("load", "draw", "read")


class _Reply:
    status_code = 200
    ok = True
    text = ""
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        yield json.dumps(self._payload).encode("utf-8")

    def close(self):
        pass


class Sandbox:
    """Answers each ``/exec`` and ``/execJs`` with a new artifact named after
    the node and its turn, the store's name of that run's output, which is all
    its session made. An Autark node's load answers a layer list. A node whose
    code says ``# derive`` first writes a file in the run's folder
    (``media_dir``). Every node run is kept, in order (:meth:`sent`)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.runs: list[tuple[str, str]] = []
        self.bodies: dict = {}
        self.made: dict = {}
        self.forgotten: list = []
        self.other: list = []

    def sent(self) -> list[str]:
        """The nodes sent to the sandbox to run, in order."""
        with self.lock:
            return [node for _path, node in self.runs]

    def __call__(self, method, path, **kwargs):
        if path not in ("/exec", "/execJs"):
            with self.lock:
                self.other.append(path)
            return _Reply({})
        body = json.loads(kwargs["data"])
        found = NODE_MARK.search(body["code"])
        node = found.group(1) if found else str(body.get("nodeType") or "").rsplit("/", 1)[-1]
        if "# derive" in body["code"] and body.get("media_dir"):
            folder = Path(body["media_dir"])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{node}.png").write_bytes(b"\x89PNG derived")
        with self.lock:
            self.runs.append((path, node))
            made = f"art-{node}-{len(self.runs)}"
            self.made[body["session_id"]] = made
            self.bodies[node] = body
        data_type = "list" if path == "/execJs" and not found else "dataframe"
        return _Reply({"stdout": [f"ran {node}"], "stderr": "", "output": {"path": made, "dataType": data_type}})

    def sessions(self, method, path, **kwargs):
        named = json.loads(kwargs["data"])["sessionIds"]
        if path.endswith("/describe"):
            with self.lock:
                return _Reply({"sessions": {s: {"bytes": 10, "ids": [self.made.get(s, "")]} for s in named}})
        with self.lock:
            self.forgotten.extend(named)
        return _Reply({"forgotten": len(named)})


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import jobs, kept

    # Nothing is installed unless a test says so: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = Sandbox()
    monkeypatch.setattr(node_exec, "sandbox_request", fake)
    monkeypatch.setattr(kept, "sandbox_request", fake.sessions)
    yield fake
    jobs.REGISTRY.reset()


@pytest.fixture()
def saved(monkeypatch):
    """What a run installs in the Data Catalog (``auto_install_node_output``)
    and records in the dataflow (``record_node_outputs``): ``(node, artifact)``
    each, in order."""
    from utk_curio.backend.app.datasets.application import auto_install
    from utk_curio.backend.app.projects import services as project_services

    state = SimpleNamespace(installed=[], recorded=[])

    def install(**kwargs):
        state.installed.append((kwargs["node_id"], (kwargs.get("sandbox_output") or {}).get("path")))
        return {"status": "skipped", "nodeId": kwargs.get("node_id"), "reason": "the test's fake artifacts are not files"}

    def record(user, project_id, outputs, warnings=None, **_kwargs):
        state.recorded.extend((ref.node_id, ref.filename) for ref in outputs)
        return []

    monkeypatch.setattr(auto_install, "auto_install_node_output", install)
    monkeypatch.setattr(project_services, "record_node_outputs", record)
    return state


@pytest.fixture()
def counted(monkeypatch):
    """The measures the monitor's Usage tab counts from now on, by name."""
    from utk_curio.backend.app.monitor import usage

    keys: list[str] = []
    lock = threading.Lock()

    def record(key, *, ms, failed=False):
        with lock:
            keys.append(key)

    monkeypatch.setattr(usage, "record", record)
    return keys


def _account(db, username: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=TOKENS[username]))
    db.session.commit()
    return user


@pytest.fixture()
def people(db, user_and_token):
    alice, alice_token = user_and_token
    return SimpleNamespace(alice=alice, bob=_account(db, "bob"), tokens={"alice": alice_token, **TOKENS})


def _node(node_id, body="return input_0", **fields):
    return {"id": node_id, "type": CODE, "content": f"# node {node_id}\n{body}", **fields}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target, "targetHandle": "in"}


def _chain(draw="return input_0", **draw_fields):
    """load, then draw, which derives a file from what load gave it, then
    read, which reads draw's rows."""
    nodes = [_node("load", "return 1"), _node("draw", f"# derive\n{draw}", **draw_fields), _node("read")]
    return nodes, [_edge("load", "draw"), _edge("draw", "read")]


def _spec(nodes, edges, name):
    return {"dataflow": {"name": name, "nodes": list(nodes), "edges": list(edges)}}


def _create(client, token, nodes, edges=(), name="Reuse"):
    resp = client.post("/api/projects", data=json.dumps({
        "name": name, "spec": _spec(nodes, edges, name), "outputs": [],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _resave(client, token, project_id, nodes, edges=(), name="Reuse"):
    resp = client.put(f"/api/projects/{project_id}", data=json.dumps({
        "name": name, "spec": _spec(nodes, edges, name),
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _alices(client, people, nodes, edges=()):
    """alice's dataflow of *nodes*, with bob invited to edit it."""
    from utk_curio.backend.app.projects import access

    project_id = _create(client, people.tokens["alice"], nodes, edges)
    access.add_editor(people.alice, project_id, "bob")
    return project_id


def _run(client, token, project_id, **body) -> dict:
    """A run on the server of *project_id*, the whole dataflow unless *body*
    names a ``target`` or ``targets``, to its end: its record, with its steps."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    resp = client.post(f"/api/projects/{project_id}/runs", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 202, resp.get_data(as_text=True)
    run_id = resp.get_json()["id"]
    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None, "no job holds the run"
    job.thread.join(timeout=60)
    assert not job.thread.is_alive(), "the run did not end"
    # End this thread's read, so it sees what the run's threads committed.
    db.session.rollback()
    record = client.get(f"/api/runs/{run_id}", headers=auth_headers(token))
    assert record.status_code == 200, record.get_data(as_text=True)
    return record.get_json()


def _steps(run) -> dict:
    return {step["nodeId"]: step for step in run["steps"]}


def _outputs(run) -> dict:
    return {node: step["outputPath"] for node, step in _steps(run).items()}


def _reused(run) -> dict:
    """``{node: when the output it reused was made}``, None for a step that ran."""
    return {node: step.get("reusedMadeAt") for node, step in _steps(run).items()}


def _kept(project_id) -> list:
    from utk_curio.backend.app.runs.models import KeptStepOutput

    return KeptStepOutput.query.filter_by(project_id=project_id).all()


def _made_at(entries) -> dict:
    """``{node: when its newest kept output was made}``, as a step's record says it."""
    from utk_curio.backend.app.runs.service import _iso

    newest: dict = {}
    for entry in sorted(entries, key=lambda e: e.created_at):
        newest[entry.node_id] = _iso(entry.created_at)
    return newest


def _folders() -> set:
    from utk_curio.backend.app.discovery.infrastructure import media_dirs

    return {str(folder) for _account, folder in media_dirs.run_folders()}


def _open(client, token, project_id) -> dict:
    """``{node: output}`` the canvas of *token* opens *project_id* with
    (``?results=last``)."""
    resp = client.get(f"/api/projects/{project_id}", query_string={"results": "last"}, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {output["node_id"]: output["filename"] for output in resp.get_json()["outputs"]}


# ---------------------------------------------------------------------------
# A Run All reuses; the nodes a run is asked for run
# ---------------------------------------------------------------------------

def test_a_second_run_all_with_nothing_changed_runs_nothing_and_keeps_nothing_new(client, user_and_token, sandbox):
    _user, token = user_and_token
    project_id = _create(client, token, *_chain())
    first = _run(client, token, project_id)
    assert sandbox.sent() == list(CHAIN)
    assert first["status"] == "succeeded", first
    kept_first = {(entry.id, entry.node_id, entry.output_path) for entry in _kept(project_id)}
    folders = _folders()
    assert len(folders) == 1, f"draw's run derived into a folder of its own: {folders}"

    second = _run(client, token, project_id)

    assert sandbox.sent() == list(CHAIN), "the second Run All sent the sandbox a node run"
    assert second["status"] == "succeeded", second
    assert {node: step["status"] for node, step in _steps(second).items()} == {node: "ok" for node in CHAIN}
    assert _outputs(second) == _outputs(first), "the second Run All handed on other outputs than the first's"
    entries = _kept(project_id)
    assert {(entry.id, entry.node_id, entry.output_path) for entry in entries} == kept_first, (
        "the second Run All kept outputs of its own"
    )
    assert [entry.node_id for entry in entries if entry.replaced_at is not None] == []
    assert _folders() == folders, "the second Run All wrote a folder"
    assert _reused(second) == _made_at(entries), "a reused step does not say when the output it reused was made"
    assert all(not step.get("stdoutTail") for step in second["steps"]), "a reused step printed logs"


def test_a_run_all_after_one_nodes_code_changed_runs_it_and_the_nodes_below_and_reuses_those_above(
    client, user_and_token, sandbox,
):
    _user, token = user_and_token
    project_id = _create(client, token, *_chain())
    first = _run(client, token, project_id)
    _resave(client, token, project_id, *_chain("# drawn in blue now\nreturn input_0"))

    second = _run(client, token, project_id)

    assert sandbox.sent() == [*CHAIN, "draw", "read"], "the Run All did not run exactly the changed node and below"
    assert _outputs(second)["load"] == _outputs(first)["load"]
    assert _reused(second)["load"] is not None
    for node in ("draw", "read"):
        assert _outputs(second)[node] != _outputs(first)[node], node
        assert _reused(second)[node] is None, node


@pytest.mark.parametrize("asked", [{"target": "read"}, {"targets": ["read"]}], ids=["play", "automatic-run"])
def test_the_node_a_run_is_asked_for_runs_and_the_nodes_above_it_reuse(client, user_and_token, sandbox, asked):
    """A Play always runs its node, though its key holds an output: that is
    how a node that reads what its key cannot see gets a fresh result. So
    does an automatic run, which names the nodes a widget's change made
    stale. The nodes above them, which the run needs and the canvas sent no
    output of, reuse what was kept."""
    _user, token = user_and_token
    project_id = _create(client, token, *_chain())
    first = _run(client, token, project_id)

    asked_run = _run(client, token, project_id, **asked)

    assert sandbox.sent() == [*CHAIN, "read"], "the run did not run exactly the node it was asked for"
    assert _outputs(asked_run)["read"] != _outputs(first)["read"]
    assert _reused(asked_run)["read"] is None
    assert {node: _outputs(asked_run)[node] for node in ("load", "draw")} == {
        node: _outputs(first)[node] for node in ("load", "draw")
    }
    assert all(_reused(asked_run)[node] for node in ("load", "draw"))


def test_an_editors_first_run_all_reuses_none_of_the_owners_outputs_and_his_second_reuses_his_own(
    client, people, sandbox,
):
    """The owner's kept results are hers alone (owner, 10-25): bob's runs
    reuse only what his own runs kept."""
    project_id = _alices(client, people, *_chain())
    _run(client, people.tokens["alice"], project_id)
    bobs_first = _run(client, people.tokens["bob"], project_id)
    assert sandbox.sent() == [*CHAIN, *CHAIN], "bob's first Run All reused an output alice's run kept"
    assert set(_reused(bobs_first).values()) == {None}

    bobs_second = _run(client, people.tokens["bob"], project_id)

    assert sandbox.sent() == [*CHAIN, *CHAIN], "bob's second Run All ran again what his first kept"
    assert _outputs(bobs_second) == _outputs(bobs_first)


# ---------------------------------------------------------------------------
# A reused output is saved as a run's is
# ---------------------------------------------------------------------------

def test_a_reused_output_whose_save_was_turned_on_since_is_installed_and_recorded(
    client, user_and_token, sandbox, saved,
):
    _user, token = user_and_token
    project_id = _create(client, token, *_chain())
    first = _outputs(_run(client, token, project_id))
    assert "draw" not in {node for node, _artifact in saved.recorded}
    _resave(client, token, project_id, *_chain(saveOutputDataset=True))

    _run(client, token, project_id)

    assert sandbox.sent() == list(CHAIN), "the Run All ran draw again for its Save"
    assert ("draw", first["draw"]) in saved.recorded, f"draw's reused output was not recorded: {saved.recorded}"
    assert ("draw", first["draw"]) in saved.installed, f"draw's reused output was not installed: {saved.installed}"


def test_a_node_played_with_other_code_then_set_back_saves_the_output_its_first_run_kept(
    client, user_and_token, sandbox, saved,
):
    _user, token = user_and_token
    project_id = _create(client, token, *_chain(saveOutputDataset=True))
    first = _outputs(_run(client, token, project_id))
    _resave(client, token, project_id, *_chain("# in blue\nreturn input_0", saveOutputDataset=True))
    _run(client, token, project_id, target="draw")
    _resave(client, token, project_id, *_chain(saveOutputDataset=True))

    back = _run(client, token, project_id)

    assert sandbox.sent() == [*CHAIN, "draw"], "the Run All after draw's code was set back ran a node"
    assert _outputs(back) == first
    drawn = [artifact for node, artifact in saved.recorded if node == "draw"]
    assert drawn[-1] == first["draw"], f"the dataflow saved {drawn[-1]!r}, not the output draw shows"


# ---------------------------------------------------------------------------
# An editor's key holds the owner's packages
# ---------------------------------------------------------------------------

def _install_a_package(user) -> None:
    """A package of *user*'s own, as an install leaves it in her store."""
    from utk_curio.backend.app.packages.repositories.store import user_packages_dir
    from utk_curio.backend.app.projects.services import _user_dir_key

    folder = user_packages_dir(_user_dir_key(user)) / "test.run-all-tools@1"
    (folder / "sources").mkdir(parents=True, exist_ok=True)
    (folder / "sources" / "depth.py").write_text("return 1\n", encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({
        "id": "test.run-all-tools", "version": "1.0.0", "name": "Run All tools", "publisher": "Test",
        "license": "MIT", "compatibility": {"major": 1}, "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [{
            "id": "depth", "label": "Depth", "category": "computation", "engine": "python", "editor": "code",
            "behavior": "code", "hasCode": True, "inputPorts": [],
            "outputPorts": [{"types": ["JSON"], "cardinality": "1"}], "source": "sources/depth.py",
        }],
    }), encoding="utf-8")


def test_an_editors_key_holds_the_owners_packages(client, people, sandbox):
    """bob's runs use alice's packages for her dataflow's nodes, so what his
    runs kept is keyed by her store too: once she installs a package, his
    reopen shows none of his results, and his next Run All runs every node."""
    project_id = _alices(client, people, *_chain())
    bob = people.tokens["bob"]
    _run(client, bob, project_id)
    second = _run(client, bob, project_id)
    assert sandbox.sent() == list(CHAIN), "bob's second Run All ran again what his first kept"
    assert _open(client, bob, project_id) == _outputs(second)

    _install_a_package(people.alice)

    assert _open(client, bob, project_id) == {}, "bob's reopen shows results kept before alice's packages changed"
    _run(client, bob, project_id)
    assert sandbox.sent() == [*CHAIN, *CHAIN], "bob's Run All after alice's install reused what her old packages made"


# ---------------------------------------------------------------------------
# A reused step is no node run
# ---------------------------------------------------------------------------

def test_a_reused_step_counts_no_node_run_and_adds_no_journal_entry(client, user_and_token, sandbox, counted):
    from utk_curio.backend.app.execution import runtime_journal
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = _create(client, token, *_chain())
    _run(client, token, project_id)
    assert counted.count("node.python") == 3 and counted.count("run") == 1, counted

    def seqs():
        return {node: (runtime_journal.read_record(_user_dir_key(user), project_id, node) or {}).get("executionSeq")
                for node in CHAIN}

    before = seqs()
    assert all(before.values()), before

    _run(client, token, project_id)

    assert counted.count("node.python") == 3, f"the reused steps counted as node runs: {counted}"
    assert counted.count("run") == 2, counted
    assert seqs() == before, "a reused step added a runtime journal entry"


# ---------------------------------------------------------------------------
# The key a step looks up is the key its run kept
# ---------------------------------------------------------------------------

def _listed(client, token, project_id, dataset_id):
    resp = client.post(f"/api/dataflows/{project_id}/datasets/install",
                       data=json.dumps({"datasetId": dataset_id}), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _a_dataset(client, token, tmp_path, monkeypatch):
    imported = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {token}"},
        data={"file": (io.BytesIO(TREES), "trees.csv")}, content_type="multipart/form-data",
    )
    assert imported.status_code == 201, imported.get_data(as_text=True)
    trees = imported.get_json()["id"]
    return _node("step", f'trees = curio_load_data("{trees}")\nreturn trees'), trees


def _a_layer_group(client, token, tmp_path, monkeypatch):
    from utk_curio.backend.tests.test_datasets.test_layer_group_execution import _imported_group

    group_id, _layers = _imported_group(client, token, tmp_path, monkeypatch)
    return _node("step", f'layers = curio_load_data("{group_id}")\nreturn layers'), None


def _a_collection(client, token, tmp_path, monkeypatch):
    from utk_curio.backend.app.discovery.infrastructure import storage as discovery_storage

    monkeypatch.setenv(discovery_storage.ENV_ROOT, str(REPO / "discovery"))
    return _node("step", f'rows = curio_load_collection("{SURVEY}")\nreturn rows'), None


def _a_javascript_node(client, token, tmp_path, monkeypatch):
    return {"id": "step", "type": JS, "content": "// node step\nreturn 1;"}, None


def _an_autark_load(client, token, tmp_path, monkeypatch):
    return {"id": "step", "type": AUTARK, "content": json.dumps(ROADS)}, None


@pytest.mark.parametrize("make", [_a_dataset, _a_layer_group, _a_collection, _a_javascript_node, _an_autark_load],
                         ids=["dataset", "layer-group", "collection", "javascript", "autark-load"])
def test_the_key_a_step_looks_up_is_the_key_its_run_kept(client, user_and_token, sandbox, tmp_path, monkeypatch, make):
    """Each kind of step whose key is built from something else than its code
    and its inputs: a key that did not match would only make it run again,
    which no other test would see."""
    _user, token = user_and_token
    node, dataset_id = make(client, token, tmp_path, monkeypatch)
    project_id = _create(client, token, [node])
    if dataset_id:
        _listed(client, token, project_id, dataset_id)
    first = _run(client, token, project_id)
    assert _steps(first)["step"]["status"] == "ok", first
    assert len(sandbox.sent()) == 1, sandbox.sent()

    second = _run(client, token, project_id)

    assert len(sandbox.sent()) == 1, "the second Run All ran the step again: the key it looked up is not the key kept"
    assert _outputs(second) == _outputs(first)
    assert _reused(second)["step"] is not None


# ---------------------------------------------------------------------------
# A request of the browser's Run All
# ---------------------------------------------------------------------------

def _post(client, token, project_id, *, reuse, path="/processPythonCode", save=False):
    python = path == "/processPythonCode"
    body = {
        "code": "    # node a\n    return 1\n" if python else "// node a\nreturn 1;",
        "nodeType": f"{CODE}@1" if python else f"{JS}@1", "nodeId": "a", "dataflowId": project_id,
        "input": "", "saveOutputDataset": save,
    }
    if reuse:
        body["reuseKept"] = True
    resp = client.post(path, data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def test_a_request_that_may_reuse_runs_its_node_once_and_answers_the_second_from_what_it_kept(
    client, user_and_token, sandbox, counted,
):
    _user, token = user_and_token
    project_id = _create(client, token, [_node("a", "return 1")])
    first = _post(client, token, project_id, reuse=True)

    second = _post(client, token, project_id, reuse=True)

    assert sandbox.sent() == ["a"], "the request that may reuse ran its node again"
    assert second["output"]["path"] == first["output"]["path"]
    assert (second.get("reused") or {}).get("madeAt"), second
    assert second["stdout"] == [] and second["stderr"] == ""
    assert counted.count("node.python") == 1, counted


def test_a_request_without_the_flag_runs_its_node_every_time(client, user_and_token, sandbox):
    """guard: a Play's request always runs."""
    _user, token = user_and_token
    project_id = _create(client, token, [_node("a", "return 1")])
    _post(client, token, project_id, reuse=False)
    second = _post(client, token, project_id, reuse=False)

    assert sandbox.sent() == ["a", "a"]
    assert "reused" not in second or not second["reused"]


def test_a_replaced_output_and_one_past_its_days_are_not_reused(client, user_and_token, sandbox, monkeypatch):
    """guard: the outputs a reuse may pick are the dashboard's, live and not
    replaced."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
    from utk_curio.backend.extensions import db

    _user, token = user_and_token
    project_id = _create(client, token, [_node("a", "return 1")])
    _post(client, token, project_id, reuse=False)
    db.session.query(KeptStepOutput).filter_by(project_id=project_id).update({"replaced_at": naive_utc_now()})
    db.session.commit()
    _post(client, token, project_id, reuse=True)
    assert sandbox.sent() == ["a", "a"], "a replaced output was reused"

    later = naive_utc_now() + timedelta(days=kept.KEPT_DAYS + 1)
    monkeypatch.setattr(kept, "naive_utc_now", lambda: later)
    _post(client, token, project_id, reuse=True)
    assert sandbox.sent() == ["a", "a", "a"], "an output past its days was reused"


def test_a_javascript_node_that_saves_reuses_no_output_its_run_did_not_save(client, user_and_token, sandbox):
    """guard: a JavaScript node's saved table is an artifact its run makes
    only when it saves (``output.dataset``)."""
    _user, token = user_and_token
    project_id = _create(client, token, [{"id": "a", "type": JS, "content": "// node a\nreturn 1;"}])
    _post(client, token, project_id, reuse=False, path="/processJavaScriptCode", save=False)

    _post(client, token, project_id, reuse=True, path="/processJavaScriptCode", save=True)

    assert sandbox.sent() == ["a", "a"], "a JavaScript node that saves reused an output its run did not save"


# ---------------------------------------------------------------------------
# reset-db
# ---------------------------------------------------------------------------

def test_reset_db_empties_the_kept_outputs(client, user_and_token, sandbox):
    from utk_curio.backend.app.runs.models import KeptStepOutput
    from utk_curio.backend.extensions import db

    _user, token = user_and_token
    _run(client, token, _create(client, token, *_chain()))
    assert KeptStepOutput.query.count() == len(CHAIN)

    resp = client.post("/api/testing/reset-db", data="{}", content_type="application/json")

    assert resp.status_code == 200, resp.get_data(as_text=True)
    db.session.rollback()
    assert KeptStepOutput.query.count() == 0, "reset-db left the kept outputs of the dataflows it emptied"
