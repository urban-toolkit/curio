"""Playwright: the Dataflow Builder builds a two-scenario comparison (#662).

The scripted Dataflow Builder plans a frame of building heights, a shadow step
whose height factor is a widget, a scenario of that step, a duplicate of it as
a second scenario with the factor set to 2, and a step that compares the two.
The browser shows what a person judges:

1. **The review card** names both scenarios, what the duplicate copies and the
   value it changes, before anything lands.
2. **Apply** carries the widgets, the copy's lineage and the scenarios to the
   live canvas, so the canvas's own save keeps them.
3. **Solve** writes code that places the widget as a reference, and the
   comparison, run on the canvas, reads two different outcomes: the copy's
   shadows are twice as long.
4. **A reload** brings both scenarios back in the Scenarios panel.

Driven by the scripted provider, so no model is called and no socket leaves the
stack.
"""
from __future__ import annotations

import json
import re
import time

import pytest
from playwright.sync_api import expect

from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    dismiss_toasts,
    install_session_cookie,
    leave_agent_badge,
    load_artifact_as_dict,
    node_locator,
    play_node,
    read_node_code,
    read_node_output_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
    wait_for_node_done,
)

USERNAME = "agent_scenarios_e2e_user"
DFB_COORD = "agent.dataflow-builder@1.0.0"
DFB_NAME = "Dataflow Builder"
CA = "curio.builtin/computation-analysis"

FACTOR = {"name": "height_factor", "type": "number", "label": "Height factor", "default": 1,
          "options": {"min": 0.5, "max": 4, "step": 0.5}}

PLAN = {
    "goal": "compare the shadows of the buildings at their real heights and twice as tall",
    "nodes": [
        {"ref": "buildings", "nodeType": CA, "title": "Buildings", "intent": "a frame of six building heights"},
        {"ref": "shadows", "nodeType": CA, "title": "Shadows", "intent": "the shadow length per building",
         "widgets": [FACTOR]},
        {"ref": "compare", "nodeType": CA, "title": "Compare", "intent": "the mean shadow of each scenario"},
    ],
    "edges": [
        {"from": "buildings", "to": "shadows"},
        {"from": "shadows", "to": "compare", "toHandle": "in"},
        {"from": "shadows_tall", "to": "compare", "toHandle": "in_1"},
    ],
    "scenarios": [
        {"name": "Real heights", "nodes": ["shadows"], "description": "each building at its mapped height"},
        {"name": "Twice as tall", "duplicateOf": "Real heights", "copies": {"shadows": "shadows_tall"},
         "values": {"shadows_tall": {"height_factor": 2}}, "description": "every building doubled"},
    ],
}

#: What Solve's per-node calls answer, keyed by a part of each node's intent.
#: The copy has its original's intent, so one answer fills both.
CONTENT = {
    "six building heights": (
        "import pandas as pd\n\n"
        "buildings = pd.DataFrame({\n"
        "    'building': ['Library', 'Market', 'Station', 'School', 'Tower', 'Hall'],\n"
        "    'height_m': [12.0, 18.0, 25.0, 9.0, 60.0, 30.0],\n"
        "})\n"
        "return buildings\n"
    ),
    "shadow length per building": (
        "import math\n\n"
        "buildings = [!! input 0 !!].copy()\n"
        "buildings['height_m'] = buildings['height_m'] * [!! height_factor !!]\n"
        "buildings['shadow_m'] = buildings['height_m'] / math.tan(math.radians(35))\n"
        "return buildings\n"
    ),
    "mean shadow of each scenario": (
        "import pandas as pd\n\n"
        "return pd.DataFrame({\n"
        "    'scenario': ['Real heights', 'Twice as tall'],\n"
        "    'mean_shadow_m': [[!! input 0 !!]['shadow_m'].mean(), [!! input 1 !!]['shadow_m'].mean()],\n"
        "})\n"
    ),
}

_STORE_NODES_JS = """() => window.__curio_reactFlow.getNodes().map((n) => ({
    id: n.id,
    goal: (n.data && n.data.goal) || '',
    widgets: (n.data && n.data.widgets) || null,
    copiedFrom: (n.data && n.data.copiedFrom) || null,
}))"""


@pytest.fixture(scope="class")
def scenarios_session(workflow_page, frontend_server, current_server):
    workflow_page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username=USERNAME, name="Agent Scenarios E2E")
    install_session_cookie(workflow_page, frontend_server, login["token"])
    use_scripted_llm(current_server, login["token"])
    return {"page": workflow_page, "frontend": frontend_server, "backend": current_server,
            "token": login["token"]}


def _new_project_with_the_builder(session) -> str:
    backend, token = session["backend"], session["token"]
    project = api_json(
        f"{backend}/api/testing/stub-project", token, method="POST",
        payload={"username": USERNAME, "name": "Two scenarios",
                 "spec": {"dataflow": {"name": "Two scenarios", "task": "", "nodes": [], "edges": [], "packages": []}}},
    )
    base = f"{backend}/api/agents/projects/{project['id']}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": DFB_COORD})
    api_json(f"{base}/attachments", token, method="POST",
             payload={"coord": DFB_COORD, "target": {"kind": "canvas"}})
    return project["id"]


def _saved(session, project_id) -> dict:
    return api_json(f"{session['backend']}/api/projects/{project_id}", session["token"])["spec"]["dataflow"]


def _open_chat(page):
    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")).first
    expect(opener).to_be_visible(timeout=20000)
    opener.click()
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}"))
    expect(panel).to_be_visible(timeout=20000)
    return panel


def _close_chat(page, panel) -> None:
    panel.get_by_role("button", name="Close chat").click()
    expect(page.locator('[role="dialog"][aria-label^="Chat with"]')).to_have_count(0, timeout=10000)
    leave_agent_badge(page)


def _code_of(page, node_id: str) -> str:
    """The node's code, or "" while its editor is still mounting."""
    try:
        return read_node_code(page, node_id, timeout=5000)
    except Exception:  # noqa: BLE001 - polled: a missing editor is "not yet"
        return ""


def _wait_until(predicate, *, what: str, timeout: float = 240.0, step: float = 1.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(step)
    raise AssertionError(f"{what} did not happen within {timeout}s (last: {last!r})")


class TestTheDataflowBuilderBuildsTwoScenarios:
    def test_a_widget_lever_two_scenarios_and_their_comparison(self, scenarios_session):
        require_project_page()
        require_user_auth()
        session = scenarios_session
        page = session["page"]
        project_id = _new_project_with_the_builder(session)
        reply = "Two scenarios over one frame of buildings.\n```curio.v1\n" + json.dumps({"dataflowPlan": PLAN}) + "\n```"
        script_agent_replies(session["backend"], reply, by_intent=dict(CONTENT))

        page.goto(f"{session['frontend']}/dataflow/{project_id}", timeout=120000)
        page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
        require_owner_view(page)
        _wait_for_reactflow_ready(page)
        dismiss_toasts(page)
        panel = _open_chat(page)
        panel.get_by_role("textbox", name="Message this agent").fill(
            "Compare the shadows of these buildings at their real heights and twice as tall."
        )
        panel.get_by_role("button", name="Send", exact=True).click()

        # 1. The card says what it will build, both scenarios by name, before anything lands.
        card = panel.get_by_role("group", name=re.compile(r"^Review proposal: Apply plan")).first
        expect(card).to_be_visible(timeout=45000)
        expect(card).to_contain_text("2 scenarios", timeout=15000)
        listed = card.get_by_role("group", name="Scenarios this plan saves")
        expect(listed.get_by_label("Scenario Real heights")).to_be_visible()
        expect(listed.get_by_label("Scenario Twice as tall")).to_contain_text(
            "a copy of Real heights · Shadows · sets height_factor 2"
        )
        assert page.evaluate("() => window.__curio_reactFlow.getNodes().length") == 0

        # 2. Apply: the copy, its lineage and its widget value reach the live canvas.
        apply_control = panel.get_by_role("button", name=re.compile(r"^(Apply plan|Apply all without validation)$")).first
        expect(apply_control).to_be_visible(timeout=20000)
        with page.expect_response(
            lambda r: "/proposals/" in r.url and r.url.endswith("/apply") and r.request.method == "POST",
            timeout=60000,
        ) as applied:
            apply_control.click()
        assert applied.value.ok, f"apply failed: {applied.value.status}"
        page.wait_for_function("() => window.__curio_reactFlow.getNodes().length === 4", timeout=45000)
        live = {n["id"]: n for n in page.evaluate(_STORE_NODES_JS)}
        copy = next(n for n in live.values() if n["copiedFrom"])
        original = live[copy["copiedFrom"][-1]]
        assert original["goal"] == copy["goal"] and original["goal"].startswith("Shadows")
        assert original["widgets"][0]["default"] == 1 and "value" not in original["widgets"][0], original
        assert copy["widgets"][0]["value"] == 2, copy

        # 3. Solve writes each node's code, the widget placed as a reference.
        strip = page.get_by_role("group", name=DFB_NAME).first
        solve = strip.get_by_role("button", name=re.compile(r"^(Solve|Retry \d+ \w+)$"))
        expect(solve).to_be_visible(timeout=30000)
        solve.click()
        _wait_until(
            lambda: all((n.get("content") or "").strip() for n in _saved(session, project_id)["nodes"]),
            what="Solve writing every node's code",
        )
        _wait_until(
            lambda: "[!! height_factor !!]" in _code_of(page, copy["id"]),
            what="the copy's code reaching the canvas",
            timeout=60.0,
        )
        _close_chat(page, panel)

        # The canvas's own save keeps what the apply wrote: nothing was dropped
        # on the way through the live canvas.
        save_dataflow(page)
        saved = _saved(session, project_id)
        by_id = {n["id"]: n for n in saved["nodes"]}
        assert by_id[copy["id"]]["metadata"]["copiedFrom"] == [original["id"]]
        assert by_id[copy["id"]]["metadata"]["widgets"][0]["value"] == 2
        assert [(s["name"], s["nodes"]) for s in saved["scenarios"]] == [
            ("Real heights", [original["id"]]), ("Twice as tall", [copy["id"]]),
        ]

        # 4. The comparison reads both outcomes: the copy's shadows are twice as long.
        compare = next(n for n in saved["nodes"] if n["goal"].startswith("Compare"))
        play_node(page, compare["id"])
        wait_for_node_done(page, compare["id"], node_type=CA)
        output = read_node_output_text(page, compare["id"])
        match = re.search(r"Saved to file:\s(\w+_\w+)", output)
        assert match, f"the comparison saved no output: {output!r}"
        real, taller = load_artifact_as_dict(match.group(1))["data"]["mean_shadow_m"]
        assert real > 0 and taller == pytest.approx(2 * real), (real, taller)

        # 5. After a reload, both scenarios are listed, and the copy keeps its lever.
        page.reload()
        _wait_for_reactflow_ready(page)
        dismiss_toasts(page)
        node_locator(page, copy["id"]).wait_for(state="attached", timeout=45000)
        page.get_by_role("button", name="View menu").click()
        page.get_by_role("button", name="Show scenarios", exact=True).click()
        scenarios_panel = page.get_by_test_id("scenarios-panel")
        expect(scenarios_panel).to_be_visible(timeout=10000)
        names = [s["name"] for s in saved["scenarios"]]
        for scenario in saved["scenarios"]:
            card = page.get_by_test_id(f"scenario-card-{scenario['id']}")
            expect(card.get_by_label("Scenario name")).to_have_value(scenario["name"])
        assert names == ["Real heights", "Twice as tall"]
        reloaded = {n["id"]: n for n in page.evaluate(_STORE_NODES_JS)}
        assert reloaded[copy["id"]]["widgets"][0]["value"] == 2
        assert reloaded[copy["id"]]["copiedFrom"] == [original["id"]]
