"""Playwright E2E: the Scenarios panel and the collaboration panel share the
canvas's right edge.

With collaboration on (``curio.py start --collab``), the collaboration panel
opens by default on the right of the canvas, under the top bar, and View, Show
scenarios opens the Scenarios panel there too. The Scenarios panel opens under
the collaboration panel while that one is open, and moves up to the top bar
once it is closed, so neither covers the other.

CI's stacks start without ``--collab``. The page learns whether collaboration
is on from ``/api/config/public``, so this test answers that request with the
backend's own answer and ``enable_collab`` set: the page then shows the
collaboration panel and its bar button as it does under ``--collab``, with
nobody else in the room. Where the two panels sit is decided by the page
alone, which is what is under test.

The same rule, read from the source: ``canvasSidePanels.test.ts``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_side_panels_e2e.py -v
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .utils import (
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The collaboration panel's section titles, each with its count.
SECTIONS = ("Users", "Proposals", "Activity")

# Whether the point at the middle of an element hits that element: nothing
# else is drawn over it there.
_ON_TOP_JS = """(el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
}"""


def _collaboration_on(route) -> None:
    """The backend's public config, with collaboration on."""
    response = route.fetch()
    config = response.json()
    config["enable_collab"] = True
    route.fulfill(response=response, json=config)


def _section_title(scope, section: str):
    return scope.get_by_text(re.compile(rf"^{section} \(\d+\)$"))


def _collaboration_panel(page):
    """The collaboration panel: the innermost element that holds its Users and
    its Activity sections."""
    return (
        page.locator("*")
        .filter(has=_section_title(page, "Users"))
        .filter(has=_section_title(page, "Activity"))
        .last
    )


def _assert_stacked(page, collaboration, scenarios) -> dict:
    """Both panels open inside the window, the Scenarios panel under the
    collaboration panel, their boxes apart and nothing over either. Returns
    the collaboration panel's box."""
    window = page.viewport_size
    boxes = {"collaboration panel": collaboration.bounding_box(), "Scenarios panel": scenarios.bounding_box()}
    for name, box in boxes.items():
        assert box and box["width"] > 0 and box["height"] > 0, f"the {name} has no box: {box}"
        assert box["x"] >= 0 and box["x"] + box["width"] <= window["width"] + 0.5, (
            f"the {name} runs past the window's sides: {box} in {window}"
        )
        assert box["y"] >= 0 and box["y"] + box["height"] <= window["height"] + 0.5, (
            f"the {name} runs past the window's top or bottom: {box} in {window}"
        )
    a, b = boxes["collaboration panel"], boxes["Scenarios panel"]
    across = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
    down = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
    assert across <= 0.5 or down <= 0.5, (
        f"the Scenarios panel {b} covers the collaboration panel {a}: "
        f"they share {across:.0f} x {down:.0f} px"
    )
    assert b["y"] >= a["y"] + a["height"] - 0.5, (
        f"the Scenarios panel {b} does not open under the collaboration panel {a}"
    )
    for section in SECTIONS:
        assert _section_title(collaboration, section).evaluate(_ON_TOP_JS), (
            f"the collaboration panel's {section} section is covered"
        )
    assert scenarios.get_by_role("heading", name="Scenarios").evaluate(_ON_TOP_JS), (
        "the Scenarios panel's title is covered"
    )
    return a


def test_the_scenarios_panel_opens_under_the_collaboration_panel(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.route("**/api/config/public", _collaboration_on)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Side Panels",
        username="side_panels_e2e",
        project_name="Side panels",
    )

    # The collaboration panel opens by itself; the Scenarios panel from View.
    collaboration = _collaboration_panel(page)
    collaboration.wait_for(state="visible", timeout=30000)
    page.get_by_role("button", name="View menu").click()
    page.get_by_role("button", name="Show scenarios", exact=True).click()
    scenarios = page.get_by_test_id("scenarios-panel")
    scenarios.wait_for(state="visible", timeout=10000)
    top = _assert_stacked(page, collaboration, scenarios)["y"]

    # Closed from its bar button, the collaboration panel gives its place to
    # the Scenarios panel, which moves up to the top bar.
    toggle = page.get_by_role("button", name="Collaboration", exact=True)
    toggle.click()
    collaboration.wait_for(state="hidden", timeout=10000)
    page.wait_for_function(
        """(top) => {
            const box = document.querySelector('[data-testid="scenarios-panel"]').getBoundingClientRect();
            return Math.abs(box.top - top) <= 0.5;
        }""",
        arg=top,
        timeout=10000,
    )

    # Opened again, it takes the top back and the Scenarios panel goes under it.
    toggle.click()
    collaboration.wait_for(state="visible", timeout=10000)
    _assert_stacked(page, collaboration, scenarios)
