"""Playwright E2E: a package's node reads its saved input after a new sign-in.

A package's node gets the output of the node before it as a reference and reads
it with ``window.curio.fetchData``, the reader the canvas reads outputs with.
While a dataflow is open that reader goes through the dataflow's output route,
which reads an output the dataflow saved from the file its owner's store holds.
The plain ``/get`` reads only the store under the caller's session, so after a
new sign-in, which is a new session, it cannot read that output.

The owner adds ``curio.example-ui@1``, drops a Data Loading node and the Column
Filter, runs the loader with its output saved, and saves. Then the owner leaves
the dataflow, signs in again, which starts a new session, opens the dataflow
from the projects page, and the Column Filter shows the column and the row
count with nobody running anything.

The same reads, without a browser: ``curioGlobalFetchData.test.ts`` and
``exampleUiColumnFilter.test.tsx``.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_package_node_reads_saved_input_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_package_refresh_e2e import _install_from_the_node_catalog
from .utils import (
    api_json,
    close_tools_palette,
    connect_nodes,
    drag_builtin_to_canvas,
    drag_to_canvas,
    enable_save_output,
    node_locator,
    open_tools_palette,
    project_card,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_dataflow,
    set_node_code,
    stub_db_login,
    stub_login_and_enter_workflow,
    wait_for_projects_page,
)
from .walkthroughs.column_filter import COLUMN_FILTER_CODE, EXAMPLE_UI_PKG

if TYPE_CHECKING:
    from .utils import FrontendPage

#: What the Column Filter says once it has read the loader's three rows: its
#: threshold starts at 0 with ">", so every row matches.
ALL_ROWS_MATCH = "3 of 3 rows match"

#: The global the example package's bundle sets once it has run, which is when
#: it registers the Column Filter's behavior (its UMD name, from
#: ``webpack.packages.config.js``).
BUNDLE_GLOBAL = "curio_example-ui_1"


def _open_from_the_projects_page(page, base: str, name: str, project_id: str) -> None:
    """Open the dataflow as a user who has just signed in does: select its card
    on the projects page, then Open dataflow (as ``_open_from_projects`` in
    ``test_loaded_dataflow_saves_e2e.py`` does).

    The projects page loads the bundle of every installed package. The card is
    opened once the example package's bundle has run, so the dataflow's Column
    Filter is built with the behavior the bundle registers.
    """
    page.goto(f"{base}/projects")
    wait_for_projects_page(page, timeout=30000)
    page.wait_for_function(f"() => window[{BUNDLE_GLOBAL!r}] !== undefined", timeout=30000)
    card = project_card(page, name).first
    card.wait_for(state="visible", timeout=30000)
    assert card.get_attribute("data-project-id") == project_id, (
        f"the projects page's card named {name!r} is not the dataflow this test saved"
    )
    card.click()
    expect(page.locator("h2", has_text=name).first).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Open dataflow", exact=True).click()
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=30000)


def _node_text(page, node_id: str) -> str:
    return " ".join((node_locator(page, node_id).text_content() or "").split())


def _reads_the_frame(page, node_id: str, *, when: str) -> None:
    """The Column Filter names the frame's numeric column and counts its rows."""
    body = node_locator(page, node_id)
    try:
        expect(body).to_contain_text(ALL_ROWS_MATCH, timeout=60000)
        expect(body).to_contain_text("population", timeout=10000)
    except AssertionError as exc:
        raise AssertionError(
            f"{when}, the Column Filter did not read the loader's output. "
            f"It shows: {_node_text(page, node_id)[:300]!r}"
        ) from exc


def test_a_package_node_reads_its_saved_input_after_a_new_sign_in(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    base = app_frontend.base_url
    username = f"pkg_reads_{uuid.uuid4().hex[:8]}"

    page.emulate_media(reduced_motion="reduce")
    first = stub_login_and_enter_workflow(
        page, frontend_url=base, backend_url=current_server,
        name="Package Reads", username=username, project_name="Package reads",
    )
    require_owner_view(page)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    project_id = first["project"]["id"]

    _install_from_the_node_catalog(page)

    # A node is 525 px wide at zoom 1: these two drops leave room for the wire
    # between them and keep the filter inside the 1280 px viewport.
    loading = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    set_node_code(page, loading, COLUMN_FILTER_CODE)
    enable_save_output(page, loading)

    open_tools_palette(page, "packages")
    row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{EXAMPLE_UI_PKG}"]')
    expect(row).to_have_count(1, timeout=30000)
    column_filter = drag_to_canvas(page, row, at=(740, 220))
    close_tools_palette(page, "packages")

    connect_nodes(page, loading, column_filter)
    run_node_and_wait(page, loading, node_type="curio.builtin/data-loading")
    _reads_the_frame(page, column_filter, when="In the session that ran the loader")

    saved = save_dataflow(page)
    outputs = [o.get("node_id") for o in (saved.get("outputs") or [])]
    assert loading in outputs, f"the save did not record the loader's output: {outputs}"

    # The owner leaves the dataflow, signs in again, which starts a new
    # session, and opens it again.
    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    second = stub_db_login(
        page, frontend_url=base, backend_url=current_server,
        name="Package Reads", username=username,
    )
    assert second["user"]["id"] == first["user"]["id"], (
        "the second sign-in made a new account instead of signing the owner in again"
    )
    assert second["token"] != first["token"], "the second sign-in reused the first session"
    name = api_json(f"{current_server}/api/projects/{project_id}", second["token"])["project"]["name"]
    _open_from_the_projects_page(page, base, name, project_id)
    require_owner_view(page)
    node_locator(page, column_filter).wait_for(state="visible", timeout=45000)

    # Nobody runs anything: the loader's saved output reaches the filter.
    _reads_the_frame(page, column_filter, when="After a new sign-in")
