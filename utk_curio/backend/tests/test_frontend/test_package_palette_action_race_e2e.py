"""Playwright E2E: a package row's summary actions survive the row growing.

The regression guard for the second half of #334 - the one the export-download
timeout bump (#335) and the self-hosted webfont (``bc321854``) did not cure,
because neither was the cause.

**What actually happened.** The packages palette renders its rows from the
installed-package registry, which is ready immediately. The ``CatalogPublishPill``
in each row's ``<summary>`` waits on a *separate* catalog snapshot - three
parallel API calls behind one ``setState`` - so for a while each row shows only
its Export and Edit buttons. Those actions share a flex cluster with the row
title, and the title is ``flex: 1``, so it absorbs the slack. When the pill
finally mounts, every button to its left jumps ~65px left.

``test_package_roundtrip_e2e`` clicked Export with ``force=True``, which turns
off Playwright's hit-target check. Dispatched just after that jump, the click
landed on **Publish** instead: the "Publish this package?" confirm dialog opened,
its overlay covered the palette, the export was never requested, and the test sat
out its whole budget waiting for a download that was never coming. The CI failure
screenshot for run 35453502118 shows exactly that dialog. Under load the snapshot
lands later, which is why it read as "CI load" rather than as a race.

**What this test does.** It stops waiting for a loaded runner to produce the
window and holds it open itself: the catalog call is parked in a route handler,
so the row is on screen and clickable while the pill is still guaranteed to be
missing. The call is released immediately before the export click, which puts
the mount and the click in the same moment - the collision, on demand, on any
machine.

It deliberately does not re-test the archive: ``test_package_export_import.py``
owns the download bytes. All this needs is that the download begins at all, that
no confirm dialog opened in its place, and that the row really did grow across
the click - otherwise the test would be proving nothing about a hazard that had
already passed.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_package_palette_action_race_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from .utils import (
    EXPORT_DOWNLOAD_TIMEOUT_MS,
    api_json,
    click_package_summary_action,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: A package built through the factory route rather than installed from the
#: committed catalog, and that distinction is the whole point: the catalog IS
#: the published set, so a catalog package counts as already published and its
#: row renders no Publish pill at all (``InstalledPackageAccordion`` passes no
#: ``onUnpublish``). Only an unpublished package - which is what a canvas-authored
#: one is, and what CI had - grows the pill that moves the Export button.
PACKAGE_ID = "ai.test.paletterace"

#: The smallest draft the factory accepts. The body imports nothing, so the
#: install derives no dependencies and does not shell out to pip.
DRAFT = {
    "manifest": {
        "id": PACKAGE_ID,
        "version": "1.0.0",
        "createdAt": "2000-01-01T00:00:00Z",
        "name": "Palette Race",
        "publisher": "Tests",
        "description": "Fixture for the palette action race guard",
        "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [],
        "dependencies": {"packages": {}, "python": {}, "js": {}},
        "templates": [
            {
                "id": "demo",
                "label": "Demo",
                "category": "computation",
                "engine": "python",
                "editor": "code",
                "hasCode": True,
                "hasWidgets": False,
                "hasGrammar": False,
                "inputPorts": [],
                "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
                "source": "sources/demo.py",
            }
        ],
    },
    "sources": {"demo": {"filename": "demo.py", "code": "def run():\n    return {}\n"}},
}


@pytest.fixture
def uninstall_packages(current_server):
    """Remove what this test installed, through the real DELETE route.

    ``.curio/users/<id>/packages/`` outlives ``reset-db`` while sqlite recycles
    user ids from 1, so a leak would show up in every later test's palette.
    """
    registered: list[tuple[str, str]] = []

    def register(token: str, dir_name: str) -> None:
        registered.append((token, dir_name))

    yield register

    for token, dir_name in registered:
        try:
            api_json(
                f"{current_server}/api/packages/{dir_name}", token, method="DELETE"
            )
        except Exception as exc:  # pragma: no cover - teardown only
            print(f"[teardown] DELETE package {dir_name} failed: {exc}")


def test_export_click_survives_the_publish_pill_mounting_late(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
    tmp_path,
    uninstall_packages,
):
    """Export exports, even when the row grows underneath the click."""
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Palette Racer",
        username="palette_racer",
        project_name="Palette Action Race",
    )
    require_owner_view(page)
    token = session["token"]

    # Two steps, because the palette is project-scoped: the factory install puts
    # the package in the user's store, and only the project lockfile install puts
    # a row in this dataflow's palette.
    installed = api_json(
        f"{current_server}/api/packages/factory/install",
        token,
        method="POST",
        payload=DRAFT,
        timeout=60.0,
    )
    dir_name = installed["package"]["dirName"]
    api_json(
        f"{current_server}/api/packages/projects/{session['project']['id']}/install",
        token,
        method="POST",
        payload={"dirName": dir_name},
    )
    uninstall_packages(token, dir_name)

    # Park the catalog call instead of delaying it by a fixed amount: a sleep
    # would be a race of its own on a slow runner, and blocking inside the
    # handler would deadlock the sync dispatcher. Holding the route object and
    # releasing it from the test keeps the page fully drivable meanwhile.
    #
    # Matched on the path, not a glob, so ``/api/packages/catalog/install`` and
    # any query string cannot be caught by accident. Only the browser's call is
    # affected; the install above goes over plain HTTP from Python.
    # The palette effect re-runs (its deps change while the call is in flight),
    # so more than one catalog request can be parked. Release every one of them
    # and let anything issued afterwards straight through - holding a later
    # request would keep the snapshot pending for good.
    held: list = []
    released = {"yes": False}

    def _hold_catalog(route):
        if released["yes"]:
            route.continue_()
        else:
            held.append(route)

    page.route(
        lambda url: urlparse(url).path.endswith("/api/packages/catalog"),
        _hold_catalog,
    )

    def _release_catalog():
        released["yes"] = True
        for route in held:
            try:
                route.continue_()
            except Exception as exc:  # a request React already abandoned
                print(f"[race] parked route could not be continued: {exc}")

    page.reload()
    page.wait_for_load_state("domcontentloaded")
    open_tools_palette(page, "packages")

    anchor = page.locator(
        f'#packages-palette [data-pkg-palette-coords~="{dir_name}"]'
    )
    expect(anchor).to_have_count(1, timeout=20000)

    export_button = anchor.locator('button[title="Export package"]')
    expect(export_button).to_be_visible(timeout=20000)

    # The row is on screen and its Export button is clickable, but the palette
    # has not finished growing. This is the window the flake lived in, and it
    # stays open until the line that releases the route.
    palette = page.locator("#packages-palette [data-curio-palette-catalog]")
    expect(palette).to_have_attribute("data-curio-palette-catalog", "loading")
    box_before = export_button.bounding_box()

    assert held, "the catalog call was never routed, so nothing is being held"
    _release_catalog()

    with page.expect_download(timeout=EXPORT_DOWNLOAD_TIMEOUT_MS) as download:
        click_package_summary_action(page, anchor, "Export package")
    download.value.save_as(tmp_path / "raced.curio.zip")

    # The failure mode this guards is not "no download" but "the wrong button":
    # had the click landed on Publish, this dialog would be up. Assert it by
    # name, so a regression says which control was hit rather than only that the
    # export did not happen.
    expect(page.get_by_role("heading", name="Publish this package?")).to_have_count(0)

    # And prove the hazard was live rather than already past: the pill landed
    # across the click and moved the button. If this ever fails because the
    # summary stopped reflowing, the race is gone at the source and this whole
    # test can go with it.
    expect(palette).to_have_attribute("data-curio-palette-catalog", "loaded")
    box_after = export_button.bounding_box()
    assert box_before and box_after
    assert box_after["x"] < box_before["x"], (
        "the Publish pill never mounted, so the export button never moved and "
        f"this test raced nothing (x {box_before['x']} -> {box_after['x']})"
    )
