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


def test_share_link_opens_read_only_and_save_copy_flow(
    app_frontend: "FrontendPage",
    current_server: str,
    browser,
):
    """Visiting another user's /dataflow/<id> URL renders a read-only canvas;
    clicking 'Save a copy' creates a new project owned by the visitor."""
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

        # Save the dataflow into the visitor's workspace via File menu.
        # In shared mode the entry is labelled "Save dataflow" but its handler
        # uses saveAsNewProject under the hood, so the resulting URL is a new id.
        file_btn = visitor_page.get_by_role("button", name=re.compile("File"))
        file_btn.wait_for(state="visible", timeout=15000)
        file_btn.click(force=True)
        visitor_page.get_by_role("button", name="Save dataflow", exact=True).click()

        # Navigation lands on the new copy, which is a *different* project id.
        visitor_page.wait_for_url(
            re.compile(r".*/dataflow/(?!" + re.escape(project_id) + r"$)[0-9a-f-]{36}$"),
            timeout=20000,
        )
        # Banner is gone on the visitor's own copy (viewerMode = owner).
        assert visitor_page.get_by_test_id("shared-view-banner").count() == 0
    finally:
        owner_ctx.close()
        visitor_ctx.close()
