"""Playwright E2E: a package installed in one dataflow stays there (#204, #220).

Only a browser settles this. The leak lived in the interaction between a
module-level singleton (``projectPackagesStore``), a React mirror seeded from it
in a PARENT of the component that writes it (``useWorkflowOperations`` vs
``ProjectLoader``), and a ``useSyncExternalStore`` read in the palette. Every
one of those is fine in isolation; the bug was the order they ran in on a route
change, which no unit test observes.

``src/tests/registry/paletteFilterScope.test.ts`` owns the filter rule itself
and is the cheaper place to assert it. What is asserted here is the thing that
actually broke: navigating from a dataflow that HAS a package to a new one.

``curio.example-ui@1`` is the ONLY package a test may install: it declares no
python dependencies, so nothing shells out to pip. See the note at the top of
``test_node_catalog.py``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_catalog_project_scope_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    close_tools_palette,
    open_tools_palette,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PKG_DIR = "curio.example-ui@1"
PKG_COORD = "curio.example-ui@1"
PKG_NAME = "Example: Custom UI Node"

DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'


def _one_node_spec(name: str) -> dict:
    """A single node, so the canvas is never empty on either dataflow."""
    return {
        "dataflow": {
            "name": name,
            "task": "",
            "nodes": [
                {
                    "id": f"{name}-node",
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


def _open_node_catalog(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Node Catalog", exact=True).click()
    page.locator(DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Node Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _palette_coords(page) -> list[str]:
    """Every package coord the packages palette is currently offering.

    The rows only exist while the palette is open, so this opens it rather than
    querying a closed dropdown and reading an empty list as "not there".
    """
    open_tools_palette(page, "packages")
    coords = page.locator("[data-pkg-palette-coords]").evaluate_all(
        "els => els.flatMap(e => (e.getAttribute('data-pkg-palette-coords') || '').split(' '))"
    )
    close_tools_palette(page, "packages")
    return [c for c in coords if c]


def test_a_new_dataflow_does_not_inherit_the_previous_palette(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scope User",
        username="scope_user",
        project_name="Has a package",
        project_spec=_one_node_spec("HasAPackage"),
    )
    require_owner_view(page)

    # The claim is about a package that belongs to ONE dataflow. An account
    # default belongs to all of them, and a new dataflow is supposed to inherit
    # those -- so with the package defaulted this test would assert the opposite
    # of the intended behaviour. Clear it, rather than assume it is absent: the
    # e2e DB truncates per test, restarting user ids, while the user store on
    # disk is keyed by id, so a sibling test's defaults can arrive here.
    api_json(
        f"{current_server}/api/packages/defaults/{PKG_DIR}",
        session["token"],
        method="DELETE",
        timeout=30.0,
    )

    # Get the package into THIS dataflow. Written to tolerate it already being
    # there: the e2e DB is truncated per test, which restarts user ids, while
    # the user package store on disk is keyed BY id -- so a sibling test that
    # writes account defaults can leave them to whoever gets that id next. The
    # assertion below is about the leak, not about who installed what.
    drawer = _open_node_catalog(page)
    card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    expect(card).to_have_count(1, timeout=15000)

    add = card.get_by_role("button", name="Add to project", exact=True)
    if add.count() > 0:
        # Mirrors the install flow in test_node_catalog.py, including waiting on
        # the responses rather than on the dialog appearing: it mounts before
        # /resolve settles.
        with page.expect_response(
            lambda r: r.url.endswith("/api/packages/resolve"), timeout=30000
        ):
            add.click()

        dialog = page.get_by_role("dialog").filter(
            has=page.get_by_role("heading", name=f'Add "{PKG_NAME}"', exact=True)
        )
        expect(dialog).to_be_visible(timeout=10000)
        with page.expect_response(
            lambda r: "/api/packages/projects/" in r.url
            and r.url.endswith("/install")
            and r.request.method == "POST"
            and r.ok,
            timeout=30000,
        ):
            dialog.get_by_role("button", name="Add to project", exact=True).click()
        expect(dialog).to_have_count(0, timeout=30000)

    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_be_visible(timeout=20000)
    page.keyboard.press("Escape")

    assert PKG_COORD in _palette_coords(page), (
        "precondition failed: the package should be on the palette of the "
        "dataflow it was just installed into"
    )

    # Now a brand-new dataflow. This is the reported path.
    page.goto(f"{app_frontend.base_url}/dataflow/new")
    require_owner_view(page)
    page.wait_for_selector(".react-flow", timeout=30000)

    assert PKG_COORD not in _palette_coords(page), (
        f"{PKG_COORD} leaked into a new dataflow's palette (#204): a new "
        "dataflow must start from the account defaults, not from whatever "
        "dataflow happened to be open before it"
    )


def test_remove_is_offered_before_the_first_save(
    app_frontend: "FrontendPage", current_server: str, page, request
):
    """#220's second half: the removal action existed but was unreachable.

    ``performUninstall`` opened with ``if (!projectId) return`` and
    ``onUninstall`` refused to even raise its confirm, and a dataflow has no id
    until its first save. So a package the ACCOUNT DEFAULTS put into a new
    dataflow could not be taken back out of it.

    The default is what makes this reachable without an install: installing from
    the drawer auto-saves (that path always did), which would hand the test a
    project id and quietly stop exercising the unsaved case at all.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Scope User Two",
        username="scope_user_two",
        project_name="Saved once",
        project_spec=_one_node_spec("SavedOnce"),
    )
    require_owner_view(page)

    # Put the package in the account defaults, so every NEW dataflow starts with
    # it and no install (and so no auto-save) is needed to see it.
    api_json(
        f"{current_server}/api/packages/defaults",
        session["token"],
        method="POST",
        payload={"dirName": PKG_DIR},
        timeout=60.0,
    )
    # Undo it whatever happens below. Defaults live in the user store on disk,
    # which the per-test DB truncation does not touch, so leaving one behind
    # hands it to whichever later test is allocated the same user id.
    request.addfinalizer(
        lambda: api_json(
            f"{current_server}/api/packages/defaults/{PKG_DIR}",
            session["token"],
            method="DELETE",
            timeout=30.0,
        )
    )

    # A brand-new, never-saved dataflow.
    page.goto(f"{app_frontend.base_url}/dataflow/new")
    require_owner_view(page)
    page.wait_for_selector(".react-flow", timeout=30000)

    drawer = _open_node_catalog(page)
    card = drawer.locator(f'article[data-pkg-dir="{PKG_DIR}"]')
    expect(card).to_have_count(1, timeout=15000)

    # The defaulted package reads as in-this-dataflow, so the card offers Remove
    # rather than Add — that is the scope working before any save.
    remove = card.get_by_role("button", name="Remove from project", exact=True)
    expect(remove).to_be_visible(timeout=20000)

    # And it actually removes: the click has to auto-save first to have a
    # lockfile to write. Before the fix this returned immediately and nothing
    # happened at all.
    remove.click()
    confirm = page.get_by_role("dialog", name=f"Remove {PKG_NAME}?")
    expect(confirm).to_be_visible(timeout=10000)
    with page.expect_response(
        lambda r: "/api/packages/projects/" in r.url
        and r.request.method == "DELETE"
        and r.ok,
        timeout=60000,
    ):
        confirm.get_by_role("button", name="Remove", exact=True).click()

    expect(
        card.get_by_role("button", name="Add to project", exact=True)
    ).to_be_visible(timeout=30000)
