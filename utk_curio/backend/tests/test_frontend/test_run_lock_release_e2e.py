"""A failed Autark node releases the runner, and the canvas keeps working (#271).

The report was that a WebGPU failure "permanently locks node execution state
across the dataflow": after it, every play button and Run All click did nothing,
and the only way out was reopening the dataflow. The cause was a run that never
ended - the runner waits for each node in a level to report success or error,
and a node whose WebGPU init threw in a render reported neither, so the guard
that refuses a second run was never released.

#293 fixed that, but nothing held the reported journey itself. The walkthrough
``run-all-survives-a-failed-node`` covers the run ending and a second Run All;
what no test covered is the reporter's step 4 - running **another, unrelated
node** after the failure - which is the half that reads as "the engine is
corrupted" to the person hitting it.

This walks their five steps in order. The assertions are deliberately the
observations they would make: the button says a run is in flight, the node says
what went wrong, the button comes back, an unrelated node runs again, and a
second Run All starts.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    dismiss_toasts,
    play_node,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
    wait_for_node_done,
)
from .walkthroughs import load_example_spec

# Autark node, plus a data-loading node that is neither upstream nor downstream
# of it - so "another independent node" means what the report means.
EXAMPLE = "09-heterogeneous-data-linked-views.json"
INDEPENDENT_PREFIX = "4b7c2234"

NOTIFICATIONS = "Notifications"
RUN_IN_PROGRESS = re.compile("already in progress", re.I)


@pytest.fixture
def dataflow_without_webgpu(app_frontend, current_server, page):
    """Example 09 open on a canvas whose browser has no WebGPU."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")

    spec = load_example_spec(EXAMPLE)
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Run lock",
        username="runlock271",
        project_name="Run lock release",
        project_spec=spec,
    )
    require_owner_view(page)
    _wait_for_reactflow_ready(page)

    # Step 1: "a browser without WebGPU enabled". Removing the property is how
    # the walkthroughs simulate it - the e2e browser is Chromium with a real
    # adapter, and the reporter's Firefox is not something CI can launch.
    page.evaluate(
        "() => Object.defineProperty(navigator, 'gpu',"
        " { configurable: true, value: undefined })"
    )

    nodes = spec["dataflow"]["nodes"]
    autark_id = next(n["id"] for n in nodes if n["type"] == "curio.builtin/autk-grammar")
    independent_id = next(n["id"] for n in nodes if n["id"].startswith(INDEPENDENT_PREFIX))
    return {"autark": autark_id, "independent": independent_id}


def test_a_webgpu_failure_does_not_lock_the_canvas(page, dataflow_without_webgpu):
    autark_id = dataflow_without_webgpu["autark"]
    independent_id = dataflow_without_webgpu["independent"]

    run_all = page.get_by_role("button", name="Run all nodes")
    cancel = page.get_by_role("button", name="Cancel run")

    # Step 2: run everything.
    expect(run_all).to_be_visible(timeout=30000)
    run_all.click()
    # The button IS the run's state. A silent no-op here is indistinguishable
    # from a dead control, which is how this was reported in the first place.
    expect(cancel).to_be_visible(timeout=30000)

    # Step 3: the Autark node refuses, and says why. Reporting is what releases
    # its level - a node that stays silent is the wedge.
    autark = page.locator(f'.react-flow__node[data-id="{autark_id}"]')
    alert = autark.locator('[role="alert"]').first
    expect(alert).to_be_visible(timeout=60000)
    expect(alert).to_contain_text(re.compile("WebGPU", re.I))

    # The claim of #271: the run ends on its own. Generous, because the level
    # also carries data-loading nodes that fetch real files on a loaded runner.
    expect(run_all).to_be_visible(timeout=180000)

    # Step 4a: "attempt to execute other independent nodes". Its badge already
    # says executed from the run above, so the evidence is its output: every
    # execution stamps a new "Saved to file: <timestamp>_<hash>".
    dismiss_toasts(page)
    before = read_node_output_text(page, independent_id)
    play_node(page, independent_id)
    wait_for_node_done(page, independent_id, node_type="DATA_LOADING", timeout_ms=90000)
    after = read_node_output_text(page, independent_id)
    assert after != before, (
        "the independent node did not re-run after the Autark failure; its "
        f"output is still {before!r}"
    )

    toasts = page.get_by_label(NOTIFICATIONS)
    if toasts.count():
        assert not RUN_IN_PROGRESS.search(toasts.inner_text()), (
            "the run was still held: the node play was refused as 'already in "
            "progress'"
        )

    # Step 4b: Run All again, and leave the canvas as we found it.
    dismiss_toasts(page)
    run_all.click()
    expect(cancel).to_be_visible(timeout=30000)
    cancel.click()
    expect(run_all).to_be_visible(timeout=60000)
