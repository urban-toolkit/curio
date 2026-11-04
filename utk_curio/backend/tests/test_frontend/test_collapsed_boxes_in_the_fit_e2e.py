"""Playwright E2E: a fit of the whole canvas frames what the scenario layers
draw beside the nodes, as well as the nodes.

The report (the frame audit of #1252): a scenario dropped from the Scenario
Catalog arrives collapsed, its set's shared context a box of cards. A fit
framed only the nodes that show, so after the scenario was opened the box sat
under the left rail, and the set's outline and title ran off the canvas's
edge. The box, the pill over it and the set's title are drawn beside React
Flow, which no fit of its nodes knows of.

Here the set's shared context is collapsed far to the left of its scenario.
Once the dataflow opens, its fit puts the box, its pill and the set's title in
the part of the canvas the rail and the bar leave in sight; and so does Fit
view, pressed after the view has moved away from them.

Python nodes only, so it runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_collapsed_boxes_in_the_fit_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    settled_viewport,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

CONTEXT, OWN, OUTCOME = "fit-context", "fit-own", "fit-outcome"
SET = "set-fit-heights"

#: What must be in sight: the shared context's box and its pill, and the set's title.
DRAWN = {
    "the shared context's box": '[data-shared-box$=":context"]',
    "its pill": '[data-shared-header$=":context"]',
    "the set's title": "[data-scenario-set-title]",
}


def _node(node_id: str, x: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": 0,
        "content": "return 1", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec() -> dict:
    """A context node far left of its scenario's node, then a shared outcome:
    one scenario set whose shared context is collapsed."""
    chain = [CONTEXT, OWN, OUTCOME]
    return {
        "dataflow": {
            "name": "Collapsed boxes in the fit", "task": "", "timestamp": 1789193389280,
            "provenance_id": "Collapsed boxes in the fit",
            "nodes": [_node(CONTEXT, -2000), _node(OWN, 0), _node(OUTCOME, 700)],
            "edges": [
                {"id": f"e-{a}-{b}", "source": a, "target": b, "sourceHandle": "out", "targetHandle": "in"}
                for a, b in zip(chain, chain[1:])
            ],
            "scenarioSets": [{"id": SET, "name": "Heights", "shared": {"context": {"collapsed": True}}}],
            "scenarios": [{
                "id": "taller", "name": "Taller", "color": "#e86a3c", "nodes": [OWN], "set": SET,
                "context": [CONTEXT], "outcomes": [OUTCOME],
            }],
        }
    }


#: Where each of *selectors* is against the part of the canvas in sight: right
#: of the rail and below the bar, the dataflow's title and its chips.
_IN_SIGHT_JS = """(selectors) => {
    const pane = document.querySelector('.react-flow').getBoundingClientRect();
    const dock = document.getElementById('tools-palette-dock');
    const left = Math.max(pane.left, dock ? dock.getBoundingClientRect().right : pane.left);
    let top = pane.top;
    const overlays = '[data-curio-menu-bar], [data-curio-canvas-title], '
        + '[data-curio-canvas-title] [data-curio-category-chips]';
    for (const el of document.querySelectorAll(overlays)) {
        top = Math.max(top, el.getBoundingClientRect().bottom);
    }
    const round = (v) => Math.round(v);
    return Object.fromEntries(Object.entries(selectors).map(([what, selector]) => {
        const el = document.querySelector(selector);
        if (!el) return [what, 'not drawn'];
        const r = el.getBoundingClientRect();
        const inSight = r.left >= left - 1 && r.top >= top - 1
            && r.right <= pane.right + 1 && r.bottom <= pane.bottom + 1;
        return [what, inSight ? 'in sight' : `from ${round(r.left)},${round(r.top)} to `
            + `${round(r.right)},${round(r.bottom)}, where the sight is ${round(left)},${round(top)} `
            + `to ${round(pane.right)},${round(pane.bottom)}`];
    }));
}"""


def _where(page) -> dict:
    settled_viewport(page)
    return page.evaluate(_IN_SIGHT_JS, DRAWN)


def test_a_fit_of_the_whole_canvas_frames_a_collapsed_shared_box_and_the_sets_title(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Fit Boxes",
        username="fit_boxes_e2e",
        project_name="Collapsed boxes in the fit",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in (OWN, OUTCOME):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    page.locator(DRAWN["the shared context's box"]).wait_for(state="attached", timeout=45000)

    every = {what: "in sight" for what in DRAWN}
    # 1. The fit of the dataflow as it opens.
    opened = _where(page)

    # 2. The view moved well away to the right, then Fit view.
    page.evaluate("() => window.__curio_reactFlow.setViewport({ x: 1600, y: 200, zoom: 1.5 })")
    moved_away = _where(page)
    page.get_by_role("button", name="fit view", exact=True).click()
    fitted = _where(page)

    seen = {"opened": opened, "after Fit view": fitted}
    assert seen == {"opened": every, "after Fit view": every}, seen
    # Fit view had something to bring back.
    assert moved_away != every, moved_away
