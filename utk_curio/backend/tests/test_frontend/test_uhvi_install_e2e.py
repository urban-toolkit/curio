"""Playwright E2E for #154: the UHVI package must be installable from the catalog.

``ai.urbanlab.uhvi@1`` declared ``geopandas ^0.14`` (i.e. ``<1.0.0``) while the
mandatory ``curio.builtin@1`` declares ``>=1.1.3``. Disjoint, so the resolver
correctly reported a conflict and the Install button stayed disabled - and it
could never be resolved, because builtin is ``readOnly`` and refuses to
uninstall. The dialog's only advice ("uninstall one of the conflicting
packages") was impossible to follow, and the package ``docs/NODE-CATALOG.md``
advertises as the one to install to see the packaging flow was unreachable.

The resolver was right; the manifest was wrong. Unit coverage of that lives in
``test_packages/test_resolver.py`` and ``test_packages/test_shipped_catalog.py``.
What only a browser can show is the part the user actually hit: the dialog's
conflict banner and its disabled button. So this asserts on those, then lets the
install round-trip complete.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_uhvi_install_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    dismiss_toasts,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PKG_DIR = "ai.urbanlab.uhvi@1"
PKG_NAME = "Urban Heat Vulnerability Index"
DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'


def _one_node_spec() -> dict:
    """A single node, so ``_wait_for_reactflow_ready`` has something to fit."""
    return {
        "dataflow": {
            "name": "UhviInstallBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "uhvi-baseline-node",
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


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def test_the_uhvi_package_installs_without_a_geopandas_conflict(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    # Drawers slide via translate3d, so reduced motion is what makes
    # `to_be_visible` a real gate rather than a race.
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="UHVI Installer",
        username="uhvi_installer",
        project_name="UHVI Install",
        project_spec=_one_node_spec(),
    )
    require_owner_view(page)

    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    drawer = _drawer(page)

    card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    expect(card).to_have_count(1, timeout=15000)

    # The resolve probe fires on click and posts every installed package plus
    # this candidate - and curio.builtin@1 is always among them, which is what
    # made the conflict unavoidable.
    card.get_by_role("button", name="Add to project", exact=True).click()

    # The install dialog, picked out by its own heading. It used to be selected
    # by negation - "the dialog that is NOT the catalog" - which held only while
    # exactly two dialogs existed. Modals are announced as dialogs too now, so a
    # third one on screen would have made that filter match two elements and
    # fail on strict mode, blaming the install flow for an unrelated panel.
    install_dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name=re.compile(r'^Add "'))
    )
    expect(install_dialog).to_be_visible(timeout=15000)

    # 1. No conflict section. Asserted on the dead-end hint the dialog renders
    #    only when `conflicts.length > 0` (InstallPermissionsDialog), not on the
    #    word "geopandas": the dialog also *lists* the package's own dependencies,
    #    so a bare substring check would fail on the healthy case too.
    expect(
        install_dialog.get_by_text(
            "Remove one of the conflicting packages", exact=False
        )
    ).to_have_count(0)

    dialog_text = install_dialog.inner_text()
    assert "Dependency conflicts" not in dialog_text, (
        "the install dialog still reports dependency conflicts, so UHVI cannot be "
        "added alongside the mandatory built-in package (#154):\n" + dialog_text
    )

    # 2. The button the user could not press. Its label is the dialog's
    #    `confirmLabel` default, and `hasConflicts` is the only thing that would
    #    disable it here (`busy` stays false until it is clicked).
    install_button = install_dialog.get_by_role(
        "button", name="Add to project", exact=True
    )
    expect(install_button).to_be_visible(timeout=10000)
    expect(install_button).to_be_enabled(timeout=10000)

    # Baseline captured with the dialog open and the button live - the state the
    # issue was filed about, and the one no locator assertion can show.
    save_workflow_test_screenshot(
        page, "uhvi-install",
        test_name="test_the_uhvi_package_installs_without_a_geopandas_conflict",
    )

    # 3. And it actually installs.
    with page.expect_response(
        lambda r: "/api/packages" in r.url and r.request.method == "POST",
        timeout=120000,
    ):
        install_button.click()

    expect(
        drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]').get_by_role(
            "button", name="Remove from project", exact=True
        )
    ).to_be_visible(timeout=120000)

    dismiss_toasts(page)
