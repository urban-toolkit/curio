"""Playwright E2E: the shared guest workspace is visible across sessions."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from .utils import (
    allow_guest_login_env,
    auth_enabled_env,
    require_project_page,
    wait_for_projects_page,
)


def _auth_enabled() -> bool:
    return auth_enabled_env()


def _allow_guest_login() -> bool:
    return allow_guest_login_env()


def _enter_guest_workspace(page, base_url: str) -> None:
    page.goto(f"{base_url}/auth/signin" if _auth_enabled() else f"{base_url}/")
    page.wait_for_load_state("domcontentloaded")

    if _auth_enabled():
        page.get_by_text("Continue as Guest").wait_for(timeout=10000)
        page.get_by_text("Continue as Guest").click()

    page.wait_for_url("**/projects", timeout=30000)
    wait_for_projects_page(page, timeout=10000)


def _session_token(page) -> str:
    for cookie in page.context.cookies():
        if cookie["name"] == "session_token":
            return cookie["value"]
    raise AssertionError("session_token cookie was not set")


def _create_project(backend_url: str, token: str, project_name: str) -> dict:
    payload = {
        "name": project_name,
        "spec": {"dataflow": {"name": project_name, "nodes": [], "edges": []}},
        "outputs": [],
    }
    req = Request(
        f"{backend_url}/api/projects",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=10.0) as resp:  # noqa: S310 (trusted local URL)
        assert resp.status == 201
        return json.loads(resp.read().decode("utf-8"))


def test_guest_workspace_shared_across_sessions(app_frontend, current_server, browser):
    """A project created by one guest session should be visible to another."""
    require_project_page()
    if _auth_enabled() and not _allow_guest_login():
        pytest.skip("Guest login is disabled for this session")

    base = app_frontend.base_url
    first_context = browser.new_context()
    second_context = browser.new_context()

    try:
        first_page = first_context.new_page()
        second_page = second_context.new_page()

        _enter_guest_workspace(first_page, base)
        token = _session_token(first_page)
        project_name = f"Shared Guest {uuid4().hex[:8]}"
        _create_project(current_server, token, project_name)

        first_page.goto(f"{base}/projects")
        first_page.get_by_text(project_name).wait_for(timeout=10000)

        _enter_guest_workspace(second_page, base)
        second_page.goto(f"{base}/projects")
        second_page.get_by_text(project_name).wait_for(timeout=10000)
    finally:
        first_context.close()
        second_context.close()
