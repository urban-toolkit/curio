def test_backend_server(current_server, sandbox_server, page):
    """Test that the backend server is live."""
    page.goto(f"{current_server}/liveness")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Backend is live.").wait_for()
    assert "Backend is live." in page.content()


def test_sandbox_server(sandbox_server, page):
    """Test that the sandbox server is live."""
    page.goto(f"{sandbox_server}/liveness")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Sandbox is live.").wait_for()
    assert "Sandbox is live." in page.content()


def test_frontend_server(frontend_server, page):
    """Test that the frontend server is live."""
    page.goto(f"{frontend_server}")
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text("Logar").wait_for()

    assert page.title() == "Curio"
    assert "Logar" in page.content()
