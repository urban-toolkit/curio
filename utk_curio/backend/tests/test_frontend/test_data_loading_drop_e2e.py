"""Playwright E2E: a Data Loading node loads a file dropped on it or picked with Choose file.

A fresh Data Loading node opens on its Widgets tab, which shows only its Data
box: no tag, Edit, Delete, Add widget or selections, as Data Export's shows
only its File name and Download, while a Python node's keeps them all. Its
starter code, ``data = curio_load_data([!! data !!])``, is on its Code tab. A
CSV file from the computer dropped
on the node is imported into the Data Catalog and added to the dataflow, the
widget names it, the code stays the starter, and a run hands the file's rows
to the node after it. Choose file, the widget's file dialog, does the same,
and a file dropped on the empty canvas makes a Data Loading node that loads it.
A GeoTIFF's loader names the window it reads, and the node shows no error.
On a node whose code reads no dataset widget, a dropped file's loader goes into
the code, as a Data Catalog card's does.

A file from the computer is a ``DataTransfer`` holding a real ``File``, built in
the page, as the browser builds one for a drop from the desktop.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_data_loading_drop_e2e.py -v
"""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    CANVAS_DROP_TARGET,
    assert_shows_only_controls,
    canvas_nodes,
    connect_nodes,
    dataset_widget_state,
    drag_builtin_to_canvas,
    node_locator,
    read_node_code,
    require_owner_view,
    require_user_auth,
    run_node_and_wait,
    save_node_closeup,
    set_canvas_zoom,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_code,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_TYPE = "curio.builtin/data-loading"
TRANSFORM_TYPE = "curio.builtin/data-transformation"
STARTER = "data = curio_load_data([!! data !!])\nreturn data\n"
STEM = "data-loading-drop"
TREES = "tree_id,height\n1,10\n2,12\n3,9\n"
PARKS = "park_id,area\n1,5.5\n2,7.25\n"
ROW_MARKER = "ROWS"
COUNT_ROWS = f'print("{ROW_MARKER}", len(input_0))\nreturn input_0\n'
#: What a GeoTIFF taken on a fresh node makes of its starter: the loader names
#: the window it reads.
GEOTIFF_LOADER = "data = curio_load_data([!! data !!], bounds=None)\nreturn data\n"
#: The Data box, on the node's Widgets tab, which shows only its controls.
DATA_WIDGET = "[data-widget-controls] [data-dataset-drop]"
#: The node's Widgets tab, which a Data Loading node opens on.
WIDGETS_TAB = '.nav-link[data-rr-ui-event-key="widgets"]'

# Records, from now on, every status the node *nodeId* shows and every error
# it names, so a test can tell that it never failed, even for a moment.
_WATCH_STATUS_JS = r"""(nodeId) => {
    const el = document.querySelector(`.react-flow__node[data-id="${nodeId}"] [data-curio-node-status]`);
    if (!el) return false;
    const seen = { statuses: [el.getAttribute("data-curio-node-status")], errors: [] };
    window.__curioNodeStatusSeen = seen;
    new MutationObserver(() => {
        seen.statuses.push(el.getAttribute("data-curio-node-status"));
        const error = el.getAttribute("data-curio-node-error");
        if (error) seen.errors.push(error);
    }).observe(el, { attributes: true, attributeFilter: ["data-curio-node-status", "data-curio-node-error"] });
    return true;
}"""

# Drops a file named *name* holding *text* on the element *selector* names, at
# *at* from its top-left corner (its centre without one), with dragenter,
# dragover and drop, as a drop from the desktop arrives. Answers whether the
# page took the drop (a dragover it accepted).
_DROP_FILE_JS = r"""({ selector, name, text, type, at }) => {
    const target = document.querySelector(selector);
    if (!target) return `no element ${selector}`;
    const box = target.getBoundingClientRect();
    const transfer = new DataTransfer();
    transfer.items.add(new File([text], name, { type }));
    const [x, y] = at || [box.width / 2, box.height / 2];
    const init = {
        bubbles: true, cancelable: true, composed: true, dataTransfer: transfer,
        clientX: box.x + x, clientY: box.y + y,
    };
    target.dispatchEvent(new DragEvent("dragenter", init));
    const over = new DragEvent("dragover", init);
    target.dispatchEvent(over);
    target.dispatchEvent(new DragEvent("drop", init));
    return over.defaultPrevented ? "taken" : "refused";
}"""


def _opens_with_the_starter(page, node_id: str) -> None:
    """The node's editor holds the starter, which reaches a fresh node from the
    starters the canvas loaded, so it may come a moment after the node."""
    wait_for_node_code(page, node_id, STARTER)


def _enter(page, base: str, server: str, name: str) -> dict:
    page.emulate_media(reduced_motion="reduce")
    entered = stub_login_and_enter_workflow(
        page, frontend_url=base, backend_url=server,
        name=name, username=f"dl_drop_{uuid.uuid4().hex[:8]}", project_name=name,
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    return entered


def _drop_file(
    page, selector: str, name: str, text: str, type: str = "text/csv",
    at: tuple[float, float] | None = None,
) -> None:
    taken = page.evaluate(
        _DROP_FILE_JS,
        {"selector": selector, "name": name, "text": text, "type": type, "at": list(at) if at else None},
    )
    assert taken == "taken", f"the drop of {name} on {selector} was {taken}"


def _data_widget(page, node_id: str):
    return node_locator(page, node_id).locator(DATA_WIDGET)


def _holds(page, node_id: str, title: str) -> None:
    """The node's Data widget names the dataset it holds, an imported one, and
    the node is bound to it, as a save keeps it."""
    widget = _data_widget(page, node_id)
    try:
        expect(widget).to_have_attribute("data-dataset-drop", "set", timeout=60000)
        expect(widget).to_contain_text(title, timeout=10000)
    except AssertionError as exc:
        raise AssertionError(
            f"the Data widget does not hold {title!r}: it says {widget.text_content()!r}"
        ) from exc
    state = dataset_widget_state(page, node_id)
    assert str(state["value"]).startswith("imported."), state
    assert state["value"] in state["datasetRefs"], state


def _rows_reach_the_next_node(page, loader: str, rows: int) -> None:
    """A run of the loader hands its rows to a Data Transformation wired after it."""
    # A close-up leaves the view framed on the loader: back to the view the
    # loader was dropped in, so the next node lands beside it.
    set_canvas_zoom(page, 1)
    transform = drag_builtin_to_canvas(page, "#tile-data-transformation", at=(760, 220))
    set_node_code(page, transform, COUNT_ROWS)
    connect_nodes(page, loader, transform)
    loader_output = run_node_and_wait(page, loader, node_type=LOADER_TYPE)
    assert "Saved to file:" in loader_output, loader_output
    transform_output = run_node_and_wait(page, transform, node_type=TRANSFORM_TYPE)
    assert f"{ROW_MARKER} {rows}" in transform_output, transform_output


def test_a_fresh_data_loading_node_opens_on_its_data_widget(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading fresh")

    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))

    # It opens on its Widgets tab, which shows only the Data box; the starter
    # is on its Code tab.
    expect(node_locator(page, loader).locator(WIDGETS_TAB)).to_have_class(
        re.compile(r"\bactive\b"), timeout=30000,
    )
    widget = _data_widget(page, loader)
    expect(widget).to_have_attribute("data-dataset-drop", "empty", timeout=30000)
    expect(widget).to_contain_text("Drop a file or a Data Catalog dataset here")
    expect(widget.get_by_text("Choose file", exact=True)).to_be_visible()
    assert_shows_only_controls(page, loader)
    _opens_with_the_starter(page, loader)
    save_node_closeup(page, STEM, loader, test_name=f"{STEM}_fresh_node")


def test_data_loading_and_data_export_show_only_their_controls_and_a_python_node_the_whole_tab(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading controls only")
    # Three nodes side by side, so the view takes them at half size.
    set_canvas_zoom(page, 0.5)
    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(120, 150))
    export = drag_builtin_to_canvas(page, "#tile-data-export", at=(420, 150))
    python = drag_builtin_to_canvas(page, "#tile-data-transformation", at=(720, 150))

    # Data Loading and Data Export open on their Widgets tab, which shows only
    # their controls: the Data box, and File name with Download.
    for node_id in (loader, export):
        expect(node_locator(page, node_id).locator(WIDGETS_TAB)).to_have_class(
            re.compile(r"\bactive\b"), timeout=30000,
        )
        assert_shows_only_controls(page, node_id)
    expect(_data_widget(page, loader)).to_be_visible()
    controls = node_locator(page, export).locator("[data-widget-controls]")
    expect(controls.get_by_label("File name", exact=True)).to_be_visible()
    expect(controls.locator('[data-node-controls] button[aria-label^="Download"]')).to_have_count(1)

    # A Python node's Widgets tab keeps everything that edits its widgets.
    node_locator(page, python).locator(WIDGETS_TAB).dispatch_event("click")
    panel = node_locator(page, python).locator("[data-widgets-panel]")
    expect(panel).to_be_visible(timeout=10000)
    panel.get_by_role("button", name="Add widget", exact=True).click()
    panel.get_by_label("Widget name").fill("factor")
    panel.get_by_label("Widget type").select_option("number")
    panel.get_by_label("Widget label").fill("Factor")
    panel.get_by_label("Widget default").fill("2")
    panel.get_by_role("button", name="Add widget", exact=True).click()
    expect(panel.locator('[data-widget-row="factor"] [data-widget-tag="factor"]')).to_have_count(1)
    expect(panel.get_by_role("button", name="Edit widget factor")).to_be_visible()
    expect(panel.get_by_role("button", name="Delete widget factor")).to_be_visible()
    expect(panel.get_by_role("button", name="Add widget", exact=True)).to_be_visible()
    expect(node_locator(page, python).locator("[data-widget-controls]")).to_have_count(0)


def _geotiff_bytes() -> bytes:
    """A GeoTIFF of 4 by 3 heights, made here as the export test makes one."""
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff", width=4, height=3, count=1, dtype="float32",
            crs="EPSG:32616", transform=from_origin(440000, 4640000, 30, 30), nodata=-1,
        ) as raster:
            raster.write(np.arange(12, dtype="float32").reshape(3, 4), 1)
        return memory.read()


def test_a_geotiff_chosen_on_a_fresh_node_names_its_window_and_the_node_shows_no_error(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading GeoTIFF")
    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    widget = _data_widget(page, loader)
    widget.wait_for(state="visible", timeout=30000)
    _opens_with_the_starter(page, loader)
    assert page.evaluate(_WATCH_STATUS_JS, loader), "the node shows no status to watch"

    with page.expect_file_chooser(timeout=15000) as chooser:
        widget.get_by_text("Choose file", exact=True).click()
    chooser.value.set_files({"name": "heights.tif", "mimeType": "image/tiff", "buffer": _geotiff_bytes()})

    _holds(page, loader, "Heights")
    # The starter becomes the GeoTIFF's loader, which names its window.
    wait_for_node_code(page, loader, GEOTIFF_LOADER)
    seen = page.evaluate("() => window.__curioNodeStatusSeen")
    # The node holds the file its code reads: nothing failed, not for a moment.
    assert "error" not in seen["statuses"] and seen["errors"] == [], seen


def test_a_csv_dropped_on_the_node_is_imported_and_loaded(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading drop")
    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    _data_widget(page, loader).wait_for(state="visible", timeout=30000)
    # A drop sets the widget the code reads: the starter has to be there.
    _opens_with_the_starter(page, loader)

    _drop_file(page, f'.react-flow__node[data-id="{loader}"] {DATA_WIDGET}', "trees.csv", TREES)

    _holds(page, loader, "Trees")
    # The code stays the starter: the widget is what changed.
    _opens_with_the_starter(page, loader)
    # The import's toasts would sit over the node's right edge.
    save_node_closeup(page, STEM, loader, test_name=f"{STEM}_after_a_drop", sweep_toasts=True)
    _rows_reach_the_next_node(page, loader, 3)


def test_choose_file_loads_the_file_picked_in_its_dialog(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading choose")
    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    widget = _data_widget(page, loader)
    widget.wait_for(state="visible", timeout=30000)
    _opens_with_the_starter(page, loader)

    with page.expect_file_chooser(timeout=15000) as chooser:
        widget.get_by_text("Choose file", exact=True).click()
    chooser.value.set_files({"name": "parks.csv", "mimeType": "text/csv", "buffer": PARKS.encode()})

    _holds(page, loader, "Parks")
    _rows_reach_the_next_node(page, loader, 2)


def test_a_file_dropped_on_the_empty_canvas_makes_a_data_loading_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading canvas drop")
    before = {node["id"] for node in canvas_nodes(page)}

    # Where the other tests drop a fresh tile, so the node after it has room.
    _drop_file(page, CANVAS_DROP_TARGET, "trees.csv", TREES, at=(170, 200))

    page.wait_for_function(
        "(n) => window.__curio_reactFlow.getNodes().length > n", arg=len(before), timeout=60000,
    )
    [loader] = [node["id"] for node in canvas_nodes(page) if node["id"] not in before]
    _holds(page, loader, "Trees")
    # Made holding the file, it opens on its Widgets tab.
    expect(node_locator(page, loader).locator(WIDGETS_TAB)).to_have_class(re.compile(r"\bactive\b"))
    _opens_with_the_starter(page, loader)
    _rows_reach_the_next_node(page, loader, 3)


def test_a_file_dropped_on_code_that_reads_no_dataset_widget_goes_into_the_code(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading merge")
    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    set_node_code(page, loader, "import pandas as pd\n\nreturn pd.DataFrame({'a': [1]})\n")

    _drop_file(page, f'.react-flow__node[data-id="{loader}"] .monaco-editor', "trees.csv", TREES)

    code = node_locator(page, loader)
    expect(code).to_contain_text("# Curio dataset loader: Trees", timeout=60000)
    assert "curio_load_data(" in read_node_code(page, loader)
    # The Data widget holds nothing: the code does not read it.
    expect(_data_widget(page, loader)).to_have_attribute("data-dataset-drop", "empty")
