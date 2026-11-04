"""Playwright E2E: two tabs on one dataflow keep its scenario sets, a chip's
size and a node's one name in step, and a reload keeps them.

The owner and an invited editor open one dataflow: a scenario in a set, and a
node of its shared context folded to its chip. In the owner's tab the set is
renamed with its pencil in the Scenario drawer's In project tab, the chip is
resized from its corner, and the scenario's node is renamed from its header.
Each change reaches the editor's canvas, and the editor's reload opens the
dataflow with all three.

Every stack with sign-in serves this: there is no switch for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_node_rename_persists_e2e import _rename
from .utils import (
    api_json,
    close_after_routes,
    close_scenario_drawer,
    node_locator,
    open_in_project_tab,
    require_project_page,
    require_user_auth,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER, OWNER_NAME = "sets_owner_e2e", "Sets Owner"
EDITOR, EDITOR_NAME = "sets_editor_e2e", "Sets Editor"
CHIP, SHADE = "sets-heights", "sets-shade"
SET, SET_NAME, NEW_SET_NAME = "set-tall", "Towers", "Towers, renamed"
NEW_TITLE = "Shade at noon"


def _spec() -> dict:
    """A heights node folded to its chip, the shared context of one scenario,
    whose node computes the shade, in the set Towers."""

    def node(node_id, x, **extra):
        return {
            "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": 0,
            "content": "return 1\n", "in": "DEFAULT", "out": "DEFAULT", "goal": "",
            "metadata": {"keywords": []}, **extra,
        }

    return {
        "name": "Two tabs, one set",
        "dataflow": {
            "name": "Two tabs, one set",
            "nodes": [node(CHIP, 0, title="Heights", minimized=True), node(SHADE, 700, title="Shade")],
            "edges": [{"id": f"e-{CHIP}-{SHADE}", "source": CHIP, "target": SHADE,
                       "sourceHandle": "out", "targetHandle": "in"}],
            "scenarios": [{"id": "tall", "name": "Tall", "color": "#4477aa", "nodes": [SHADE],
                           "set": SET, "context": [CHIP], "outcomes": []}],
            "scenarioSets": [{"id": SET, "name": SET_NAME}],
        },
    }


def _open_as(page, base: str, project_id: str, role: str) -> None:
    """Open the dataflow's link and wait until its room names this tab's role,
    with the canvas bound to the dataflow's doc."""
    page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
    node_locator(page, SHADE).wait_for(timeout=30000)
    try:
        page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
        page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the dataflow's room never named this tab its {role}, with its doc bound") from exc


def _node_data(page, node_id: str) -> dict:
    """The chip's size and the name the canvas node itself carries."""
    return page.evaluate(
        """(nodeId) => {
            const rf = window.__curio_reactFlow;
            const node = rf ? rf.getNodes().find((n) => n.id === nodeId) : null;
            const data = (node && node.data) || {};
            return { width: data.minimizedWidth ?? null, height: data.minimizedHeight ?? null, title: data.title ?? null };
        }""",
        node_id,
    )


def _wait_for_node_data(page, node_id: str, want: dict, *, timeout: float = 20000) -> None:
    try:
        page.wait_for_function(
            """([nodeId, want]) => {
                const rf = window.__curio_reactFlow;
                const node = rf ? rf.getNodes().find((n) => n.id === nodeId) : null;
                const data = (node && node.data) || {};
                return Object.entries(want).every(([key, value]) => data[key] === value);
            }""",
            arg=[node_id, want],
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"node {node_id} never held {want}: it holds {_node_data(page, node_id)}") from exc


def _resize_chip(page, node_id: str, dx: int, dy: int) -> None:
    """Drag the chip's bottom-right corner, as a person resizes it."""
    handle = page.locator(f'[id="{node_id}resizer"]')
    handle.wait_for(state="visible", timeout=15000)
    box = handle.bounding_box()
    assert box, "the chip has no corner to drag"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=8)
    page.mouse.up()


def _rename_set(page, name: str, new_name: str) -> None:
    """Rename the set with its pencil in the In project tab."""
    drawer = open_in_project_tab(page)
    drawer.get_by_role("button", name=f"Rename {name}", exact=True).click()
    field = drawer.get_by_label("Scenario set name", exact=True)
    field.fill(new_name)
    field.press("Enter")
    expect(drawer.locator("section[aria-labelledby] h3").first).to_have_text(new_name, timeout=10000)
    close_scenario_drawer(page)


def _expect_set_name(page, name: str) -> None:
    drawer = open_in_project_tab(page)
    expect(drawer.locator("section[aria-labelledby] h3").first).to_have_text(name, timeout=20000)
    close_scenario_drawer(page)


def test_a_set_renamed_a_chip_resized_and_a_node_renamed_in_one_tab_reach_the_other_and_survive_its_reload(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport)
    editor_ctx = browser.new_context(viewport=viewport)
    try:
        owner, editor = owner_ctx.new_page(), editor_ctx.new_page()
        stubbed = stub_db_login(
            owner, frontend_url=base, backend_url=current_server, username=OWNER, name=OWNER_NAME,
            project_name="Two tabs, one set", project_spec=_spec(),
        )
        project_id, token = stubbed["project"]["id"], stubbed["token"]
        stub_db_login(editor, frontend_url=base, backend_url=current_server, username=EDITOR, name=EDITOR_NAME)
        api_json(f"{current_server}/api/projects/{project_id}/editors", token, method="POST",
                 payload={"username": EDITOR})
        _open_as(owner, base, project_id, "owner")
        _open_as(editor, base, project_id, "editor")

        _rename_set(owner, SET_NAME, NEW_SET_NAME)
        before = _node_data(owner, CHIP)
        _resize_chip(owner, CHIP, 90, 40)
        resized = _node_data(owner, CHIP)
        assert isinstance(resized["width"], (int, float)) and isinstance(resized["height"], (int, float)), (
            f"the chip kept no size of its own after its corner was dragged: {before} -> {resized}"
        )
        _rename(owner, SHADE, NEW_TITLE)

        # Each change reaches the editor's canvas.
        _wait_for_node_data(editor, CHIP, {"minimizedWidth": resized["width"], "minimizedHeight": resized["height"]})
        _wait_for_node_data(editor, SHADE, {"title": NEW_TITLE})
        _expect_set_name(editor, NEW_SET_NAME)

        # And a reload opens the dataflow with all three.
        editor.reload()
        node_locator(editor, SHADE).wait_for(timeout=45000)
        _wait_for_node_data(editor, CHIP, {"minimizedWidth": resized["width"], "minimizedHeight": resized["height"]})
        _wait_for_node_data(editor, SHADE, {"title": NEW_TITLE})
        _expect_set_name(editor, NEW_SET_NAME)
    finally:
        close_after_routes(owner_ctx)
        close_after_routes(editor_ctx)
