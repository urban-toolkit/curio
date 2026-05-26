"""Playwright E2E: signup -> /projects -> signout -> signin."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .utils import auth_enabled_env, signup_e2e_user

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

    page.get_by_role("heading", name="Projects").wait_for(timeout=10000)

    # 4. Sign out — use the stable data-testid (UserMenu mounts the sign-out
    # button asynchronously after the auth context resolves; Playwright's
    # auto-wait on test_id locators handles the race more cleanly than a
    # bare get_by_text(...).click() which timed out under load).
    page.get_by_test_id("signout-button").click()
    page.wait_for_url("**/auth/signin", timeout=15000)

    # 5. Sign back in by username
    page.get_by_label("Username or Email").fill("e2etestuser")
    page.get_by_label("Password").fill("testpass123")
    page.get_by_role("button", name="Sign In", exact=True).click()
    page.wait_for_url("**/projects", timeout=30000)
    page.get_by_text("Projects", exact=True).wait_for(timeout=10000)
