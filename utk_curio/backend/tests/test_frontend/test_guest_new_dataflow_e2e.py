"""Playwright E2E: a hosted guest's File > New is a dataflow of its own,
kept until the server starts again.

On a Curio started with ``--deploy`` every visitor signs in to the one shared
guest account. A visitor opens File > New, adds a node by hand, and drops the
Dataflow Builder on the canvas: that first action that needs an id makes the
dataflow, as an account's does, and the agent's plan (a scripted model) adds a
node to it. A reload shows both nodes, the gallery lists the dataflow first,
marked Kept for this visit, and a second visitor finds none of it.

On a stack without sign-in the shared guest is the one local user: its File >
New is a dataflow of the account's, which the gallery lists unmarked and a
second browser lists too.
"""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError

from playwright.sync_api import expect

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    canvas_nodes,
    close_tools_palette,
    drag_builtin_to_canvas,
    node_locator,
    open_new_workflow,
    open_tools_palette,
    script_agent_replies,
    use_scripted_llm,
    wait_for_changes_kept,
    wait_for_projects_page,
)
from .utils.canvas_authoring import _DRAG_TO_CANVAS_JS, CANVAS_DROP_TARGET
from .utils.db_stubs import _post_json, _request_json

PLANNER = "agent.curio.dataflow-builder@1"
CODE = "curio.builtin/python-computation"
CARDS = '[data-curio-projects-scroll="true"] [data-project-id]'
KEPT = '[data-curio-kept-for-visit="true"]'


def _plan_reply() -> str:
    """The scripted Dataflow Builder's answer: a plan of one node."""
    plan = {
        "goal": "count the street trees",
        "nodes": [{"ref": "count", "nodeType": CODE, "title": "Count trees", "intent": "count the trees"}],
        "edges": [],
    }
    return "Here is the plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _enter_as_a_guest(page, base: str, hosted: bool) -> str:
    """Open the gallery as a guest, a hosted guest through Continue as Guest;
    the token of the browser's sign-in."""
    page.goto(f"{base}/auth/signin" if hosted else f"{base}/", timeout=120000)
    if hosted:
        page.get_by_text("Continue as Guest").click(timeout=30000)
    page.wait_for_url("**/projects", timeout=30000)
    wait_for_projects_page(page, timeout=30000)
    for cookie in page.context.cookies():
        if cookie["name"] == "session_token":
            return cookie["value"]
    raise AssertionError("the guest's browser holds no session_token cookie")


def _status(url: str, token: str) -> int:
    try:
        api_json(url, token)
    except HTTPError as exc:
        return exc.code
    return 200


def _drop_on_the_canvas(page, coord: str) -> None:
    """Drag the agent *coord* from the agents palette onto an empty part of
    the canvas, below and right of the hand-made node."""
    open_tools_palette(page, "agents")
    row = page.locator(f'#agents-palette [data-agent-coord="{coord}"]')
    row.wait_for(state="visible", timeout=30000)
    pane = page.locator(CANVAS_DROP_TARGET)
    box = pane.bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    dropped = page.evaluate(_DRAG_TO_CANVAS_JS, {
        "source": row.element_handle(), "targetSelector": CANVAS_DROP_TARGET,
        "clientX": box["x"] + box["width"] - 120, "clientY": box["y"] + box["height"] - 120,
    })
    assert dropped == "ok", f"the agent's drag failed: {dropped}"
    close_tools_palette(page, "agents")


def _gallery(page, base: str):
    """The cards the gallery of *page*'s browser shows, once it has listed."""
    page.goto(f"{base}/projects")
    wait_for_projects_page(page, timeout=30000)
    page.wait_for_function(
        """() => !!document.querySelector('[data-curio-projects-scroll="true"] [data-project-id]')
            || /No projects yet/.test(document.body.innerText)""",
        timeout=30000,
    )
    return page.locator(CARDS)


def test_a_guests_file_new_is_its_own_dataflow_which_a_reload_and_its_gallery_keep(
    app_frontend, current_server, browser,
):
    hosted = auth_enabled_env()
    if hosted:
        assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
    base, backend = app_frontend.base_url, current_server
    contexts = []
    endpoint_set = False
    try:
        contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce"))
        mine = contexts[-1].new_page()
        my_token = _enter_as_a_guest(mine, base, hosted)
        if hosted:
            # A hosted guest's agents answer on this Curio's own endpoint.
            _post_json(f"{backend}/api/testing/llm-deployment", {"scripted": True})
            endpoint_set = True
        else:
            use_scripted_llm(backend, my_token)

        # File > New, and a node added by hand: no dataflow is made yet.
        open_new_workflow(mine)
        mine.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
        assert re.search(r"/dataflow/new$", mine.url), mine.url
        hand = drag_builtin_to_canvas(mine, "#tile-python-computation", at=(100, 100))

        # The Dataflow Builder dropped on the canvas makes the dataflow, then attaches.
        with mine.expect_response(
            lambda r: r.request.method == "POST" and re.search(r"/api/projects$", r.url) is not None,
            timeout=60000,
        ) as created:
            _drop_on_the_canvas(mine, PLANNER)
        assert created.value.status == 201, created.value.text()
        made = created.value.json()
        assert made.get("kept_for_visit", False) is hosted, made
        project_id = made["id"]
        expect(mine.get_by_text("Agent attached to the canvas.")).to_be_visible(timeout=30000)
        mine.wait_for_url(f"**/dataflow/{project_id}", timeout=30000)
        listed = api_json(f"{backend}/api/agents/projects/{project_id}/attachments", my_token)["attachments"]
        attached = [a for a in listed if a.get("coord") == PLANNER and (a.get("target") or {}).get("kind") == "canvas"]
        assert len(attached) == 1, f"the drop did not attach one Dataflow Builder to the canvas: {listed}"

        # The agent's plan lands its node in the dataflow, which the tab shows.
        script_agent_replies(backend, _plan_reply(), attachment=attached[0]["attachmentId"])
        answered = api_json(
            f"{backend}/api/agents/projects/{project_id}/attachments/{attached[0]['attachmentId']}/run",
            my_token, method="POST", payload={"message": "Plan a node that counts the trees."}, timeout=120,
        )
        assert [c["status"] for c in answered["content"] if c.get("type") == "change"] == ["applied"], answered
        mine.wait_for_function("() => window.__curio_reactFlow.getNodes().length >= 2", timeout=30000)
        planned = [n["id"] for n in canvas_nodes(mine) if n["id"] != hand]
        assert len(planned) == 1, canvas_nodes(mine)
        wait_for_changes_kept(mine)
        bar = mine.locator("[data-curio-save-state]")
        expect(bar).to_have_text("Kept for this visit" if hosted else "Saved")

        # A reload opens the dataflow with both nodes.
        mine.reload()
        for node in (hand, planned[0]):
            node_locator(mine, node).wait_for(timeout=30000)
        held = {n["id"] for n in api_json(f"{backend}/api/projects/{project_id}", my_token)["spec"]["dataflow"]["nodes"]}
        assert {hand, planned[0]} <= held, held

        # The gallery lists it first, marked when it is a hosted guest's own.
        cards = _gallery(mine, base)
        expect(cards.first).to_have_attribute("data-project-id", project_id)
        if hosted:
            mark = cards.first.locator(KEPT)
            expect(mark).to_have_text("Kept for this visit")
            expect(mark).to_have_attribute("data-tooltip", "Sign in to save dataflows.")
        else:
            expect(cards.first.locator(KEPT)).to_have_count(0)

        # A second visitor finds none of it; the local guest's second browser is the same account.
        contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}))
        theirs = contexts[-1].new_page()
        their_token = _enter_as_a_guest(theirs, base, hosted)
        their_cards = _gallery(theirs, base)
        if hosted:
            assert their_token != my_token
            assert _status(f"{backend}/api/projects/{project_id}", their_token) == 404
            assert project_id not in [p["id"] for p in api_json(f"{backend}/api/projects", their_token)]
            expect(theirs.locator(f'[data-project-id="{project_id}"]')).to_have_count(0)
        else:
            expect(their_cards.first).to_have_attribute("data-project-id", project_id)
    finally:
        if endpoint_set:
            _request_json(f"{backend}/api/testing/llm-deployment", method="DELETE")
        for context in contexts:
            context.close()
