"""Playwright E2E: a node's output and its error can be selected.

The report: neither a node's output nor its error could be selected, with
the mouse or by double-clicking a word, so nothing in them could be copied.

Each claim is a real gesture, read back from the page's selection:

  * dragging across words selects them, and the node stays where it is;
  * double-clicking a word selects that word;

on a node's output pane, on a failed node's output pane, and on the error
line shown over a failed node.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_select_node_text_e2e.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    upload_workflow,
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
_PHRASE_RECT_JS = r"""([selector, phrase]) => {
    const target = document.querySelector(selector);
    if (!target) return { error: `nothing matches ${selector}` };
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
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Select Text",
        username="select_node_text",
        project_name="Select node text",
    )
    spec_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8")
    json.dump(_spec(), spec_file)
    spec_file.close()
    try:
        upload_workflow(page, app_frontend, spec_file.name, 2)
    finally:
        os.unlink(spec_file.name)
    for node_id in (OK_ID, ERR_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)
    assert wait_for_node_settled(page, OK_ID, node_type="COMPUTATION_ANALYSIS") == "success"
    assert wait_for_node_settled(page, ERR_ID, node_type="COMPUTATION_ANALYSIS") == "error"

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
