"""Playwright E2E: verify project ownership isolation."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .utils import (
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

    page.get_by_test_id("signout-button").click()
    page.wait_for_url("**/auth/signin", timeout=15000)

    signup_e2e_user(page, base, name="Owner B", username="ownerb")

    wait_for_projects_page(page, timeout=10000)
    empty_msg = page.get_by_text("No projects yet")
    assert empty_msg.is_visible()
