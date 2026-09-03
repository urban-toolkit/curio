"""Playwright E2E for #194's delivery half: an upgrade must reach an existing install.

The Column Filter fix shipped inside ``curio.example-ui@1`` at an unchanged
version. That is the ordinary shape of a Curio upgrade — the catalog under
``packages/`` moves, the coordinate does not — and installing is copy-once:
``install_to_store`` returns early when the directory is already there, and
``_ensure_user_store_install`` copies with ``replace=False``. So a user who had
the package before the upgrade kept the broken ``behaviors.js`` indefinitely,
and the node kept saying "Connect a DataFrame upstream" against a frame that
was right there.

The recheck found this by hashing the file on a live machine: two accounts held
``d20d470728cf`` (pre-fix) while the catalog and a fresh install held
``2d2100dd7828``. This test does the same comparison as a regression, and does
it through ``/api/testing/package-store`` rather than from the pytest process,
because under a compose stack the harness does not share the container's
filesystem — the same reason ``dataset-paths`` resolves paths server-side.

Run::

    CURIO_E2E_USE_EXISTING=1 CURIO_TESTING=1 \
      pytest utk_curio/backend/tests/test_frontend/test_package_refresh_e2e.py -v
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

from playwright.sync_api import expect

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PKG_DIR = "curio.example-ui@1"
#: The file the #194 fix actually changed. Hashing the manifest would compare
#: something the fix never touched and pass either way.
PKG_FILE = "scripts/behaviors.js"
NODE_DRAWER = '[data-curio-node-catalog-drawer="true"]'
#: A fresh account per run. Not load-bearing since ``reset-db`` began clearing
#: the per-user tree, but it keeps a failure message about *this* run rather
#: than about whatever account last held the id.
USERNAME = f"pkg_refresh_{uuid.uuid4().hex[:10]}"


def _package_store(backend: str, **body) -> dict:
    """Call the dev-only store probe, server-side."""
    req = Request(
        f"{backend}/api/testing/package-store",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=20) as resp:  # noqa: S310 — trusted local URL
        return json.loads(resp.read().decode("utf-8") or "{}")


def _install_from_the_node_catalog(page) -> None:
    """Add ``curio.example-ui@1`` through the drawer, the way a user would."""
    page.get_by_text("NODE CATALOG").click()
    page.get_by_role("button", name=re.compile("Browse Node Catalog")).click()
    drawer = page.locator(NODE_DRAWER)
    drawer.wait_for(state="attached", timeout=15000)
    expect(drawer).to_have_attribute("aria-hidden", "false", timeout=10000)

    card = page.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    if card.count() == 0:
        card = page.locator("article").filter(has_text="Example: Custom UI Node").first
    card.first.get_by_role("button", name=re.compile(r"^Add to project")).click()
    page.get_by_role("dialog").last.get_by_role(
        "button", name=re.compile(r"^(Add|Install)")
    ).last.click()
    # The install copies the tree and pip-resolves; give it room.
    expect(
        page.locator(f'article[data-pkg-dir="{PKG_DIR}"]').first.get_by_role(
            "button", name="Remove from project"
        )
    ).to_be_visible(timeout=120000)
    page.keyboard.press("Escape")


def test_an_upgrade_reaches_a_package_that_is_already_installed(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Refresh User",
        username=USERNAME,
        project_name="PackageRefresh",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

    # State the starting point rather than assume it. ``reset-db`` clears the
    # per-user tree now, so this is belt and braces — but this test plants a
    # perturbed file on purpose, and inheriting one would fail the first
    # assertion below while describing a run that already finished.
    _package_store(current_server, username=USERNAME, dirName=PKG_DIR, action="reset")

    _install_from_the_node_catalog(page)

    # 1. A fresh install matches the catalog. If this ever fails the install
    #    itself is broken and everything below would be measuring that instead.
    fresh = _package_store(
        current_server, username=USERNAME, dirName=PKG_DIR, path=PKG_FILE, action="hash",
    )
    assert fresh["catalog_sha256"], "the catalog has no copy of the probe file"
    assert fresh["sha256"] == fresh["catalog_sha256"], (
        "a fresh install already differs from the catalog it was copied from: "
        f"store {fresh['sha256'][:12]} vs catalog {fresh['catalog_sha256'][:12]}"
    )

    # 2. Make the store copy stale, exactly as an upgrade does: the catalog
    #    moves on while the user's copy stays where it was.
    stale = _package_store(
        current_server, username=USERNAME, dirName=PKG_DIR, path=PKG_FILE, action="stale",
    )
    assert stale["sha256"] != stale["catalog_sha256"], (
        "planting staleness did not change the hash, so the rest of this test "
        "would pass without proving anything"
    )

    # 3. Reopen the dataflow. `save_project` / `load_project` call
    #    `ensure_builtin_seeded`, which is the hook an upgrade rides in on.
    page.reload()
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    page.wait_for_timeout(3000)

    # 4. THE POINT: the store copy is the catalog's again.
    after = _package_store(
        current_server, username=USERNAME, dirName=PKG_DIR, path=PKG_FILE, action="hash",
    )
    assert after["sha256"] == after["catalog_sha256"], (
        "the stale copy was never refreshed, so a fix shipped inside a package "
        "at an unchanged version never reaches a user who already had it: "
        f"store {after['sha256'][:12]} vs catalog {after['catalog_sha256'][:12]}"
    )
