"""Playwright E2E: build a dataflow by hand, from an empty canvas to a result.

Every other test in this suite gets its graph from somewhere else: a Trill JSON
through the File menu, or a spec seeded straight into the database. This is the
only one that builds a graph the way a user does, and it is the only coverage of
three interactions that ship in every release:

  * dragging a dataset out of the palette, which creates a loader node
  * dragging a built-in node type off the tool rail
  * drawing an edge between two handles

Covered more cheaply elsewhere and not re-asserted here: the Data Catalog
drawer's own behaviour (``test_data_catalog.py``), which button a card shows
(``src/tests/components/datasetCardActions.test.tsx``), and the per-kind drag
payload (``src/tests/components/toolsMenuPackagePalette/packageTemplateRow.test.tsx``).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_canvas_authoring_e2e.py -v
"""
from __future__ import annotations

import csv
import os
import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    api_json,
    canvas_node_type,
    connect_nodes,
    drag_to_canvas,
    open_tools_palette,
    read_node_code,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

# The CSV hub dataset: three rows, two numeric columns, and a loader that only
# needs pandas. The geojson ones would drag geopandas and a geometry parse into
# what is meant to be a test about the canvas.
DATASET_ID = "data.urbanlab.acs-neighborhood-profile"
DATASET_CSV = os.path.join(
    REPO_ROOT, "datasets", f"{DATASET_ID}@1", "data",
    "acs-neighborhood-profile.csv",
)

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
# The "Adding…" placeholder is an <article role="status"> carrying the same
# title as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'

LOADER_TYPE = "curio.builtin/data-loading"
TRANSFORM_TYPE = "curio.builtin/data-transformation"
TRANSFORM_TILE = "#step-transformation"

# Node geometry: 525x350 at zoom 1 in a 1280x720 viewport. Anything closer than
# ~600px apart horizontally overlaps, and the later node's body then covers the
# earlier one's output handle, which makes the connection drag a silent no-op.
POS_LOADER = (150, 150)
POS_TRANSFORM = (760, 150)

# The inline output box shows stdout plus "Saved to file: …" - never the return
# value itself - so a result assertion has to print what it wants to check.
ROW_MARKER = "CURIO_E2E_ROWS"
TRANSFORM_CODE = (
    "df = arg\n"
    f'print("{ROW_MARKER}", len(df))\n'
    "return df.head(2)\n"
)


def _unversioned(node_type: str | None) -> str:
    """Strip the ``@<major>`` a descriptor id may carry.

    The same kind arrives with and without it depending on how the node was
    created: a dataset drop goes through ``createCodeNode(NodeType.DATA_LOADING)``
    with the bare id, while a palette drag carries the descriptor's full
    coordinate. Neither form is wrong, so tests compare the unversioned name.
    """
    return (node_type or "").split("@", 1)[0]


def _expected_row_count() -> int:
    """Row count read off the committed CSV, not off its manifest.

    ``manifest.json`` advertises ``rowCount: 2408`` while the committed fixture
    holds three rows, so the manifest is not a usable oracle here.
    """
    with open(DATASET_CSV, newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


# No dataset teardown, deliberately. Installing a *hub* dataset copies it into
# ``.curio/users/<id>/datasets/`` (``mutations.install_dataset`` ->
# ``install_dataset_from_catalog``), and that copy cannot be removed: the
# account-level DELETE runs ``unpublish_dataset`` first, which 403s because this
# user is not the publisher of a committed catalog dataset. The copy is harmless
# to a re-run because installed-ness is scoped to a dataflow, not to the store,
# so a fresh project still shows the card offering "Add to dataflow" and the
# install path is exercised again in full.


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _add_dataset_from_catalog(page, palette):
    """Add the hub dataset to the open dataflow and leave the palette showing it.

    Returns once the palette row exists, which is what the drag needs.
    """
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = _drawer(page)
    card = drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]')
    expect(card).to_have_count(1, timeout=15000)

    with page.expect_response(
        lambda r: "/datasets/install" in r.url and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        card.get_by_role("button", name="Add to dataflow", exact=True).click()

    # Re-resolve rather than reuse the handle: the install flips origin
    # hub -> imported, which changes the React key so the card is replaced.
    expect(
        drawer.locator(f'{CARD}[data-dataset-id="{DATASET_ID}"]').get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=20000)

    # This drawer has no Escape handler, so close through the header button.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)

    row = page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    expect(row).to_have_count(1, timeout=20000)
    return row


def test_build_and_run_dataflow_from_scratch(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    # Before navigating: the drawer slides via translate3d, so to_be_visible is
    # not a gate on its own, and the provider reads prefers-reduced-motion
    # through useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Canvas Author",
        username="canvas_author",
        project_name="Canvas Authoring",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    # 1. DATA IN. The palette has to stay open past the drawer, because the row
    #    it renders is what gets dragged onto the canvas below.
    palette = open_tools_palette(page, "datasets")
    dataset_row = _add_dataset_from_catalog(page, palette)

    # 2. LOADER NODE, by dragging the dataset onto the pane.
    loader_id = drag_to_canvas(page, dataset_row, at=POS_LOADER)
    assert _unversioned(canvas_node_type(page, loader_id)) == LOADER_TYPE, (
        "dropping a dataset must take the dataset branch of handleDrop and "
        "create a Data Loading node"
    )
    loader_code = read_node_code(page, loader_id)
    assert "pd.read_csv" in loader_code and "return df" in loader_code, (
        f"generated loader code does not read the CSV:\n{loader_code}"
    )

    # 3. SECOND NODE, from the built-in tool rail.
    transform_id = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=POS_TRANSFORM)
    assert _unversioned(canvas_node_type(page, transform_id)) == TRANSFORM_TYPE

    # 4. CONNECT THEM. The edge id is derived, not random, so it doubles as an
    #    assertion that the handles the drag hit were the ones intended.
    edge_id = connect_nodes(page, loader_id, transform_id)
    assert edge_id == f"reactflow__edge-{loader_id}out-{transform_id}in"

    # 5. CODE. Through Monaco's setValue, which is the same path a keystroke
    #    takes to reach data.code.
    set_node_code(page, transform_id, TRANSFORM_CODE)

    # 6. RUN, and check the result rather than just the status. The loader's
    #    artifact line proves the CSV reached DuckDB; the transformation's
    #    printed row count proves the data actually crossed the edge as ``arg``.
    loader_output = run_node_and_wait(page, loader_id, node_type=LOADER_TYPE)
    assert "Saved to file:" in loader_output, loader_output

    transform_output = run_node_and_wait(
        page, transform_id, node_type=TRANSFORM_TYPE
    )
    expected_rows = _expected_row_count()
    assert f"{ROW_MARKER} {expected_rows}" in transform_output, (
        f"expected {expected_rows} rows to reach the transformation, got:\n"
        f"{transform_output}"
    )
    assert "Saved to file:" in transform_output, transform_output

    # 7. PERSIST. Server truth alongside the DOM: what the canvas built is what
    #    a reload would get back.
    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=10000)
    save_btn.click()
    # handleSave closes the File menu once the save round-trip completes, so the
    # button going hidden is the signal that the write finished.
    save_btn.wait_for(state="hidden", timeout=30000)

    spec = api_json(f"{current_server}/api/projects/{project_id}", token)["spec"]
    dataflow = spec["dataflow"]
    saved_nodes = {node["id"]: node for node in dataflow["nodes"]}
    assert set(saved_nodes) == {loader_id, transform_id}, dataflow["nodes"]
    assert [edge["id"] for edge in dataflow["edges"]] == [edge_id], dataflow["edges"]
    assert ROW_MARKER in saved_nodes[transform_id]["content"], (
        "the code typed into the node was not persisted with it"
    )
    assert DATASET_ID in {
        ref.get("id") for ref in (dataflow.get("datasets") or [])
    } or DATASET_ID in loader_code, (
        "the dataflow does not record the dataset it loads"
    )
    # Visual baseline for a canvas nobody hand-checks otherwise. The semantic
    # assertions above cover what each node computed; this covers what the
    # canvas *looks* like - most usefully that the edge is actually drawn, which
    # a store-level edge assertion cannot see. Compared at the suite's default
    # tolerance (20% of pixels, 30/255 per channel), which is what absorbs the
    # per-run "Saved to file: <timestamp>_<hash>" text in each output box.
    # The helper fitViews first, so baseline and comparison share one viewport,
    # and it writes the baseline on the first run if the file is absent.
    save_workflow_test_screenshot(
        page, "canvas-authoring", test_name="test_build_and_run_dataflow_from_scratch",
    )

