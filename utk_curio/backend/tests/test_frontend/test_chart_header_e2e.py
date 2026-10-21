"""Playwright E2E: a chart's header lists every chip it can use (#662).

The shipped test dataflow ``chicago-loop-shadow-towers.json``, opened with no
run. Its chart "Mean accumulated shadow", Scout's Bars (``curio.scout/bars``),
reads the two scenarios' shadow statistics stacked, ``[!! inputs !!]``, and
draws them with ``[!! scenario colors !!]`` and ``[!! scenario order !!]``:

1. On the chart's Grammar tab, the header above the spec is one row of closed
   categories: Inputs 3 (``input_0``, ``input_1`` and ``inputs``), Scenarios 5,
   Widgets 3 and Shared 1 (the dataflow's Season Parameter node).
2. Opened, Scenarios shows both boxes' swatches, Existing's and Towers
   removed's, as one tag, then text colors and order, then a tag per input in
   the color of the box it comes from.
3. Each of those tags, dragged into the spec, writes its chip where it drops:
   a scale or a list as it is, an input's color in quotes.
4. A close-up of the node with Scenarios open, its spec as shipped.

Nothing runs: the chart's editor is what is checked.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_chart_header_e2e.py -v
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    api_json,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    open_strip_category,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_node_closeup,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "chicago-loop-shadow-towers.json"
TEST_NAME = "test_the_chart_header_lists_its_chips_and_each_scenario_tag_drags_its_chip"
#: Scout's Bars, "Mean accumulated shadow".
CHART = "d0e547ba-e7d6-52e1-9c0e-f047443b715c"
PACKAGES = ("curio.scout@1", "model.scout.deep-umbra@1")
SCENARIO_MIME = "application/x-curio-scenario"
#: Each scenario tag under Scenarios, and what it writes dropped at the end of
#: the spec's first line, outside any string.
SCENARIO_TAGS = [
    ("[data-scenario-swatches]", "[!! scenario colors !!]"),
    ('[data-scenario-chip="text_colors"]', "[!! scenario text_colors !!]"),
    ('[data-scenario-chip="order"]', "[!! scenario order !!]"),
    ('[data-scenario-input="0"]', '"[!! scenario input_0 !!]"'),
    ('[data-scenario-input="1"]', '"[!! scenario input_1 !!]"'),
]

# The header's row, as drawn: each category's name and count, and whether it is open.
_ROW_JS = r"""(nodeId) => Array.from(document.querySelectorAll(
    `.react-flow__node[data-id="${nodeId}"] [data-widget-strip] [data-strip-category]`
)).map((button) => ({
    category: button.getAttribute("data-strip-category"),
    label: `${button.querySelector("[data-strip-name]")?.textContent} ${button.querySelector("[data-strip-count]")?.textContent}`,
    open: button.getAttribute("aria-expanded") === "true",
}))"""

# What Scenarios shows: the swatches' names and colors, and each tag in order.
_SCENARIOS_JS = r"""(nodeId) => {
    const chips = document.querySelector(
        `.react-flow__node[data-id="${nodeId}"] [data-widget-strip] [data-strip-chips="scenarios"]`);
    if (!chips) return null;
    const swatch = (el) => [el.getAttribute("data-scenario-swatch"), el.getAttribute("data-color")];
    return {
        tags: Array.from(chips.children).map((tag) =>
            tag.getAttribute("data-scenario-chip")
            ?? (tag.hasAttribute("data-scenario-swatches") ? "colors" : `input_${tag.getAttribute("data-scenario-input")}`)),
        swatches: Array.from(chips.querySelectorAll("[data-scenario-swatches] [data-scenario-swatch]")).map(swatch),
        inputs: Array.from(chips.querySelectorAll("[data-scenario-input]")).map((tag) => [
            tag.getAttribute("data-scenario-input"),
            tag.querySelector("[data-scenario-swatch]")?.getAttribute("data-scenario-swatch"),
            tag.getAttribute("data-color"),
        ]),
    };
}"""

# Where a drop lands just past the text of the spec's first line, from Monaco's
# own layout of it, and what the page shows there (test_widget_tags_e2e's).
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
    const line = editor.getScrolledVisiblePosition({ lineNumber: 1, column: editor.getModel().getLineMaxColumn(1) });
    if (!line) return { over: false, why: "line 1 is not laid out" };
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

# Drags the tag *selector* under Scenarios and drops it at (x, y), with
# synthetic events: the tag's own onDragStart fills the DataTransfer, and the
# editor's drop handler reads it (test_widget_tags_e2e's).
_DRAG_TAG_TO_POINT_JS = r"""({ nodeId, selector, mime, x, y }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const tag = nodeEl.querySelector(`[data-widget-strip] [data-strip-chips="scenarios"] ${selector}`);
    if (!tag) return `no ${selector} under Scenarios`;
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

# Puts *spec* back in the node's editor, as a user's edit does.
_SET_SPEC_JS = r"""({ nodeId, spec }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return false;
    editor.setValue(spec);
    return editor.getValue() === spec;
}"""


def _drop_at_line_end(page, selector: str, *, timeout: float = 15000) -> None:
    deadline = time.time() + timeout / 1000
    point = page.evaluate(_LINE_END_POINT_JS, CHART)
    while not point["over"] and time.time() < deadline:
        page.wait_for_timeout(250)
        point = page.evaluate(_LINE_END_POINT_JS, CHART)
    assert point["over"], f"no point past line 1 lies over the spec's editor: {point['why']}"
    result = page.evaluate(
        _DRAG_TAG_TO_POINT_JS,
        {"nodeId": CHART, "selector": selector, "mime": SCENARIO_MIME, "x": point["x"], "y": point["y"]},
    )
    assert result == "ok", f"could not drag {selector} into the spec: {result}"


def _wait_for_spec_change(page, before: str, *, timeout: float = 10000) -> str:
    deadline = time.time() + timeout / 1000
    spec = read_node_code(page, CHART)
    while spec == before and time.time() < deadline:
        page.wait_for_timeout(100)
        spec = read_node_code(page, CHART)
    return spec


def test_the_chart_header_lists_its_chips_and_each_scenario_tag_drags_its_chip(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    assert nodes[CHART]["type"] == "curio.scout/bars", nodes[CHART]["type"]
    colors = {scenario["name"]: scenario["color"] for scenario in dataflow["scenarios"]}
    assert colors == {"Existing": "#2a9d8f", "Towers removed": "#e76f51"}, colors

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Chart Header",
        username="chart_header_e2e",
        project_name=dataflow["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    node_locator(page, CHART).wait_for(state="attached", timeout=45000)
    frame_nodes(page, [CHART])
    _open_tab(page, CHART, "grammar")
    node_locator(page, CHART).locator('[data-widget-strip] [data-strip-category="inputs"]').wait_for(
        state="visible", timeout=30000,
    )
    shipped = read_node_code(page, CHART)
    for chip in ('"[!! inputs !!]"', "[!! scenario colors !!]", "[!! scenario order !!]"):
        assert chip in shipped, f"the chart's editor holds no {chip}: {shipped!r}"

    # 1. One row of closed categories, each with its count.
    assert page.evaluate(_ROW_JS, CHART) == [
        {"category": "inputs", "label": "Inputs 3", "open": False},
        {"category": "scenarios", "label": "Scenarios 5", "open": False},
        {"category": "widgets", "label": "Widgets 3", "open": False},
        {"category": "shared", "label": "Shared 1", "open": False},
    ], page.evaluate(_ROW_JS, CHART)

    # 2. Scenarios: both boxes' swatches as one tag, text colors, order, then
    # a tag per input in its box's color.
    open_strip_category(page, CHART, "scenarios")
    shown = page.evaluate(_SCENARIOS_JS, CHART)
    assert shown == {
        "tags": ["colors", "text_colors", "order", "input_0", "input_1"],
        "swatches": [["Existing", "#2a9d8f"], ["Towers removed", "#e76f51"]],
        "inputs": [["0", "Existing", "#2a9d8f"], ["1", "Towers removed", "#e76f51"]],
    }, shown

    # 3. Each tag writes its chip where it drops, the spec put back after each.
    dismiss_toasts(page)
    first, rest = shipped.split("\n", 1)
    for selector, chip in SCENARIO_TAGS:
        _drop_at_line_end(page, selector)
        written = _wait_for_spec_change(page, shipped)
        assert written == f"{first}{chip}\n{rest}", (
            f"{selector} did not write {chip} at the end of the first line: {written.splitlines()[0]!r}"
        )
        assert page.evaluate(_SET_SPEC_JS, {"nodeId": CHART, "spec": shipped}), "could not put the shipped spec back"

    # 4. The node with Scenarios open, over its spec as shipped.
    assert read_node_code(page, CHART) == shipped
    save_node_closeup(page, "chicago-loop-shadow-towers-chart-header", CHART, test_name=TEST_NAME, sweep_toasts=True)
