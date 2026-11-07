"""Playwright E2E: signup -> /projects -> signout -> signin, and a session
that only a 401 ends."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    SESSION_COOKIE_NAME,
    auth_enabled_env,
    require_project_page,
    signup_e2e_user,
    stub_db_login,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_signup_signin_flow(app_frontend: FrontendPage, page):
    """Full auth round-trip: signup, reach projects, sign out, sign back in."""
    if not auth_enabled_env():
        pytest.skip("Signup/signin flow is disabled when CURIO_NO_AUTH=1")

    base = app_frontend.base_url

    signup_e2e_user(
        page,
        base,
        name="E2E Test User",
        username="e2etestuser",
        password="testpass123",
    )

    wait_for_projects_page(page, timeout=10000)

    # 4. Sign out — use the stable data-testid (GlobalPageHeader mounts the
    # sign-out button only once the auth context resolves; Playwright's
    # auto-wait on test_id locators handles the race more cleanly than a
    # bare get_by_text(...).click() which timed out under load).
    page.get_by_test_id("signout-button").click()
    page.wait_for_url("**/auth/signin", timeout=15000)

    # 5. Sign back in by username
    page.get_by_label("Username or Email").fill("e2etestuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.wait_for_url("**/projects", timeout=30000)
    wait_for_projects_page(page, timeout=10000)


# ---------------------------------------------------------------------------
# A failed session check is not a sign-out
# ---------------------------------------------------------------------------
#
# Every page load asks /api/auth/me. The server answers a dead session with 401
# and nothing else; a check the browser aborted because the page navigated
# away, or one that met a server error, says nothing about the session, so the
# load asks again after each of ASK_AGAIN_WAITS_MS (utils/askAgain.ts, 7.5 s
# in all) before it shows the sign-in page. The routes below fail every check
# of one load on purpose, so that load shows the sign-in page either way: what
# is under test is the NEXT load.
#
# Except the last test: there only the load's first check fails, as when the
# machine's network changes under it, and the load itself opens signed in.

#: The sign-in page of a load whose every check fails comes after its checks
#: and the 7.5 s of waits between them.
FAILED_CHECKS_TIMEOUT_MS = 30000


@pytest.fixture()
def signed_in(app_frontend: "FrontendPage", current_server: str, page, request):
    if not auth_enabled_env():
        pytest.skip("There is no session to keep when CURIO_NO_AUTH=1")
    require_project_page()
    login = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Session Keeper",
        username=f"session_{abs(hash(request.node.name)) % 10**8}",
        project_name="Kept",
    )
    page.goto(f"{app_frontend.base_url}/projects")
    wait_for_projects_page(page, timeout=15000)
    return SimpleNamespace(page=page, base=app_frontend.base_url, token=login["token"])


def _session_cookie(page):
    return next(
        (c["value"] for c in page.context.cookies() if c["name"] == SESSION_COOKIE_NAME),
        None,
    )


def _reload_with_failing_session_check(page, fail) -> None:
    page.route("**/api/auth/me", fail)
    page.reload()
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible(
        timeout=FAILED_CHECKS_TIMEOUT_MS)
    page.unroute("**/api/auth/me", fail)


@pytest.mark.parametrize("failure", ["aborted", "server-error"])
def test_a_failed_session_check_keeps_the_session(signed_in, failure):
    page = signed_in.page

    def _fail(route):
        if failure == "aborted":
            route.abort("aborted")
        else:
            route.fulfill(status=503, content_type="application/json",
                          body='{"error": "unavailable"}')

    _reload_with_failing_session_check(page, _fail)
    assert _session_cookie(page) == signed_in.token, "the failed check deleted the session cookie"

    page.goto(f"{signed_in.base}/projects")
    wait_for_projects_page(page, timeout=15000)
    expect(page.get_by_test_id("signout-button")).to_be_visible(timeout=15000)


def test_a_refused_session_check_signs_out(signed_in):
    page = signed_in.page

    def _refuse(route):
        route.fulfill(status=401, content_type="application/json",
                      body='{"error": "Authorization required."}')

    _reload_with_failing_session_check(page, _refuse)
    assert _session_cookie(page) is None

    page.goto(f"{signed_in.base}/projects")
    expect(page.get_by_role("button", name="Sign in", exact=True)).to_be_visible(timeout=15000)


def test_a_session_check_the_browser_dropped_is_asked_again(signed_in):
    """A load whose first session check the browser drops still opens signed in.

    Chromium fails every request in flight when the machine's network changes
    (net::ERR_NETWORK_CHANGED). On a CI runner that once hit a page's only
    check, and a signed-in owner's dataflow opened on the sign-in page. Here
    the load's first check fails the same way and the next one goes through.
    """
    page = signed_in.page
    checks = []

    def _drop_the_first(route):
        if route.request.method == "GET":
            checks.append(route.request.url)
            if len(checks) == 1:
                route.abort("internetdisconnected")
                return
        route.continue_()

    page.route("**/api/auth/me", _drop_the_first)
    page.reload()
    wait_for_projects_page(page, timeout=15000)
    expect(page.get_by_test_id("signout-button")).to_be_visible(timeout=15000)
    page.unroute("**/api/auth/me", _drop_the_first)
    assert len(checks) >= 2, f"the page checked its session {len(checks)} time(s): it never asked again"
    assert _session_cookie(page) == signed_in.token, "the dropped check deleted the session cookie"
