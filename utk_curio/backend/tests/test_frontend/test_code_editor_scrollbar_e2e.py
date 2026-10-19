"""Playwright E2E: a node's code or spec editor scrolls as a Jupyter cell does (#1004).

Code is never wrapped and no line break is added to it: a line longer than its
editor scrolls sideways. Whenever an editor's code runs past one of its sides,
the bar of that side shows at rest, with the pointer away. It is the thin
scrollbar of Curio's panels (``styles/scrollbars.module.css``), as
``test_widget_panel_scrollbar_e2e.py`` reads it: 6 px, with a thumb of
``rgba(30, 31, 35, 0.18)``. An editor whose code fits shows no bar.

The editor is Monaco, which draws its bars as elements of its own, not the
browser's. By default it shows a bar only while the pointer is over the editor
or the editor scrolls, hides it 500 ms later and fades it out over 800 ms, so
a capture caught the bar on one run and missed it on the next.

The dataflow holds four nodes and no edges, so nothing runs:

- a Python node with one line longer than its editor: its horizontal bar shows, its vertical one does not;
- a Python node with more lines than its editor shows: its vertical bar shows, its horizontal one does not;
- a Python node whose two short lines fit: no bar;
- a Vega-Lite node whose spec has one long line, in the spec editor (``GrammarEditor``): its horizontal bar shows.

The test checks:

1. Each editor holds its code as written, and each line is one row: the long
   lines are not wrapped.
2. The pointer passes over every editor, where Monaco shows its bars, then
   rests on the bare canvas past Monaco's fade.
3. Each bar shows exactly where its editor's code runs past that side, and
   every bar, shown or not, is 6 px with the shared thumb. All four editors are
   read in one assertion, so a failure lists every one.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_code_editor_scrollbar_e2e.py -v
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .test_widget_panel_scrollbar_e2e import BAR_PX, THUMB
from .utils import (
    frame_nodes,
    node_locator,
    park_pointer,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_login,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PYTHON_TYPE = "curio.builtin/computation-analysis"
VEGA_TYPE = "curio.builtin/vis-vega"

#: One line far longer than a node's editor is wide.
WIDE_CODE = (
    'label = "Average flood depth by census tract, in metres, with and without the nature-based '
    'solutions of each period, for every one of the tracts in the Quad Cities"\n'
    "return label\n"
)
#: Far more lines than a node's editor shows, each one short.
TALL_CODE = "".join(f"step_{i} = {i}\n" for i in range(1, 41)) + "return step_40\n"
#: Two short lines.
FITS_CODE = "total = 1 + 1\nreturn total\n"
#: A Vega-Lite spec whose description is one long line.
WIDE_SPEC = json.dumps(
    {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "description": (
            "Average flood depth by census tract, in metres, with and without the nature-based "
            "solutions of each period, for every one of the tracts in the Quad Cities"
        ),
        "mark": "bar",
    },
    indent=2,
)

#: Each editor: its node's type, the tab its editor is on, its code, where it
#: sits, and which of its sides the code runs past.
EDITORS = {
    "editor-wide": (PYTHON_TYPE, "code", WIDE_CODE, (0, 0), {"horizontal": True, "vertical": False}),
    "editor-tall": (PYTHON_TYPE, "code", TALL_CODE, (620, 0), {"horizontal": False, "vertical": True}),
    "editor-fits": (PYTHON_TYPE, "code", FITS_CODE, (0, 460), {"horizontal": False, "vertical": False}),
    "spec-wide": (VEGA_TYPE, "grammar", WIDE_SPEC, (620, 460), {"horizontal": True, "vertical": False}),
}

#: How long the pointer rests away from the editors before the bars are read:
#: past Monaco's hide, 500 ms after the pointer leaves (HIDE_TIMEOUT in its
#: scrollableElement.js), and its 800 ms fade (``.invisible.fade`` in its
#: scrollbars.css).
AT_REST_MS = 2000

#: The node's Monaco editor, found as the other e2e helpers find it, once it
#: is laid out at a size and holds *code*.
_EDITOR_HOLDS_JS = r"""({ nodeId, code }) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return false;
    const dom = editor.getDomNode();
    return dom.offsetWidth > 0 && dom.offsetHeight > 0
        && editor.getValue().replace(/\r\n/g, "\n") === code;
}"""

#: An editor's lines and rows, which of its sides its code runs past (as
#: Monaco measures it), and its two bars. A bar is ``shown`` when Monaco reveals
#: it and it is opaque; a hidden one keeps its element at opacity 0. ``px`` is
#: its thickness on the page before the canvas zoom, and ``thumb`` its slider's
#: colour.
_EDITOR_BARS_JS = r"""(nodeId) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editors.find((e) => editorEl && editorEl.contains(e.getDomNode()));
    if (!editor) return null;
    const dom = editor.getDomNode();
    const layout = editor.getLayoutInfo();
    const lines = editor.getModel().getLineCount();
    const lineHeight = editor.getOption(window.monaco.editor.EditorOption.lineHeight);
    const bar = (side) => {
        const track = dom.querySelector(`.editor-scrollable > .scrollbar.${side}`);
        if (!track) return null;
        const slider = track.querySelector(".slider");
        return {
            shown: track.classList.contains("visible") && getComputedStyle(track).opacity === "1",
            px: side === "horizontal" ? track.offsetHeight : track.offsetWidth,
            thumb: slider ? getComputedStyle(slider).backgroundColor : null,
        };
    };
    return {
        lines,
        rows: Math.round((editor.getTopForLineNumber(lines) - editor.getTopForLineNumber(1)) / lineHeight) + 1,
        overflows: {
            horizontal: editor.getScrollWidth() > layout.contentWidth,
            vertical: editor.getScrollHeight() > layout.height,
        },
        horizontal: bar("horizontal"),
        vertical: bar("vertical"),
    };
}"""


def _spec() -> dict:
    nodes = [
        {
            "id": node_id, "type": node_type, "x": x, "y": y, "content": code,
            "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
        }
        for node_id, (node_type, _tab, code, (x, y), _overflows) in EDITORS.items()
    ]
    return {"dataflow": {"name": "Code editor scrollbar", "task": "", "nodes": nodes, "edges": []}}


def _show_editor(page, node_id: str, tab: str, code: str) -> None:
    """Bring the node's editor tab forward and wait for its editor to hold *code*."""
    tab_link = node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{tab}"]').first
    tab_link.wait_for(state="visible", timeout=45000)
    if "active" not in (tab_link.get_attribute("class") or ""):
        tab_link.dispatch_event("click")
    page.wait_for_function(_EDITOR_HOLDS_JS, arg={"nodeId": node_id, "code": code}, timeout=30000)


def test_code_editors_show_the_shared_scrollbar_at_rest_where_their_code_overflows(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_db_login(
        page,
        app_frontend.base_url,
        current_server,
        username="code_editor_scrollbar_e2e",
        name="Code Editor Scrollbar",
        project_name="Code editor scrollbar",
        project_spec=_spec(),
    )
    page.goto(f"{app_frontend.base_url}/dataflow/{session['project']['id']}", timeout=120000)
    page.wait_for_load_state("domcontentloaded")
    require_owner_view(page)

    # 1. Each editor holds its code as written, in view.
    for node_id, (_type, tab, code, _at, _overflows) in EDITORS.items():
        _show_editor(page, node_id, tab, code)
    frame_nodes(page, list(EDITORS))

    # 2. The pointer passes over each editor, where Monaco shows its bars, and
    #    then rests on the bare canvas past Monaco's fade.
    for node_id in EDITORS:
        box = node_locator(page, node_id).locator(".monaco-editor").first.bounding_box()
        assert box, f"the editor of {node_id} is not on the page"
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=4)
        page.wait_for_timeout(200)
    park_pointer(page)
    page.wait_for_timeout(AT_REST_MS)

    # 3. Each bar shows where its editor's code runs past that side, and only
    #    there; each line is one row; every bar is the shared 6 px one.
    seen = {node_id: page.evaluate(_EDITOR_BARS_JS, node_id) for node_id in EDITORS}
    missing = [node_id for node_id, drawn in seen.items() if drawn is None]
    assert not missing, f"no Monaco editor found in {missing}"
    wanted = {
        node_id: {
            "lines": seen[node_id]["lines"],
            "rows": seen[node_id]["lines"],
            "overflows": overflows,
            **{
                side: {"shown": overflows[side], "px": BAR_PX, "thumb": THUMB}
                for side in ("horizontal", "vertical")
            },
        }
        for node_id, (_type, _tab, _code, _at, overflows) in EDITORS.items()
    }
    assert seen == wanted, (
        "a code editor does not scroll as a Jupyter cell does: each line one row, and at rest a "
        f"{BAR_PX} px bar with the thumb {THUMB} on each side its code runs past, and none on a "
        f"side it fits: {seen}"
    )
