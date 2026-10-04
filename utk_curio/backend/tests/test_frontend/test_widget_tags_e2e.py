"""Playwright E2E: a widget added as a tag drives the code it is dragged into (#662).

A node's widgets are declared in its Widgets tab. Each shows as a tag, which is
dragged into the code as a ``[!! name !!]`` reference; a run replaces the
reference with the widget's value. This drives the whole path in a browser:

1. Add a number widget in the panel, and drag its tag from the strip above the
   code editor to the end of the first line. The reference lands where it is
   dropped, not at the cursor, and is drawn as a chip.
2. Run the node below it: the value reaches the sandbox.
3. Change the value and run the node below again. The widget's node runs again
   too, although its code text did not change: a changed value makes it stale.
4. Save and reopen: the widget, its value and the reference are all back.

Before, a widget was a ``[!! name$TYPE$default !!]`` marker typed into the
code, a new value did not re-run an ancestor, and a save kept no value at all.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_widget_tags_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    connect_nodes,
    drag_to_canvas,
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

TILE = "#tile-computation-analysis"
NODE_TYPE = "curio.builtin/computation-analysis"

SOURCE_CODE = "factor = \nreturn factor * 10\n"
SOURCE_WITH_REFERENCE = "factor = [!! factor !!]\nreturn factor * 10\n"
READER_CODE = "print(f'<<{arg}>>')\nreturn arg\n"

# Where a drop lands just past the text of the editor's first line, from
# Monaco's own layout of that line (scaled to the editor's box on screen, so a
# zoomed canvas does not move it), and what the page shows at that point. Right
# after a tab switch the editor can still be laid out at no size, so the test
# polls this until the point is over the editor.
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
    return {
        over: !!hit && dom.contains(hit),
        x, y,
        why: `(${Math.round(x)}, ${Math.round(y)}) shows ${hit ? hit.tagName + "." + hit.className : "nothing"}; `
            + `editor box ${Math.round(box.left)},${Math.round(box.top)} ${Math.round(box.width)}x${Math.round(box.height)}`,
    };
}"""

# Drags the tag in the strip above a node's code editor and drops it at (x, y).
# The cursor is parked on line 2 first, so a reference that lands on line 1 was
# placed by the drop point. Synthetic events, like drag_to_canvas: the tag's own
# onDragStart fills the DataTransfer, and the editor's drop handler reads it.
_DRAG_TAG_TO_POINT_JS = r"""({ nodeId, name, x, y }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const tag = nodeEl.querySelector(`[data-widget-strip] [data-widget-tag="${name}"]`);
    if (!tag) return "no tag in the strip above the code";
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
    if (!dt.types.includes("application/x-curio-widget")) return "the tag put nothing on the drag";
    const at = { ...init, clientX: x, clientY: y };
    target.dispatchEvent(new DragEvent("dragenter", at));
    target.dispatchEvent(new DragEvent("dragover", at));
    target.dispatchEvent(new DragEvent("drop", at));
    tag.dispatchEvent(new DragEvent("dragend", init));
    return "ok";
}"""


def _drag_tag_to_line_end(page, node_id: str, name: str, *, timeout: float = 15000) -> None:
    deadline = time.time() + timeout / 1000
    point = page.evaluate(_LINE_END_POINT_JS, node_id)
    while not point["over"] and time.time() < deadline:
        page.wait_for_timeout(250)
        point = page.evaluate(_LINE_END_POINT_JS, node_id)
    assert point["over"], f"no point past line 1 lies over the code editor: {point['why']}"
    result = page.evaluate(
        _DRAG_TAG_TO_POINT_JS, {"nodeId": node_id, "name": name, "x": point["x"], "y": point["y"]}
    )
    assert result == "ok", f"could not drag the tag into the code: {result}"


def _open_tab(page, node_id: str, key: str) -> None:
    tab = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{key}"]').first
    tab.wait_for(state="visible", timeout=15000)
    if "active" not in (tab.get_attribute("class") or ""):
        tab.dispatch_event("click")
    page.wait_for_function(
        """([nodeId, key]) => {
            const el = document.querySelector(
                `.react-flow__node[data-id="${nodeId}"] .nav-link[data-rr-ui-event-key="${key}"]`);
            return !!el && el.classList.contains("active");
        }""",
        arg=[node_id, key],
        timeout=10000,
    )


def _panel(page, node_id: str):
    return node_locator(page, node_id).locator("[data-widgets-panel]").first


def _add_number_widget(page, node_id: str, *, name: str, label: str, default: int) -> None:
    _open_tab(page, node_id, "widgets")
    panel = _panel(page, node_id)
    panel.get_by_role("button", name="Add widget").click()
    panel.get_by_label("Widget name").fill(name)
    panel.get_by_label("Widget type").select_option("number")
    panel.get_by_label("Widget label").fill(label)
    panel.get_by_label("Widget default").fill(str(default))
    panel.get_by_role("button", name="Add widget").click()
    panel.locator(f'[data-widget-row="{name}"]').wait_for(state="visible", timeout=10000)


def _set_number(page, node_id: str, label: str, value: int) -> None:
    _open_tab(page, node_id, "widgets")
    _panel(page, node_id).get_by_label(label, exact=True).fill(str(value))


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
            f"{what}: the node below never printed {needle!r}; its output reads "
            f"{read_node_output_text(page, node_id)!r}"
        ) from None


def test_a_widget_tag_drives_the_code_and_survives_a_reopen(
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
        name="Widget Tags",
        username="widget_tags_e2e",
        project_name="Widget tags",
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    source = drag_to_canvas(page, page.locator(TILE), at=(150, 150))
    reader = drag_to_canvas(page, page.locator(TILE), at=(760, 150))
    connect_nodes(page, source, reader)
    set_node_code(page, source, SOURCE_CODE)
    set_node_code(page, reader, READER_CODE)

    # 1. The widget is added in the panel, and its tag dragged into the code.
    _add_number_widget(page, source, name="factor", label="Factor", default=2)
    _open_tab(page, source, "code")
    strip_tag = node_locator(page, source).locator('[data-widget-strip] [data-widget-tag="factor"]')
    strip_tag.wait_for(state="visible", timeout=10000)
    _drag_tag_to_line_end(page, source, "factor")
    _wait_for_code_containing(page, source, "[!! factor !!]")
    assert read_node_code(page, source) == SOURCE_WITH_REFERENCE, (
        "the dropped tag did not land where it was dropped (the end of line 1): "
        f"{read_node_code(page, source)!r}"
    )
    chip = node_locator(page, source).locator(".monaco-editor .curio-widget-ref")
    chip.first.wait_for(state="attached", timeout=10000)
    assert node_locator(page, source).locator(".monaco-editor .curio-widget-ref-problem").count() == 0

    # 2. A run uses the widget's value.
    run_node_and_wait(page, reader, node_type=NODE_TYPE)
    _wait_for_output(page, reader, "<<20>>", "With the widget at 2")

    # 3. A new value makes the widget's node stale: running the node below
    # runs it again, so the new value reaches the node below.
    _set_number(page, source, "Factor", 5)
    play_node(page, reader)
    _wait_for_output(page, reader, "<<50>>", "After setting the widget to 5")

    # 4. The widget, its value and the reference are saved...
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    by_id = {n["id"]: n for n in saved["dataflow"]["nodes"]}
    assert by_id[source]["metadata"].get("widgets") == [
        {"name": "factor", "type": "number", "label": "Factor", "default": 2, "value": 5}
    ], by_id[source]["metadata"]
    assert "[!! factor !!]" in by_id[source]["content"]
    assert "widgets" not in by_id[reader].get("metadata", {})

    # ...and back after a reopen. Left and reopened rather than reloaded in
    # place, so nothing survives in component state.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, source).wait_for(state="visible", timeout=45000)
    _wait_for_code_containing(page, source, "[!! factor !!]", timeout=45000)
    _open_tab(page, source, "widgets")
    control = _panel(page, source).get_by_label("Factor", exact=True)
    control.wait_for(state="visible", timeout=15000)
    assert control.input_value() == "5", (
        f"the reopened widget reads {control.input_value()!r}, not the 5 that was saved"
    )
