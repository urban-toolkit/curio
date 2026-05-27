"""Playwright E2E: guest project cleanup (simulated 24h TTL)."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .utils import allow_guest_login_env, auth_enabled_env, require_project_page

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_guest_save_is_blocked(app_frontend: FrontendPage, page):
    """A guest who hit 'Continue as Guest' must NOT be able to save a dataflow.

    Codifies the policy introduced by commit 8ed8cd6 ('On deployment, blocks
    non-shared guest users from saving dataflows'). Two layers enforce it:

    1. Backend: ``app/projects/services.py::_assert_guest_can_save`` raises
       ``ProjectError(..., 403)`` for any guest user that is NOT the
       shared-guest singleton.
    2. Frontend (client-side guard, the layer actually exercised here):
       ``hook/useWorkflowOperations.ts`` sets
       ``blockGuestSaves = enableUserAuth && !!user?.is_guest`` and
       ``saveCurrentProject`` throws before issuing the POST, so the click
       on 'Save dataflow' fires a toast and **no** ``POST /api/projects``
       leaves the browser.

    The previous incarnation of this test (``test_guest_can_save_project``)
    asserted the opposite — that the save succeeded with status 201. After
    8ed8cd6 it just timed out waiting for a POST that would never happen.
    Now we wait briefly, then assert that no save request was issued.
    """
    require_project_page()
    base = app_frontend.base_url
    auth_enabled = auth_enabled_env()
    allow_guest = allow_guest_login_env()

    page.goto(f"{base}/auth/signin" if auth_enabled else f"{base}/")
    page.wait_for_load_state("domcontentloaded")

    if auth_enabled:
        if not allow_guest:
            pytest.skip("Explicit guest login is disabled for this session")
        guest_btn = page.get_by_text("Continue as Guest")
        guest_btn.wait_for(timeout=10000)
        guest_btn.click()

    page.wait_for_url("**/projects", timeout=30000)
    page.get_by_role("heading", name="Projects").wait_for(timeout=10000)

    page.get_by_text("+ New Dataflow").click()
    page.wait_for_url("**/dataflow/**", timeout=15000)
    page.wait_for_load_state("domcontentloaded")

    # Wait on the File button explicitly instead of a fixed sleep — the
    # canvas-mount completion is what we actually depend on. Once the
    # button is visible, the FlowProvider + UpMenu are mounted and
    # `saveCurrentProject` is wired through the React tree.
    file_btn = page.get_by_test_id("file-menu-btn")
    file_btn.wait_for(state="visible", timeout=15000)

    # Assert the block by *expecting no request* — `expect_request` with
    # the inverse semantics. `saveCurrentProject` throws synchronously
    # inside the click handler before any `fetch` runs, so a real block
    # produces no POST and we hit the timeout; an unintended save flow
    # fires the matching request and the with-block resolves early.
    try:
        with page.expect_request(
            lambda r: r.method == "POST" and "/api/projects" in r.url,
            timeout=2000,
        ) as captured:
            file_btn.click(force=True)
            page.get_by_role("button", name="Save dataflow", exact=True).click()
    except PlaywrightTimeoutError:
        return  # expected: no POST fired within the budget → block works.
    # If we get here, the request fired — the guard was bypassed.
    pytest.fail(
        f"Expected the client-side guest-save guard to suppress the request, "
        f"but a POST landed: {captured.value.url}"
    )
