"""Playwright E2E: the collaboration panel on the canvas's right edge.

With collaboration on (``curio.py start --collab``), the collaboration panel
opens by default on the right of the canvas, under the top bar, inside the
window and with nothing over its sections, and the bar's Collaboration button
closes and reopens it where it was. It is the one panel of that dock: a
dataflow's scenarios are the Scenario Catalog drawer's In project tab
(``test_scenarios_in_project_e2e.py``).

CI's stacks start without ``--collab``. The page learns whether collaboration
is on from ``/api/config/public``, so this test answers that request with the
backend's own answer and ``enable_collab`` set: the page then shows the
collaboration panel and its bar button as it does under ``--collab``, with
nobody else in the room. Where the panel sits is decided by the page alone,
which is what is under test, with its sections: Users and Activity, and no
Proposals, since code is typed together with no vote.

The same rule, read from the source: ``canvasSidePanels.test.ts``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_side_panels_e2e.py -v
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .utils import (
    end_routes,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The collaboration panel's section titles, each with its count. Code is
#: typed together with no vote, so the panel holds no Proposals.
SECTIONS = ("Users", "Activity")

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


def _assert_in_place(page, collaboration) -> dict:
    """The panel opens inside the window, under the top bar, with nothing over
    its sections. Returns its box."""
    window = page.viewport_size
    box = collaboration.bounding_box()
    assert box and box["width"] > 0 and box["height"] > 0, f"the collaboration panel has no box: {box}"
    assert box["x"] >= 0 and box["x"] + box["width"] <= window["width"] + 0.5, (
        f"the collaboration panel runs past the window's sides: {box} in {window}"
    )
    assert box["y"] >= 0 and box["y"] + box["height"] <= window["height"] + 0.5, (
        f"the collaboration panel runs past the window's top or bottom: {box} in {window}"
    )
    bar = page.locator('header[data-curio-menu-bar="true"]').first.bounding_box()
    assert bar and box["y"] >= bar["y"] + bar["height"] - 0.5, (
        f"the collaboration panel {box} is not under the top bar {bar}"
    )
    for section in SECTIONS:
        assert _section_title(collaboration, section).evaluate(_ON_TOP_JS), (
            f"the collaboration panel's {section} section is covered"
        )
    assert _section_title(collaboration, "Proposals").count() == 0, (
        "the collaboration panel still has a Proposals section"
    )
    return box


def test_the_collaboration_panel_opens_under_the_top_bar_and_its_button_toggles_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.route("**/api/config/public", _collaboration_on)
    try:
        stub_login_and_enter_workflow(
            page,
            frontend_url=app_frontend.base_url,
            backend_url=current_server,
            name="Side Panels",
            username="side_panels_e2e",
            project_name="Side panels",
        )

        # The collaboration panel opens by itself.
        collaboration = _collaboration_panel(page)
        collaboration.wait_for(state="visible", timeout=30000)
        first = _assert_in_place(page, collaboration)

        # Its bar button closes it, and opens it again where it was.
        toggle = page.get_by_role("button", name="Collaboration", exact=True)
        toggle.click()
        collaboration.wait_for(state="hidden", timeout=10000)
        toggle.click()
        collaboration.wait_for(state="visible", timeout=10000)
        again = _assert_in_place(page, collaboration)
        assert abs(again["y"] - first["y"]) <= 0.5 and abs(again["x"] - first["x"]) <= 0.5, (
            f"the collaboration panel opened again at {again}, not where it was, {first}"
        )
    finally:
        # The page's context closes after the test, and a call of the route
        # still reading the backend's answer then would fail at this worker's
        # next Playwright call (utils/routes.py).
        end_routes(page)
