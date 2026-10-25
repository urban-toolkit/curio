"""A dataflow reopens with the results it was left with (``runs/reopen.py``).

The owner's plays and runs on the server keep each step's output 7 days, under
a key of what made it (``runs/kept.py``). A canvas opens the dataflow with
``GET /api/projects/<id>?results=last``: each node a run executes shows the
newest output kept under the key the saved dataflow gives its step, and a
node with none shows its saved output. Without ``results=last`` a load shows
the saved outputs only, as a dashboard opens with.

The sandbox is a fake: each run answers an artifact named after its node and
its turn. A play is posted as the canvas posts it: its code indented as
``PythonInterpreter.ts`` indents it, its type with its version, its input as
``executionInputRef`` sends it, and its wired circles.
"""
from __future__ import annotations

import json
import threading
from datetime import timedelta

import pytest

from utk_curio.backend.app.runs import kept
from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

CODE = "curio.builtin/computation-analysis"


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
def sandbox(monkeypatch):
    from utk_curio.backend import config
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs import jobs

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    jobs.REGISTRY.reset()
    state = {"runs": [], "made": {}}
    lock = threading.Lock()

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        with lock:
            state["runs"].append(node)
            made = f"art-{node}-{len(state['runs'])}"
            state["made"][body["session_id"]] = made
        return _Reply({"stdout": [], "stderr": "", "output": {"path": made, "dataType": "dataframe"}})

    def sessions(method, path, **kwargs):
        named = json.loads(kwargs["data"])["sessionIds"]
        if path.endswith("/describe"):
            return _Reply({"sessions": {s: {"bytes": 10, "ids": [state["made"].get(s, "")]} for s in named}})
        return _Reply({"forgotten": len(named)})

    monkeypatch.setattr(node_exec, "sandbox_request", run)
    monkeypatch.setattr(kept, "sandbox_request", sessions)
    return state


def _content(node: str) -> str:
    return f"# node {node}\nreturn input_0"


def _node(node: str, **fields) -> dict:
    return {"id": node, "type": CODE, "content": _content(node), **fields}


def _edge(source: str, target: str, handle: str = "in") -> dict:
    return {"id": f"{source}-{target}", "source": source, "target": target, "targetHandle": handle}


def _create(client, token, nodes, edges=()) -> str:
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Reopen",
        "spec": {"dataflow": {"name": "Reopen", "nodes": list(nodes), "edges": list(edges)}},
        "outputs": [],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _resave(client, token, project_id, nodes, edges=()):
    resp = client.put(f"/api/projects/{project_id}", data=json.dumps({
        "name": "Reopen",
        "spec": {"dataflow": {"name": "Reopen", "nodes": list(nodes), "edges": list(edges)}},
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)


def _as_a_play_posts(code: str) -> str:
    """``playIndent`` in ``PythonInterpreter.ts``."""
    return "".join("    " + line + "\n" for line in code.split("\n"))


def _play(client, token, project_id, node, *, inputs=(), content=None) -> str:
    if len(inputs) > 1:
        input_ref = {"dataType": "outputs", "data": [{"path": name, "dataType": "dataframe"} for name in inputs]}
    elif inputs:
        input_ref = {"path": inputs[0], "dataType": "dataframe"}
    else:
        input_ref = ""
    body = {
        "code": _as_a_play_posts(content or _content(node)), "nodeType": f"{CODE}@1",
        "nodeId": node, "dataflowId": project_id, "input": input_ref, "saveOutputDataset": False,
    }
    if inputs:
        body["inputSlots"] = list(range(len(inputs)))
    resp = client.post("/processPythonCode", data=json.dumps(body), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["output"]["path"]


def _open(client, token, project_id, *, last=True) -> dict:
    resp = client.get(
        f"/api/projects/{project_id}", query_string={"results": "last"} if last else {},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {o["node_id"]: (o["filename"], o.get("data_type")) for o in resp.get_json()["outputs"]}


def _record_as_saved(user, project_id, node, name):
    """*name* recorded as *node*'s saved output, with a computed dataset for
    it, as a save records one."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user_key = _user_dir_key(user)
    install_computed_file_for_node(user_key, b"a\n1\n", f"{node}.csv", "csv", node_id=node, dataflow_id=project_id)
    storage.record_outputs(user_key, project_id, [{"node_id": node, "filename": name, "data_type": "dataframe"}])


def test_a_dataflow_reopens_with_what_its_plays_left(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])
    made_a = _play(client, token, project_id, "a")
    made_b = _play(client, token, project_id, "b", inputs=[made_a])

    assert _open(client, token, project_id) == {"a": (made_a, "dataframe"), "b": (made_b, "dataframe")}


def test_a_node_with_several_inputs_reopens_with_its_result(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id = _create(
        client, token, [_node("a"), _node("b"), _node("c")],
        [_edge("a", "c", "in"), _edge("b", "c", "in_1")],
    )
    made_a = _play(client, token, project_id, "a")
    made_b = _play(client, token, project_id, "b")
    made_c = _play(client, token, project_id, "c", inputs=[made_a, made_b])

    assert _open(client, token, project_id)["c"] == (made_c, "dataframe")


def test_a_load_without_last_results_shows_the_saved_outputs_only(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id = _create(client, token, [_node("a")])
    _play(client, token, project_id, "a")

    assert _open(client, token, project_id, last=False) == {}


def test_the_newest_result_shows(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id = _create(client, token, [_node("a")])
    _play(client, token, project_id, "a")
    again = _play(client, token, project_id, "a")

    assert _open(client, token, project_id) == {"a": (again, "dataframe")}


def test_a_node_whose_code_changed_since_shows_no_kept_result_nor_what_is_below_it(client, user_and_token, sandbox):
    user, token = user_and_token
    nodes, edges = [_node("a"), _node("b")], [_edge("a", "b")]
    project_id = _create(client, token, nodes, edges)
    made_a = _play(client, token, project_id, "a")
    _play(client, token, project_id, "b", inputs=[made_a])

    _resave(client, token, project_id, [{**_node("a"), "content": _content("a") + " * 2"}, _node("b")], edges)
    assert _open(client, token, project_id) == {}

    _resave(client, token, project_id, [_node("a"), {**_node("b"), "content": _content("b") + " * 2"}], edges)
    assert _open(client, token, project_id) == {"a": (made_a, "dataframe")}


def test_past_its_days_a_node_shows_its_saved_output_again(client, user_and_token, sandbox):
    from utk_curio.backend.extensions import db

    user, token = user_and_token
    project_id = _create(client, token, [_node("a")])
    saved = "1700000000000_5a7ed000"
    _record_as_saved(user, project_id, "a", saved)
    made = _play(client, token, project_id, "a")
    assert _open(client, token, project_id) == {"a": (made, "dataframe")}

    eight_days_ago = naive_utc_now() - timedelta(days=kept.KEPT_DAYS + 1)
    KeptStepOutput.query.filter_by(project_id=project_id).update({"created_at": eight_days_ago})
    db.session.commit()

    assert _open(client, token, project_id) == {"a": (saved, "dataframe")}


def test_a_dataflow_opens_with_its_saved_outputs_when_the_lookup_fails(client, user_and_token, sandbox, monkeypatch):
    """Whatever goes wrong finding its kept results, a dataflow opens, with
    its saved outputs."""
    user, token = user_and_token
    project_id = _create(client, token, [_node("a")])
    saved = "1700000000000_5a7ed000"
    _record_as_saved(user, project_id, "a", saved)
    _play(client, token, project_id, "a")

    def broken(_user_key):
        raise RuntimeError("the package store cannot be read")

    monkeypatch.setattr(kept, "packages_fingerprint", broken)

    assert _open(client, token, project_id) == {"a": (saved, "dataframe")}


def test_a_node_whose_code_does_not_compile_is_left_out_and_the_rest_reopen(client, user_and_token, sandbox, monkeypatch):
    user, token = user_and_token
    project_id = _create(client, token, [_node("a"), _node("b")])
    made_a = _play(client, token, project_id, "a")
    _play(client, token, project_id, "b")
    real = kept.step_call

    def step_call(plan, step, code, input_ref):
        if step.node_id == "b":
            raise ValueError("an Autark document that does not compile")
        return real(plan, step, code, input_ref)

    monkeypatch.setattr(kept, "step_call", step_call)

    assert _open(client, token, project_id) == {"a": (made_a, "dataframe")}


def test_another_account_opens_nothing_of_it(client, db, user_and_token, sandbox):
    from utk_curio.backend.app.users.models import User, UserSession

    user, token = user_and_token
    project_id = _create(client, token, [_node("a")])
    _play(client, token, project_id, "a")
    other = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(other)
    db.session.flush()
    db.session.add(UserSession(user_id=other.id, token="bob-token-789"))
    db.session.commit()

    resp = client.get(f"/api/projects/{project_id}", query_string={"results": "last"},
                      headers=auth_headers("bob-token-789"))

    assert resp.status_code == 404


def test_a_dataflow_reopens_with_what_its_run_on_the_server_left(client, user_and_token, sandbox):
    """What a run on the server's steps made shows as a play's does: the
    canvas no longer restores the last run's steps itself."""
    from utk_curio.backend.app.runs import jobs
    from utk_curio.backend.extensions import db

    user, token = user_and_token
    project_id = _create(client, token, [_node("a"), _node("b")], [_edge("a", "b")])

    resp = client.post(f"/api/projects/{project_id}/runs", data=json.dumps({}), headers=auth_headers(token))
    assert resp.status_code in (200, 201, 202), resp.get_data(as_text=True)
    job = jobs.REGISTRY.get_job(resp.get_json()["id"])
    job.thread.join(timeout=30)
    assert not job.thread.is_alive()
    db.session.rollback()

    opened = _open(client, token, project_id)
    assert sorted(opened) == ["a", "b"]
    assert {filename.split("-")[1] for filename, _type in opened.values()} == {"a", "b"}
