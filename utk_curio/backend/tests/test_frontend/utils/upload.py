"""Load a dataflow file through the File menu."""

import re

from playwright.sync_api import Error as PlaywrightError

from .environment import debug_log


# ---------------------------------------------------------------------------
# Reusable upload helper
# ---------------------------------------------------------------------------

def upload_workflow(
    page, app_frontend, workflow_file: str, expected_node_count: int
):
    """Open the File menu on the current workflow canvas, upload a workflow
    JSON and wait until the expected number of nodes render.

    The caller is expected to have already navigated ``page`` to a
    ``/dataflow/...`` route (e.g. via ``signup_and_enter_new_workflow``).
    """
    debug_log(
        "fixtures.py:upload_workflow",
        "upload_workflow called",
        {
            "page_type": type(page).__name__,
            "app_frontend_type": type(app_frontend).__name__,
            "workflow_file": workflow_file,
            "expected_node_count": expected_node_count,
            "page_is_closed": page.is_closed(),
            "page_url": str(page.url),
        },
        "H1,H2,H3",
    )
    page.wait_for_load_state("domcontentloaded")

    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except PlaywrightError:
        pass

    file_menu_btn = page.get_by_role("button", name=re.compile("File"))
    file_menu_btn.wait_for(state="visible", timeout=60000)
    file_menu_btn.scroll_into_view_if_needed()
    # force=True so the click isn't captured by the ReactFlow canvas layer
    file_menu_btn.click(force=True)

    # Click "Load dataflow" and upload the JSON file
    load_spec = page.get_by_role("button", name="Load dataflow")
    load_spec.wait_for(state="visible", timeout=15000)
    assert load_spec.is_visible()

    with page.expect_file_chooser() as fc_info:
        # The role locator, not get_by_text: it names the File menu row's
        # button whatever the row nests inside it.
        load_spec.click()
    fc_info.value.set_files(workflow_file)

    # Wait until all expected nodes have rendered on the ReactFlow canvas
    page.wait_for_function(
        f"document.querySelectorAll('.react-flow__node').length >= "
        f"{expected_node_count}",
        timeout=60000,
    )
    # hide the tools menu bar so it doesn't interfere with the test
    # get parent of #tile-data-loading
    loading_tile = page.locator("#tile-data-loading")
    tools_menu_bar = loading_tile.locator("..")
    if tools_menu_bar.count() >= 1:
        page.evaluate(
            "element => { element.style.display = 'none'; }",
            tools_menu_bar.element_handle() # Pass the ElementHandle to the evaluate function
        )

        assert tools_menu_bar.is_hidden() is True, (
            f"Tools menu bar is not hidden"
        )
