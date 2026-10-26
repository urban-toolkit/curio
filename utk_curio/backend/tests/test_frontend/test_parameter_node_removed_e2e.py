"""Playwright E2E: the Parameter node is gone.

* The Built-in palette has no Parameter tile.
* A dataflow saved with a Parameter node opens with that node as a type no
  installed package provides. Builtin is installed and only dropped the type,
  so the node gets the "Removed node type" card, titled with the type, which
  names Builtin and offers no Install button. Nothing aliases or migrates it,
  and every other node opens as it was saved. A node whose code reads the
  Parameter node's value, ``[!! @season !!]``, draws that reference as a
  problem: ``@season`` names no widget.
* Run All on it ends, as on any dataflow: the node that reads
  ``[!! @season !!]`` ends in an error that says it names no widget, the node
  that reads nothing of it ends done, and the Parameter node stays its card.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_parameter_node_removed_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_compare_scenarios_removed_e2e import _node, _opened_as
from .utils import (
    dismiss_toasts,
    frame_node,
    node_locator,
    open_tools_palette,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The type a saved Parameter node carries.
PARAMETER_TYPE = "curio.builtin/parameter"
PYTHON_TYPE = "curio.builtin/computation-analysis"
PROJECT = "Parameter node removed e2e"

PARAMETER = "prm-gone-parameter"
READER = "prm-gone-reader"
OTHER = "prm-gone-other"
#: How long Run All may take on this small dataflow: well under the ten
#: minutes a level waits for a node that never reports before it moves on.
RUN_ALL_MS = 180000

#: The one widget a saved Parameter node holds, with the value it was set to.
SEASON = {
    "name": "season", "type": "choice", "label": "Season", "default": "summer",
    "options": {"choices": ["summer", "winter"]}, "value": "winter",
}
#: A node whose code read the Parameter node's value.
READER_CODE = "season = [!! @season !!]\nreturn season\n"
#: A node that reads nothing of it.
OTHER_CODE = "return 1\n"
#: What a run says of the reader's reference.
REFUSAL = "[!! @season !!] does not name a widget. Widget names are letters, digits and underscores."


def _spec() -> dict:
    return {
        "dataflow": {
            "name": PROJECT,
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(PARAMETER, PARAMETER_TYPE, "", 0, metadata={"widgets": [SEASON]}),
                _node(READER, PYTHON_TYPE, READER_CODE, 700),
                _node(OTHER, PYTHON_TYPE, OTHER_CODE, 700, 600),
            ],
            "edges": [],
        },
    }


def _enter(page, app_frontend, current_server, *, prefix: str, spec: dict | None = None) -> None:
    """Sign in as a fresh owner, on the canvas of a fresh dataflow saved as
    *spec* (an empty one by default)."""
    require_project_page()
    require_user_auth()
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Parameter Gone",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name=PROJECT,
        project_spec=spec,
    )
    require_owner_view(page)
    dismiss_toasts(page)


def test_the_built_in_palette_has_no_parameter_tile(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="prm_gone_palette")
    panel = open_tools_palette(page, "builtin")
    # The registry has answered once the Map Editor node's tile is there.
    expect(panel.locator("#tile-edit-features")).to_be_visible(timeout=30000)
    tiles = panel.locator('[id^="tile-"]').evaluate_all("(tiles) => tiles.map((tile) => tile.id)")
    assert "tile-parameter" not in tiles, f"the Built-in palette holds the Parameter node: {tiles}"
    expect(panel.get_by_label("Parameter", exact=True)).to_have_count(0)


def test_a_dataflow_saved_with_a_parameter_node_opens_with_it_as_a_removed_type(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="prm_gone_saved", spec=_spec())
    page.wait_for_selector(".react-flow__node", timeout=45000)

    opened = {node_id: _opened_as(page, node_id) for node_id in (PARAMETER, READER, OTHER)}
    assert opened == {PARAMETER: "removed type", READER: "its own body", OTHER: "its own body"}, (
        f"the saved Parameter node should open as a type its installed package no longer has: {opened}"
    )

    card = node_locator(page, PARAMETER).get_by_test_id("removed-node-type")
    expect(card).to_have_attribute("data-tooltip", f"No installed package provides {PARAMETER_TYPE}")
    expect(card).to_contain_text("Removed node type")
    expect(card).to_contain_text(f"This dataflow asks for {PARAMETER_TYPE}, which Builtin no longer has.")
    expect(card.get_by_role("button")).to_have_count(0)
    expect(node_locator(page, PARAMETER).locator("[data-parameter-panel]")).to_have_count(0)

    # The reader's reference names no widget, so its editor draws it as a problem.
    frame_node(page, READER)
    editor = node_locator(page, READER).locator(".monaco-editor")
    editor.locator(".curio-widget-ref-problem").first.wait_for(state="attached", timeout=15000)
    assert editor.locator(".curio-widget-ref").count() == 0, (
        "the reader's [!! @season !!] is drawn as a chip that resolves"
    )


def test_run_all_on_a_dataflow_saved_with_a_parameter_node_fails_the_node_that_reads_it(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Run All on the same dataflow ends, as on any dataflow: the node whose
    code reads ``[!! @season !!]`` ends in an error saying that names no
    widget, the node that reads nothing of it ends done, and the Parameter
    node stays its card."""
    _enter(page, app_frontend, current_server, prefix="prm_gone_run", spec=_spec())
    page.wait_for_selector(".react-flow__node", timeout=45000)
    for node_id in (PARAMETER, READER, OTHER):
        _opened_as(page, node_id)

    run_all_and_wait(page, timeout_ms=RUN_ALL_MS)
    status = wait_for_node_settled(page, OTHER, node_type=PYTHON_TYPE, timeout_ms=60000)
    assert status == "done", f"{OTHER} ended {status!r}: {read_node_error_text(node_locator(page, OTHER))}"
    status = wait_for_node_settled(page, READER, node_type=PYTHON_TYPE, timeout_ms=60000)
    said = read_node_error_text(node_locator(page, READER)) or ""
    assert status == "error" and REFUSAL in said, (
        f"the node reading [!! @season !!] ended {status!r}, saying {said!r}, not {REFUSAL!r}"
    )
    assert _opened_as(page, PARAMETER) == "removed type"
