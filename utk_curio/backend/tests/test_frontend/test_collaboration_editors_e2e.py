"""Playwright E2E: who edits a dataflow in collaboration.

The owner invites an editor by username from Share > Invite editors. The
editor opens the dataflow's link and moves its node: the move reaches the
owner's canvas, which marks the dataflow Unsaved so its save keeps it. A
watcher, anyone else signed in who opens the link, gets a read-only canvas:
the banner says so and the node does not move, while the editor's next change
reaches the watcher too.

Needs a stack started with ``--collab``: CI's e2e-collab job, which runs the
tests marked ``needs_collab`` (``runner_split.py``), or a local run with
``CURIO_E2E_COLLAB=1``, as ``fixtures.py`` passes ``--collab`` then. On any
other stack it fails saying so.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    drag_builtin_to_canvas,
    node_locator,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

pytestmark = pytest.mark.needs_collab

FRAMES = "collaboration-editors"
NODE = "collab-node"
EDITOR = "collab_editor_e2e"

_POSITION_JS = """(id) => {
    const node = window.__curio_reactFlow && window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    return node ? [node.position.x, node.position.y] : null;
}"""


def _spec() -> dict:
    return {
        "name": "Shared plan",
        "dataflow": {
            "name": "Shared plan",
            "nodes": [{
                "id": NODE, "type": "curio.builtin/data-loading", "x": 0, "y": 0,
                "content": "", "metadata": {}, "out": {"type": "string"},
            }],
            "edges": [],
        },
    }


def _require_collab_stack(backend: str) -> None:
    if not api_json(f"{backend}/api/config/public", "").get("enable_collab"):
        pytest.fail(
            "this stack runs without --collab: run the test in CI's e2e-collab job, "
            "or locally with CURIO_E2E_COLLAB=1"
        )


def _open_as(page, base: str, project_id: str, role: str) -> None:
    """Open the dataflow's link and wait for its room to name this tab's role:
    the collaboration panel lists everyone with theirs."""
    page.goto(f"{base}/dataflow/{project_id}", timeout=120000)
    node_locator(page, NODE).wait_for(timeout=30000)
    try:
        page.locator(f'[data-collab-role="{role}"]').first.wait_for(timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"the collaboration panel never named a {role} on this tab") from exc


def _position(page, node_id: str = NODE):
    return page.evaluate(_POSITION_JS, node_id)


def _save(page) -> None:
    """Save from the top bar's save status, and wait until it reads Saved."""
    page.locator("[data-curio-save-state]").click()
    page.locator('[data-curio-save-state="saved"]').wait_for(timeout=30000)


def _open_invite_editors(page, *, frame: bool = False) -> None:
    """Share > Invite editors; with *frame*, the menu's frame on the way."""
    page.get_by_test_id("share-menu-btn").click()
    item = page.get_by_test_id("invite-editors-menu-item")
    item.wait_for(timeout=10000)
    if frame:
        save_workflow_test_screenshot(
            page, FRAMES, test_name="share-menu-invite-editors",
            clip_selector='[data-testid="share-menu-btn"] + div', fit_reactflow=False,
        )
    item.click()


#: What a press at a point lands on: "node" on *id*'s card where a drag starts,
#: else what is there (the top bar over the canvas, say).
_PRESS_TARGET_JS = """([id, x, y]) => {
    const hit = document.elementFromPoint(x, y);
    if (!hit) return 'nothing';
    const node = hit.closest('.react-flow__node');
    if (node && node.getAttribute('data-id') === id) {
        return hit.closest('.nodrag') ? 'a part of the node that does not drag' : 'node';
    }
    const named = hit.closest('[data-testid]');
    if (named) return named.getAttribute('data-testid');
    return hit.tagName.toLowerCase() + (hit.className ? '.' + String(hit.className).trim().split(/\\s+/).join('.') : '');
}"""


def _drag_node_by(page, node_id: str, dx: float, dy: float) -> None:
    """Drag a node by its header with the mouse, *dx* and *dy* in canvas units,
    a few pixels at a time, as test_feature_tour_video.py's does.

    Before-run: the helper as it was when run 40713502116 failed, with no
    fit and no check of where the press lands."""
    zoom = page.evaluate("() => window.__curio_reactFlow.getViewport().zoom")
    box = node_locator(page, node_id).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + 15 * zoom
    page.mouse.move(x, y)
    page.mouse.down()
    for leg_x, leg_y in ((dx * zoom, 0.0), (0.0, dy * zoom)):
        steps = max(1, math.ceil(max(abs(leg_x), abs(leg_y)) / 6))
        for i in range(1, steps + 1):
            page.mouse.move(x + leg_x * i / steps, y + leg_y * i / steps)
            page.wait_for_timeout(20)
        x, y = x + leg_x, y + leg_y
    page.mouse.up()
    page.wait_for_timeout(600)


def _wait_for_position(page, expected, *, what: str) -> None:
    try:
        page.wait_for_function(
            """([id, want]) => {
                const node = window.__curio_reactFlow && window.__curio_reactFlow.getNodes().find((n) => n.id === id);
                return !!node && Math.abs(node.position.x - want[0]) < 0.5 && Math.abs(node.position.y - want[1]) < 0.5;
            }""",
            arg=[NODE, expected],
            timeout=15000,
        )
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"{what}: the node is at {_position(page)}, not {expected}") from exc


def test_an_invited_editors_move_reaches_the_owner_and_a_watcher_only_watches(
    app_frontend: "FrontendPage", current_server: str, browser,
):
    require_project_page()
    require_user_auth()
    _require_collab_stack(current_server)
    base = app_frontend.base_url
    viewport = {"width": 1280, "height": 768}
    owner_ctx = browser.new_context(viewport=viewport)
    editor_ctx = browser.new_context(viewport=viewport)
    watcher_ctx = browser.new_context(viewport=viewport)
    try:
        owner, editor, watcher = owner_ctx.new_page(), editor_ctx.new_page(), watcher_ctx.new_page()
        stubbed = stub_db_login(
            owner, frontend_url=base, backend_url=current_server,
            username="collab_owner_e2e", name="Collab Owner",
            project_name="Shared plan", project_spec=_spec(),
        )
        project_id, owner_token = stubbed["project"]["id"], stubbed["token"]
        stub_db_login(editor, frontend_url=base, backend_url=current_server,
                      username=EDITOR, name="Collab Editor")
        stub_db_login(watcher, frontend_url=base, backend_url=current_server,
                      username="collab_watcher_e2e", name="Collab Watcher")

        # The owner invites the editor from the Share menu.
        _open_as(owner, base, project_id, "owner")
        _open_invite_editors(owner)
        dialog = owner.get_by_test_id("invite-editors-dialog")
        dialog.get_by_text("No editors yet.").wait_for(timeout=10000)
        dialog.get_by_label("Username").fill(EDITOR)
        dialog.get_by_role("button", name="Add").click()
        dialog.locator(f'[data-editor="{EDITOR}"]').wait_for(timeout=10000)
        dialog.get_by_role("button", name="Done").click()
        dialog.wait_for(state="detached", timeout=10000)
        # What is on disk, so that Unsaved below is the editor's change alone.
        _save(owner)

        # The editor's canvas is editable, and their move reaches the owner.
        _open_as(editor, base, project_id, "editor")
        assert editor.get_by_test_id("shared-view-banner").count() == 0, (
            "an invited editor's canvas opened read-only"
        )
        # The room can answer before the tab's load fit lands, and the canvas
        # then still shows its default view, the node's header under the top
        # bar. The editor's canvas is put there, so every run meets that order.
        editor.evaluate("() => window.__curio_reactFlow.setViewport({x: 0, y: 0, zoom: 1})")
        before = _position(editor)
        _drag_node_by(editor, NODE, 160, 90)
        moved = _position(editor)
        assert moved and before and (moved[0] - before[0]) > 50 and (moved[1] - before[1]) > 30, (
            f"the editor's drag did not move the node: {before} -> {moved}"
        )
        _wait_for_position(owner, moved, what="the editor's move never reached the owner")
        # The owner's tab keeps it: the dataflow reads Unsaved, and its save
        # writes the editor's position.
        owner.locator('[data-curio-save-state="unsaved"]').wait_for(timeout=15000)
        _save(owner)
        saved = api_json(f"{current_server}/api/projects/{project_id}", owner_token)["spec"]
        node = next(n for n in saved["dataflow"]["nodes"] if n["id"] == NODE)
        assert (node["x"], node["y"]) == pytest.approx(tuple(moved), abs=0.5), (
            f"the owner's save did not keep the editor's move: {node['x']}, {node['y']} not {moved}"
        )

        # A watcher's canvas is read-only: the banner, and a node that stays.
        _open_as(watcher, base, project_id, "watcher")
        banner = watcher.get_by_test_id("shared-view-banner")
        banner.wait_for(timeout=15000)
        assert "read-only" in (banner.inner_text() or "").lower()
        watching = _position(watcher)
        assert watching == pytest.approx(moved, abs=0.5), f"the watcher opened {watching}, not the saved {moved}"
        _drag_node_by(watcher, NODE, 200, 120)
        assert _position(watcher) == pytest.approx(watching, abs=0.5), "a watcher moved the node"
        assert _position(owner) == pytest.approx(moved, abs=0.5), "a watcher's drag reached the owner"

        # The editor's next change reaches everyone: the owner and the watcher.
        added = drag_builtin_to_canvas(editor, "#tile-computation-analysis", at=(200, 450))
        node_locator(owner, added).wait_for(timeout=15000)
        node_locator(watcher, added).wait_for(timeout=15000)

        # The frames, last: the Share menu with Invite editors, and its dialog
        # listing the editor.
        _open_invite_editors(owner, frame=True)
        dialog = owner.get_by_test_id("invite-editors-dialog")
        dialog.locator(f'[data-editor="{EDITOR}"]').wait_for(timeout=10000)
        save_workflow_test_screenshot(
            owner, FRAMES, test_name="invite-editors-dialog",
            clip_selector='[data-testid="invite-editors-dialog"]', fit_reactflow=False,
        )
    finally:
        owner_ctx.close()
        editor_ctx.close()
        watcher_ctx.close()
