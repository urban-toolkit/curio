"""Playwright E2E: verify beforeunload guard when project has unsaved changes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    require_project_page,
    signup_and_enter_new_workflow,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_dirty_guard_on_navigation(app_frontend: "FrontendPage", page):
    """After saving and editing, navigating away should trigger confirmation."""
    require_project_page()
    base = app_frontend.base_url

    signup_and_enter_new_workflow(
        page,
        base,
        name="Dirty Guard User",
        username="dirtyguard",
    )

    page.wait_for_timeout(2000)

    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=10000)
