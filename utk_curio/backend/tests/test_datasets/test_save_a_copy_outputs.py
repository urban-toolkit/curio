"""Save a copy brings the saved outputs of the dataflow it copies.

File > Save a copy makes a new dataflow from the tab and names the outputs the
tab shows. A save installs only the outputs its caller may read (#1150), so a
copy of a dataflow another account shared came with none of its saved
outputs; before that, an output came only while the store still held it,
which it does for seven days (#1141). Now the create names the dataflow it
copies (``copy_of``), and each node whose output is the one that dataflow
saved gets that saved output, copied from its owner's Data Catalog into the
copying account's as Duplicate copies one: its files linked, its manifest
naming the copy's dataflow and node. So the copy reads it after the store
and the owner have let theirs go. Anyone who may open a dataflow may read its
saved outputs (``load_shared_project``). Nothing comes from the store, and no
result the owner's runs kept is copied (#1143).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers

#: The warning a save gives an output it cannot install.
MISSING = "output artifact not found at save time"
TABLE_ZONE = "Bob's table zone"
BUNDLE_ZONE = "Bob's bundle zone"
NODES = ("table-node", "bundle-node")


def _spec(name, *nodes):
    return {"dataflow": {
        "name": name,
        "nodes": [{"id": node, "type": "curio.builtin/computation-analysis"} for node in nodes],
        "edges": [],
    }}


def _account(db, username, token):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


def _stored(value, session):
    """*value* as a node run stored it in *session*: its artifact id."""
    from utk_curio.sandbox.util.parsers import save_to_duckdb

    return save_to_duckdb(value, node_id="n", session_id=session)


def _ref(node_id, art_id, data_type="dataframe"):
    return {"node_id": node_id, "filename": art_id, "data_type": data_type}


def _create(client, token, name, spec, outputs, **extra) -> dict:
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": name, "spec": spec, "outputs": outputs, **extra}),
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


def _kept_by(db, project_id, node_id, art_id, session, key):
    """*art_id*, made in the kept session *session*, kept for the runs of
    *project_id*'s owner under the step key *key*."""
    from utk_curio.backend.app.runs import kept
    from utk_curio.backend.app.runs.models import KeptStepOutput, naive_utc_now

    now = naive_utc_now()
    db.session.add(KeptStepOutput(
        project_id=project_id, node_id=node_id, step_key=key, session_id=session,
        output=json.dumps({"path": art_id, "dataType": "dataframe"}), output_path=art_id,
        artifact_ids=json.dumps([art_id]), private_to=None, made_by=kept.MADE_BY_OWNER,
        created_at=now, used_at=now,
    ))
    db.session.commit()


def _forget_the_store():
    """What the store's sweep does to every output once its days are up."""
    from utk_curio.sandbox.util import parsers

    parsers.forget_made_before(int((time.time() + 3 * 24 * 3600) * 1000))


def _outputs(body) -> list:
    return sorted(output["node_id"] for output in body["outputs"])


def _warnings(body) -> dict:
    return {warning["node_id"]: warning["reason"] for warning in body["dataset_install_warnings"]}


def _no_dataset_of(user, project_id, node_id) -> bool:
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    return not dataset_dir(str(user.id), f"{computed_dataset_id(node_id, project_id)}@1").exists()


@pytest.fixture()
def bobs(client, db):
    """Bob's dataflow, which saved a table and a bundle from his own runs."""
    token = "bob-token-789"
    bob = _account(db, "bob", token)
    table = _stored(pd.DataFrame({"zone": [TABLE_ZONE, "South"], "pm25": [12.1, 9.8]}), token)
    bundle = _stored((pd.DataFrame({"zone": [BUNDLE_ZONE]}), pd.DataFrame({"n": [1, 2]})), token)
    saved = [_ref("table-node", table), _ref("bundle-node", bundle, "outputs")]
    body = _create(client, token, "Bob's dataflow", _spec("Bob's dataflow", *NODES), saved)
    assert _outputs(body) == sorted(NODES), body
    return SimpleNamespace(id=body["id"], user=bob, token=token, refs=saved)


def _shared_outputs(client, project_id) -> list:
    """The outputs a tab showing the dataflow's share link holds."""
    resp = client.get(f"/api/projects/{project_id}/shared")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["outputs"]


def _save_a_copy(client, token, source_id, outputs) -> dict:
    name = "Bob's dataflow (copy)"
    return _create(client, token, name, _spec(name, *NODES), outputs, copy_of=source_id)


def _reads_both(client, token, copy_id):
    """The copy's two saved outputs, listed and read in the Data Catalog of
    the account *token* signs in to."""
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    table_id, bundle_id = (computed_dataset_id(node, copy_id) for node in NODES)
    listing = client.get("/api/datasets/catalog?includeHub=true", headers=auth_headers(token))
    assert listing.status_code == 200, listing.get_data(as_text=True)
    items = {item["id"]: item for item in listing.get_json()["items"]}
    assert table_id in items and bundle_id in items, sorted(items)
    assert items[table_id]["producerDataflowId"] == items[bundle_id]["producerDataflowId"] == copy_id

    table = client.get(f"/api/datasets/{table_id}/preview", headers=auth_headers(token))
    download = client.get(f"/api/datasets/{table_id}/download", headers=auth_headers(token))
    bundle = client.get(f"/api/datasets/{bundle_id}/preview", headers=auth_headers(token))
    assert table.status_code == download.status_code == bundle.status_code == 200
    assert TABLE_ZONE in table.get_data(as_text=True)
    assert TABLE_ZONE in download.get_data(as_text=True)
    assert bundle.get_json().get("bundle") is True
    assert BUNDLE_ZONE in bundle.get_data(as_text=True)


# -- Another account's dataflow ---------------------------------------------------

def test_a_copy_of_another_accounts_dataflow_brings_its_saved_outputs(client, user_and_token, bobs):
    from utk_curio.backend.app.datasets.infrastructure.storage import user_datasets_dir
    from utk_curio.backend.app.projects import services, storage

    alice, token = user_and_token
    copy = _save_a_copy(client, token, bobs.id, _shared_outputs(client, bobs.id))

    assert _warnings(copy) == {}
    assert _outputs(copy) == sorted(NODES)
    _reads_both(client, token, copy["id"])
    alice_key, bob_key = services._user_dir_key(alice), services._user_dir_key(bobs.user)
    for ref in bobs.refs:
        copied = storage.saved_output_file(alice_key, copy["id"], ref["filename"])
        theirs = storage.saved_output_file(bob_key, bobs.id, ref["filename"])
        assert copied is not None and theirs is not None
        assert Path(copied.path).resolve().is_relative_to(user_datasets_dir(alice_key).resolve())
        assert os.path.samefile(copied.path, theirs.path)


def test_the_copy_reads_its_outputs_once_the_store_and_their_owner_let_go(client, user_and_token, bobs):
    from utk_curio.backend.app.datasets.install.installer import computed_dataset_id

    _, token = user_and_token
    copy = _save_a_copy(client, token, bobs.id, _shared_outputs(client, bobs.id))
    assert _outputs(copy) == sorted(NODES), copy

    _forget_the_store()
    _reads_both(client, token, copy["id"])

    for node in NODES:
        resp = client.delete(f"/api/datasets/{computed_dataset_id(node, bobs.id)}", headers=auth_headers(bobs.token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
    _reads_both(client, token, copy["id"])
    reopened = client.get(f"/api/projects/{copy['id']}", headers=auth_headers(token))
    assert reopened.status_code == 200, reopened.get_data(as_text=True)
    assert _outputs(reopened.get_json()) == sorted(NODES)


def test_a_copy_brings_no_result_the_owners_runs_kept(client, db, user_and_token, bobs):
    """A newer result kept for a node that saved one, and one kept for a node
    that saved none, are the owner's alone."""
    from utk_curio.common.kept_sessions import new_session_id

    alice, token = user_and_token
    session = new_session_id()
    newer = _stored(pd.DataFrame({"zone": ["Bob's kept zone"]}), session)
    unsaved = _stored(pd.DataFrame({"n": [3]}), session)
    _kept_by(db, bobs.id, "table-node", newer, session, "a" * 64)
    _kept_by(db, bobs.id, "kept-node", unsaved, session, "b" * 64)
    name = "A copy of what Bob's runs kept"

    copy = _create(
        client, token, name, _spec(name, *NODES, "kept-node"),
        [_ref("table-node", newer), _ref("kept-node", unsaved)], copy_of=bobs.id,
    )

    assert _outputs(copy) == []
    assert _warnings(copy) == {"table-node": MISSING, "kept-node": MISSING}
    assert _no_dataset_of(alice, copy["id"], "table-node")
    assert _no_dataset_of(alice, copy["id"], "kept-node")


def test_a_copy_of_no_dataflow_or_of_a_name_it_did_not_save_brings_nothing(client, user_and_token, bobs):
    alice, token = user_and_token
    table = bobs.refs[0]["filename"]
    never_saved = _stored(pd.DataFrame({"zone": ["Bob's unsaved zone"]}), bobs.token)

    from_nowhere = _save_a_copy(client, token, str(uuid4()), bobs.refs)
    not_saved = _save_a_copy(client, token, bobs.id, [
        # A name Bob made but never saved, and the name his dataflow saved
        # for the other node.
        _ref("table-node", never_saved), _ref("bundle-node", table),
    ])

    for copy in (from_nowhere, not_saved):
        assert _outputs(copy) == []
        assert _warnings(copy) == {"table-node": MISSING, "bundle-node": MISSING}
        assert all(_no_dataset_of(alice, copy["id"], node) for node in NODES)


# -- The owner's own dataflow -----------------------------------------------------

def test_an_owners_copy_of_their_own_dataflow_links_its_saved_outputs(client, bobs):
    """The same path, with nothing read from the store, which has forgotten
    the outputs by then."""
    from utk_curio.backend.app.projects import services, storage

    _forget_the_store()
    copy = _save_a_copy(client, bobs.token, bobs.id, bobs.refs)

    assert _warnings(copy) == {}
    assert _outputs(copy) == sorted(NODES)
    bob_key = services._user_dir_key(bobs.user)
    for ref in bobs.refs:
        copied = storage.saved_output_file(bob_key, copy["id"], ref["filename"])
        source = storage.saved_output_file(bob_key, bobs.id, ref["filename"])
        assert copied is not None and source is not None
        assert copied.path != source.path
        assert os.path.samefile(copied.path, source.path)
