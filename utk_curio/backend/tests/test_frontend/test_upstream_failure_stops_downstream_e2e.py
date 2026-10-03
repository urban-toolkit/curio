"""Playwright E2E for #603: a failed node stops the node it feeds.

The report: a Python Computation node reading ``arg['sp_units']`` failed with
"This node received no input but its code references `arg`", although its
input was wired. The Data Loading node feeding it had failed a moment earlier
in the same Run All. The runner went on to the next level anyway, so the
downstream node was sent to the sandbox with nothing, and its message pointed
at the wiring rather than at the node that actually failed. And the failed
node's own strip read "Traceback (most recent call last):", so the reason was
behind "more" on both nodes.

The same shape here, with a plain ``raise`` upstream. The claims, each read
off the page:

  * the downstream node is never sent to the sandbox (the run's
    ``/processPythonCode`` requests name only the upstream node);
  * it says which node feeding it failed, and nothing about missing input;
  * the upstream's collapsed strip shows its exception line.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_upstream_failure_stops_downstream_e2e.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    node_locator,
    read_node_error_text,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    upload_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

LOADER_ID = "upstream-failure-loader"
COMPUTE_ID = "upstream-failure-compute"

LOADER_CODE = 'raise RuntimeError("upstream boom")\n'
# Reads its input the way the reporter's node did.
COMPUTE_CODE = "sp = arg['sp_units']\nreturn sp\n"


def _node(node_id: str, node_type: str, x: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": 150, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _spec() -> dict:
    return {"dataflow": {
        "name": "Upstream failure", "task": "", "timestamp": 1789193389280,
        "provenance_id": "Upstream failure",
        "nodes": [
            _node(LOADER_ID, "curio.builtin/data-loading", 0, LOADER_CODE),
            _node(COMPUTE_ID, "curio.builtin/computation-analysis", 645, COMPUTE_CODE),
        ],
        "edges": [{
            "id": f"reactflow__edge-{LOADER_ID}out-{COMPUTE_ID}in",
            "source": LOADER_ID,
            "target": COMPUTE_ID,
        }],
    }}


def test_a_failed_node_stops_the_node_it_feeds(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    page.emulate_media(reduced_motion="reduce")
    # Loaded through the File menu, the way the workflow suite loads its
    # dataflows, so the test runs the same on a stack with user accounts and on
    # the isolated stack, which has none.
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Upstream Failure",
        username="upstream_failure_603",
        project_name="Upstream failure",
    )
    spec_file = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8",
    )
    json.dump(_spec(), spec_file)
    spec_file.close()
    try:
        upload_workflow(page, app_frontend, spec_file.name, 2)
    finally:
        os.unlink(spec_file.name)
    for node_id in (LOADER_ID, COMPUTE_ID):
        node_locator(page, node_id).wait_for(state="visible", timeout=45000)

    # Every node execution leaves the browser as one POST naming its node.
    executed: list[str] = []

    def _record(request) -> None:
        if request.method != "POST" or not request.url.endswith("/processPythonCode"):
            return
        try:
            body = json.loads(request.post_data or "{}")
        except ValueError:
            body = {}
        executed.append(str(body.get("nodeId")))

    page.on("request", _record)

    run_all_and_wait(page, timeout_ms=180000)

    assert wait_for_node_settled(page, LOADER_ID, node_type="DATA_LOADING") == "error"
    assert wait_for_node_settled(
        page, COMPUTE_ID, node_type="COMPUTATION_ANALYSIS"
    ) == "error"
    reason = read_node_error_text(node_locator(page, COMPUTE_ID)) or ""

    # 1. Never sent to the sandbox.
    assert executed == [LOADER_ID], (
        f"Run All executed {executed}; the node fed by the failed loader must "
        f"not run at all. It showed: {reason!r}"
    )

    # 2. It names the node that failed, and does not blame its wiring.
    assert "The node feeding this one" in reason, reason
    assert "Data Loading" in reason, reason
    assert "received no input" not in reason, reason

    # 3. The failed node's strip leads with its exception, not the header of
    #    the traceback.
    strip = page.get_by_test_id(f"node-outcome-{LOADER_ID}")
    expect(strip).to_contain_text("RuntimeError: upstream boom", timeout=15000)
    expect(strip).not_to_contain_text("Traceback (most recent call last)")
