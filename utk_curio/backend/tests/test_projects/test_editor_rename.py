"""A rename an invited editor makes on the canvas reaches the owner's project
row (``PUT /api/projects/<id>/name``).

The name is stored twice: the project row, which the owner's Projects page
lists, and the dataflow's, which the canvas title shows. The doc takes the
dataflow's from the editor's canvas, and no doc writes the row; the owner's
tab renames the row with the name-only PUT of the dataflow, which refuses
anyone but the owner. So the editor's rename goes through a route of its own,
which renames both as that PUT does. Anyone the owner did not invite is
refused, and the name stays.

New names are imported inside each test, so the module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import pytest

BOB_TOKEN = "bob-token-for-rename-tests"
CAROL_TOKEN = "carol-token-for-rename-tests"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _account(db, username: str, token: str):
    from utk_curio.backend.app.users.models import User, UserSession

    user = User(username=username, name=username.title(), email=f"{username}@test.com")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token=token))
    db.session.commit()
    return user


@pytest.fixture()
def shared(client, db, user_and_token, tmp_curio):
    """alice's dataflow "Before", bob invited to edit it, carol invited to nothing."""
    from utk_curio.backend.app.projects import access

    alice, token = user_and_token
    r = client.post(
        "/api/projects",
        json={"name": "Before", "spec": {"dataflow": {"name": "Before", "nodes": [], "edges": []}}, "outputs": []},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    project_id = r.get_json()["id"]
    _account(db, "bob", BOB_TOKEN)
    _account(db, "carol", CAROL_TOKEN)
    access.add_editor(alice, project_id, "bob")
    return project_id, token


def _names(client, token: str, project_id: str) -> tuple:
    detail = client.get(f"/api/projects/{project_id}", headers=_auth(token)).get_json()
    return detail["project"]["name"], detail["spec"]["dataflow"]["name"]


def test_an_invited_editors_rename_reaches_the_owners_project_row_and_the_dataflow(client, shared):
    project_id, owner_token = shared

    r = client.put(f"/api/projects/{project_id}/name", json={"name": "  Renamed by Bob "},
                   headers=_auth(BOB_TOKEN))

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"id": project_id, "name": "Renamed by Bob"}
    assert _names(client, owner_token, project_id) == ("Renamed by Bob", "Renamed by Bob")
    listed = {p["id"]: p["name"] for p in client.get("/api/projects", headers=_auth(owner_token)).get_json()}
    assert listed[project_id] == "Renamed by Bob"


def test_anyone_the_owner_did_not_invite_is_refused_and_the_name_stays(client, shared):
    project_id, owner_token = shared

    r = client.put(f"/api/projects/{project_id}/name", json={"name": "Renamed by Carol"},
                   headers=_auth(CAROL_TOKEN))

    assert r.status_code == 403, r.get_data(as_text=True)
    assert _names(client, owner_token, project_id) == ("Before", "Before")


def test_a_rename_with_no_name_is_refused(client, shared):
    project_id, owner_token = shared

    r = client.put(f"/api/projects/{project_id}/name", json={"name": "   "}, headers=_auth(BOB_TOKEN))

    assert r.status_code == 400, r.get_data(as_text=True)
    assert _names(client, owner_token, project_id) == ("Before", "Before")


def test_a_rename_of_a_dataflow_that_is_gone_is_not_found(client, shared):
    r = client.put("/api/projects/00000000-0000-4000-8000-000000000000/name", json={"name": "X"},
                   headers=_auth(BOB_TOKEN))

    assert r.status_code == 404, r.get_data(as_text=True)
