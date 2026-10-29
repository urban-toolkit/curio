"""An output a request names is read or installed only if its caller may read it.

A save names the outputs it installs in the caller's Data Catalog. The Data
Catalog's live outputs name what the canvas holds, Install names the output it
adds, and a new dataflow's spec may carry a dataset ref naming one. Each used
to reach any output in the store by its id, so an account that learned the id
of another account's output could install it in its own Data Catalog, preview
it or download it. Now each is read under the session its caller reads it
under (``runs/kept.readable_by``): the caller's sign-in, or the kept session
that made it when the runs of one of the caller's dataflows kept it. One the
caller may not read fails as one that is gone does, so a refusal says nothing
of whether it exists. A run on the server records what it made, unasked.
"""
from __future__ import annotations

import base64
import json

import pandas as pd
import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers, create_project

#: The warning a save gives an output it cannot install.
MISSING = "output artifact not found at save time"
#: An artifact id no run made.
GONE = "1700000000000_deadbeef"
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


def _ref(node_id, art_id):
    return {"node_id": node_id, "filename": art_id, "data_type": "dataframe"}


def _live(**names) -> str:
    """The ``liveOutputs`` query value naming each node's output."""
    return base64.b64encode(json.dumps([_ref(node, art_id) for node, art_id in names.items()]).encode()).decode()


def _put(client, token, project_id, outputs) -> dict:
    resp = client.put(
        f"/api/projects/{project_id}", data=json.dumps({"outputs": outputs}), headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _installed(body) -> list:
    return sorted(output["node_id"] for output in body["outputs"])


def _warnings(body) -> dict:
    return {warning["node_id"]: warning["reason"] for warning in body["dataset_install_warnings"]}


def _no_dataset_of(user, project_id, node_id) -> bool:
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    return not dataset_dir(str(user.id), f"{computed_dataset_id(node_id, project_id)}@1").exists()


# -- A save -------------------------------------------------------------------

def test_a_save_installs_only_the_outputs_its_caller_may_read(client, user_and_token, theirs):
    user, token = user_and_token
    project_id = create_project(client, token, name="A save")
    mine = _table(token)

    body = _put(client, token, project_id, [_ref("mine", mine), _ref("theirs", theirs), _ref("gone", GONE)])

    assert _installed(body) == ["mine"]
    assert _warnings(body) == {"theirs": MISSING, "gone": MISSING}
    assert _no_dataset_of(user, project_id, "theirs")


def test_a_canvas_records_only_the_outputs_its_caller_may_read(client, user_and_token, theirs):
    """The outputs the owner's canvas sends after a run, a pin or a scenario
    (no tab saves the dataflow) pass the same check a save's do."""
    user, token = user_and_token
    project_id = create_project(client, token, name="A canvas's outputs")
    mine = _table(token)

    resp = client.post(
        f"/api/projects/{project_id}/outputs",
        data=json.dumps({"outputs": [_ref("mine", mine), _ref("theirs", theirs), _ref("gone", GONE)]}),
        headers=auth_headers(token),
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert _installed(body) == ["mine"]
    assert _warnings(body) == {"theirs": MISSING, "gone": MISSING}
    assert _no_dataset_of(user, project_id, "theirs")


def test_a_new_dataflow_installs_only_the_outputs_its_creator_may_read(client, user_and_token, theirs):
    user, token = user_and_token
    mine = _table(token)

    resp = client.post("/api/projects", data=json.dumps({
        "name": "A copy",
        "spec": {"dataflow": {"name": "A copy", "nodes": [], "edges": []}},
        "outputs": [_ref("mine", mine), _ref("theirs", theirs), _ref("gone", GONE)],
    }), headers=auth_headers(token))

    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert _installed(body) == ["mine"]
    assert _warnings(body) == {"theirs": MISSING, "gone": MISSING}
    assert _no_dataset_of(user, body["id"], "theirs")


def test_a_save_after_a_new_sign_in_installs_what_the_owners_runs_kept(client, db, user_and_token):
    from utk_curio.common.kept_sessions import new_session_id

    user, token = user_and_token
    project_id = create_project(client, token, name="Kept, then saved")
    session = new_session_id()
    art_id = _table(session)
    _kept_by(db, project_id, "kept-node", art_id, session)
    later = _sign_in(db, user, "alice-token-later")

    body = _put(client, later, project_id, [_ref("kept-node", art_id)])

    assert _warnings(body) == {}
    assert _installed(body) == ["kept-node"]


def test_a_save_after_a_new_sign_in_keeps_the_output_it_has_on_record(client, db, user_and_token):
    user, token = user_and_token
    project_id = create_project(client, token, name="Saved, then reopened")
    mine = _table(token)
    assert _warnings(_put(client, token, project_id, [_ref("node", mine)])) == {}
    later = _sign_in(db, user, "alice-token-later")

    body = _put(client, later, project_id, [_ref("node", mine)])

    assert _warnings(body) == {}
    assert [output["filename"] for output in body["outputs"]] == [mine]


def test_a_run_on_the_server_records_what_it_made_unasked(client, user_and_token):
    """The run engine records its own steps' outputs, made in sessions no
    sign-in reads (``projects/services.record_node_outputs``)."""
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.projects.schemas import OutputRef
    from utk_curio.common.kept_sessions import new_session_id

    user, token = user_and_token
    project_id = create_project(client, token, name="Recorded by a run")
    made = _table(new_session_id())
    warnings: list = []

    recorded = services.record_node_outputs(
        user, project_id, [OutputRef(node_id="node", filename=made, data_type="dataframe")], warnings,
    )

    assert warnings == []
    assert [ref.filename for ref in recorded] == [made]


# -- The Data Catalog -----------------------------------------------------------

def test_the_catalog_lists_only_the_live_outputs_its_caller_may_read(client, user_and_token, theirs):
    _, token = user_and_token
    mine = _table(token)

    resp = client.get(
        f"/api/datasets/catalog?includeHub=false&liveOutputs={_live(mine=mine, theirs=theirs)}",
        headers=auth_headers(token),
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    ids = [item["id"] for item in resp.get_json()["items"]]
    assert "computed.mine" in ids
    assert "computed.theirs" not in ids
    assert theirs not in resp.get_data(as_text=True)


@pytest.mark.parametrize("route", ["preview", "download"])
def test_a_live_output_is_read_only_by_a_caller_who_may_read_it(client, user_and_token, theirs, route):
    _, token = user_and_token
    mine = _table(token)

    def read(art_id):
        return client.get(
            f"/api/datasets/computed.node/{route}?liveOutputs={_live(node=art_id)}", headers=auth_headers(token),
        )

    refused, gone = read(theirs), read(GONE)

    assert read(mine).status_code == 200
    assert refused.status_code == gone.status_code == 404
    assert refused.get_json() == gone.get_json()
    assert SECRET not in refused.get_data(as_text=True)


def test_a_live_output_is_published_only_by_a_caller_who_may_read_it(
    client, user_and_token, theirs, tmp_path, monkeypatch,
):
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(tmp_path / "catalog"))
    _, token = user_and_token
    mine = _table(token)

    def publish(node_id, art_id):
        return client.post("/api/datasets/publish", data=json.dumps({
            "datasetId": f"computed.{node_id}", "liveOutputs": [_ref(node_id, art_id)],
        }), headers=auth_headers(token))

    refused = publish("theirs", theirs)

    assert publish("mine", mine).status_code == 201
    assert refused.status_code == publish("gone", GONE).status_code == 404
    assert not any(
        SECRET.encode() in path.read_bytes() for path in (tmp_path / "catalog").rglob("*") if path.is_file()
    )


def test_install_adds_a_live_output_only_for_a_caller_who_may_read_it(client, user_and_token, theirs):
    user, token = user_and_token
    project_id = create_project(client, token, name="Install a live output")
    mine = _table(token)

    def install(node_id, art_id):
        return client.post(f"/api/dataflows/{project_id}/datasets/install", data=json.dumps({
            "datasetId": f"computed.{node_id}",
            "sourceItem": {
                "id": f"computed.{node_id}", "origin": "computed",
                "uri": f"curio://outputs/{art_id}", "producerNodeId": node_id,
            },
        }), headers=auth_headers(token))

    refused, gone = install("theirs", theirs), install("gone", GONE)

    assert install("mine", mine).status_code == 200
    assert refused.status_code == gone.status_code == 404
    assert refused.get_json() == gone.get_json()
    assert _no_dataset_of(user, project_id, "theirs")


def test_a_dataset_ref_a_new_dataflow_carries_reads_no_output_its_creator_may_not(client, user_and_token, theirs):
    """A new dataflow kept the dataset refs its spec sent (Save a copy, a
    file's import), and a ref may name a live output by its URI. A new one
    keeps no such ref now (``test_carried_output_refs.py``), so the ref is put
    in the spec on disk, as one written before."""
    from utk_curio.backend.app.projects import services, storage

    user, token = user_and_token
    project_id = create_project(client, token, name="Carries a ref")
    user_key = services._user_dir_key(user)
    spec = storage.read_spec(user_key, project_id)
    spec["dataflow"]["datasets"] = [{
        "id": "computed.carried", "origin": "computed", "format": "parquet",
        "title": "Carried", "uri": f"curio://outputs/{theirs}",
    }]
    storage.write_spec(user_key, project_id, spec)

    listing = client.get(f"/api/datasets/catalog?includeHub=false&dataflowId={project_id}", headers=auth_headers(token))
    download = client.get(f"/api/datasets/computed.carried/download?dataflowId={project_id}", headers=auth_headers(token))
    preview = client.get(f"/api/datasets/computed.carried/preview?dataflowId={project_id}", headers=auth_headers(token))

    assert listing.status_code == 200, listing.get_data(as_text=True)
    carried = next(item for item in listing.get_json()["items"] if item["id"] == "computed.carried")
    assert not carried.get("path")
    assert download.status_code == 404
    assert SECRET not in preview.get_data(as_text=True)
