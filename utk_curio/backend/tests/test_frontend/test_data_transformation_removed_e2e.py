"""Playwright E2E: the Data Transformation node is gone (komar41's #1327).

* The Built-in palette has no Data Transformation tile; Python Computation,
  which runs the same code, is there.
* A dataflow saved with a Data Transformation node, with or without ``@1``,
  opens with that node as a type no installed package provides. Builtin is
  installed and only dropped the type, so the node gets the "Removed node
  type" card, titled with the type, which names Builtin and offers no Install
  button. Nothing aliases or migrates it, and every other node opens as it
  was saved.
* Run All on it ends, as on any dataflow: a Python Computation node holding
  the same code ends done, and the Data Transformation nodes stay their cards.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_data_transformation_removed_e2e.py -v
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_compare_scenarios_removed_e2e import _node, _opened_as
from .utils import (
    dismiss_toasts,
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

#: The types a saved Data Transformation node carries: a node made in code
#: wrote the first, one dropped from the palette the second.
GONE_TYPES = ("curio.builtin/data-transformation", "curio.builtin/data-transformation@1")
PYTHON_TYPE = "curio.builtin/python-computation"
PROJECT = "Data Transformation removed e2e"

GONE = "dt-gone-unversioned"
GONE_V1 = "dt-gone-versioned"
KEPT = "dt-gone-python"
#: How long Run All may take on this small dataflow: well under the ten
#: minutes a level waits for a node that never reports before it moves on.
RUN_ALL_MS = 180000

#: The code each node holds: a Data Transformation's, and the same in Python.
CODE = "import pandas as pd\nreturn pd.DataFrame({'a': [1, 2, 3]})\n"


def _spec() -> dict:
    return {
        "dataflow": {
            "name": PROJECT,
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [
                _node(GONE, GONE_TYPES[0], CODE, 0),
                _node(GONE_V1, GONE_TYPES[1], CODE, 0, 600),
                _node(KEPT, PYTHON_TYPE, CODE, 700),
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
        name="Transformation Gone",
        username=f"{prefix}_{uuid.uuid4().hex[:8]}",
        project_name=PROJECT,
        project_spec=spec,
    )
    require_owner_view(page)
    dismiss_toasts(page)


def test_the_built_in_palette_has_no_data_transformation_tile(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="dt_gone_palette")
    panel = open_tools_palette(page, "builtin")
    # The registry has answered once the Map Editor node's tile is there.
    expect(panel.locator("#tile-edit-features")).to_be_visible(timeout=30000)
    tiles = panel.locator('[id^="tile-"]').evaluate_all("(tiles) => tiles.map((tile) => tile.id)")
    assert "tile-data-transformation" not in tiles, f"the Built-in palette holds Data Transformation: {tiles}"
    assert "tile-python-computation" in tiles, f"the Built-in palette lacks Python Computation: {tiles}"
    expect(panel.get_by_label("Data Transformation", exact=True)).to_have_count(0)


def test_a_dataflow_saved_with_a_data_transformation_node_opens_with_it_as_a_removed_type(
    app_frontend: "FrontendPage", current_server: str, page,
):
    _enter(page, app_frontend, current_server, prefix="dt_gone_saved", spec=_spec())
    page.wait_for_selector(".react-flow__node", timeout=45000)

    opened = {node_id: _opened_as(page, node_id) for node_id in (GONE, GONE_V1, KEPT)}
    assert opened == {GONE: "removed type", GONE_V1: "removed type", KEPT: "its own body"}, (
        f"a saved Data Transformation node should open as a type its installed package no longer has: {opened}"
    )

    for node_id, node_type in ((GONE, GONE_TYPES[0]), (GONE_V1, GONE_TYPES[1])):
        card = node_locator(page, node_id).get_by_test_id("removed-node-type")
        expect(card).to_have_attribute("data-tooltip", f"No installed package provides {node_type}")
        expect(card).to_contain_text("Removed node type")
        expect(card).to_contain_text(f"This dataflow asks for {node_type}, which Builtin no longer has.")
        expect(card.get_by_role("button")).to_have_count(0)
        expect(node_locator(page, node_id).locator(".monaco-editor")).to_have_count(0)


def test_run_all_on_a_dataflow_saved_with_a_data_transformation_node_runs_the_python_node(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """Run All on the same dataflow ends, as on any dataflow: the Python
    Computation node holding the same code ends done, and the Data
    Transformation nodes stay their cards."""
    _enter(page, app_frontend, current_server, prefix="dt_gone_run", spec=_spec())
    page.wait_for_selector(".react-flow__node", timeout=45000)
    for node_id in (GONE, GONE_V1, KEPT):
        _opened_as(page, node_id)

    run_all_and_wait(page, timeout_ms=RUN_ALL_MS)
    status = wait_for_node_settled(page, KEPT, node_type=PYTHON_TYPE, timeout_ms=60000)
    assert status == "done", f"{KEPT} ended {status!r}: {read_node_error_text(node_locator(page, KEPT))}"
    assert (_opened_as(page, GONE), _opened_as(page, GONE_V1)) == ("removed type", "removed type")
