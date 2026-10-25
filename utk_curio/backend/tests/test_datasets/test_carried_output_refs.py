"""A dataset ref a dataflow carries reads no output of another account's.

A new dataflow keeps the dataset refs its spec sends (Save a copy, a file's
import), and a ref may name a live output: by its ``curio://outputs/<id>``
URI, or by the store file its ``path`` names. The Data Catalog's routes read
such a URI only under the caller's sign-in (#1150). Node code's
``curio_load_data``, the agents, the Scenario Catalog and discovery build the
catalog with no sign-in, and read it whichever account made it; a ``path``
into the store got past the sign-in too. Now a new dataflow keeps no such ref,
an item's path never reaches the store, and with no sign-in a live output is
read only when its account vouches for it: it carries no session, one of the
account's sign-ins made it, or a run of one of the account's dataflows kept
it. A ref written before this change is read the same way.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import (
    auth_headers,
    create_project,
    store_sandbox_artifact,
    stored_artifact_file,
)

#: What only the other account's output holds.
SECRET = "Bob's own zone"


def _sign_in(db, user, token):
    from utk_curio.backend.app.users.models import UserSession

    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return token


def _other_account(db):
    from utk_curio.backend.app.users.models import User

    other = User(username="bob", name="Bob", email="bob@test.com")
    db.session.add(other)
    db.session.flush()
    return other, _sign_in(db, other, "bob-token-789")


def _table(session, zone="North"):
    """A table a node run stored in *session*: its id."""
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    return save_to_duckdb(
        pd.DataFrame({"zone": [zone, "South"], "pm25": [12.1, 9.8]}), node_id="n", session_id=session,
    )


def _kept_by(db, project_id, node_id, art_id, session):
    """*art_id*, made in the kept session *session*, kept for the runs of
    *project_id*'s owner."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now

    now = naive_utc_now()
    db.session.add(KeptStepOutput(
        project_id=project_id, node_id=node_id, step_key="k" * 64, session_id=session,
        output=json.dumps({"path": art_id, "dataType": "dataframe"}), output_path=art_id,
        artifact_ids=json.dumps([art_id]), private_to=None, made_by=kept.MADE_BY_OWNER,
        created_at=now, used_at=now,
    ))
    db.session.commit()


@pytest.fixture(params=["their sign-in", "their kept run"])
def theirs(request, client, db):
    """A table of the other account's: made in their sign-in, or by a kept run
    of their dataflow, whose session reads what every kept run made."""
    from utk_curio.common.kept_sessions import new_session_id

    _bob, bob_token = _other_account(db)
    if request.param == "their sign-in":
        return _table(bob_token, zone=SECRET)
    session = new_session_id()
    art_id = _table(session, zone=SECRET)
    _kept_by(db, create_project(client, bob_token, name="Bob's dataflow"), "bob-node", art_id, session)
    return art_id


def _by_uri(dataset_id, art_id):
    """A ref naming the live output *art_id* by its URI."""
    return {
        "id": dataset_id, "origin": "computed", "format": "parquet", "title": dataset_id,
        "uri": f"curio://outputs/{art_id}",
    }


def _by_path(dataset_id, art_id):
    """A ref naming the live output *art_id* by the file the store holds for it."""
    return {
        "id": dataset_id, "origin": "imported", "format": "parquet", "title": dataset_id,
        "path": str(stored_artifact_file(art_id)),
    }


REFS = {"uri": _by_uri, "path": _by_path}


def _carrying(user, project_id, refs):
    """Put *refs* in *project_id*'s spec on disk, as a new dataflow kept the
    refs its spec sent before this change."""
    from utk_curio.backend.app.projects import services, storage

    user_key = services._user_dir_key(user)
    spec = storage.read_spec(user_key, project_id)
    spec["dataflow"]["datasets"] = list(refs)
    storage.write_spec(user_key, project_id, spec)


def _paths_node_code_gets(client, token, project_id, dataset_ids, monkeypatch) -> dict:
    """The dataset paths the sandbox is handed for a node of *project_id*
    whose code loads each of *dataset_ids* (``curio_load_data``)."""
    sent = {}
    reply = MagicMock()
    reply.json.return_value = {"stdout": "", "stderr": "", "output": {}}

    def fake_call(method, path, **kwargs):
        if path == "/exec":
            sent["body"] = json.loads(kwargs["data"])
        return reply

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", fake_call)
    code = "".join(f'    d{index} = curio_load_data("{dataset_id}")\n' for index, dataset_id in enumerate(dataset_ids))
    resp = client.post("/processPythonCode", data=json.dumps({
        "code": code + "    return 1\n",
        "nodeType": "PYTHON_COMPUTATION",
        "dataflowId": project_id,
        "input": {"path": "", "dataType": "str"},
        "saveOutputDataset": False,
    }), headers=auth_headers(token))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return sent["body"]["dataset_paths"]


# -- Node code --------------------------------------------------------------------

@pytest.mark.parametrize("by", sorted(REFS))
def test_node_code_reads_no_output_of_another_account_through_a_carried_ref(
    client, db, user_and_token, theirs, by, monkeypatch,
):
    """The dataflow also carries a ref to an output its own kept run made, so
    a kept session that vouches for one name must not read another's."""
    from utk_curio.common.kept_sessions import new_session_id

    user, token = user_and_token
    project_id = create_project(client, token, name="Carries refs")
    session = new_session_id()
    mine = _table(session)
    _kept_by(db, project_id, "my-node", mine, session)
    _carrying(user, project_id, [_by_uri("computed.mine", mine), REFS[by]("carried.theirs", theirs)])

    paths = _paths_node_code_gets(client, token, project_id, ["computed.mine", "carried.theirs"], monkeypatch)

    assert "computed.mine" in paths
    assert "carried.theirs" not in paths
    assert str(stored_artifact_file(theirs)) not in json.dumps(paths)


def test_node_code_still_reads_the_accounts_own_outputs_through_an_old_ref(client, db, user_and_token, monkeypatch):
    """Made in an earlier sign-in of the account, by a kept run of its
    dataflow, or with no session at all."""
    from utk_curio.common.kept_sessions import new_session_id

    user, token = user_and_token
    project_id = create_project(client, token, name="Old refs")
    earlier = _table(_sign_in(db, user, "alice-token-earlier"))
    session = new_session_id()
    kept = _table(session)
    _kept_by(db, project_id, "kept-node", kept, session)
    untagged = store_sandbox_artifact(pd.DataFrame({"n": [1, 2]}))
    _carrying(user, project_id, [
        _by_uri("computed.earlier", earlier), _by_uri("computed.kept", kept), _by_uri("computed.untagged", untagged),
    ])

    paths = _paths_node_code_gets(
        client, token, project_id, ["computed.earlier", "computed.kept", "computed.untagged"], monkeypatch,
    )

    assert set(paths) == {"computed.earlier", "computed.kept", "computed.untagged"}


# -- The Data Catalog -----------------------------------------------------------

def test_a_carried_path_into_the_store_reads_no_output_on_the_catalog_routes(client, user_and_token, theirs):
    user, token = user_and_token
    project_id = create_project(client, token, name="Carries a path")
    _carrying(user, project_id, [_by_path("carried.theirs", theirs)])

    download = client.get(f"/api/datasets/carried.theirs/download?dataflowId={project_id}", headers=auth_headers(token))
    preview = client.get(f"/api/datasets/carried.theirs/preview?dataflowId={project_id}", headers=auth_headers(token))

    assert download.status_code == 404
    assert SECRET not in download.get_data(as_text=True)
    assert SECRET not in preview.get_data(as_text=True)


# -- A new dataflow ---------------------------------------------------------------

def test_a_new_dataflow_keeps_no_ref_naming_a_live_output(client, user_and_token, theirs):
    from utk_curio.backend.app.projects import services, storage

    user, token = user_and_token
    installed = {"datasetId": "imported.kept", "dirName": "imported.kept@1", "origin": "imported"}
    resp = client.post("/api/projects", data=json.dumps({
        "name": "Carries refs",
        "spec": {"dataflow": {"name": "Carries refs", "nodes": [], "edges": [], "datasets": [
            _by_uri("carried.by-uri", theirs), _by_path("carried.by-path", theirs), installed,
        ]}},
        "outputs": [],
    }), headers=auth_headers(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)

    spec = storage.read_spec(services._user_dir_key(user), resp.get_json()["id"])
    kept = [ref.get("datasetId") or ref.get("id") for ref in spec["dataflow"].get("datasets") or []]
    assert kept == ["imported.kept"]
