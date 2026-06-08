"""Integration tests for /api/auth/* routes via Flask test client."""

import json

from utk_curio.backend.app.projects import tasks
from utk_curio.backend.app.users import routes

def _post(client, path, data=None):
    return client.post(
        path,
        data=json.dumps(data or {}),
        content_type="application/json",
    )


def _get(client, path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.get(path, headers=headers)


def _signup(client, **kwargs):
    defaults = {
        "name": "Alice",
        "username": "alice",
        "password": "password123",
    }
    defaults.update(kwargs)
    return _post(client, "/api/auth/signup", defaults)


class TestSignupRoute:
    def test_signup_returns_201(self, client):
        resp = _signup(client)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["user"]["username"] == "alice"
        assert data["token"]

    def test_duplicate_username_409(self, client):
        _signup(client)
        resp = _signup(client, name="Alice2")
        assert resp.status_code == 409


class TestSigninRoute:
    def test_signin_returns_200(self, client):
        _signup(client)
        resp = _post(
            client,
            "/api/auth/signin",
            {"identifier": "alice", "password": "password123"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["token"]

    def test_wrong_password_401(self, client):
        _signup(client)
        resp = _post(
            client,
            "/api/auth/signin",
            {"identifier": "alice", "password": "wrong"},
        )
        assert resp.status_code == 401


class TestMeRoute:
    def test_me_requires_auth(self, client):
        resp = _get(client, "/api/auth/me")
        assert resp.status_code == 401

    def test_me_with_valid_token(self, client):
        signup_resp = _signup(client)
        token = signup_resp.get_json()["token"]
        resp = _get(client, "/api/auth/me", token=token)
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "alice"


class TestSignoutRoute:
    def test_signout_invalidates_token(self, client):
        signup_resp = _signup(client)
        token = signup_resp.get_json()["token"]
        resp = client.post(
            "/api/auth/signout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # token should no longer work
        resp = _get(client, "/api/auth/me", token=token)
        assert resp.status_code == 401

    def test_signout_disabled_when_auth_off(self, client, monkeypatch):
        monkeypatch.setattr(routes, "CURIO_NO_AUTH", True)
        signin = _post(client, "/api/auth/signin/auto-guest")
        token = signin.get_json()["token"]
        resp = client.post(
            "/api/auth/signout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestGuestRoute:
    def test_guest_login(self, client):
        resp = _post(client, "/api/auth/signin/guest")
        assert resp.status_code == 200
        assert resp.get_json()["user"]["is_guest"] is True

    def test_guest_login_uses_shared_user(self, client):
        first = _post(client, "/api/auth/signin/guest").get_json()
        second = _post(client, "/api/auth/signin/guest").get_json()
        assert first["user"]["id"] == second["user"]["id"]

    def test_auto_guest_forbidden_when_auth_enabled(self, client):
        first = _post(client, "/api/auth/signin/auto-guest")
        assert first.status_code == 403

    def test_auto_guest_when_auth_disabled(self, client, monkeypatch):
        monkeypatch.setattr(routes, "CURIO_NO_AUTH", True)
        first = _post(client, "/api/auth/signin/auto-guest")
        assert first.status_code == 200
        first_body = first.get_json()
        second = client.post(
            "/api/auth/signin/auto-guest",
            headers={"Authorization": f"Bearer {first_body['token']}"},
        )
        assert second.status_code == 200
        second_body = second.get_json()
        assert first_body["user"]["id"] == second_body["user"]["id"]
        assert first_body["token"] == second_body["token"]

    def test_auth_routes_blocked_when_auth_disabled(self, client, monkeypatch):
        monkeypatch.setattr(routes, "CURIO_NO_AUTH", True)
        assert _signup(client).status_code == 403
        assert _post(
            client,
            "/api/auth/signin",
            {"identifier": "alice", "password": "password123"},
        ).status_code == 403
        assert _post(
            client,
            "/api/auth/signin/google",
            {"code": "fake"},
        ).status_code == 403
        assert _post(client, "/api/auth/signin/guest").status_code == 403


class TestPublicConfig:
    def test_public_config(self, client):
        resp = _get(client, "/api/config/public")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "allow_guest_login" in data
        assert "curio_no_auth" in data
        assert "curio_no_project" in data
        assert "skip_project_page" in data
        assert "shared_guest_username" in data
        assert "default_save_node_output" in data
        assert isinstance(data["default_save_node_output"], bool)
        assert "enable_user_auth" not in data


class TestGuestCleanupScheduler:
    def test_cleanup_scheduler_respects_flag(self, monkeypatch, app):
        calls = []

        monkeypatch.setattr(tasks, "GUEST_PROJECT_CLEANUP", False)
        monkeypatch.setattr(
            tasks, "_schedule_next", lambda application: calls.append("scheduled")
        )
        monkeypatch.setattr(
            tasks,
            "cleanup_expired_guest_projects",
            lambda application: calls.append("cleanup"),
        )
        tasks.start_cleanup_scheduler(app)
        assert calls == []

        monkeypatch.setattr(tasks, "GUEST_PROJECT_CLEANUP", True)
        tasks.start_cleanup_scheduler(app)
        assert calls == ["cleanup", "scheduled"]
