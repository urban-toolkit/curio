"""Playwright E2E: the Data Catalog drawer.

Mirrors ``test_node_catalog.py`` but across a different boundary. Installing a
dataset does not refresh the palette through a React subscription - it dispatches
a ``window`` CustomEvent (``curio:dataset-catalog-refresh``) that fans out to two
independent module caches keyed on *different* query strings (the drawer asks
with ``includeHub=true&groupOsm=true``, the palette with ``includeHub=false``).
Only a real browser has a window to dispatch on and two live caches to invalidate.

No seeding *of the hub itself*: the datasets under ``datasets/`` are scanned
live on every request and surface as ``origin: "hub"``. (Separately, the datasets
the shipped examples declare are copied into a user's own store by
``app/datasets/seed.py``, which is what makes them render as real rows in the
palette rather than dirName-titled placeholders; that path is covered without a
browser in ``test_datasets/test_example_dataset_palette.py``.)

Covered more cheaply elsewhere and not re-asserted here:
``test_datasets/test_dataset_catalog_routes.py`` owns the install route, and
``src/tests/components/datasetCardActions.test.tsx`` owns which button a card
shows for a given prop set. This file asserts the datasets are *listed*; that
each one actually loads and feeds a downstream node is
``test_dataset_catalog_datasets_e2e.py``, parametrized over the same scan.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_catalog.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import re
from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATASET_ID = "data.urbanlab.chicago-community-areas"
DATASET_TITLE = "Chicago Community Areas"
OTHER_HUB_TITLES = ("Chicago Boundary", "ACS Neighborhood Profile")

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
SEARCH_PLACEHOLDER = "Search datasets, publishers, tags…"
# The "Adding…" placeholder is an <article role="status"> carrying the same
# title as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'

#: The formats the Data Catalog's rail offers, in its own order. Mirrors
#: ``FORMAT_FILTERS`` in pages/dataHub/dataHubBrowseConstants.ts - the chip row
#: is derived from these, so the expected chip set is derivable from the facet
#: counts alone (#232).
RAIL_FORMATS = ("geojson", "csv", "json", "parquet", "geotiff", "shp")


def _one_node_spec() -> dict:
    """A single node so the canvas is not empty.

    ``save_workflow_test_screenshot`` pins the viewport with
    ``_wait_for_reactflow_ready`` before capturing, and that waits for at least
    one ``.react-flow__node``. An empty dataflow therefore times out. A node also
    makes the baseline more useful: it shows the drawer against real canvas
    content rather than blank space.
    """
    return {
        "dataflow": {
            "name": "CatalogBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "catalog-baseline-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _enter_dataflow(page, app_frontend, current_server, *, username, project):
    # Before navigating: the drawer slides via translate3d, so to_be_visible is
    # not a gate, and the provider reads prefers-reduced-motion through
    # useSyncExternalStore.
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Data Catalog User",
        username=username,
        project_name=project,
        project_spec=_one_node_spec(),
    )
    require_owner_view(page)
    return result


def _open_drawer_from_menu(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Data Catalog", exact=True).click()
    return _drawer(page)


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal here: until the rAF flips it, every
    # role query inside the subtree returns zero matches, so gating on it is
    # strictly better than waiting for visibility.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _card(drawer, dataset_id):
    return drawer.locator(f'{CARD}[data-dataset-id="{dataset_id}"]')


def test_drawer_lists_hub_datasets(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="datacat_list", project="Data Catalog List",
    )

    drawer = _open_drawer_from_menu(page)

    # The named committed hub datasets render, each exactly once - proving the
    # live directory scan reached the browser. Asserted by title rather than by
    # total count, so adding a dataset to the catalog does not break this.
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)
    for title in (DATASET_TITLE, *OTHER_HUB_TITLES):
        expect(
            drawer.locator(CARD).filter(
                has=page.get_by_role("heading", name=title, exact=True)
            )
        ).to_have_count(1, timeout=15000)

    expect(drawer.locator('[role="alert"]')).to_have_count(0)

    # Visual baseline of the hub listing. Card text includes a relative
    # timestamp, which drifts slowly against a fixed manifest date; the suite's
    # default tolerance (20% of pixels, 30/255 per channel) absorbs that.
    save_workflow_test_screenshot(
        page, "data-catalog-drawer", test_name="test_drawer_lists_hub_datasets",
    )

    # Close/reopen: the portal must unmount and remount exactly once. This drawer
    # has no Escape handler, so close through the header button.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    _open_drawer_from_menu(page)
    expect(page.locator(DRAWER_ROOT)).to_have_count(1)


def test_drawer_search_filters_server_side(
    app_frontend: "FrontendPage", current_server: str, page
):
    """Worth a browser assertion: this search is debounced, refetched and deferred.

    Typing waits 280ms, issues a *new* server request, then renders through
    useDeferredValue - three chances to race that no unit test reproduces.
    """
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="datacat_search", project="Data Catalog Search",
    )

    drawer = _open_drawer_from_menu(page)
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)

    drawer.get_by_placeholder(SEARCH_PLACEHOLDER).fill("Community Areas")

    # Named presence/absence rather than a total count: test_dataset_palette.py
    # leaves a computed.* dataset dir behind under a recycled user id, which
    # shows up here as an extra card and would break any exact count.
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)
    for title in OTHER_HUB_TITLES:
        expect(
            drawer.locator(CARD).filter(
                has=page.get_by_role("heading", name=title, exact=True)
            )
        ).to_have_count(0, timeout=15000)


def test_add_dataset_propagates_to_palette(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server,
        username="datacat_add", project="Data Catalog Add",
    )
    token = result["token"]
    project_id = result["project"]["id"]

    catalog_url = (
        f"{current_server}/api/datasets/catalog"
        f"?includeHub=true&dataflowId={project_id}"
    )

    def _installed_flag():
        items = api_json(catalog_url, token)["items"]
        item = next((i for i in items if i["id"] == DATASET_ID), None)
        assert item is not None, (
            f"{DATASET_ID} missing from the catalog: {[i['id'] for i in items]}"
        )
        return item.get("installed")

    # Diagnostic precondition, so a dirty state is distinguishable from a
    # browser-timing problem.
    assert _installed_flag() is not True, "dataset already installed before the test"

    palette = open_tools_palette(page, "datasets")
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = _drawer(page)
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)

    _card(drawer, DATASET_ID).get_by_role(
        "button", name="Add to project", exact=True
    ).click()
    with page.expect_response(
        lambda r: "/datasets/install" in r.url
        and r.request.method == "POST"
        and r.ok,
        timeout=30000,
    ):
        # The Data catalog confirms an add now (#196), so the card click only
        # opens the dialog - the POST follows the confirm.
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to project"
        )

    # Re-resolve, never reuse a handle: installing flips origin hub -> imported,
    # which changes the React key so the node is replaced outright, and it patches
    # updatedAt so the card moves under the default "recent" sort.
    expect(
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Remove from project", exact=True
        )
    ).to_be_visible(timeout=20000)

    # THE POINT: close the drawer, and the palette already lists it - the window
    # event reached the palette's own cache with no reload.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    ).to_have_count(1, timeout=20000)

    # Server-side truth: the spec ref was persisted, not just the React state.
    assert _installed_flag() is True

    # Round-trip. Removal confirms in an app dialog now (#196, #197): the card
    # click only opens "Remove <title>?", and the DELETE follows the confirm.
    # The confirm button reads "Remove and delete" when no other dataflow uses
    # the file, so match it by prefix.
    drawer = _open_drawer_from_menu(page)
    _card(drawer, DATASET_ID).get_by_role(
        "button", name="Remove from project", exact=True
    ).click()
    with page.expect_response(
        lambda r: "/datasets/" in r.url and r.request.method == "DELETE",
        timeout=30000,
    ):
        accept_confirm_dialog(
            page,
            title=f"Remove {DATASET_TITLE}?",
            button=re.compile(r"^Remove( and delete)?$"),
        )

    expect(
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Add to project", exact=True
        )
    ).to_be_visible(timeout=20000)
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#datasets-palette [data-dataset-id="{DATASET_ID}"]')
    ).to_have_count(0, timeout=20000)
    assert _installed_flag() is not True


@pytest.fixture
def delete_imported_datasets(current_server):
    """Remove datasets the test registered, through the real DELETE route.

    An import writes into ``.curio/users/<id>/datasets/``, which survives
    ``reset-db`` while sqlite recycles user ids from 1 - so without this the next
    run sees a phantom dataset in the catalog.
    """
    registered: list[tuple[str, str]] = []

    def register(token: str, dataset_id: str) -> None:
        registered.append((token, dataset_id))

    yield register

    for token, dataset_id in registered:
        try:
            api_json(
                f"{current_server}/api/datasets/{dataset_id}", token, method="DELETE"
            )
        except Exception as exc:  # noqa: BLE001 - teardown must not mask failures
            print(f"[teardown] DELETE dataset {dataset_id} failed: {exc}")


def test_importing_a_user_dataset_registers_without_attaching(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    delete_imported_datasets,
):
    """A user's own file becomes a catalog entry, but is NOT added to the dataflow.

    Import is deliberately register-only: it creates an account-level catalog
    item and leaves ``dataflow.datasets`` untouched, so the dataset/node link is
    only ever made by an explicit Add. Conflating the two would silently attach
    every imported file to whatever dataflow happened to be open - which is why
    this asserts the *absence* of a palette row before asserting its presence
    after an explicit Add.
    """
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server,
        username="datacat_import", project="Data Catalog Import",
    )
    token = result["token"]

    source = tmp_path / "my-observations.csv"
    source.write_text(
        """station,reading
alpha,1
beta,2
""",
        encoding="utf-8",
    )

    palette = open_tools_palette(page, "datasets")
    palette.get_by_role("button", name="Browse Data Catalog +").click(force=True)
    drawer = _drawer(page)
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)

    # The footer is shared with the Node Catalog; the dataset surface overrides
    # its label and widens `accept` past .curio.zip archives.
    import_button = drawer.get_by_role("button", name="Import dataset")
    expect(import_button).to_be_visible()
    accept = drawer.locator('input[type="file"]').get_attribute("accept")
    assert ".csv" in accept and ".geojson" in accept, accept

    with page.expect_response(
        lambda r: r.url.endswith("/api/datasets/import")
        and r.request.method == "POST"
        and r.ok,
        timeout=60000,
    ) as imported:
        with page.expect_file_chooser() as chooser:
            import_button.click()
        chooser.value.set_files(str(source))

    dataset_id = imported.value.json()["id"]
    delete_imported_datasets(token, dataset_id)

    expect(page.get_by_label("Notifications")).to_contain_text(
        f"Registered {source.name} in the Data Catalog.", timeout=20000
    )

    # 1. It is now a catalog entry the user can see...
    card = _card(drawer, dataset_id)
    expect(card).to_have_count(1, timeout=20000)
    # ...offering Add, which is the proof it was NOT auto-attached.
    expect(
        card.get_by_role("button", name="Add to project", exact=True)
    ).to_be_visible(timeout=20000)
    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_have_count(0)

    # 2. And the dataflow itself is untouched: nothing in the palette.
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#datasets-palette [data-dataset-id="{dataset_id}"]')
    ).to_have_count(0)

    # 3. An explicit Add is what attaches it - and an imported dataset takes the
    #    same path a hub one does.
    drawer = _open_drawer_from_menu(page)
    _card(drawer, dataset_id).get_by_role(
        "button", name="Add to project", exact=True
    ).click()
    with page.expect_response(
        lambda r: "/datasets/install" in r.url
        and r.request.method == "POST"
        and r.ok,
        timeout=30000,
    ):
        # The Data catalog confirms an add now (#196), so the card click only
        # opens the dialog - the POST follows the confirm.
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to project"
        )

    expect(
        _card(drawer, dataset_id).get_by_role(
            "button", name="Remove from project", exact=True
        )
    ).to_be_visible(timeout=20000)
    drawer.locator("header").get_by_role(
        "button", name="Close Data Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#datasets-palette [data-dataset-id="{dataset_id}"]')
    ).to_have_count(1, timeout=20000)



def test_quick_filters_cover_every_populated_format(
    app_frontend: "FrontendPage", current_server: str, page
):
    """#232: the /catalog/data quick-filter chips were a hardcoded three.

    The page renders format filters twice - a sidebar rail derived from the live
    ``facets.format`` counts, and a chip row above the cards that was a literal
    ``["geojson", "csv", "json"]``. So the chips advertised JSON with zero
    datasets while hiding Parquet and GeoTIFF, both of which the rail beside them
    was counting off the shipped ``datasets/`` folder.

    Chips are located by accessible NAME, never by index: the set is derived from
    the catalog now, so a positional locator would silently follow the data.
    """
    require_project_page()
    require_user_auth()

    session = _enter_dataflow(
        page, app_frontend, current_server,
        username="quickfilters", project="Quick Filters",
    )
    token = session["token"]
    # Absorb the cold webpack compile HERE, on the canvas, the way the rest of
    # this suite does. The fixture's readiness gate is port-based, and
    # webpack-dev-server opens its port before the first build finishes - so on
    # a loaded machine the first navigation of a run can outrun the bundle, and
    # every later wait then expires against a page React never mounted.
    page.wait_for_selector(".react-flow__node", timeout=90000)

    page.goto(f"{app_frontend.base_url}/catalog/data")
    # `networkidle`, not `domcontentloaded`: the page renders its rail and chips
    # from the catalog listing, so the markup this test reads does not exist
    # until that request has come back. On a loaded machine the difference is
    # the whole test.
    page.wait_for_load_state("networkidle")
    expect(
        page.get_by_role("heading", name="Data Catalog", exact=True)
    ).to_be_visible(timeout=30000)

    # Located by data attribute, not by class: CSS Modules hashes every class
    # name, so a `[class*=...]` selector matches nothing in a real build - a trap
    # this suite has been caught by before (see test_tools_rail_fits.py).
    bar = page.locator('[data-curio-catalog-filter-bar="true"]')
    expect(bar).to_be_visible(timeout=20000)
    chip = lambda fmt: bar.locator(f'[data-curio-format-chip="{fmt}"]')

    # Gate on a derived chip, not a timeout: the row renders off the facets, so
    # it is empty until the first listing lands.
    expect(chip("geojson")).to_have_count(1, timeout=20000)

    # The contract, not the fixture: the chip row must be exactly the rail
    # formats that hold datasets. An earlier version of this test hardcoded
    # "JSON must be absent", which is only true of a pristine catalog - in a
    # full-suite run another test had published a JSON dataset to the shared
    # hub, so JSON legitimately had a chip and the assertion failed on correct
    # behaviour. Reading the same facet counts the page reads keeps it honest
    # whatever else the suite has left lying around.
    facets = api_json(f"{current_server}/api/datasets/catalog", token)["facets"]["format"]
    expected = [f for f in RAIL_FORMATS if facets.get(f, 0) > 0]
    offered = bar.locator("[data-curio-format-chip]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-curio-format-chip'))"
    )
    assert offered == expected, (
        f"chips {offered} do not match the populated formats {expected} "
        f"(facet counts: {facets})"
    )

    # ...and the shipped catalog must actually exercise the bug, or the check
    # above could pass vacuously. Parquet and GeoTIFF are the two formats the
    # hardcoded list could never show, and both ship with datasets.
    for populated in ("parquet", "geotiff"):
        assert facets.get(populated, 0) > 0, (
            f"{populated} has no datasets, so this test cannot prove #232"
        )
        expect(chip(populated)).to_have_count(1)

    # Every dot must actually be painted. A format-keyed class with no CSS rule
    # resolves to "" and renders an invisible 8px dot - jest cannot catch that at
    # all, because CSS modules are mapped to identity-obj-proxy there.
    for populated in offered:
        colour = chip(populated).locator("[data-curio-format-chip-dot]").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert colour not in ("rgba(0, 0, 0, 0)", "transparent"), (
            f"the {populated} chip's dot is transparent ({colour!r}) - its "
            f".chipDot_* rule is missing"
        )

    # Selecting a format must not collapse the row. The facets are computed
    # BEFORE the format filter is applied (listing.py), and this is what pins
    # that ordering: move the facet call below the filter and this fails.
    chip("parquet").click()
    # If any of these disappears, the facets are being computed AFTER the format
    # filter instead of before it, and the chip row has become self-erasing.
    page.wait_for_timeout(1000)
    after = bar.locator("[data-curio-format-chip]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-curio-format-chip'))"
    )
    assert after == offered, (
        f"selecting Parquet changed the chip row from {offered} to {after}"
    )
