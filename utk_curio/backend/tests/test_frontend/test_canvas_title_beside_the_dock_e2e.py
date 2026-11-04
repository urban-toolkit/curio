"""Playwright E2E: the canvas title stops before the agents' dock.

The title sits at the top left of the canvas and the dock, with the dataflow's
goal and the canvas agents, at the top middle, on the same row. A long name was
drawn over the dock, its Goal label and the start of the goal. Now the title is
cut short with an ellipsis where the dock starts, as a node's title is cut in
its header, and its tooltip gives the whole name. A short title, and a long one
with no dock beside it, are shown whole as before.

The dataflow's row and its spec carry the same name here, so the canvas shows
it on every build, before and after a create named the dataflow as its row.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_title_beside_the_dock_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    _wait_for_reactflow_ready,
    hover_until_tooltip_says,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    tooltip_close_up,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LONG_NAME = "Heat islands in Chicago, ranked by tree canopy and summer surface temperature"
SHORT_NAME = "Heat islands"
TITLE = "[data-curio-canvas-title] h1"
DOCK = '[role="toolbar"][aria-label="Canvas agents"]'
AGENT = "agent.curio.dataflow-builder@1"
FRAMES = "canvas-title-beside-the-dock"

# The title's box, the dock's and whether the title's text is cut, as the page
# lays them out now.
_LAYOUT_JS = """() => {
    const title = document.querySelector('[data-curio-canvas-title] h1');
    const dock = document.querySelector('[role="toolbar"][aria-label="Canvas agents"]');
    const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {left: r.left, right: r.right, top: r.top, bottom: r.bottom};
    };
    return {
        title: box(title),
        dock: box(dock),
        text: title ? title.textContent : null,
        cut: title ? title.scrollWidth > title.clientWidth : null,
        scrollWidth: title ? title.scrollWidth : null,
        clientWidth: title ? title.clientWidth : null,
        dockLeft: getComputedStyle(document.documentElement).getPropertyValue('--curio-canvas-dock-left'),
    };
}"""


def _spec(name: str) -> dict:
    """One node, named as its project, so the canvas loads a dataflow."""
    return {
        "dataflow": {
            "name": name,
            "task": "",
            "nodes": [
                {
                    "id": "title-dock-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 360,
                    "content": "return 1",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _open(page, app_frontend, current_server, *, username: str, name: str) -> None:
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Title Beside The Dock",
        username=username,
        project_name=name,
        project_spec=_spec(name),
    )
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    expect(page.locator(TITLE)).to_have_text(name, timeout=30000)


def _attach_an_agent(page, current_server: str, name: str) -> None:
    """An agent attached to the canvas, which brings the dock and its goal
    field, over HTTP as the dataflow-goal walkthrough attaches one; then the
    page again, whose dock is drawn from the attachments it reads, once it
    shows the dataflow *name*."""
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the test cannot attach an agent"
    project_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    base = f"{current_server}/api/agents/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    installed = page.request.post(f"{base}/install", headers=headers, data={"coord": AGENT})
    assert installed.ok, f"install failed: {installed.status} {installed.text()[:200]}"
    attached = page.request.post(
        f"{base}/attachments", headers=headers, data={"coord": AGENT, "target": {"kind": "canvas"}},
    )
    assert attached.ok, f"attach failed: {attached.status} {attached.text()[:200]}"
    page.reload()
    require_owner_view(page)
    expect(page.locator(DOCK)).to_be_visible(timeout=30000)
    expect(page.get_by_label("Dataflow goal")).to_be_visible(timeout=30000)
    expect(page.locator(TITLE)).to_have_text(name, timeout=30000)


def _frame(page, name: str, failures: list[str], **capture) -> None:
    """One of the test's close-ups. A missing or moved frame is told at the
    test's end, so every check after it still runs."""
    try:
        save_workflow_test_screenshot(
            page, FRAMES, test_name=name, fit_reactflow=False,
            pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO,
            closeup=True, **capture,
        )
    except AssertionError as error:
        failures.append(f"{name}: {error}")


def _row(page) -> dict:
    """The box around the title and the dock, a few pixels out."""
    boxes = [page.locator(TITLE).bounding_box(), page.locator(DOCK).bounding_box()]
    left = min(box["x"] for box in boxes) - 8
    top = min(box["y"] for box in boxes) - 6
    right = max(box["x"] + box["width"] for box in boxes) + 8
    bottom = max(box["y"] + box["height"] for box in boxes) + 6
    return {"x": int(max(0, left)), "y": int(max(0, top)),
            "width": int(right - max(0, left)) + 1, "height": int(bottom - max(0, top)) + 1}


def _title_ends_before_the_dock(page, what: str) -> dict:
    """Wait until the title's right edge is at or left of the dock's left
    edge, and return the layout; the failure gives both boxes."""
    try:
        page.wait_for_function(
            """() => {
                const title = document.querySelector('[data-curio-canvas-title] h1');
                const dock = document.querySelector('[role="toolbar"][aria-label="Canvas agents"]');
                if (!title || !dock) return false;
                return title.getBoundingClientRect().right <= dock.getBoundingClientRect().left + 0.5;
            }""",
            timeout=10000,
        )
    except Exception:  # noqa: BLE001 - the failure says what the page laid out
        layout = page.evaluate(_LAYOUT_JS)
        raise AssertionError(
            f"{what}: the canvas title runs into the agents' dock. Title {layout['title']}, "
            f"dock {layout['dock']}, title cut short: {layout['cut']} "
            f"({layout['scrollWidth']} wide, {layout['clientWidth']} shown), "
            f"--curio-canvas-dock-left {layout['dockLeft']!r}"
        ) from None
    return page.evaluate(_LAYOUT_JS)


def test_a_long_title_stops_before_the_agents_dock_and_shows_whole_on_hover(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    frames_failed: list[str] = []
    _open(page, app_frontend, current_server, username="title_dock_long", name=LONG_NAME)
    _attach_an_agent(page, current_server, LONG_NAME)

    layout = _title_ends_before_the_dock(page, "A long name beside the dock")
    assert layout["cut"], f"the long name fits beside the dock, so this checks nothing: {layout}"
    assert layout["title"]["right"] - layout["title"]["left"] > 100, (
        f"the title is cut to almost nothing: {layout}"
    )
    # The row as it reads, the pointer off the canvas so nothing hovers.
    page.mouse.move(2, 2)
    _frame(page, "long-title-row", frames_failed, clip_rect=_row(page))
    # The whole name is the title's tooltip.
    tip = hover_until_tooltip_says(page, TITLE, "the canvas title", [LONG_NAME])
    _frame(page, "long-title-tooltip", frames_failed, keep_tooltip=True, clip_rect=tooltip_close_up(page, tip))
    assert not frames_failed, "\n".join(frames_failed)


def test_a_short_title_beside_the_agents_dock_is_shown_whole(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    _open(page, app_frontend, current_server, username="title_dock_short", name=SHORT_NAME)
    _attach_an_agent(page, current_server, SHORT_NAME)

    layout = _title_ends_before_the_dock(page, "A short name beside the dock")
    assert layout["text"] == SHORT_NAME and not layout["cut"], (
        f"a short name beside the dock is cut: {layout}"
    )


def test_a_long_title_with_no_dock_is_shown_whole(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    _open(page, app_frontend, current_server, username="title_dock_none", name=LONG_NAME)

    layout = page.evaluate(_LAYOUT_JS)
    assert layout["dock"] is None, f"this canvas has a dock, so it checks nothing: {layout}"
    assert layout["text"] == LONG_NAME and not layout["cut"], (
        f"a long name with no dock beside it is cut: {layout}"
    )
