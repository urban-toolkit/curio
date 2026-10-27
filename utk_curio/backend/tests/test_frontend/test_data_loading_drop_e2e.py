"""Playwright E2E: a Data Loading node loads a file dropped on it or picked with Choose file.

A fresh Data Loading node opens with its Data widget above its starter code,
``data = curio_load_data([!! data !!])``. A CSV file from the computer dropped
on the node is imported into the Data Catalog and added to the dataflow, the
widget names it, the code stays the starter, and a run hands the file's rows
to the node after it. Choose file, the widget's file dialog, does the same,
and a file dropped on the empty canvas makes a Data Loading node that loads it.
On a node whose code reads no dataset widget, a dropped file's loader goes into
the code, as a Data Catalog card's does.

A file from the computer is a ``DataTransfer`` holding a real ``File``, built in
the page, as the browser builds one for a drop from the desktop.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_data_loading_drop_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    CANVAS_DROP_TARGET,
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
#: The Data widget above the code. The node's Widgets tab draws it too.
DATA_WIDGET = "[data-controls-with-code] [data-dataset-drop]"

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
    transform = drag_builtin_to_canvas(page, "#tile-data-transformation", at=(760, 220))
    set_node_code(page, transform, COUNT_ROWS)
    connect_nodes(page, loader, transform)
    loader_output = run_node_and_wait(page, loader, node_type=LOADER_TYPE)
    assert "Saved to file:" in loader_output, loader_output
    transform_output = run_node_and_wait(page, transform, node_type=TRANSFORM_TYPE)
    assert f"{ROW_MARKER} {rows}" in transform_output, transform_output


def test_a_fresh_data_loading_node_shows_its_data_widget_above_its_starter(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_user_auth()
    _enter(page, app_frontend.base_url, current_server, "Data Loading fresh")

    loader = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))

    widget = _data_widget(page, loader)
    expect(widget).to_have_attribute("data-dataset-drop", "empty", timeout=30000)
    expect(widget).to_contain_text("Drop a file or a Data Catalog dataset here")
    expect(widget.get_by_text("Choose file", exact=True)).to_be_visible()
    # The widget sits above the code, in the code's own pane.
    column = node_locator(page, loader).locator("[data-controls-with-code]")
    expect(column.locator("[data-widget-controls]")).to_have_count(1)
    _opens_with_the_starter(page, loader)
    save_node_closeup(page, STEM, loader, test_name=f"{STEM}_fresh_node")


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
    save_node_closeup(page, STEM, loader, test_name=f"{STEM}_after_a_drop")
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
