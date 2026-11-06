"""Playwright E2E: the rows a widget rule keeps reach a Python node and a Simple View.

``docs/examples/dataflows/filter-rows-with-widgets.json``: a Data Loading node
makes six rows of buildings; a Python Computation keeps those its three
widgets let through (the column, the comparison and the threshold: height
above 15); a Simple View shows the rows it kept, and a second Python
Computation prints them. Alpha, Bravo, Charlie and Foxtrot pass; Delta and
Echo do not.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_filter_rows_with_widgets_e2e.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    dismiss_toasts,
    node_execution_timeout_ms,
    node_locator,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = os.path.join(REPO_ROOT, "docs", "examples", "dataflows", "filter-rows-with-widgets.json")

FILTER = "filter-rows"
VIEW = "show-table"
PRINT = "print-rows"

#: The rows whose height is above 15, the widgets' rule, and the rows it drops.
KEPT = ("Alpha", "Bravo", "Charlie", "Foxtrot")
DROPPED = ("Delta", "Echo")


def _spec() -> dict:
    with open(DATAFLOW, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture()
def filter_canvas(app_frontend: "FrontendPage", current_server, page):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Filter Rows",
        username=f"frw_{uuid.uuid4().hex[:10]}",
        project_name="Filter rows with widgets",
        project_spec=_spec(),
    )
    require_owner_view(page)
    node_locator(page, PRINT).wait_for(state="visible", timeout=45000)
    dismiss_toasts(page)
    return page


def _wait_for_output(page, node_id: str, node_type: str, needle: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(node_type),
        )
    except Exception:
        raise AssertionError(
            f"{node_id} never printed {needle!r}; its output reads {read_node_output_text(page, node_id)!r}"
        ) from None


def test_the_rows_the_widgets_keep_reach_python_and_the_simple_view(filter_canvas):
    page = filter_canvas

    play_node(page, PRINT)
    wait_for_node_done(page, FILTER, node_type="COMPUTATION_ANALYSIS", timeout_ms=120000)
    _wait_for_output(page, PRINT, "COMPUTATION_ANALYSIS", KEPT[-1])
    wait_for_node_done(page, PRINT, node_type="COMPUTATION_ANALYSIS", timeout_ms=120000)
    printed = read_node_output_text(page, PRINT)
    for name in KEPT:
        assert name in printed, f"{name} passes height > 15 but was not printed: {printed!r}"
    for name in DROPPED:
        assert name not in printed, f"{name} fails height > 15 but was printed: {printed!r}"

    wait_for_node_settled(page, VIEW, node_type="VIS_SIMPLE", timeout_ms=120000)
    view = node_locator(page, VIEW)
    # A Simple View says done when its input arrives, before its table draws.
    view.get_by_text(KEPT[0], exact=True).first.wait_for(state="visible", timeout=30000)
    rows = view.locator("tbody tr")
    assert rows.count() == len(KEPT), f"the Simple View shows {rows.count()} rows: {view.inner_text()!r}"
    shown = view.inner_text()
    for name in KEPT:
        assert name in shown, f"the Simple View does not show {name}: {shown!r}"
    for name in DROPPED:
        assert name not in shown, f"the Simple View shows {name}, which fails height > 15: {shown!r}"
