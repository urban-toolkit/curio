"""Playwright E2E: every dataset in the Data Catalog actually loads and is usable.

One test per committed dataset, parametrized off the same live directory scan
the app itself uses (``list_catalog_datasets`` via
``tests/dataset_catalog_coverage.catalog_datasets``). Adding a directory under
``datasets/`` therefore adds a case here automatically; adding one whose
*format* has no recipe fails loudly rather than quietly collecting nothing.

Each case installs the dataset from the drawer, drops it on the canvas to get a
generated loader, wires a Data Transformation to it, runs both, and asserts on
values parsed out of the committed file - row/feature counts, column names, the
geometry type that came back from ``gpd.read_file``. Geo datasets get a third
node, a Vega-Lite chart of a per-feature measure derived from the parsed
geometry, so the coordinates are proven to survive all the way to a rendered
mark rather than merely to a row count.

WHY THIS IS NOT COVERED BY THE EXISTING SUITE
---------------------------------------------
Before this module, only ``acs-neighborhood-profile`` was ever *executed*
(``test_canvas_authoring_e2e.py``). The two geojson datasets appeared solely in
listing/install/export assertions, so a regression in the geojson loader snippet
(``gpd.read_file``, ``datasetLoaderSnippets.ts``) or in geopandas/fiona
availability inside the sandbox would have shipped green.

Covered more cheaply elsewhere and deliberately not re-asserted here: the
drawer's listing/search and the install round-trip (``test_data_catalog.py``);
the authoring gestures themselves - drag, drop, connect
(``test_canvas_authoring_e2e.py``); dataset lineage
(``test_dataset_lineage_e2e.py``); and persistence of the built spec. This
module is about the *data* being readable and usable, not about the canvas.

The per-format code and the expected marker values live in
``tests/dataset_catalog_coverage.py`` so the non-browser guard
(``test_datasets/test_catalog_dataset_coverage.py``) can share them.

No dataset teardown, deliberately - same reasoning as
``test_canvas_authoring_e2e.py``: installing a *hub* dataset copies it into
``.curio/users/<id>/datasets/`` and that copy cannot be removed (the
account-level DELETE runs ``unpublish_dataset``, which 403s for a non-publisher
of a committed catalog dataset). It is harmless to a re-run because
installed-ness is scoped to a dataflow, not to the store, so a fresh project
still shows the card offering "Add to dataflow".

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_dataset_catalog_datasets_e2e.py -v

    # one dataset at a time
    CURIO_TESTING=1 pytest .../test_dataset_catalog_datasets_e2e.py -k chicago-boundary
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import re
from playwright.sync_api import expect

from utk_curio.backend.tests.dataset_catalog_coverage import (
    CatalogDataset,
    catalog_datasets,
    expected_markers,
    marker_text,
    plan_for,
)

from .utils import (
    accept_confirm_dialog,
    assert_vega_canvas_rendered,
    canvas_node_type,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    close_tools_palette,
    open_tools_palette,
    play_node,
    read_node_code,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_canvas_zoom,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_TYPE = "curio.builtin/data-loading"
TRANSFORM_TYPE = "curio.builtin/data-transformation"
VEGA_TYPE = "curio.builtin/vis-vega"

TRANSFORM_TILE = "#step-transformation"
VEGA_TILE = "#step-vega"

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
# The "Adding…" placeholder is an <article role="status"> carrying the same
# title as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'

# Two nodes at zoom 1: the pair proven by test_canvas_authoring_e2e.py. A node
# is 525x350 flow units in a 1280x720 viewport, so this is about as close as
# they can sit with both facing handles still exposed.
POS_PAIR = ((150, 150), (760, 150))

# Three nodes do not fit at zoom 1, so the camera is pulled back first and the
# drops are spaced for the smaller painted width (525 * 0.55 = 289px): the nodes
# then occupy 190-479, 550-839 and 910-1199 across a 1280px viewport, leaving
# ~70px between neighbours and clearing the ~150px-wide tool rail on the left.
# In flow space that is 654 units apart against a 525-unit node, so every facing
# handle stays exposed. ``connect_nodes`` hit-tests each handle and names the
# covering element if this ever gets too tight again.
THREE_NODE_ZOOM = 0.55
POS_TRIPLE = ((190, 140), (550, 140), (910, 140))

CATALOG = catalog_datasets()


def _unversioned(node_type: str | None) -> str:
    """Strip the ``@<major>`` a descriptor id may carry.

    A dataset drop goes through ``createCodeNode(NodeType.DATA_LOADING)`` with
    the bare id, while a palette drag carries the descriptor's full coordinate,
    so the same kind arrives in both forms.
    """
    return (node_type or "").split("@", 1)[0]


def _username(dataset: CatalogDataset) -> str:
    """A short, per-dataset login so parametrized cases never share state."""
    tail = dataset.dataset_id.rsplit(".", 1)[-1].replace("-", "_")
    return f"ds_{tail}"[:30]


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches, so gating on it is
    # strictly better than waiting for visibility (the drawer slides in via
    # translate3d, so it is "visible" before it is usable).
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _add_dataset_from_catalog(page, palette, dataset: CatalogDataset):
    """Add *dataset* to the open dataflow, and return its palette row.

    The row is what gets dragged onto the canvas, so the palette has to stay
    open past the drawer.
    """
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = _drawer(page)
    card = drawer.locator(f'{CARD}[data-dataset-id="{dataset.dataset_id}"]')
    # By id, never by count: test_dataset_palette.py can leave a computed.*
    # dataset dir behind under a recycled user id, which shows up here as an
    # extra card and would break any exact count.
    expect(card).to_have_count(1, timeout=15000)

    card.get_by_role("button", name="Add to dataflow", exact=True).click()
    with page.expect_response(
        lambda r: "/datasets/install" in r.url and r.request.method == "POST" and r.ok,
        timeout=60000,
    ):
        # The Data catalog confirms an add now (#196), so the card click only
        # opens the dialog - the POST follows the confirm.
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to dataflow"
        )

    # Re-resolve rather than reuse the handle: the install flips origin
    # hub -> imported, which changes the React key so the card is replaced.
    expect(
        drawer.locator(f'{CARD}[data-dataset-id="{dataset.dataset_id}"]').get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=20000)

    # This drawer has no Escape handler, so close through the header button.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)

    row = page.locator(f'#datasets-palette [data-dataset-id="{dataset.dataset_id}"]')
    expect(row).to_have_count(1, timeout=20000)
    return row


def test_the_catalog_is_not_empty():
    """A catalog scanning to nothing would collect zero cases below, silently."""
    assert CATALOG, (
        "no datasets found under the catalog root, so the parametrized test "
        "below would collect nothing and this suite would pass vacuously"
    )


@pytest.mark.parametrize(
    "dataset", CATALOG, ids=[entry.dataset_id for entry in CATALOG]
)
def test_dataset_loads_and_feeds_a_consumer(
    dataset: CatalogDataset,
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """Install one catalog dataset, load it, and consume it downstream."""
    require_project_page()
    require_user_auth()

    plan = plan_for(dataset)
    markers = expected_markers(dataset)
    positions = POS_TRIPLE if plan.vega_spec else POS_PAIR

    def reframe():
        """Re-pin the camera before each drop on the three-node path."""
        if plan.vega_spec:
            set_canvas_zoom(page, THREE_NODE_ZOOM)

    # Before navigating: the drawer slides via translate3d, and the provider
    # reads prefers-reduced-motion through useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name=dataset.manifest.name,
        username=_username(dataset),
        project_name=f"{dataset.manifest.name} E2E",
    )
    require_owner_view(page)

    # 1. THE DATASET, added to the dataflow from the catalog drawer.
    palette = open_tools_palette(page, "datasets")
    dataset_row = _add_dataset_from_catalog(page, palette, dataset)

    # 2. A LOADER FOR IT, created by dropping the dataset on the pane.
    reframe()
    loader_id = drag_to_canvas(page, dataset_row, at=positions[0])
    # The palette floats over the left third of the canvas. The drop above did
    # not care - drag_to_canvas dispatches on the pane without hit-testing - but
    # every connect_nodes below does, so give the canvas back now that the row
    # has served its purpose.
    close_tools_palette(page, "datasets")
    assert _unversioned(canvas_node_type(page, loader_id)) == LOADER_TYPE, (
        "dropping a dataset must take the dataset branch of handleDrop and "
        "create a Data Loading node"
    )
    loader_code = read_node_code(page, loader_id)
    assert plan.loader_marker in loader_code, (
        f"the generated loader for a {dataset.manifest.format} dataset does "
        f"not call {plan.loader_marker}:\n{loader_code}"
    )
    # The portable form: the sandbox resolves the id at execution time, so the
    # generated code carries no machine- or user-specific absolute path.
    assert f'curio_dataset_path("{dataset.dataset_id}")' in loader_code, (
        f"loader does not resolve the dataset by id:\n{loader_code}"
    )

    # 3. A CONSUMER, wired to it. The edge id is derived, not random, so it
    #    doubles as an assertion that the handles the drag hit were the
    #    intended ones.
    reframe()
    transform_id = drag_to_canvas(page, page.locator(TRANSFORM_TILE), at=positions[1])
    assert _unversioned(canvas_node_type(page, transform_id)) == TRANSFORM_TYPE
    edge_id = connect_nodes(page, loader_id, transform_id)
    assert edge_id == f"reactflow__edge-{loader_id}out-{transform_id}in"
    set_node_code(page, transform_id, plan.transform_code)

    # 4. RUN. The loader's artifact line proves the file reached DuckDB; the
    #    consumer's markers prove the *content* crossed the edge as ``arg``.
    loader_output = run_node_and_wait(page, loader_id, node_type=LOADER_TYPE)
    assert "Saved to file:" in loader_output, loader_output

    transform_output = run_node_and_wait(page, transform_id, node_type=TRANSFORM_TYPE)
    for name, value in markers.items():
        expected = marker_text(name, value)
        assert expected in transform_output, (
            f"{dataset.dataset_id}: expected {expected!r} in the "
            f"transformation output, got:\n{transform_output}"
        )
    assert "Saved to file:" in transform_output, transform_output

    # 5. A VIEW, for formats that carry geometry: the chart can only draw marks
    #    if the coordinates parsed, so this is the end-to-end proof that a
    #    spatial dataset is usable and not merely countable.
    if plan.vega_spec:
        reframe()
        vega_id = drag_to_canvas(page, page.locator(VEGA_TILE), at=positions[2])
        assert _unversioned(canvas_node_type(page, vega_id)) == VEGA_TYPE
        vega_edge = connect_nodes(page, transform_id, vega_id)
        assert vega_edge == f"reactflow__edge-{transform_id}out-{vega_id}in"
        # A vis-vega node holds its Vega-Lite spec in a Monaco JSON editor
        # (GrammarEditor), which is the same editor set_node_code drives.
        set_node_code(page, vega_id, plan.vega_spec)
        play_node(page, vega_id)
        # Grammar nodes render through an output tab rather than the inline
        # code counter, so this is status-only - run_node_and_wait would then
        # look for a [data-curio-node-output] box that does not exist.
        wait_for_node_done(page, vega_id, node_type=VEGA_TYPE)
        assert_vega_canvas_rendered(page, vega_id)

    # Visual baseline for a canvas nobody hand-checks otherwise, one per
    # dataset. The semantic assertions above cover what each node computed;
    # this covers what the result *looks* like - most usefully that the chart
    # drew bars and the edges are actually rendered. Compared at the suite's
    # default tolerance (20% of pixels, 30/255 per channel), which is what
    # absorbs the per-run "Saved to file: <timestamp>_<hash>" text. The helper
    # pins its own fitView first, so the authoring zoom above does not leak
    # into the capture.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page,
        dataset.slug,
        test_name="test_dataset_loads_and_feeds_a_consumer",
    )
