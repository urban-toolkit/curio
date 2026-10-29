"""Playwright E2E: a dataflow's scenarios in the Scenario Catalog drawer's In
project tab, which took over the Scenarios panel (step 16 of #819's port).

A loader feeds a step that doubles its heights, which feeds a total. The
scenario "Doubled" holds the doubling step, so the loader is its fixed context.
With the total selected on the canvas, the drawer opened from the top bar's
Scenario Catalog button shows, on its In project tab, the scenario's card, and
the tab counts this dataflow's one scenario. Then:

1. Pointing at its card outlines its fixed context, the loader, on the canvas,
   and nothing else; leaving the card takes the outline away.
2. Edit scenario opens Define scenario on it, its node selected; selecting
   the total too and saving puts the total into the scenario, and the
   scenario's frame on the canvas grows around it; editing it again with its
   node alone selected takes the total out.
3. Its details change its name and its color: the card and the frame on the
   canvas follow.
4. Run scenario runs it: the loader, which has not run, and its lever, each
   once.
5. The saved dataflow keeps the new name and color, and the total is added
   again through Edit scenario for the frames, before and after.

Every check comes before the frames, so a frame with no baseline yet hides
none. Python nodes only, so it runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scenarios_in_project_e2e.py -v
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    SandboxRuns,
    api_json,
    close_scenario_details,
    close_scenario_drawer,
    in_project_card,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow_and_settle_header,
    save_workflow_test_screenshot,
    scenario_card_button,
    set_canvas_zoom,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
    wait_for_run_guard_released,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER = "inp-load"
SCALE = "inp-scale"
TOTAL = "inp-total"
SCENARIO = "inp-doubled"
DATAFLOW = "Heights study"
NAME, COLOR = "Doubled", "#e86a3c"
NEW_NAME, NEW_COLOR = "Twice as tall", "#2f8f4a"
TEST_NAME = "test_the_in_project_tab_adds_renames_marks_and_runs_a_scenario"

#: The canvas zoom the frames show: every node between the tools rail and
#: where the drawer opens, under the dataflow's title.
ZOOM = 0.45
#: The drawer's width (``CatalogDrawerShell.module.css``: ``min(520px, 100vw)``).
DRAWER_WIDTH = 520
#: The class the canvas gives the fixed context of the scenario pointed at.
FIXED_CLASS = "curio-scenario-fixed"

LOADER_CODE = 'import pandas as pd\nreturn pd.DataFrame({"height": [10, 20, 30]})\n'
SCALE_CODE = 'df = input_0.copy()\ndf["height"] = df["height"] * 2\nreturn df\n'
TOTAL_CODE = 'return input_0.assign(total=input_0["height"].sum())\n'


def _spec() -> dict:
    node = lambda node_id, node_type, x, y, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": DATAFLOW,
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": DATAFLOW,
            "nodes": [
                node(LOADER, "curio.builtin/data-loading", 400, 340, LOADER_CODE),
                node(SCALE, "curio.builtin/computation-analysis", 1045, 340, SCALE_CODE),
                node(TOTAL, "curio.builtin/computation-analysis", 1045, 840, TOTAL_CODE),
            ],
            "edges": [
                {"id": "e-load-scale", "source": LOADER, "target": SCALE,
                 "sourceHandle": "out", "targetHandle": "in"},
                {"id": "e-scale-total", "source": SCALE, "target": TOTAL,
                 "sourceHandle": "out", "targetHandle": "in"},
            ],
            "scenarios": [{"id": SCENARIO, "name": NAME, "color": COLOR, "nodes": [SCALE]}],
        }
    }


_SELECTED_JS = """() => window.__curio_reactFlow.getNodes().filter((n) => n.selected).map((n) => n.id).sort()"""

_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""

# Whether the scenario's frame on the canvas surrounds the node.
_FRAMED_JS = """([scenario, node]) => {
    const frame = document.querySelector(`[data-scenario-frame="${scenario}"]`);
    const el = document.querySelector(`.react-flow__node[data-id="${node}"]`);
    if (!frame || !el) return false;
    const f = frame.getBoundingClientRect();
    const n = el.getBoundingClientRect();
    return n.left >= f.left - 0.5 && n.top >= f.top - 0.5 && n.right <= f.right + 0.5 && n.bottom <= f.bottom + 0.5;
}"""

_FRAME_COLOR_JS = """(id) => {
    const el = document.querySelector(`[data-scenario-frame="${id}"]`);
    return el ? getComputedStyle(el).borderTopColor : null;
}"""

_OUTLINED_JS = """(cls) => [...document.querySelectorAll('.react-flow__node')]
    .filter((el) => el.classList.contains(cls)).map((el) => el.getAttribute('data-id')).sort()"""


def _rgb(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i:i + 2], 16) for i in (0, 2, 4)))


def _saved_scenarios(server: str, token: str, project_id: str) -> list[dict]:
    return api_json(f"{server}/api/projects/{project_id}", token)["spec"]["dataflow"].get("scenarios") or []


# The bottom of what is fixed over the top of the canvas: the top bar, and the
# dataflow's title with its category chips.
_TOP_OVERLAYS_JS = """() => Math.max(...[
    ...document.querySelectorAll('[data-curio-menu-bar]'),
    ...document.querySelectorAll('[data-curio-canvas-title], [data-curio-canvas-title] [data-curio-category-chips]'),
].map((el) => el.getBoundingClientRect().bottom))"""


def _assert_beside_the_drawer(page, node_ids: list[str]) -> None:
    """Every node shows whole between the tools rail and where the drawer
    opens, under the top bar and the dataflow's title."""
    window = page.viewport_size
    rail = page.locator("#tools-palette-dock").bounding_box()
    top = page.evaluate(_TOP_OVERLAYS_JS)
    for node_id in node_ids:
        box = node_locator(page, node_id).bounding_box()
        assert box and box["x"] >= rail["x"] + rail["width"], f"{node_id} at {box} is under the tools rail {rail}"
        assert box["x"] + box["width"] <= window["width"] - DRAWER_WIDTH, (
            f"{node_id} at {box} is not left of the drawer"
        )
        assert box["y"] >= top and box["y"] + box["height"] <= window["height"], (
            f"{node_id} at {box} is not under the top bar and the title (bottom {top}), in the window"
        )


def _select_with_shift_drag(page, node_id: str) -> None:
    """Select *node_id* as a person does: Shift, and a box dragged around it on
    the empty canvas, at the view the canvas shows."""
    box = node_locator(page, node_id).bounding_box()
    left, top = box["x"] - 12, box["y"] - 12
    right, bottom = box["x"] + box["width"] + 12, box["y"] + box["height"] + 12
    for point in ((right, bottom), (left, top)):
        assert page.evaluate(_ON_PANE_JS, list(point)), f"{point} is not on the empty canvas"
    page.mouse.move(right, bottom)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(left, top, steps=20)
    page.mouse.up()
    page.keyboard.up("Shift")


def _edit_scenario_nodes(page, scenario_id: str, node_ids: list[str]) -> None:
    """Edit scenario on its card, select *node_ids* on the canvas in step 1,
    and save it from the last step; the drawer closes as the panel opens."""
    scenario_card_button(page, scenario_id, "Edit scenario").click()
    panel = page.get_by_test_id("scenario-define-panel")
    expect(panel).to_be_visible(timeout=10000)
    page.wait_for_function(f"() => ({_SELECTED_JS})().length > 0", timeout=10000)
    page.evaluate(
        "(ids) => window.__curio_reactFlow.setNodes((all) => all.map((n) => ({...n, selected: ids.includes(n.id)})))",
        node_ids,
    )
    expect(panel).to_contain_text(f"{len(node_ids)} node{'' if len(node_ids) == 1 else 's'} selected")
    panel.get_by_role("button", name="Next: shared context & outcomes").click()
    panel.get_by_role("button", name="Next: name & set").click()
    panel.get_by_test_id("scenario-define-save").click()
    expect(panel).to_be_hidden(timeout=10000)


def _park_on_the_canvas(page) -> None:
    """The pointer off the drawer and off every node, so no card shows hovered
    and nothing is outlined."""
    page.mouse.move(400, page.viewport_size["height"] - 30)


def test_the_in_project_tab_adds_renames_marks_and_runs_a_scenario(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scenarios In Project",
        username="scenarios_in_project_e2e",
        project_name=DATAFLOW,
        project_spec=_spec(),
    )
    require_owner_view(page)
    token, project_id = session["token"], session["project"]["id"]
    for node_id in (LOADER, SCALE, TOTAL):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
    set_canvas_zoom(page, ZOOM)
    _assert_beside_the_drawer(page, [LOADER, SCALE, TOTAL])

    # The total, selected on the canvas before the drawer opens.
    _select_with_shift_drag(page, TOTAL)
    assert page.evaluate(_SELECTED_JS) == [TOTAL], f"the Shift-drag selected {page.evaluate(_SELECTED_JS)}"

    drawer = open_in_project_tab(page)
    expect(drawer.get_by_role("button", name=re.compile(r"^In project"))).to_have_text("In project1")
    card = in_project_card(page, SCENARIO)
    expect(card).to_contain_text(NAME)
    expect(card).to_contain_text("1 node")
    assert page.evaluate(_FRAMED_JS, [SCENARIO, SCALE]), "the scenario's frame does not surround its node"
    assert not page.evaluate(_FRAMED_JS, [SCENARIO, TOTAL]), "the frame surrounds the total before it is added"

    # 1. Pointing at its card outlines its fixed context, the loader, alone.
    assert page.evaluate(_OUTLINED_JS, FIXED_CLASS) == []
    card.hover()
    page.wait_for_function(f"() => ({_OUTLINED_JS})('{FIXED_CLASS}').length > 0", timeout=10000)
    assert page.evaluate(_OUTLINED_JS, FIXED_CLASS) == [LOADER], page.evaluate(_OUTLINED_JS, FIXED_CLASS)
    drawer.get_by_placeholder("Search scenarios, projects…").hover()
    page.wait_for_function(f"() => ({_OUTLINED_JS})('{FIXED_CLASS}').length === 0", timeout=10000)

    # 2. Edit scenario: the panel starts from its node, selected on the
    # canvas. With the total selected too, the total joins the scenario and
    # its frame grows around it; edited again, it takes the total out.
    _edit_scenario_nodes(page, SCENARIO, [SCALE, TOTAL])
    page.wait_for_function(_FRAMED_JS, arg=[SCENARIO, TOTAL], timeout=10000)
    assert page.evaluate(_FRAMED_JS, [SCENARIO, SCALE])
    open_in_project_tab(page)
    expect(card).to_contain_text("2 nodes")
    _edit_scenario_nodes(page, SCENARIO, [SCALE])
    page.wait_for_function(f"(args) => !({_FRAMED_JS})(args)", arg=[SCENARIO, TOTAL], timeout=10000)
    assert page.evaluate(_FRAMED_JS, [SCENARIO, SCALE])
    open_in_project_tab(page)
    expect(card).to_contain_text("1 node")

    # 3. Its details change its name and its color; the card and the frame follow.
    details = open_scenario_details(page, SCENARIO)
    name = details.get_by_label("Scenario name")
    expect(name).to_have_value(NAME)
    name.fill(NEW_NAME)
    name.press("Enter")
    expect(details.get_by_role("heading", name=NEW_NAME)).to_be_visible(timeout=10000)
    details.get_by_label(f"Color of {NEW_NAME}").fill(NEW_COLOR)
    page.wait_for_function(
        f"([id, color]) => ({_FRAME_COLOR_JS})(id) === color", arg=[SCENARIO, _rgb(NEW_COLOR)], timeout=10000,
    )
    close_scenario_details(page)
    expect(card).to_contain_text(NEW_NAME)

    # 4. Run scenario runs the loader, which has not run, and its lever.
    sent = SandboxRuns(page, token, project_id)
    scenario_card_button(page, SCENARIO, "Run scenario").click()
    close_scenario_drawer(page)
    for node_id in (LOADER, SCALE):
        status = wait_for_node_settled(page, node_id, timeout_ms=120000)
        assert status == "done", f"{node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    wait_for_run_guard_released(page, timeout_ms=60000)
    executed = sent.stop()
    assert sorted(executed) == sorted([LOADER, SCALE]), (
        f"Run scenario sent {executed}: the loader it reads has not run, so it runs once, then its lever once"
    )

    # 5. The saved dataflow keeps the new name and color. Saved before each
    # frame, so the header shows the save whatever the autosave reached (#584).
    save_dataflow_and_settle_header(page)
    [saved] = _saved_scenarios(current_server, token, project_id)
    assert (saved["name"], saved["color"], saved["nodes"]) == (NEW_NAME, NEW_COLOR, [SCALE]), saved

    # The frames, before and after the total is added.
    open_in_project_tab(page)
    expect(card).to_contain_text("1 node")
    _park_on_the_canvas(page)
    save_workflow_test_screenshot(
        page, "scenarios-in-project-before-add", test_name=TEST_NAME, fit_reactflow=False, sweep_toasts=True,
    )
    _edit_scenario_nodes(page, SCENARIO, [SCALE, TOTAL])
    page.wait_for_function(_FRAMED_JS, arg=[SCENARIO, TOTAL], timeout=10000)
    save_dataflow_and_settle_header(page)
    [saved] = _saved_scenarios(current_server, token, project_id)
    assert (saved["name"], saved["color"], sorted(saved["nodes"])) == (NEW_NAME, NEW_COLOR, sorted([SCALE, TOTAL])), saved
    open_in_project_tab(page)
    expect(card).to_contain_text("2 nodes")
    _park_on_the_canvas(page)
    save_workflow_test_screenshot(
        page, "scenarios-in-project-after-add", test_name=TEST_NAME, fit_reactflow=False, sweep_toasts=True,
    )
