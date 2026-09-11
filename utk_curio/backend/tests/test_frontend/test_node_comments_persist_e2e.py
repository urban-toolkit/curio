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
    from the bug - see ``test_a_comment_survives_dashboard_mode``.
    """
    return page.evaluate(
        """(nodeId) => {
            const rf = window.__curio_reactFlow;
            const node = rf ? rf.getNodes().find((n) => n.id === nodeId) : null;
            return (node && node.data && node.data.comments) || [];
        }""",
        node_id,
    )


def test_a_comment_survives_dashboard_mode(
    app_frontend: "FrontendPage", current_server, page
):
    """A comment is carried by the node, so Dashboard Mode cannot lose it.

    Read the assertions before changing them: the obvious version of this test
    proves nothing.

    Toggling Dashboard Mode does NOT unmount the node - it is the same
    ``<ReactFlow>`` instance with different props, and the node's DOM element
    survives the whole round trip. So a test that merely looked for the comment
    text afterwards would ALSO have passed against the bug, because
    component-local ``useState`` survives a re-render just as well. That is the
    trap this test exists to avoid falling into.

    What does discriminate is where the comment lives. Dashboard Mode rewrites
    every pinned node's data (position, dimensions, ``dashboardPinned``), and
    the comment has to come through that intact - which it can only do by being
    ON the node. Before the fix ``node.data.comments`` did not exist at any
    point in the lifecycle, so the store assertion below could not have passed.
    """
    require_project_page()
    require_user_auth()

    stub_login_and_enter_workflow(
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

    node_id = _rightmost_node_id(page)
    _add_comment(page, node_id, COMMENT_TEXT)

    stored = _node_data_comments(page, node_id)
    assert [c["text"] for c in stored] == [COMMENT_TEXT], (
        f"the comment never reached the node's data, so it is still living in "
        f"component state (#237); node.data.comments = {stored!r}"
    )

    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    # Dashboard Mode refuses to enter with nothing pinned (#192), so pin the
    # node under test first - otherwise the toggle below is a no-op. The pin
    # control is title-toggling ("Pin to dashboard" -> "Unpin from dashboard"),
    # so this selector only matches while the node is unpinned.
    activate_header_icon(node.locator('[title="Pin to dashboard"]').first)
    expect(node.locator('[title="Unpin from dashboard"]')).to_have_count(1, timeout=10000)

    # In: View -> Dashboard Mode.
    page.get_by_role("button", name=re.compile("View")).click(force=True)
    page.get_by_text("Dashboard Mode", exact=True).first.click()
    exit_btn = page.locator('[title="Exit Dashboard Mode"]')
    exit_btn.wait_for(state="visible", timeout=15000)

    # The node's header icons are not rendered in dashboard mode, so there is
    # nothing to click on the node itself here - only the panel's own control.
    assert node.locator('[title="Comments"]').count() == 0, (
        "the node header is rendering in dashboard mode; this test's "
        "assumptions about what is reachable there no longer hold"
    )

    # Out: the panel's own control. There is no View menu in dashboard mode -
    # `{!dashboardOn && <UpMenu>}` takes the whole top bar with it.
    exit_btn.click()
    page.wait_for_selector('[title="Comments"]', timeout=45000)
    dismiss_toasts(page)

    survived = _node_data_comments(page, node_id)
    assert [c["text"] for c in survived] == [COMMENT_TEXT], (
        f"the dashboard round trip dropped the comment from the node's data, "
        f"so it would not be saved either (#237); node.data.comments = "
        f"{survived!r}"
    )
    # And it is still on screen. The popover was never closed - `showComments`
    # is component state and nothing here unmounts the node - so re-activating
    # the Comments icon would toggle it SHUT rather than open.
    assert _comment_visible(page, node_id, COMMENT_TEXT), (
        "the comment is on the node but no longer rendered after leaving "
        "dashboard mode"
    )
