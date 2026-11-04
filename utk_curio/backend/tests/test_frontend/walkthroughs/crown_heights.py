"""Building the Crown Heights shade example a step at a time: the five scenes
the guide's Crown Heights page shows as clips.

``docs/examples/dataflows/crown-heights-1550-bedford-shadow.json`` compares the
shade on Block 1259's open ground without and with the tower proposed at 1550
Bedford Avenue. Each scene opens on the example cut back to where its step
begins (``Walkthrough.start``) and checks that the step lands where the example
is:

1. the Dataflow Builder plans a first version from a short prompt, and Solve
   writes its code;
2. the two scenarios and their scenario set are defined by hand, a Map Editor
   goes into the second, and the agent's check table comes out;
3. the Node Builder adds the tower's two parts in the Map Editor;
4. the Dataflow Builder adds the day's plot and the map of the shade the tower
   adds, and Solve writes their specs;
5. the dashboard opens on the winter solstice and moves to the summer one.

The agents' replies are scripted (``utils/scripted_llm.py``) and carry the
example's own code, specs and edges, so what an agent writes is what the
example holds. What a clip leaves out, the waits on Solve and on the runs, is
marked as a cut (``ctx.mark``) in the recording.
"""
from __future__ import annotations

import copy
import json
import re
import time
import uuid

from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.infrastructure.testing_provider import FALLBACK_REPLY

from ..utils import (
    CANVAS_DROP_TARGET,
    SCENARIO_DRAWER,
    _DRAG_TO_CANVAS_JS,
    api_json,
    captured_agent_prompts,
    close_scenario_details,
    close_scenario_drawer,
    close_tools_palette,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    frame_nodes,
    keep_drawing,
    leave_agent_badge,
    node_locator,
    open_in_project_tab,
    open_scenario_details,
    open_tools_palette,
    park_pointer,
    play_node,
    require_webgpu,
    run_all_and_wait,
    save_dataflow,
    scenario_card_button,
    script_agent_replies,
    settled_viewport,
    use_scripted_llm,
    wait_for_drawer_closed,
    wait_for_node_done,
)
from ..utils.capture_waits import _wait_for_no_node_running
from .framework import Ctx, walkthrough
from .steps import load_example_spec


EXAMPLE = "dataflows/crown-heights-1550-bedford-shadow.json"
#: The example's name, from which its builder
#: (``scripts/build_example_bedford_shadow.py``) makes its node ids: a node's
#: id is the uuid5 of its key in this namespace.
NAME = "Crown Heights shade from 1550 Bedford Avenue"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, f"https://curio.dev/examples/{NAME}")
DATASET = "data.nyc.crown-heights-1550-bedford"
EDIT_TYPE = "curio.builtin/edit-features"
CHAT = '[role="dialog"][aria-label^="Chat with"]'

#: How long a Run All of the whole example may take on a busy GPU runner.
RUN_ALL_MS = 600000
#: How long Solve may take to write and check every node it was given.
SOLVE_S = 480.0


def nid(key: str) -> str:
    """The id of the example's node of builder key *key*."""
    return str(uuid.uuid5(NAMESPACE, key))


#: The first version, by builder key: what both scenarios will read (the
#: three loads, the sun's steps on the day picked and through 2027, the open
#: ground and the maps' extent), then one scenario's buildings for the GPU and
#: its three GPU steps. It stops there: Solve proves the code it writes by
#: running it on the server, where an Autark step is only checked, so the
#: nodes that read a GPU step's result could not be proven.
FIXED = ("buildings", "block", "streets", "year-steps", "steps", "ground", "map-area")
TO_THE_GPU = ("base-tower", "base-sun-rays", "base-block-rays", "base-year-rays")
FIRST_VERSION = FIXED + TO_THE_GPU

#: The table of the open-ground cells the first version adds to check the
#: grid, which the second scene takes out.
TABLE = str(uuid.uuid5(NAMESPACE, "check-table"))
TABLE_TYPE = "curio.builtin/vis-simple"
TABLE_TITLE = "Table: open-ground cells"
TABLE_GOAL = "Show the open-ground cells as a table, to check the grid."
#: Where the table sits in the second scene's first version: beside the grid,
#: left of the chain, so outside the box a Shift-drag selects the chain with.
TABLE_AT = (1290, -450)
#: How far right of the example's place the second scene's first version puts
#: the chain: one column, so the copies Duplicate scenario makes below it
#: leave the grid's column free for the Map Editor, left of the copies, and
#: the second scenario's frame takes in no node of the context.
CHAIN_SHIFT = 645

#: What the fourth scene's agent adds: the plot of the block's share in shadow
#: through the day, and the map of the shade the tower adds.
PLOT_AND_MAP = ("plot", "added-map")

#: A Map Editor node's code with no edit, as the node writes it.
NO_EDITS = (
    "# Map Editor writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
    "return curio_edit_features(input_0, [])\n"
)

#: What the person types, scene by scene.
FIRST_PROMPT = (
    "Compare the shade on the block across Eastern Parkway with and without "
    "the tower proposed at 1550 Bedford Avenue."
)
TOWER_PROMPT = (
    "Add the building proposed at 1550 Bedford Avenue: a base to 135 feet, 30 "
    "feet back from Eastern Parkway, and upper floors to 185 feet, set back above it."
)
PLOT_AND_MAP_PROMPT = (
    "Plot the block's share in shadow through the day, a line per scenario, "
    "and map the shade the tower adds."
)

#: How much of a long prompt a clip shows typed before it cuts to the whole.
PROMPT_SHOWN = 48

#: What each first turn's title call is answered: the queue's next reply
#: names the chat, and an empty queue would name it after the scripted
#: provider's fallback.
FIRST_TITLE = "Crown Heights shade study"
TOWER_TITLE = "The proposed tower"
PLOT_AND_MAP_TITLE = "The day's plot and the added shade"

#: A by-intent key is this long a start of the intent it answers: enough to
#: tell the example's nodes apart, short of any trimming of the intent.
_INTENT_KEY_CHARS = 48


# ---------------------------------------------------------------------------
# The example, cut back
# ---------------------------------------------------------------------------

def _example() -> dict:
    return load_example_spec(EXAMPLE)


def _nodes(spec: dict) -> dict[str, dict]:
    return {node["id"]: node for node in spec["dataflow"]["nodes"]}


def _cut(spec: dict, keep: set[str], *, scenarios: bool) -> dict:
    """*spec* with only the nodes in *keep* and the connections between them,
    and its scenarios and their set only when *scenarios*: each scenario then
    lists the nodes in *keep* alone, as its own, its context and its outcomes."""
    cut = copy.deepcopy(spec)
    flow = cut["dataflow"]
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] in keep]
    flow["edges"] = [edge for edge in flow["edges"] if edge["source"] in keep and edge["target"] in keep]
    if not scenarios:
        flow.pop("scenarios", None)
        flow.pop("scenarioSets", None)
        return cut
    for scenario in flow.get("scenarios") or []:
        for part in ("nodes", "context", "outcomes"):
            if part in scenario:
                scenario[part] = [node_id for node_id in scenario[part] if node_id in keep]
    return cut


def _empty(spec: dict) -> dict:
    """The dataflow the first scene opens on: no node yet and the example's
    name. The scene adds the dataset as the Data Catalog does."""
    cut = _cut(spec, set(), scenarios=False)
    cut["dataflow"].pop("datasets", None)
    return cut


def _first_version(spec: dict) -> dict:
    """Where the first scene ends and the second begins: the first version,
    pinned to no dashboard yet, with the agent's check table beside the grid
    and the chain a column right of the example's place."""
    cut = _cut(spec, {nid(key) for key in FIRST_VERSION}, scenarios=False)
    flow = cut["dataflow"]
    chain = {nid(key) for key in TO_THE_GPU}
    for node in flow["nodes"]:
        for key in ("dashboardPinned", "dashboardX", "dashboardY", "dashboardWidth", "dashboardHeight"):
            node.pop(key, None)
        if node["id"] in chain:
            node["x"] += CHAIN_SHIFT
    flow["nodes"].append({
        "id": TABLE,
        "type": TABLE_TYPE,
        "x": TABLE_AT[0],
        "y": TABLE_AT[1],
        "content": "",
        "out": "DEFAULT",
        "in": "DEFAULT",
        "goal": TABLE_GOAL,
        "metadata": {"keywords": []},
        "title": TABLE_TITLE,
    })
    flow["edges"].append({
        "id": f"reactflow__edge-{nid('ground')}out-{TABLE}in",
        "source": nid("ground"),
        "target": TABLE,
        "sourceHandle": "out",
        "targetHandle": "in",
    })
    return cut


def _without_edits(spec: dict) -> dict:
    """The example before the third scene: the Map Editor holds no edit."""
    cut = copy.deepcopy(spec)
    _nodes(cut)[nid("add-building")]["content"] = NO_EDITS
    return cut


def _without_plot_and_map(spec: dict) -> dict:
    """The example before the fourth scene: no day's plot and no map of the
    shade the tower adds."""
    gone = {nid(key) for key in PLOT_AND_MAP}
    return _cut(spec, set(_nodes(spec)) - gone, scenarios=True)


# ---------------------------------------------------------------------------
# What the agents reply
# ---------------------------------------------------------------------------

def _intent(node: dict) -> str:
    """A planned node's intent: its goal in the example. A loader's names the
    dataset it reads, which grounds its source as a person's words would."""
    goal = str(node["goal"]).strip()
    if node["type"] == "curio.builtin/data-loading":
        return f"{goal} It reads {DATASET}."
    return goal


def _intent_key(intent: str) -> str:
    return intent[:_INTENT_KEY_CHARS]


def _plan(spec: dict, refs: dict[str, str], goal: str, extra: tuple = ()) -> dict:
    """A plan of the example's nodes *refs* (``{ref: node id}``), each with its
    title, its goal as the intent and its widgets, and the example's
    connections into them: between planned nodes by ref, from any other node
    by its id. *extra* adds planned nodes and edges of the plan's own."""
    nodes = _nodes(spec)
    ref_of = {node_id: ref for ref, node_id in refs.items()}
    planned = []
    for ref, node_id in refs.items():
        node = nodes[node_id]
        entry = {"ref": ref, "nodeType": node["type"], "title": node["title"], "intent": _intent(node)}
        widgets = (node.get("metadata") or {}).get("widgets")
        if widgets:
            entry["widgets"] = widgets
        planned.append(entry)
    edges = [
        {"from": ref_of.get(edge["source"], edge["source"]), "to": ref_of[edge["target"]],
         "toHandle": edge["targetHandle"]}
        for edge in spec["dataflow"]["edges"]
        if edge["target"] in ref_of and edge.get("type") != "Interaction"
    ]
    for node, node_edges in extra:
        planned.append(node)
        edges.extend(node_edges)
    return {"goal": goal, "nodes": planned, "edges": edges}


def _plan_reply(text: str, plan: dict) -> str:
    return f"{text}\n```curio.v1\n{json.dumps({'dataflowPlan': plan})}\n```"


def _solve_replies(spec: dict, refs: dict[str, str]) -> dict[str, str]:
    """What Solve's call for each planned node is answered: the example's
    code or spec for that node, keyed by the start of the node's intent."""
    nodes = _nodes(spec)
    return {_intent_key(_intent(nodes[node_id])): nodes[node_id]["content"] for node_id in refs.values()}


def _write_reply(text: str, node_id: str, content: str) -> str:
    """The Node Builder's reply: the node's new content, which lands with it."""
    request = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": node_id, "content": content}}}
    return f"{text}\n\n```curio.v1\n{json.dumps(request)}\n```"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def _agent(agent_id: str):
    """A shipped agent's manifest: its coordinate and its name."""
    return next(m for m in builtin.list_builtin_manifests() if m.agent_id == agent_id)


def _session(page) -> tuple[str, str]:
    """The signed-in owner's token and the open dataflow's id."""
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the scene cannot reach the API"
    return token, page.url.rstrip("/").rsplit("/", 1)[-1]


def _saved(ctx: Ctx, token: str, project_id: str) -> dict:
    return api_json(f"{ctx.backend}/api/projects/{project_id}", token)["spec"]["dataflow"]


def _install(ctx: Ctx, token: str, project_id: str, agent, *, target: dict | None = None) -> None:
    """Add *agent* to the dataflow, and attach it to *target* when given."""
    base = f"{ctx.backend}/api/agents/projects/{project_id}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": agent.dir_name})
    if target is not None:
        api_json(f"{base}/attachments", token, method="POST", payload={"coord": agent.dir_name, "target": target})


def _reload(page) -> None:
    """Reload the dataflow, so what was set over HTTP is on the page."""
    page.reload()
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=60000)


def _node_ids(page) -> list[str]:
    return page.evaluate("() => window.__curio_reactFlow.getNodes().map((n) => n.id)")


def _centre(page, node_id: str) -> tuple[float, float]:
    box = node_locator(page, node_id).bounding_box()
    assert box, f"node {node_id} has no layout box"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _pane_centre(page) -> tuple[float, float]:
    box = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert box, f"{CANVAS_DROP_TARGET} has no layout box"
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _drop_agent(ctx: Ctx, agent, point: tuple[float, float]) -> None:
    """Drag *agent* from the rail's agent palette onto *point*: the empty
    canvas attaches it to the canvas, a node to that node. The palette lists
    the agents the dataflow holds, so it was added first."""
    page = ctx.page
    ctx.focus(page.locator('#agents-palette button[data-tooltip="Open agent palette"]'), hold=500)
    open_tools_palette(page, "agents")
    row = page.locator(f'#agents-palette [data-agent-coord="{agent.dir_name}"]')
    row.wait_for(state="visible", timeout=20000)
    ctx.focus(row, hold=700)
    ctx.point_at(*point, hold=500)
    dropped = page.evaluate(
        _DRAG_TO_CANVAS_JS,
        {"source": row.element_handle(), "targetSelector": CANVAS_DROP_TARGET,
         "clientX": point[0], "clientY": point[1]},
    )
    assert dropped == "ok", f"the agent's drag failed: {dropped}"
    close_tools_palette(page, "agents")


def _open_chat(ctx: Ctx, agent):
    """Open *agent*'s chat from its badge, unless it is open, and return it."""
    page = ctx.page
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(agent.name)}"))
    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(agent.name)}")).first
    expect(opener).to_be_visible(timeout=30000)
    if panel.count() == 0:
        ctx.click(opener)
    expect(panel).to_be_visible(timeout=20000)
    return panel


def _send(ctx: Ctx, panel, message: str, *, shown: int | None = None) -> None:
    """Type *message* and send it. With *shown*, the clip shows its first
    *shown* characters typed and cuts to the whole of it."""
    field = panel.get_by_role("textbox", name="Message this agent")
    if shown is None:
        ctx.narrator.type_into(field, message)
    else:
        ctx.narrator.type_into(field, message[:shown])
        ctx.mark("cut", "start")
        field.fill(message)
        ctx.beat(300)
        ctx.mark("cut", "end")
    ctx.click(panel.get_by_role("button", name="Send", exact=True))


def _close_chat(ctx: Ctx, panel) -> None:
    ctx.click(panel.get_by_role("button", name="Close chat"))
    expect(ctx.page.locator(CHAT)).to_have_count(0, timeout=10000)
    leave_agent_badge(ctx.page)


def _plan_lands(ctx: Ctx, panel, nodes: int, *, before: int) -> None:
    """The plan lands with the agent's reply: the agent drags its *nodes*
    onto the canvas, which held *before* nodes, one after another, and the
    plan's card says what it built, with its Undo."""
    page = ctx.page
    card = panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first
    expect(card).to_be_visible(timeout=90000)
    expect(card).to_contain_text(f"{nodes} nodes", timeout=15000)
    expect(card.get_by_role("button", name="Undo")).to_be_visible(timeout=10000)
    ctx.focus(card, hold=2200)
    page.wait_for_function(
        "(n) => window.__curio_reactFlow.getNodes().length === n", arg=before + nodes, timeout=90000,
    )


def _change_lands(ctx: Ctx, panel) -> None:
    """The agent's change lands with its reply: its card says what it
    changed, with its Undo."""
    card = panel.get_by_role("group", name=re.compile(r"^Change: ")).first
    expect(card).to_be_visible(timeout=60000)
    expect(card.get_by_role("button", name="Undo")).to_be_visible(timeout=10000)
    ctx.focus(card, hold=1800)


def _by_title(saved: dict, title: str) -> dict:
    """The saved node a plan made under *title*, which it holds as its title,
    as the example's node does; a plan writes its goal as the title and then
    the plan row's intent."""
    found = [node for node in saved["nodes"] if node.get("title") == title]
    assert len(found) == 1, f"{len(found)} saved nodes are titled {title!r}"
    goal = str(found[0].get("goal") or "")
    assert goal.startswith(f"{title} "), f"the node titled {title!r} has the goal {goal!r}"
    return found[0]


def _solve(ctx: Ctx, agent, panel, token: str, project_id: str, titles: list[str]) -> dict[str, dict]:
    """Press Solve, and wait until each node of *titles* holds its content in
    the saved dataflow. Returns them, by title. A Solve that leaves one empty
    says what its progress list reads and how many calls reached the model."""
    page = ctx.page
    strip = page.get_by_role("group", name=agent.name).first
    solve = strip.get_by_role("button", name=re.compile(r"^(Solve|Retry \d+ \w+)$"))
    expect(solve).to_be_visible(timeout=30000)
    ctx.click(solve, hold=1500)
    ctx.mark("cut", "start")
    deadline = time.time() + SOLVE_S
    while True:
        saved = _saved(ctx, token, project_id)
        filled = {title: _by_title(saved, title) for title in titles}
        empty = sorted(title for title, node in filled.items() if not (node.get("content") or "").strip())
        if not empty:
            break
        if time.time() >= deadline:
            progress = panel.get_by_label("Plan node progress")
            said = progress.first.inner_text() if progress.count() else "no progress list"
            raise AssertionError(
                f"Solve left {empty} empty after {SOLVE_S:.0f} s. Its progress list reads {said!r}, "
                f"and the model was called {len(captured_agent_prompts(ctx.backend))} times."
            )
        page.wait_for_timeout(1000)
    ctx.mark("cut", "end")
    return filled


def _said_only_what_was_scripted(panel) -> None:
    """A call the scene scripted no reply for gets the scripted provider's
    fallback, which the chat would then show on camera."""
    expect(panel).not_to_contain_text(FALLBACK_REPLY)


def _shows_headers(page, titles: list[str]) -> None:
    """Each of *titles* is a node's title on the canvas, which its header
    shows, not only in the save: the name a plan gave the node, in place of
    its template's, which a node with no title of its own starts with."""
    headers = page.evaluate(
        "() => window.__curio_reactFlow.getNodes().map((n) => n.data && n.data.title)"
    )
    missing = [title for title in titles if title not in headers]
    assert not missing, f"no node on the canvas is headed {missing}"


def _wait_for_code(page, node_id: str, code: str, *, timeout: float = 60000) -> None:
    """Wait until the canvas node holds *code*, as an apply or Solve writes it."""
    page.wait_for_function(
        "([id, code]) => { const n = window.__curio_reactFlow.getNodes().find((x) => x.id === id);"
        " const held = n && n.data ? (n.data.code ?? n.data.defaultCode) : null;"
        " return typeof held === 'string' && held.trim() === code.trim(); }",
        arg=[node_id, code],
        timeout=timeout,
    )


def _same_code(written: str, expected: str) -> bool:
    """Whether *written* is *expected*: the same document for a spec, which a
    writer may lay out otherwise, and the same text for code."""
    try:
        return json.loads(written) == json.loads(expected)
    except ValueError:
        return written.strip() == expected.strip()


_ON_PANE_JS = """([x, y]) => {
    const hit = document.elementFromPoint(x, y);
    return !!hit && !!hit.closest('.react-flow__pane') && !hit.closest('.react-flow__node');
}"""


def _shift_drag_around(ctx: Ctx, node_ids: list[str]) -> None:
    """Select *node_ids* the way a person does: Shift, and a box dragged around
    them on the empty canvas, from the bottom right."""
    page = ctx.page
    frame_nodes(page, node_ids)
    boxes = [node_locator(page, node_id).bounding_box() for node_id in node_ids]
    left = min(b["x"] for b in boxes) - 12
    top = min(b["y"] for b in boxes) - 12
    right = max(b["x"] + b["width"] for b in boxes) + 12
    bottom = max(b["y"] + b["height"] for b in boxes) + 12
    assert page.evaluate(_ON_PANE_JS, [right, bottom]), f"({right}, {bottom}) is not on the empty canvas"
    ctx.point_at(right, bottom, hold=400)
    page.mouse.move(right, bottom)
    page.keyboard.down("Shift")
    page.mouse.down()
    page.mouse.move(left, top, steps=20)
    ctx.point_at(left, top, hold=300)
    page.mouse.up()
    page.keyboard.up("Shift")
    selected = page.evaluate("() => window.__curio_reactFlow.getNodes().filter((n) => n.selected).map((n) => n.id)")
    assert sorted(selected) == sorted(node_ids), f"the Shift-drag selected {selected}, not {node_ids}"


def _select(ctx: Ctx, node_id: str) -> None:
    """Click a node's header strip, so it is the canvas's selection. The point
    is the one ``test_canvas_delete_key_e2e`` clicks at zoom 1, scaled to the
    canvas's zoom."""
    page = ctx.page
    node = node_locator(page, node_id)
    box = node.bounding_box()
    assert box, f"node {node_id} has no layout box"
    zoom = page.evaluate("() => window.__curio_reactFlow.getViewport().zoom")
    at = {"x": 300 * zoom, "y": max(4.0, 8 * zoom)}
    ctx.point_at(box["x"] + at["x"], box["y"] + at["y"], hold=400)
    node.click(position=at)
    page.wait_for_function(
        "id => !!document.querySelector(`.react-flow__node[data-id='${id}'].selected`)", arg=node_id, timeout=10000,
    )
    assert node.get_by_role("textbox", name="Node title").count() == 0, (
        f"the click on node {node_id}'s header opened its title for editing rather than selecting it"
    )


#: A point on connection *id* that a click lands on: along its curve, where
#: nothing else covers it.
_EDGE_POINT_JS = """(id) => {
    const group = document.querySelector(`.react-flow__edge[data-testid="rf__edge-${id}"]`);
    const path = group && (group.querySelector('.react-flow__edge-interaction') || group.querySelector('path'));
    if (!path || !path.getPointAtLength) return null;
    const total = path.getTotalLength();
    const svg = path.ownerSVGElement;
    const ctm = path.getScreenCTM();
    if (!total || !svg || !ctm) return null;
    for (const f of [0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65, 0.3, 0.7, 0.25, 0.75]) {
        const at = path.getPointAtLength(total * f);
        const pt = svg.createSVGPoint();
        pt.x = at.x;
        pt.y = at.y;
        const screen = pt.matrixTransform(ctm);
        const hit = document.elementFromPoint(screen.x, screen.y);
        if (hit && hit.closest('.react-flow__edge') === group) return [screen.x, screen.y];
    }
    return null;
}"""


def _edges(page) -> list[dict]:
    return page.evaluate(
        "() => window.__curio_reactFlow.getEdges().map((e) => "
        "({id: e.id, source: e.source, target: e.target, targetHandle: e.targetHandle}))"
    )


def _delete_edge(ctx: Ctx, source: str, target: str) -> None:
    """Click the connection from *source* to *target* and press Delete."""
    page = ctx.page
    found = [edge for edge in _edges(page) if edge["source"] == source and edge["target"] == target]
    assert len(found) == 1, f"{len(found)} connections run from {source} to {target}"
    edge_id = found[0]["id"]
    point = page.evaluate(_EDGE_POINT_JS, edge_id)
    assert point, f"no point of the connection {edge_id} is in view to click"
    ctx.point_at(*point, hold=500)
    page.mouse.click(*point)
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !window.__curio_reactFlow.getEdges().some((e) => e.id === id)", arg=edge_id, timeout=10000,
    )


def _connect(ctx: Ctx, source: str, target: str, *, target_handle: str = "in") -> None:
    """Draw a connection from *source*'s output to *target*'s input, the
    pointer shown going from one to the other."""
    page = ctx.page
    ctx.point_at(*_handle_point(page, source, "out"), hold=400)
    connect_nodes(page, source, target, target_handle=target_handle)
    ctx.point_at(*_handle_point(page, target, target_handle), hold=500)


def _handle_point(page, node_id: str, handle: str) -> tuple[float, float]:
    box = node_locator(page, node_id).locator(f'.react-flow__handle[data-handleid="{handle}"]').first.bounding_box()
    if not box:
        return _centre(page, node_id)
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


_SCENARIO_CARDS_JS = """(root) => Array.from(
    document.querySelectorAll(root + ' [data-testid^="scenario-card-"]')
).map((card) => card.getAttribute('data-testid').slice('scenario-card-'.length))"""


#: The Scenario Catalog drawer, open.
_OPEN_SCENARIO_DRAWER = f'{SCENARIO_DRAWER}[aria-hidden="false"]'


def _define_panel(page):
    """Define scenario, open beside the canvas, once the Scenario Catalog
    drawer that opened it, if one did, has gone."""
    panel = page.get_by_test_id("scenario-define-panel")
    expect(panel).to_be_visible(timeout=10000)
    wait_for_drawer_closed(page, SCENARIO_DRAWER)
    return panel


def _at_step(panel, step: str) -> None:
    expect(panel.get_by_role("listitem").filter(has_text=step)).to_have_attribute("aria-current", "step")


def _lists(panel, part: str, node_ids: list[str]) -> None:
    """One of Define scenario's lists holds the nodes *node_ids*, whatever
    their order: the scenario's own nodes ("nodes"), its shared "context" or
    its shared "outcomes"."""
    rows = panel.get_by_test_id(f"scenario-define-{part}").locator("[data-node]")
    try:
        expect(rows).to_have_count(len(node_ids), timeout=10000)
    except AssertionError:
        pass  # the check below says what the list holds
    listed = [row.get_attribute("data-node") for row in rows.all()]
    assert sorted(listed) == sorted(node_ids), f"Define scenario's {part} lists {listed}, not {node_ids}"


#: True once every node *ids* names lies whole between the tools rail and
#: Define scenario's panel, under what covers the top of the canvas.
_BESIDE_THE_PANEL_JS = """([ids, panel]) => {
    const edge = document.querySelector(panel).getBoundingClientRect().left;
    const rail = document.getElementById('tools-palette-dock').getBoundingClientRect().right;
    return ids.every((id) => {
        const el = document.querySelector(`.react-flow__node[data-id="${id}"]`);
        const box = el && el.getBoundingClientRect();
        return !!box && box.width > 0 && box.left > rail && box.right < edge;
    });
}"""

#: Sets the view so the nodes *ids* name fill, at most at 100% zoom, the
#: canvas between the tools rail and Define scenario's panel, under the top
#: bar and the dataflow's title. The canvas's own fit leaves no room for the
#: panel, which sits over the canvas's right.
_FRAME_BESIDE_THE_PANEL_JS = """([ids, panel, pad]) => {
    const flow = window.__curio_reactFlow;
    const nodes = flow.getNodes().filter((n) => ids.includes(n.id));
    const pane = document.querySelector('.react-flow').getBoundingClientRect();
    const tops = [...document.querySelectorAll(
        '[data-curio-menu-bar], [data-curio-canvas-title], [data-curio-canvas-title] [data-curio-category-chips]',
    )].map((el) => el.getBoundingClientRect().bottom);
    const area = {
        left: document.getElementById('tools-palette-dock').getBoundingClientRect().right + pad,
        right: document.querySelector(panel).getBoundingClientRect().left - pad,
        top: Math.max(pane.top, ...tops) + pad,
        bottom: pane.bottom - pad,
    };
    const x0 = Math.min(...nodes.map((n) => n.position.x));
    const y0 = Math.min(...nodes.map((n) => n.position.y));
    const x1 = Math.max(...nodes.map((n) => n.position.x + (n.width || 0)));
    const y1 = Math.max(...nodes.map((n) => n.position.y + (n.height || 0)));
    const zoom = Math.min(1, (area.right - area.left) / (x1 - x0), (area.bottom - area.top) / (y1 - y0));
    flow.setViewport({
        x: area.left - pane.left + (area.right - area.left - (x1 - x0) * zoom) / 2 - x0 * zoom,
        y: area.top - pane.top + (area.bottom - area.top - (y1 - y0) * zoom) / 2 - y0 * zoom,
        zoom,
    });
    return nodes.length;
}"""

_PANEL = '[data-testid="scenario-define-panel"]'


def _frame_beside_the_panel(page, node_ids: list[str]) -> None:
    """Show *node_ids* whole beside Define scenario's panel, the pointer
    parked first."""
    park_pointer(page)
    framed = page.evaluate(_FRAME_BESIDE_THE_PANEL_JS, [node_ids, _PANEL, 48])
    assert framed == len(node_ids), f"only {framed} of {node_ids} are on the canvas"
    settled_viewport(page)
    page.wait_for_function(_BESIDE_THE_PANEL_JS, arg=[node_ids, _PANEL], timeout=10000)


def _name_and_set(ctx: Ctx, panel, scenario: dict, *, new_set: str | None = None) -> None:
    """Name & set: *scenario*'s name typed and its color, and, with *new_set*,
    the name of the scenario set it starts."""
    _at_step(panel, "Name & set")
    field = panel.get_by_test_id("scenario-define-name")
    field.fill("")
    ctx.narrator.type_into(field, scenario["name"])
    panel.get_by_test_id("scenario-define-color").fill(scenario["color"])
    if new_set is not None:
        # The dataflow has no set yet, so the scenario starts one, named
        # after the dataflow until it is named.
        named = panel.get_by_test_id("scenario-define-set-name")
        expect(named).to_be_visible(timeout=10000)
        named.fill("")
        ctx.narrator.type_into(named, new_set)
    ctx.beat(700)


def _save_define(ctx: Ctx, panel) -> None:
    ctx.click(panel.get_by_test_id("scenario-define-save"))
    expect(panel).to_be_hidden(timeout=10000)


def _describe(page, scenario_id: str, description: str) -> None:
    """Write a scenario's description in its details, which keep it once the
    field is left."""
    details = open_scenario_details(page, scenario_id)
    field = details.get_by_label("Scenario description")
    field.fill(description)
    field.blur()
    expect(page.locator(f'{_OPEN_SCENARIO_DRAWER} [data-testid="scenario-card-{scenario_id}"]')).to_contain_text(
        description, timeout=10000,
    )
    close_scenario_details(page)


def _scenario_as_kept(scenario: dict) -> dict:
    """What a saved scenario says: its name, color and description, and its
    own nodes, shared context and shared outcomes, each in any order."""
    return {
        "name": scenario["name"], "color": scenario["color"], "description": scenario.get("description"),
        **{part: sorted(scenario.get(part) or []) for part in ("nodes", "context", "outcomes")},
    }


def _reads(flow: dict, members: list[str], boxed: set[str]) -> set[str]:
    """The nodes *members* read in the dataflow *flow*, at any depth: every
    node upstream of one through the connections a run follows (no
    Interaction link), the walk going past no node of *boxed*, the scenarios'
    own nodes, as Curio's own finding of a shared context does."""
    up: dict[str, list[str]] = {}
    for edge in flow["edges"]:
        if edge.get("type") == "Interaction" or (edge.get("sourceHandle"), edge.get("targetHandle")) == ("in/out", "in/out"):
            continue
        up.setdefault(edge["target"], []).append(edge["source"])
    seen: set[str] = set()
    frontier = list(members)
    while frontier:
        for source in up.get(frontier.pop(), []):
            if source not in boxed and source not in seen:
                seen.add(source)
                frontier.append(source)
    return seen


def _scenario_as_built(entry: dict, ours: dict[str, str], present: set[str], *, reads: set[str] | None = None) -> dict:
    """The example's scenario *entry* as far as a scene has built it, as
    :func:`_scenario_as_kept` reads a saved one: each node by the id the scene
    gave it (*ours*, else the example's own), the nodes the scene's dataflow
    holds (*present*) alone, and with *reads*, of its shared context only the
    nodes its built nodes read."""
    def here(ids: list[str], keep: set[str] | None = None) -> list[str]:
        mapped = (ours.get(n, n) for n in ids)
        return sorted(node_id for node_id in mapped if node_id in present and (keep is None or node_id in keep))

    return {
        "name": entry["name"], "color": entry["color"], "description": entry.get("description"),
        "nodes": here(entry.get("nodes") or []),
        "context": here(entry.get("context") or [], reads),
        "outcomes": here(entry.get("outcomes") or []),
    }


def _as_curio_finds(ctx: Ctx, scenario_id: str, built: dict) -> None:
    """Edit scenario on *scenario_id*'s card, its own nodes as they are: its
    shared context and outcomes found again from them by Curio, which must be
    what *built* (``_scenario_as_built``) lists, then Save. Next alone keeps
    the lists the scenario was saved with while its own nodes stay the same,
    so the finding is asked for anew."""
    page = ctx.page
    ctx.focus(page.get_by_role("button", name="Scenario Catalog", exact=True), hold=400)
    open_in_project_tab(page)
    ctx.click(scenario_card_button(page, scenario_id, "Edit scenario"))
    panel = _define_panel(page)
    _at_step(panel, "Scenario-specific nodes")
    _lists(panel, "nodes", built["nodes"])
    ctx.click(panel.get_by_role("button", name="Next: shared context & outcomes"))
    _at_step(panel, "Shared context & outcomes")
    ctx.click(panel.get_by_role("button", name="Start again from what Curio found"))
    _lists(panel, "context", built["context"])
    _lists(panel, "outcomes", built["outcomes"])
    _save_define(ctx, panel)


def _frame_all(ctx: Ctx) -> None:
    frame_nodes(ctx.page, _node_ids(ctx.page))
    park_pointer(ctx.page)


def _play(ctx: Ctx, node_id: str) -> None:
    ctx.focus(node_locator(ctx.page, node_id).locator("svg.fa-circle-play"), hold=400)
    play_node(ctx.page, node_id)


# ---------------------------------------------------------------------------
# The scenes
# ---------------------------------------------------------------------------

@walkthrough(
    slug="crown-heights-build-first-version",
    title="Crown Heights: an agent builds a first version",
    premise="From a short prompt, the Dataflow Builder plans the first version of "
            "the Crown Heights shade study: the buildings, the block and the streets, "
            "the sun's steps, the open ground, and one scenario's buildings for the "
            "GPU with its three GPU steps. The plan lands with its reply, the agent "
            "dragging each node onto the canvas, and Solve writes their code.",
    tests=["test_frontend/test_example_reconstruction_e2e.py",
           "test_frontend/test_agent_scenarios_e2e.py"],
    example=EXAMPLE,
    dataflow_name=NAME,
    start=_empty,
    needs_examples=True,
)
def crown_heights_first_version(ctx: Ctx) -> None:
    page = ctx.page
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=60000)
    token, project_id = _session(page)
    builder = _agent("agent.curio.dataflow-builder")
    use_scripted_llm(ctx.backend, token)
    # The Crown Heights dataset, added as the Data Catalog adds one.
    api_json(
        f"{ctx.backend}/api/dataflows/{project_id}/datasets/install", token,
        method="POST", payload={"datasetId": DATASET},
    )
    _install(ctx, token, project_id, builder)

    spec = _example()
    refs = {key: nid(key) for key in FIRST_VERSION}
    table = (
        {"ref": "check-table", "nodeType": TABLE_TYPE, "title": TABLE_TITLE, "intent": TABLE_GOAL},
        [{"from": "ground", "to": "check-table", "toHandle": "in"}],
    )
    plan = _plan(
        spec, refs,
        "Compare the shade on Block 1259 without and with the tower proposed at 1550 Bedford "
        "Avenue: first the data, the sun's steps, the open ground and one scenario's GPU steps.",
        extra=(table,),
    )
    reply = _plan_reply(
        "Here is a first version. Three loaders read the buildings, Block 1259 and the "
        "streets from the Crown Heights dataset. Two nodes list the sun's steps, on the "
        "day you pick and on every day of 2027. The open ground is cut into 3 m cells, "
        "and the buildings are drawn into a heights grid that three GPU steps march the "
        "sun's rays across. A table shows the grid's cells, to check them.",
        plan,
    )
    script_agent_replies(ctx.backend, reply, FIRST_TITLE, by_intent=_solve_replies(spec, refs))
    _reload(page)

    ctx.mark("clip", "start")
    _drop_agent(ctx, builder, _pane_centre(page))
    panel = _open_chat(ctx, builder)
    before = len(_node_ids(page))
    _send(ctx, panel, FIRST_PROMPT)
    _plan_lands(ctx, panel, len(plan["nodes"]), before=before)
    ctx.capture("plan-landed", fit_reactflow=False)
    ctx.beat(1200)

    titles = [spec_node["title"] for spec_node in (_nodes(spec)[node_id] for node_id in refs.values())]
    solved = _solve(ctx, builder, panel, token, project_id, titles)
    # Solve's writes reach the saved dataflow before the canvas: the clip
    # ends on code, so it waits for one of the last.
    tower = solved[_nodes(spec)[nid("base-tower")]["title"]]
    _wait_for_code(page, tower["id"], tower["content"])
    _said_only_what_was_scripted(panel)
    _close_chat(ctx, panel)
    _frame_all(ctx)
    ctx.beat(2500)
    ctx.mark("clip", "end")

    # Every planned node holds the example's code or spec, the Day widget
    # included, and the connections are the example's.
    nodes = _nodes(spec)
    wrong = [
        title for (title, node), node_id in zip(solved.items(), refs.values())
        if not _same_code(node.get("content") or "", nodes[node_id]["content"])
    ]
    assert not wrong, f"Solve wrote other code than the example's for {wrong}"
    saved = _saved(ctx, token, project_id)
    # Each planned node, found by the title it holds (_by_title), is named as
    # the example names it, which its header shows on the canvas too.
    by_ref = {ref: _by_title(saved, nodes[node_id]["title"])["id"] for ref, node_id in refs.items()}
    by_ref["check-table"] = _by_title(saved, TABLE_TITLE)["id"]
    _shows_headers(page, [*titles, TABLE_TITLE])
    days = (_by_title(saved, nodes[nid("steps")]["title"]).get("metadata") or {}).get("widgets") or []
    assert [w.get("name") for w in days] == ["day"], f"the day's sun steps hold the widgets {days}"
    made = sorted((e["source"], e["target"], e.get("targetHandle") or "in") for e in saved["edges"])
    planned = sorted(
        (by_ref.get(edge["from"], edge["from"]), by_ref[edge["to"]], edge["toHandle"]) for edge in plan["edges"]
    )
    assert made == planned, f"the canvas holds the connections {made}, not the plan's {planned}"


@walkthrough(
    slug="crown-heights-build-scenarios",
    title="Crown Heights: two scenarios by hand",
    premise="The first version's GPU chain is defined as a scenario, in a scenario set of its "
            "own, with the shared context Curio finds, and duplicated as a second; the two "
            "are named without and with the proposed building. A Map Editor node goes into "
            "the second between the buildings and its chain, and the agent's check table "
            "comes out.",
    tests=["test_frontend/test_scenario_sets_define_e2e.py",
           "test_frontend/test_scenarios_canvas_e2e.py",
           "test_frontend/test_scenarios_in_project_e2e.py"],
    example=EXAMPLE,
    dataflow_name=NAME,
    start=_first_version,
    needs_examples=True,
)
def crown_heights_scenarios(ctx: Ctx) -> None:
    page = ctx.page
    token, project_id = _session(page)
    chain = [nid(key) for key in TO_THE_GPU]
    example = _example()["dataflow"]
    without, with_ = example["scenarios"]
    [scenario_set] = example["scenarioSets"]
    # The shared context Curio finds for the chain: the nodes of the
    # example's that the chain reads. The streets and the map extent are read
    # only by the scenarios' maps, which this scene does not build.
    reads = _reads(_first_version(_example())["dataflow"], chain, set(chain))
    found = [node_id for node_id in without["context"] if node_id in reads]
    frame_nodes(page, [nid("ground"), *chain, TABLE])

    ctx.mark("clip", "start")
    # The chain, defined as the first scenario: its own nodes; the shared
    # context Curio finds, and no outcome yet; then its name, its color and a
    # scenario set of its own.
    _shift_drag_around(ctx, chain)
    ctx.click(page.get_by_role("button", name="View menu"))
    ctx.click(page.get_by_role("button", name="Define scenario", exact=True))
    panel = _define_panel(page)
    _at_step(panel, "Scenario-specific nodes")
    _lists(panel, "nodes", chain)
    ctx.click(panel.get_by_role("button", name="Next: shared context & outcomes"))
    _at_step(panel, "Shared context & outcomes")
    _lists(panel, "context", found)
    _lists(panel, "outcomes", [])
    ctx.beat(1200)
    ctx.click(panel.get_by_role("button", name="Next: name & set"))
    _name_and_set(ctx, panel, without, new_set=scenario_set["name"])
    _save_define(ctx, panel)

    # Duplicated, from its card: the copy, below the chain, reads what the
    # chain reads, in the same set with the same shared context, and Define
    # scenario opens on it at Name & set.
    ctx.focus(page.get_by_role("button", name="Scenario Catalog", exact=True), hold=400)
    open_in_project_tab(page)
    cards = page.evaluate(_SCENARIO_CARDS_JS, _OPEN_SCENARIO_DRAWER)
    assert len(cards) == 1, f"the In project tab lists {cards}, not one scenario"
    [first] = cards
    ctx.click(scenario_card_button(page, first, "Duplicate scenario"))
    panel = _define_panel(page)
    _at_step(panel, "Name & set")
    ctx.beat(800)
    # It is named the same way; the clip cuts to it named.
    ctx.mark("cut", "start")
    _name_and_set(ctx, panel, with_)
    _save_define(ctx, panel)
    ctx.mark("cut", "end")
    copies = {
        node["copiedFrom"][-1]: node["id"]
        for node in page.evaluate(
            "() => window.__curio_reactFlow.getNodes().map((n) => ({id: n.id, copiedFrom: n.data && n.data.copiedFrom}))"
        )
        if node["copiedFrom"]
    }
    assert sorted(copies) == sorted(chain), f"the copies name {sorted(copies)} as their originals"

    # A Map Editor node in the second scenario, between the buildings and the
    # copy of the chain, where the proposed building will be added. The copy's
    # two connections come out first, while no node covers them, the lower one
    # first: then the other never moves up a circle, and the copy's code still
    # reads input_0 and input_1 as written.
    tower = copies[nid("base-tower")]
    # Define scenario's toast sits where the copy's connections arrive.
    dismiss_toasts(page)
    frame_nodes(page, [nid("buildings"), nid("ground"), tower])
    _delete_edge(ctx, nid("ground"), tower)
    _delete_edge(ctx, nid("buildings"), tower)
    frame_nodes(page, [nid("buildings"), tower, copies[nid("base-year-rays")]])
    ctx.focus(page.locator('#builtin-palette button[data-tooltip="Open built-in palette"]'), hold=400)
    open_tools_palette(page, "builtin")
    tile = page.locator("#tile-edit-features")
    ctx.focus(tile, hold=600)
    pane = page.locator(CANVAS_DROP_TARGET).bounding_box()
    # A dropped node's corner lands where it is dropped: here, a column left
    # of the copy of the buildings for the GPU, which the chain's shift left
    # free.
    beside = node_locator(page, tower).bounding_box()
    zoom = page.evaluate("() => window.__curio_reactFlow.getViewport().zoom")
    drop = (beside["x"] - CHAIN_SHIFT * zoom, beside["y"])
    ctx.point_at(*drop, hold=400)
    editor = drag_to_canvas(page, tile, at=(drop[0] - pane["x"], drop[1] - pane["y"]))
    close_tools_palette(page, "builtin")
    # The copy reads the Map Editor where it read the buildings, on its first
    # circle, with the ground on its second.
    frame_nodes(page, [nid("buildings"), nid("ground"), editor, tower])
    _connect(ctx, nid("buildings"), editor)
    _connect(ctx, editor, tower, target_handle="in")
    _connect(ctx, nid("ground"), tower, target_handle="in_1")

    # The Map Editor joins the second scenario: Edit scenario on its card, the
    # node selected on the canvas and added. Its shared context is found anew
    # from its nodes: what the first scenario's is.
    ctx.focus(page.get_by_role("button", name="Scenario Catalog", exact=True), hold=400)
    open_in_project_tab(page)
    cards = page.evaluate(_SCENARIO_CARDS_JS, _OPEN_SCENARIO_DRAWER)
    assert len(cards) == 2 and cards[0] == first, f"the In project tab lists {cards}"
    second = cards[1]
    ctx.click(scenario_card_button(page, second, "Edit scenario"))
    panel = _define_panel(page)
    _at_step(panel, "Scenario-specific nodes")
    _lists(panel, "nodes", list(copies.values()))
    _frame_beside_the_panel(page, [editor, tower])
    _select(ctx, editor)
    ctx.click(panel.get_by_test_id("scenario-define-nodes").get_by_role("button", name="+ Add selected node"))
    _lists(panel, "nodes", [editor, *copies.values()])
    ctx.click(panel.get_by_role("button", name="Next: shared context & outcomes"))
    _at_step(panel, "Shared context & outcomes")
    _lists(panel, "context", found)
    _lists(panel, "outcomes", [])
    ctx.beat(1200)
    _save_define(ctx, panel)

    # The check table goes: the grid is right.
    frame_nodes(page, [nid("ground"), TABLE])
    _select(ctx, TABLE)
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)", arg=TABLE, timeout=10000,
    )
    _frame_all(ctx)
    ctx.capture("two-scenarios", fit_reactflow=False)
    ctx.beat(2500)
    ctx.mark("clip", "end")

    # Each scenario's description, as the example words it, in its details.
    open_in_project_tab(page)
    for scenario_id, entry in ((first, without), (second, with_)):
        _describe(page, scenario_id, entry["description"])
    close_scenario_drawer(page)

    save_dataflow(page)
    saved = _saved(ctx, token, project_id)
    by_id = {node["id"]: node for node in saved["nodes"]}
    assert TABLE not in by_id, "the check table is still in the saved dataflow"
    # Each scenario is the example's own as far as this scene builds it: its
    # name, color and description; its nodes, the second's by the ids its
    # copies and its Map Editor have here; of its shared context, the nodes
    # its nodes read; and its outcomes, which no node of the first version is.
    ours = {nid("add-building"): editor, **{nid(key.removeprefix("base-")): copies[nid(key)] for key in TO_THE_GPU}}
    scenarios = saved.get("scenarios") or []
    boxed = {node_id for s in scenarios for node_id in s["nodes"]}
    kept = [_scenario_as_kept(s) for s in scenarios]
    built = []
    for entry in (without, with_):
        members = [n for n in (ours.get(m, m) for m in entry["nodes"]) if n in by_id]
        built.append(_scenario_as_built(entry, ours, set(by_id), reads=_reads(saved, members, boxed)))
    assert kept == built, f"the scenarios saved are {kept}, not the example's {built}"
    # Both in the one scenario set, named as the example's.
    sets = {s["id"]: s["name"] for s in saved.get("scenarioSets") or []}
    assert list(sets.values()) == [scenario_set["name"]], f"the scenario sets saved are {sets}"
    assert {s["set"] for s in scenarios} == set(sets), [(s["name"], s["set"]) for s in scenarios]
    for original, copied in copies.items():
        assert (by_id[copied].get("metadata") or {}).get("copiedFrom") == [original], by_id[copied]
    wiring = {(e["source"], e["target"], e.get("targetHandle") or "in") for e in saved["edges"]}
    assert (nid("buildings"), editor, "in") in wiring, "the buildings do not feed the Map Editor"
    # The copy reads what the example's second scenario reads, on the same
    # circles, with its code as the original's.
    expected = sorted(
        (ours.get(e["source"], e["source"]), e.get("targetHandle") or "in")
        for e in _example()["dataflow"]["edges"] if e["target"] == nid("tower")
    )
    made = sorted((source, handle) for source, target, handle in wiring if target == tower)
    assert made == expected, f"the copy's buildings for the GPU read {made}, not the example's {expected}"
    assert _same_code(by_id[tower].get("content") or "", _nodes(_example())[nid("tower")]["content"]), (
        f"the copy's code changed as its connections did: {by_id[tower].get('content')!r}"
    )


@walkthrough(
    slug="crown-heights-build-map-editor",
    title="Crown Heights: an agent adds the proposed tower",
    premise="The Node Builder, dropped on the Map Editor node, adds the tower proposed "
            "at 1550 Bedford Avenue in two parts: its base to 135 ft, 30 ft back from "
            "Eastern Parkway, and its upper floors to 185 ft. Its change lands with its "
            "reply; run, the map with the proposed building shows it.",
    tests=["test_frontend/test_map_edits_agent_e2e.py",
           "test_frontend/test_crown_heights_dashboard_e2e.py"],
    example=EXAMPLE,
    dataflow_name=NAME,
    start=_without_edits,
    needs_examples=True,
)
def crown_heights_map_editor(ctx: Ctx) -> None:
    from ..test_map_edits_e2e import _changed, _map_pixels, _wait_for_map_drawn, _wait_for_redraw

    page = ctx.page
    require_webgpu(page)
    token, project_id = _session(page)
    node_builder = _agent("agent.curio.node-builder")
    editor, with_map = nid("add-building"), nid("shadow-map")
    edits = _nodes(_example())[editor]["content"]
    use_scripted_llm(ctx.backend, token)
    _install(ctx, token, project_id, node_builder)
    script_agent_replies(
        ctx.backend,
        _write_reply(
            "I add the proposed building on the vacant lot in two parts: its base to 135 ft "
            "(41.1 m), 30 ft back from Eastern Parkway, and its upper floors to 185 ft "
            "(56.4 m), set back above the base.",
            editor, edits,
        ),
        "The two parts are in the Map Editor.",
        TOWER_TITLE,
    )
    _reload(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    # The maps draw once the dataflow has run; the clip starts after.
    run_all_and_wait(page, timeout_ms=RUN_ALL_MS)
    frame_nodes(page, [editor, with_map])
    _wait_for_map_drawn(page, with_map, "the Run All before the tower")
    before = _map_pixels(page, with_map)
    keep_drawing(page, f"#autk-grammar-map-{with_map}")
    # The Map Editor alone, where the agent is dropped, clear of the palette.
    frame_nodes(page, [editor])

    ctx.mark("clip", "start")
    _drop_agent(ctx, node_builder, _centre(page, editor))
    panel = _open_chat(ctx, node_builder)
    _send(ctx, panel, TOWER_PROMPT, shown=PROMPT_SHOWN)
    _change_lands(ctx, panel)
    _wait_for_code(page, editor, edits)
    _said_only_what_was_scripted(panel)
    _close_chat(ctx, panel)
    frame_nodes(page, [editor, with_map])
    _play(ctx, editor)
    # Played, the Map Editor runs the steps below it too: the map draws the
    # tower, then its shadow once the GPU steps have run again. The clip cuts
    # to the end.
    ctx.mark("cut", "start")
    wait_for_node_done(page, editor, node_type=EDIT_TYPE)
    expect(node_locator(page, editor).locator('li[data-edit-op="add"]')).to_have_count(2, timeout=30000)
    _wait_for_redraw(page, with_map, "the tower was added")
    _wait_for_no_node_running(page, timeout_ms=RUN_ALL_MS)
    _wait_for_map_drawn(page, with_map, "the steps below the Map Editor ran again")
    ctx.mark("cut", "end")
    ctx.beat(2500)
    ctx.mark("clip", "end")

    moved = _changed(before, _map_pixels(page, with_map))
    assert moved > 0, "the map with the proposed building drew again the same once the tower was added"
    ctx.capture_node("map-with-the-tower", with_map)
    save_dataflow(page)
    # The node's history, which the server keeps, holds the agent's change,
    # named after it, as an edit.
    history = api_json(f"{ctx.backend}/api/projects/{project_id}/history/nodes/{editor}", token)["entries"]
    named = [entry for entry in history if entry.get("label") == node_builder.name]
    assert named, f"the Map Editor's history has no entry named {node_builder.name!r}: {history}"
    assert _same_code(str(named[-1].get("code") or ""), edits), named[-1]
    assert named[-1].get("kind") == "edit", named[-1]


@walkthrough(
    slug="crown-heights-build-plot-and-map",
    title="Crown Heights: an agent creates a plot and a map",
    premise="Asked for the block's share in shadow through the day and the shade the "
            "tower adds, the Dataflow Builder plans a Vega-Lite plot and an Autark map "
            "wired to the scenarios' results. The plan lands with its reply, Solve "
            "writes their specs, each scenario takes them among its shared outcomes, "
            "and both draw.",
    tests=["test_frontend/test_crown_heights_dashboard_e2e.py",
           "test_frontend/test_scenarios_in_project_e2e.py"],
    example=EXAMPLE,
    dataflow_name=NAME,
    start=_without_plot_and_map,
    needs_examples=True,
)
def crown_heights_plot_and_map(ctx: Ctx) -> None:
    from ..test_crown_heights_dashboard_e2e import _colors, _plot_drew
    from ..test_map_edits_e2e import _wait_for_map_drawn

    page = ctx.page
    require_webgpu(page)
    token, project_id = _session(page)
    builder = _agent("agent.curio.dataflow-builder")
    spec = _example()
    refs = {key: nid(key) for key in PLOT_AND_MAP}
    plan = _plan(spec, refs, "Plot the block's share in shadow through the day and map the shade the tower adds.")
    use_scripted_llm(ctx.backend, token)
    _install(ctx, token, project_id, builder, target={"kind": "canvas"})
    script_agent_replies(
        ctx.backend,
        _plan_reply(
            "A Vega-Lite plot draws the share of Block 1259's open ground in shadow at each "
            "step of the day, a line per scenario in its color, over the day's window. An "
            "Autark map draws the shade the tower adds, over the buildings, the block and "
            "the streets.",
            plan,
        ),
        PLOT_AND_MAP_TITLE,
        by_intent=_solve_replies(spec, refs),
    )
    _reload(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    # The plot and the map draw the scenarios' results, so the dataflow runs
    # first; the clip starts after.
    run_all_and_wait(page, timeout_ms=RUN_ALL_MS)
    _frame_all(ctx)

    ctx.mark("clip", "start")
    panel = _open_chat(ctx, builder)
    before = len(_node_ids(page))
    _send(ctx, panel, PLOT_AND_MAP_PROMPT, shown=PROMPT_SHOWN)
    _plan_lands(ctx, panel, len(plan["nodes"]), before=before)
    nodes = _nodes(spec)
    titles = [nodes[node_id]["title"] for node_id in refs.values()]
    written = _solve(ctx, builder, panel, token, project_id, titles)
    _said_only_what_was_scripted(panel)
    _close_chat(ctx, panel)
    plot, added = (written[nodes[nid(key)]["title"]]["id"] for key in PLOT_AND_MAP)
    for title in titles:
        _wait_for_code(page, written[title]["id"], written[title]["content"])
    # Each scenario takes the plot and the map of the shade the tower adds
    # among its shared outcomes, as the example has them: Edit scenario on its
    # card, and what Curio finds from its nodes, confirmed. Neither is a
    # scenario's own map, so no scenario's own nodes or context change. The
    # clip cuts the two edits.
    ours = {nid(key): new for key, new in zip(PLOT_AND_MAP, (plot, added))}
    present = set(_node_ids(page))
    ctx.mark("cut", "start")
    for entry in spec["dataflow"]["scenarios"]:
        _as_curio_finds(ctx, entry["id"], _scenario_as_built(entry, ours, present))
    ctx.mark("cut", "end")
    frame_nodes(page, [plot, added])
    # Each draws its spec, once played, from the results its inputs already
    # hold. The clip cuts each draw's wait.
    _play(ctx, plot)
    ctx.mark("cut", "start")
    _plot_drew(page, plot, _colors())
    ctx.mark("cut", "end")
    _play(ctx, added)
    ctx.mark("cut", "start")
    _wait_for_map_drawn(page, added, "Solve wrote its spec")
    ctx.mark("cut", "end")
    ctx.beat(2500)
    ctx.mark("clip", "end")

    ctx.capture_node("plot", plot)
    ctx.capture_node("map", added)
    wrong = [
        title for title, node in written.items()
        if not _same_code(node.get("content") or "", nodes[nid(PLOT_AND_MAP[titles.index(title)])]["content"])
    ]
    assert not wrong, f"Solve wrote other specs than the example's for {wrong}"
    _shows_headers(page, titles)
    save_dataflow(page)
    saved = _saved(ctx, token, project_id)
    # Each scenario is the example's own, every node of it built by now: the
    # plot and the map among its shared outcomes by the ids they got here.
    present = {node["id"] for node in saved["nodes"]}
    scenarios = saved.get("scenarios") or []
    kept = [_scenario_as_kept(s) for s in scenarios]
    built = [_scenario_as_built(entry, ours, present) for entry in spec["dataflow"]["scenarios"]]
    assert kept == built, f"the scenarios saved are {kept}, not the example's {built}"
    sets = {s["id"]: s["name"] for s in saved.get("scenarioSets") or []}
    assert list(sets.values()) == [s["name"] for s in spec["dataflow"]["scenarioSets"]], sets
    assert {s["set"] for s in scenarios} == set(sets), [(s["name"], s["set"]) for s in scenarios]
    made = {new: nid(key) for key, new in zip(PLOT_AND_MAP, (plot, added))}
    wired = sorted(
        (e["source"], made[e["target"]], e.get("targetHandle") or "in")
        for e in saved["edges"] if e["target"] in made and e.get("type") != "Interaction"
    )
    example = sorted(
        (e["source"], e["target"], e["targetHandle"])
        for e in spec["dataflow"]["edges"] if e["target"] in made.values() and e.get("type") != "Interaction"
    )
    assert wired == example, f"the plot and the map are wired {wired}, not as the example's {example}"


@walkthrough(
    slug="crown-heights-build-dashboard",
    title="Crown Heights: the dashboard",
    premise="Run and saved, the Crown Heights study opens as its dashboard: the three "
            "maps, the two plots, the months' table and the Day radio. On the winter "
            "solstice the tower shades the block; picked, the summer solstice redraws "
            "the maps and the day's plot.",
    tests=["test_frontend/test_crown_heights_dashboard_e2e.py"],
    example=EXAMPLE,
    dataflow_name=NAME,
    needs_examples=True,
    # The dashboard page lays its tiles out itself.
    fit_reactflow=False,
)
def crown_heights_dashboard(ctx: Ctx) -> None:
    from utk_curio.backend.tests._support.crown_heights import SUMMER, WINTER
    from ..test_crown_heights_dashboard_e2e import (
        _PLOT_PIXELS_JS,
        _colors,
        _day,
        _ids,
        _keep_drawing_maps,
        _maps_redrew,
        _plot_redrew,
        _shows_winter,
    )

    page = ctx.page
    require_webgpu(page)
    token, project_id = _session(page)
    ids, colors = _ids(), _colors()
    # Run and saved: a save keeps the outputs the dashboard's tiles read.
    run_all_and_wait(page, timeout_ms=RUN_ALL_MS)
    _shows_winter(page, ids, colors, "the owner's Run All", on_canvas=True)
    save_dataflow(page)
    _frame_all(ctx)

    ctx.mark("clip", "start")
    ctx.click(page.get_by_test_id("share-menu-btn"), force=True)
    link = page.get_by_test_id("open-dashboard-link")
    ctx.focus(link, hold=1200)
    # Open dashboard opens a tab of its own, and a recording holds one page,
    # so the dashboard opens in this one. The clip cuts from the menu to the
    # drawn dashboard.
    ctx.mark("cut", "start")
    page.goto(f"{ctx.frontend}/dashboard/{project_id}")
    page.get_by_test_id("edit-layout-btn").wait_for(state="visible", timeout=45000)
    _shows_winter(page, ids, colors, "the dashboard opened")
    expect(_day(page, ids["steps"], WINTER["Day"])).to_be_checked(timeout=30000)
    park_pointer(page)
    ctx.mark("cut", "end")
    ctx.beat(2500)
    ctx.capture("winter", fit_reactflow=False)

    winter_plot = page.evaluate(_PLOT_PIXELS_JS, ids["plot"])
    _keep_drawing_maps(page, ids)
    summer = _day(page, ids["steps"], SUMMER["Day"])
    expect(summer).to_be_enabled(timeout=20000)
    ctx.click(summer)
    ctx.beat(1500)
    ctx.mark("cut", "start")
    _maps_redrew(page, ids, "the summer solstice was picked")
    _plot_redrew(page, ids["plot"], winter_plot)
    ctx.mark("cut", "end")
    expect(summer).to_be_checked(timeout=10000)
    park_pointer(page)
    ctx.beat(2500)
    ctx.mark("clip", "end")
