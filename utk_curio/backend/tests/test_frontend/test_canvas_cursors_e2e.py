"""Playwright E2E: everyone's pointer on the canvas, in two browsers.

The owner opens her dataflow and a watcher opens its link, each in a browser of
their own. Where one's pointer is on the canvas shows on the other's, at the
same point of the dataflow whatever either has panned or zoomed to, in their
color with their name, and nobody's own pointer is drawn. The watcher's reaches
the owner's tab too: the server keeps a watcher's awareness ``pointer``. A
pointer that rests fades and is drawn whole again when it moves; one that
leaves the canvas goes.

A watcher is in the dataflow's room on any stack with sign-in, so this needs no
``--collab``.
"""

from __future__ import annotations

import math
import re
import time
from typing import TYPE_CHECKING

import pytest

from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    _wait_for_reactflow_ready,
    node_locator,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    settled_viewport,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

FRAMES = "canvas-cursors"
OWNER, WATCHER = "cursor_owner_e2e", "cursor_watcher_e2e"
OWNER_NAME, WATCHER_NAME = "Cursor Owner", "Cursor Watcher"
NODE = "cursor-node"
TYPE = "curio.builtin/computation-analysis"
#: The view each tab starts from: the node on the left, bare canvas to its right.
START_VIEW = {"x": 160, "y": 140, "zoom": 0.6}
#: How far a drawn cursor's tip may be from the point the other tab's pointer is on.
NEAR_PX = 1.5
#: ``CURSOR_IDLE_MS`` in ``providers/collab/cursors.ts``, in seconds.
IDLE_S = 5.0
#: A faded cursor's opacity (``.cursor[data-idle]`` in ScenarioLayers.module.css).
FADED_OPACITY = 0.35


def _spec() -> dict:
    return {
        "name": "Pointed at",
        "dataflow": {
            "name": "Pointed at",
            "nodes": [{"id": NODE, "type": TYPE, "x": 0, "y": 0, "content": "x = 1\n"}],
            "edges": [],
        },
    }


_CANVAS = ".curio-canvas-drop-target .react-flow"

#: The canvas's box and React Flow's view.
_VIEW_JS = f"""() => {{
    const box = document.querySelector('{_CANVAS}').getBoundingClientRect();
    return {{left: box.left, top: box.top, ...window.__curio_reactFlow.getViewport()}};
}}"""

#: Every cursor the page draws: its tip, its name, whether it is faded.
_CURSORS_JS = """() => [...document.querySelectorAll('[data-canvas-cursor]')].map((el) => {
    const tip = el.getBoundingClientRect();
    const label = el.querySelector('span');
    return {
        client: el.getAttribute('data-canvas-cursor'),
        name: label ? label.textContent : null,
        x: tip.left,
        y: tip.top,
        idle: el.getAttribute('data-idle') === 'true',
        opacity: Number(getComputedStyle(el).opacity),
        color: getComputedStyle(el).color,
        label: label ? getComputedStyle(label).backgroundColor : null,
    };
})"""

#: Whether the point is on the bare canvas, where a press pans it.
_BARE_JS = """([x, y]) => {
    const el = document.elementFromPoint(x, y);
    return !!el && el.classList.contains('react-flow__pane');
}"""

#: Whether the point is on the canvas, a node's body included.
_ON_CANVAS_JS = f"""([x, y]) => {{
    const el = document.elementFromPoint(x, y);
    return !!el && !!el.closest('{_CANVAS}');
}}"""


class _Room:
    """The owner's dataflow, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.project_id = None

    def person(self, username: str, name: str, *, owns: bool = False):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768})
        self.contexts.append(context)
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Pointed at", "project_spec": _spec()} if owns else {}),
        )
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def open(self, page) -> None:
        """Open the dataflow, bound to its doc, at START_VIEW."""
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        node_locator(page, NODE).wait_for(timeout=30000)
        try:
            page.wait_for_function(
                """() => !!document.querySelector('style#curio-remote-cursors')""", timeout=30000,
            )
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError("the canvas never bound to the dataflow's doc") from exc
        _show_view(page, START_VIEW)

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


def _same_view(a: dict, b: dict) -> bool:
    return all(abs(a[key] - b[key]) < 0.01 for key in ("x", "y", "zoom"))


def _show_view(page, view: dict) -> None:
    """Show *view* and keep it: the canvas's own fit on opening can land after it."""
    _wait_for_reactflow_ready(page)
    shown = None
    for _ in range(8):
        page.evaluate("(view) => window.__curio_reactFlow.setViewport(view)", view)
        shown = settled_viewport(page)
        if _same_view(shown, view):
            page.wait_for_timeout(1000)
            shown = settled_viewport(page)
            if _same_view(shown, view):
                return
    raise AssertionError(f"the canvas did not keep the view {view}: it shows {shown}")


def _view(page) -> dict:
    """The page's view once its moves have landed, and its canvas's corner."""
    settled_viewport(page)
    return page.evaluate(_VIEW_JS)


def _flow_point(page, client: tuple[float, float]) -> tuple[float, float]:
    """The point of the dataflow a pointer at *client* is on, by the page's view."""
    view = _view(page)
    return (
        (client[0] - view["left"] - view["x"]) / view["zoom"],
        (client[1] - view["top"] - view["y"]) / view["zoom"],
    )


def _drawn_at(page, flow: tuple[float, float]) -> tuple[float, float]:
    """Where the page draws the point *flow* of the dataflow, in its window."""
    view = _view(page)
    return (flow[0] * view["zoom"] + view["x"] + view["left"], flow[1] * view["zoom"] + view["y"] + view["top"])


def _bare_point(page, *, right: float, down: float) -> tuple[float, float]:
    """A point of the bare canvas, *right* of the node's right edge and *down* from its top."""
    box = node_locator(page, NODE).bounding_box()
    point = (box["x"] + box["width"] + right, box["y"] + down)
    assert page.evaluate(_BARE_JS, list(point)), f"{point} is not on the bare canvas"
    return point


def _cursors(page, name: str | None = None) -> list[dict]:
    return [c for c in page.evaluate(_CURSORS_JS) if name is None or c["name"] == name]


def _point_at(page, point: tuple[float, float]) -> None:
    """Move the page's pointer to *point*, on its canvas."""
    assert page.evaluate(_ON_CANVAS_JS, list(point)), f"{point} is not on the canvas"
    page.mouse.move(*point, steps=4)


def _cursor_lands(page, name: str, want: tuple[float, float], *, what: str, timeout_s: float = 15) -> dict:
    """*name*'s one cursor on *page*, once its tip is at *want*."""
    deadline = time.monotonic() + timeout_s
    seen: list[dict] = []
    while time.monotonic() < deadline:
        seen = _cursors(page, name)
        if len(seen) == 1 and math.hypot(seen[0]["x"] - want[0], seen[0]["y"] - want[1]) <= NEAR_PX:
            return seen[0]
        page.wait_for_timeout(100)
    raise AssertionError(
        f"{what} should be drawn at {want[0]:.1f}, {want[1]:.1f}; the page draws {seen or 'no cursor of theirs'}"
    )


def _cursor_goes(page, name: str, *, what: str, timeout_s: float = 15) -> None:
    deadline = time.monotonic() + timeout_s
    seen = _cursors(page, name)
    while seen and time.monotonic() < deadline:
        page.wait_for_timeout(100)
        seen = _cursors(page, name)
    assert not seen, f"{what} is still drawn: {seen}"


def _cursor_fades(page, name: str, *, what: str, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    seen: list[dict] = []
    while time.monotonic() < deadline:
        seen = _cursors(page, name)
        # Its fade's end, which a frame of it waits for.
        if len(seen) == 1 and seen[0]["idle"] and seen[0]["opacity"] <= FADED_OPACITY + 0.001:
            return seen[0]
        page.wait_for_timeout(100)
    raise AssertionError(f"{what} never faded: {seen or 'no cursor of theirs'}")


def _cursor_whole(page, name: str, *, what: str, timeout_s: float = 15) -> dict:
    deadline = time.monotonic() + timeout_s
    seen: list[dict] = []
    while time.monotonic() < deadline:
        seen = _cursors(page, name)
        if len(seen) == 1 and not seen[0]["idle"] and seen[0]["opacity"] == pytest.approx(1):
            return seen[0]
        page.wait_for_timeout(100)
    raise AssertionError(f"{what} is not drawn whole: {seen or 'no cursor of theirs'}")


def _pan_and_zoom(page, press: tuple[float, float], *, by: tuple[float, float], wheel: float) -> tuple[float, float]:
    """Drag the bare canvas from *press* by *by*, then turn the wheel there, as a
    person pans and zooms. Where the pointer rests after, which the view must
    have moved under."""
    before = _view(page)
    assert page.evaluate(_BARE_JS, list(press)), f"{press} is not on the bare canvas"
    page.mouse.move(*press, steps=2)
    page.mouse.down()
    rest = (press[0] + by[0], press[1] + by[1])
    page.mouse.move(*rest, steps=10)
    page.mouse.up()
    page.mouse.wheel(0, wheel)
    after = _view(page)
    assert after["zoom"] != pytest.approx(before["zoom"], abs=0.01), f"the wheel did not zoom: {before} then {after}"
    assert (after["x"], after["y"]) != pytest.approx((before["x"], before["y"]), abs=1), (
        f"the drag did not pan: {before} then {after}"
    )
    return rest


def _editor_color(page, client: str) -> str | None:
    """The color the page gives client *client*'s cursor in the code editors."""
    rules = page.evaluate("() => document.querySelector('style#curio-remote-cursors').textContent")
    found = re.search(rf"\.yRemoteSelectionHead-{client}::after \{{[^}}]*background: #([0-9a-f]{{6}})", rules)
    if not found:
        return None
    red, green, blue = (int(found.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgb({red}, {green}, {blue})"


def _frame(page, name: str, cursor: dict, failures: list[str]) -> None:
    """A close-up of *cursor* and its name. A missing or moved frame is told at
    the test's end, so every check around it still runs."""
    clip = {"x": math.floor(cursor["x"]) - 24, "y": math.floor(cursor["y"]) - 20, "width": 240, "height": 72}
    try:
        save_workflow_test_screenshot(
            page, FRAMES, test_name=name, fit_reactflow=False, clip_rect=clip,
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO, closeup=True,
        )
    except AssertionError as error:
        failures.append(f"{name}: {error}")


def test_a_watchers_pointer_shows_on_the_owners_canvas_at_its_point_of_the_dataflow_as_either_pans_and_zooms(room):
    frames_failed: list[str] = []
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    room.open(owner)

    # Alone on the canvas, no pointer is drawn: one's own never is.
    _point_at(owner, _bare_point(owner, right=200, down=100))
    owner.wait_for_timeout(1000)
    assert _cursors(owner) == [], f"a canvas with nobody else on it draws a cursor: {_cursors(owner)}"

    watcher = room.person(WATCHER, WATCHER_NAME)
    room.open(watcher)

    # The watcher's pointer reaches the owner's tab: on the owner's canvas at
    # the same point of the dataflow, in the watcher's color with the
    # watcher's name.
    at = _bare_point(watcher, right=220, down=90)
    _point_at(watcher, at)
    drawn = _cursor_lands(owner, WATCHER_NAME, _drawn_at(owner, _flow_point(watcher, at)),
                          what="the watcher's pointer, on the owner's canvas,")
    _frame(owner, "watchers-pointer", drawn, frames_failed)
    assert not _cursors(owner, WATCHER_NAME)[0]["idle"], "the watcher's cursor faded before its frame was taken"
    assert drawn["opacity"] == pytest.approx(1), f"a pointer that just moved is drawn faded: {drawn}"
    assert drawn["label"] == drawn["color"], f"the name is not in the cursor's color: {drawn}"
    editor_color = _editor_color(owner, drawn["client"])
    assert drawn["color"] == editor_color, (
        f"the cursor's color {drawn['color']} is not the watcher's color in the code editors, {editor_color}"
    )

    # The watcher pans and zooms, then moves on: drawn where it is on the dataflow.
    _pan_and_zoom(watcher, _bare_point(watcher, right=380, down=260), by=(-200, -120), wheel=-300)
    at = (900, 430)
    _point_at(watcher, at)
    flow = _flow_point(watcher, at)
    _cursor_lands(owner, WATCHER_NAME, _drawn_at(owner, flow),
                  what="after the watcher panned and zoomed, the watcher's pointer")

    # The owner pans and zooms while the watcher's pointer rests: it stays on
    # its point of the dataflow, somewhere else on the owner's screen now.
    before = _drawn_at(owner, flow)
    owner_rest = _pan_and_zoom(owner, _bare_point(owner, right=150, down=320), by=(160, 90), wheel=240)
    after = _drawn_at(owner, flow)
    assert math.hypot(after[0] - before[0], after[1] - before[1]) > 50, (
        f"the owner's pan and zoom left the watcher's point where it was drawn: {before} then {after}"
    )
    _cursor_lands(owner, WATCHER_NAME, after,
                  what="after the owner panned and zoomed, the watcher's resting pointer")

    # The owner's pointer rests where the pan left it, which the watcher's
    # canvas draws; neither tab draws its own.
    _cursor_lands(watcher, OWNER_NAME, _drawn_at(watcher, _flow_point(owner, owner_rest)),
                  what="the owner's pointer, resting where the owner's pan and zoom left it")
    assert _cursors(owner, OWNER_NAME) == [], "the owner's tab draws the owner's own pointer"
    assert _cursors(watcher, WATCHER_NAME) == [], "the watcher's tab draws the watcher's own pointer"

    assert not frames_failed, "\n".join(frames_failed)


def test_a_pointer_that_leaves_the_canvas_goes_from_the_other_tab(room):
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    watcher = room.person(WATCHER, WATCHER_NAME)
    room.open(owner)
    room.open(watcher)

    at = _bare_point(owner, right=200, down=100)
    _point_at(owner, at)
    _cursor_lands(watcher, OWNER_NAME, _drawn_at(watcher, _flow_point(owner, at)), what="the owner's pointer")

    # Onto the top bar's File menu: off the canvas.
    menu = owner.locator('[data-testid="file-menu-btn"]').first.bounding_box()
    owner.mouse.move(menu["x"] + menu["width"] / 2, menu["y"] + menu["height"] / 2, steps=4)
    _cursor_goes(watcher, OWNER_NAME, what="the owner's pointer, moved off the canvas onto the top bar,")

    # Back on the canvas, it is drawn again.
    _point_at(owner, at)
    _cursor_lands(watcher, OWNER_NAME, _drawn_at(watcher, _flow_point(owner, at)),
                  what="the owner's pointer, back on the canvas,")


def test_a_resting_pointer_fades_in_the_other_tab_and_is_drawn_whole_when_it_moves(room):
    frames_failed: list[str] = []
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    watcher = room.person(WATCHER, WATCHER_NAME)
    room.open(owner)
    room.open(watcher)

    at = _bare_point(owner, right=200, down=100)
    _point_at(owner, at)
    moved = time.monotonic()
    drawn = _cursor_lands(watcher, OWNER_NAME, _drawn_at(watcher, _flow_point(owner, at)), what="the owner's pointer")
    assert not drawn["idle"] and drawn["opacity"] == pytest.approx(1), f"a pointer that just moved is drawn faded: {drawn}"

    faded = _cursor_fades(watcher, OWNER_NAME, what="the owner's resting pointer", timeout_s=IDLE_S + 15)
    rested = time.monotonic() - moved
    assert rested >= IDLE_S - 1, f"the cursor faded {rested:.1f} s after the pointer stopped, before resting {IDLE_S} s"
    _frame(watcher, "resting-pointer", faded, frames_failed)

    # It moves on: drawn whole again, where it went.
    again = (at[0] + 60, at[1] + 40)
    _point_at(owner, again)
    _cursor_lands(watcher, OWNER_NAME, _drawn_at(watcher, _flow_point(owner, again)),
                  what="the owner's pointer, moved on after resting")
    _cursor_whole(watcher, OWNER_NAME, what="the owner's pointer, moved on after resting,")

    assert not frames_failed, "\n".join(frames_failed)
