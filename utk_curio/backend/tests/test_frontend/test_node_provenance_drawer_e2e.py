"""Playwright E2E: a node's Provenance button opens its runs in the provenance drawer.

A Python node runs twice. Its first run's code is put back from the drawer,
without a run, though it is the code the node loaded with; a third run then
branches from that first run. The drawer lists the line to the newest run, with
the run left behind folded under the run it left from, or draws the same runs
as the Graph, the branch in a column of its own. A click opens a run: what it
read and returned, when it ran and its code. A notebook cell's button opens the
same drawer.

A run's times come from the server's clock, not the browser's, so no fixed date
reaches them. A frame shows them only in the List, on one line the screenshot
masks; the Graph frame shows the runs closed, since an opened box wraps its
times over lines that change with the date and the hour.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_provenance_drawer_e2e.py -v
"""
from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    dismiss_toasts,
    frame_nodes,
    node_locator,
    read_node_code,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    await_provenance_history,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

TEST_NAME = "test_a_nodes_runs_open_in_the_provenance_drawer"

NODE = "runs-node"
NODE_TYPE = "curio.builtin/computation-analysis"
FIRST = "return 1\n"
SECOND = "return 2\n"
THIRD = "return 3\n"
#: The menu bar, which holds the Canvas | Notebook switch.
BAR = "header[data-curio-menu-bar]"
ACTIVE = re.compile(r"\bactive\b")


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Node runs",
            "task": "",
            "description": "",
            "packages": [],
            "datasets": [],
            "nodes": [{
                "id": NODE, "type": NODE_TYPE, "x": 0, "y": 0,
                "in": "DEFAULT", "out": "DEFAULT", "goal": "",
                "metadata": {"keywords": []}, "content": FIRST,
            }],
            "edges": [],
        },
    }


def _run(page, code: str) -> None:
    set_node_code(page, NODE, code)
    run_node_and_wait(page, NODE, node_type="computation-analysis", timeout_ms=120000)


def _open_runs(page):
    node_locator(page, NODE).locator('.nav-link[data-rr-ui-event-key="provenance"]').first.click()
    expect(page.get_by_role("dialog", name="Node provenance")).to_be_visible(timeout=20000)
    await_drawer_at_rest(page)
    return page.locator(PROVENANCE_PANEL)


def _close(page) -> None:
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)


def _shown(panel) -> list[str]:
    return panel.locator("[data-provenance-item]").evaluate_all(
        "els => els.map((el) => el.dataset.provenanceItem)"
    )


def _run_item(panel, run_id: str):
    return panel.locator(f'[data-provenance-item="{run_id}"]')


def _open_run(panel, run_id: str) -> None:
    item = _run_item(panel, run_id)
    head = item.locator("button").first
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    expect(item.get_by_role("button", name="Put this code back in the node", exact=True)).to_be_visible()


def test_a_nodes_runs_open_in_the_provenance_drawer(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Runs Owner",
        username=f"node_runs_{uuid.uuid4().hex[:8]}",
        project_name="Node runs",
        project_spec=_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, [NODE])

    _run(page, FIRST)
    _run(page, SECOND)

    # The two runs, the second in use: the next run would branch from it.
    panel = _open_runs(page)
    expect(panel.get_by_text(re.compile(r"^Runs of \S"))).to_be_visible()
    runs = _shown(panel)
    assert len(runs) == 2, f"two runs should be listed, not {runs}"
    first_run, second_run = runs
    expect(_run_item(panel, second_run)).to_have_attribute("data-provenance-current", "true")

    # Opening the first run shows it and puts nothing back.
    _open_run(panel, first_run)
    first = _run_item(panel, first_run)
    expect(first).to_contain_text("In: none | Out: VALUE")
    expect(first.get_by_text(re.compile(r"^Started "))).to_be_visible()
    expect(first.locator("pre")).to_have_text(re.compile(r"^\s*return 1\s*$"))
    assert read_node_code(page, NODE).strip() == SECOND.strip(), "opening a run changed the node's code"

    # Its button puts that code back, though it is the code the node loaded
    # with, and the next run branches from it. Nothing runs.
    first.get_by_role("button", name="Put this code back in the node", exact=True).click()
    expect(first).to_have_attribute("data-provenance-current", "true")
    expect(_run_item(panel, second_run)).not_to_have_attribute("data-provenance-current", "true")
    assert len(_shown(panel)) == 2, "putting a run's code back ran the node"
    _close(page)
    code_pill = node_locator(page, NODE).locator('.nav-link[data-rr-ui-event-key="code"]').first
    expect(code_pill).to_have_class(ACTIVE)
    assert read_node_code(page, NODE).strip() == FIRST.strip(), (
        "the first run's code did not go back in the node"
    )

    # A third run branches from the first: the List keeps the line to it, with
    # the second run folded under the first.
    _run(page, THIRD)
    panel = _open_runs(page)
    runs = _shown(panel)
    assert len(runs) == 2 and runs[0] == first_run and runs[1] not in (first_run, second_run), (
        f"the List should show the first run then the third, the second folded: {runs}"
    )
    third_run = runs[1]
    fold = panel.get_by_role("button", name=re.compile(r"^1 run on another branch$"))
    expect(fold).to_have_attribute("aria-expanded", "false")
    fold.click()
    assert _shown(panel) == [first_run, second_run, third_run]

    # The Graph: the second run in a column of its own, beside the first.
    panel.get_by_role("button", name="Graph", exact=True).click()
    counts = await_provenance_history(page)
    assert counts["items"] == 3 and counts["links"] == 2 == counts["drawn"], counts
    columns = {run_id: _run_item(panel, run_id).evaluate("el => el.style.gridColumn") for run_id in runs + [second_run]}
    assert columns == {first_run: "1", second_run: "2", third_run: "1"}, columns
    save_workflow_test_screenshot(
        page, "node-provenance-graph", test_name=TEST_NAME, fit_reactflow=False, clip_selector=PROVENANCE_PANEL,
    )

    # A run opened in the Graph is still open in the List, where its times
    # fit one line.
    _open_run(panel, third_run)
    panel.get_by_role("button", name="List", exact=True).click()
    expect(_run_item(panel, third_run).locator("button").first).to_have_attribute("aria-expanded", "true")
    save_workflow_test_screenshot(
        page, "node-provenance-list", test_name=TEST_NAME, fit_reactflow=False, clip_selector=PROVENANCE_PANEL,
    )
    _close(page)

    # A notebook cell's button opens the same drawer, with the same runs.
    radio = page.locator(BAR).get_by_role("radio", name="Notebook view", exact=True)
    radio.click()
    expect(radio).to_have_attribute("aria-checked", "true")
    panel = _open_runs(page)
    assert sorted(_shown(panel)) == sorted([first_run, third_run]), _shown(panel)
    _close(page)
