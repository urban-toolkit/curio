"""Playwright E2E: dataflow share links.

A user creates a project; a second browser context opens the canonical
``/dataflow/<id>`` URL and lands on a read-only canvas with a "Save a copy"
entry that clones the dataflow into the visitor's workspace.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from .utils import (
    allow_guest_login_env,
    auth_enabled_env,
    require_project_page,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def _shared_demo_spec() -> dict:
    """Minimal but renderable dataflow spec used as the source of the share."""
    return {
        "name": "Shared Demo",
        "dataflow": {
            "name": "Shared Demo",
            "nodes": [
                {
                    "id": "node-1",
                    "type": "DATA_LOADING",
                    "x": 0,
                    "y": 0,
                    "content": "",
                    "metadata": {},
                    "out": {"type": "string"},
                }
            ],
            "edges": [],
        },
    }


def test_share_link_opens_read_only(
    app_frontend: "FrontendPage",
    current_server: str,
    browser,
):
    """Visiting another user's /dataflow/<id> URL renders a read-only canvas.

    The "Save dataflow" fork path is intentionally not exercised here: the e2e
    harness boots the backend with ``--auth`` (``CURIO_NO_AUTH=0``), which
    means ``blockGuestSaves=true`` for the auto-signed-in shared guest. The
    fork only works in deploy mode (``CURIO_NO_AUTH=1``); see
    ``test_share_link_save_fork`` below.
    """
    require_project_page()
    if auth_enabled_env() and not allow_guest_login_env():
        pytest.skip("Share-link auto-guest requires ALLOW_GUEST_LOGIN")

    base = app_frontend.base_url
    owner_ctx = browser.new_context()
    visitor_ctx = browser.new_context()
    try:
        owner_page = owner_ctx.new_page()
        visitor_page = visitor_ctx.new_page()

        # Owner: stub-login + stub-project. We don't need the owner's browser
        # for the assertion — we just need a project row to share.
        result = stub_db_login(
            owner_page,
            frontend_url=base,
            backend_url=current_server,
            username="share_owner",
            name="Share Owner",
            project_name="Shared Demo",
            project_spec=_shared_demo_spec(),
        )
        project_id = result["project"]["id"]

        # Visitor: open the share URL with no cookie. They should be auto-
        # signed-in as the shared guest by the UserProvider bootstrap, and
        # ProjectLoader should fall back from /api/projects/<id> (404 — not
        # the visitor's project) to /api/projects/<id>/shared.
        visitor_page.goto(f"{base}/dataflow/{project_id}")
        visitor_page.wait_for_load_state("domcontentloaded")

        banner = visitor_page.get_by_test_id("shared-view-banner")
        banner.wait_for(timeout=30000)
        assert "read-only" in (banner.inner_text() or "").lower()

        # Canvas rendered the owner's node.
        visitor_page.wait_for_function(
            "document.querySelectorAll('.react-flow__node').length >= 1",
            timeout=15000,
        )
    finally:
        owner_ctx.close()
        visitor_ctx.close()


def test_share_link_save_fork(
    app_frontend: "FrontendPage",
    current_server: str,
    browser,
):
    """Clicking 'Save dataflow' on a shared link creates a copy in the
    visitor's workspace.

    Only runs in deploy mode (``CURIO_NO_AUTH=1``) where the shared guest is
    allowed to save. In auth-enabled mode the click toasts an error instead,
    which is the intended behavior — covered by leaving the assertion to the
    deploy-mode run.
    """
    require_project_page()
    if auth_enabled_env():
        pytest.skip("Save-fork from a share link requires CURIO_NO_AUTH=1")

    base = app_frontend.base_url
    owner_ctx = browser.new_context()
    visitor_ctx = browser.new_context()
    try:
        owner_page = owner_ctx.new_page()
        visitor_page = visitor_ctx.new_page()

        result = stub_db_login(
            owner_page,
            frontend_url=base,
            backend_url=current_server,
            username="share_owner_fork",
            name="Share Owner Fork",
            project_name="Shared Demo Fork",
            project_spec=_shared_demo_spec(),
        )
        project_id = result["project"]["id"]

        visitor_page.goto(f"{base}/dataflow/{project_id}")
        visitor_page.wait_for_load_state("domcontentloaded")
        visitor_page.get_by_test_id("shared-view-banner").wait_for(timeout=30000)
        visitor_page.wait_for_function(
            "document.querySelectorAll('.react-flow__node').length >= 1",
            timeout=15000,
        )

        file_btn = visitor_page.get_by_role("button", name=re.compile("File"))
        file_btn.wait_for(state="visible", timeout=15000)
        file_btn.click(force=True)
        visitor_page.get_by_role(
            "button", name="Save dataflow", exact=True,
        ).click()

        visitor_page.wait_for_url(
            re.compile(
                r".*/dataflow/(?!" + re.escape(project_id) + r"$)"
                r"[0-9a-f-]{36}$"
            ),
            timeout=20000,
        )
        assert visitor_page.get_by_test_id("shared-view-banner").count() == 0
    finally:
        owner_ctx.close()
        visitor_ctx.close()
