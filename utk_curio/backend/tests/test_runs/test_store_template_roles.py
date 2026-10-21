"""A run on the server reads the account's own store for what a node's
template declares, then the catalog, then the packages Curio ships.

A package of the account's own can declare a Data Export's behavior for one
of its templates. A run of a dataflow holding such a node forwards what
reaches it, as it forwards a Data Export, for the account whose store holds
the package; for any other account no installed package provides the node's
type, so the run fails it, naming the type, and skips what it feeds, as the
canvas does with the card it shows for it. The sandbox is a fake behind
``node_exec.sandbox_request``. ``runs`` is imported inside each test, so a
checkout without it fails each test on its own.
"""
from __future__ import annotations

import json

import pytest


def _port() -> dict:
    return {"cardinality": "1", "types": ["DATAFRAME", "GEODATAFRAME"]}


#: A package of an account's own with a Data Export of its own, which only its store holds.
STORE_PACKAGE = {
    "id": "acme.mine",
    "name": "My nodes",
    "version": "1.0.0",
    "publisher": "alice",
    "license": "MIT",
    "description": "Nodes saved from a dataflow.",
    "createdAt": "2026-10-19T00:00:00Z",
    "compatibility": {"major": 1},
    "permissions": [],
    "dependencies": {"python": {}, "js": {}, "packages": {}},
    "templates": [
        {
            "id": "download", "label": "My download", "description": "", "category": "data",
            "engine": "python", "editor": "none", "behavior": "data-export",
            "hasCode": False, "hasGrammar": False, "hasWidgets": False,
            "inputPorts": [_port()], "outputPorts": [],
        },
    ],
}


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


class FakeSandbox:
    """Answers ``/exec`` with an artifact named after the node, and keeps
    each node's request."""

    def __init__(self):
        self.bodies = {}

    def __call__(self, method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node_id = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        self.bodies[node_id] = body

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

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    fake = FakeSandbox()
    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake)
    return fake


def _second_account(db):
    from utk_curio.backend.app.users.models import User, UserSession

    bob = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(bob)
    db.session.flush()
    db.session.add(UserSession(user_id=bob.id, token="bob-token-789"))
    db.session.commit()
    return bob, "bob-token-789"


def _hold_the_package(user):
    """Put the package in *user*'s own store, and nowhere else."""
    from utk_curio.backend.app.packages import service as packages_service
    from utk_curio.backend.app.projects.services import _user_dir_key

    folder = packages_service.user_packages_dir(_user_dir_key(user)) / "acme.mine@1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps(STORE_PACKAGE), encoding="utf-8")


def _code_node(node_id, code):
    return {"id": node_id, "type": "curio.builtin/computation-analysis", "content": f"# node {node_id}\n{code}"}


def _create(client, token):
    """A node, the account's download after it, and a node after that."""
    dataflow = {
        "name": "Store download",
        "nodes": [
            _code_node("src", "return 1"),
            {"id": "dl", "type": "acme.mine/download@1", "content": ""},
            _code_node("after", "return input_0"),
        ],
        "edges": [
            {"id": "src-dl", "source": "src", "target": "dl"},
            {"id": "dl-after", "source": "dl", "target": "after"},
        ],
    }
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Store download", "spec": {"dataflow": dataflow}, "outputs": [],
    }), headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _run(client, token, project_id):
    """Start a run of the whole dataflow and wait for its thread; the roles its
    steps had and the run as it ended."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    started = client.post(f"/api/projects/{project_id}/runs", data=json.dumps({}), headers=_auth(token))
    assert started.status_code == 202, started.get_data(as_text=True)
    run_id = started.get_json()["id"]
    roles = {step["nodeId"]: step["role"] for step in started.get_json()["steps"]}
    job = jobs.REGISTRY.get_job(run_id)
    assert job is not None
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()
    resp = client.get(f"/api/runs/{run_id}", headers=_auth(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return roles, resp.get_json()


def test_a_run_forwards_a_download_saved_in_the_accounts_store(client, db, user_and_token, sandbox):
    alice, alice_token = user_and_token
    project_id = _create(client, alice_token)
    _hold_the_package(alice)

    roles, run = _run(client, alice_token, project_id)

    assert roles == {"src": "run", "dl": "forward", "after": "run"}
    assert run["status"] == "succeeded"
    # The node after the download read what reached the download.
    assert sandbox.bodies["after"]["file_path"] == "art-src"


def test_for_another_account_the_same_node_is_a_type_no_installed_package_provides(
    client, db, user_and_token, sandbox,
):
    alice, _alice_token = user_and_token
    bob, bob_token = _second_account(db)
    project_id = _create(client, bob_token)
    _hold_the_package(alice)

    roles, run = _run(client, bob_token, project_id)

    assert roles == {"src": "run", "dl": "missing", "after": "run"}
    assert run["status"] == "failed"
    assert "after" not in sandbox.bodies
    steps = {step["nodeId"]: step for step in run["steps"]}
    assert steps["dl"]["status"] == "error"
    assert steps["dl"]["stderrTail"] == "No installed package provides acme.mine/download@1"
    assert steps["after"]["status"] == "skipped"
