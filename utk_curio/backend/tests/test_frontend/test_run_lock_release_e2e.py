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

import copy
import re

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    dismiss_toasts,
    held_node_executions,
    hold_node_execution,
    play_node,
    read_node_output_text,
    release_node_execution,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_button,
    stub_login_and_enter_workflow,
    wait_for_held_node_execution,
    wait_for_node_done,
    wait_for_run_all_to_end,
    watch_run_all,
)
from .walkthroughs import load_example_spec

# Autark node, plus a data-loading node that is neither upstream nor downstream
# of it - so "another independent node" means what the report means.
EXAMPLE = "09-heterogeneous-data-linked-views.json"
INDEPENDENT_PREFIX = "4b7c2234"
#: The Python node that hands example 09's map its census tracts.
MAP_FEEDER_PREFIX = "3cc268ee"

NOTIFICATIONS = "Notifications"
RUN_IN_PROGRESS = re.compile("already in progress", re.I)

#: What this test gives a run on the server, from the data loads' release.
RUN_BUDGET_MS = 180000

#: How long the node before the map takes in the slow case: past the minute
#: the map's refusal once had from the release, as example 09's UTCI over the
#: Milan raster took on a loaded utk-desktop-01 (106 s, run 42334009628).
SLOW_FEEDER_S = 61

#: The slow case's Python node: the census tracts, each with the ``mean`` the
#: map colours by, handed on after ``SLOW_FEEDER_S`` seconds.
SLOW_FEEDER_CODE = f"""import time

gdf = input_0.copy()
time.sleep({SLOW_FEEDER_S})
gdf["mean"] = 0.0
return gdf
"""


def _open_without_webgpu(page, app_frontend, current_server, spec: dict, *, username: str) -> dict:
    """*spec* open on a canvas whose browser has no WebGPU, for a signed-in
    owner: a Run All runs on the server. Returns the ``stub-login`` session."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")

    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Run lock",
        username=username,
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
    return session


def _autark_id(spec: dict) -> str:
    return next(n["id"] for n in spec["dataflow"]["nodes"] if n["type"] == "curio.builtin/autk-grammar")


@pytest.fixture
def dataflow_without_webgpu(app_frontend, current_server, page):
    """Example 09 open on a canvas whose browser has no WebGPU."""
    spec = load_example_spec(EXAMPLE)
    session = _open_without_webgpu(page, app_frontend, current_server, spec, username="runlock271")
    nodes = spec["dataflow"]["nodes"]
    independent_id = next(n["id"] for n in nodes if n["id"].startswith(INDEPENDENT_PREFIX))
    return {
        "autark": _autark_id(spec),
        "independent": independent_id,
        "backend": current_server,
        "token": session["token"],
        "project": session["project"]["id"],
    }


@pytest.fixture
def map_after_a_slow_node_without_webgpu(app_frontend, current_server, page):
    """Example 09's map fed by its census load through a Python node that
    takes ``SLOW_FEEDER_S`` seconds, open on a canvas whose browser has no
    WebGPU: the nodes before the map take longer than a minute, and nothing
    else in the dataflow does."""
    spec = load_example_spec(EXAMPLE)
    flow = spec["dataflow"]
    census = next(n for n in flow["nodes"] if n["id"].startswith(INDEPENDENT_PREFIX))
    feeder = copy.deepcopy(next(n for n in flow["nodes"] if n["id"].startswith(MAP_FEEDER_PREFIX)))
    feeder["content"] = SLOW_FEEDER_CODE
    autark_id = _autark_id(spec)
    autark = next(n for n in flow["nodes"] if n["id"] == autark_id)
    flow["nodes"] = [census, feeder, autark]
    flow["edges"] = [
        {
            "id": f"reactflow__edge-{census['id']}out-{feeder['id']}in",
            "source": census["id"], "target": feeder["id"],
        },
        next(e for e in flow["edges"] if e["source"] == feeder["id"] and e["target"] == autark_id),
    ]
    session = _open_without_webgpu(page, app_frontend, current_server, spec, username="runlock271slow")
    return {
        "autark": autark_id,
        "backend": current_server,
        "token": session["token"],
        "project": session["project"]["id"],
    }


def _run_all_until_the_autark_node_refuses(page, dataflow: dict) -> None:
    """Steps 2 and 3: Run All is in flight, and the Autark node refuses and
    says why."""
    # One button in two states (Run All / Cancel run), so the locator matches
    # either name and the assertions read the state off data-run-active. A
    # locator written for one name stops matching the moment the run changes
    # state, and a click on it then waits out its whole budget.
    run_all = run_all_button(page)

    # Step 2: run everything. The node executions are held first: the first
    # level is data-loading nodes (three in example 09), one execution each,
    # and the only thing keeping the button on "Cancel run" is that those have
    # not answered yet. Held, the in-flight state is a fact; unheld, it is a
    # race with a loaded runner.
    expect(run_all).to_be_visible(timeout=30000)
    hold_node_execution(page)
    watch_run_all(page)
    run_all.click()
    # The button IS the run's state. A silent no-op here is indistinguishable
    # from a dead control, which is how this was reported in the first place.
    expect(run_all).to_have_attribute("data-run-active", "true", timeout=30000)
    expect(run_all).to_have_attribute("aria-label", "Cancel run")
    wait_for_held_node_execution(page)
    release_node_execution(page)

    # Step 3: the Autark node refuses, and says why. Reporting is what releases
    # its level - a node that stays silent is the wedge.
    autark = page.locator(f'.react-flow__node[data-id="{dataflow["autark"]}"]')
    alert = autark.locator('[role="alert"]').first
    expect(alert).to_be_visible(timeout=60000)
    expect(alert).to_contain_text(re.compile("WebGPU", re.I))


def test_a_webgpu_failure_does_not_lock_the_canvas(page, dataflow_without_webgpu):
    independent_id = dataflow_without_webgpu["independent"]
    run_all = run_all_button(page)

    _run_all_until_the_autark_node_refuses(page, dataflow_without_webgpu)

    # The claim of #271: the run ends on its own. Generous, because the level
    # also carries data-loading nodes that fetch real files on a loaded runner.
    wait_for_run_all_to_end(page, timeout_ms=RUN_BUDGET_MS)
    expect(run_all).to_have_attribute("aria-label", "Run all nodes")

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

    # Step 4b: Run All again, cancel it, and leave the canvas as we found it.
    #
    # This is the one place a real browser checks that the button's second state
    # does what it says - the unit tests assert cancelRun is CALLED, not that a
    # run stops. Clicking it needs a run that is still in flight, so the level's
    # node executions are held across the click rather than hoped to still be
    # outstanding. The assertion afterwards is the one the old version could not
    # make: the button came back WHILE the requests are still held, so the run
    # was cancelled rather than merely finished.
    dismiss_toasts(page)
    hold_node_execution(page)
    try:
        watch_run_all(page)
        run_all.click()
        expect(run_all).to_have_attribute(
            "data-run-active", "true", timeout=30000)
        wait_for_held_node_execution(page)

        run_all.click()  # the same button, now cancelling
        expect(run_all).to_have_attribute("aria-label", "Run all nodes",
                                          timeout=30000)
        expect(run_all).not_to_have_attribute("data-run-active", "true")
        assert held_node_executions(page) > 0, (
            "the run ended before the cancel click, so this asserted nothing; "
            "the held node executions were released too early"
        )
    finally:
        release_node_execution(page)


def test_a_webgpu_failure_is_told_however_long_the_nodes_before_it_take(
    page, map_after_a_slow_node_without_webgpu,
):
    """The map's refusal does not depend on how long the nodes before it take:
    here a Python node takes over a minute, as example 09's UTCI over the Milan
    raster did on a loaded runner, and the map still says WebGPU is missing,
    and the run still ends on its own."""
    _run_all_until_the_autark_node_refuses(page, map_after_a_slow_node_without_webgpu)
    wait_for_run_all_to_end(page, timeout_ms=RUN_BUDGET_MS)
    expect(run_all_button(page)).to_have_attribute("aria-label", "Run all nodes")
