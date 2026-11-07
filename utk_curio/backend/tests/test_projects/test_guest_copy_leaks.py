"""What one hosted guest does to an example stays in their own copy of it
(``projects/visitor_copies.py``).

Every hosted guest (a guest on a Curio started with ``--deploy``) signs in to
the one shared guest account, which owns the shipped examples. Its agents
already work on a copy of the example of its own; so do its plays, its Data
Catalog Add and Remove, and its rename of the dataflow. These tests sign two
visitors, A and B, in to that account, as two browsers do, and have A act on
an example. A sees what A did; B opens the example as it ships; and the
example's spec and manifest on disk, and the account's dataset store, are
byte for byte what they were.

The sandbox is a fake: each node's run answers an artifact the store holds for
that node, written beforehand as a run writes it, so a run's output can be
installed as a run's is. A play is posted as the canvas posts it.
"""
from __future__ import annotations

import hashlib
import io
import json

import pandas as pd
import pytest

from utk_curio.backend import config
from utk_curio.backend.app.common.user_storage import GUEST_KEY
from utk_curio.backend.app.projects import storage
from utk_curio.backend.app.runs import kept
from utk_curio.backend.app.runs.models import KeptStepOutput
from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    store_sandbox_artifact,
)
from utk_curio.common.kept_sessions import is_kept_session

#: Two visitors' sign-ins to the shared guest account.
VISITOR_A = "hosted-guest-visitor-a"
VISITOR_B = "hosted-guest-visitor-b"
CODE = "curio.builtin/python-computation"
#: A dataset of the Data Catalog the example ships with, and its folder.
SHIPPED = "data.test.park-shade"
SHIPPED_DIR = f"{SHIPPED}@1"


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


@pytest.fixture()
def app(tmp_curio, monkeypatch):
    """The app on a fresh workspace whose store a test writes artifacts to,
    as a run writes them."""
    from utk_curio.backend.app import create_app
    from utk_curio.backend.extensions import db as _db
    from utk_curio.backend.tests._unit_fixtures import TestConfig
    from utk_curio.sandbox.util.db import release_connection

    release_connection()
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_curio / ".curio" / "data"))
    application = create_app(TestConfig)
    with application.app_context():
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()
    release_connection()


@pytest.fixture()
def sandbox(app, monkeypatch):
    """The sandbox as these plays meet it: a node's run answers the artifact
    the store holds for it (``artifacts``), which is all its session made; a
    read is noted with the session it names."""
    from utk_curio.backend.app.api import routes as api_routes
    from utk_curio.backend.app.execution import node_exec

    state = {
        "runs": {}, "made": {}, "reads": [],
        "artifacts": {
            node: store_sandbox_artifact(pd.DataFrame({"node": [node], "value": [i]}), node_id=node)
            for i, node in enumerate(("a", "b"))
        },
    }

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        state["runs"][node] = body
        made = state["artifacts"][node]
        state["made"][body["session_id"]] = made
        return _Reply({"stdout": [], "stderr": "", "output": {"path": made, "dataType": "dataframe"}})

    def sessions(method, path, **kwargs):
        named = json.loads(kwargs["data"])["sessionIds"]
        if path.endswith("/describe"):
            return _Reply({"sessions": {s: {"bytes": 10, "ids": [state["made"].get(s, "")]} for s in named}})
        return _Reply({"forgotten": len(named)})

    def read(method, path, *, label, timeout, **kwargs):
        state["reads"].append(kwargs["params"])
        return _Reply({"rows": []})

    monkeypatch.setattr(node_exec, "sandbox_request", run)
    monkeypatch.setattr(kept, "sandbox_request", sessions)
    monkeypatch.setattr(api_routes, "_sandbox_call", read)
    return state


def _content(node: str) -> str:
    return f"# node {node}\nreturn input_0"


def _node(node: str) -> dict:
    return {"id": node, "type": CODE, "content": _content(node)}


@pytest.fixture()
def example(client, db, monkeypatch):
    """An example the shared guest owns, a to b, saved as the local guest
    saves one, with sign-in off. The visitors come with it on, as on a Curio
    started with ``--deploy``, and each opens it once, as their canvases do,
    before anything is measured."""
    from utk_curio.backend.app.users.models import User, UserSession

    guest = User(username=config.CURIO_SHARED_GUEST_USERNAME, name="Guest",
                 email="guest@test.com", is_guest=True)
    db.session.add(guest)
    db.session.flush()
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_A))
    db.session.add(UserSession(user_id=guest.id, token=VISITOR_B))
    db.session.commit()
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    created = client.post("/api/projects", data=json.dumps({
        "name": "Example",
        "spec": {"dataflow": {
            "name": "Example", "nodes": [_node("a"), _node("b")],
            "edges": [{"id": "a-b", "source": "a", "target": "b", "targetHandle": "in"}],
        }},
        "outputs": [],
    }), headers=auth_headers(VISITOR_A))
    assert created.status_code == 201, created.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    example_id = created.get_json()["id"]
    for token in (VISITOR_A, VISITOR_B):
        _open(client, token, example_id)
    return example_id


def _as_a_play_posts(code: str) -> str:
    """``playIndent`` in ``PythonInterpreter.ts``."""
    return "".join("    " + line + "\n" for line in code.split("\n"))


def _play(client, token, project_id, node, *, inputs=()) -> dict:
    """The visitor signed in as *token* plays *node*, saving its output as a
    dataset as the canvas asks by default; the reply."""
    body = {
        "code": _as_a_play_posts(_content(node)), "nodeType": f"{CODE}@1",
        "nodeId": node, "dataflowId": project_id,
        "input": {"path": inputs[0], "dataType": "dataframe"} if inputs else "",
        "saveOutputDataset": True,
    }
    if inputs:
        body["inputSlots"] = list(range(len(inputs)))
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _open(client, token, project_id) -> dict:
    """The dataflow as the canvas of the visitor signed in as *token* opens it
    (``?results=last``)."""
    resp = client.get(f"/api/projects/{project_id}", query_string={"results": "last"},
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _results(client, token, project_id) -> dict:
    """``{node id: output}`` the canvas of *token*'s visitor opens with."""
    return {o["node_id"]: o["filename"] for o in _open(client, token, project_id)["outputs"]}


def _computed_in_the_store() -> list[str]:
    """The node outputs saved as datasets in the guest account's store, which
    every guest's Data Catalog lists."""
    from utk_curio.backend.app.datasets.infrastructure.storage import list_user_datasets

    return sorted(p.name for p in list_user_datasets(GUEST_KEY) if p.name.startswith("computed."))


def _digests(example_id: str) -> dict:
    """The example's spec and manifest on disk, and every file of the guest
    account's dataset store, each by the digest of its bytes."""
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir

    folder = storage.project_dir(GUEST_KEY, example_id)
    files = {name: folder / name for name in (storage.SPEC_FILE, "manifest.json")}
    store = user_datasets_dir(GUEST_KEY)
    if store.is_dir():
        files.update({
            f"datasets/{path.relative_to(store).as_posix()}": path
            for path in store.rglob("*") if path.is_file() and not path.name.endswith(".lock")
        })
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        for name, path in sorted(files.items())
    }


def _copy_of(token: str, project_id: str) -> str:
    from utk_curio.backend.app.projects import visitor_copies

    return visitor_copies.copy_id(token, project_id)


def test_a_hosted_guests_play_adds_nothing_to_the_shared_data_catalog(client, example, sandbox):
    before = _digests(example)

    reply = _play(client, VISITOR_A, example, "a")

    # The guests' Data Catalog is every guest's: B's "Saved outputs" would
    # list it.
    assert reply["installedDataset"] is None
    assert _computed_in_the_store() == []
    assert _digests(example) == before


def test_a_hosted_guests_results_reopen_for_them_alone(client, example, sandbox):
    before = _digests(example)
    made_a = sandbox["artifacts"]["a"]
    made_b = sandbox["artifacts"]["b"]

    _play(client, VISITOR_A, example, "a")
    _play(client, VISITOR_A, example, "b", inputs=[made_a])

    # The next guest opens the example as it ships, with none of A's results.
    assert _results(client, VISITOR_B, example) == {}
    # A's canvas opens with them: b read a's output, which A's play kept.
    assert is_kept_session(sandbox["runs"]["b"]["session_id"])
    assert _results(client, VISITOR_A, example) == {"a": made_a, "b": made_b}
    # Nothing is kept on the example itself.
    assert KeptStepOutput.query.filter_by(project_id=example).count() == 0
    assert _digests(example) == before


def test_another_hosted_guest_reads_none_of_a_guests_results(client, example, sandbox):
    before = _digests(example)
    made_a = sandbox["artifacts"]["a"]
    _play(client, VISITOR_A, example, "a")

    for read in (f"/api/projects/{example}/outputs/get", "/get"):
        client.get(read, query_string={"fileName": made_a}, headers=auth_headers(VISITOR_B))
        # B reads under B's own sign-in, never under the session A's play kept.
        assert sandbox["reads"][-1]["sessionId"] == VISITOR_B, read
        client.get(read, query_string={"fileName": made_a}, headers=auth_headers(VISITOR_A))
        assert is_kept_session(sandbox["reads"][-1]["sessionId"]), read
    assert _digests(example) == before


def test_a_hosted_guests_run_outcomes_are_recorded_on_their_copy(client, example, sandbox):
    from utk_curio.backend.app.execution import runtime_journal

    before = _digests(example)
    _play(client, VISITOR_A, example, "a")

    # The runtime journal agents and node bodies read is A's copy's.
    assert runtime_journal.read_record(GUEST_KEY, example, "a") is None
    assert runtime_journal.read_record(GUEST_KEY, _copy_of(VISITOR_A, example), "a")["status"] == "ok"

    def recorded(token, node):
        resp = client.get("/nodeRuntime", query_string={"dataflowId": example, "nodeId": node},
                          headers=auth_headers(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        return resp.get_json()

    assert recorded(VISITOR_A, "a")["run"]["status"] == "ok"
    assert recorded(VISITOR_B, "a")["run"] is None

    # A render a node reports from the browser is recorded on its guest's
    # copy, and nowhere for a guest who has none.
    for token, said in ((VISITOR_B, "B's chart failed"), (VISITOR_A, "A's chart failed")):
        resp = client.post("/nodeRuntime", data=json.dumps({
            "dataflowId": example, "nodeId": "b", "status": "error", "message": said,
        }), headers=auth_headers(token))
        assert resp.status_code == 204, resp.get_data(as_text=True)
    assert runtime_journal.read_render_record(GUEST_KEY, example, "b") is None
    assert recorded(VISITOR_A, "b")["render"]["stderrTail"] == "A's chart failed"
    assert recorded(VISITOR_B, "b")["render"] is None
    assert _digests(example) == before


@pytest.fixture()
def datasets(client, example, tmp_path, monkeypatch):
    """The example ships with a Data Catalog dataset, which the guest
    account's store holds, and the store holds a file someone uploaded too.
    Both are in place, and each visitor has opened the example again, before
    anything is measured. The upload's id."""
    catalog = tmp_path / "catalog"
    folder = catalog / SHIPPED_DIR
    (folder / "data").mkdir(parents=True)
    (folder / "data" / "park_shade.csv").write_text("design,shade\nlawn,0.1\ntrees,0.6\n", encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps({
        "id": SHIPPED, "name": "Park area in shade", "version": "1.0.0", "format": "csv",
        "description": "A test table.", "publisher": "Curio", "license": "MIT", "tags": ["csv"],
        "dataFile": "data/park_shade.csv", "compatibility": {"major": 1}, "sourceLabel": "Test tables",
        "rowCount": 2, "featureCount": None, "schema": None,
        "createdAt": "2026-10-17T00:00:00Z", "updatedAt": "2026-10-17T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(catalog))
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    shipped = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": SHIPPED}),
                          headers=auth_headers(VISITOR_A))
    assert shipped.status_code == 200, shipped.get_data(as_text=True)
    uploaded = client.post(
        "/api/datasets/import", headers={"Authorization": f"Bearer {VISITOR_A}"},
        data={"file": (io.BytesIO(b"tree,height\noak,12\n"), "trees.csv")}, content_type="multipart/form-data",
    )
    assert uploaded.status_code == 201, uploaded.get_data(as_text=True)
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)
    for token in (VISITOR_A, VISITOR_B):
        _open(client, token, example)
    return uploaded.get_json()["id"]


def _in_the_dataflow(client, token, project_id) -> list[str]:
    """The datasets the canvas of *token*'s visitor opens the dataflow with."""
    spec = _open(client, token, project_id)["spec"]
    return [r["datasetId"] for r in (spec.get("dataflow") or {}).get("datasets") or []]


def _listed_as_installed(client, token, project_id, dataset_id) -> bool:
    """Whether *token*'s visitor's Data Catalog lists *dataset_id* as in the
    dataflow."""
    resp = client.get("/api/datasets/catalog", query_string={"dataflowId": project_id, "includeHub": "true"},
                      headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return any(i.get("id") == dataset_id and i.get("installed") is True for i in resp.get_json()["items"])


def test_a_hosted_guests_datasets_change_their_copy_alone(client, example, datasets):
    uploaded = datasets
    before = _digests(example)

    added = client.post(f"/api/dataflows/{example}/datasets/install", data=json.dumps({"datasetId": uploaded}),
                        headers=auth_headers(VISITOR_A))
    assert added.status_code == 200, added.get_data(as_text=True)

    # B opens the example with the datasets it ships with, and A with A's.
    assert _in_the_dataflow(client, VISITOR_B, example) == [SHIPPED]
    assert _in_the_dataflow(client, VISITOR_A, example) == [SHIPPED, uploaded]
    assert _listed_as_installed(client, VISITOR_A, example, uploaded)
    assert not _listed_as_installed(client, VISITOR_B, example, uploaded)

    for dataset_id in (SHIPPED, uploaded):
        removed = client.delete(f"/api/dataflows/{example}/datasets/{dataset_id}", headers=auth_headers(VISITOR_A))
        assert removed.status_code == 200, removed.get_data(as_text=True)

    assert _in_the_dataflow(client, VISITOR_A, example) == []
    assert not _listed_as_installed(client, VISITOR_A, example, SHIPPED)
    assert _in_the_dataflow(client, VISITOR_B, example) == [SHIPPED]
    assert _listed_as_installed(client, VISITOR_B, example, SHIPPED)
    # The upload A took out of A's copy stays in the store every guest reads.
    assert _digests(example) == before


def test_a_hosted_guests_rename_names_their_copy_alone(client, db, example):
    from utk_curio.backend.app.projects.models import Project

    before = _digests(example)

    renamed = client.put(f"/api/projects/{example}", data=json.dumps({"name": "Mine"}),
                         headers=auth_headers(VISITOR_A))

    assert renamed.status_code == 200, renamed.get_data(as_text=True)
    assert renamed.get_json()["name"] == "Mine"
    mine, theirs = _open(client, VISITOR_A, example), _open(client, VISITOR_B, example)
    assert (mine["project"]["name"], mine["spec"]["dataflow"]["name"]) == ("Mine", "Mine")
    assert (theirs["project"]["name"], theirs["spec"]["dataflow"]["name"]) == ("Example", "Example")
    assert db.session.get(Project, example).name == "Example"
    assert _digests(example) == before


def test_a_hosted_guests_results_go_with_the_copies_when_the_server_starts(client, example, sandbox):
    from utk_curio.backend.app.projects import visitor_copies

    before = _digests(example)
    _play(client, VISITOR_A, example, "a")

    assert visitor_copies.drop_all() == 1

    assert KeptStepOutput.query.filter_by(project_id=_copy_of(VISITOR_A, example)).count() == 0
    # The same sign-in's next copy starts from the example as it ships, with
    # none of the results its last one held.
    renamed = client.put(f"/api/projects/{example}", data=json.dumps({"name": "Mine"}),
                         headers=auth_headers(VISITOR_A))
    assert renamed.status_code == 200, renamed.get_data(as_text=True)
    assert _results(client, VISITOR_A, example) == {}
    assert _digests(example) == before
