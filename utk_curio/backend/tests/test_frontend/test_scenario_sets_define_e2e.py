"""Playwright E2E: scenario sets on the canvas.

1. A shipped dataflow with a set of three scenarios (Lower Manhattan park
   shade): under each shared node, a circle per scenario of the set, filled
   where that scenario uses the node. *Buildings around parks* is read by the
   two edited scenarios only, so Existing's circle is hollow under it.
2. Defining two scenarios in a small dataflow, step by step: View, Define
   scenario; the scenario's own nodes, selected on the canvas; the shared
   context and outcomes Curio found, confirmed; a name and a new scenario set,
   then Save scenario; then the second one into the same set. The saved spec holds the set, each scenario's context and
   outcomes, and the shared nodes carry both scenarios' circles. Collapsing
   the shared outcomes makes one box of cards, which the set keeps.

Nothing here runs a node, so neither test needs WebGPU.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_sets_define_e2e.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import (
    REPO_ROOT,
    api_json,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PARK_SHADE = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "lower-manhattan-park-shade.json"

_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""

_SELECTED_JS = "() => window.__curio_reactFlow.getNodes().filter((n) => n.selected).map((n) => n.id).sort()"


def _circles(page, node_id: str) -> list[tuple[str, bool]]:
    row = page.locator(f'[data-scenario-dots="{node_id}"]')
    row.wait_for(state="attached", timeout=15000)
    return [
        (dot.get_attribute("data-scenario"), dot.get_attribute("data-member") == "true")
        for dot in row.locator("[data-scenario]").all()
    ]


def test_the_shared_nodes_of_a_set_carry_a_circle_per_scenario(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(PARK_SHADE.read_text(encoding="utf-8"))
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Sets",
        username="scenario_sets_circles_e2e",
        project_name="Lower Manhattan park shade",
        project_spec=spec,
    )
    require_owner_view(page)
    scenarios = spec["dataflow"]["scenarios"]
    ids = [s["id"] for s in scenarios]
    existing, towers, cap = ids

    around = "park-shade-around"
    node_locator(page, around).wait_for(state="visible", timeout=45000)
    assert _circles(page, around) == [(existing, False), (towers, True), (cap, True)]
    # Fed by all three: every circle filled.
    chart = next(n["id"] for n in spec["dataflow"]["nodes"] if n.get("title") == "Minutes of shadow per park")
    assert _circles(page, chart) == [(existing, True), (towers, True), (cap, True)]

    # The circles sit under the node, not over its header.
    frame_nodes(page, [around])
    node_box = node_locator(page, around).bounding_box()
    dots_box = page.locator(f'[data-scenario-dots="{around}"]').bounding_box()
    assert dots_box["y"] >= node_box["y"] + node_box["height"] - 1, (node_box, dots_box)


def _spec() -> dict:
    node = lambda node_id, title, x, y: {  # noqa: E731
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": y,
        "content": "return input_0" if node_id != "load" else "return 1",
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "title": title, "metadata": {"keywords": []},
    }
    edge = lambda a, b: {"id": f"{a}-{b}", "source": a, "target": b, "sourceHandle": "out", "targetHandle": "in"}  # noqa: E731
    return {"dataflow": {
        "name": "Heights", "task": "", "timestamp": 1789193389280, "provenance_id": "Heights",
        "nodes": [
            node("load", "Load buildings", 0, 300),
            node("real", "Real heights", 700, 0),
            node("tall", "Twice as tall", 700, 600),
            node("chart", "Compare shade", 1400, 300),
        ],
        "edges": [edge("load", "real"), edge("load", "tall"), edge("real", "chart"), edge("tall", "chart")],
    }}


TITLES = {"load": "Load buildings", "real": "Real heights", "tall": "Twice as tall", "chart": "Compare shade"}


def _select(page, node_id: str) -> None:
    """Select one node the way a person does: Shift, and a box dragged around it.
    A toast from the last save sits in the canvas's corner: gone first."""
    dismiss_toasts(page)
    frame_nodes(page, [node_id])
    box = node_locator(page, node_id).bounding_box()
    right, bottom = box["x"] + box["width"] + 12, box["y"] + box["height"] + 12
    left, top = box["x"] - 12, box["y"] - 12
    for point in ((right, bottom), (left, top)):
        assert page.evaluate(_ON_PANE_JS, list(point)), f"{point} is not on the empty canvas"
    page.mouse.move(right, bottom)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(left, top, steps=20)
    page.mouse.up()
    page.keyboard.up("Shift")
    assert page.evaluate(_SELECTED_JS) == [node_id]


def _define(page, node_id: str, name: str) -> None:
    _select(page, node_id)
    page.get_by_role("button", name="View menu").click()
    page.get_by_role("button", name="Define scenario", exact=True).click()
    panel = page.get_by_test_id("scenario-define-panel")
    panel.wait_for(state="visible", timeout=10000)
    # 1. Its own nodes: the selection.
    panel.get_by_role("region", name="Scenario-specific nodes").get_by_text(TITLES[node_id]).wait_for(timeout=10000)
    panel.get_by_role("button", name="Next: shared context & outcomes").click()
    # 2. What Curio found up and down from them.
    context = panel.get_by_role("region", name="Shared context").inner_text()
    outcomes = panel.get_by_role("region", name="Shared outcomes").inner_text()
    assert "Load buildings" in context, context
    assert "Compare shade" in outcomes, outcomes
    panel.get_by_role("button", name="Next: name & set").click()
    # 3. Its name and set.
    panel.get_by_test_id("scenario-define-name").fill(name)
    panel.get_by_test_id("scenario-define-save").click()
    panel.wait_for(state="detached", timeout=10000)


def test_two_scenarios_defined_step_by_step_share_one_set(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Sets Define",
        username="scenario_sets_define_e2e",
        project_name="Heights",
        project_spec=_spec(),
    )
    require_owner_view(page)
    for node_id in ("load", "real", "tall", "chart"):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    _define(page, "real", "Real heights")
    # The first scenario made a set; the second goes in it, chosen by default.
    _define(page, "tall", "Twice as tall")

    save_dataflow(page)
    project_id = session["project"]["id"]
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]["dataflow"]
    assert [s["name"] for s in saved["scenarioSets"]] == ["Heights"]
    set_id = saved["scenarioSets"][0]["id"]
    assert [(s["name"], s["nodes"], s["set"], s["context"], s["outcomes"]) for s in saved["scenarios"]] == [
        ("Real heights", ["real"], set_id, ["load"], ["chart"]),
        ("Twice as tall", ["tall"], set_id, ["load"], ["chart"]),
    ]
    ids = [s["id"] for s in saved["scenarios"]]
    assert _circles(page, "load") == [(ids[0], True), (ids[1], True)]
    assert _circles(page, "chart") == [(ids[0], True), (ids[1], True)]

    # 3. Collapse the shared outcomes: one gray box with a card per node, the
    # set's circles on it, and the node hidden. The set keeps it collapsed.
    frame_nodes(page, ["chart"])
    page.get_by_test_id(f"shared-collapse-{set_id}-outcomes").click()
    box = page.get_by_test_id(f"shared-box-{set_id}-outcomes")
    box.wait_for(state="visible", timeout=10000)
    card = box.locator('[data-shared-row="chart"]')
    assert "Compare shade" in card.inner_text()
    assert [d.get_attribute("data-member") for d in card.locator("[data-scenario]").all()] == ["true", "true"]
    assert not node_locator(page, "chart").is_visible()
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]["dataflow"]
    assert saved["scenarioSets"][0].get("shared") == {"outcomes": {"collapsed": True}}

    # Reopened, it is still collapsed; a double-click shows the node again.
    page.reload()
    box.wait_for(state="visible", timeout=45000)
    assert "Double-click to expand" in box.inner_text()
    # The reopened view fits the nodes that show, which can leave the box out.
    box.dispatch_event("dblclick")
    node_locator(page, "chart").wait_for(state="visible", timeout=10000)
    assert page.locator(f'[data-shared-header="group:{set_id}:outcomes"]').inner_text().startswith("Shared outcomes")
