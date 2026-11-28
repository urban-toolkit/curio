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

When the person typed into one of the plan's nodes after it landed, and the
Undo goes ahead anyway, the Undo is a version of its own made from the one on
the canvas, the typing, and named after what it did, so the Provenance drawer
lists every version on one line, with no branch folded: the plan, the
typing, then the Undo.

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
    frame_nodes,
    leave_agent_badge,
    require_owner_view,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    set_node_code,
    stub_db_login,
    use_scripted_llm,
    wait_for_changes_kept,
    wait_for_drawer_closed,
)
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    await_provenance_history,
    listed_versions,
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

#: Who lands the plan, types into its Count node, and asks for its Undo.
TYPIST = "Plan Undo Typist"
#: What they type into Count.
TYPED = "return 'counted by hand'"
#: The chat's panel.
CHAT_PANEL = '[role="dialog"][aria-label^="Chat with"]'
#: What the plan's Undo is named in the history: what it did.
UNDID = "Undid Dataflow Builder's change"


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


def _code_of(flow: dict, node_id: str):
    return next((node.get("content") for node in flow["nodes"] if node.get("id") == node_id), None)


def _versions(backend: str, token: str, project_id: str) -> list[dict]:
    """The dataflow's versions as the Provenance drawer reads them."""
    return api_json(f"{backend}/api/projects/{project_id}/history", token)["versions"]


def _plan_typed_into_on_an_open_canvas(app_frontend, current_server: str, page, *, username: str) -> dict:
    """The scripted Dataflow Builder's plan of Parks and Count, landed from its
    chat on an empty dataflow open in this tab, bound to its doc, and
    :data:`TYPED` typed into Count through its code editor after it landed,
    in the saved dataflow: the token, the dataflow, the Builder's attachment
    and change, its chat's panel and the plan's card, and Count's id."""
    login = stub_db_login(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        username=username, name=TYPIST, project_name="Parks", project_spec=_spec(),
    )
    token, project_id = login["token"], login["project"]["id"]
    use_scripted_llm(current_server, token)
    agents = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{agents}/install", token, method="POST", payload={"coord": DFB_COORD})
    att = api_json(f"{agents}/attachments", token, method="POST",
                   payload={"coord": DFB_COORD, "target": {"kind": "canvas"}})["attachmentId"]
    # Every call in order: the plan, then the conversation's title.
    script_agent_replies(current_server, PLAN_REPLY, TITLE, dataflow=project_id)

    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}", timeout=120000)
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    # The canvas binds on the doc's first sync, so what is typed reaches the
    # doc as this tab's typing, which the history keeps as the typist's.
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    page.locator('[data-curio-room-role="owner"]').wait_for(state="attached", timeout=30000)
    page.wait_for_function(
        "() => !!window.__curio_awareness && window.__curio_awareness.doc.getMap('meta').has('id')", timeout=30000,
    )
    dismiss_toasts(page)

    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")).first
    expect(opener).to_be_visible(timeout=45000)
    opener.click()
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}"))
    expect(panel).to_be_visible(timeout=20000)
    panel.get_by_role("textbox", name=re.compile(r"^Message ")).fill("Count the parks by street.")
    panel.get_by_role("button", name="Send", exact=True).click()
    card = panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first
    expect(card).to_be_visible(timeout=90000)
    expect(card.get_by_role("button", name="Undo", exact=True)).to_be_visible(timeout=10000)
    page.wait_for_function(_CANVAS_HOLDS_JS, arg=[2, 1], timeout=60000)
    flow = _wait_until(
        lambda: (lambda flow: flow if len(flow["nodes"]) == 2 and len(flow["edges"]) == 1 else None)(
            _saved(current_server, token, project_id)),
        what="the plan's two nodes and its connection in the saved dataflow",
    )
    count = next(node["id"] for node in flow["nodes"] if node.get("title") == "Count")
    turns = api_json(f"{agents}/attachments/{att}/session", token)["turns"]
    [change] = [part["changeId"] for turn in turns for part in turn.get("content") or []
                if part.get("type") == "change" and part.get("kind") == "plan"]

    # The person types into the plan's Count node, in its code editor.
    frame_nodes(page, [count])
    set_node_code(page, count, TYPED)
    wait_for_changes_kept(page)
    _wait_until(
        lambda: _code_of(_saved(current_server, token, project_id), count) == TYPED,
        what="what was typed into Count, in the saved dataflow",
    )
    return {"token": token, "project": project_id, "attachment": att, "change": change, "panel": panel,
            "card": card, "count": count}


def _open_provenance(page):
    """The Provenance drawer, opened from the View menu, its history listed."""
    page.get_by_role("button", name="View menu", exact=True).click()
    page.get_by_test_id("provenance-menu-item").click()
    drawer = page.locator(PROVENANCE_PANEL)
    drawer.wait_for(state="visible", timeout=20000)
    await_drawer_at_rest(page)
    await_provenance_history(page)
    return drawer


def test_a_plans_undo_is_a_version_on_top_of_the_typing_and_provenance_lists_every_version_on_one_line(
    app_frontend: "FrontendPage", current_server: str, page,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    landed = _plan_typed_into_on_an_open_canvas(app_frontend, current_server, page, username="plan_undo_on_top")
    token, project_id = landed["token"], landed["project"]
    # The typing is a version of the history once its pause is over.
    typing = _wait_until(
        lambda: (lambda last: last if last["kind"] == "typing" else None)(
            _versions(current_server, token, project_id)[-1]),
        what="the typing in Count, a version of the history",
    )
    assert typing["what"] == f"{TYPIST} edited", typing

    # The plan's Undo, asked to go ahead though Count was typed into, as its
    # card's Undo anyway asks it.
    undone = api_json(
        f"{current_server}/api/agents/projects/{project_id}/attachments/{landed['attachment']}"
        f"/changes/{landed['change']}/undo",
        token, method="POST", payload={"anyway": True},
    )
    assert undone["status"] == "undone", undone
    page.wait_for_function(_CANVAS_HOLDS_JS, arg=[0, 0], timeout=30000)
    versions = _versions(current_server, token, project_id)
    undo = versions[-1]
    assert versions[-2]["id"] == typing["id"], versions[-3:]

    # The Provenance drawer lists every version on one line, with no branch
    # folded: the typing right above the Undo, which says what it did.
    landed["panel"].get_by_role("button", name="Close chat").click()
    expect(page.locator(CHAT_PANEL)).to_have_count(0, timeout=10000)
    leave_agent_badge(page)
    drawer = _open_provenance(page)
    expect(drawer.locator(f'[data-provenance-item="{undo["id"]}"]')).to_be_visible(timeout=20000)
    folds = drawer.locator("[data-provenance-fold]").count()
    listed = listed_versions(page)
    assert folds == 0 and listed == [version["id"] for version in versions], (
        f"the drawer folds {folds} branch(es) and lists {listed}, not every version on one line: "
        f"{[(version['id'], version.get('what')) for version in versions]}")
    expect(drawer.locator(f'[data-provenance-item="{typing["id"]}"]')).to_contain_text(f"{TYPIST} edited")
    expect(drawer.locator(f'[data-provenance-item="{undo["id"]}"]')).to_contain_text(UNDID)
    page.get_by_role("button", name="Close Dataflow provenance", exact=True).click()
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)
