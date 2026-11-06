"""Playwright E2E: a package's node reads its saved input after a new sign-in.

A package's node gets the output of the node before it as a reference and reads
it with ``window.curio.fetchData``, the reader the canvas reads outputs with.
While a dataflow is open that reader goes through the dataflow's output route,
which reads an output the dataflow saved from the file its owner's store holds.
The plain ``/get`` reads only the store under the caller's session, so after a
new sign-in, which is a new session, it cannot read that output.

The package is ``test.ui-node@1``, made with ``scripts/new_package.py
--with-ui`` and planted in the catalog for the test (``ui_node_in_catalog``).
The owner adds it, drops a Data Loading node and the UI Node, runs the loader
with its output saved, and saves. Then the owner leaves the dataflow, signs in
again, which starts a new session, opens the dataflow from the projects page,
and the UI Node lists the frame's columns with nobody running anything.

The same reads, without a browser: ``curioGlobalFetchData.test.ts``.

Run::

    CURIO_E2E_USE_EXISTING=1 pytest \\
        utk_curio/backend/tests/test_frontend/test_package_node_reads_saved_input_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from utk_curio.backend.tests._support.ui_test_package import (
    UI_TEST_BUNDLE_GLOBAL,
    UI_TEST_NODE_SEND,
    UI_TEST_NODE_WAITING,
    UI_TEST_PACKAGE,
)

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

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The loader's frame: three rows, a numeric column and a text column.
LOADER_CODE = (
    "import pandas as pd\n"
    "df = pd.DataFrame({'population': [2746, 8804, 1200],"
    " 'name': ['Chicago', 'NYC', 'Peoria']})\n"
    "return df\n"
)

#: What the UI Node offers once it has read the loader's frame: the frame's
#: columns, in its order, the first one chosen.
FRAME_COLUMNS = ["population", "name"]

#: The global the package's bundle sets once it has run, which is when it
#: registers the UI Node's behavior (its UMD name, from
#: ``webpack.packages.config.js``).
BUNDLE_GLOBAL = UI_TEST_BUNDLE_GLOBAL


def _open_from_the_projects_page(page, base: str, name: str, project_id: str) -> None:
    """Open the dataflow as a user who has just signed in does: select its card
    on the projects page, then Open dataflow (as ``_open_from_projects`` in
    ``test_loaded_dataflow_saves_e2e.py`` does).

    The projects page loads the bundle of every installed package. The card is
    opened once the package's bundle has run, so the dataflow's UI Node is built
    with the behavior the bundle registers.
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
    """The UI Node lists the frame's columns, and only those, in the frame's
    order, with the first chosen: it read the loader's output, not nothing and
    not an error."""
    body = node_locator(page, node_id)
    choice = body.locator("select")
    try:
        expect(choice.locator("option")).to_have_text(FRAME_COLUMNS, timeout=60000)
        expect(choice).to_have_value(FRAME_COLUMNS[0], timeout=10000)
        expect(body.get_by_role("button", name=UI_TEST_NODE_SEND)).to_be_enabled(timeout=10000)
    except AssertionError as exc:
        raise AssertionError(
            f"{when}, the UI Node did not read the loader's output. "
            f"It shows: {_node_text(page, node_id)[:300]!r}"
        ) from exc
    text = _node_text(page, node_id)
    assert UI_TEST_NODE_WAITING not in text, (
        f"{when}, the UI Node still says it has no frame: {text[:300]!r}"
    )


def test_a_package_node_reads_its_saved_input_after_a_new_sign_in(
    app_frontend: "FrontendPage", current_server: str, page, ui_node_in_catalog,
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
    # between them and keep the UI Node inside the 1280 px viewport.
    loading = drag_builtin_to_canvas(page, "#tile-data-loading", at=(170, 200))
    set_node_code(page, loading, LOADER_CODE)
    enable_save_output(page, loading)

    open_tools_palette(page, "packages")
    row = page.locator(f'#packages-palette [data-pkg-palette-coords~="{UI_TEST_PACKAGE}"]')
    expect(row).to_have_count(1, timeout=30000)
    ui_node = drag_to_canvas(page, row, at=(740, 220))
    close_tools_palette(page, "packages")

    connect_nodes(page, loading, ui_node)
    run_node_and_wait(page, loading, node_type="curio.builtin/data-loading")
    _reads_the_frame(page, ui_node, when="In the session that ran the loader")

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
    node_locator(page, ui_node).wait_for(state="visible", timeout=45000)

    # Nobody runs anything: the loader's saved output reaches the UI Node.
    _reads_the_frame(page, ui_node, when="After a new sign-in")
