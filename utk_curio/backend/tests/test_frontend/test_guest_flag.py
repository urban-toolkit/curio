"""Playwright E2E: guest visibility respects auth + guest flags."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    allow_guest_login_env,
    auth_enabled_env,
    skip_project_page_env,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_guest_button_visible_in_dev(app_frontend: FrontendPage, page):
    """Guest visibility follows CURIO_NO_AUTH + ALLOW_GUEST_LOGIN."""
    base = app_frontend.base_url

    auth_enabled = auth_enabled_env()
    allow_guest = allow_guest_login_env()
    skip_projects = skip_project_page_env()

    page.goto(f"{base}/auth/signin")
    page.wait_for_load_state("domcontentloaded")
    if not auth_enabled:
        # When auth is disabled the signin page redirects to the entry route.
        # In ``--no-project`` mode the entry route is ``/dataflow``; otherwise
        # it's the projects list.
        if skip_projects:
            page.wait_for_url("**/dataflow**", timeout=30000)
        else:
            page.wait_for_url("**/projects", timeout=30000)
            wait_for_projects_page(page, timeout=10000)
        return

    page.get_by_role("button", name="Sign in", exact=True).wait_for(timeout=30000)

    guest = page.get_by_text("Continue as Guest")
    if allow_guest:
        guest.wait_for(timeout=10000)
        assert guest.is_visible()
    else:
        assert not guest.is_visible()
