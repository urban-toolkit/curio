"""Playwright E2E: a node's output and its error can be selected, and a box
selection selects nodes, not text.

The report: neither a node's output nor its error could be selected, with
the mouse or by double-clicking a word, so nothing in them could be copied.

Each claim is a real gesture, read back from the page's selection:

  * dragging across words selects them, and the node stays where it is;
  * double-clicking a word selects that word;

on a node's output pane, on a failed node's output pane, and on the error
line shown over a failed node.

The second report (komar41's #914): a Shift-drag on the empty canvas draws
the selection box, and the browser also selected the text of everything the
pointer crossed. The box is drawn with the real gesture across two nodes'
output text; it selects both nodes, and no text at any moment of the drag.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_select_node_text_e2e.py -v
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .utils import (
    frame_nodes,
    node_locator,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OK_ID = "select-text-ok"
ERR_ID = "select-text-error"

OK_CODE = 'print("plain marigold output")\nreturn 1\n'
ERR_CODE = 'raise RuntimeError("copyable tangerine failure")\n'


def _node(node_id: str, x: int, content: str) -> dict:
    return {
        "id": node_id, "type": "curio.builtin/computation-analysis", "x": x, "y": 150,
        "content": content, "in": "DEFAULT", "out": "DEFAULT", "goal": "",
        "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {"dataflow": {
        "name": "Select node text", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Select node text",
        "nodes": [_node(OK_ID, 0, OK_CODE), _node(ERR_ID, 645, ERR_CODE)],
        "edges": [],
    }}


#: Where a phrase is drawn inside *selector*: the first occurrence whose start
#: and end the page actually hits there (not covered by anything), after
#: scrolling the target to its end if no occurrence is in view at first.
#: Measured only once the target and the canvas transform have held still for
#: fifteen frames: a canvas still settling after the run moved the text away
#: between the measurement and the press.
_PHRASE_RECT_JS = r"""async ([selector, phrase]) => {
    const target = document.querySelector(selector);
    if (!target) return { error: `nothing matches ${selector}` };
    const viewport = document.querySelector(".react-flow__viewport");
    const where = () => {
        const r = target.getBoundingClientRect();
        return [r.left, r.top, r.width, r.height, viewport ? viewport.style.transform : ""].join(",");
    };
    let last = where();
    let still = 0;
    const started = performance.now();
    while (still < 15 && performance.now() - started < 10000) {
        await new Promise((resolve) => requestAnimationFrame(resolve));
        const now = where();
        still = now === last ? still + 1 : 0;
        last = now;
    }
    if (still < 15) return { error: `${selector} kept moving for 10 s` };
    const hits = (x, y) => {
        const el = document.elementFromPoint(x, y);
        return !!el && target.contains(el);
    };
    const find = () => {
        const walker = document.createTreeWalker(target, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            let from = node.data.indexOf(phrase);
            while (from >= 0) {
                const range = document.createRange();
                range.setStart(node, from);
                range.setEnd(node, from + phrase.length);
                const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0);
                if (rects.length) {
                    const first = rects[0];
                    const last = rects[rects.length - 1];
                    const y = first.top + first.height / 2;
                    const start = { x: first.left + 1, y };
                    const end = { x: last.right - 1, y: last.top + last.height / 2 };
                    if (hits(start.x, start.y) && hits(end.x, end.y)) return { start, end };
                }
                from = node.data.indexOf(phrase, from + 1);
            }
        }
        return null;
    };
    let found = find();
    if (!found) {
        target.scrollTop = target.scrollHeight;
        found = find();
    }
    return found || { error: `"${phrase}" is not visible in ${selector}` };
}"""

_CLEAR_SELECTION_JS = "() => window.getSelection().removeAllRanges()"
_SELECTION_JS = "() => window.getSelection().toString()"


def _node_position(page, node_id: str) -> tuple[float, float]:
    return tuple(page.evaluate(
        """(id) => {
            const node = window.__curio_reactFlow.getNode(id);
            return [node.position.x, node.position.y];
        }""",
        node_id,
    ))


def _drag_select(page, selector: str, phrase: str, node_id: str) -> dict:
    """Press at the phrase's first letter, move to its last, release."""
    rect = page.evaluate(_PHRASE_RECT_JS, [selector, phrase])
    if "error" in rect:
        return rect
    page.evaluate(_CLEAR_SELECTION_JS)
    before = _node_position(page, node_id)
    page.mouse.move(rect["start"]["x"], rect["start"]["y"])
    page.mouse.down()
    page.mouse.move(rect["end"]["x"], rect["end"]["y"], steps=12)
    page.mouse.up()
    selected = page.evaluate(_SELECTION_JS)
    return {"selected": selected, "node_moved": _node_position(page, node_id) != before}


def _double_click_select(page, selector: str, word: str) -> dict:
    rect = page.evaluate(_PHRASE_RECT_JS, [selector, word])
    if "error" in rect:
        return rect
    page.evaluate(_CLEAR_SELECTION_JS)
    x = (rect["start"]["x"] + rect["end"]["x"]) / 2
    page.mouse.dblclick(x, rect["start"]["y"])
    return {"selected": page.evaluate(_SELECTION_JS).strip()}


def test_a_nodes_output_and_error_can_be_selected(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    page.emulate_media(reduced_motion="reduce")
    # Opened as a saved dataflow, not loaded with File > Load: a loaded file
    # opens as the browser user's own dataflow (#751), and on the isolated
    # stack, which has no accounts, this one opens read-only for the shared
    # guest, where a node's text is selected differently (#685).
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Select Text",
        username="select_node_text",
        project_name="Select node text",
        project_spec=_spec(),
    )
    for node_id in (OK_ID, ERR_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    assert wait_for_node_settled(page, OK_ID, node_type="COMPUTATION_ANALYSIS") == "done"
    assert wait_for_node_settled(page, ERR_ID, node_type="COMPUTATION_ANALYSIS") == "error"
    # The output pane is on the code tab, as read_node_error_text finds it.
    for node_id in (OK_ID, ERR_ID):
        code_tab = node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="code"]').first
        if code_tab.count() and "active" not in (code_tab.get_attribute("class") or ""):
            code_tab.click(force=True)
        node_locator(page, node_id).locator("[data-curio-node-output]").first.wait_for(
            state="visible", timeout=10000
        )

    output = '.react-flow__node[data-id="{}"] [data-curio-node-output="true"]'
    strip = '[data-testid="node-outcome-{}"]'
    targets = {
        "output pane": (output.format(OK_ID), OK_ID, "marigold output", "marigold"),
        "error in the output pane": (output.format(ERR_ID), ERR_ID, "tangerine failure", "tangerine"),
        "error line over the node": (strip.format(ERR_ID), ERR_ID, "tangerine failure", "tangerine"),
    }
    seen = {}
    for name, (selector, node_id, phrase, word) in targets.items():
        seen[name] = {
            "drag": _drag_select(page, selector, phrase, node_id),
            "double-click": _double_click_select(page, selector, word),
        }

    # Every target, both gestures, in one assertion: what fails shows beside
    # what works.
    expected = {
        name: {
            "drag": {"selected": phrase, "node_moved": False},
            "double-click": {"selected": word},
        }
        for name, (_selector, _node_id, phrase, word) in targets.items()
    }
    assert seen == expected, json.dumps(seen, indent=2)


BOX_LEFT_ID = "box-select-left"
BOX_RIGHT_ID = "box-select-right"

#: What a code node's output pane says before any run: plain text that a drag
#: across it can select.
NO_OUTPUT = "No output yet"


def _box_spec() -> dict:
    return {"dataflow": {
        "name": "Box select", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Box select",
        "nodes": [_node(BOX_LEFT_ID, 0, "return 1\n"), _node(BOX_RIGHT_ID, 645, "return 2\n")],
        "edges": [],
    }}


#: Whether a point is on the empty canvas: React Flow starts its selection box
#: only from a press on the pane itself.
_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""

#: Clear the selection, then keep every text the page selects from now on, as
#: its ``selectionchange`` events report it, so text that a drag selects and
#: lets go again before the release counts too.
_RECORD_SELECTIONS_JS = """() => {
    window.getSelection().removeAllRanges();
    window.__curio_selectedTexts = [];
    document.addEventListener("selectionchange", () => {
        const text = window.getSelection().toString();
        if (text.trim()) window.__curio_selectedTexts.push(text);
    });
}"""

#: What was recorded, once the selection events already queued are handled.
_SELECTED_TEXTS_JS = """async () => {
    await new Promise((resolve) => setTimeout(resolve, 100));
    return window.__curio_selectedTexts;
}"""

_SELECTED_NODES_JS = (
    "() => window.__curio_reactFlow.getNodes().filter((n) => n.selected).map((n) => n.id).sort()"
)


def test_a_box_selection_selects_nodes_and_no_text(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Box Select",
        username="box_select_text",
        project_name="Box select",
        project_spec=_box_spec(),
    )
    node_ids = [BOX_LEFT_ID, BOX_RIGHT_ID]
    for node_id in node_ids:
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)
        # The output pane is on the code tab.
        code_tab = node_locator(page, node_id).locator('.nav-link[data-rr-ui-event-key="code"]').first
        if code_tab.count() and "active" not in (code_tab.get_attribute("class") or ""):
            code_tab.click(force=True)
        node_locator(page, node_id).locator("[data-curio-node-output]").first.wait_for(
            state="visible", timeout=10000
        )
    frame_nodes(page, node_ids)

    # Where each node's output text is drawn, and a box around both nodes, from
    # the empty canvas above and left of them to below and right of them.
    output = '.react-flow__node[data-id="{}"] [data-curio-node-output="true"]'
    texts = {node_id: page.evaluate(_PHRASE_RECT_JS, [output.format(node_id), NO_OUTPUT]) for node_id in node_ids}
    assert all("error" not in rect for rect in texts.values()), json.dumps(texts, indent=2)
    boxes = [node_locator(page, node_id).bounding_box() for node_id in node_ids]
    left = min(b["x"] for b in boxes) - 12
    top = min(b["y"] for b in boxes) - 12
    right = max(b["x"] + b["width"] for b in boxes) + 12
    bottom = max(b["y"] + b["height"] for b in boxes) + 12
    for point in ((left, top), (right, bottom)):
        assert page.evaluate(_ON_PANE_JS, list(point)), f"{point} is not on the empty canvas"

    # Shift, a press on the empty canvas, and a drag whose pointer crosses each
    # node's output text on its way to the box's far corner. The drag goes
    # right and down, so the pointer stays at the box's open bottom-right edge,
    # over the text, not over the box React Flow draws.
    page.evaluate(_RECORD_SELECTIONS_JS)
    page.mouse.move(left, top)
    page.keyboard.down("Shift")
    try:
        page.mouse.down()
        for node_id in (BOX_LEFT_ID, BOX_RIGHT_ID):
            rect = texts[node_id]
            page.mouse.move(rect["start"]["x"], rect["start"]["y"], steps=8)
            page.mouse.move(rect["end"]["x"], rect["end"]["y"], steps=8)
        page.mouse.move(right, bottom, steps=12)
        page.mouse.up()
    finally:
        page.keyboard.up("Shift")

    seen = {
        "nodes the box selected": page.evaluate(_SELECTED_NODES_JS),
        "text selected during the drag": page.evaluate(_SELECTED_TEXTS_JS),
        "text selected after it": page.evaluate(_SELECTION_JS),
    }
    expected = {
        "nodes the box selected": sorted(node_ids),
        "text selected during the drag": [],
        "text selected after it": "",
    }
    assert seen == expected, json.dumps(seen, indent=2)
