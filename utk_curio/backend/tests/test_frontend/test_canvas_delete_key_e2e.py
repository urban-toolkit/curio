"""Playwright E2E for #153: Delete must remove the canvas selection, not just Backspace.

React Flow's ``deleteKeyCode`` default is ``'Backspace'`` alone, and MainCanvas
passed ``undefined`` (i.e. "use the default"). macOS never noticed - its delete
key emits Backspace - so this reached users as "Delete does nothing on Windows".

Both keys are exercised, because the fix is a two-element array and dropping
either entry is the obvious way to regress it. The third case is the one that
makes widening the binding safe rather than reckless: with the caret inside a
node's Monaco editor, Delete must edit text and leave the node alone. React Flow
gets that right via ``isInputDOMNode``, but nothing in this repo pinned it.

The last three cases are #155: deleting wired nodes removes their edges too,
from the key and from the node header's Delete node button.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_delete_key_e2e.py -v
"""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from .utils import (
    _wait_for_reactflow_ready,
    canvas_nodes,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    read_node_code,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#tile-computation-analysis"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"
POS_FIRST = (150, 150)
POS_SECOND = (760, 150)
POS_THIRD = (760, 560)


def _node_ids(page) -> set[str]:
    return {node["id"] for node in canvas_nodes(page)}


def _select(page, node_id: str) -> None:
    """Click a node's header strip so it becomes the canvas selection.

    The y offset matters: the header is only ~20px tall and everything below it
    is Monaco, whose ``.view-line`` layer intercepts pointer events. Clicking
    into the editor would also be the wrong thing to test here - that is the
    third case, where the delete keys must NOT reach the canvas.
    """
    node_locator(page, node_id).click(position={"x": 300, "y": 8})
    page.wait_for_function(
        "id => {"
        "  const el = document.querySelector(`.react-flow__node[data-id='${id}']`);"
        "  return el && el.classList.contains('selected');"
        "}",
        arg=node_id,
        timeout=10000,
    )


def test_delete_and_backspace_both_remove_the_selected_node(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Delete Key",
        username="delete_key",
        project_name="Delete Key",
    )
    require_owner_view(page)

    first = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_FIRST)
    second = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_SECOND)
    assert {first, second} <= _node_ids(page)

    # 1. Delete — the key that did nothing before the fix.
    _select(page, first)
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)",
        arg=first,
        timeout=10000,
    )
    assert first not in _node_ids(page)

    # 2. Backspace — the pre-existing binding, which the fix must not drop.
    _select(page, second)
    page.keyboard.press("Backspace")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)",
        arg=second,
        timeout=10000,
    )
    assert second not in _node_ids(page)


def test_delete_inside_a_code_editor_edits_text_and_keeps_the_node(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """Widening the binding must not make code editing destructive."""
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Delete Key",
        username="delete_key_editor",
        project_name="Delete Key In Editor",
    )
    require_owner_view(page)

    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_FIRST)
    set_node_code(page, node_id, "AB\n")

    # Give the editor focus through Monaco's own API. A plain click is
    # intercepted by Monaco's .view-line overlay, and focusing the bare textarea
    # gives the keystroke a target but no caret. What this test needs is only
    # that focus is *inside the editor* when the key is pressed - that is the
    # condition React Flow's isInputDOMNode checks.
    node_locator(page, node_id).locator(".monaco-editor").first.wait_for(
        state="visible", timeout=15000,
    )
    focused_in_editor = page.evaluate(
        """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            if (!editorEl) return false;
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const match = editors.find((e) => editorEl.contains(e.getDomNode()));
            if (!match) return false;
            match.focus();
            match.setPosition({ lineNumber: 1, column: 1 });
            return editorEl.contains(document.activeElement);
        }""",
        node_id,
    )
    assert focused_in_editor, "could not move focus into the node's code editor"

    page.keyboard.press("Delete")
    page.wait_for_timeout(500)

    # The claim under test. Whether Monaco forward-deletes a character is
    # Monaco's business and is not asserted here - what would break users is the
    # canvas binding swallowing the key and deleting their node instead.
    assert node_id in _node_ids(page), (
        "pressing Delete with focus inside a node's code editor deleted the NODE. "
        "React Flow's isInputDOMNode guard is what makes widening deleteKeyCode "
        "to include Delete safe, and it is not holding."
    )
    code = read_node_code(page, node_id)
    assert "B" in code, f"the editor lost its content entirely: {code!r}"

    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "canvas-delete-key",
        test_name="test_delete_inside_a_code_editor_edits_text_and_keeps_the_node",
    )


def _edges(page) -> list[dict]:
    return page.evaluate(
        "() => (window.__curio_reactFlow.getEdges() || [])"
        ".map((e) => ({id: e.id, source: e.source, target: e.target}))"
    )


def _node_input(page, node_id: str):
    return page.evaluate(
        "id => { const n = (window.__curio_reactFlow.getNodes() || [])"
        ".find((x) => x.id === id); return n ? n.data.input : null; }",
        node_id,
    )


def _wait_gone(page, node_id: str) -> None:
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)",
        arg=node_id,
        timeout=10000,
    )


def _no_connection_warning(page) -> None:
    toasts = page.locator('[aria-label="Notifications"] .toast')
    for index in range(toasts.count()):
        said = " ".join((toasts.nth(index).text_content() or "").split()).lower()
        assert "connection" not in said and "cannot be removed" not in said, (
            f"deleting a wired node was refused: {said!r}"
        )


def test_deleting_a_wired_node_removes_its_edge_and_clears_the_downstream_input(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """#155: Delete on a wired node removes it with its edge.

    The node downstream stays, and loses the input the deleted node fed it,
    exactly as when that edge is deleted by hand.
    """
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Delete Key",
        username="delete_key_wired",
        project_name="Delete Key Wired",
    )
    require_owner_view(page)

    first = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_FIRST)
    second = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_SECOND)
    connect_nodes(page, first, second)
    set_node_code(page, first, "return 1\n")
    run_node_and_wait(page, first, node_type=ANALYSIS_TYPE)
    page.wait_for_function(
        "id => { const n = (window.__curio_reactFlow.getNodes() || [])"
        ".find((x) => x.id === id); return !!(n && n.data.input); }",
        arg=second,
        timeout=30000,
    )
    dismiss_toasts(page)

    _select(page, first)
    page.keyboard.press("Delete")
    _wait_gone(page, first)

    assert second in _node_ids(page), "the downstream node was removed too"
    assert _edges(page) == [], f"the deleted node's edge is still there: {_edges(page)}"
    page.wait_for_function(
        "id => { const n = (window.__curio_reactFlow.getNodes() || [])"
        ".find((x) => x.id === id); return !!n && !n.data.input; }",
        arg=second,
        timeout=10000,
    )
    _no_connection_warning(page)


def test_a_selection_of_wired_nodes_is_deleted_with_its_edges(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """#155's report: select connected nodes, press Delete, all of them go.

    A is wired to B and B to C. Selecting A and B removes both, with both
    edges, and C stays.
    """
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Delete Key",
        username="delete_key_selection",
        project_name="Delete Key Selection",
    )
    require_owner_view(page)

    a = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_FIRST)
    b = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_SECOND)
    c = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_THIRD)
    # Three nodes do not fit a 1280x720 viewport at zoom 1, so fit them all
    # before wiring, or a handle sits outside the viewport.
    _wait_for_reactflow_ready(page, padding=0.1)
    connect_nodes(page, a, b)
    connect_nodes(page, b, c)
    dismiss_toasts(page)

    def header_point(node_id: str) -> dict:
        # A fraction of the scaled width: the header's right end holds its
        # icon buttons, Delete node among them.
        box = node_locator(page, node_id).bounding_box()
        assert box, f"node {node_id} has no layout box"
        return {"x": box["width"] * 0.4, "y": 6}

    node_locator(page, a).click(position=header_point(a))
    modifier = "Meta" if sys.platform == "darwin" else "Control"
    page.keyboard.down(modifier)
    node_locator(page, b).click(position=header_point(b))
    page.keyboard.up(modifier)
    page.wait_for_function(
        "ids => ids.every((id) => {"
        "  const el = document.querySelector(`.react-flow__node[data-id='${id}']`);"
        "  return el && el.classList.contains('selected');"
        "})",
        arg=[a, b],
        timeout=10000,
    )

    page.keyboard.press("Delete")
    _wait_gone(page, a)
    _wait_gone(page, b)

    assert _node_ids(page) == {c}, f"expected only {c} to remain: {_node_ids(page)}"
    assert _edges(page) == [], f"edges of the deleted nodes remain: {_edges(page)}"
    _no_connection_warning(page)


def test_the_header_delete_removes_a_wired_node(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The node header's Delete node button follows the same rule as the key."""
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Delete Key",
        username="delete_key_header",
        project_name="Delete Key Header",
    )
    require_owner_view(page)

    first = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_FIRST)
    second = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_SECOND)
    connect_nodes(page, first, second)
    dismiss_toasts(page)

    node_locator(page, second).get_by_title("Delete node").first.click()
    _wait_gone(page, second)

    assert _node_ids(page) == {first}
    assert _edges(page) == [], f"the deleted node's edge is still there: {_edges(page)}"
    _no_connection_warning(page)
