"""Playwright E2E for #153: Delete must remove the canvas selection, not just Backspace.

React Flow's ``deleteKeyCode`` default is ``'Backspace'`` alone, and MainCanvas
passed ``undefined`` (i.e. "use the default"). macOS never noticed - its delete
key emits Backspace - so this reached users as "Delete does nothing on Windows".

Both keys are exercised, because the fix is a two-element array and dropping
either entry is the obvious way to regress it. The third case is the one that
makes widening the binding safe rather than reckless: with the caret inside a
node's Monaco editor, Delete must edit text and leave the node alone. React Flow
gets that right via ``isInputDOMNode``, but nothing in this repo pinned it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_delete_key_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    canvas_nodes,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    read_node_code,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#step-analysis"
POS_FIRST = (150, 150)
POS_SECOND = (760, 150)


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


def test_a_wired_node_is_refused_and_the_toast_says_how_many_connections(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """Refusing to delete a connected node must explain itself.

    The two tests above never connect their nodes, so neither covers what happens
    when one is wired - and that is the case a real dataflow is always in. A user
    test read the silence as "Delete is broken" and only a source bisect showed
    the refusal was deliberate (``MainCanvas.handleNodesChange``). The behaviour
    stays; what is pinned here is that the user is told what is in the way.
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
    dismiss_toasts(page)

    _select(page, second)
    page.keyboard.press("Delete")
    page.wait_for_timeout(1500)

    # Still there: the refusal is the documented behaviour.
    assert second in _node_ids(page), (
        "a node with an edge was removed; deleting a wired node is supposed to "
        "be refused until its connections are gone"
    )

    # And the user was told, with the count so they know what to clear.
    toast = page.locator('[aria-label="Notifications"] .toast').first
    toast.wait_for(state="visible", timeout=10000)
    said = " ".join((toast.text_content() or "").split())
    assert "1 connection" in said, (
        f"the toast did not name how many connections block the delete: {said!r}"
    )
    assert "Delete or Backspace" in said, (
        f"the toast did not say how to clear them: {said!r}"
    )
    dismiss_toasts(page)

    # Clearing the edge makes the node deletable, which is the path the toast
    # describes. Proves the refusal is a gate, not a dead end.
    #
    # The edge is removed by selecting it and pressing Delete, exactly as the
    # toast instructs. Not by writing React Flow's store: `useStoreUpdater`
    # pushes FlowContext's own edge array straight back over it, so the edge
    # would reappear and the delete stay refused (see utils.drag_to_canvas).
    edge_point = page.evaluate(
        """() => {
            const path = document.querySelector('.react-flow__edge-interaction');
            if (!path) return null;
            const at = path.getPointAtLength(path.getTotalLength() / 2);
            const svg = path.ownerSVGElement;
            const point = svg.createSVGPoint();
            point.x = at.x;
            point.y = at.y;
            const screen = point.matrixTransform(path.getScreenCTM());
            return [screen.x, screen.y];
        }"""
    )
    assert edge_point, "no edge interaction path to click"
    page.mouse.click(edge_point[0], edge_point[1])
    page.wait_for_function(
        "() => (window.__curio_reactFlow.getEdges() || [])"
        ".some((e) => e.selected)",
        timeout=10000,
    )
    page.keyboard.press("Delete")
    page.wait_for_function(
        "() => (window.__curio_reactFlow.getEdges() || []).length === 0",
        timeout=10000,
    )
    dismiss_toasts(page)
    _select(page, second)
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)",
        arg=second,
        timeout=10000,
    )
    assert second not in _node_ids(page)
