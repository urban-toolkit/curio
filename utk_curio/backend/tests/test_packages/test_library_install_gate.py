"""Who may pip-install into, or uninstall from, the shared interpreter (#309).

``POST``/``DELETE /api/packages/libraries`` change the interpreter that runs
every user's nodes, so they answer to the same operator switch as the sandbox's
own ``/install`` (``CURIO_ALLOW_RUNTIME_INSTALL``: on for a local launch, off
under ``--auth``/``--deploy``), and never to a guest on an instance with
accounts. A local launch without auth signs in AS the shared guest, so that
case must keep working.
"""
from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.packages import libraries as libs
from utk_curio.backend.app.packages import pip_runner
from utk_curio.backend.app.packages.pip_runner import InstallReport, UninstallReport


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _make_user(db, username: str, token: str, *, is_guest: bool = False):
    from utk_curio.backend.app.users.models import User, UserSession

    u = User(username=username, name=username.title(),
             email=f"{username}@test.com", is_guest=is_guest)
    db.session.add(u)
    db.session.flush()
    db.session.add(UserSession(user_id=u.id, token=token))
    db.session.commit()
    return u


@pytest.fixture
def shared_guest_token(db):
    """The single account every guest sign-in lands on."""
    _make_user(db, config.CURIO_SHARED_GUEST_USERNAME, "guest-token", is_guest=True)
    return "guest-token"


@pytest.fixture
def pip_calls(monkeypatch):
    """Every pip install/uninstall the routes ask for."""
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda deps: calls.append(("install", list(deps)))
        or InstallReport(installed=list(deps), skipped=[]),
    )
    monkeypatch.setattr(
        pip_runner, "uninstall_python_deps",
        lambda names: calls.append(("uninstall", list(names)))
        or UninstallReport(removed=list(names), kept=[]),
    )
    return calls


@pytest.fixture
def installs_off(monkeypatch):
    monkeypatch.setattr(config, "CURIO_ALLOW_RUNTIME_INSTALL", False, raising=False)


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)


@pytest.fixture
def auth_off(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)


def _user_key(user):
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


class TestOperatorSwitch:
    def test_install_is_refused_and_names_the_flag(
        self, client, user_and_token, installs_off, pip_calls,
    ):
        _, token = user_and_token
        resp = client.post("/api/packages/libraries",
                           json={"kind": "python", "spec": "humanize"},
                           headers=_auth(token))

        assert resp.status_code == 403
        body = resp.get_json()
        assert body["code"] == "library_install_disabled"
        assert "--allow-runtime-install" in body["error"]
        assert pip_calls == []
        listed = client.get("/api/packages/libraries", headers=_auth(token)).get_json()
        assert listed["standalone"]["python"] == []

    def test_remove_is_refused_too(
        self, client, user_and_token, installs_off, pip_calls,
    ):
        user, token = user_and_token
        libs.add_library(_user_key(user), "python", "humanize")

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(token))

        assert resp.status_code == 403
        assert pip_calls == []
        assert libs.list_standalone(_user_key(user))["python"] == ["humanize"]

    def test_the_list_says_installs_are_off_and_why(
        self, client, user_and_token, installs_off,
    ):
        _, token = user_and_token
        body = client.get("/api/packages/libraries", headers=_auth(token)).get_json()

        assert body["installAllowed"] is False
        assert "--allow-runtime-install" in body["installDisabledReason"]

    def test_the_list_says_installs_are_on(self, client, user_and_token):
        _, token = user_and_token
        body = client.get("/api/packages/libraries", headers=_auth(token)).get_json()

        assert body["installAllowed"] is True
        assert body["installDisabledReason"] is None


class TestGuest:
    def test_a_guest_cannot_install_on_an_instance_with_accounts(
        self, client, shared_guest_token, auth_on, pip_calls,
    ):
        resp = client.post("/api/packages/libraries",
                           json={"kind": "python", "spec": "humanize"},
                           headers=_auth(shared_guest_token))

        assert resp.status_code == 403
        assert "guest" in resp.get_json()["error"].lower()
        assert pip_calls == []

    def test_a_guest_cannot_uninstall_either(
        self, client, shared_guest_token, auth_on, pip_calls,
    ):
        libs.add_library("guest", "python", "humanize")

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(shared_guest_token))

        assert resp.status_code == 403
        assert pip_calls == []

    def test_a_local_launch_without_auth_still_installs(
        self, client, shared_guest_token, auth_off, pip_calls,
    ):
        # With auth off, the one local user IS the shared guest.
        resp = client.post("/api/packages/libraries",
                           json={"kind": "python", "spec": "humanize"},
                           headers=_auth(shared_guest_token))

        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert pip_calls == [("install", ["humanize"])]


class TestSharedInterpreter:
    def test_remove_keeps_a_library_another_user_still_lists(
        self, client, db, user_and_token, pip_calls,
    ):
        alice, alice_token = user_and_token
        bob = _make_user(db, "bob", "bob-token")
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth(alice_token))
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth("bob-token"))
        pip_calls.clear()

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(alice_token))

        assert resp.status_code == 200
        assert resp.get_json()["standalone"]["python"] == []
        assert pip_calls == [], "bob still lists humanize - it must stay installed"
        assert libs.list_standalone(_user_key(bob))["python"] == ["humanize"]

    def test_remove_still_uninstalls_when_nobody_else_lists_it(
        self, client, db, user_and_token, pip_calls,
    ):
        _, alice_token = user_and_token
        _make_user(db, "bob", "bob-token")
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth(alice_token))
        pip_calls.clear()

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(alice_token))

        assert resp.status_code == 200
        assert pip_calls == [("uninstall", ["humanize"])]

    def test_remove_with_an_invalid_name_is_a_bad_request(
        self, client, user_and_token, pip_calls,
    ):
        _, token = user_and_token
        resp = client.delete("/api/packages/libraries/python/not%20a%20name",
                             headers=_auth(token))

        assert resp.status_code == 400
        assert pip_calls == []
