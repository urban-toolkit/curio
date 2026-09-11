"""Playwright E2E: verify project ownership isolation."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    project_card,
    require_project_page,
    signup_and_enter_new_workflow,
    signup_e2e_user,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_project_not_visible_to_other_user(app_frontend: "FrontendPage", page):
    """User A saves a project; User B should not see it on their projects page."""
    require_project_page()
    base = app_frontend.base_url

    signup_and_enter_new_workflow(
        page, base, name="Owner A", username="ownera",
    )

    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    page.get_by_role("button", name="Save dataflow", exact=True).click()
    page.wait_for_timeout(2000)

    # Positive control first: the save landed on A's own list, so the absence
    # asserted below for B is about ownership and not about a save that never
    # happened. ``FlowProvider`` seeds the name to "DefaultDataflow".
    page.goto(f"{base}/projects")
    wait_for_projects_page(page, timeout=15000)
    expect(project_card(page, "DefaultDataflow")).to_have_count(1, timeout=20000)

    page.get_by_test_id("signout-button").click()
    page.wait_for_url("**/auth/signin", timeout=15000)

    signup_e2e_user(page, base, name="Owner B", username="ownerb")
    wait_for_projects_page(page, timeout=10000)

    # Not "No projects yet": a registered account is seeded its own copies of
    # the examples at sign-up when the stack runs --with-examples (#200), so B's
    # list is legitimately non-empty there, and the message only shows for the
    # instant before the list request returns. The old ``is_visible()`` check
    # passed or failed on that race. Wait for the list to settle - cards, or
    # the empty state on a stack without examples - then assert the one thing
    # this test is about: A's project is not among what B sees.
    settled = page.locator(
        '[data-curio-projects-scroll="true"] [data-project-id]'
    ).or_(page.get_by_text("No projects yet")).first
    expect(settled).to_be_visible(timeout=20000)
    expect(project_card(page, "DefaultDataflow")).to_have_count(0)
