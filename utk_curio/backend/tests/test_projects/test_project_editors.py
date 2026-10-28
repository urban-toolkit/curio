"""A dataflow's editors, as its owner invites and removes them from the Share
menu (``/api/projects/<id>/editors``, ``projects/access.py``).

Only the owner manages the list: anyone else is told the dataflow is not
found, and no guest manages one, since the shared guest owns the examples
every hosted guest opens as its own. An invite names an account by username,
never a guest's or the owner's.
"""
import json

import pytest

from utk_curio.backend.app.projects import services
from utk_curio.backend.app.projects.schemas import ProjectCreate


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _account(db, username, *, is_guest=False):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=None if is_guest else f"{username}@test.com",
                is_guest=is_guest)
    db.session.add(user)
    db.session.flush()
    token = f"{username}-token"
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user, token


@pytest.fixture()
def dataflow(app, db, user_and_token, tmp_curio):
    alice, token = user_and_token
    detail = services.save_project(alice, ProjectCreate(name="Shared", spec={"dataflow": {"name": "Shared"}}))
    return detail.id, alice, token


def _invite(client, project_id, token, username):
    return client.post(f"/api/projects/{project_id}/editors",
                       data=json.dumps({"username": username}), headers=_auth(token))


def test_the_owner_invites_lists_and_removes_an_editor(client, db, dataflow):
    project_id, _alice, token = dataflow
    bob, _ = _account(db, "bob")

    added = _invite(client, project_id, token, "bob")
    assert added.status_code == 201, added.get_json()
    assert [(e["user_id"], e["username"], e["name"]) for e in added.get_json()["editors"]] == [
        (bob.id, "bob", "Bob"),
    ]
    assert added.get_json()["editors"][0]["added_at"]

    listed = client.get(f"/api/projects/{project_id}/editors", headers=_auth(token))
    assert listed.status_code == 200
    assert [e["username"] for e in listed.get_json()["editors"]] == ["bob"]

    removed = client.delete(f"/api/projects/{project_id}/editors/{bob.id}", headers=_auth(token))
    assert removed.status_code == 200
    assert removed.get_json() == {"editors": []}
    again = client.delete(f"/api/projects/{project_id}/editors/{bob.id}", headers=_auth(token))
    assert again.status_code == 404


def test_the_editor_routes_answer_the_owner_alone(client, db, dataflow):
    """An editor, or any other account, is told the dataflow is not found,
    as the other owner routes tell them: it cannot read or change the list."""
    project_id, _alice, token = dataflow
    bob, bob_token = _account(db, "bob")
    _carol, _ = _account(db, "carol")
    assert _invite(client, project_id, token, "bob").status_code == 201

    assert client.get(f"/api/projects/{project_id}/editors", headers=_auth(bob_token)).status_code == 404
    assert _invite(client, project_id, bob_token, "carol").status_code == 404
    assert client.delete(f"/api/projects/{project_id}/editors/{bob.id}",
                         headers=_auth(bob_token)).status_code == 404
    listed = client.get(f"/api/projects/{project_id}/editors", headers=_auth(token)).get_json()
    assert [e["username"] for e in listed["editors"]] == ["bob"]
    assert client.get(f"/api/projects/{project_id}/editors").status_code == 401


@pytest.mark.parametrize("no_auth", [False, True])
def test_a_guest_manages_no_editors(client, db, tmp_curio, monkeypatch, no_auth):
    """The shared guest owns the examples, so every hosted guest would manage
    their editors; without --deploy it is the one local user, with nobody to
    invite."""
    from utk_curio.backend import config
    from utk_curio.backend.app.projects.access import GUEST_INVITE_REFUSAL

    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)
    guest, token = _account(db, config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
    _account(db, "bob")
    example = services.save_project(guest, ProjectCreate(name="Example", spec={"dataflow": {"name": "Example"}})).id
    monkeypatch.setattr(config, "CURIO_NO_AUTH", no_auth)

    for resp in (
        client.get(f"/api/projects/{example}/editors", headers=_auth(token)),
        _invite(client, example, token, "bob"),
    ):
        assert resp.status_code == 403
        assert resp.get_json() == {"error": GUEST_INVITE_REFUSAL}


def test_an_invite_names_an_account_that_is_neither_a_guest_nor_the_owner(client, db, dataflow):
    from utk_curio.backend import config
    from utk_curio.backend.app.projects.access import GUEST_INVITEE, NO_USERNAME, OWNER_INVITEE

    project_id, _alice, token = dataflow
    _account(db, config.CURIO_SHARED_GUEST_USERNAME, is_guest=True)
    _account(db, "bob")

    cases = {
        "": (400, NO_USERNAME),
        "zed": (404, "No account is named 'zed'."),
        config.CURIO_SHARED_GUEST_USERNAME: (400, GUEST_INVITEE),
        "alice": (400, OWNER_INVITEE),
    }
    for username, (status, error) in cases.items():
        resp = _invite(client, project_id, token, username)
        assert (resp.status_code, resp.get_json()) == (status, {"error": error}), username
    assert _invite(client, project_id, token, "bob").status_code == 201
    twice = _invite(client, project_id, token, "bob")
    assert (twice.status_code, twice.get_json()) == (409, {"error": "bob already edits this dataflow."})


def test_deleting_a_dataflow_deletes_its_editors(client, db, dataflow):
    from utk_curio.backend.app.projects.models import ProjectEditor

    project_id, _alice, token = dataflow
    _account(db, "bob")
    assert _invite(client, project_id, token, "bob").status_code == 201
    assert ProjectEditor.query.filter_by(project_id=project_id).count() == 1

    assert client.delete(f"/api/projects/{project_id}", headers=_auth(token)).status_code == 204

    assert ProjectEditor.query.filter_by(project_id=project_id).count() == 0


def test_a_copy_of_a_dataflow_has_no_editors(client, db, dataflow):
    """Editors are invited to one dataflow: its copy starts with none."""
    project_id, alice, token = dataflow
    _account(db, "bob")
    assert _invite(client, project_id, token, "bob").status_code == 201

    copy = services.duplicate_project(alice, project_id)

    listed = client.get(f"/api/projects/{copy.id}/editors", headers=_auth(token))
    assert listed.status_code == 200 and listed.get_json() == {"editors": []}


def test_an_editor_saves_nothing(client, db, dataflow):
    """Saving stays the owner's: an editor's save of the dataflow is refused as
    anyone's but the owner's is."""
    project_id, _alice, token = dataflow
    _bob, bob_token = _account(db, "bob")
    assert _invite(client, project_id, token, "bob").status_code == 201

    resp = client.put(f"/api/projects/{project_id}", data=json.dumps({"name": "Bob's now"}),
                      headers=_auth(bob_token))

    assert resp.status_code == 404
