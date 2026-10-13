"""Playwright E2E: a dataflow saved before inputs were named ``input_k``.

A node's code reads the edge on input circle k as ``input_k``, and its chips
are ``[!! input_0 !!]``. ``arg`` and ``input``, the names a node's whole input
once had, and chips spelled ``[!! input 0 !!]`` are refused, with no alias.

So a dataflow saved the old way, opened and run, says on each old node what to
write instead, naming ``input_0``. The claims, each read off the page:

  * a Python node that reads ``arg`` fails, and says ``arg`` is gone and
    ``input_0`` is its input;
  * a node holding the chip ``[!! input 0 !!]`` fails, and names
    ``[!! input_0 !!]``;
  * a JavaScript node that reads ``arg`` fails the same way;
  * a node written the new way, beside them, runs.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_old_input_names_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    read_node_error_text,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "old-names-loader"
OLD_ARG_ID = "old-names-arg"
OLD_CHIP_ID = "old-names-chip"
OLD_JS_ID = "old-names-js"
NEW_ID = "old-names-new"

LOADER_CODE = "import pandas as pd\nreturn pd.DataFrame({'n': [1, 2, 3]})\n"
OLD_ARG_CODE = "return int(arg['n'].sum())\n"
OLD_CHIP_CODE = "return int([!! input 0 !!]['n'].sum())\n"
OLD_JS_CODE = "return arg.length;"
NEW_CODE = "return int(input_0['n'].sum())\n"

COMPUTE = "curio.builtin/computation-analysis"
JAVASCRIPT = "curio.builtin/js-computation"


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _edge(target: str) -> dict:
    return {
        "id": f"reactflow__edge-{LOADER_ID}out-{target}in",
        "source": LOADER_ID, "sourceHandle": "out", "target": target, "targetHandle": "in",
    }


def _spec() -> dict:
    return {"dataflow": {
        "name": "Old input names", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Old input names",
        "nodes": [
            _node(LOADER_ID, "curio.builtin/data-loading", 0, 300, LOADER_CODE),
            _node(OLD_ARG_ID, COMPUTE, 645, 0, OLD_ARG_CODE),
            _node(OLD_CHIP_ID, COMPUTE, 645, 420, OLD_CHIP_CODE),
            _node(OLD_JS_ID, JAVASCRIPT, 1290, 0, OLD_JS_CODE),
            _node(NEW_ID, COMPUTE, 1290, 420, NEW_CODE),
        ],
        "edges": [_edge(OLD_ARG_ID), _edge(OLD_CHIP_ID), _edge(OLD_JS_ID), _edge(NEW_ID)],
    }}


def test_an_old_dataflow_says_what_each_old_input_name_is_now(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    page.emulate_media(reduced_motion="reduce")
    # Opened as the stub user's saved dataflow: on a stack with user accounts
    # its owner runs it on the server, and on the isolated stack the shared
    # guest opens it read-only and the run stays in the page, so both ways a
    # node's code is resolved and run are covered.
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Old Input Names",
        username="old_input_names",
        project_name="Old input names",
        project_spec=_spec(),
    )
    for node_id in (LOADER_ID, OLD_ARG_ID, OLD_CHIP_ID, OLD_JS_ID, NEW_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    run_all_and_wait(page, timeout_ms=180000)

    assert wait_for_node_settled(page, LOADER_ID, node_type="DATA_LOADING") == "done"
    assert wait_for_node_settled(page, NEW_ID, node_type="COMPUTATION_ANALYSIS") == "done"

    said = {}
    for node_id, node_type in (
        (OLD_ARG_ID, "COMPUTATION_ANALYSIS"),
        (OLD_CHIP_ID, "COMPUTATION_ANALYSIS"),
        (OLD_JS_ID, "JS_COMPUTATION"),
    ):
        status = wait_for_node_settled(page, node_id, node_type=node_type)
        said[node_id] = read_node_error_text(node_locator(page, node_id)) or ""
        assert status == "error", f"{node_id} ended {status!r}, showing {said[node_id]!r}"

    for node_id in (OLD_ARG_ID, OLD_JS_ID):
        assert "reads `arg`, which Curio no longer defines" in said[node_id], said[node_id]
        assert "input_0" in said[node_id], said[node_id]
    assert "[!! input 0 !!] names an input the old way" in said[OLD_CHIP_ID], said[OLD_CHIP_ID]
    assert "Write [!! input_0 !!]" in said[OLD_CHIP_ID], said[OLD_CHIP_ID]
