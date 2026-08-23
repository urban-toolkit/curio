"""Playwright E2E: the Data Catalog drawer.

Mirrors ``test_node_catalog.py`` but across a different boundary. Installing a
dataset does not refresh the palette through a React subscription — it dispatches
a ``window`` CustomEvent (``curio:dataset-catalog-refresh``) that fans out to two
independent module caches keyed on *different* query strings (the drawer asks
with ``includeHub=true&groupOsm=true``, the palette with ``includeHub=false``).
Only a real browser has a window to dispatch on and two live caches to invalidate.

No seeding: the three datasets under ``datasets/`` are scanned live on every
request and surface as ``origin: "hub"``.

Covered more cheaply elsewhere and not re-asserted here:
``test_datasets/test_dataset_catalog_routes.py`` owns the install route, and
``src/tests/components/datasetCardActions.test.tsx`` owns which button a card
shows for a given prop set.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_catalog.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    skip_if_shared_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATASET_ID = "data.urbanlab.chicago-community-areas"
DATASET_TITLE = "Chicago Community Areas"
OTHER_HUB_TITLES = ("Chicago Boundary", "ACS Neighborhood Profile")

DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
SEARCH_PLACEHOLDER = "Search datasets, publishers, tags..."
# The "Adding…" placeholder is an <article role="status"> carrying the same
# title as the real card, so every card locator has to exclude it.
CARD = 'article:not([role="status"])'


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
    )
    skip_if_shared_view(page)
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

    # All three committed hub datasets render, each exactly once — proving the
    # live directory scan reached the browser.
    expect(_card(drawer, DATASET_ID)).to_have_count(1, timeout=15000)
    for title in (DATASET_TITLE, *OTHER_HUB_TITLES):
        expect(
            drawer.locator(CARD).filter(
                has=page.get_by_role("heading", name=title, exact=True)
            )
        ).to_have_count(1, timeout=15000)

    expect(drawer.locator('[role="alert"]')).to_have_count(0)

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
    useDeferredValue — three chances to race that no unit test reproduces.
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

    with page.expect_response(
        lambda r: "/datasets/install" in r.url
        and r.request.method == "POST"
        and r.ok,
        timeout=30000,
    ):
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Add to dataflow", exact=True
        ).click()

    # Re-resolve, never reuse a handle: installing flips origin hub -> imported,
    # which changes the React key so the node is replaced outright, and it patches
    # updatedAt so the card moves under the default "recent" sort.
    expect(
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=20000)

    # THE POINT: close the drawer, and the palette already lists it — the window
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

    # Round-trip. No window.confirm on this path, unlike package removal.
    drawer = _open_drawer_from_menu(page)
    with page.expect_response(
        lambda r: "/datasets/" in r.url and r.request.method == "DELETE",
        timeout=30000,
    ):
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Remove from dataflow", exact=True
        ).click()

    expect(
        _card(drawer, DATASET_ID).get_by_role(
            "button", name="Add to dataflow", exact=True
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
