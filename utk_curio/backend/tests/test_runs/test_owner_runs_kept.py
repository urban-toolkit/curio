"""The owner's runs of a saved dataflow are kept seven days, as a viewer's are.

A play or a run on the server by the dataflow's owner runs in a kept session
(``execution/node_exec._kept_run``) and keeps its output under the key a
viewer's run of the same step computes (``runs/kept.py``). The owner reads it
through the dataflow's routes from any sign-in; no one else reads it there. A
run whose input is not the dataflow's own runs in the caller's session, as
before, since a kept session reads any kept output. What the owner's keys
made, and anything made from it, is the owner's alone, for its full days.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from utk_curio.backend.app.runs import kept
from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now
from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project
from utk_curio.common.kept_sessions import is_kept_session, new_session_id


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
    """The sandbox as these runs meet it: a run answers an artifact named
    after its node, which is all its session made; a read is noted with the
    session it names."""
    from utk_curio.backend import config
    from utk_curio.backend.app.api import routes as api_routes
    from utk_curio.backend.app.execution import node_exec

    monkeypatch.setattr(config, "CURIO_DEFAULT_SAVE_NODE_OUTPUT", False)
    state = {"runs": {}, "made": {}, "reads": [], "forgotten": []}

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
        state["forgotten"].extend(named)
        return _Reply({"forgotten": len(named)})

    def read(method, path, *, label, timeout, **kwargs):
        state["reads"].append(kwargs["params"])
        return _Reply({"rows": []})

    monkeypatch.setattr(node_exec, "sandbox_request", run)
    monkeypatch.setattr(kept, "sandbox_request", sessions)
    monkeypatch.setattr(api_routes, "_sandbox_call", read)
    return state


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


def _other_account(db):
    from utk_curio.backend.app.users.models import User, UserSession

    other = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(other)
    db.session.flush()
    db.session.add(UserSession(user_id=other.id, token="bob-token-789"))
    db.session.commit()
    return other, "bob-token-789"


def _read(client, token, project_id, name):
    response = client.get(
        f"/api/projects/{project_id}/outputs/get", query_string={"fileName": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def test_a_play_is_read_after_a_new_sign_in(client, db, user_and_token, sandbox):
    user, token = user_and_token
    project_id = create_project(client, token, name="Kept plays")
    _play(client, token, project_id, "a")
    session = sandbox["runs"]["a"]["session_id"]
    assert is_kept_session(session)

    later = _sign_in(db, user, "alice-token-later")
    _read(client, later, project_id, "art-a")

    assert sandbox["reads"][-1]["sessionId"] == session
    entry = KeptStepOutput.query.filter_by(project_id=project_id, node_id="a").one()
    assert (entry.made_by, entry.private_to, entry.output_path) == ("owner", None, "art-a")


def test_another_account_reads_no_kept_output(client, db, user_and_token, sandbox):
    user, token = user_and_token
    project_id = create_project(client, token, name="Kept plays")
    _play(client, token, project_id, "a")
    _other, other_token = _other_account(db)

    _read(client, other_token, project_id, "art-a")

    assert sandbox["reads"][-1]["sessionId"] == other_token


def test_a_play_reads_the_dataflows_kept_output_in_a_kept_session(client, user_and_token, sandbox):
    user, token = user_and_token
    project_id = create_project(client, token, name="Kept plays")
    _play(client, token, project_id, "a")

    _play(client, token, project_id, "b", input_path="art-a")

    assert sandbox["runs"]["b"]["file_path"] == "art-a"
    assert is_kept_session(sandbox["runs"]["b"]["session_id"])
    assert sandbox["runs"]["b"]["imports_session"] == token


def test_an_input_from_another_dataflow_runs_in_the_callers_session(client, user_and_token, sandbox):
    """A kept session reads any kept output, so only the dataflow's own
    reach one: another dataflow's output keeps the caller's session, where
    the sandbox serves only the caller's own artifacts."""
    user, token = user_and_token
    first = create_project(client, token, name="First")
    second = create_project(client, token, name="Second")
    _play(client, token, first, "a")

    _play(client, token, second, "b", input_path="art-a")

    assert sandbox["runs"]["b"]["session_id"] == token
    assert KeptStepOutput.query.filter_by(project_id=second).count() == 0


def _record_as_saved(client, token, user, project_id, name):
    """*name* recorded as node ``n1``'s saved output in the manifest, with a
    computed dataset for ``n1``, as a save records one."""
    from utk_curio.backend.app.datasets.install.installer import install_computed_file_for_node
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user_key = _user_dir_key(user)
    install_computed_file_for_node(user_key, b"a\n1\n", "n1.csv", "csv", node_id="n1", dataflow_id=project_id)
    storage.record_outputs(user_key, project_id, [{"node_id": "n1", "filename": name}])


def test_a_saved_input_another_kept_run_made_runs_in_the_callers_session(client, user_and_token, sandbox):
    """A saved output is read from the store first, and a kept session reads
    any kept run's artifact: a name a manifest records that another kept run
    made, a viewer's of someone else's dashboard say, never reaches one."""
    import pandas as pd

    from utk_curio.sandbox.util.parsers import save_to_duckdb

    user, token = user_and_token
    project_id = create_project(client, token, name="Crafted")
    theirs = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n", session_id=new_session_id())
    _record_as_saved(client, token, user, project_id, theirs)

    _play(client, token, project_id, "b", input_path=theirs)

    assert sandbox["runs"]["b"]["session_id"] == token
    assert sandbox["runs"]["b"]["saved_paths"][theirs]["path"]


def test_a_saved_input_the_caller_made_runs_in_a_kept_session(client, user_and_token, sandbox):
    import pandas as pd

    from utk_curio.sandbox.util.parsers import save_to_duckdb

    user, token = user_and_token
    project_id = create_project(client, token, name="Reopened")
    mine = save_to_duckdb(pd.DataFrame({"n": [1]}), node_id="n", session_id=token)
    _record_as_saved(client, token, user, project_id, mine)

    _play(client, token, project_id, "b", input_path=mine)

    assert is_kept_session(sandbox["runs"]["b"]["session_id"])
    assert sandbox["runs"]["b"]["saved_paths"][mine]["path"]


def test_a_collaborators_play_stays_in_their_own_session(client, db, user_and_token, sandbox):
    user, token = user_and_token
    project_id = create_project(client, token, name="Shared")
    _other, other_token = _other_account(db)

    _play(client, other_token, project_id, "a")

    assert sandbox["runs"]["a"]["session_id"] == other_token
    assert KeptStepOutput.query.filter_by(project_id=project_id).count() == 0


def test_what_the_owners_keys_made_and_what_was_made_from_it_are_the_owners_alone(
    client, user_and_token, sandbox, monkeypatch,
):
    from utk_curio.backend.app.execution import node_exec
    from utk_curio.backend.app.runs.service import RunError

    user, token = user_and_token
    project_id = create_project(client, token, name="Keys")
    monkeypatch.setattr(node_exec, "resolve_secrets",
                        lambda code, user: {"k": "v"} if "# node a" in code else {})
    _play(client, token, project_id, "a")
    _play(client, token, project_id, "b", input_path="art-a")

    entries = {e.node_id: e for e in KeptStepOutput.query.filter_by(project_id=project_id)}
    assert entries["a"].private_to == entries["b"].private_to == kept.OWNER_ONLY
    for entry in entries.values():
        assert kept.kept_output(project_id, entry.step_key) is None
        assert kept.kept_output(project_id, entry.step_key, private_to=kept.digest("a-viewers-token")) is None
        with pytest.raises(RunError):
            kept.readable_output(project_id, entry.output_path, "a-viewers-token")
        assert kept.owner_entry(project_id, entry.output_path) == entry


def test_the_owners_own_output_lives_its_days_and_a_tabs_its_hour(app, user_and_token, client):
    from utk_curio.backend.extensions import db

    user, token = user_and_token
    project_id = create_project(client, token, name="Lifetimes")
    two_hours_ago = naive_utc_now() - timedelta(hours=2)
    for node, private_to, made_by in (("owners", kept.OWNER_ONLY, kept.MADE_BY_OWNER),
                                      ("tabs", kept.digest("tab-token"), kept.MADE_BY_VIEWER)):
        db.session.add(KeptStepOutput(
            project_id=project_id, node_id=node, step_key=f"key-{node}", session_id=new_session_id(),
            output=json.dumps({"path": f"art-{node}"}), output_path=f"art-{node}",
            artifact_ids=json.dumps([f"art-{node}"]), private_to=private_to, made_by=made_by,
            created_at=two_hours_ago, used_at=two_hours_ago,
        ))
        db.session.commit()

    assert kept.owner_entry(project_id, "art-owners") is not None
    assert kept.kept_output(project_id, "key-tabs", private_to=kept.digest("tab-token")) is None


def test_the_owners_outputs_are_bounded_by_their_days_not_the_viewers_budget(app, user_and_token, client, monkeypatch):
    """The owner's open canvas shows them, so no budget evicts them; the
    viewers' outputs past theirs still go, least recently used first."""
    from utk_curio.backend.extensions import db

    user, token = user_and_token
    project_id = create_project(client, token, name="Budgets")
    monkeypatch.setattr(kept, "MAX_KEPT_BYTES", 100)
    monkeypatch.setattr(kept, "forget_sessions", lambda sessions: None)
    now = naive_utc_now()
    for index, made_by in enumerate([kept.MADE_BY_OWNER] * 3 + [kept.MADE_BY_VIEWER] * 3):
        made = now - timedelta(minutes=10 - index)
        db.session.add(KeptStepOutput(
            project_id=project_id, node_id=f"n{index}", step_key=f"key-{index}", session_id=new_session_id(),
            output=json.dumps({"path": f"art-{index}"}), output_path=f"art-{index}",
            artifact_ids="[]", size_bytes=60, made_by=made_by, created_at=made, used_at=made,
        ))
    db.session.commit()

    kept.prune(now)

    left = {e.node_id for e in KeptStepOutput.query.filter_by(project_id=project_id)}
    assert left == {"n0", "n1", "n2", "n5"}
