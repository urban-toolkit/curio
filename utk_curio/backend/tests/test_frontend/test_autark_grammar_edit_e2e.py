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

A fresh Autark node now opens empty, like a Vega chart, and the starter comes
from the input that reaches it (``hook/useStarterSpec``), through the same
``defaultValueOverride``. So this wires a GeoDataFrame loader into an empty
Autark node, runs the loader, and edits the starter the node was given.

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
    dismiss_toasts,
    node_locator,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "autk-edit-loader"
AUTK_ID = "autk-edit-map"

LOADER_CODE = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    "    {\"pop\": [1, 2, 3]},\n"
    "    geometry=[Point(0, 0), Point(1, 1), Point(2, 2)],\n"
    "    crs=\"EPSG:4326\",\n"
    ")\n"
)

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


def _spec() -> dict:
    node = lambda node_id, node_type, x, content: {  # noqa: E731
        "id": node_id, "type": node_type, "x": x, "y": 0, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }
    return {
        "dataflow": {
            "name": "Autark Grammar Editing",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Autark Grammar Editing",
            "nodes": [
                node(LOADER_ID, "curio.builtin/data-loading", 0, LOADER_CODE),
                # Empty on purpose: the starter only ever fills an empty editor.
                node(AUTK_ID, "curio.builtin/autk-grammar", 645, ""),
            ],
            "edges": [{
                "id": f"reactflow__edge-{LOADER_ID}out-{AUTK_ID}in",
                "source": LOADER_ID,
                "target": AUTK_ID,
            }],
        }
    }


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
        project_spec=_spec(),
    )
    require_owner_view(page)

    node_id = AUTK_ID
    node_el = node_locator(page, node_id)
    node_el.wait_for(state="visible", timeout=45000)
    # The Grammar tab. autk-grammar declares hasCode:false, so this is the node's
    # first editor tab - part of #157 was that NodeEditor still opened on "code",
    # leaving no pane active at all.
    grammar_tab = node_el.locator('.nav-link[data-rr-ui-event-key="grammar"]').first
    grammar_tab.wait_for(state="visible", timeout=20000)
    grammar_tab.dispatch_event("click")

    # An edge alone carries no schema, so nothing has been written yet.
    before = _grammar_value(page, node_id)
    assert before is None or before.strip() in ("", "{}"), (
        f"the Autark node was filled before its input had run: {before!r}"
    )

    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    page.wait_for_function(
        "(args) => { const ed = (" + _GRAMMAR_EDITOR_JS + ")(args.nodeId);"
        " return !!ed && ed.getValue().includes('layerRefs'); }",
        arg={"nodeId": node_id},
        timeout=60000,
    )
    starter = _grammar_value(page, node_id)
    assert '"getFnv": "pop"' in starter, (
        f"the starter should colour the layer by its number column: {starter!r}"
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
