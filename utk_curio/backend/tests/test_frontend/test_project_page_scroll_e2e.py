"""Playwright E2E for #161: the projects page must scroll when it overflows.

``MainCanvas.css`` sets ``html, body { overflow: hidden }``. It is a plain
(non-module) CSS import inside a statically-imported component, so style-loader
injects that rule on *every* route, not just the canvas. ``ProjectsList`` used
``minHeight: 100vh`` and relied on document scroll, so past the first screenful
the project grid was simply unreachable - no scrollbar, no wheel, nothing.

Needs enough projects to overflow, which is why they are created over the API
rather than through the UI: this is a layout test, not a project-creation test.

The two captures are the point rather than a nicety. The fix deliberately moves
scrolling into an inner ``overflow-y: auto`` container, and
``_capture_full_page`` measures *document* height - so a single screenshot of
this page looks identical whether or not the fix is present. Top and bottom is
what shows the content actually moved.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_project_page_scroll_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    _post_json,
    api_json,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

SCROLLER = '[data-curio-projects-scroll="true"]'

# The grid is `repeat(auto-fill, minmax(260px, 1fr))` with 180px-tall cards, so
# in a 1280x720 viewport a handful of rows is already more than fits. 24 leaves
# plenty of headroom without making the API setup slow.
PROJECT_COUNT = 24


def _empty_spec(name: str) -> dict:
    return {"dataflow": {"name": name, "nodes": [], "edges": []}}


def test_the_projects_page_scrolls_when_the_grid_overflows(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    session = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scroll User",
        username="scroll_user",
    )
    token = session["token"]

    # Seeded through the testing seam rather than the UI: this is a layout test,
    # and clicking "+ New Dataflow" 24 times would make it a project-creation one.
    for i in range(PROJECT_COUNT):
        _post_json(
            f"{current_server}/api/testing/stub-project",
            {
                "username": "scroll_user",
                "name": f"Scroll Fixture {i:02d}",
                "spec": _empty_spec(f"Scroll {i:02d}"),
            },
        )
    listed = api_json(f"{current_server}/api/projects", token)
    assert len(listed) >= PROJECT_COUNT, f"only {len(listed)} projects were created"

    page.goto(f"{app_frontend.base_url}/projects")

    # Wait for cards before measuring anything: an empty grid cannot overflow, so
    # a premature measurement would make this test vacuously pass.
    page.get_by_text("Scroll Fixture 00").first.wait_for(state="visible", timeout=20000)

    # Checked FIRST, and deliberately not through any test-only attribute: this is
    # the behavioural symptom of #161. html/body have overflow:hidden app-wide, so
    # content that grows the *document* is content the user cannot reach. Pre-fix
    # this is what fails, and the message says why rather than pointing at a
    # missing hook.
    overflow = page.evaluate(
        """() => ({
            docScroll: document.documentElement.scrollHeight,
            docClient: document.documentElement.clientHeight,
            bodyOverflowY: getComputedStyle(document.body).overflowY,
        })"""
    )
    assert overflow["bodyOverflowY"] == "hidden", (
        f"this test assumes the app-wide html/body overflow:hidden rule from "
        f"MainCanvas.css is in play; got {overflow['bodyOverflowY']!r}"
    )
    assert overflow["docScroll"] <= overflow["docClient"] + 1, (
        f"the document is taller than the viewport ({overflow}) while body "
        f"overflow is hidden, so the overflowing projects are unreachable - this "
        f"is #161. The page must own its scroll inside the viewport instead."
    )

    scroller = page.locator(SCROLLER)
    expect(scroller).to_be_visible(timeout=20000)
    metrics = scroller.evaluate(
        "el => ({ scrollHeight: el.scrollHeight, clientHeight: el.clientHeight })"
    )
    assert metrics["scrollHeight"] > metrics["clientHeight"], (
        f"the project grid does not overflow its container ({metrics}), so this "
        f"test cannot tell a scrollable page from a clipped one - add more "
        f"fixtures or shrink the viewport"
    )

    save_workflow_test_screenshot(
        page, "projects-page-scroll",
        test_name="test_the_projects_page_scrolls_when_the_grid_overflows__top",
        fit_reactflow=False,
    )

    # Now actually scroll it, and prove the content moved.
    scroller.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    page.wait_for_function(
        "sel => document.querySelector(sel).scrollTop > 0",
        arg=SCROLLER,
        timeout=10000,
    )
    scrolled = scroller.evaluate("el => el.scrollTop")
    assert scrolled > 0, "the container did not scroll"

    save_workflow_test_screenshot(
        page, "projects-page-scroll",
        test_name="test_the_projects_page_scrolls_when_the_grid_overflows__bottom",
        fit_reactflow=False,
    )
