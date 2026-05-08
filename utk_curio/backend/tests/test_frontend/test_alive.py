from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import auth_enabled_env, skip_project_page_env

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_backend_server(current_server, page):
    """Test that the backend server is live."""
    page.goto(f"{current_server}/live")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Backend is live.").wait_for()
    assert "Backend is live." in page.content()


def test_sandbox_server(sandbox_server, page):
    """Test that the sandbox server is live."""
    page.goto(f"{sandbox_server}/live")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Sandbox is live.").wait_for()
    assert "Sandbox is live." in page.content()


def test_backend_version(current_server, page):
    """Backend /version returns the package version as JSON."""
    from utk_curio import __version__

    resp = page.request.get(f"{current_server}/version")
    assert resp.ok, f"GET {current_server}/version returned {resp.status}"
    body = resp.json()
    assert body.get("version") == __version__, (
        f"Expected version {__version__!r}, got {body!r}"
    )


def test_sandbox_version(sandbox_server, page):
    """Sandbox /version returns the package version as JSON."""
    from utk_curio import __version__

    resp = page.request.get(f"{sandbox_server}/version")
    assert resp.ok, f"GET {sandbox_server}/version returned {resp.status}"
    body = resp.json()
    assert body.get("version") == __version__, (
        f"Expected version {__version__!r}, got {body!r}"
    )


def test_frontend_server(app_frontend: FrontendPage, page):
    """Test that the frontend server is live and redirects to auth."""
    app_frontend.goto_page("/")
    page.wait_for_load_state("domcontentloaded")
    page.context.clear_cookies()
    page.goto(app_frontend.base_url + "/")
    page.wait_for_load_state("domcontentloaded")
    auth_disabled = not auth_enabled_env()
    skip_projects = skip_project_page_env()

    if skip_projects:
        # ``--no-project`` mode: SPA auto-guest-signs in and routes ``/`` to
        # ``/dataflow`` (see index.tsx); there is no ``/projects`` page.
        page.wait_for_url("**/dataflow**", timeout=60000)
        return

    if auth_disabled:
        page.wait_for_url("**/projects", timeout=60000)
        page.get_by_role("heading", name="Projects").wait_for(timeout=60000)
        return

    # The app should redirect unauthenticated users to /auth/signin
    page.get_by_role("button", name="Sign In", exact=True).or_(page.get_by_text("Login")).wait_for(timeout=60000)

    app_frontend.expect_page_title("Curio")
    content = page.content()
    assert "Sign in" in content or "Login" in content
