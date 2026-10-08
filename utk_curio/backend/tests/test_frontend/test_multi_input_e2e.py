"""Playwright E2E: several inputs on one node, read through chips (#662).

A Python node takes several edges: connecting one makes a new empty circle
appear below it. Its code reads each input through a chip dragged from the
strip above the editor, and each column of an input through a column chip.
This drives the whole path in a browser:

1. Two producers into one Python node: the second edge lands on the circle the
   first one made, and a third, empty circle appears.
2. The input tags and a column tag are dragged into the code, where each lands
   at its drop point as a chip.
3. A run reads both inputs: ``[!! input_0 !!]`` is ``input_0``,
   ``[!! input_1 !!]`` is ``input_1``, and the column chip is the column's name.
4. Deleting the first producer closes the gap: the second producer's edge moves
   to circle 0, and the code is renumbered, the deleted input's chip becoming
   ``[!! input_? !!]``. With that line gone, a run reads the one input left as
   ``input_0``.
5. Save and reopen: the circles and the chips are back.

Before, a node held one input, and a second edge was refused.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_multi_input_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_execution_timeout_ms,
    node_locator,
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

TILE = "#tile-computation-analysis"
NODE_TYPE = "curio.builtin/computation-analysis"

# A node is 525x350 at zoom 1 in a 1280x720 viewport: the producers stack in
# the left column so the consumer's circles stay clear of them.
POS_A = (120, 60)
POS_B = (120, 430)
POS_T = (720, 60)

A_CODE = "return 11\n"
B_CODE = "import pandas as pd\nreturn pd.DataFrame({'population': [10, 21]})\n"
T_TEMPLATE = (
    "a = \n"
    "b = \n"
    "col = \n"
    "total = int(b[col].sum())\n"
    "print(f'<<{a}|{total}>>')\n"
    "return total\n"
)
T_WITH_CHIPS = (
    "a = [!! input_0 !!]\n"
    "b = [!! input_1 !!]\n"
    "col = [!! input_1.population !!]\n"
    "total = int(b[col].sum())\n"
    "print(f'<<{a}|{total}>>')\n"
    "return total\n"
)
# What deleting the first producer leaves: input 1 is now input 0.
T_RENUMBERED = (
    "a = [!! input_? !!]\n"
    "b = [!! input_0 !!]\n"
    "col = [!! input_0.population !!]\n"
    "total = int(b[col].sum())\n"
    "print(f'<<{a}|{total}>>')\n"
    "return total\n"
)
T_ONE_INPUT = (
    "b = [!! input_0 !!]\n"
    "col = [!! input_0.population !!]\n"
    "total = int(b[col].sum())\n"
    "print(f'<<{total}>>')\n"
    "return total\n"
)

# Where a drop lands just past the text of one line of a node's editor, from
# Monaco's own layout of that line, scaled to the editor's box on screen.
_LINE_END_POINT_JS = r"""({ nodeId, lineNumber }) => {
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
        lineNumber, column: editor.getModel().getLineMaxColumn(lineNumber),
    });
    if (!line) return { over: false, why: `line ${lineNumber} is not laid out` };
    const scale = box.width / dom.offsetWidth;
    const x = box.left + (line.left + 12) * scale;
    const y = box.top + (line.top + line.height / 2) * scale;
    const hit = document.elementFromPoint(x, y);
    return {
        over: !!hit && dom.contains(hit),
        x, y,
        why: `(${Math.round(x)}, ${Math.round(y)}) shows ${hit ? hit.tagName + "." + hit.className : "nothing"}`,
    };
}"""

# Drags a tag in the strip above a node's code and drops it at (x, y). The
# cursor is parked on the last line first, so a reference that lands on the
# aimed line was placed by the drop point.
_DRAG_TAG_TO_POINT_JS = r"""({ nodeId, selector, mime, x, y }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const tag = nodeEl.querySelector(selector);
    if (!tag) return `no ${selector} in the strip above the code`;
    const editorEl = nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return "no monaco instance owns this node's editor";
    editor.setPosition({ lineNumber: editor.getModel().getLineCount(), column: 1 });
    const target = document.elementFromPoint(x, y);
    if (!target || !editor.getDomNode().contains(target)) return "the drop point left the editor";

    const dt = new DataTransfer();
    const init = { bubbles: true, cancelable: true, composed: true, dataTransfer: dt };
    tag.dispatchEvent(new DragEvent("dragstart", init));
    if (!dt.types.includes(mime)) return `the tag put no ${mime} on the drag`;
    const at = { ...init, clientX: x, clientY: y };
    target.dispatchEvent(new DragEvent("dragenter", at));
    target.dispatchEvent(new DragEvent("dragover", at));
    target.dispatchEvent(new DragEvent("drop", at));
    tag.dispatchEvent(new DragEvent("dragend", init));
    return "ok";
}"""

INPUT_MIME = "application/x-curio-input"


def _drag_tag_to_line_end(page, node_id: str, selector: str, line: int, *, timeout: float = 15000) -> None:
    deadline = time.time() + timeout / 1000
    args = {"nodeId": node_id, "lineNumber": line}
    point = page.evaluate(_LINE_END_POINT_JS, args)
    while not point["over"] and time.time() < deadline:
        page.wait_for_timeout(250)
        point = page.evaluate(_LINE_END_POINT_JS, args)
    assert point["over"], f"no point past line {line} lies over the code editor: {point['why']}"
    result = page.evaluate(
        _DRAG_TAG_TO_POINT_JS,
        {"nodeId": node_id, "selector": selector, "mime": INPUT_MIME, "x": point["x"], "y": point["y"]},
    )
    assert result == "ok", f"could not drag {selector} into the code: {result}"


def _wait_for_code(page, node_id: str, text: str, *, timeout: float = 10000) -> None:
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


def _circles(page, node_id: str) -> list[str]:
    """The input handles a node draws, top to bottom."""
    return page.evaluate(
        """(nodeId) => Array.from(document.querySelectorAll(
            `.react-flow__node[data-id="${nodeId}"] .react-flow__handle.target`))
            .map((h) => h.getAttribute("data-handleid"))""",
        node_id,
    )


def _wait_for_circles(page, node_id: str, expected: list[str]) -> None:
    try:
        page.wait_for_function(
            """([nodeId, expected]) => {
                const ids = Array.from(document.querySelectorAll(
                    `.react-flow__node[data-id="${nodeId}"] .react-flow__handle.target`))
                    .map((h) => h.getAttribute("data-handleid"));
                return JSON.stringify(ids) === JSON.stringify(expected);
            }""",
            arg=[node_id, expected],
            timeout=10000,
        )
    except Exception:
        raise AssertionError(f"node {node_id} draws circles {_circles(page, node_id)}, not {expected}") from None


def _edge_handles(page, target: str) -> dict:
    return page.evaluate(
        """(target) => Object.fromEntries((window.__curio_reactFlow.getEdges() || [])
            .filter((e) => e.target === target).map((e) => [e.source, e.targetHandle]))""",
        target,
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


def _delete_node(page, node_id: str) -> None:
    box = node_locator(page, node_id).bounding_box()
    assert box, f"node {node_id} has no layout box"
    # A point on the header left of its icon buttons selects the node.
    node_locator(page, node_id).click(position={"x": box["width"] * 0.4, "y": 6})
    page.wait_for_function(
        "id => document.querySelector(`.react-flow__node[data-id='${id}']`)?.classList.contains('selected')",
        arg=node_id,
        timeout=10000,
    )
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)",
        arg=node_id,
        timeout=10000,
    )


def test_a_node_reads_several_inputs_through_chips(
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
        name="Several Inputs",
        username="several_inputs_e2e",
        project_name="Several inputs",
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    a = drag_to_canvas(page, page.locator(TILE), at=POS_A)
    b = drag_to_canvas(page, page.locator(TILE), at=POS_B)
    t = drag_to_canvas(page, page.locator(TILE), at=POS_T)
    set_node_code(page, a, A_CODE)
    set_node_code(page, b, B_CODE)
    set_node_code(page, t, T_TEMPLATE)

    # 1. A circle appears for each edge, with a free one below.
    _wait_for_circles(page, t, ["in"])
    connect_nodes(page, a, t)
    _wait_for_circles(page, t, ["in", "in_1"])
    connect_nodes(page, b, t, target_handle="in_1")
    _wait_for_circles(page, t, ["in", "in_1", "in_2"])
    assert _edge_handles(page, t) == {a: "in", b: "in_1"}

    # 2. The input tags and a column tag land where they are dropped, as chips.
    run_node_and_wait(page, a, node_type=NODE_TYPE)
    run_node_and_wait(page, b, node_type=NODE_TYPE)
    dismiss_toasts(page)
    strip = node_locator(page, t).locator("[data-widget-strip]")
    strip.locator('[data-input-tag="1"]').wait_for(state="visible", timeout=10000)
    _drag_tag_to_line_end(page, t, '[data-input-tag="0"]', 1)
    _drag_tag_to_line_end(page, t, '[data-input-tag="1"]', 2)
    strip.get_by_label("Show the columns of input_1").click()
    strip.locator('[data-column-tag="population"]').wait_for(state="visible", timeout=30000)
    _drag_tag_to_line_end(page, t, '[data-column-tag="population"]', 3)
    _wait_for_code(page, t, "[!! input_1.population !!]")
    assert read_node_code(page, t) == T_WITH_CHIPS, (
        f"the dropped tags did not land at the ends of lines 1 to 3: {read_node_code(page, t)!r}"
    )
    node_locator(page, t).locator(".monaco-editor .curio-input-ref").first.wait_for(state="attached", timeout=10000)
    assert node_locator(page, t).locator(".monaco-editor .curio-input-ref-problem").count() == 0

    # 3. A run reads both inputs, in circle order.
    run_node_and_wait(page, t, node_type=NODE_TYPE)
    _wait_for_output(page, t, "<<11|31>>", "With both producers wired")

    # 4. Deleting the first producer closes the gap and renumbers the chips.
    _delete_node(page, a)
    _wait_for_circles(page, t, ["in", "in_1"])
    assert _edge_handles(page, t) == {b: "in"}
    _wait_for_code(page, t, "[!! input_? !!]")
    assert read_node_code(page, t) == T_RENUMBERED, read_node_code(page, t)
    set_node_code(page, t, T_ONE_INPUT)
    run_node_and_wait(page, t, node_type=NODE_TYPE)
    _wait_for_output(page, t, "<<31>>", "With one producer left")

    # 5. Saved, and back after a reopen.
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    edges = [e for e in saved["dataflow"]["edges"] if e["target"] == t]
    assert [(e["source"], e.get("targetHandle")) for e in edges] == [(b, "in")], edges
    assert "[!! input_0.population !!]" in {n["id"]: n for n in saved["dataflow"]["nodes"]}[t]["content"]

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, t).wait_for(state="visible", timeout=45000)
    _wait_for_code(page, t, "[!! input_0.population !!]", timeout=45000)
    _wait_for_circles(page, t, ["in", "in_1"])
    node_locator(page, t).locator('[data-widget-strip] [data-input-tag="0"]').wait_for(state="visible", timeout=15000)
