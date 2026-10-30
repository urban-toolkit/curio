"""An invited editor's runs on the server, of the owner's dataflow.

alice owns a dataflow. bob is an editor she invited, erin was one until alice
took her off the list, and carol was never invited. bob runs alice's dataflow
on the server as alice does: the run reads her dataflow from her store, and it
is bob's. Its record is in his runs, not hers; it counts toward his cap; he
follows it and stops it; and its steps run as his Play does, in his session,
with nothing kept or recorded as alice's and nothing written into his store.
The datasets alice's dataflow lists load in his run. erin and carol run
nothing, as before.

The sandbox is a fake behind ``node_exec.sandbox_request``, as in
``test_run_routes.py``. Names main lacks are imported inside the tests, so
the module imports there and each test fails on its own.
"""
from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

CODE = "curio.builtin/computation-analysis"
TOKENS = {"bob": "bob-token-for-runs", "carol": "carol-token-for-runs", "erin": "erin-token-for-runs"}
TREES = b"tree,species\n1,elm\n2,oak\n"


def _node(node_id, content=None, **fields):
    # The marker names the node in the sandbox request, which carries no id.
    body = content if content is not None else "return input_0"
    return {"id": node_id, "type": CODE, "content": f"# node {node_id}\n{body}", **fields}


def _edge(source, target):
    return {"id": f"{source}-{target}", "source": source, "target": target}


class FakeSandbox:
    """Answers ``/exec`` with an artifact named after the node; *hold* keeps
    the named nodes running until :meth:`release`. Each node's last request
    body is in :attr:`bodies`."""

    def __init__(self):
        self.hold = set()
        self.gate = threading.Event()
        self.started = threading.Event()
        self.bodies = {}

    def release(self):
        self.gate.set()

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.bodies[node_id] = body
        self.started.set()
        if node_id in self.hold:
            assert self.gate.wait(timeout=30), "the test never released the gate"

        class Reply:
            status_code = 200
            text = ""

            def json(_self):
                return {"stdout": [f"ran {node_id}"], "stderr": "",
                        "output": {"path": f"art-{node_id}", "dataType": "dataframe"}}

        return Reply()


@pytest.fixture()
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.runs import jobs

    # Nothing is installed unless a test says so: the fake artifacts are not files.
    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    yield fake
    fake.release()


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
    return SimpleNamespace(
        alice=alice, bob=_account(db, "bob"), carol=_account(db, "carol"), erin=_account(db, "erin"),
        tokens={"alice": alice_token, **TOKENS},
    )


def _create(client, token, nodes, edges=(), name="Street trees"):
    resp = client.post("/api/projects", data=json.dumps({
        "name": name,
        "spec": {"dataflow": {"name": name, "nodes": list(nodes), "edges": list(edges)}},
        "outputs": [],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _alices(client, people, nodes, edges=()):
    """alice's dataflow of *nodes*, with bob invited to edit it and erin
    invited, then taken off."""
    from utk_curio.backend.app.projects import access

    project_id = _create(client, people.tokens["alice"], nodes, edges)
    access.add_editor(people.alice, project_id, "bob")
    access.add_editor(people.alice, project_id, "erin")
    access.remove_editor(people.alice, project_id, people.erin.id)
    return project_id


def _start(client, token, project_id, **body):
    return client.post(f"/api/projects/{project_id}/runs", data=json.dumps(body), headers=auth_headers(token))


def _started(client, token, project_id, **body) -> str:
    resp = _start(client, token, project_id, **body)
    assert resp.status_code == 202, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _wait(run_id):
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    # End this thread's read, so it sees what the run's threads committed.
    db.session.rollback()
    return job


def _get(client, token, run_id):
    resp = client.get(f"/api/runs/{run_id}", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _events(client, token, run_id):
    resp = client.get(f"/api/runs/{run_id}/stream", headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    events = []
    for block in resp.get_data(as_text=True).strip().split("\n\n"):
        kind = block.split("\n", 1)[0].removeprefix("event: ")
        events.append((kind, json.loads(block.split("data: ", 1)[1])))
    return events


def _listed(client, token, path):
    resp = client.get(path, headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [run["id"] for run in resp.get_json()["runs"]]


# ---------------------------------------------------------------------------
# Who runs the dataflow on the server
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("who, status", [("bob", 202), ("erin", 404), ("carol", 404)],
                         ids=["editor", "removed-editor", "uninvited"])
def test_an_editor_she_invited_runs_her_dataflow_and_no_one_else_does(
    client, people, sandbox, who, status,
):
    """bob's start of alice's dataflow is a run, and he lists it among his runs
    of her dataflow. erin, whom alice took off her editors and who only watches
    now, and carol, never invited, are told the dataflow is not found, as
    before."""
    project_id = _alices(client, people, [_node("a")])

    started = _start(client, people.tokens[who], project_id)

    assert started.status_code == status, started.get_data(as_text=True)
    listing = client.get(f"/api/projects/{project_id}/runs", headers=auth_headers(people.tokens[who]))
    if status == 404:
        assert started.get_json()["error"] == "Dataflow not found."
        assert listing.status_code == 404, listing.get_data(as_text=True)
        assert "a" not in sandbox.bodies
        return
    run_id = started.get_json()["id"]
    _wait(run_id)
    assert listing.status_code == 200, listing.get_data(as_text=True)
    assert [run["id"] for run in listing.get_json()["runs"]] == [run_id]


def test_an_editor_starts_follows_and_cancels_a_run_on_the_owners_dataflow(client, people, sandbox):
    """bob's run of alice's dataflow is his: he reads it as it goes, stops it
    before its next node, and reads its events once it ended. Its record names
    alice's dataflow and bob. Neither alice nor carol reads or stops it."""
    from utk_curio.backend.app.runs.models import DataflowRun
    from utk_curio.backend.extensions import db

    project_id = _alices(client, people, [_node("a"), _node("b")], [_edge("a", "b")])
    bob = people.tokens["bob"]
    sandbox.hold = {"a"}

    run_id = _started(client, bob, project_id)
    assert sandbox.started.wait(timeout=10)
    db.session.rollback()
    going = _get(client, bob, run_id)
    assert going["status"] == "running" and going["projectId"] == project_id
    for other in ("alice", "carol"):
        token = people.tokens[other]
        assert client.get(f"/api/runs/{run_id}", headers=auth_headers(token)).status_code == 404
        assert client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers(token)).status_code == 404
    stopped = client.post(f"/api/runs/{run_id}/cancel", headers=auth_headers(bob))
    assert stopped.status_code == 202, stopped.get_data(as_text=True)
    sandbox.release()
    _wait(run_id)

    ended = _get(client, bob, run_id)
    assert ended["status"] == "cancelled"
    assert {s["nodeId"]: s["status"] for s in ended["steps"]} == {"a": "cancelled", "b": "cancelled"}
    assert "b" not in sandbox.bodies
    events = _events(client, bob, run_id)
    assert events[-1][0] == "run_finished" and events[-1][1]["status"] == "cancelled"
    record = db.session.get(DataflowRun, run_id)
    assert (record.project_id, record.user_id) == (project_id, people.bob.id)


def test_an_editors_run_runs_as_the_editor_and_records_nothing_in_the_owners_dataflow(
    client, people, sandbox, monkeypatch,
):
    """alice's run records the output her dataflow saves and keeps each output
    as hers. bob's run of the same dataflow runs each step as his Play does:
    in his session, his store's key, with no dataset installed in his store.
    It records nothing in her dataflow and keeps nothing as hers, and each
    step says its node still holds the code it ran, read in alice's store."""
    from utk_curio.backend.app.datasets.application import auto_install
    from utk_curio.backend.app.projects import services as project_services
    from utk_curio.backend.app.runs.models import KeptStepOutput

    installs, recorded = [], []
    monkeypatch.setattr(
        auto_install, "auto_install_node_output",
        lambda **kwargs: installs.append((kwargs["node_id"], kwargs["dataflow_id"], kwargs["user"].id))
        or {"status": "skipped", "nodeId": kwargs.get("node_id")},
    )
    monkeypatch.setattr(
        project_services, "record_node_outputs",
        lambda user, project_id, outputs, warnings=None: recorded.extend(
            (o.node_id, user.id) for o in outputs) or [],
    )
    project_id = _alices(client, people, [_node("kept", saveOutputDataset=True), _node("plain")])
    alice, bob = people.alice, people.bob

    _wait(_started(client, people.tokens["alice"], project_id))
    assert recorded == [("kept", alice.id)]
    assert installs == [("kept", project_id, alice.id)]
    kept_by_alice = {(e.node_id, e.session_id) for e in KeptStepOutput.query.filter_by(project_id=project_id)}
    assert {node for node, _session in kept_by_alice} == {"kept", "plain"}

    run_id = _started(client, people.tokens["bob"], project_id)
    _wait(run_id)

    for node in ("kept", "plain"):
        body = sandbox.bodies[node]
        assert body["session_id"] == people.tokens["bob"], f"{node} ran in {body['session_id']!r}"
        assert body["imports_session"] == people.tokens["bob"]
        assert body["user_key"] == str(bob.id)
    assert recorded == [("kept", alice.id)], "bob's run recorded an output in alice's dataflow"
    assert installs[1:] == [("kept", None, bob.id)], "bob's run installed a dataset in his store"
    assert {(e.node_id, e.session_id) for e in KeptStepOutput.query.filter_by(project_id=project_id)} == kept_by_alice
    run = _get(client, people.tokens["bob"], run_id)
    assert run["status"] == "succeeded"
    assert {s["nodeId"]: s["codeCurrent"] for s in run["steps"]} == {"kept": True, "plain": True}


def test_each_account_lists_its_own_runs_of_the_dataflow(client, people, sandbox):
    """bob's run of alice's dataflow is in his runs, and in his runs of her
    dataflow; alice's lists of runs hold only her own."""
    project_id = _alices(client, people, [_node("a")])
    alices = _started(client, people.tokens["alice"], project_id)
    _wait(alices)
    bobs = _started(client, people.tokens["bob"], project_id)
    _wait(bobs)

    assert _listed(client, people.tokens["bob"], "/api/runs") == [bobs]
    assert _listed(client, people.tokens["bob"], f"/api/projects/{project_id}/runs") == [bobs]
    assert _listed(client, people.tokens["alice"], "/api/runs") == [alices]
    assert _listed(client, people.tokens["alice"], f"/api/projects/{project_id}/runs") == [alices]
    mine = client.get("/api/runs", headers=auth_headers(people.tokens["bob"])).get_json()["runs"][0]
    assert (mine["projectId"], mine["projectName"]) == (project_id, "Street trees")


def test_an_editors_run_counts_toward_the_editors_cap(client, people, sandbox):
    """bob's run of alice's dataflow is one of the two runs his account may
    have going: with it and a run of his own going, a third is refused. It is
    not alice's: she runs her dataflow while bob's run of it goes."""
    from utk_curio.backend.app.runs import jobs

    project_id = _alices(client, people, [_node("a")])
    bob = people.tokens["bob"]
    his_own = _create(client, bob, [_node("a")], name="Bob's own")
    his_third = _create(client, bob, [_node("c")], name="Bob's third")
    sandbox.hold = {"a"}

    going = [_started(client, bob, project_id), _started(client, bob, his_own)]
    refused = _start(client, bob, his_third)
    alices = _start(client, people.tokens["alice"], project_id)

    assert refused.status_code == 429, refused.get_data(as_text=True)
    assert refused.get_json()["error"] == jobs.REGISTRY.cap_message
    assert alices.status_code == 202, alices.get_data(as_text=True)
    sandbox.release()
    for run_id in [*going, alices.get_json()["id"]]:
        _wait(run_id)


def test_an_editors_run_loads_a_dataset_the_dataflow_lists(client, people, sandbox):
    """A node of alice's dataflow loads the street trees, a dataset of her Data
    Catalog her dataflow lists: in bob's run it resolves to her file, as in
    his Play (#1239)."""
    alice = people.tokens["alice"]
    imported = client.post(
        "/api/datasets/import",
        headers={"Authorization": f"Bearer {alice}"},
        data={"file": (io.BytesIO(TREES), "trees.csv")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 201, imported.get_data(as_text=True)
    trees = imported.get_json()["id"]
    project_id = _alices(client, people, [_node("load", f'd0 = curio_load_data("{trees}")\nreturn d0')])
    listed = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        data=json.dumps({"datasetId": trees}), headers=auth_headers(alice),
    )
    assert listed.status_code == 200, listed.get_data(as_text=True)

    _wait(_started(client, people.tokens["bob"], project_id))

    paths = sandbox.bodies["load"]["dataset_paths"]
    assert set(paths) == {trees}, f"bob's run resolved {paths}"
    assert Path(paths[trees]).read_bytes() == TREES
