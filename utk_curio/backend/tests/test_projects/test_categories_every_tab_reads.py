"""Every tab of a dataflow reads its categories as it is now, which the canvas
title shows (``GET /api/projects/<id>/categories``).

No tab saves the dataflow any more, whose answer carried them, so each tab
asks again as the dataflow changes. The owner, an editor the owner invited and
a watcher (anyone else who opens the dataflow's link) are each answered, as the
shared read serves the dataflow to anyone who opens its link, with the
categories a load shows. A dataflow that is gone is not found, as that read
says.

The route is called inside each test, so a checkout without it fails each test
on its own.
"""

from __future__ import annotations

import pytest

BOB_TOKEN = "bob-token-for-categories-tests"
CAROL_TOKEN = "carol-token-for-categories-tests"
NODE_TYPE = "curio.builtin/computation-analysis"


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


def _change(user, project_id: str, change) -> None:
    """Change the dataflow as a tab's edit reaches its doc: no save follows."""
    from utk_curio.backend.app.collaboration import dataflow_docs
    from utk_curio.backend.app.projects.services import _user_dir_key

    ukey = _user_dir_key(user)
    spec = dataflow_docs.live(ukey, project_id)
    change(spec["dataflow"])
    dataflow_docs.write(ukey, project_id, spec, dataflow_docs.person(ukey, "edit"))


@pytest.fixture()
def shared(client, db, user_and_token, tmp_curio):
    """alice's dataflow, whose code a tab's edit made import pandas after it
    was made, bob invited to edit it, and carol invited to nothing."""
    from utk_curio.backend.app.projects import access

    alice, token = user_and_token
    r = client.post(
        "/api/projects",
        json={"name": "Tables", "outputs": [], "spec": {"dataflow": {
            "name": "Tables", "edges": [], "nodes": [{"id": "a", "type": NODE_TYPE, "content": "return 1"}],
        }}},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.get_data(as_text=True)
    project_id = r.get_json()["id"]
    _change(alice, project_id, lambda dataflow: dataflow["nodes"][0].update(
        content="import pandas as pd\nreturn pd.DataFrame({'a': [1]})",
    ))
    _account(db, "bob", BOB_TOKEN)
    _account(db, "carol", CAROL_TOKEN)
    access.add_editor(alice, project_id, "bob")
    return project_id, token


def _loaded(client, token: str, project_id: str) -> dict:
    """The categories the owner's load of the dataflow shows."""
    r = client.get(f"/api/projects/{project_id}", headers=_auth(token))
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["project"]["categories"]


def test_the_owner_reads_the_categories_of_the_dataflow_as_it_is_now(client, shared):
    project_id, owner_token = shared
    loaded = _loaded(client, owner_token, project_id)

    r = client.get(f"/api/projects/{project_id}/categories", headers=_auth(owner_token))

    assert r.status_code == 200, r.get_data(as_text=True)
    categories = r.get_json()["categories"]
    # The edit no save followed: its code imports pandas.
    assert "Pandas" in categories["auto"]["tags"]
    assert categories == loaded


def test_an_editor_the_owner_invited_reads_them(client, shared):
    project_id, owner_token = shared
    loaded = _loaded(client, owner_token, project_id)

    r = client.get(f"/api/projects/{project_id}/categories", headers=_auth(BOB_TOKEN))

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["categories"] == loaded


def test_a_watcher_reads_them_as_anyone_who_opens_the_dataflows_link(client, shared):
    """carol, whom the owner did not invite, watches the dataflow she opens by
    its link (``access.room_role``), whose shared read serves it to her."""
    project_id, owner_token = shared
    loaded = _loaded(client, owner_token, project_id)
    assert client.get(f"/api/projects/{project_id}/shared").status_code == 200

    r = client.get(f"/api/projects/{project_id}/categories", headers=_auth(CAROL_TOKEN))

    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["categories"] == loaded


def test_a_dataflow_that_is_gone_is_not_found(client, shared):
    project_id, owner_token = shared
    assert client.delete(f"/api/projects/{project_id}", headers=_auth(owner_token)).status_code == 204

    for token in (owner_token, BOB_TOKEN, CAROL_TOKEN):
        r = client.get(f"/api/projects/{project_id}/categories", headers=_auth(token))
        assert r.status_code == 404, r.get_data(as_text=True)
        assert r.get_json() == {"error": "Project not found"}
    r = client.get("/api/projects/00000000-0000-4000-8000-000000000000/categories", headers=_auth(CAROL_TOKEN))
    assert r.status_code == 404, r.get_data(as_text=True)
    assert r.get_json() == {"error": "Project not found"}
