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
    """One interpreter for everybody: --deploy on a host that cannot isolate.

    Also clears the operator opt-out. The suite-wide conftest declares
    ``CURIO_ALLOW_SHARED_INSTALLS=1`` so the ~900 tests about install mechanics
    are not all gate tests; the gate's own suite has to state each posture
    itself rather than inherit that one.
    """
    monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: False)
    monkeypatch.setattr(config, "CURIO_ALLOW_SHARED_INSTALLS", False)


@pytest.fixture
def unscoped_but_permitted(monkeypatch):
    """Unscoped, with the operator having accepted that (--allow-shared-installs)."""
    monkeypatch.setattr(backend_runtime, "per_user_node_envs", lambda: False)
    monkeypatch.setattr(config, "CURIO_ALLOW_SHARED_INSTALLS", True)


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

    def test_nobody_may_when_installs_are_not_scoped(self, db, auth_on, unscoped):
        # #309's residual: a signed-in account on a --deploy instance that
        # could not isolate still wrote into the shared interpreter.
        user = _make_user(db, "carol", "t5")
        refusal = package_install_refusal(user)
        assert refusal and "scope" in refusal.lower()


class TestTheOperatorOptOut:
    """``--allow-shared-installs``.

    Rule 3 is far broader than "a misconfigured deployment": isolation needs
    Linux, fork, setrlimit, pyseccomp AND a configured execution user, so
    ``--deploy`` on macOS or Windows, on Linux without pyseccomp, or on Linux
    with no exec user all land in "cannot scope". Refusing every one of them
    would take package installation away from deployments whose operator knows
    every account. The flag is off by default, so the safe posture is the one
    you get without knowing the flag exists.
    """

    def test_an_operator_can_accept_shared_installs(
        self, db, auth_on, unscoped_but_permitted,
    ):
        user = _make_user(db, "frank", "t6")
        assert package_install_refusal(user) is None

    def test_it_does_not_let_a_guest_back_in(self, db, auth_on, unscoped_but_permitted):
        # The flag is about SCOPING, not about identity. Every guest is still
        # the same account, and that is a different objection.
        guest = _make_user(db, config.CURIO_SHARED_GUEST_USERNAME, "t7", is_guest=True)
        refusal = package_install_refusal(guest)
        assert refusal and "guest" in refusal.lower()


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

    def test_workflow_deps_install_is_refused_when_unscoped(
        self, client, db, auth_on, unscoped, pip_calls,
    ):
        _make_user(db, "dave", "dave-token")
        resp = client.post(
            "/api/packages/workflow-deps/install",
            json={"packages": ["curio.builtin@1"]},
            headers=_auth("dave-token"),
        )
        assert resp.status_code == 403, resp.get_data(as_text=True)
        assert "scope" in resp.get_json()["error"].lower()
        assert pip_calls == []

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
    def test_the_libraries_listing_reports_the_unscoped_refusal(
        self, client, db, auth_on, unscoped,
    ):
        # The drawer hides the affordance from what this returns, so a refusal
        # the listing does not mention is a button that fails when clicked.
        _make_user(db, "erin", "erin-token")
        body = client.get(
            "/api/packages/libraries", headers=_auth("erin-token"),
        ).get_json()
        assert body["installAllowed"] is False
        assert "scope" in body["installDisabledReason"].lower()
