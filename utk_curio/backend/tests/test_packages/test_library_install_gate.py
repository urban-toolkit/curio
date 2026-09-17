"""Who may install or uninstall a node library, and what Remove uninstalls (#309).

The shared guest is every anonymous visitor at once, so it never installs on an
instance with accounts. A local launch without auth signs in AS the shared
guest, so that case must keep working - it is the everyday single-user path.

Remove is ref-counted. Where one interpreter serves everyone, another user's
list is a reason to keep a library; under per-user node environments it is not,
because it describes another user's tree.
"""
from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.packages import libraries as libs
from utk_curio.backend.app.packages import pip_runner
from utk_curio.backend.app.packages import services as packages_services
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
def auth_on(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)


@pytest.fixture
def auth_off(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)


def _user_key(user):
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


class TestTheListReportsWhetherInstallsAreAllowed:
    def test_it_says_allowed_for_an_account(self, client, user_and_token):
        _, token = user_and_token
        body = client.get("/api/packages/libraries", headers=_auth(token)).get_json()

        assert body["installAllowed"] is True
        assert body["installDisabledReason"] is None

    def test_it_says_refused_and_why_for_a_guest(
        self, client, shared_guest_token, auth_on,
    ):
        body = client.get(
            "/api/packages/libraries", headers=_auth(shared_guest_token),
        ).get_json()

        assert body["installAllowed"] is False
        assert "guest" in body["installDisabledReason"].lower()


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


class TestPerUserTreesChangeWhatRefCountingMeans:
    """``listed_by_others`` keeps a library because every user's list is
    bookkeeping over ONE interpreter. Per-user node environments abolish that
    premise: another user's list then describes another user's directory, so
    asking would refuse to remove a library from yours because someone else
    installed it into theirs."""

    def test_another_users_list_no_longer_blocks_a_removal(
        self, client, db, user_and_token, pip_calls, monkeypatch,
    ):
        from utk_curio.backend.app.packages import backend_runtime

        _, alice_token = user_and_token
        _make_user(db, "bob", "bob-token")
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth(alice_token))
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth("bob-token"))
        pip_calls.clear()
        monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: True)
        # Record at the service boundary: under per-user trees the removal goes
        # to the target uninstaller, never to the shared interpreter, so the
        # question is whether the route got past the ref-count gate at all.
        removed = []
        monkeypatch.setattr(
            packages_services, "uninstall_user_library",
            lambda user_key, name: removed.append((user_key, name)),
        )

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(alice_token))

        assert resp.status_code == 200
        assert [name for _, name in removed] == ["humanize"], (
            "alice's tree is hers; bob listing humanize says nothing about it"
        )
        assert pip_calls == [], "the shared interpreter is not involved"

    def test_it_is_not_even_consulted(
        self, client, user_and_token, pip_calls, monkeypatch,
    ):
        from utk_curio.backend.app.packages import backend_runtime

        _, token = user_and_token
        client.post("/api/packages/libraries",
                    json={"kind": "python", "spec": "humanize"},
                    headers=_auth(token))
        monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: True)

        def _boom(*a, **kw):
            raise AssertionError("listed_by_others asked under per-user trees")

        monkeypatch.setattr(libs, "listed_by_others", _boom)

        resp = client.delete("/api/packages/libraries/python/humanize",
                             headers=_auth(token))

        assert resp.status_code == 200
