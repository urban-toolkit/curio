"""The outputs the owner's canvas holds are recorded without a save.

No tab saves the dataflow, which its doc keeps as each change is made. After a
run in the browser, a pin or a scenario, the owner's tab sends the outputs its
canvas holds that the dataflow records (``POST /api/projects/<id>/outputs``):
each is installed in the account's Data Catalog and named in the manifest, a
newer one already on record wins, and one on record whose node the dataflow no
longer holds, or no longer records, goes, as it went from a save. Nothing else
is written: not the dataflow, and not its revision.

The route is called inside each test, so a checkout without it fails each test
on its own.
"""
from __future__ import annotations

import json

from utk_curio.backend.tests.test_datasets.computed_test_helpers import auth_headers
from utk_curio.backend.tests.test_datasets.test_outputs_recorded_by_runs import (
    _artifact,
    _both_saving,
    _create,
    _installed,
    _outputs,
    _record,
)


def _send(client, token, project_id, outputs):
    return client.post(
        f"/api/projects/{project_id}/outputs",
        data=json.dumps({"outputs": [
            {"node_id": node_id, "filename": filename, "data_type": "dict"}
            for node_id, filename in outputs
        ]}),
        headers=auth_headers(token),
    )


def _change(user, project_id, change):
    """Change the dataflow as a tab's edit reaches its doc."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    ukey = _user_dir_key(user)
    spec = dataflow_docs.live(ukey, project_id)
    change(spec["dataflow"])
    dataflow_docs.write(ukey, project_id, spec, dataflow_docs.person(ukey, "edit"))


def test_the_outputs_a_canvas_sends_are_recorded_and_installed(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    a = _artifact(1790000000000, {"v": "a"})
    b = _artifact(1790000000100, {"v": "b"})

    resp = _send(client, token, project_id, [("a", a), ("b", b)])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert sorted((o["node_id"], o["filename"]) for o in body["outputs"]) == [("a", a), ("b", b)]
    assert body["dataset_install_warnings"] == []
    assert _outputs(user, project_id) == {"a": a, "b": b}
    assert _installed(user, project_id, "b") == {"v": "b"}


def test_a_record_answers_the_categories_the_canvas_title_shows(app, client, user_and_token):
    """What a run made changes the dataflow's categories, and no save follows
    a run now to bring them: the record answers them, as File > Save's version
    does (``test_history.py``)."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects import services
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    a = _artifact(1790000000000, {"v": "a"})

    resp = _send(client, token, project_id, [("a", a)])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    expected = services._categories(user, project_id, dataflow_docs.read(_user_dir_key(user), project_id))
    assert resp.get_json()["categories"] == expected


def test_recording_a_canvas_outputs_writes_neither_the_spec_nor_its_revision(app, client, user_and_token):
    from utk_curio.backend.app.projects import storage
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    ukey = _user_dir_key(user)
    spec_before = storage.read_spec(ukey, project_id)
    revision_before = storage.spec_revision(ukey, project_id)

    assert _send(client, token, project_id, [("a", _artifact(1790000000000, {"v": "a"}))]).status_code == 200

    assert storage.read_spec(ukey, project_id) == spec_before
    assert storage.spec_revision(ukey, project_id) == revision_before


def test_a_newer_output_on_record_wins_over_the_one_a_canvas_sends(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    newer = _artifact(1790000000500, {"v": "newer"})
    _record(user, project_id, [("a", newer)])

    resp = _send(client, token, project_id, [("a", _artifact(1790000000000, {"v": "older"}))])

    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert _outputs(user, project_id)["a"] == newer
    assert _installed(user, project_id, "a") == {"v": "newer"}


def test_an_output_on_record_stays_while_its_node_records_it(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    b = _artifact(1790000000100, {"v": "b"})
    _record(user, project_id, [("b", b)])

    assert _send(client, token, project_id, [("a", _artifact(1790000000200, {"v": "a"}))]).status_code == 200

    assert _outputs(user, project_id)["b"] == b


def test_the_output_of_a_node_the_dataflow_no_longer_holds_goes(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    _record(user, project_id, [("b", _artifact(1790000000100, {"v": "b"}))])
    _change(user, project_id, lambda dataflow: dataflow.update(
        nodes=[n for n in dataflow["nodes"] if n["id"] != "b"],
    ))

    assert _send(client, token, project_id, [("a", _artifact(1790000000200, {"v": "a"}))]).status_code == 200

    assert set(_outputs(user, project_id)) == {"a"}


def test_the_output_of_a_node_whose_save_is_off_goes(app, client, user_and_token):
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    _record(user, project_id, [("b", _artifact(1790000000100, {"v": "b"}))])

    def save_off(dataflow):
        for node in dataflow["nodes"]:
            if node["id"] == "b":
                node["saveOutputDataset"] = False

    _change(user, project_id, save_off)

    assert _send(client, token, project_id, [("a", _artifact(1790000000200, {"v": "a"}))]).status_code == 200

    assert set(_outputs(user, project_id)) == {"a"}


def test_a_run_keeps_every_other_nodes_output_as_before(app, client, user_and_token):
    """The run's record keeps what it does not name, whatever the dataflow
    records: the canvas's rule is the canvas's alone."""
    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    _record(user, project_id, [("b", _artifact(1790000000100, {"v": "b"}))])
    _change(user, project_id, lambda dataflow: dataflow.update(
        nodes=[n for n in dataflow["nodes"] if n["id"] != "b"],
    ))

    _record(user, project_id, [("a", _artifact(1790000000200, {"v": "a"}))])

    assert set(_outputs(user, project_id)) == {"a", "b"}


def test_only_the_owner_records_a_dataflows_outputs(app, client, db, user_and_token):
    from utk_curio.backend.app.users.models import User, UserSession

    user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())
    other = User(username="carol", name="Carol", email="carol@test.com")
    db.session.add(other)
    db.session.flush()
    db.session.add(UserSession(user_id=other.id, token="carol-token-1"))
    db.session.commit()

    resp = _send(client, "carol-token-1", project_id, [("a", _artifact(1790000000000, {"v": "a"}))])

    assert resp.status_code == 404
    assert _outputs(user, project_id) == {}


def test_a_body_without_outputs_is_refused(app, client, user_and_token):
    _user, token = user_and_token
    project_id = _create(client, token, spec=_both_saving())

    resp = client.post(f"/api/projects/{project_id}/outputs", data=json.dumps({}), headers=auth_headers(token))

    assert resp.status_code == 400
