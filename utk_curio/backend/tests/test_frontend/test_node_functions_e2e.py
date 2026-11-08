"""Playwright E2E: Functions, what a node's code can call, in the header above
its code.

Example 24, SCOUT's shadow model on Chicago Loop, as it opens, with no run:

1. Accumulated Shadow (Deep Umbra's node) lists its own package's functions
   first, ``accumulated_shadow`` and ``season_factor`` under ``deep_umbra``,
   then Rasterization's, which Deep Umbra depends on, by module, then Curio's
   own. The Raster Calculator, Rasterization's node, lists Rasterization's and
   Curio's: a package's nodes list their own package's functions.
2. A hover of ``season_factor``'s tag shows, in the one Curio tooltip, its
   call, ``season_factor(season)``, and the first paragraph of its docstring.
   A frame of it, as tightly compared as a node's close-up.
3. A click on it writes its call at the cursor, and its import after the code's
   first import, which the code lacks; a click on one of Curio's writes its
   call alone.

The header is an element, so its tag is hovered with ``hover_until_tooltip_says``
(utils/tooltips). None of this needs a GPU: the maps stay undrawn on a CPU
runner, and nothing here reads them.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_functions_e2e.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

from .test_widget_tags_e2e import _open_tab
from .utils import (
    CLOSEUP_MAX_DIFF_RATIO,
    CLOSEUP_PIXEL_THRESHOLD,
    REPO_ROOT,
    api_json,
    frame_nodes,
    hover_until_tooltip_says,
    node_locator,
    open_strip_category,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    tooltip_close_up,
)

EXAMPLE =Path(REPO_ROOT) / "docs" / "examples" / "24-scout-shadow-model-chicago-loop.json"
#: Example 24's Accumulated Shadow and Raster Calculator.
SHADOW = "45abcfa2-7705-50d4-adf2-db8f556a59c6"
CALCULATOR = "8a914e39-4cb1-535d-9a8b-19b45f6be288"
PACKAGES = ("curio.rasterization@1", "model.scout.deep-umbra@1")

#: The stem of this module's frames.
STEM = "node-functions"
#: How long the header may take to read what the code can call, in ms.
READ_MS = 30000

#: Each line under Functions, as ``(its group, its tags)``.
_GROUPS_JS = """(nodeId) => [...document.querySelectorAll(
    `.react-flow__node[data-id="${nodeId}"] [data-widget-strip] [data-strip-chips="functions"] [data-function-group]`)]
    .map((line) => [line.getAttribute("data-function-group"),
        [...line.querySelectorAll("[data-function-tag]")].map((tag) => tag.textContent)])"""

#: Puts the cursor of *nodeId*'s editor at the end of its code.
_CURSOR_AT_THE_END_JS = """(nodeId) => {
    const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
    const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const editor = editorEl && editors.find((e) => editorEl.contains(e.getDomNode()));
    if (!editor) return null;
    const model = editor.getModel();
    const line = model.getLineCount();
    editor.setPosition({ lineNumber: line, column: model.getLineMaxColumn(line) });
    return line;
}"""


def _open_example(page, app_frontend, current_server: str) -> None:
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Node Functions",
        username="node_functions_e2e",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in (SHADOW, CALCULATOR):
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)


def _groups(page, node_id: str) -> list:
    """Opens Functions above *node_id*'s code, and gives each of its lines."""
    _open_tab(page, node_id, "code")
    open_strip_category(page, node_id, "functions", timeout=READ_MS)
    return [[group, tags] for group, tags in page.evaluate(_GROUPS_JS, node_id)]


def test_a_nodes_functions_show_beside_its_inputs_say_what_they_do_and_write_their_call(
    app_frontend,
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()
    _open_example(page, app_frontend, current_server)

    # 1. Rasterization's node: its own package's modules, then Curio's.
    frame_nodes(page, [CALCULATOR])
    calculator = _groups(page, CALCULATOR)
    assert [group for group, _tags in calculator] == [
        "scout_rasters.mosaic", "scout_rasters.node_outputs", "scout_rasters.raster_algebra",
        "scout_rasters.web_tiles", "curio",
    ], calculator
    assert calculator[0][1] == ["mosaic_rasters", "mosaic_collection"], calculator
    assert calculator[2][1] == ["raster_calculate", "raster_statistics"], calculator

    # Deep Umbra's node: its own package's first, then Rasterization's, then Curio's.
    frame_nodes(page, [SHADOW])
    shadow = _groups(page, SHADOW)
    assert shadow[0] == ["deep_umbra", ["accumulated_shadow", "season_factor"]], shadow
    assert [group for group, _tags in shadow[1:]] == [group for group, _tags in calculator], shadow
    assert {"curio_load_model", "curio_output_file"} <= set(shadow[-1][1]), shadow
    # Beside Inputs.
    row = page.evaluate(
        """(nodeId) => [...document.querySelectorAll(
            `.react-flow__node[data-id="${nodeId}"] [data-widget-strip] [data-strip-category]`)]
            .map((button) => button.getAttribute("data-strip-category"))""",
        SHADOW,
    )
    assert row[:2] == ["inputs", "functions"], row

    # 2. The hover: its call and the first paragraph of its docstring.
    tag = f'.react-flow__node[data-id="{SHADOW}"] [data-widget-strip] [data-function-tag="season_factor"]'
    tip = hover_until_tooltip_says(
        page, tag, "season_factor's tag",
        ["season_factor", "from deep_umbra", "season_factor(season)", "Minutes of shadow a pixel at 1 stands for"],
        timeout=READ_MS,
    )
    save_workflow_test_screenshot(
        page, STEM, test_name="season-factor-tag",
        fit_reactflow=False, keep_tooltip=True, clip_rect=tooltip_close_up(page, tip, None),
        pixel_threshold=CLOSEUP_PIXEL_THRESHOLD, max_diff_ratio=CLOSEUP_MAX_DIFF_RATIO, closeup=True,
    )

    # 3. A click writes the call at the cursor, and the import the code lacks
    # after its first import.
    shipped = read_node_code(page, SHADOW)
    assert shipped.startswith("from deep_umbra import accumulated_shadow\n"), shipped
    assert page.evaluate(_CURSOR_AT_THE_END_JS, SHADOW), "the Accumulated Shadow editor was not found"
    page.locator(tag).click()
    page.wait_for_function(
        """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const editor = editorEl && editors.find((e) => editorEl.contains(e.getDomNode()));
            return !!editor && editor.getValue().includes("season_factor(season)");
        }""",
        arg=SHADOW,
        timeout=15000,
    )
    written = read_node_code(page, SHADOW)
    assert written == (
        "from deep_umbra import accumulated_shadow\n"
        "from deep_umbra import season_factor\n"
        + shipped.split("\n", 1)[1]
        + "season_factor(season)"
    ), written

    # One of Curio's: its call alone, on the next line.
    page.keyboard.press("Enter")
    page.locator(f'.react-flow__node[data-id="{SHADOW}"] [data-widget-strip] [data-function-tag="curio_output_file"]').click()
    page.wait_for_function(
        """(nodeId) => {
            const nodeEl = document.querySelector(`.react-flow__node[data-id="${nodeId}"]`);
            const editorEl = nodeEl && nodeEl.querySelector(".monaco-editor");
            const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
            const editor = editorEl && editors.find((e) => editorEl.contains(e.getDomNode()));
            return !!editor && editor.getValue().includes("curio_output_file(name)");
        }""",
        arg=SHADOW,
        timeout=15000,
    )
    lines = read_node_code(page, SHADOW).rstrip("\n").split("\n")
    assert lines[-2:] == ["season_factor(season)", "curio_output_file(name)"], lines
    assert sum(line.startswith("from deep_umbra import") for line in lines) == 2, lines
