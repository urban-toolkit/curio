"""Playwright E2E: the Scenario Catalog drawer's Browse all tab lists each
dataflow's scenarios under its name (from komar41's #914).

Two dataflows of the account's own: "Elm Grove heat", with the scenarios "Cool
roofs" and "Street trees", and "Elm Grove flood", with "Levee". Searched for
"Elm Grove", so the seeded examples' scenarios stay out, and sorted by name,
the three cards alternate between the two dataflows. Grouped, Elm Grove heat's
two cards sit together under its name and count, its group first because its
first card is, then Elm Grove flood's card under its own.

Every check comes before the frame, so a frame with no baseline yet hides
none. Python nodes only, so it runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenario_catalog_drawer_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DRAWER = '[data-curio-scenario-catalog-drawer="true"]'
TEST_NAME = "test_browse_all_groups_the_cards_by_dataflow"
SEARCH = "Elm Grove"
HEAT, FLOOD = "Elm Grove heat", "Elm Grove flood"

#: Each dataflow's scenarios, as it lists them, with their colors.
DATAFLOWS = {
    HEAT: [("Cool roofs", "#3567c7"), ("Street trees", "#2f8f4a")],
    FLOOD: [("Levee", "#e86a3c")],
}

#: The open dataflow's one node: a capture frames the canvas's nodes.
CANVAS_NODE = "groups-canvas-node"


def _node(node_id: str, x: int) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": 0,
        "content": "return 1", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec(name: str, scenarios: list[tuple[str, str]]) -> dict:
    """A chain of code nodes, a loader and then one step per scenario, each
    scenario holding its step, all in one scenario set named after the
    dataflow."""
    steps = [f"step{i}" for i in range(len(scenarios))]
    chain = ["load", *steps]
    return {
        "dataflow": {
            "name": name, "task": "", "timestamp": 1789193389280, "provenance_id": name,
            "nodes": [_node(node_id, 400 * i) for i, node_id in enumerate(chain)],
            "edges": [
                {"id": f"e-{a}-{b}", "source": a, "target": b, "sourceHandle": "out", "targetHandle": "in"}
                for a, b in zip(chain, chain[1:])
            ],
            "scenarioSets": [{"id": "set", "name": name}],
            "scenarios": [
                {"id": f"s{i}", "name": scenario, "color": color, "nodes": [steps[i]], "set": "set"}
                for i, (scenario, color) in enumerate(scenarios)
            ],
        }
    }


def _canvas_spec() -> dict:
    return {
        "dataflow": {
            "name": "Scenario groups", "task": "", "timestamp": 1789193389280,
            "provenance_id": "Scenario groups", "nodes": [_node(CANVAS_NODE, 420)], "edges": [],
        }
    }


_CARD_KEYS_JS = "(cards) => cards.map((card) => card.getAttribute('data-scenario-key'))"


def test_browse_all_groups_the_cards_by_dataflow(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenario Groups",
        username="scenario_groups_e2e",
        project_name="Scenario groups",
        project_spec=_canvas_spec(),
    )
    require_owner_view(page)
    token = session["token"]
    ids = {}
    for name, scenarios in DATAFLOWS.items():
        created = api_json(f"{current_server}/api/projects", token, method="POST",
                           payload={"name": name, "spec": _spec(name, scenarios), "outputs": []})
        ids[name] = created["id"]
    node_locator(page, CANVAS_NODE).wait_for(state="visible", timeout=45000)

    page.get_by_role("button", name="Scenario Catalog", exact=True).click()
    drawer = page.locator(DRAWER)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=20000)
    browse = drawer.get_by_role("button", name="Browse all", exact=True)
    browse.click()
    expect(browse).to_have_attribute("aria-pressed", "true")
    drawer.get_by_placeholder("Search scenarios, projects…").fill(SEARCH)
    drawer.get_by_role("combobox", name="Sort scenarios").select_option("name")
    cards = drawer.locator("article[data-scenario-key]")
    expect(cards).to_have_count(3, timeout=20000)
    heat, flood = ids[HEAT], ids[FLOOD]
    # By name alone the cards would alternate: Cool roofs (heat), Levee
    # (flood), Street trees (heat). Grouped, heat's two come first.
    order = cards.evaluate_all(_CARD_KEYS_JS)
    assert order == [f"{heat}/s0", f"{heat}/s1", f"{flood}/s0"], (
        f"the cards read {order}: each dataflow's cards are not together"
    )

    groups = drawer.locator("[data-scenario-group]")
    expect(groups).to_have_count(2)
    projects = [groups.nth(i).get_attribute("data-scenario-group") for i in range(2)]
    assert projects == [heat, flood], (
        f"the groups are {projects}, not {[heat, flood]}: not in the order of their first cards"
    )
    for project, name, count, keys in (
        (heat, HEAT, "2 scenarios", [f"{heat}/s0", f"{heat}/s1"]),
        (flood, FLOOD, "1 scenario", [f"{flood}/s0"]),
    ):
        group = drawer.get_by_role("region", name=name, exact=True)
        expect(group).to_have_attribute("data-scenario-group", project)
        expect(group.locator("h3").first).to_have_text(f"{name} {count}")
        held = group.locator("article[data-scenario-key]").evaluate_all(_CARD_KEYS_JS)
        assert held == keys, f"{name}'s group holds {held}, not its own cards {keys}"

    # The pointer on the canvas, off the drawer, so no card shows hovered.
    page.mouse.move(400, page.viewport_size["height"] - 30)
    save_workflow_test_screenshot(page, "scenario-catalog-drawer", test_name=TEST_NAME, sweep_toasts=True)
