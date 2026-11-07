"""Playwright E2E: the shared guest workspace is visible across sessions.

Every guest session is the one shared guest, so two sessions list the same
dataflows. Without sign-in that guest is the one local user and saves: a
dataflow one session saves is listed in the other. With sign-in, a hosted
guest's create is a dataflow of its own, kept until the server starts again:
the session that made it lists it first, marked Kept for this visit, and the
other session lists the dataflows the shared guest owns, as before, and none
of it.

A guest whose first listing the server fails still gets the dataflows (#1274).
"""

from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from playwright.sync_api import expect

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    close_after_routes,
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


def _gallery(backend_url: str, token: str) -> list[dict]:
    """The dataflows the session signed in as *token* lists, in its gallery's order."""
    return api_json(f"{backend_url}/api/projects", token)


def _listed(backend_url: str, token: str) -> list[tuple[str, str]]:
    return sorted((p["id"], p["name"]) for p in _gallery(backend_url, token))


def test_guest_workspace_shared_across_sessions(app_frontend, current_server, browser):
    """Two guest sessions list the dataflows the shared guest owns. Without
    sign-in, one the first session saves is listed in both. With sign-in, the
    first session's create is a dataflow of its own: listed first in its
    gallery alone, marked Kept for this visit."""
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
        assert status == 201, body
        assert body.get("kept_for_visit", False) is _auth_enabled(), body

        _enter_guest_workspace(second_page, base)
        if not _auth_enabled():
            first, second = _listed(current_server, token), _listed(current_server, _session_token(second_page))
            assert first == second, "two guest sessions list different dataflows"
            assert project_name in {name for _id, name in second}
            second_page.goto(f"{base}/projects")
            project_card(second_page, project_name).first.wait_for(timeout=10000)
            return

        mine = body["id"]
        first, second = _gallery(current_server, token), _gallery(current_server, _session_token(second_page))
        assert (first[0]["id"], first[0]["name"], first[0]["kept_for_visit"]) == (mine, project_name, True), (
            f"the first session's gallery does not list its own dataflow first, marked: {first[:2]}"
        )
        assert sorted((p["id"], p["name"]) for p in first[1:]) == sorted((p["id"], p["name"]) for p in second), (
            "besides the first session's own dataflow, the two sessions list different dataflows"
        )
        assert mine not in {p["id"] for p in second} and not any(p.get("kept_for_visit") for p in second), (
            "the second session lists the first session's own dataflow"
        )
        # The first session's gallery shows its dataflow marked; the second's shows none of it.
        first_page.goto(f"{base}/projects")
        card = project_card(first_page, project_name).first
        card.wait_for(timeout=10000)
        mark = card.locator('[data-curio-kept-for-visit="true"]')
        expect(mark).to_have_text("Kept for this visit")
        expect(mark).to_have_attribute("data-tooltip", "Sign in to save dataflows.")
        second_page.goto(f"{base}/projects")
        if second:
            project_card(second_page, second[0]["name"]).first.wait_for(timeout=10000)
        expect(project_card(second_page, project_name)).to_have_count(0)
    finally:
        first_context.close()
        second_context.close()


# How many of the page's first list requests the server fails.
FAILED_LISTINGS = 2


def test_a_guest_whose_first_listing_fails_still_gets_the_dataflows(app_frontend, current_server, browser):
    """#1274: "Continue as Guest" on a fresh browser while the server fails the
    list request, as stable failed some of its requests in the days its backend
    ran out of open files. The projects page drew the failed list as an empty
    gallery and never asked again, so the guest saw no dataflow until a reload.
    It now asks again, and the guest's dataflows come without a reload. Without
    sign-in the shared guest signs in by itself, and the page is the same."""
    failed: list[str] = []

    def fail_the_first_listings(route) -> None:
        if route.request.method == "GET" and len(failed) < FAILED_LISTINGS:
            failed.append(route.request.url)
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"error": "[Errno 24] Too many open files"}),
            )
        else:
            route.continue_()

    context = browser.new_context()
    try:
        page = context.new_page()
        page.route(
            lambda url: urlparse(url).path.rstrip("/").endswith("/api/projects"),
            fail_the_first_listings,
        )
        _enter_guest_workspace(page, app_frontend.base_url)
        names = [name for _id, name in _listed(current_server, _session_token(page))]
        assert names, "the shared guest lists no dataflow, so the page would have none to show"

        try:
            project_card(page, names[0]).first.wait_for(timeout=20000)
        except Exception as exc:
            raise AssertionError(
                f"after the server failed {len(failed)} list request(s), the projects page showed "
                f"no dataflow within 20 s, though the guest has {len(names)}"
            ) from exc
        assert failed, "the server failed no list request, so this proves nothing"
    finally:
        close_after_routes(context)
