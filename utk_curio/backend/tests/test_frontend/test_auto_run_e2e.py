"""Playwright E2E: "Run stale nodes automatically" (#845).

A dataflow holds a Parameter node with a slider, ``factor``; a Python node that
reads it; a node below that one; and a node apart from both. This drives the
whole path in a browser, on the server runs a signed-in canvas makes:

1. Run All once.
2. With the toggle off, as in a new dataflow, a slider move runs nothing: the
   nodes keep their outputs until the next Run All, as before. The View menu
   offers the toggle, off.
3. Turn it on. A slider move runs the node that reads the parameter and the
   node below it, on their own, as one run on the server; the node apart does
   not run.
4. Code typed into a node runs nothing.
5. Save and reopen: the toggle is still on. Turn it off: a slider move runs
   nothing again.

Frames for the owner: the View menu, the dataflow after a slider move with the
toggle off, and after one with it on.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_auto_run_e2e.py -v
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    frame_node,
    node_execution_timeout_ms,
    node_locator,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    save_dataflow,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

PYTHON = "curio.builtin/computation-analysis"
PARAMETER = "curio.builtin/parameter"
FRAMES = "auto-run-845"
TOGGLE = "Run stale nodes automatically"

PARAM_ID = "factor-parameter"
READS_ID = "reads-factor"
BELOW_ID = "below-reader"
APART_ID = "apart"


def _spec() -> dict:
    slider = {"name": "factor", "type": "slider", "label": "Factor", "default": 2,
              "options": {"min": 0, "max": 10, "step": 1}}
    nodes = [
        {"id": PARAM_ID, "type": PARAMETER, "x": 80, "y": 80, "content": "", "title": "Factor",
         "metadata": {"widgets": [slider]}},
        {"id": READS_ID, "type": PYTHON, "x": 700, "y": 80,
         "content": "value = [!! @factor !!]\nprint(f'<<A {value * 10}>>')\nreturn value * 10\n"},
        {"id": BELOW_ID, "type": PYTHON, "x": 1320, "y": 80,
         "content": "print(f'<<B {input_0 + 1}>>')\nreturn input_0 + 1\n"},
        {"id": APART_ID, "type": PYTHON, "x": 700, "y": 520,
         "content": "print('<<C ran>>')\nreturn 1\n"},
    ]
    edges = [{"id": f"{READS_ID}-{BELOW_ID}", "source": READS_ID, "target": BELOW_ID,
              "sourceHandle": "out", "targetHandle": "in_0"}]
    return {
        "name": "Auto-run",
        "dataflow": {"name": "Auto-run", "nodes": nodes, "edges": edges,
                     "task": "", "timestamp": 0, "provenance_id": "Auto-run"},
    }


def _runs(backend: str, token: str, project_id: str) -> list[dict]:
    return api_json(f"{backend}/api/projects/{project_id}/runs?limit=50", token)["runs"]


def _wait_for_output(page, node_id: str, needle: str, what: str) -> None:
    try:
        page.wait_for_function(
            """([nodeId, needle]) => {
                const box = document.querySelector(
                    `.react-flow__node[data-id="${nodeId}"] [data-curio-node-output]`);
                return !!box && (box.textContent || "").includes(needle);
            }""",
            arg=[node_id, needle],
            timeout=node_execution_timeout_ms(PYTHON),
        )
    except Exception:
        raise AssertionError(
            f"{what}: the node never printed {needle!r}; its output reads "
            f"{read_node_output_text(page, node_id)!r}"
        ) from None


def _slider(page):
    return node_locator(page, PARAM_ID).locator("[data-parameter-panel]").first.get_by_label("Factor", exact=True)


def _move_slider(page, steps: int) -> None:
    """Move the slider *steps* to the right, one key press a step, as a drag does."""
    frame_node(page, PARAM_ID)
    slider = _slider(page)
    slider.focus()
    for _ in range(steps):
        page.keyboard.press("ArrowRight")
    slider.blur()


def _view_menu(page):
    return page.get_by_role("button", name="View menu", exact=True)


def _toggle(page):
    return page.get_by_role("button", name=TOGGLE, exact=True)


def _set_auto_run(page, on: bool) -> None:
    _view_menu(page).click()
    row = _toggle(page)
    row.wait_for(state="visible", timeout=10000)
    if (row.get_attribute("aria-pressed") == "true") != on:
        row.click()
    if _toggle(page).count():
        page.keyboard.press("Escape")
    expect(_toggle(page)).to_have_count(0)


def _frame(page, test_name: str) -> None:
    """The whole dataflow, with the mouse on empty canvas: the last click (a menu
    row, Run All) otherwise leaves a node's or a button's hover look in the frame."""
    page.mouse.move(1260, 440)
    save_workflow_test_screenshot(page, FRAMES, test_name=test_name, sweep_toasts=True)


def _no_new_run(backend: str, token: str, project_id: str, before: int, what: str) -> None:
    # Longer than a change takes to settle and a run takes to start.
    time.sleep(3)
    runs = _runs(backend, token, project_id)
    assert len(runs) == before, f"{what}: a run started on its own: {runs[0]}"


def test_a_slider_move_runs_the_stale_nodes_only_when_auto_run_is_on(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Auto Run",
        username="auto_run_e2e",
        project_name="Auto-run",
        project_spec=_spec(),
    )
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    token, project_id = session["token"], session["project"]["id"]
    node_locator(page, APART_ID).wait_for(state="visible", timeout=45000)

    # 1. Run All once.
    run_all_and_wait(page)
    _wait_for_output(page, BELOW_ID, "<<B 21>>", "After Run All")
    _wait_for_output(page, APART_ID, "<<C ran>>", "After Run All")

    # 2. A new dataflow has auto-run off, so a slider move runs nothing.
    runs_before = len(_runs(current_server, token, project_id))
    _move_slider(page, 3)
    _no_new_run(current_server, token, project_id, runs_before, "With auto-run off")
    assert "<<B 21>>" in read_node_output_text(page, BELOW_ID)
    _frame(page, "slider-moved")

    # The View menu offers the toggle, off.
    _view_menu(page).click()
    save_workflow_test_screenshot(
        page, FRAMES, test_name="view-menu",
        clip_selector='button[aria-label="View menu"] + div', fit_reactflow=False,
    )
    assert _toggle(page).get_attribute("aria-pressed") == "false", "auto-run is on in a new dataflow"
    page.keyboard.press("Escape")

    # 3. On, a slider move runs the node that reads it and the node below, once.
    _set_auto_run(page, True)
    runs_before = len(_runs(current_server, token, project_id))
    _move_slider(page, 2)
    _wait_for_output(page, READS_ID, "<<A 70>>", "With auto-run on, after the slider moved to 7")
    _wait_for_output(page, BELOW_ID, "<<B 71>>", "With auto-run on, below the node that reads the slider")
    time.sleep(2)
    runs = _runs(current_server, token, project_id)
    assert len(runs) == runs_before + 1, f"the slider move started {len(runs) - runs_before} runs: {runs[:3]}"
    auto = api_json(f"{current_server}/api/runs/{runs[0]['id']}", token)
    assert auto["trigger"] == "auto", auto
    assert sorted(s["nodeId"] for s in auto["steps"]) == sorted([READS_ID, BELOW_ID]), auto["steps"]
    _frame(page, "slider-auto-run")

    # 4. Code typed into a node runs nothing.
    runs_before = len(runs)
    set_node_code(page, APART_ID, "print('<<C edited>>')\nreturn 2\n")
    _no_new_run(current_server, token, project_id, runs_before, "After typing code")

    # 5. The toggle is saved with the dataflow...
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", token)["spec"]
    assert saved["dataflow"].get("autoRun") is True, saved["dataflow"].get("autoRun")
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, PARAM_ID).wait_for(state="visible", timeout=45000)
    _view_menu(page).click()
    expect(_toggle(page)).to_have_attribute("aria-pressed", "true", timeout=15000)
    save_workflow_test_screenshot(
        page, FRAMES, test_name="view-menu-on",
        clip_selector='button[aria-label="View menu"] + div', fit_reactflow=False,
    )
    page.keyboard.press("Escape")

    # ...and once it is off, a slider move runs nothing again.
    _set_auto_run(page, False)
    runs_before = len(_runs(current_server, token, project_id))
    _move_slider(page, 1)
    _no_new_run(current_server, token, project_id, runs_before, "After turning auto-run off")
