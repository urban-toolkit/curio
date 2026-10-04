"""Playwright E2E: one Parameter node drives two nodes (#662).

A Parameter node holds one widget. Its tag, ``@factor``, is offered under
Shared above every node's code, and ``[!! @factor !!]`` reads its value. The
Parameter node has no edge. This drives the whole path in a browser:

1. Drop a Parameter node and declare its widget, a number named ``factor``.
2. Drag its tag from the strip above one node's code, and type the reference
   into a second node. The Parameter node lists both as using it.
3. Run both: each gets the value.
4. Change the value. Running the node below the first runs the first again,
   though its code did not change; running the second gives the new value.
5. Rename the parameter: both nodes' code follows the new name.
6. Save and reopen: the widget, its value and the renamed references are back.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_parameter_node_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    connect_nodes,
    drag_to_canvas,
    frame_node,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_code,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_dataflow,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PARAMETER_TILE = "#tile-parameter"
CODE_TILE = "#tile-computation-analysis"
NODE_TYPE = "curio.builtin/computation-analysis"
PARAMETER_TYPE = "curio.builtin/parameter"

A_TEMPLATE = "factor = \nprint(f'<<A {factor * 10}>>')\nreturn factor * 10\n"
A_WITH_TAG = "factor = [!! @factor !!]\nprint(f'<<A {factor * 10}>>')\nreturn factor * 10\n"
B_CODE = "value = [!! @factor !!]\nprint(f'<<B {value}>>')\nreturn value\n"
READER_CODE = "print(f'<<R {arg}>>')\nreturn arg\n"

# A code node is 525x350 at zoom 1: the two it feeds and the one below it
# leave each facing handle clear, and the Parameter node sits apart.
POS_A = (150, 60)
POS_READER = (760, 60)
POS_B = (150, 440)
POS_PARAMETER = (760, 440)

# Where a drop lands just past the text of the editor's first line, from
# Monaco's own layout of that line (scaled to the editor's box on screen), and
# what the page shows at that point.
_LINE_END_POINT_JS = r"""(nodeId) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return { over: false, why: "no monaco instance owns this node's editor" };
    const dom = editor.getDomNode();
    const box = dom.getBoundingClientRect();
    if (!box.width || !box.height || !dom.offsetWidth) {
        return { over: false, why: `the editor is ${box.width}x${box.height} on screen` };
    }
    const line = editor.getScrolledVisiblePosition({
        lineNumber: 1, column: editor.getModel().getLineMaxColumn(1),
    });
    if (!line) return { over: false, why: "line 1 is not laid out" };
    const scale = box.width / dom.offsetWidth;
    const x = box.left + (line.left + 12) * scale;
    const y = box.top + (line.top + line.height / 2) * scale;
    const hit = document.elementFromPoint(x, y);
    return { over: !!hit && dom.contains(hit), x, y,
        why: `(${Math.round(x)}, ${Math.round(y)}) shows ${hit ? hit.tagName : "nothing"}` };
}"""

# Drags the shared tag in the strip above a node's code and drops it at (x, y).
# The cursor is parked on line 2 first, so a reference that lands on line 1 was
# placed by the drop point. Synthetic events, like drag_to_canvas.
_DRAG_SHARED_TAG_JS = r"""({ nodeId, name, x, y }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const tag = nodeEl.querySelector(`[data-widget-strip] [data-shared-tag="${name}"]`);
    if (!tag) return "no shared tag in the strip above the code";
    const editorEl = nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return "no monaco instance owns this node's editor";
    editor.setPosition({ lineNumber: 2, column: 1 });
    const target = document.elementFromPoint(x, y);
    if (!target || !editor.getDomNode().contains(target)) return "the drop point left the editor";

    const dt = new DataTransfer();
    const init = { bubbles: true, cancelable: true, composed: true, dataTransfer: dt };
    tag.dispatchEvent(new DragEvent("dragstart", init));
    if (!dt.types.includes("application/x-curio-shared")) return "the tag put nothing on the drag";
    const at = { ...init, clientX: x, clientY: y };
    target.dispatchEvent(new DragEvent("dragenter", at));
    target.dispatchEvent(new DragEvent("dragover", at));
    target.dispatchEvent(new DragEvent("drop", at));
    tag.dispatchEvent(new DragEvent("dragend", init));
    return "ok";
}"""

_USERS_JS = r"""(nodeId) => Array.from(document.querySelectorAll(
    `.react-flow__node[data-id="${nodeId}"] [data-parameter-users] [data-parameter-user]`
)).map((el) => el.getAttribute("data-parameter-user")).sort()"""


def _drag_shared_tag_to_line_end(page, node_id: str, name: str, *, timeout: float = 15000) -> None:
    deadline = time.time() + timeout / 1000
    point = page.evaluate(_LINE_END_POINT_JS, node_id)
    while not point["over"] and time.time() < deadline:
        page.wait_for_timeout(250)
        point = page.evaluate(_LINE_END_POINT_JS, node_id)
    assert point["over"], f"no point past line 1 lies over the code editor: {point['why']}"
    result = page.evaluate(
        _DRAG_SHARED_TAG_JS, {"nodeId": node_id, "name": name, "x": point["x"], "y": point["y"]}
    )
    assert result == "ok", f"could not drag the shared tag into the code: {result}"


def _panel(page, node_id: str):
    return node_locator(page, node_id).locator("[data-parameter-panel]").first


def _wait_for_code_containing(page, node_id: str, text: str, *, timeout: float = 10000) -> None:
    page.wait_for_function(
        """([nodeId, text]) => {
            const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"] .monaco-editor`);
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const ed = editors.find((e) => el && el.contains(e.getDomNode()));
            return !!ed && ed.getValue().includes(text);
        }""",
        arg=[node_id, text],
        timeout=timeout,
    )


def _wait_for_output(page, node_id: str, needle: str, what: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(NODE_TYPE),
        )
    except Exception:
        raise AssertionError(
            f"{what}: the node never printed {needle!r}; its output reads "
            f"{read_node_output_text(page, node_id)!r}"
        ) from None


def _wait_for_users(page, parameter: str, expected: list[str], what: str) -> None:
    try:
        page.wait_for_function(
            f"(nodeId) => JSON.stringify(({_USERS_JS})(nodeId)) === JSON.stringify({sorted(expected)!r})",
            arg=parameter,
            timeout=10000,
        )
    except Exception:
        raise AssertionError(
            f"{what}: the Parameter node lists {page.evaluate(_USERS_JS, parameter)}, not {sorted(expected)}"
        ) from None


def test_one_parameter_node_drives_two_nodes(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Parameter Node",
        username="parameter_node_e2e",
        project_name="Parameter node",
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    a = drag_to_canvas(page, page.locator(CODE_TILE), at=POS_A)
    reader = drag_to_canvas(page, page.locator(CODE_TILE), at=POS_READER)
    b = drag_to_canvas(page, page.locator(CODE_TILE), at=POS_B)
    parameter = drag_to_canvas(page, page.locator(PARAMETER_TILE), at=POS_PARAMETER)
    connect_nodes(page, a, reader)
    set_node_code(page, a, A_TEMPLATE)
    set_node_code(page, reader, READER_CODE)
    set_node_code(page, b, B_CODE)

    # 1. The Parameter node's widget is declared in its body.
    frame_node(page, parameter)
    panel = _panel(page, parameter)
    panel.get_by_label("Widget name").fill("factor")
    panel.get_by_label("Widget type").select_option("number")
    panel.get_by_label("Widget label").fill("Factor")
    panel.get_by_label("Widget default").fill("2")
    panel.get_by_role("button", name="Add parameter").click()
    panel.locator('[data-shared-tag="factor"]').wait_for(state="visible", timeout=10000)

    # 2. Its tag is offered above every node's code. Dragged into the first
    # node, the reference lands where it is dropped and is drawn as a shared
    # chip; the second node names it in typed code. Both are listed as users.
    frame_node(page, a)
    _drag_shared_tag_to_line_end(page, a, "factor")
    _wait_for_code_containing(page, a, "[!! @factor !!]")
    assert read_node_code(page, a) == A_WITH_TAG, (
        "the dropped shared tag did not land where it was dropped (the end of line 1): "
        f"{read_node_code(page, a)!r}"
    )
    node_locator(page, a).locator(".monaco-editor .curio-shared-ref").first.wait_for(
        state="attached", timeout=10000
    )
    assert node_locator(page, a).locator(".monaco-editor .curio-widget-ref-problem").count() == 0
    _wait_for_users(page, parameter, [a, b], "After both nodes named the parameter")

    # 3. A run of each uses the value.
    run_node_and_wait(page, reader, node_type=NODE_TYPE)
    _wait_for_output(page, reader, "<<R 20>>", "With the parameter at 2, below the first node")
    run_node_and_wait(page, b, node_type=NODE_TYPE)
    _wait_for_output(page, b, "<<B 2>>", "With the parameter at 2, in the second node")

    # 4. A new value makes the nodes that use it stale: running the node below
    # the first runs the first again, although its code did not change.
    frame_node(page, parameter)
    control = _panel(page, parameter).get_by_label("Factor", exact=True)
    control.fill("5")
    control.blur()
    play_node(page, reader)
    _wait_for_output(page, reader, "<<R 50>>", "After setting the parameter to 5, below the first node")
    play_node(page, b)
    _wait_for_output(page, b, "<<B 5>>", "After setting the parameter to 5, in the second node")

    # 5. A rename rewrites the references in both nodes.
    frame_node(page, parameter)
    panel = _panel(page, parameter)
    panel.get_by_role("button", name="Edit parameter factor").click()
    panel.get_by_label("Widget name").fill("height_factor")
    panel.get_by_role("button", name="Save parameter").click()
    _wait_for_code_containing(page, a, "[!! @height_factor !!]")
    _wait_for_code_containing(page, b, "[!! @height_factor !!]")
    assert read_node_code(page, a) == A_WITH_TAG.replace("@factor", "@height_factor")
    assert read_node_code(page, b) == B_CODE.replace("@factor", "@height_factor")
    _wait_for_users(page, parameter, [a, b], "After the rename")

    # 6. The widget, its value and the references are saved, with no edge to
    # or from the Parameter node...
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    by_id = {n["id"]: n for n in saved["dataflow"]["nodes"]}
    assert by_id[parameter]["type"].split("@")[0] == PARAMETER_TYPE
    assert by_id[parameter]["metadata"].get("widgets") == [
        {"name": "height_factor", "type": "number", "label": "Factor", "default": 2, "value": 5}
    ], by_id[parameter]["metadata"]
    assert "[!! @height_factor !!]" in by_id[a]["content"]
    assert "[!! @height_factor !!]" in by_id[b]["content"]
    assert not [e for e in saved["dataflow"]["edges"] if parameter in (e["source"], e["target"])]

    # ...and back after a reopen. Left and reopened rather than reloaded in
    # place, so nothing survives in component state.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, parameter).wait_for(state="visible", timeout=45000)
    _wait_for_code_containing(page, a, "[!! @height_factor !!]", timeout=45000)
    frame_node(page, parameter)
    control = _panel(page, parameter).get_by_label("Factor", exact=True)
    control.wait_for(state="visible", timeout=15000)
    assert control.input_value() == "5", (
        f"the reopened parameter reads {control.input_value()!r}, not the 5 that was saved"
    )
    _wait_for_users(page, parameter, [a, b], "After the reopen")
    assert node_locator(page, a).locator(".monaco-editor .curio-widget-ref-problem").count() == 0
