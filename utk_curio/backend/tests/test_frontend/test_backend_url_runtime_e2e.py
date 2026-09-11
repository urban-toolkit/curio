"""The bundle resolves the backend at RUNTIME, not at build time.

``src/utils/backendUrl.ts`` prefers ``window.__CURIO_BACKEND_URL__`` over the
value dotenv-webpack baked in, and the ``browser`` fixture injects that global
into every context. This is the contract that lets one frontend build serve N
backend+sandbox pairs under xdist; if it regresses, every worker but the one
matching the baked port silently tests someone else's backend.
"""

from .utils import REPO_ROOT  # noqa: F401  (keeps the package import path warm)


def test_the_page_sees_this_workers_backend_url(page, frontend_server, current_server):
    page.goto(frontend_server)
    # window.curio is created by src/registry/index.ts when the bundle loads.
    page.wait_for_function(
        "() => window.curio && typeof window.curio.backendUrl === 'string'",
        timeout=30_000,
    )
    assert page.evaluate("window.__CURIO_BACKEND_URL__") == current_server
    # The registry exposes a getter, so this reads the runtime value.
    assert page.evaluate("window.curio.backendUrl") == current_server


def test_the_injected_value_wins_over_the_baked_one(browser, frontend_server, current_server):
    # A context whose init script names a DIFFERENT backend must see that one.
    # Nothing is fetched from it; this only proves the resolution order.
    context = browser.new_context()
    try:
        decoy = current_server.rstrip("/") + "9"
        context.add_init_script(f"window.__CURIO_BACKEND_URL__ = {decoy!r};")
        page = context.new_page()
        page.goto(frontend_server)
        page.wait_for_function(
            "() => window.curio && typeof window.curio.backendUrl === 'string'",
            timeout=30_000,
        )
        assert page.evaluate("window.curio.backendUrl") == decoy
    finally:
        context.close()
