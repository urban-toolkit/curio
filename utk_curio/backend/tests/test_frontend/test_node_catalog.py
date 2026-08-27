"""Playwright E2E: the Node Catalog drawer.

The claim only a browser can settle is the last one: installing a package from
the drawer re-renders the tools palette without a reload. That path crosses a
React portal (the drawer is a ``createPortal`` child of ``<body>``), a
module-level singleton (``projectPackagesStore``), a ``useSyncExternalStore``
subscription (``subscribeToRegistry``) and a real injected ``<script>``
(``loadPackageBehaviorScripts``). Nothing below this level spans that graph.

Covered more cheaply elsewhere, and deliberately not re-asserted here:
``test_packages/test_lockfile.py`` owns the lockfile writes, and
``src/tests/components/packageCardActions.test.tsx`` owns which button a card
shows for a given prop set.

``curio.example-ui@1`` is the ONLY package a test may install: it declares no
python dependencies, so nothing shells out to pip. ``curio.weather@1``,
``ai.urbanlab.uhvi@1`` and ``curio.streetvision@1`` pull
rasterio/geopandas/torch through a synchronous call capped at 30 minutes, and
the resulting user-store copy makes every later ``curio start`` re-resolve them
(``main.py`` walks every user store on boot and exits on pip failure).

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_catalog.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
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

PKG_DIR = "curio.example-ui@1"
PKG_ID = "curio.example-ui"
PKG_NAME = "Example: Custom UI Node"
BUILTIN_DIR = "curio.builtin@1"

DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'
SEARCH_PLACEHOLDER = "Search packages, publishers, tags…"


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
    """Authenticated owner session on a saved dataflow, with motion disabled."""
    # Set BEFORE navigating. The drawers slide in via
    # `transform: translate3d(100%)`, which keeps a full bounding box off-screen,
    # so `to_be_visible` would pass before the panel is reachable. Both providers
    # read prefers-reduced-motion through useSyncExternalStore, so emulating it
    # makes presentation synchronous and collapses the 380ms close timer to zero.
    # No reload is needed (or wanted - it races ProjectLoader into the
    # shared-guest fallback): emulate_media fires the matchMedia change event the
    # store already subscribes to.
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Node Catalog User",
        username=username,
        project_name=project,
        project_spec=_one_node_spec(),
    )
    require_owner_view(page)
    return result


def _open_drawer_from_menu(page):
    """Data menu -> Node Catalog."""
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    # "Node Catalog" also labels the palette trigger, whose accessible name
    # includes a count span - exact=True picks out the menu row's own button.
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    return _drawer(page)


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # Resolved by heading rather than role name: the install dialog is also a
    # role="dialog" but carries NO accessible name, so a bare get_by_role would
    # be a strict-mode violation whenever it is open.
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _card(drawer, dir_name):
    return drawer.locator(f'article[data-pkg-dir="{dir_name}"]')


def test_drawer_lists_catalog_packages(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="nodecat_list", project="Node Catalog List",
    )

    drawer = _open_drawer_from_menu(page)

    expect(_card(drawer, PKG_DIR)).to_have_count(1, timeout=15000)
    expect(
        _card(drawer, PKG_DIR).get_by_role("button", name="Add to dataflow", exact=True)
    ).to_be_visible()

    # curio.builtin ships with every instance and can be neither uninstalled nor
    # published, so its card must offer nothing.
    expect(_card(drawer, BUILTIN_DIR).get_by_role("button")).to_have_count(0)

    # A wedged user store (a half-copied package dir with no manifest) surfaces
    # here as an error banner. Asserting its absence turns that into a legible
    # failure instead of a button that mysteriously never flips.
    expect(drawer.locator('[role="alert"]')).to_have_count(0)

    # Visual baseline of the drawer in its listing state. The assertions above
    # cover which cards and buttons exist; this covers the layout they sit in,
    # which no locator can see. Captured with the drawer open, before the
    # close/reopen cycle below changes what is on screen.
    save_workflow_test_screenshot(
        page, "node-catalog-drawer", test_name="test_drawer_lists_catalog_packages",
    )

    # Escape closes and the portal unmounts; reopening mounts exactly one. Guards
    # the duplicate-portal regression the provider's own comment says once shipped.
    page.keyboard.press("Escape")
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    _open_drawer_from_menu(page)
    expect(page.locator(DRAWER_ROOT)).to_have_count(1)


def test_drawer_search_filters_by_package_id(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="nodecat_search", project="Node Catalog Search",
    )

    drawer = _open_drawer_from_menu(page)
    expect(_card(drawer, PKG_DIR)).to_have_count(1, timeout=15000)

    # Filtering is client-side and synchronous (packageUtils.matchesSearch), so
    # no debounce budget is needed. Searching the id proves it matches on more
    # than the display name.
    drawer.get_by_placeholder(SEARCH_PLACEHOLDER).fill(PKG_ID)
    expect(drawer.locator("article")).to_have_count(1, timeout=10000)
    expect(_card(drawer, PKG_DIR)).to_have_count(1)

    drawer.get_by_placeholder(SEARCH_PLACEHOLDER).fill("")
    # Count-free on purpose: adding a package under packages/ must not break this.
    expect(_card(drawer, BUILTIN_DIR)).to_have_count(1, timeout=10000)


def test_add_package_propagates_to_palette(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server,
        username="nodecat_add", project="Node Catalog Add",
    )
    token = result["token"]
    project_id = result["project"]["id"]

    # 1. pip-free precondition, before any click. Self-guarding: if the manifest
    #    ever grows a dependency this fails in a second instead of hanging in pip.
    catalog = api_json(f"{current_server}/api/packages/catalog", token)
    row = next(p for p in catalog["packages"] if p["dirName"] == PKG_DIR)
    assert row["dependencies"]["python"] == {}, (
        f"{PKG_DIR} gained python deps {row['dependencies']['python']}; the e2e "
        f"suite cannot stub pip (it runs in the backend subprocess). Pick another "
        f"zero-dep package or this test will shell out to pip."
    )
    assert row["permissions"] == [], row["permissions"]

    # 2. Hard guard: only this coordinate may reach the install endpoint, so a
    #    mis-targeted click fails in milliseconds rather than installing torch.
    def _only_the_safe_package(route):
        if PKG_DIR in (route.request.post_data or ""):
            route.continue_()
        else:
            route.abort()

    page.route("**/api/packages/projects/*/install", _only_the_safe_package)

    lock_before = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]

    # 3. Enter from the palette footer, which leaves the palette mounted for the
    #    post-condition below.
    palette = open_tools_palette(page, "packages")
    palette.get_by_role("button", name=re.compile(r"^Browse Node Catalog")).click(
        force=True
    )
    drawer = _drawer(page)
    card = _card(drawer, PKG_DIR)
    expect(card).to_have_count(1, timeout=15000)

    # 4. The dialog mounts BEFORE /resolve settles, and a non-409 error unmounts
    #    it again - so wait on the response, not just on the dialog appearing.
    with page.expect_response(
        lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000
    ):
        card.get_by_role("button", name="Add to dataflow", exact=True).click()

    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    # hasConflicts disables confirm permanently, which would otherwise surface as
    # a 30s click timeout with no explanation.
    expect(
        dialog.get_by_text("Dependency conflicts with installed packages")
    ).to_have_count(0)
    confirm = dialog.get_by_role("button", name="Add to dataflow", exact=True)
    expect(confirm).to_be_enabled()

    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST"
        # 201, not 200 - the route reports a created lockfile entry.
        and r.ok,
        timeout=30000,
    ):
        confirm.click()
    # Never target the "Adding…" label; watch the dialog unmount instead.
    expect(dialog).to_have_count(0, timeout=30000)

    # 5. The card flips.
    expect(
        card.get_by_role("button", name="Remove from dataflow", exact=True)
    ).to_be_visible(timeout=20000)
    expect(card.get_by_role("button", name="Add to dataflow", exact=True)).to_have_count(0)

    # 6. Badge count derived from the API: a new project's lockfile may or may
    #    not already carry curio.builtin@1, so a literal would be brittle.
    tabs = drawer.get_by_role("navigation", name="Catalog sections")
    expect(tabs.get_by_role("button", name=re.compile(r"^In dataflow"))).to_have_text(
        re.compile(rf"^In dataflow\s*{len(lock_before) + 1}$"), timeout=15000
    )

    # 7. THE POINT: close the drawer (its overlay is inset:0 with
    #    pointer-events:auto and would swallow the palette click), then the
    #    palette must already show the new package with no reload.
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    # ~= not =: PackagesPaletteDropdown renders a space-joined list of member
    # keys for fork families.
    expect(
        page.locator(f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]')
    ).to_have_count(1, timeout=20000)

    # 8. Diagnostic read: localises a UI failure to backend vs frontend.
    lock_after = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]
    assert set(lock_after) == set(lock_before) | {PKG_DIR}, lock_after

    # 9. Remove round-trip. Playwright's default dialog action is DISMISS, which
    #    would make this a silent no-op, so handle it selectively.
    def _accept_if_about_our_package(dialog_):
        if PKG_DIR in dialog_.message:
            dialog_.accept()
        else:
            dialog_.dismiss()
            pytest.fail(f"unexpected confirm: {dialog_.message!r}")

    page.once("dialog", _accept_if_about_our_package)
    drawer = _open_drawer_from_menu(page)
    card = _card(drawer, PKG_DIR)
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.request.method == "DELETE",
        timeout=30000,
    ):
        card.get_by_role("button", name="Remove from dataflow", exact=True).click()

    expect(
        card.get_by_role("button", name="Add to dataflow", exact=True)
    ).to_be_visible(timeout=20000)
    drawer.locator("header").get_by_role(
        "button", name="Close Node Catalog drawer"
    ).click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#packages-palette [data-pkg-palette-coords~="{PKG_DIR}"]')
    ).to_have_count(0, timeout=20000)

    # Uninstall also prunes the user-store copy, so the test leaves no residue
    # that would make a re-run vacuous.
    lock_final = api_json(
        f"{current_server}/api/packages/projects/{project_id}", token
    )["packages"]
    assert set(lock_final) == set(lock_before), lock_final
