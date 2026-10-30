"""An invited editor's results are kept 7 days, as his.

alice owns a dataflow and invited bob to edit it; carol was never invited. A
play of bob's on her dataflow, as each step of his run on the server, runs in
a kept session of its own when every input is his: an output his own runs
kept, or one the dataflow saved. Its output is then kept 7 days as his
(``made_by`` editor, private to his account), and read under any of his
sign-ins, on the dataflow's routes and on those that name none, by no one
else: alice and carol read under their own sign-ins. None of alice's kept
outputs reaches his kept session. His kept outputs live their days and are
bounded by them alone, as alice's are, and a dashboard viewer's run is handed
none of them through a wrapper. He reopens her dataflow with the results his
runs kept.

The sandbox is a fake, as in ``test_owner_runs_kept.py``. The tests name only
what main has, so each fails there at its own assertion.
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from utk_curio.backend.app.runs import kept
from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.common.kept_sessions import is_kept_session, new_session_id

CODE = "curio.builtin/computation-analysis"
TOKENS = {"bob": "bob-token-for-kept-runs", "carol": "carol-token-for-kept-runs"}


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
    """A run answers an artifact named after its node, which is all its
    session made; a read is noted with the session it names."""
    from utk_curio.backend import config
    from utk_curio.backend.app.api import routes as api_routes
    from utk_curio.backend.app.execution import node_exec

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    state = {"runs": {}, "made": {}, "reads": []}

    def run(method, path, **kwargs):
        body = json.loads(kwargs["data"])
        node = body["code"].split("# node ", 1)[1].split("\n", 1)[0]
        state["runs"][node] = body
        state["made"][body["session_id"]] = f"art-{node}"
        return _Reply({"stdout": [], "stderr": "", "output": {"path": f"art-{node}", "dataType": "dataframe"}})

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
        alice=alice, bob=_account(db, "bob"), carol=_account(db, "carol"),
        tokens={"alice": alice_token, **TOKENS},
    )


def _content(node: str) -> str:
    return f"# node {node}\nreturn input_0"


def _alices(client, people, nodes=()) -> str:
    """alice's dataflow of *nodes*, with bob invited to edit it."""
    from utk_curio.backend.app.projects import access

    resp = client.post("/api/projects", data=json.dumps({
        "name": "Street trees",
        "spec": {"dataflow": {"name": "Street trees", "nodes": list(nodes), "edges": []}},
        "outputs": [],
    }), headers=auth_headers(people.tokens["alice"]))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    project_id = resp.get_json()["id"]
    access.add_editor(people.alice, project_id, "bob")
    return project_id


def _play(client, token, project_id, node, *, input_path=""):
    response = client.post("/processPythonCode", data=json.dumps({
        "code": f"    # node {node}\n    return input_0\n",
        "nodeType": "PYTHON_COMPUTATION", "nodeId": node, "dataflowId": project_id,
        "input": {"path": input_path, "dataType": "dataframe" if input_path else "str"},
        "saveOutputDataset": False,
    }), headers=auth_headers(token))
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _sign_in(db, user, token):
    from utk_curio.backend.app.users.models import UserSession

    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return token


def _read_on_the_dataflow(client, token, project_id, name) -> str:
    """The session a read of *name* on the dataflow's route goes to."""
    response = client.get(
        f"/api/projects/{project_id}/outputs/get", query_string={"fileName": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


def _entry(project_id, node, *, made, private_to, made_by, size=10, path=None):
    path = path or f"art-{node}"
    return KeptStepOutput(
        project_id=project_id, node_id=node, step_key=f"key-{node}", session_id=new_session_id(),
        output=json.dumps({"path": path, "dataType": "dataframe"}), output_path=path,
        artifact_ids=json.dumps([path]), size_bytes=size, private_to=private_to, made_by=made_by,
        created_at=made, used_at=made,
    )


def test_an_editors_play_is_kept_as_his_and_read_under_any_of_his_sign_ins(client, db, people, sandbox):
    project_id = _alices(client, people)

    _play(client, people.tokens["bob"], project_id, "a")
    session = sandbox["runs"]["a"]["session_id"]
    later = _sign_in(db, people.bob, "bob-token-later")
    _read_on_the_dataflow(client, later, project_id, "art-a")
    on_the_dataflow = sandbox["reads"][-1]["sessionId"]
    plain = client.get("/get", query_string={"fileName": "art-a"}, headers=auth_headers(later))
    assert plain.status_code == 200, plain.get_data(as_text=True)
    on_no_dataflow = sandbox["reads"][-1]["sessionId"]
    entry = KeptStepOutput.query.filter_by(project_id=project_id, node_id="a").one_or_none()

    assert {
        "ran in a kept session": is_kept_session(session),
        "imports stay his": sandbox["runs"]["a"]["imports_session"],
        "kept as": entry and (entry.made_by, entry.private_to),
        "his later sign-in reads it on the dataflow's route": on_the_dataflow == session,
        "and on /get": on_no_dataflow == session,
    } == {
        "ran in a kept session": True,
        "imports stay his": people.tokens["bob"],
        "kept as": ("editor", f"account:{people.bob.id}"),
        "his later sign-in reads it on the dataflow's route": True,
        "and on /get": True,
    }


def test_no_one_but_the_editor_reads_his_kept_output(client, people, sandbox):
    project_id = _alices(client, people)
    _play(client, people.tokens["bob"], project_id, "a")
    bobs = sandbox["runs"]["a"]["session_id"]

    reads = {}
    for who in ("alice", "carol"):
        token = people.tokens[who]
        _read_on_the_dataflow(client, token, project_id, "art-a")
        reads[f"{who} on the dataflow's route"] = sandbox["reads"][-1]["sessionId"]
        plain = client.get("/get", query_string={"fileName": "art-a"}, headers=auth_headers(token))
        assert plain.status_code == 200, plain.get_data(as_text=True)
        reads[f"{who} on /get"] = sandbox["reads"][-1]["sessionId"]

    assert is_kept_session(bobs), f"bob's play ran in {bobs!r}, not a kept session"
    assert reads == {
        "alice on the dataflow's route": people.tokens["alice"],
        "alice on /get": people.tokens["alice"],
        "carol on the dataflow's route": people.tokens["carol"],
        "carol on /get": people.tokens["carol"],
    }


def test_an_editors_kept_run_reads_his_own_kept_outputs_and_none_of_the_owners(client, people, sandbox):
    project_id = _alices(client, people)
    _play(client, people.tokens["alice"], project_id, "a")
    _play(client, people.tokens["bob"], project_id, "x")

    _play(client, people.tokens["bob"], project_id, "b", input_path="art-a")
    _play(client, people.tokens["bob"], project_id, "c", input_path="art-x")

    hers, his = sandbox["runs"]["b"], sandbox["runs"]["c"]
    assert {
        "reading alice's kept output": (hers["session_id"], hers.get("saved_paths")),
        "reading his own, in a kept session": is_kept_session(his["session_id"]),
    } == {
        "reading alice's kept output": (people.tokens["bob"], None),
        "reading his own, in a kept session": True,
    }


def _record_as_saved(user, project_id, names: dict):
    """*names* (``{node id: output name}``) recorded as the nodes' saved
    outputs in alice's manifest, each with a computed dataset of its node,
    as a save records them."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user_key = _user_dir_key(user)
    for node in names:
        install_computed_file_for_node(user_key, b"a\n1\n", f"{node}.csv", "csv", node_id=node, dataflow_id=project_id)
    storage.record_outputs(user_key, project_id, [{"node_id": node, "filename": name} for node, name in names.items()])


def test_an_editors_play_on_a_saved_output_her_run_made_is_kept_as_his(client, db, people, sandbox):
    """bob's node below a node whose output alice's run made, kept and saved,
    reads that saved output, the dataflow's own: his run is kept as his. A
    saved output another kept run made, one alice's runs did not keep, keeps
    his run in his own session, since his kept session would read that run's
    artifact, whoever's it is."""
    import pandas as pd

    from utk_curio.sandbox.util.parsers import save_to_duckdb

    project_id = _alices(client, people)
    hers_session = new_session_id()
    hers = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="a", session_id=hers_session)
    theirs = save_to_duckdb(pd.DataFrame({"n": [2]}), node_id="t", session_id=new_session_id())
    now = naive_utc_now()
    db.session.add(KeptStepOutput(
        project_id=project_id, node_id="a", step_key="a" * 64, session_id=hers_session,
        output=json.dumps({"path": hers, "dataType": "dataframe"}), output_path=hers,
        artifact_ids=json.dumps([hers]), made_by="owner", created_at=now, used_at=now,
    ))
    db.session.commit()
    _record_as_saved(people.alice, project_id, {"a": hers, "t": theirs})

    _play(client, people.tokens["bob"], project_id, "b", input_path=hers)
    _play(client, people.tokens["bob"], project_id, "c", input_path=theirs)

    on_hers, on_theirs = sandbox["runs"]["b"], sandbox["runs"]["c"]
    assert {
        "on her saved output, kept": is_kept_session(on_hers["session_id"]),
        "read from its file": bool(on_hers["saved_paths"][hers]["path"]),
        "on another kept run's": on_theirs["session_id"],
    } == {
        "on her saved output, kept": True,
        "read from its file": True,
        "on another kept run's": people.tokens["bob"],
    }


def test_an_editors_kept_outputs_live_their_days_bounded_by_them_alone(app, client, db, people, monkeypatch):
    """A tab's own output lives an hour and the viewers' share a budget; his,
    as alice's, live their 7 days, whatever their size."""
    project_id = _alices(client, people)
    monkeypatch.setattr(kept, "MAX_KEPT_BYTES", 100)
    monkeypatch.setattr(kept, "forget_sessions", lambda sessions: None)
    now = naive_utc_now()
    his = f"account:{people.bob.id}"
    for node, made in (
        ("two-hours-old", now - timedelta(hours=2)),
        ("eight-days-old", now - timedelta(days=8)),
        ("big", now - timedelta(minutes=10)),
        ("bigger", now - timedelta(minutes=9)),
    ):
        db.session.add(_entry(project_id, node, made=made, private_to=his, made_by="editor", size=60))
    db.session.commit()

    kept.prune(now)

    left = {e.node_id for e in KeptStepOutput.query.filter_by(project_id=project_id)}
    assert left == {"two-hours-old", "big", "bigger"}


def test_a_viewers_run_is_handed_no_editors_kept_output_through_a_wrapper(client, db, people):
    """A dashboard viewer's step runs in a kept session, which reads any kept
    output: one a wrapper among its inputs names must be the dataflow's own,
    and bob's are his, not the dataflow's."""
    from utk_curio.backend.app.execution.node_exec import _foreign_wrapped

    project_id = _alices(client, people)
    now = naive_utc_now()
    db.session.add(_entry(project_id, "hers", made=now, private_to=None, made_by="owner"))
    db.session.add(_entry(
        project_id, "his", made=now, private_to=f"account:{people.bob.id}", made_by="editor",
    ))
    db.session.commit()

    assert {
        "alice's kept output": _foreign_wrapped(project_id, ["art-hers"], {}),
        "bob's kept output": _foreign_wrapped(project_id, ["art-his"], {}),
    } == {"alice's kept output": False, "bob's kept output": True}


def _as_a_play_posts(code: str) -> str:
    """``playIndent`` in ``PythonInterpreter.ts``."""
    return "".join("    " + line + "\n" for line in code.split("\n"))


def _play_as_the_canvas(client, token, project_id, node) -> str:
    """A play posted as the canvas posts it, so the dataflow keys it as a
    run of its step: its output's name."""
    resp = client.post("/processPythonCode", data=json.dumps({
        "code": _as_a_play_posts(_content(node)), "nodeType": f"{CODE}@1",
        "nodeId": node, "dataflowId": project_id, "input": "", "saveOutputDataset": False,
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["output"]["path"]


def _open_shared(client, token, project_id) -> dict:
    resp = client.get(
        f"/api/projects/{project_id}/shared", query_string={"results": "last"}, headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {o["node_id"]: o["filename"] for o in resp.get_json()["outputs"]}


def test_an_editor_reopens_her_dataflow_with_the_results_his_runs_kept(client, people, sandbox):
    """His canvas opens her dataflow from its link: each node his runs ran
    shows his newest kept result, as hers opens with hers. carol, who only
    watches, gets the saved outputs, and none is saved."""
    project_id = _alices(client, people, [{"id": "a", "type": CODE, "content": _content("a")}])
    made = _play_as_the_canvas(client, people.tokens["bob"], project_id, "a")

    assert {
        "bob": _open_shared(client, people.tokens["bob"], project_id),
        "carol": _open_shared(client, people.tokens["carol"], project_id),
    } == {"bob": {"a": made}, "carol": {}}
