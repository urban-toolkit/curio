"""Playwright E2E for #217: a saved output stays in the Data Catalog.

The report: with "Save tabular output to Data Catalog on run" enabled on a
Python Computation node returning ``1``, the dataset "shows up in the Data
Catalog for about a second and then disappears".

This is deliberately written as a REPRODUCTION first. The plan for #217 called
for a failing test before a fix, because the mechanism was never settled --
three candidate causes were ruled out against the code and none of them
explained it:

  * the scalar is not a failed install. ``int`` is in ``ROW_ONLY_KINDS``, so
    ``install_node_output`` synthesises the bytes from the DuckDB row
    (``install/bundle.py``). ``test_computed_json_output_e2e.py`` already pins
    exactly this and passes, which is the strongest evidence that the dataset
    is CREATED and persists;
  * live outputs are not dropped once the dataflow has an id -- the
    ``dataflow_id`` branch in ``listing.py`` passes them through;
  * the catalog is refreshed on both save branches --
    ``syncDatasetsFromSavedSpec`` calls ``notifyDatasetCatalogRefresh``.

What the report describes is therefore most likely a DISPLAY defect rather than
a persistence one: the row leaves the drawer while the dataset still exists.
That is what this asserts, and it is the distinction the issue cannot make from
the outside -- so the test checks the API and the drawer separately, and says
which of the two is wrong when it fails.

The "about a second" is not folklore: ``applyNewOutput`` ->
``scheduleInstallSyncRef`` paints an optimistic "Adding..." row and debounces
500 ms before the save whose ``.finally`` clears it (``FlowProvider.tsx``). So
the window the reporter describes is exactly the placeholder's lifetime, and
anything asserted before that has settled is asserting against a state that has
not happened yet.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_computed_dataset_persists_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    canvas_node_type,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#step-analysis"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"
DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'

# The reported code, exactly. A scalar is the shape with no artifact file of its
# own, which is what made #180 mis-report it as a failed generation.
SCALAR_CODE = "return 1\n"

# Long enough to cover the 500 ms install-sync debounce, its save round trip and
# the catalog refetch that follows -- i.e. past the window in which the reporter
# says the row is still visible.
SETTLE_MS = 4000


def _install_save_response(project_id: str, node_id: str):
    """Match the project save that carries this node's output ref."""

    def predicate(response) -> bool:
        if f"/api/projects/{project_id}" not in response.url:
            return False
        if response.request.method not in ("PUT", "POST"):
            return False
        return node_id in (response.request.post_data or "")

    return predicate


def _enable_save_toggle(page, node_id: str) -> None:
    """Flip the node's save-output toggle on through the UI.

    The deployment default is off, and "the user enabled the toggle" is the
    scenario #217 reports. Keying on the aria-label makes the click double as an
    assertion that it actually flipped.
    """
    toggle = node_locator(page, node_id).locator(f"label:has(input#save-output-{node_id})")
    toggle.wait_for(state="visible", timeout=15000)
    if "enabled" in (toggle.get_attribute("aria-label") or ""):
        return
    toggle.click()
    expect(toggle).to_have_attribute(
        "aria-label", "Save output to Data Catalog enabled", timeout=10000
    )


def _open_data_catalog(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Data Catalog", exact=True).click()
    page.locator(DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _computed_rows(drawer, node_id: str):
    """Catalog rows produced by *node_id*.

    Matched on the producing node rather than on a title: a computed dataset's
    title is derived and has changed shape before, while the producer is what
    the row is actually about.
    """
    return drawer.locator(f'article[data-dataset-id*="{node_id}"]')


def _server_has_dataset(current_server: str, token: str, project_id: str, node_id: str) -> bool:
    """Does the ACCOUNT hold a computed dataset for this node?

    Read from the API rather than the drawer, so a failure can say whether the
    dataset stopped existing or merely stopped being shown -- the distinction
    the issue could not make from the outside.
    """
    catalog = api_json(
        f"{current_server}/api/datasets/catalog?includeHub=false&dataflowId={project_id}",
        token,
    )
    return any(node_id in str(item.get("id", "")) for item in catalog.get("items", []))


def test_a_saved_scalar_output_stays_in_the_data_catalog(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    # Before navigating: the drawer reads prefers-reduced-motion through
    # useSyncExternalStore, and doing this after login races ProjectLoader into
    # the shared-guest fallback.
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Persist User",
        username="persist_user",
        project_name="Saved output persists",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=(200, 180))
    # Palette-dragged nodes carry the package major (``...@1``), so compare the
    # unversioned form -- the assertion is "we dragged the right tile", not
    # "the registry pins this major".
    assert canvas_node_type(page, node_id).split("@")[0] == ANALYSIS_TYPE
    set_node_code(page, node_id, SCALAR_CODE)
    _enable_save_toggle(page, node_id)

    # Armed BEFORE the run: the install-save is 500 ms debounced after the node
    # reports Done, so asserting at Done asserts against a state that has not
    # happened yet.
    with page.expect_response(
        _install_save_response(project_id, node_id), timeout=180000
    ) as save_info:
        run_node_and_wait(page, node_id, node_type=ANALYSIS_TYPE)
    save = save_info.value
    assert save.ok, f"install-save failed: {save.status} {save.url}"

    # The save reported no trouble generating it. If this fails, the defect is
    # in the install path and the disappearance is a symptom, not the bug.
    warnings = save.json().get("dataset_install_warnings")
    assert warnings == [], f"the run reported install warnings: {warnings!r}"

    dismiss_toasts(page)
    drawer = _open_data_catalog(page)
    expect(_computed_rows(drawer, node_id).first).to_be_visible(timeout=30000)

    # THE POINT. Past the debounce, the save and the refetch that follows it --
    # i.e. past the window the reporter describes as "about a second".
    page.wait_for_timeout(SETTLE_MS)

    on_server = _server_has_dataset(current_server, token, project_id, node_id)
    assert _computed_rows(drawer, node_id).count() > 0, (
        "the dataset left the Data Catalog after the run settled (#217). "
        + (
            "It still exists server-side, so this is a display defect: the "
            "drawer stopped listing a dataset that is there."
            if on_server
            else "It is gone server-side too, so the run did not persist it "
            "despite reporting no install warnings."
        )
    )

    # And it survives a reload, which is the difference between "listed from
    # this session's live outputs" and "actually saved".
    page.reload()
    require_owner_view(page)
    drawer = _open_data_catalog(page)
    expect(_computed_rows(drawer, node_id).first).to_be_visible(timeout=30000)


def test_the_row_survives_a_run_watched_from_an_open_drawer(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    """The same claim, watched the way the reporter watched it.

    The test above opens the Data Catalog after the run has settled, and passes.
    That is not what #217 describes: "shows up for a moment and then
    disappears" is someone with the drawer ALREADY OPEN, seeing the optimistic
    "Adding..." row painted by ``beginPendingInstall`` and then cleared by the
    save's ``.finally``.

    So this holds the drawer open across the whole run. If the row the
    placeholder stood for does not take its place, the drawer visibly loses a
    dataset that exists -- which is the reported experience even though nothing
    was lost.
    """
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Watching User",
        username="watching_user",
        project_name="Watched from the drawer",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    node_id = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=(200, 180))
    set_node_code(page, node_id, SCALAR_CODE)
    _enable_save_toggle(page, node_id)

    # Open FIRST, and pin it so a click on the canvas cannot dismiss it.
    drawer = _open_data_catalog(page)
    pin = drawer.get_by_role("button", name=re.compile("^(Pin|Unpin)", re.I))
    if pin.count() > 0 and "Pin" in (pin.first.get_attribute("aria-label") or "Pin"):
        pin.first.click()

    with page.expect_response(
        _install_save_response(project_id, node_id), timeout=180000
    ) as save_info:
        run_node_and_wait(page, node_id, node_type=ANALYSIS_TYPE)
    assert save_info.value.ok

    page.wait_for_timeout(SETTLE_MS)

    on_server = _server_has_dataset(current_server, token, project_id, node_id)
    assert _computed_rows(drawer, node_id).count() > 0, (
        "the row vanished from a drawer that was open across the run (#217). "
        + (
            "The dataset exists server-side, so the optimistic row was cleared "
            "without the real one taking its place."
            if on_server
            else "The dataset does not exist server-side either."
        )
    )
