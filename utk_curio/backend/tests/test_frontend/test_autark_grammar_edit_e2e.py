"""Playwright E2E for #157: the Autark grammar editor must accept edits at once.

The reported symptom was odd enough to be worth restating: edits to existing
lines did nothing, and typing only started working after the reporter had added
text on the *last* line and a red error marker appeared.

That is the signature of a controlled-value loop, not of a read-only editor.
``useAutkGrammarBehavior`` derived ``defaultValueOverride`` from ``data.code``,
which GrammarEditor itself writes back to (floatCode -> nodeState.setCode ->
``data.code = code``). So the override oscillated between the starter spec and
``undefined`` on every render. While the buffer still equalled the starter spec
@monaco-editor/react's ``value !== editor.getValue()`` guard hid it; the instant
the user changed anything, the next render ran
``executeEdits(fullModelRange, starterSpec, {forceMoveMarkers: true})`` -
replacing the document and parking the cursor at the end.

This drives Monaco through ``executeEdits`` on a MIDDLE line rather than through
``set_node_code``. That distinction is the whole test: ``set_node_code`` calls
``setValue``, which replaces the buffer wholesale and would paper over exactly
the reconciliation bug under test.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_autark_grammar_edit_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    canvas_node_type,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

AUTK_TILE = "#step-utk"
AUTK_TYPE = "curio.builtin/autk-grammar"
POS_NODE = (150, 120)

# Typed into a line in the middle of the starter spec. A marker string is easier
# to assert on than a structural edit, and being mid-document is what matters:
# the pre-fix build only appeared to accept input on the final line.
EDIT_MARKER = "curio_e2e_edit"

_GRAMMAR_EDITOR_JS = r"""(nodeId) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return null;
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    // The grammar editor's model is registered under a `grammar-<nodeId>.json`
    // path (GrammarEditor passes `path`), which distinguishes it from a code
    // editor on the same node.
    return editors.find((e) => {
        const uri = e.getModel() && e.getModel().uri && e.getModel().uri.path;
        return uri && uri.includes(`grammar-${nodeId}`);
    }) || null;
}"""


def _grammar_value(page, node_id: str) -> str:
    return page.evaluate(
        "(nodeId) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(nodeId);"
        " return ed ? ed.getValue() : null; }",
        node_id,
    )


def test_editing_a_middle_line_of_the_autark_grammar_sticks(
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
        name="Autark Editor",
        username="autark_editor",
        project_name="Autark Grammar Editing",
    )
    skip_if_shared_view(page)

    node_id = drag_to_canvas(page, page.locator(AUTK_TILE), at=POS_NODE)
    assert canvas_node_type(page, node_id).split("@", 1)[0] == AUTK_TYPE

    node_el = node_locator(page, node_id)
    # The Grammar tab. autk-grammar declares hasCode:false, so this is the node's
    # first editor tab - part of #157 was that NodeEditor still opened on "code",
    # leaving no pane active at all.
    grammar_tab = node_el.locator('.nav-link[data-rr-ui-event-key="grammar"]').first
    grammar_tab.wait_for(state="visible", timeout=20000)
    grammar_tab.dispatch_event("click")

    page.wait_for_function(
        "(args) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        " return !!ed && ed.getValue().length > 0; }",
        arg={"nodeId": node_id},
        timeout=20000,
    )
    starter = _grammar_value(page, node_id)
    assert starter and starter.strip() not in ("", "{}"), (
        f"the grammar editor opened with no starter spec to edit: {starter!r}"
    )
    line_count = len(starter.split("\n"))
    assert line_count >= 3, (
        f"need a multi-line starter spec to edit a middle line; got {line_count}"
    )

    # Insert on a middle line, through executeEdits — the same path a keystroke
    # takes into the model. NOT setValue, which would replace the whole buffer
    # and so could not surface the reconciliation bug.
    target_line = max(2, line_count // 2)
    page.evaluate(
        "(args) => {"
        "  const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        "  ed.focus();"
        "  const pos = { lineNumber: args.line, column: 1 };"
        "  ed.setPosition(pos);"
        "  ed.executeEdits('e2e', [{"
        "    range: { startLineNumber: args.line, startColumn: 1,"
        "             endLineNumber: args.line, endColumn: 1 },"
        "    text: args.text, forceMoveMarkers: true }]);"
        "}",
        {"nodeId": node_id, "line": target_line, "text": f'"{EDIT_MARKER}",\n'},
    )

    # Give the render loop several frames. The pre-fix revert happened on the
    # *next* render after the edit, so a check that ran synchronously would pass
    # against the broken build.
    page.wait_for_timeout(1500)

    after = _grammar_value(page, node_id)
    assert EDIT_MARKER in after, (
        "the edit was reverted: the grammar editor's controlled value snapped "
        "back over what was typed, which is #157.\n"
        f"expected {EDIT_MARKER!r} on line {target_line} of:\n{after}"
    )
    # It must also still be where it was typed. `forceMoveMarkers` reconciliation
    # moved the caret to the end of the document, so an edit landing on the last
    # line is the pre-fix behaviour rather than a pass.
    edited_line = next(
        (i + 1 for i, line in enumerate(after.split("\n")) if EDIT_MARKER in line),
        None,
    )
    assert edited_line == target_line, (
        f"the edit landed on line {edited_line}, not the line {target_line} it "
        f"was typed on - the cursor was moved by a value reconciliation"
    )

    # A second edit, to prove the editor stays usable rather than accepting one
    # change and then locking up.
    page.evaluate(
        "(args) => {"
        "  const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        "  ed.executeEdits('e2e', [{"
        "    range: { startLineNumber: args.line, startColumn: 1,"
        "             endLineNumber: args.line, endColumn: 1 },"
        "    text: args.text, forceMoveMarkers: true }]);"
        "}",
        {"nodeId": node_id, "line": target_line, "text": f'"{EDIT_MARKER}_two",\n'},
    )
    page.wait_for_timeout(1000)
    assert f"{EDIT_MARKER}_two" in _grammar_value(page, node_id), (
        "the second edit was reverted, so the editor accepts one change and then "
        "stops tracking"
    )

    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "autark-grammar-edit",
        test_name="test_editing_a_middle_line_of_the_autark_grammar_sticks",
    )
