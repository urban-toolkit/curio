"""Playwright: a Dataflow Builder plan's Undo, clicked on the canvas the plan
landed on.

The scripted Dataflow Builder plans two nodes and the connection between them
on a dataflow whose goal is empty, open in this tab, whose canvas is bound to
the dataflow's doc. The plan lands as the agent's writes, a node, a node, then
the connection, and fills the goal. The **Undo** on the plan's card then takes
it all back: the server answers 200, the nodes and the connection leave the
canvas and the saved dataflow, and the goal is empty again.

Found by #1636's dev check (11-26): the open tab wrote the settings its canvas
gives a node (its Save toggle, its input and output types, its keywords) into
each of the plan's nodes as it arrived, between the plan's writes, and every
Undo was refused with 409. What this tab's canvas writes into the doc is
recorded from before the plan until after its Undo: it writes nothing.

Driven by the scripted provider, so no model is called. Nothing is drawn.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_plan_undo_on_an_open_canvas_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    dismiss_toasts,
    require_owner_view,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_login,
    use_scripted_llm,
    wait_for_changes_kept,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DFB_COORD = "agent.curio.dataflow-builder@1"
DFB_NAME = "Dataflow Builder"
CA = "curio.builtin/python-computation"
GOAL = "count the parks by street"
PLAN = {
    "goal": GOAL,
    "nodes": [
        {"ref": "parks", "nodeType": CA, "title": "Parks", "intent": "load the parks"},
        {"ref": "count", "nodeType": CA, "title": "Count", "intent": "count the parks by street"},
    ],
    "edges": [{"from": "parks", "to": "count"}],
}
PLAN_REPLY = "Two nodes for the count.\n```curio.v1\n" + json.dumps({"dataflowPlan": PLAN}) + "\n```"
TITLE = "Parks by street"
GOAL_EMPTY = "Add what this dataflow is for"

#: Every update this tab's canvas writes into the dataflow's doc from now on
#: (its writes carry ``CANVAS_ORIGIN``, "canvas"), each with the readable runs
#: of its bytes, so a failure says what was written.
_RECORD_CANVAS_WRITES_JS = """() => {
    const doc = window.__curio_awareness.doc;
    const writes = [];
    window.__curio_canvasWrites = writes;
    doc.on('update', (update, origin) => {
        if (origin !== 'canvas') return;
        const runs = [];
        let run = '';
        for (const byte of update) {
            if (byte >= 32 && byte < 127) {
                run += String.fromCharCode(byte);
                continue;
            }
            if (run.length >= 2) runs.push(run);
            run = '';
        }
        if (run.length >= 2) runs.push(run);
        writes.push({at: Math.round(performance.now()), bytes: update.length, runs});
    });
}"""

_CANVAS_HOLDS_JS = """([nodes, edges]) => !!window.__curio_reactFlow
    && window.__curio_reactFlow.getNodes().length === nodes
    && window.__curio_reactFlow.getEdges().length === edges"""


def _spec() -> dict:
    """An empty dataflow, its goal empty."""
    return {"dataflow": {
        "name": "Parks", "task": "", "timestamp": 1789193389280, "provenance_id": "Parks",
        "nodes": [], "edges": [],
    }}


def _saved(backend: str, token: str, project_id: str) -> dict:
    return api_json(f"{backend}/api/projects/{project_id}", token)["spec"]["dataflow"]


def _wait_until(predicate, *, what: str, timeout: float = 60.0, step: float = 0.5):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(step)
    raise AssertionError(f"{what} did not happen within {timeout:.0f} s (last: {last!r})")


def test_a_plans_undo_on_the_canvas_it_landed_on_takes_its_nodes_its_connection_and_its_goal_back(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        username="plan_undo_on_an_open_canvas", name="Plan Undo Owner", project_name="Parks", project_spec=_spec(),
    )
    token, project_id = login["token"], login["project"]["id"]
    use_scripted_llm(current_server, token)
    agents = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{agents}/install", token, method="POST", payload={"coord": DFB_COORD})
    api_json(f"{agents}/attachments", token, method="POST", payload={"coord": DFB_COORD, "target": {"kind": "canvas"}})
    # Every call in order: the plan, then the conversation's title.
    script_agent_replies(current_server, PLAN_REPLY, TITLE, dataflow=project_id)

    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}", timeout=120000)
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    # The canvas is empty, so wait for React Flow itself, then for the room to
    # name this tab its owner and for the doc's first sync, which the canvas
    # binds on.
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    page.locator('[data-curio-room-role="owner"]').wait_for(state="attached", timeout=30000)
    page.wait_for_function(
        "() => !!window.__curio_awareness && window.__curio_awareness.doc.getMap('meta').has('id')", timeout=30000,
    )
    page.evaluate(_RECORD_CANVAS_WRITES_JS)
    dismiss_toasts(page)

    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")).first
    expect(opener).to_be_visible(timeout=45000)
    opener.click()
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}"))
    expect(panel).to_be_visible(timeout=20000)
    goal_line = panel.locator("[data-curio-chat-goal]")
    expect(goal_line.get_by_role("button", name=GOAL_EMPTY)).to_be_visible(timeout=20000)
    panel.get_by_role("textbox", name=re.compile(r"^Message ")).fill("Count the parks by street.")
    panel.get_by_role("button", name="Send", exact=True).click()

    # The plan landed with the reply: its card offers its Undo, the canvas and
    # the saved dataflow hold its two nodes and its connection, and it filled
    # the goal (#1636).
    card = panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first
    expect(card).to_be_visible(timeout=90000)
    undo = card.get_by_role("button", name="Undo")
    expect(undo).to_be_visible(timeout=10000)
    page.wait_for_function(_CANVAS_HOLDS_JS, arg=[2, 1], timeout=60000)
    _wait_until(
        lambda: (lambda flow: flow if len(flow["nodes"]) == 2 and len(flow["edges"]) == 1 and flow.get("task") == GOAL
                 else None)(_saved(current_server, token, project_id)),
        what="the plan's two nodes, its connection and its goal in the saved dataflow",
    )
    expect(goal_line).to_contain_text(GOAL, timeout=20000)
    expect(goal_line.get_by_role("button", name="Edit the goal")).to_be_visible()
    # Whatever this tab wrote meanwhile is on the server before the Undo.
    wait_for_changes_kept(page)

    # The Undo, from the card. Matched without r.ok on purpose: a refused Undo
    # says its status and its words here.
    with page.expect_response(
        lambda r: "/changes/" in r.url and r.url.endswith("/undo") and r.request.method == "POST", timeout=60000,
    ) as undone:
        undo.click()
    response = undone.value
    assert response.status == 200, f"the plan's Undo was refused: HTTP {response.status}: {response.text()[:300]}"
    expect(card.get_by_text("Undone", exact=True)).to_be_visible(timeout=20000)

    # Its nodes and its connection left the canvas and the saved dataflow, and
    # the goal it set is empty again, there and on the Goal line.
    page.wait_for_function(_CANVAS_HOLDS_JS, arg=[0, 0], timeout=30000)
    _wait_until(
        lambda: (lambda flow: flow if not flow["nodes"] and not flow["edges"] and not (flow.get("task") or "")
                 else None)(_saved(current_server, token, project_id)),
        what="the saved dataflow with no node, no connection and no goal",
    )
    expect(goal_line.get_by_role("button", name=GOAL_EMPTY)).to_be_visible(timeout=20000)

    # From before the plan to after its Undo, this tab's canvas wrote nothing
    # into the doc: what the doc brought it, it took, and wrote none of back.
    wait_for_changes_kept(page)
    written = page.evaluate("() => window.__curio_canvasWrites")
    assert written == [], f"this tab's canvas wrote into the doc while the plan landed or was undone: {written}"
