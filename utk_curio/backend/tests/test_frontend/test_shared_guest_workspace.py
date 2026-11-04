"""Playwright E2E: the shared guest workspace is visible across sessions.

Every guest session is the one shared guest, so two sessions list the same
dataflows. Without sign-in that guest is the one local user and saves: a
dataflow one session saves is listed in the other. With sign-in, a hosted
guest saves nothing: the server refuses with the words the page shows, and the
two sessions list the same dataflows, the examples the shared guest owns.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    project_card,
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


def _create_project(backend_url: str, token: str, project_name: str) -> tuple[int, dict]:
    """POST a new dataflow as the guest: the status and the body it answers."""
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
    try:
        with urlopen(req, timeout=10.0) as resp:  # noqa: S310 (trusted local URL)
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _listed(backend_url: str, token: str) -> list[tuple[str, str]]:
    return sorted((p["id"], p["name"]) for p in api_json(f"{backend_url}/api/projects", token))


def test_guest_workspace_shared_across_sessions(app_frontend, current_server, browser):
    """Two guest sessions list the same dataflows: one saved by the first
    session without sign-in, and with sign-in none, since a hosted guest's
    save is refused."""
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
        status, body = _create_project(current_server, token, project_name)
        if _auth_enabled():
            assert (status, body) == (403, {"error": "Guest users cannot save projects"}), (
                "a hosted guest saved a dataflow"
            )
        else:
            assert status == 201, body

        _enter_guest_workspace(second_page, base)
        first, second = _listed(current_server, token), _listed(current_server, _session_token(second_page))
        assert first == second, "two guest sessions list different dataflows"
        assert (project_name in {name for _id, name in second}) == (not _auth_enabled())

        shown = project_name if not _auth_enabled() else (second[0][1] if second else None)
        if shown is not None:
            second_page.goto(f"{base}/projects")
            project_card(second_page, shown).first.wait_for(timeout=10000)
    finally:
        first_context.close()
        second_context.close()
