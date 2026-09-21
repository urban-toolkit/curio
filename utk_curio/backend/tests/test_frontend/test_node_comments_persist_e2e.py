"""Playwright E2E for #237: a comment on a node must survive a save.

The report, exactly: "Comments added to modules anywhere in the project canvas
are not persisted after saving and reopening the project... The newly added
module is saved and remains on the canvas, but all comments disappear."

That pairing is what makes this worth an end-to-end test rather than only the
unit ones. Comments were held in ``NodeContainer``'s local ``useState`` and read
by nothing, so every layer downstream of it was innocent and looked correct:
``generateTrill`` serialized every field it knew about, the backend wrote the
spec through verbatim, and ``loadTrill`` restored everything it was given. Only
a round trip through the real UI shows the gap.

Reopening the project is deliberately how the round trip is closed, rather than
a reload in place: it forces a full remount from the persisted spec, so the test
cannot pass on component state that never unmounted. That also covers the half
the reporter did not try - the same missing write-back meant comments did not
survive *any* remount, save or no save.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_node_comments_persist_e2e.py -v
"""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    activate_header_icon,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

COMMENT_TEXT = "check the CRS before this join"

#: The lightest curated example with more than one node, so the scene has a
#: real node to comment on rather than an empty canvas.
EXAMPLE = "01-vega-lite-chained-transforms.json"


def _load_example(name: str) -> dict:
    import json
    import os

    from .utils import REPO_ROOT

    path = os.path.join(REPO_ROOT, "docs", "examples", name)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _rightmost_node_id(page) -> str:
    """The node with the greatest x on the canvas.

    Not just any node: the comments popover is ``position: absolute`` at
    ``left: calc(100% + 10px)`` with no z-index, so on a node that has a
    neighbour to its right the popover renders UNDERNEATH it and a real click
    lands on the neighbour instead. Driving the right-most node keeps this
    test about persistence rather than about that stacking quirk - which is
    real, but is not what #237 reported.
    """
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    return page.evaluate(
        """() => window.__curio_reactFlow.getNodes()
            .slice()
            .sort((a, b) => b.position.x - a.position.x)[0].id"""
    )


def _open_comments(page, node_id: str):
    """Open one node's comments popover and return its input."""
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)
    node.scroll_into_view_if_needed()
    # The header icons swallow the native click so press-and-drag still moves
    # the node; activate_header_icon dispatches the pointer pair instead.
    activate_header_icon(node.locator('[title="Comments"]').first)
    box = node.locator('textarea[placeholder="Write a comment..."]')
    box.wait_for(state="visible", timeout=15000)
    return node, box


def _add_comment(page, node_id: str, text: str) -> None:
    node, box = _open_comments(page, node_id)
    box.fill(text)
    node.locator('[data-curio-comment-submit="true"]').click()
    # The box clears only on a successful post, so this also rules out the
    # "typed but never submitted" case that made an earlier version of this
    # test pass against a comment that was never created.
    expect(box).to_have_value("", timeout=10000)


def _posted_comments(page, node_id: str) -> list[str]:
    """The text of every posted comment on a node.

    Scoped to the comment rows rather than the node's whole text: the compose
    textarea holds the same string while you are typing it, and matching that
    would report a comment that was never posted.
    """
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    return node.locator('[data-curio-comment="true"]').all_inner_texts()


def _comment_visible(page, node_id: str, text: str) -> bool:
    return any(text in entry for entry in _posted_comments(page, node_id))


def _save(page) -> None:
    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=5000)
    save_btn.click()
    save_btn.wait_for(state="hidden", timeout=20000)
    page.wait_for_timeout(1500)


def test_a_comment_survives_save_and_reopen(
    app_frontend: "FrontendPage", current_server, page
):
    require_project_page()
    require_user_auth()

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Comment Tester",
        username=f"cmt_{uuid.uuid4().hex[:10]}",
        project_name="Comments",
        project_spec=_load_example(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    node_id = _rightmost_node_id(page)
    _add_comment(page, node_id, COMMENT_TEXT)
    assert _comment_visible(page, node_id, COMMENT_TEXT), (
        "the comment did not render after being added, so this test cannot "
        "say anything about whether it persists"
    )

    _save(page)

    # Leave and come back the way the reporter did, rather than reloading in
    # place: a reload could pass on nothing more than component state that
    # never unmounted.
    project_id = session["project"]["id"]
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    _open_comments(page, node_id)
    assert _comment_visible(page, node_id, COMMENT_TEXT), (
        "the comment is gone after save + reopen (#237). If the node itself is "
        "present, the write-back to node data or metadata.comments is the part "
        "that regressed."
    )


def _node_data_comments(page, node_id: str) -> list[dict]:
    """The comments the canvas node itself carries.

    This, not the rendered text, is the assertion that discriminates the fix
    from the bug: before #237 ``node.data.comments`` did not exist at any point
    in the lifecycle, so a rendered comment could only ever have been component
    state.
    """
    return page.evaluate(
        """(nodeId) => {
            const rf = window.__curio_reactFlow;
            const node = rf ? rf.getNodes().find((n) => n.id === nodeId) : null;
            return (node && node.data && node.data.comments) || [];
        }""",
        node_id,
    )


def _drag_tile(page, node_id: str, dx: int, dy: int) -> None:
    """Drag a dashboard tile by its title band, the only part that moves it."""
    handle = page.locator(
        f'.react-flow__node[data-id="{node_id}"] .curio-dashboard-tile-handle'
    ).first
    handle.wait_for(state="visible", timeout=30000)
    box = handle.bounding_box()
    assert box, "the tile's title band has no box to grab"
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=10)
    page.mouse.up()


def test_a_comment_survives_a_dashboard_layout_save(
    app_frontend: "FrontendPage", current_server, page
):
    """A comment is carried by the node, so saving a dashboard cannot lose it.

    The dashboard is a page of its own now, and its one write - Save layout -
    saves the whole dataflow spec from the nodes the PAGE loaded: every one of
    them, pinned or not, rewritten with tile geometry. That is a second path by
    which a node's data reaches disk, and the comment has to come through it
    intact. Before #237 there was nothing on the node to come through.

    The round trip is two full page loads, dataflow to dashboard and back, so
    nothing can survive in component state: whatever the second canvas shows
    was read from the spec the dashboard wrote.
    """
    require_project_page()
    require_user_auth()

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Comment Tester",
        username=f"cmtdash_{uuid.uuid4().hex[:8]}",
        project_name="Comments Dashboard",
        project_spec=_load_example(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    project_id = session["project"]["id"]

    node_id = _rightmost_node_id(page)
    _add_comment(page, node_id, COMMENT_TEXT)
    stored = _node_data_comments(page, node_id)
    assert [c["text"] for c in stored] == [COMMENT_TEXT], (
        f"the comment never reached the node's data, so it is still living in "
        f"component state (#237); node.data.comments = {stored!r}"
    )

    # Pin the node under test and save, so the dashboard has it as a tile.
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    activate_header_icon(node.locator('[title="Pin to dashboard"]').first)
    expect(node.locator('[title="Unpin from dashboard"]')).to_have_count(1, timeout=10000)
    _save(page)

    # Onto the dashboard, move the tile, and save the layout.
    page.goto(f"{app_frontend.base_url}/dashboard/{project_id}")
    page.get_by_test_id("edit-layout-btn").wait_for(state="visible", timeout=45000)
    # The node header is not rendered on a tile, so the comment cannot be edited
    # here: whatever reaches disk came from the node's data, not from this page.
    tile = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    tile.wait_for(state="visible", timeout=45000)
    assert tile.locator('[title="Comments"]').count() == 0, (
        "the tile is rendering the canvas node header; this test's assumptions "
        "about what is reachable on the dashboard no longer hold"
    )
    page.get_by_test_id("edit-layout-btn").click()
    before = page.evaluate(
        "(id) => window.__curio_reactFlow.getNode(id).position", node_id,
    )
    _drag_tile(page, node_id, 120, 60)
    after = page.evaluate(
        "(id) => window.__curio_reactFlow.getNode(id).position", node_id,
    )
    assert after != before, "the tile did not move, so the layout save has nothing to write"
    page.get_by_test_id("save-layout-btn").click()
    page.get_by_test_id("save-layout-btn").wait_for(state="detached", timeout=20000)

    # Back to the dataflow, from disk.
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)

    survived = _node_data_comments(page, node_id)
    assert [c["text"] for c in survived] == [COMMENT_TEXT], (
        f"the dashboard's layout save dropped the comment from the node, so the "
        f"spec on disk no longer has it (#237); node.data.comments = {survived!r}"
    )
    _open_comments(page, node_id)
    assert _comment_visible(page, node_id, COMMENT_TEXT), (
        "the comment is on the node but is not rendered after the round trip"
    )
