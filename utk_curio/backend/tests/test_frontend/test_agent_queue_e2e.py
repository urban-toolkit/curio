"""Playwright E2E: an agent's changes on the canvas are its actions, one at a time.

Ana owns a dataflow with one node, Sum, and the Dataflow Builder on its canvas.
Ben, an editor she invited, has it open with his Built-in palette open. Ana asks
the Dataflow Builder, through its chat's route, for a plan of three chained
nodes, the last feeding Sum.

Ben's tab sees the agent join, then drag the plan's nodes from his own Built-in
palette's tiles one at a time in plan order, each ghost at its drop point under
reduced motion, each node landing as its drop ends; then the connections land,
with no motion, and the agent leaves. When Ben removes Sum while the plan
lands, the plan stops before its connections, and the change's card in Ana's
chat says what was left undone. Two agents asked at once, the Dataflow Builder
and a Node Builder adding two nodes, each drag their own nodes in their own
order, side by side.

What Ben's tab shows is recorded in the page as it happens, and read once the
replies are back: a frame would race the agents.
"""

from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    api_json,
    node_locator,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_login,
    use_scripted_llm,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER, EDITOR = "queue_agent_owner_e2e", "queue_agent_editor_e2e"
OWNER_NAME, EDITOR_NAME = "Queue Owner", "Queue Editor"
PLANNER = "agent.curio.dataflow-builder@1"
BUILDER = "agent.curio.node-builder@1"
CA = "curio.builtin/computation-analysis"
SINK = "queue-sink"
SINK_GOAL = "Sum the parks"
TITLES = ["Fetch", "Clean", "Count"]

DOCK = '[role="toolbar"][aria-label="Canvas agents"]'
PEOPLE = f'{DOCK} [role="group"][aria-label="People here"]'
ACTIVITY = f'{PEOPLE} button[aria-label="Activity"]'
ACTIVITY_LIST = '[role="region"][aria-label="Activity"]'


def _spec() -> dict:
    sink = {"id": SINK, "type": CA, "x": 0, "y": 0, "content": "return input_0", "goal": SINK_GOAL}
    return {"name": "Agents one at a time", "dataflow": {"name": "Agents one at a time", "nodes": [sink], "edges": []}}


def _plan_reply() -> str:
    plan = {
        "goal": "fetch, clean and count the parks for the sum",
        "nodes": [{"ref": title.lower(), "nodeType": CA, "title": title, "intent": f"{title.lower()} the parks"}
                  for title in TITLES],
        "edges": [{"from": "fetch", "to": "clean"}, {"from": "clean", "to": "count"}, {"from": "count", "to": SINK}],
    }
    return "Here is the plan.\n```curio.v1\n" + json.dumps({"dataflowPlan": plan}) + "\n```"


def _create_tail(title: str) -> str:
    request = {"toolRequest": {"tool": "node.create", "params": {
        "nodeType": CA, "content": f"return {title.lower()!r}", "title": title}}}
    return "```curio.v1\n" + json.dumps(request) + "\n```"


# What Ben's page shows, each time it changes: every agent's state in the room
# (what it carries and where it drops it), the drags drawn (where each starts,
# where its ghost is), the canvas's nodes with their places and how many
# connections it holds, and the agents' chips in the dock. With
# ``removeOnFirstDrag``, the node it names is removed through the canvas, as
# a person's Delete removes it, the moment an agent's first drag reaches the
# page.
_RECORD_JS = """(opts) => {
    const log = [];
    const queue = {log, removed: false};
    window.__curio_queue = queue;
    const awareness = window.__curio_awareness;
    const flow = () => window.__curio_reactFlow;
    const snapshot = () => {
        const agents = [];
        for (const state of awareness.getStates().values()) {
            if (!state || !state.user || !state.user.agent) continue;
            const carrying = state.carrying || null;
            agents.push({
                att: state.user.agent.attachmentId,
                carrying: carrying ? {id: carrying.id, kind: carrying.kind, from: carrying.from,
                                      label: carrying.node ? carrying.node.label : null} : null,
                pointer: carrying && state.pointer ? {x: state.pointer.x, y: state.pointer.y} : null,
            });
        }
        const drags = Array.from(document.querySelectorAll('[data-agent-drag]')).map((el) => {
            const ghost = el.querySelector('[data-agent-ghost]');
            return {start: el.getAttribute('data-drag-start'), kind: el.getAttribute('data-drag-kind'),
                    left: parseFloat(el.style.left), top: parseFloat(el.style.top),
                    ghost: ghost ? ghost.getAttribute('data-agent-ghost') : null};
        });
        const nodes = (flow() ? flow().getNodes() : []).map((n) => ({id: n.id, x: n.position.x, y: n.position.y}));
        const edges = flow() ? flow().getEdges().length : 0;
        const dock = document.querySelector('[role="toolbar"][aria-label="Canvas agents"]');
        const chips = Array.from(dock ? dock.querySelectorAll('[data-collab-agent]') : [])
            .map((chip) => chip.getAttribute('aria-label'));
        return {agents, drags, nodes, edges, chips};
    };
    let last = '';
    const record = () => {
        const now = snapshot();
        const key = JSON.stringify(now);
        if (key !== last) {
            last = key;
            log.push({t: performance.now(), ...now});
        }
    };
    record();
    new MutationObserver(record).observe(document.body, {subtree: true, childList: true, attributes: true});
    awareness.on('change', () => {
        if (opts.removeOnFirstDrag && !queue.removed) {
            for (const state of awareness.getStates().values()) {
                if (state && state.user && state.user.agent && state.carrying) {
                    queue.removed = true;
                    flow().deleteElements({nodes: [{id: opts.removeOnFirstDrag}]});
                    break;
                }
            }
        }
        record();
    });
}"""


class _Room:
    """Ana's dataflow, its agents, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.tokens: dict[str, str] = {}
        self.project_id = None

    def person(self, username: str, name: str, *, owns: bool = False):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
        self.contexts.append(context)
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Agents one at a time", "project_spec": _spec()} if owns else {}),
        )
        self.tokens[username] = login["token"]
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def attach(self, coord: str, target: dict) -> str:
        """*coord* on Ana's dataflow, answering on her scripted model; its attachment's id."""
        use_scripted_llm(self.backend, self.tokens[OWNER])
        base = f"{self.backend}/api/agents/projects/{self.project_id}"
        api_json(f"{base}/install", self.tokens[OWNER], method="POST", payload={"coord": coord})
        return api_json(f"{base}/attachments", self.tokens[OWNER], method="POST",
                        payload={"coord": coord, "target": target})["attachmentId"]

    def invite(self, username: str) -> None:
        api_json(f"{self.backend}/api/projects/{self.project_id}/editors", self.tokens[OWNER],
                 method="POST", payload={"username": username})

    def open(self, page, role: str) -> None:
        """Open the dataflow's link, and wait until its room names this tab
        *role* and the canvas is bound to the dataflow's doc."""
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        node_locator(page, SINK).wait_for(timeout=30000)
        try:
            page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
            page.wait_for_function("() => !!window.__curio_awareness && !!window.__curio_reactFlow", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError(f"the dataflow's room never named this tab its {role}, with its doc bound") from exc

    def ask(self, attachment_id: str, message: str) -> dict:
        """Ana asks an agent, through its chat's route, which answers once the turn is over."""
        return api_json(
            f"{self.backend}/api/agents/projects/{self.project_id}/attachments/{attachment_id}/run",
            self.tokens[OWNER], method="POST", payload={"message": message}, timeout=120,
        )

    def saved(self) -> dict:
        return api_json(f"{self.backend}/api/projects/{self.project_id}", self.tokens[OWNER])["spec"]["dataflow"]

    def close(self) -> None:
        for context in self.contexts:
            context.close()


@pytest.fixture()
def room(app_frontend: "FrontendPage", current_server: str, browser):
    require_project_page()
    require_user_auth()
    opened = _Room(app_frontend.base_url, current_server, browser)
    try:
        yield opened
    finally:
        opened.close()


def _ready(room: _Room, **record):
    """Ana's tab and Ben's on her dataflow, the Dataflow Builder on its
    canvas, Ben's Built-in palette open, his tab recording what it shows. The
    planner's attachment id, and Ana's and Ben's tabs."""
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    planner = room.attach(PLANNER, {"kind": "canvas"})
    editor = room.person(EDITOR, EDITOR_NAME)
    room.invite(EDITOR)
    room.open(owner, "owner")
    room.open(editor, "editor")
    open_tools_palette(editor, "builtin")
    editor.locator(f'[data-palette="builtin"][data-palette-item^="{CA}"]').first.wait_for(state="visible", timeout=15000)
    editor.evaluate(_RECORD_JS, record)
    return planner, owner, editor


def _recorded(page) -> list:
    return page.evaluate("() => window.__curio_queue.log")


def _wait_until_gone(page, what: str) -> None:
    try:
        page.wait_for_function(
            """() => !document.querySelector('[role="toolbar"][aria-label="Canvas agents"] [data-collab-agent]')
                && !document.querySelector('[data-agent-drag]')""",
            timeout=15000,
        )
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"{what} still shows an agent at work after its reply") from exc


def _drags_of(log: list, att: str) -> list[dict]:
    """The drags *att*'s agent played, in the order they began: each its
    carrying, its drop point, and the indices of the snapshots it was in."""
    drags: dict = {}
    for index, snapshot in enumerate(log):
        for agent in snapshot["agents"]:
            if agent["att"] == att and agent["carrying"]:
                drag = drags.setdefault(agent["carrying"]["id"], {**agent["carrying"], "drop": agent["pointer"], "at": []})
                drag["at"].append(index)
    return sorted(drags.values(), key=lambda drag: drag["at"][0])


def _near(a: dict, x: float, y: float) -> bool:
    return abs(a["x"] - x) < 0.5 and abs(a["y"] - y) < 0.5


def _landed_at(log: list, drop: dict) -> int | None:
    """The first snapshot whose canvas holds a node at *drop*, a new one's top-left."""
    for index, snapshot in enumerate(log):
        if any(node["id"] != SINK and _near(node, drop["x"], drop["y"]) for node in snapshot["nodes"]):
            return index
    return None


def _assert_dragged_one_at_a_time(log: list, att: str, labels: list[str], what: str) -> list[dict]:
    """*att*'s agent dragged one node per label, in that order, each from the
    Built-in palette's tile of its type, its ghost drawn at its drop point
    while it played (reduced motion), its node landing only once its drag
    began and before the next one began. Its drags."""
    drags = _drags_of(log, att)
    assert [drag["label"] for drag in drags] == labels, f"{what}: the drags were {drags}"
    for drag in drags:
        assert (drag["kind"], drag["from"]) == ("add", {"palette": "builtin", "item": CA}), drag
        drawn = [log[index]["drags"] for index in drag["at"] if log[index]["drags"]]
        assert drawn, f"{what}: no ghost was drawn for {drag['label']}"
        for shown in drawn:
            mine = [d for d in shown if _near({"x": d["left"], "y": d["top"]}, drag["drop"]["x"], drag["drop"]["y"])]
            assert mine and all(d["start"] == "tile" for d in mine), (
                f"{what}: {drag['label']}'s ghost was not at its drop point, from its tile: {shown}"
            )
    for current, following in zip(drags, drags[1:] + [None]):
        landed = _landed_at(log, current["drop"])
        assert landed is not None, f"{what}: {current['label']} never landed at its drop point"
        assert landed > current["at"][0], f"{what}: {current['label']} landed before its drag began"
        if following is not None:
            assert landed < following["at"][0], (
                f"{what}: {following['label']}'s drag began before {current['label']} landed"
            )
    return drags


def test_a_second_tab_sees_the_agent_drag_a_plans_nodes_one_at_a_time_then_its_connections_land(room):
    planner, _owner, editor = _ready(room)
    script_agent_replies(room.backend, _plan_reply(), attachment=planner)

    reply = room.ask(planner, "Plan the parks' analysis.")

    assert [card["status"] for card in reply["content"] if card.get("type") == "change"] == ["applied"], reply
    _wait_until_gone(editor, "Ben's tab")
    log = _recorded(editor)
    chips = [label for snapshot in log for label in snapshot["chips"]]
    assert any(label.startswith(f"Dataflow Builder (asked by {OWNER_NAME})") for label in chips), (
        f"Ben's dock never showed the Dataflow Builder at work: {chips}"
    )
    drags = _assert_dragged_one_at_a_time(log, planner, TITLES, "Ben's tab")
    # The connections land after the last node, with no motion.
    connected = next(index for index, snapshot in enumerate(log) if snapshot["edges"] > 0)
    assert connected > drags[-1]["at"][-1], f"a connection landed while a node was still being dragged: {log}"
    assert not log[connected]["drags"] and all(not a["carrying"] for a in log[connected]["agents"]), log[connected]
    assert log[-1]["edges"] == 3 and len(log[-1]["nodes"]) == 4, log[-1]
    assert log[-1]["chips"] == [], f"Ben's dock still shows the agent: {log[-1]}"
    # Ben's Activity: the agent joined, asked by Ana, then left saying what it did.
    editor.locator(ACTIVITY).click()
    activity = editor.locator(ACTIVITY_LIST)
    activity.wait_for(timeout=10000)
    lines = activity.locator("li").all_inner_texts()
    assert lines[:2] == ["Dataflow Builder left: added 3 nodes and 3 connections",
                         f"Dataflow Builder joined, asked by {OWNER_NAME}"], f"Ben's Activity lists {lines}"


def test_a_node_removed_under_a_queued_action_stops_the_queue_with_a_chat_line(room):
    planner, owner, editor = _ready(room, removeOnFirstDrag=SINK)
    script_agent_replies(room.backend, _plan_reply(), attachment=planner)

    reply = room.ask(planner, "Plan the parks' analysis.")

    assert editor.evaluate("() => window.__curio_queue.removed"), "Ben's tab never removed Sum during a drag"
    [card] = [part for part in reply["content"] if part.get("type") == "change"]
    line = f"Left undone: 3 connections, since '{SINK_GOAL}' was removed"
    assert card["status"] == "applied" and line in card["lines"], card
    _wait_until_gone(editor, "Ben's tab")
    # The plan's three nodes still landed, one at a time; none of its connections did.
    log = _recorded(editor)
    _assert_dragged_one_at_a_time(log, planner, TITLES, "Ben's tab")
    saved = room.saved()
    assert sorted(node.get("goal", "").split(" ")[0] for node in saved["nodes"]) == sorted(TITLES), saved["nodes"]
    assert saved["edges"] == [], f"a connection of the stopped plan landed: {saved['edges']}"
    # Ana's chat shows the change's card, saying what was left undone.
    owner.get_by_role("button", name=re.compile(r"^Open chat with Dataflow Builder")).first.click()
    panel = owner.get_by_role("dialog", name=re.compile(r"^Chat with Dataflow Builder"))
    expect(panel).to_be_visible(timeout=20000)
    expect(panel.get_by_role("group", name=re.compile(r"^Change: ")).first).to_contain_text(line, timeout=20000)


def test_two_agents_queues_play_side_by_side_without_mixing(room):
    planner, _owner, editor = _ready(room)
    builder = room.attach(BUILDER, {"kind": "node", "targetId": SINK})
    script_agent_replies(room.backend, _plan_reply(), attachment=planner)
    script_agent_replies(room.backend, _create_tail("One"), _create_tail("Two"), "Added two nodes.",
                         attachment=builder, reset=False)
    replies: dict = {}

    def ask(name: str, attachment_id: str, message: str) -> None:
        try:
            replies[name] = room.ask(attachment_id, message)
        except Exception as exc:  # noqa: BLE001 - what failed is the finding
            replies[name] = exc

    asked = [threading.Thread(target=ask, args=("planner", planner, "Plan the parks' analysis."), daemon=True),
             threading.Thread(target=ask, args=("builder", builder, "Add two nodes."), daemon=True)]
    for thread in asked:
        thread.start()
    for thread in asked:
        thread.join(150)
        assert not thread.is_alive(), "an agent's turn never answered"

    for name, answered in replies.items():
        assert isinstance(answered, dict), f"the {name}'s turn failed: {answered}"
    assert len([p for p in replies["planner"]["content"] if p.get("type") == "change"]) == 1, replies["planner"]
    assert len([p for p in replies["builder"]["content"] if p.get("type") == "change"]) == 2, replies["builder"]
    _wait_until_gone(editor, "Ben's tab")
    log = _recorded(editor)
    plans = _assert_dragged_one_at_a_time(log, planner, TITLES, "the Dataflow Builder")
    builds = _assert_dragged_one_at_a_time(log, builder, ["One", "Two"], "the Node Builder")
    # Side by side: each agent's drags began before the other's last one ended.
    assert plans[0]["at"][0] < builds[-1]["at"][-1] and builds[0]["at"][0] < plans[-1]["at"][-1], (
        f"the two agents' drags did not play side by side: {plans} {builds}"
    )
    saved = room.saved()
    assert sorted(node.get("title") or "" for node in saved["nodes"] if node.get("title") in ("One", "Two")) == ["One", "Two"]
    assert len(saved["nodes"]) == 6 and len(saved["edges"]) == 3, saved
