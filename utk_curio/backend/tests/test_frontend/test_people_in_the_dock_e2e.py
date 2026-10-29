"""Playwright E2E: who is here, in the canvas's dock.

Everyone in a dataflow's room is in the dock centered at the top of the canvas,
beside the canvas agents: each other person as a chip of an agent's shape,
their initials in their color, then an Activity button at the row's end, which
lists who came and who went. A chip's tooltip names the person, their role and
the node they are editing, and a click moves the view to where they point, when
they point somewhere on the canvas. Your own chip is not in the row.

The owner, with a canvas agent, sees an editor she invited and a watcher; the
editor sees the owner and the watcher; the watcher sees both, under the
read-only banner. Every stack serves this: there is no switch for it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    api_json,
    hover_until_tooltip_says,
    node_locator,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    settled_viewport,
    stub_db_login,
    tooltip_close_up,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FRAMES = "people-in-the-dock"
NODE = "dock-trees"
LABEL = "Street trees"
OWNER, EDITOR, WATCHER = "dock_owner_e2e", "dock_editor_e2e", "dock_watcher_e2e"
AGENT = "agent.curio.dataflow-builder@1"

#: The dock, the people in it, and a person's chip.
DOCK = '[role="toolbar"][aria-label="Canvas agents"]'
PEOPLE = f'{DOCK} [role="group"][aria-label="People here"]'
CHIP = f"{PEOPLE} button[data-collab-participant]"
ACTIVITY = f'{PEOPLE} button[aria-label="Activity"]'
ACTIVITY_LIST = '[role="region"][aria-label="Activity"]'
#: Where the editor says they point on the canvas, in flow coordinates.
POINT = (900, 640)


def _spec() -> dict:
    return {
        "name": "Who is here",
        "dataflow": {
            "name": "Who is here",
            "nodes": [{
                "id": NODE, "type": "curio.builtin/computation-analysis", "x": 0, "y": 0,
                "content": "trees = 12\n", "metadata": {"packageTemplateLabel": LABEL},
            }],
            "edges": [],
        },
    }


class _Room:
    """The owner's dataflow, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.tokens: dict[str, str] = {}
        self.project_id = None

    def person(self, username: str, name: str, *, owns: bool = False):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768})
        self.contexts.append(context)
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Who is here", "project_spec": _spec()} if owns else {}),
        )
        self.tokens[username] = login["token"]
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def invite(self, username: str) -> None:
        api_json(f"{self.backend}/api/projects/{self.project_id}/editors", self.tokens[OWNER],
                 method="POST", payload={"username": username})

    def attach_agent(self) -> None:
        """A canvas agent on the owner's dataflow, before she opens it."""
        base = f"{self.backend}/api/agents/projects/{self.project_id}"
        api_json(f"{base}/install", self.tokens[OWNER], method="POST", payload={"coord": AGENT})
        api_json(f"{base}/attachments", self.tokens[OWNER], method="POST",
                 payload={"coord": AGENT, "target": {"kind": "canvas"}})

    def open(self, page, role: str) -> None:
        """Open the dataflow's link, and wait until its room names this tab
        *role* and the canvas is bound to the dataflow's doc."""
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        node_locator(page, NODE).wait_for(timeout=30000)
        try:
            page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
            page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError(f"the dataflow's room never named this tab its {role}, with its doc bound") from exc

    def close(self) -> None:
        for context in self.contexts:
            context.close()


@pytest.fixture()
def room(app_frontend: "FrontendPage", current_server: str, browser):
    require_project_page()
    require_user_auth()
    opened = _Room(app_frontend.base_url, current_server, browser)
    try:
        yield opened
    finally:
        opened.close()


def _people(page) -> list[dict]:
    return page.locator(CHIP).evaluate_all(
        """(chips) => chips.map((chip) => ({
            role: chip.getAttribute('data-collab-role'),
            initials: chip.textContent,
            label: chip.getAttribute('aria-label'),
        }))"""
    )


def _wait_for_people(page, roles: list[str], *, what: str, timeout: float = 30000) -> list[dict]:
    """Wait until *page*'s dock shows a chip for each of *roles*, in the row's
    order, and no other."""
    deadline = time.time() + timeout / 1000
    people = _people(page)
    while [person["role"] for person in people] != roles and time.time() < deadline:
        page.wait_for_timeout(200)
        people = _people(page)
    assert [person["role"] for person in people] == roles, f"{what} shows {people}, not {roles}"
    return people


# Whether the middle of an element is the element: nothing is over it there.
_ON_TOP_JS = """(el) => {
    const r = el.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return !!hit && (hit === el || el.contains(hit));
}"""

# Whether this tab's awareness holds someone pointing at [x, y].
_POINTS_AT_JS = """([x, y]) => {
    const awareness = window.__curio_awareness;
    if (!awareness) return false;
    for (const state of awareness.getStates().values()) {
        const at = state && state.pointer;
        if (at && at.x === x && at.y === y) return true;
    }
    return false;
}"""

# Whether nobody else in this tab's awareness points anywhere.
_POINTS_NOWHERE_JS = """() => {
    const awareness = window.__curio_awareness;
    if (!awareness) return false;
    for (const [id, state] of awareness.getStates()) {
        if (id !== awareness.clientID && state && state.pointer) return false;
    }
    return true;
}"""

# The point of the canvas at the middle of its pane, in flow coordinates.
_FLOW_MIDDLE_JS = """() => {
    const box = document.querySelector('.react-flow').getBoundingClientRect();
    const view = window.__curio_reactFlow.getViewport();
    return [(box.width / 2 - view.x) / view.zoom, (box.height / 2 - view.y) / view.zoom];
}"""


def _union(*boxes: dict, margin: int = 8) -> dict:
    """The box holding *boxes*, *margin* pixels around them, in whole pixels."""
    left = min(box["x"] for box in boxes) - margin
    top = min(box["y"] for box in boxes) - margin
    right = max(box["x"] + box["width"] for box in boxes) + margin
    bottom = max(box["y"] + box["height"] for box in boxes) + margin
    return {"x": int(max(0, left)), "y": int(max(0, top)),
            "width": int(right - max(0, left)) + 1, "height": int(bottom - max(0, top)) + 1}


def _quiet_pointers(*pages) -> None:
    """Each page's pointer at the top bar's corner, off the canvas: no hover
    changes a frame, and no pointer of theirs is drawn on another's canvas."""
    for page in pages:
        page.mouse.move(2, 2)
    for page in pages:
        page.wait_for_timeout(300)


def test_the_dock_shows_who_else_is_here_with_their_role_the_node_they_edit_and_the_activity(room):
    owner = room.person(OWNER, "Dock Owner", owns=True)
    room.attach_agent()
    room.open(owner, "owner")
    # Alone, the owner's dock is her agent's: no people, no Activity.
    owner.locator(DOCK).wait_for(timeout=30000)
    assert owner.locator(PEOPLE).count() == 0, "the owner's dock shows people while nobody else is here"

    editor = room.person(EDITOR, "Dock Editor")
    room.invite(EDITOR)
    room.open(editor, "editor")
    watcher = room.person(WATCHER, "Dock Watcher")
    room.open(watcher, "watcher")

    # Each sees everyone else, by name, with their role, and never themselves.
    people = _wait_for_people(owner, ["editor", "watcher"], what="the owner's dock")
    assert [person["initials"] for person in people] == ["DE", "DW"], people
    assert [person["label"] for person in people] == ["Dock Editor (editor)", "Dock Watcher (watcher)"], people
    _wait_for_people(editor, ["owner", "watcher"], what="the editor's dock")
    _wait_for_people(watcher, ["editor", "owner"], what="the watcher's dock")
    # The owner's agent keeps its chip, before the people.
    named = owner.locator(f"{DOCK} button").evaluate_all(
        "(buttons) => buttons.map((b) => b.getAttribute('aria-label')).filter((n) => !n.startsWith('Detach'))"
    )
    assert named[0].startswith("Open chat with"), named
    assert named[1:] == ["Dock Editor (editor)", "Dock Watcher (watcher)", "Activity"], named

    # A watcher's dock sits under the read-only banner, nothing over it.
    banner = watcher.get_by_test_id("shared-view-banner")
    banner.wait_for(timeout=15000)
    banner_box, dock_box = banner.bounding_box(), watcher.locator(DOCK).bounding_box()
    assert banner_box["y"] + banner_box["height"] <= dock_box["y"], (
        f"the watcher's dock {dock_box} is under the banner {banner_box}"
    )
    for chip in watcher.locator(CHIP).all():
        assert chip.evaluate(_ON_TOP_JS), f"something covers {chip.get_attribute('aria-label')} on the watcher's dock"

    # The editor edits the node's code: the owner's chip of the editor says so.
    node_locator(editor, NODE).locator(".monaco-editor .view-lines").first.click()
    expected = f"Dock Editor (editor), editing {LABEL}"
    try:
        owner.locator(f'{CHIP}[aria-label="{expected}"]').wait_for(timeout=15000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the owner's chip of the editor never said {expected!r}: {_people(owner)}") from exc

    # The frames: the owner's row with her agent and the people, the tooltip
    # of the editor's chip, and the room's Activity. Moving the editor's
    # pointer away keeps the focus, and so the node they are editing.
    _quiet_pointers(owner, editor, watcher)
    save_workflow_test_screenshot(owner, FRAMES, test_name="owners-row", clip_selector=DOCK, fit_reactflow=False)
    editor_chip = f'{CHIP}[data-collab-role="editor"]'
    tip = hover_until_tooltip_says(owner, editor_chip, "the editor's chip", [expected])
    save_workflow_test_screenshot(
        owner, FRAMES, test_name="chip-tooltip",
        fit_reactflow=False, keep_tooltip=True, clip_rect=tooltip_close_up(owner, tip),
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO, closeup=True,
    )
    owner.locator(ACTIVITY).click()
    activity = owner.locator(ACTIVITY_LIST)
    activity.wait_for(timeout=10000)
    lines = activity.locator("li").all_inner_texts()
    assert lines == ["Dock Watcher joined (watcher)", "Dock Editor joined (editor)", "Dock Owner joined (owner)"], (
        f"the owner's Activity lists {lines}"
    )
    assert activity.locator("button").count() == 0, "the Activity list holds a vote"
    _quiet_pointers(owner)
    save_workflow_test_screenshot(
        owner, FRAMES, test_name="activity",
        clip_rect=_union(owner.locator(DOCK).bounding_box(), activity.bounding_box()), fit_reactflow=False,
    )
    owner.keyboard.press("Escape")
    activity.wait_for(state="detached", timeout=10000)

    # The watcher's dock, under the banner.
    _quiet_pointers(owner, editor, watcher)
    save_workflow_test_screenshot(
        watcher, FRAMES, test_name="watchers-row",
        clip_rect=_union(banner.bounding_box(), watcher.locator(DOCK).bounding_box()), fit_reactflow=False,
    )


def test_a_click_on_a_persons_chip_moves_the_view_to_where_they_point(room):
    owner = room.person(OWNER, "Dock Owner", owns=True)
    room.open(owner, "owner")
    editor = room.person(EDITOR, "Dock Editor")
    room.invite(EDITOR)
    room.open(editor, "editor")
    _wait_for_people(owner, ["editor"], what="the owner's dock")
    chip = owner.locator(f'{CHIP}[data-collab-role="editor"]')

    # The editor points nowhere on the canvas: a click moves nothing.
    editor.evaluate("() => window.__curio_awareness.setLocalStateField('pointer', null)")
    owner.wait_for_function(_POINTS_NOWHERE_JS, timeout=15000)
    before = settled_viewport(owner)
    chip.click()
    owner.wait_for_timeout(600)
    assert settled_viewport(owner) == before, "a click on the chip of someone pointing nowhere moved the view"

    # They point at a place far off the owner's view: a click centers it, at
    # the zoom the view has.
    editor.evaluate(
        "([x, y]) => window.__curio_awareness.setLocalStateField('pointer', {x, y, t: Date.now()})", list(POINT),
    )
    owner.wait_for_function(_POINTS_AT_JS, arg=list(POINT), timeout=15000)
    chip.click()
    after = settled_viewport(owner)
    assert after["zoom"] == pytest.approx(before["zoom"]), f"the move changed the zoom: {before} -> {after}"
    middle = owner.evaluate(_FLOW_MIDDLE_JS)
    assert middle == pytest.approx(list(POINT), abs=1), (
        f"the view's middle is at {middle} after the click, not where the editor points, {POINT}"
    )
