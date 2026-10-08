"""A run goes on after every page is closed, and a reopened canvas shows it.

Run All saves the dataflow and starts a run the server executes. These tests
hold that run, close every page, and only then let it go: whatever the canvas
shows afterwards, the server made with no page open.

The dataflow has two Python nodes. The first saves its output, so the run
records it in the dataflow as a save would. The second does not, so only the
run's own steps can bring its output back: when it shows on a reopened canvas,
it came from the run.
"""
from __future__ import annotations

import time

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    hold_node_execution,
    hold_server_runs,
    node_locator,
    read_node_output_text,
    release_node_execution,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_button,
    stub_login_and_enter_workflow,
    wait_for_held_node_execution,
    wait_for_node_done,
    watch_run_all,
)

PYTHON = "curio.builtin/computation-analysis"
SAVED = "kept-output"
UNSAVED = "unsaved-output"


def _spec() -> dict:
    nodes = [
        {"id": SAVED, "type": PYTHON, "x": 200, "y": 300, "saveOutputDataset": True,
         "content": "import pandas as pd\nreturn pd.DataFrame({'n': [1, 2, 3]})"},
        {"id": UNSAVED, "type": PYTHON, "x": 900, "y": 300, "saveOutputDataset": False,
         "content": "return input_0.assign(twice=input_0['n'] * 2)"},
    ]
    edges = [{"id": f"{SAVED}-{UNSAVED}", "source": SAVED, "target": UNSAVED}]
    return {
        "name": "Server run",
        "dataflow": {"name": "Server run", "nodes": nodes, "edges": edges,
                     "task": "", "timestamp": 0, "provenance_id": "Server run"},
    }


@pytest.fixture
def held_run(app_frontend, current_server, page, request):
    """The dataflow open, its Run All pressed, and the run held at its first node."""
    require_project_page()
    require_user_auth()
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Server run",
        username=f"serverrun_{request.node.name[-12:].lower()}",
        project_name="Server run",
        project_spec=_spec(),
    )
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    node_locator(page, UNSAVED).wait_for(state="visible", timeout=45000)

    hold_node_execution(page)
    try:
        watch_run_all(page)
        run_all_button(page).click()
        expect(run_all_button(page)).to_have_attribute("data-run-active", "true", timeout=30000)
        wait_for_held_node_execution(page)
        yield {
            "token": session["token"],
            "project": session["project"]["id"],
            "context": page.context,
        }
    finally:
        # A hold left standing would stop every later run on this backend.
        hold_server_runs(current_server, False)


def _close_every_page(context) -> None:
    for open_page in list(context.pages):
        open_page.close()
    assert not context.pages


def _latest_run(backend: str, token: str, project_id: str) -> dict:
    runs = api_json(f"{backend}/api/projects/{project_id}/runs?limit=1", token)["runs"]
    assert runs, "Run All started no run on the server"
    return api_json(f"{backend}/api/runs/{runs[0]['id']}", token)


def _wait_for_run_to_end(backend: str, token: str, project_id: str, *, timeout_s: float = 180) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        run = _latest_run(backend, token, project_id)
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"the run did not end within {timeout_s} s: {run['status']}"
        time.sleep(0.5)


def _status(page, node_id: str) -> str:
    return node_locator(page, node_id).locator("[data-curio-node-status]").first.get_attribute(
        "data-curio-node-status"
    ) or "idle"


def test_a_run_finishes_with_no_page_open_and_the_canvas_shows_it(
    app_frontend, current_server, held_run,
):
    token, project_id = held_run["token"], held_run["project"]
    _close_every_page(held_run["context"])

    # Nothing has run yet, and no page is left to run anything.
    going = _latest_run(current_server, token, project_id)
    assert going["status"] == "running", going
    assert going["wholeDataflow"] is True
    assert {s["nodeId"]: s["status"] for s in going["steps"]}[UNSAVED] == "pending", going["steps"]

    assert hold_server_runs(current_server, False) >= 1
    run = _wait_for_run_to_end(current_server, token, project_id)
    assert run["status"] == "succeeded", run
    steps = {s["nodeId"]: s for s in run["steps"]}
    assert steps[SAVED]["status"] == "ok" and steps[UNSAVED]["status"] == "ok", run["steps"]
    unsaved_output = steps[UNSAVED]["outputPath"]
    assert unsaved_output, steps[UNSAVED]

    # The run recorded the output that is saved, and only that one.
    saved = api_json(f"{current_server}/api/projects/{project_id}", token)
    assert {o["node_id"] for o in saved["outputs"]} == {SAVED}, saved["outputs"]

    reopened = held_run["context"].new_page()
    reopened.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    _wait_for_reactflow_ready(reopened)
    wait_for_node_done(reopened, SAVED, node_type="PYTHON", timeout_ms=45000)
    wait_for_node_done(reopened, UNSAVED, node_type="PYTHON", timeout_ms=45000)
    # Only the run's own step knows this output: the dataflow does not hold it.
    assert unsaved_output in read_node_output_text(reopened, UNSAVED)
    reopened.close()


def test_a_canvas_opened_while_the_run_goes_follows_it_to_the_end(
    app_frontend, current_server, held_run,
):
    token, project_id = held_run["token"], held_run["project"]
    _close_every_page(held_run["context"])

    reopened = held_run["context"].new_page()
    reopened.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    _wait_for_reactflow_ready(reopened)
    node_locator(reopened, UNSAVED).wait_for(state="visible", timeout=45000)

    # The held node runs, and the button says a run is going, on a page that
    # did not start it.
    reopened.wait_for_function(
        """(nodeId) => document.querySelector(
            `.react-flow__node[data-id="${nodeId}"] [data-curio-node-status]`
        )?.getAttribute('data-curio-node-status') === 'running'""",
        arg=SAVED,
        timeout=30000,
    )
    expect(run_all_button(reopened)).to_have_attribute("data-run-active", "true", timeout=30000)
    assert _status(reopened, UNSAVED) == "idle"

    assert release_node_execution(reopened) >= 1
    wait_for_node_done(reopened, SAVED, node_type="PYTHON", timeout_ms=90000)
    wait_for_node_done(reopened, UNSAVED, node_type="PYTHON", timeout_ms=90000)
    expect(run_all_button(reopened)).not_to_have_attribute("data-run-active", "true", timeout=30000)

    run = _wait_for_run_to_end(current_server, token, project_id)
    assert run["status"] == "succeeded", run
    unsaved_output = {s["nodeId"]: s for s in run["steps"]}[UNSAVED]["outputPath"]
    assert unsaved_output and unsaved_output in read_node_output_text(reopened, UNSAVED)
    reopened.close()
