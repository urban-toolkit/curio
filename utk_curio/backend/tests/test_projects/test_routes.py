"""Integration tests for /api/projects routes."""
import json
import pytest

from utk_curio.backend.app.projects import storage


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _spec():
    return {"dataflow": {"name": "route-test", "nodes": [], "edges": []}}


def test_create_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    resp = client.post(
        "/api/projects",
        data=json.dumps({"name": "Test", "spec": _spec(), "outputs": []}),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Test"
    assert body["id"]


def test_list_projects(client, user_and_token, tmp_curio):
    _, token = user_and_token
    client.post(
        "/api/projects",
        data=json.dumps({"name": "A", "spec": _spec()}),
        headers=_auth(token),
    )
    client.post(
        "/api/projects",
        data=json.dumps({"name": "B", "spec": _spec()}),
        headers=_auth(token),
    )
    resp = client.get("/api/projects?scope=mine", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2


def test_get_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Detail", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["project"]["name"] == "Detail"
    assert body["spec"] is not None


def test_update_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Upd", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"spec": _spec(), "outputs": [], "name": "Updated"}),
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Updated"
    assert resp.get_json()["spec_revision"] == 2


def test_rename_project_preserves_existing_spec(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Rename Me", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    rename = client.put(
        f"/api/projects/{pid}",
        data=json.dumps({"name": "Renamed"}),
        headers=_auth(token),
    )
    assert rename.status_code == 200
    assert rename.get_json()["name"] == "Renamed"

    loaded = client.get(f"/api/projects/{pid}", headers=_auth(token))
    assert loaded.status_code == 200
    assert loaded.get_json()["spec"] == _spec()


def test_delete_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Del", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.delete(f"/api/projects/{pid}", headers=_auth(token))
    assert resp.status_code == 204

    listing = client.get("/api/projects?scope=mine", headers=_auth(token))
    assert len(listing.get_json()) == 0


def test_duplicate_project(client, user_and_token, tmp_curio):
    _, token = user_and_token
    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Dup", "spec": _spec()}),
        headers=_auth(token),
    )
    pid = create.get_json()["id"]

    resp = client.post(f"/api/projects/{pid}/duplicate", headers=_auth(token))
    assert resp.status_code == 201
    assert resp.get_json()["name"] == "Dup (copy)"


def test_auth_required(client, tmp_curio):
    resp = client.get("/api/projects")
    assert resp.status_code in (401, 403)


def test_non_shared_guest_cannot_create_project(client, guest_user_and_token, tmp_curio):
    _, token = guest_user_and_token

    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Blocked Guest", "spec": _spec(), "outputs": []}),
        headers=_auth(token),
    )
    assert create.status_code == 403
    assert "Guest users cannot save" in create.get_json()["error"]


def test_ownership_isolation(client, user_and_token, db, tmp_curio):
    _, alice_token = user_and_token

    create = client.post(
        "/api/projects",
        data=json.dumps({"name": "Alice's", "spec": _spec()}),
        headers=_auth(alice_token),
    )
    pid = create.get_json()["id"]

    from utk_curio.backend.app.users.models import User, UserSession
    bob = User(username="bob", name="Bob")
    db.session.add(bob)
    db.session.flush()
    s = UserSession(user_id=bob.id, token="bob-token")
    db.session.add(s)
    db.session.commit()

    resp = client.get(f"/api/projects/{pid}", headers=_auth("bob-token"))
    assert resp.status_code == 404
