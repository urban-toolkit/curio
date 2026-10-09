"""Playwright E2E: a brush on a chart reaches a Python node through a selection tag (#662).

A view's current selection is added as a tag in a node's Widgets tab. Its
reference, ``[!! selection name !!]``, becomes the ids of the selected rows: the
values of a column that identifies them (``osm_id`` here), never Vega's
``_vgsid_``. This drives the whole path in a browser, on the server runs a
signed-in canvas makes:

1. Add a tag on the scatterplot, by ``osm_id``, in the counting node's Widgets
   tab, and drag its tag into the node's code.
2. Brush two points. The tag holds their ids; running the node below the
   counting node counts the two rows the Python code picked by those ids.
3. Brush again, over every point. Running the node below runs the counting
   node again, although its code did not change: a new selection makes it
   stale. It counts five.
4. Save: the tag and its ids are in the dataflow. Reopen and run everything:
   the ids are back, the chart declaring its selection again keeps them, and
   the server run reads them.

A second test clicks bars of example 02's zip chart, whose point selection is
named ``zip_select`` and picks rows by their ``zip`` (#768): a tag on that chart
holds one zip after a click, and two after a Shift-click on another bar.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_selection_tags_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    assert_in_view,
    at_fraction,
    brush_area,
    drawing_selector,
    frame_node,
    mark_point,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_code,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    set_node_code,
    stub_login_and_enter_workflow,
)
from .walkthroughs import load_example_spec

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "tag-loader"
SCATTER_ID = "tag-scatter"
COUNTER_ID = "tag-counter"
READER_ID = "tag-reader"
NODE_TYPE = "curio.builtin/computation-analysis"

LOADER_CODE = (
    "import pandas as pd\n"
    "\n"
    "return pd.DataFrame({\n"
    '    "osm_id": [1001, 1002, 1003, 1004, 1005],\n'
    '    "label": ["Alice", "Bob", "Charlie", "Dave", "Eve"],\n'
    '    "value": [30, 10, 50, 20, 40],\n'
    '    "score": [3, 9, 1, 7, 5],\n'
    "})\n"
)

# A brush of its own, and points large enough to aim at. The domains leave room
# past every point, so a brush can start just past the rightmost and lowest one
# (Charlie) and still be inside the plot.
SCATTER_SPEC = """{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "params": [{"name": "brush", "select": {"type": "interval"}}],
  "mark": {"type": "point", "filled": true, "size": 400, "opacity": 1},
  "encoding": {
    "x": {"field": "value", "type": "quantitative", "scale": {"domain": [0, 60]}},
    "y": {"field": "score", "type": "quantitative", "scale": {"domain": [0, 10]}},
    "color": {"value": "blue"}
  },
  "config": {"axis": {"grid": false}}
}"""

COUNTER_START = "print('<<waiting>>')\nreturn arg\n"
COUNTER_CODE = (
    "ids = \n"
    'rows = arg[arg["osm_id"].isin(ids)]\n'
    "print(f\"<<N {len(rows)} {sorted(rows['osm_id'].tolist())}>>\")\n"
    "return rows\n"
)
COUNTER_WITH_TAG = COUNTER_CODE.replace("ids = \n", "ids = [!! selection picked !!]\n", 1)
READER_CODE = "print(f'<<R {len(arg)}>>')\nreturn arg\n"


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "content": content,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": {"keywords": []},
    }


def _edge(source: str, target: str) -> dict:
    return {"id": f"reactflow__edge-{source}out-{target}in", "source": source, "target": target}


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Selection tags",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Selection tags",
            "nodes": [
                _node(LOADER_ID, "curio.builtin/data-loading", 0, 0, LOADER_CODE),
                _node(SCATTER_ID, "curio.builtin/vis-vega", 650, -420, SCATTER_SPEC),
                _node(COUNTER_ID, NODE_TYPE, 650, 120, COUNTER_START),
                _node(READER_ID, NODE_TYPE, 1300, 120, READER_CODE),
            ],
            "edges": [
                _edge(LOADER_ID, SCATTER_ID),
                _edge(LOADER_ID, COUNTER_ID),
                _edge(COUNTER_ID, READER_ID),
            ],
        }
    }


# Where a drop lands just past the text of the editor's first line, from
# Monaco's own layout of that line, and what the page shows at that point (as
# test_widget_tags_e2e.py finds it).
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

# Drags the selection tag in the strip above a node's code and drops it at
# (x, y), with the cursor parked on line 2, so a reference on line 1 was placed
# by the drop point. Synthetic events, like drag_to_canvas.
_DRAG_SELECTION_TAG_JS = r"""({ nodeId, name, x, y }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    if (!nodeEl) return "node is not on the canvas";
    const tag = nodeEl.querySelector(`[data-widget-strip] [data-selection-tag="${name}"]`);
    if (!tag) return "no selection tag in the strip above the code";
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
    if (!dt.types.includes("application/x-curio-selection")) return "the tag put nothing on the drag";
    const at = { ...init, clientX: x, clientY: y };
    target.dispatchEvent(new DragEvent("dragenter", at));
    target.dispatchEvent(new DragEvent("dragover", at));
    target.dispatchEvent(new DragEvent("drop", at));
    tag.dispatchEvent(new DragEvent("dragend", init));
    return "ok";
}"""


def _drag_selection_tag_to_line_end(page, node_id: str, name: str, *, timeout: float = 15000) -> None:
    deadline = time.time() + timeout / 1000
    point = page.evaluate(_LINE_END_POINT_JS, node_id)
    while not point["over"] and time.time() < deadline:
        page.wait_for_timeout(250)
        point = page.evaluate(_LINE_END_POINT_JS, node_id)
    assert point["over"], f"no point past line 1 lies over the code editor: {point['why']}"
    result = page.evaluate(
        _DRAG_SELECTION_TAG_JS, {"nodeId": node_id, "name": name, "x": point["x"], "y": point["y"]}
    )
    assert result == "ok", f"could not drag the selection tag into the code: {result}"


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


def _tag_state(page, node_id: str, name: str) -> str:
    return page.evaluate(
        """([nodeId, name]) => {
            const el = document.querySelector(
                `.react-flow__node[data-id="${nodeId}"] [data-selection-state="${name}"]`);
            return el ? el.textContent : null;
        }""",
        [node_id, name],
    )


def _wait_for_tag_state(page, node_id: str, name: str, expected: str, what: str) -> None:
    """The tag says *expected*. A new selection's ids are written a moment
    after the gesture, and a play saves the dataflow first, so every play here
    waits for this."""
    try:
        page.wait_for_function(
            """([nodeId, name, expected]) => {
                const el = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-selection-state="${name}"]`);
                return !!el && el.textContent === expected;
            }""",
            arg=[node_id, name, expected],
            timeout=15000,
        )
    except Exception:
        raise AssertionError(
            f"{what}: the selection tag reads {_tag_state(page, node_id, name)!r}, not {expected!r}"
        ) from None


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


def _brush(page, start: tuple[float, float], end: tuple[float, float], what: str) -> None:
    page.mouse.move(*assert_in_view(page, *start, f"{what}'s start"))
    page.mouse.down()
    page.mouse.move(*assert_in_view(page, *end, f"{what}'s end"), steps=8)
    page.mouse.up()


# play_node scrolls the node it plays into view, and the browser can do that by
# scrolling an element around the canvas that hides its overflow. The canvas
# then sits that far off wherever it is framed (seen on this test's first CI
# run: the chart framed 300px too high). Every such element is put back first.
_UNSCROLL_JS = r"""(nodeId) => {
    const moved = [];
    const node = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    for (let el = node && node.parentElement; el; el = el.parentElement) {
        if (el.scrollTop || el.scrollLeft) {
            moved.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}: ${el.scrollLeft},${el.scrollTop}`);
            el.scrollTop = 0;
            el.scrollLeft = 0;
        }
    }
    if (window.scrollX || window.scrollY) {
        moved.push(`window: ${window.scrollX},${window.scrollY}`);
        window.scrollTo(0, 0);
    }
    return moved;
}"""


def _scatter_boxes(page) -> tuple[dict, dict]:
    moved = page.evaluate(_UNSCROLL_JS, SCATTER_ID)
    frame_node(page, SCATTER_ID)
    canvas_selector = f"#vega{SCATTER_ID} canvas"
    page.locator(canvas_selector).first.wait_for(state="attached", timeout=60000)
    area = brush_area(page, canvas_selector)
    assert area, "the scatterplot drew no points to brush"
    canvas = page.locator(canvas_selector).first.bounding_box()
    assert canvas, "the scatterplot has no canvas box"
    width, height = page.evaluate("() => [window.innerWidth, window.innerHeight]")
    assert (
        canvas["x"] >= 0 and canvas["y"] >= 0
        and canvas["x"] + canvas["width"] <= width and canvas["y"] + canvas["height"] <= height
    ), f"the framed scatterplot is not in the {width}x{height} window: {canvas}; scrolled back first: {moved}"
    return area, canvas


def test_a_brush_reaches_a_python_node_through_a_selection_tag(
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
        name="Selection Tags",
        username="selection_tags_e2e",
        project_name="Selection tags",
        project_spec=_spec(),
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    for node_id in (LOADER_ID, SCATTER_ID, COUNTER_ID, READER_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    # The chart draws, so the rows a tag reads are known.
    run_all_and_wait(page, timeout_ms=180000)
    _scatter_boxes(page)

    # 1. A tag on the scatterplot, by osm_id, and dragged into the code.
    frame_node(page, COUNTER_ID)
    set_node_code(page, COUNTER_ID, COUNTER_CODE)
    _open_tab(page, COUNTER_ID, "widgets")
    panel = _panel(page, COUNTER_ID)
    panel.get_by_role("button", name="Add selection", exact=True).click()
    assert panel.get_by_label("Selection view").input_value() == SCATTER_ID
    column = panel.get_by_label("Selection id column")
    column.wait_for(state="visible", timeout=15000)
    assert column.input_value() == "osm_id", "osm_id is the column a tag identifies the rows by first"
    panel.get_by_label("Selection tag name").fill("picked")
    panel.get_by_role("button", name="Add selection tag").click()
    panel.locator('[data-selection-row="picked"]').wait_for(state="visible", timeout=10000)
    _wait_for_tag_state(page, COUNTER_ID, "picked", "Nothing selected", "Before any selection")

    _open_tab(page, COUNTER_ID, "code")
    _drag_selection_tag_to_line_end(page, COUNTER_ID, "picked")
    _wait_for_code_containing(page, COUNTER_ID, "[!! selection picked !!]")
    assert read_node_code(page, COUNTER_ID) == COUNTER_WITH_TAG, (
        "the dropped selection tag did not land where it was dropped (the end of line 1): "
        f"{read_node_code(page, COUNTER_ID)!r}"
    )
    node_locator(page, COUNTER_ID).locator(".monaco-editor .curio-selection-ref").first.wait_for(
        state="attached", timeout=10000
    )
    assert node_locator(page, COUNTER_ID).locator(".monaco-editor .curio-widget-ref-problem").count() == 0

    # 2. A brush over the two leftmost points, Bob (10, 9) and Dave (20, 7): from
    # between the points up and left to the canvas's corner, inside the canvas.
    area, canvas = _scatter_boxes(page)
    _brush(page, at_fraction(area, (0.35, 0.5)), (canvas["x"] + 3, canvas["y"] + 3), "the first brush")
    _wait_for_tag_state(page, COUNTER_ID, "picked", "2 selected", "After brushing Bob and Dave")
    play_node(page, READER_ID)
    _wait_for_output(page, READER_ID, "<<R 2>>", "After brushing two points, below the counting node")
    _wait_for_output(page, COUNTER_ID, "<<N 2 [1002, 1004]>>", "After brushing two points")

    # 3. A new brush, over every point: from the corner of the points' box past
    # Charlie (50, 1), outside the first brush, to the canvas's corner. The
    # counting node's code is as it was; its selection is not.
    area, canvas = _scatter_boxes(page)
    _brush(page, at_fraction(area, (1.0, 1.0)), (canvas["x"] + 3, canvas["y"] + 3), "the second brush")
    _wait_for_tag_state(page, COUNTER_ID, "picked", "5 selected", "After brushing every point")
    play_node(page, READER_ID)
    _wait_for_output(page, READER_ID, "<<R 5>>", "After a new selection, below the counting node")
    _wait_for_output(
        page, COUNTER_ID, "<<N 5 [1001, 1002, 1003, 1004, 1005]>>", "After a new selection, in the counting node"
    )

    # 4. The tag and its ids are saved with the dataflow...
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    by_id = {n["id"]: n for n in saved["dataflow"]["nodes"]}
    assert by_id[COUNTER_ID]["metadata"].get("selections") == [
        {"name": "picked", "node": SCATTER_ID, "column": "osm_id", "ids": [1001, 1002, 1003, 1004, 1005]}
    ], by_id[COUNTER_ID]["metadata"]
    assert "[!! selection picked !!]" in by_id[COUNTER_ID]["content"]
    assert "selections" not in (by_id[READER_ID].get("metadata") or {})

    # ...and back after a reopen. Left and reopened rather than reloaded in
    # place, so nothing survives in component state. Running everything draws
    # the chart again, which declares its selection as it compiles: that is
    # not a selection, so the ids stay, and the run saves them again.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, COUNTER_ID).wait_for(state="visible", timeout=45000)
    _wait_for_code_containing(page, COUNTER_ID, "[!! selection picked !!]", timeout=45000)
    run_all_and_wait(page, timeout_ms=180000)
    page.locator(f"#vega{SCATTER_ID} canvas").first.wait_for(state="attached", timeout=60000)
    _wait_for_output(page, READER_ID, "<<R 5>>", "After the reopen, in a run of everything")
    # Room for a late selection event to land before the tag is read.
    page.wait_for_timeout(1500)
    _wait_for_tag_state(page, COUNTER_ID, "picked", "5 selected", "After the reopen and the chart's redraw")
    reopened = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    counter = next(n for n in reopened["dataflow"]["nodes"] if n["id"] == COUNTER_ID)
    assert counter["metadata"].get("selections") == by_id[COUNTER_ID]["metadata"]["selections"], counter["metadata"]
    frame_node(page, COUNTER_ID)
    assert node_locator(page, COUNTER_ID).locator(".monaco-editor .curio-widget-ref-problem").count() == 0


ZIPS_EXAMPLE = "02-vega-lite-spatial-density.json"
#: Example 02's "Top 10 largest zip codes" chart: one horizontal bar per zip,
#: longest first, selected with ``{"name": "zip_select", "select": {"type":
#: "point", "fields": ["zip"], "toggle": "event.shiftKey"}}``.
ZIP_BARS_ID = "d23e2587-57bf-4db4-84fe-cdb7c2de638d"
#: Example 02's data transformation node, which holds the tag on that chart.
ZIP_TAG_NODE_ID = "e5e7e21f-609d-496b-b231-659ee91ff9af"

# The zip of the bar under the pointer: vega's own tooltip handler writes the
# hovered mark's tooltip into the chart's container as its title, one line per
# field ("zip: 60614\nVEGETATED_SQFT: ..."), at every pointer move over it.
_HOVERED_ZIP_JS = r"""(nodeId) => {
    const el = document.getElementById("vega" + nodeId);
    const match = /^zip: (.+)$/m.exec((el && el.getAttribute("title")) || "");
    return match ? match[1] : null;
}"""
_FORGET_HOVER_JS = r"""(nodeId) => {
    const el = document.getElementById("vega" + nodeId);
    if (el) el.removeAttribute("title");
}"""

# The ids a selection tag holds, as text; null when it holds a count instead.
_TAG_IDS_JS = r"""([nodeId, name]) => {
    const rf = window.__curio_reactFlow;
    const node = rf && rf.getNodes().find((n) => n.id === nodeId);
    const tag = ((node && node.data && node.data.selections) || []).find((t) => t.name === name);
    return tag && Array.isArray(tag.ids) ? tag.ids.map(String) : null;
}"""


def _zip_under(page, point: tuple[float, float]) -> str | None:
    """The zip of the bar at *point*, from its tooltip; None off every bar."""
    page.evaluate(_FORGET_HOVER_JS, ZIP_BARS_ID)
    page.mouse.move(*point)
    try:
        page.wait_for_function(
            "(nodeId) => (" + _HOVERED_ZIP_JS + ")(nodeId) !== null", arg=ZIP_BARS_ID, timeout=3000
        )
    except Exception:
        return None
    return page.evaluate(_HOVERED_ZIP_JS, ZIP_BARS_ID)


def _two_zip_bars(page) -> list[tuple[str, tuple[float, float]]]:
    """Two bars of the zip chart, each as its zip and a point on it.

    Found before any click: a selection fades every other bar, and a faded bar
    is no longer a mark ``mark_point`` finds. The points go down the left end
    of the bars, where every bar is drawn, until two of them name different
    zips."""
    page.evaluate(_UNSCROLL_JS, ZIP_BARS_ID)
    frame_node(page, ZIP_BARS_ID)
    page.locator(f"#vega{ZIP_BARS_ID} canvas").first.wait_for(state="attached", timeout=60000)
    selector = drawing_selector(page, ZIP_BARS_ID)
    assert selector, "the zip chart drew nothing"
    bars: list[tuple[str, tuple[float, float]]] = []
    seen: list[str] = []
    for down in (0.05, 0.2, 0.12, 0.28, 0.36, 0.44):
        mark = mark_point(page, selector, (0.1, down))
        if not mark:
            seen.append(f"{down:.0%} down: no bar")
            continue
        point = assert_in_view(page, mark["x"], mark["y"], f"the bar {down:.0%} down the zip chart")
        zip_code = _zip_under(page, point)
        seen.append(f"{down:.0%} down: zip {zip_code}")
        if zip_code is not None and all(zip_code != known for known, _ in bars):
            bars.append((zip_code, point))
        if len(bars) == 2:
            return bars
    raise AssertionError(f"the zip chart showed no two bars to click: {seen}")


def test_a_point_selection_over_fields_reaches_a_selection_tag(
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
        name="Zip Selection Tags",
        username="zip_selection_tags_e2e",
        project_name="Zip selection tags",
        project_spec=load_example_spec(ZIPS_EXAMPLE),
    )
    require_owner_view(page)
    for node_id in (ZIP_TAG_NODE_ID, ZIP_BARS_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    # The chart draws, so the rows a tag reads are known.
    run_all_and_wait(page, timeout_ms=180000)

    # A tag on the zip chart, by zip.
    frame_node(page, ZIP_TAG_NODE_ID)
    _open_tab(page, ZIP_TAG_NODE_ID, "widgets")
    panel = _panel(page, ZIP_TAG_NODE_ID)
    panel.get_by_role("button", name="Add selection", exact=True).click()
    panel.get_by_label("Selection view").select_option(ZIP_BARS_ID)
    column = panel.get_by_label("Selection id column")
    column.wait_for(state="visible", timeout=15000)
    column.select_option("zip")
    assert column.input_value() == "zip"
    panel.get_by_label("Selection tag name").fill("zips")
    panel.get_by_role("button", name="Add selection tag").click()
    panel.locator('[data-selection-row="zips"]').wait_for(state="visible", timeout=10000)
    _wait_for_tag_state(page, ZIP_TAG_NODE_ID, "zips", "Nothing selected", "Before any click on the zip chart")

    # A click on one bar, then a Shift-click on another, which adds it.
    (first, first_at), (second, second_at) = _two_zip_bars(page)
    page.mouse.click(*first_at)
    _wait_for_tag_state(page, ZIP_TAG_NODE_ID, "zips", "1 selected", f"After a click on the bar of zip {first}")
    assert page.evaluate(_TAG_IDS_JS, [ZIP_TAG_NODE_ID, "zips"]) == [first]

    page.keyboard.down("Shift")
    try:
        page.mouse.click(*second_at)
    finally:
        page.keyboard.up("Shift")
    _wait_for_tag_state(
        page, ZIP_TAG_NODE_ID, "zips", "2 selected", f"After a Shift-click on the bar of zip {second}"
    )
    assert sorted(page.evaluate(_TAG_IDS_JS, [ZIP_TAG_NODE_ID, "zips"])) == sorted([first, second])
