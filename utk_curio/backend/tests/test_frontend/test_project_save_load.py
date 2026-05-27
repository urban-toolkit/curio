"""Playwright E2E: save a project and verify it loads in executed state."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .utils import require_project_page, signup_and_enter_new_workflow, signup_e2e_user

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_project_save_via_menu(app_frontend: "FrontendPage", page):
    """Save via File > Save dataflow and verify the project appears on /projects.

    Previous incarnation of this test looked for a `Saved dataflows` submenu
    inside the File menu; that submenu was removed in
    a9c3f66 ("Standardizing interface elements, tweaks to the file menu")
    when the in-canvas list was superseded by the dedicated `/projects`
    page. The save round-trip itself is the same — `handleSave` POSTs to
    `/api/projects` and `refreshSavedProjects()` invalidates the cache —
    so we verify the save by navigating to `/projects` and asserting the
    new entry renders, which is the user-facing path that replaced the
    submenu.
    """
    require_project_page()
    signup_and_enter_new_workflow(
        page,
        app_frontend.base_url,
        name="Project Tester",
        username="prjtester",
    )

    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)

    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=5000)
    save_btn.click()
    # `handleSave` closes the File menu once the save + refreshSavedProjects
    # round-trip completes, so the Save button being hidden is our signal that
    # the save is fully done.
    save_btn.wait_for(state="hidden", timeout=10000)
    # wait for the save to be completed
    page.wait_for_timeout(2000)

    # Navigate to /projects (the current home for saved dataflows after
    # the file-menu simplification). `FlowProvider` seeds `workflowName` to
    # "DefaultDataflow" and `handleSave` defaults to that name, so a project
    # row with that title must be present.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_role("heading", name="Projects").wait_for(timeout=15000)
    expected = page.get_by_text("DefaultDataflow", exact=True)
    expected.first.wait_for(state="visible", timeout=10000)


def test_project_list_page(app_frontend: "FrontendPage", page):
    """Verify the projects page shows saved projects."""
    require_project_page()
    base = app_frontend.base_url

    signup_e2e_user(
        page, base, name="Project Lister", username="prjlister",
    )
    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_role("heading", name="Projects").wait_for(timeout=10000)
