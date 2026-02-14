from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_frontend_server(app_frontend: FrontendPage, page):
    """Test that the frontend server is live."""
    app_frontend.goto_page("/")
    page.wait_for_load_state("domcontentloaded")
    page.context.clear_cookies()  # Clear cookies to ensure login page appears
    # Wait for login UI (may be "Login" or "Logar" depending on locale)
    page.get_by_text("Login").or_(page.get_by_text("Logar")).wait_for(timeout=60000)

    app_frontend.expect_page_title("Curio")
    assert "Login" in page.content() or "Logar" in page.content()
