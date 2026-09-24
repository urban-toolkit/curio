"""Who may trigger a pip run, on which instances (#332, #309).

``/api/packages/libraries`` has been gated since #309: the shared guest is every
anonymous visitor at once, so on an instance with accounts it never installs.
Eight other routes reach the same pip chokepoint carrying only ``@require_auth``:
package upload, catalog install, factory install, workflow-deps install, the
per-project and defaults installs, and the agent proposal-apply path. Each of
them could put a library into the interpreter that runs everybody's node code.

The rule this pins has three parts, and the FIRST one is the one a naive
"refuse when installs are not scoped" rule gets wrong:

1. **A local run always may.** Without ``--deploy`` there is no auth, the single
   local user is signed in as the guest, and there is no isolation. Nothing is
   scoped because there is nothing to scope it from: one person, one
   interpreter, their own machine. Installing and removing libraries there is
   the everyday path and must keep working.
2. **A hosted guest may not.** Every anonymous visitor is the same account, so
   one visitor's install changes what every other visitor's nodes import.
3. **Nobody may on a hosted instance that cannot scope installs.** This is the
   half #309 was left open for: under ``--deploy`` on a host that cannot isolate
   (non-root Linux, macOS, Windows, which boot with a warning rather than a
   refusal), a *signed-in* user's install still lands in the one shared
   interpreter.
"""
from __future__ import annotations

import pytest

from utk_curio.backend import config
from utk_curio.backend.app.packages import backend_runtime
from utk_curio.backend.app.users.capabilities import package_install_refusal


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
    _make_user(db, config.CURIO_SHARED_GUEST_USERNAME, "guest-token", is_guest=True)
    return "guest-token"


@pytest.fixture
def pip_calls(monkeypatch):
    """Every pip run the routes ask for. Empty means the gate fired first."""
    from utk_curio.backend.app.packages import pip_runner
    from utk_curio.backend.app.packages.pip_runner import InstallReport

    calls: list = []
    monkeypatch.setattr(
        pip_runner, "install_python_deps",
        lambda deps: calls.append(("install", list(deps)))
        or InstallReport(installed=list(deps), skipped=[]),
    )
    monkeypatch.setattr(
        pip_runner, "install_python_deps_to_target",
        lambda deps, target, **kw: calls.append(("install_target", list(deps)))
        or InstallReport(installed=list(deps), skipped=[]),
    )
    return calls


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", False)


@pytest.fixture
def auth_off(monkeypatch):
    monkeypatch.setattr(config, "CURIO_NO_AUTH", True)


@pytest.fixture
def scoped(monkeypatch):
    """The instance gives each user their own node libraries."""
    monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: True)


@pytest.fixture
def unscoped(monkeypatch):
    """One interpreter for everybody.

    Reachable only by a test rig now: ``--deploy`` on a host that cannot
    isolate refuses to start unless ``CURIO_TESTING`` is set
    (``main.py::_refuse_unisolated_deploy``). Kept as a posture here because
    the rules below must still hold on the rigs that do run it.
    """
    monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: False)


class TestALocalRunIsNeverRefused:
    """The case the rule must not break. No --deploy means no auth and no
    isolation, and the user is signed in as the guest: all three of the
    conditions that refuse a hosted caller are true at once, locally, for the
    everyday single-user path."""

    def test_the_local_guest_may_install(self, db, auth_off, unscoped):
        guest = _make_user(db, config.CURIO_SHARED_GUEST_USERNAME, "t1", is_guest=True)
        assert package_install_refusal(guest) is None

    def test_a_local_signed_in_user_may_install(self, db, auth_off, unscoped):
        user = _make_user(db, "alice", "t2")
        assert package_install_refusal(user) is None


class TestAHostedInstance:
    def test_a_guest_may_not(self, db, auth_on, scoped):
        guest = _make_user(db, config.CURIO_SHARED_GUEST_USERNAME, "t3", is_guest=True)
        refusal = package_install_refusal(guest)
        assert refusal and "guest" in refusal.lower()

    def test_a_signed_in_user_may_when_installs_are_scoped(self, db, auth_on, scoped):
        user = _make_user(db, "bob", "t4")
        assert package_install_refusal(user) is None

    def test_a_signed_in_user_may_even_where_installs_are_not_scoped(
        self, db, auth_on, unscoped,
    ):
        """The rule that used to live here went with the mode it guarded.

        A hosted instance that cannot scope installs no longer boots: --deploy
        requires isolated execution and refuses without it. What remains in
        this posture is a test rig, which is one machine with users it created
        itself, so refusing its installs only broke its own suites.
        """
        user = _make_user(db, "carol", "t5")
        assert package_install_refusal(user) is None


class TestTheSystemCaller:
    def test_none_is_allowed(self, auth_on, unscoped):
        # The launcher installs every manifest's deps at boot with no request
        # and no user. Refusing that would refuse startup.
        assert package_install_refusal(None) is None


class TestTheRoutesEnforceIt:
    def test_workflow_deps_install_is_refused_for_a_hosted_guest(
        self, client, shared_guest_token, auth_on, scoped, pip_calls,
    ):
        resp = client.post(
            "/api/packages/workflow-deps/install",
            json={"packages": ["curio.builtin@1"]},
            headers=_auth(shared_guest_token),
        )
        assert resp.status_code == 403, resp.get_data(as_text=True)
        assert "guest" in resp.get_json()["error"].lower()
        assert pip_calls == []

    def test_workflow_deps_install_runs_when_unscoped(
        self, client, db, auth_on, unscoped, pip_calls,
    ):
        """The route no longer refuses a signed-in user for the shape alone.

        The shape is unreachable outside a test rig now: --deploy without
        isolation refuses to start. Driven through the route rather than the
        predicate, because the refusal used to be applied here too.
        """
        _make_user(db, "dave", "dave-token")
        resp = client.post(
            "/api/packages/workflow-deps/install",
            json={"packages": ["curio.builtin@1"]},
            headers=_auth("dave-token"),
        )
        assert resp.status_code != 403, resp.get_data(as_text=True)

    def test_a_local_run_still_installs_through_the_same_route(
        self, client, shared_guest_token, auth_off, unscoped, pip_calls,
    ):
        # The control for rule 1, driven through the route rather than the
        # predicate: the everyday local path must not be collateral damage.
        resp = client.post(
            "/api/packages/workflow-deps/install",
            json={"packages": ["curio.builtin@1"]},
            headers=_auth(shared_guest_token),
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)


class TestTheUIIsToldWhy:
    def test_the_libraries_listing_offers_the_install_when_unscoped(
        self, client, db, auth_on, unscoped,
    ):
        # The drawer takes the affordance from what this returns, so a refusal
        # that no longer applies must not still disable the button.
        _make_user(db, "erin", "erin-token")
        body = client.get(
            "/api/packages/libraries", headers=_auth("erin-token"),
        ).get_json()
        assert body["installAllowed"] is True
        assert not body.get("installDisabledReason")

    def test_the_libraries_listing_still_reports_the_guest_refusal(
        self, client, shared_guest_token, auth_on, scoped,
    ):
        # The rule that remains: a hosted guest is one shared account.
        body = client.get(
            "/api/packages/libraries", headers=_auth(shared_guest_token),
        ).get_json()
        assert body["installAllowed"] is False
        assert "guest" in body["installDisabledReason"].lower()
