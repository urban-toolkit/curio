"""Building the Crown Heights shade example a step at a time: the five scenes
the guide's Crown Heights page shows as clips.

``docs/examples/dataflows/crown-heights-1550-bedford-shadow.json`` compares the
shade on Block 1259's open ground without and with the tower proposed at 1550
Bedford Avenue. Each scene opens on the example cut back to where its step
begins (``Walkthrough.start``) and checks that the step lands where the example
is:

1. the Dataflow Builder plans a first version from a short prompt, and Solve
   writes its code;
2. the two scenarios are made by hand, a Map Editor goes into the second, and
   the agent's check table comes out;
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

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.infrastructure.testing_provider import FALLBACK_REPLY

from ..utils import (
    CANVAS_DROP_TARGET,
    _DRAG_TO_CANVAS_JS,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    captured_agent_prompts,
    close_scenario_details,
    close_scenario_drawer,
    close_tools_palette,
    connect_nodes,
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
    use_scripted_llm,
    wait_for_node_done,
)
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
#: the chain: one column, so the copies Duplicate as scenario makes below it
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
    and its scenarios only when *scenarios*."""
    cut = copy.deepcopy(spec)
    flow = cut["dataflow"]
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] in keep]
    flow["edges"] = [edge for edge in flow["edges"] if edge["source"] in keep and edge["target"] in keep]
    if not scenarios:
        flow.pop("scenarios", None)
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
        "metadata": {"keywords": [], "packageTemplateLabel": TABLE_TITLE},
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
    """The Node Builder's reply: the node's new content, for review."""
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


def _send(ctx: Ctx, panel, message: str) -> None:
    ctx.narrator.type_into(panel.get_by_role("textbox", name="Message this agent"), message)
    ctx.click(panel.get_by_role("button", name="Send", exact=True))


def _close_chat(ctx: Ctx, panel) -> None:
    ctx.click(panel.get_by_role("button", name="Close chat"))
    expect(ctx.page.locator(CHAT)).to_have_count(0, timeout=10000)
    leave_agent_badge(ctx.page)


def _apply_plan(ctx: Ctx, panel, nodes: int) -> None:
    """The plan's card names what it builds; Apply plan builds it."""
    page = ctx.page
    card = panel.get_by_role("group", name=re.compile(r"^Review proposal: Apply plan")).first
    expect(card).to_be_visible(timeout=45000)
    expect(card).to_contain_text(f"{nodes} nodes", timeout=15000)
    ctx.focus(card, hold=2200)
    before = len(_node_ids(page))
    apply = panel.get_by_role("button", name=re.compile(r"^(Apply plan|Apply all without validation)$")).first
    with page.expect_response(
        lambda r: "/proposals/" in r.url and r.url.endswith("/apply") and r.request.method == "POST",
        timeout=60000,
    ) as applied:
        ctx.click(apply)
    assert applied.value.ok, f"Apply plan failed: {applied.value.status} {applied.value.text()[:300]}"
    page.wait_for_function(
        "(n) => window.__curio_reactFlow.getNodes().length === n", arg=before + nodes, timeout=45000,
    )


def _apply(ctx: Ctx, panel) -> None:
    """The card shows the agent's change; Apply makes it."""
    page = ctx.page
    apply = panel.get_by_role("button", name=re.compile(r"^Apply")).first
    expect(apply).to_be_visible(timeout=45000)
    ctx.focus(apply, hold=1800)
    with page.expect_response(
        lambda r: "/proposals/" in r.url and r.url.endswith("/apply") and r.request.method == "POST",
        timeout=60000,
    ) as applied:
        ctx.click(apply)
    assert applied.value.ok, f"the apply failed: {applied.value.status} {applied.value.text()[:300]}"


def _by_title(saved: dict, title: str) -> dict:
    """The saved node a plan made under *title*: Apply plan writes a node's
    goal as its title, a dash and its intent. The whole separator is matched,
    since one title can start another ("Cast sun rays on Block 1259")."""
    found = [node for node in saved["nodes"] if str(node.get("goal") or "").startswith(f"{title} — ")]
    assert len(found) == 1, f"{len(found)} saved nodes have a goal starting {title!r}"
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


def _name_scenario(ctx: Ctx, scenario_id: str, name: str, color: str) -> None:
    """Give a scenario its name and its color in its details."""
    page = ctx.page
    card = page.locator(f'[data-testid="scenario-card-{scenario_id}"]')
    ctx.focus(card.get_by_role("button", name=re.compile(r"^View .+ details$")), hold=500)
    details = open_scenario_details(page, scenario_id)
    field = details.get_by_label("Scenario name")
    field.fill("")
    ctx.narrator.type_into(field, name)
    field.press("Enter")
    expect(details.get_by_role("heading", name=name)).to_be_visible(timeout=10000)
    details.get_by_label(f"Color of {name}").fill(color)
    ctx.beat(700)
    close_scenario_details(page)


def _frame_all(ctx: Ctx) -> None:
    frame_nodes(ctx.page, _node_ids(ctx.page))
    park_pointer(ctx.page)


def _drew(check) -> bool:
    """Whether *check*, a drawing check, passes."""
    try:
        check()
    except (AssertionError, PlaywrightTimeoutError):
        return False
    return True


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
            "GPU with its three GPU steps. Apply plan puts the nodes on the canvas, "
            "and Solve writes their code.",
    tests=["test_frontend/test_example_reconstruction_e2e.py",
           "test_frontend/test_agent_scenarios_e2e.py"],
    example=EXAMPLE,
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
    _send(ctx, panel, FIRST_PROMPT)
    _apply_plan(ctx, panel, len(plan["nodes"]))
    ctx.capture("plan-applied", fit_reactflow=False)
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
    by_ref = {ref: _by_title(saved, nodes[node_id]["title"])["id"] for ref, node_id in refs.items()}
    by_ref["check-table"] = _by_title(saved, TABLE_TITLE)["id"]
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
    premise="The first version's GPU chain is duplicated as a scenario, the two "
            "scenarios are named without and with the proposed building, a Map Editor "
            "node goes into the second between the buildings and its chain, and the "
            "agent's check table comes out.",
    tests=["test_frontend/test_scenarios_canvas_e2e.py",
           "test_frontend/test_scenarios_in_project_e2e.py"],
    example=EXAMPLE,
    start=_first_version,
    needs_examples=True,
)
def crown_heights_scenarios(ctx: Ctx) -> None:
    page = ctx.page
    token, project_id = _session(page)
    chain = [nid(key) for key in TO_THE_GPU]
    without, with_ = _example()["dataflow"]["scenarios"]
    frame_nodes(page, [nid("ground"), *chain, TABLE])

    ctx.mark("clip", "start")
    # The chain, duplicated as a scenario: the copy reads what the chain reads.
    _shift_drag_around(ctx, chain)
    ctx.click(page.get_by_role("button", name="View menu"))
    ctx.click(page.get_by_role("button", name="Duplicate as scenario", exact=True))
    open_in_project_tab(page, opened_by_command=True)
    cards = page.evaluate(_SCENARIO_CARDS_JS, '[data-curio-scenario-catalog-drawer="true"][aria-hidden="false"]')
    assert len(cards) == 2, f"the In project tab lists {cards}, not two scenarios"
    copies = {
        node["copiedFrom"][-1]: node["id"]
        for node in page.evaluate(
            "() => window.__curio_reactFlow.getNodes().map((n) => ({id: n.id, copiedFrom: n.data && n.data.copiedFrom}))"
        )
        if node["copiedFrom"]
    }
    assert sorted(copies) == sorted(chain), f"the copies name {sorted(copies)} as their originals"
    for scenario_id, scenario in zip(cards, (without, with_)):
        _name_scenario(ctx, scenario_id, scenario["name"], scenario["color"])
    close_scenario_drawer(page)

    # A Map Editor node in the second scenario, between the buildings and the
    # copy of the chain, where the proposed building will be added.
    tower = copies[nid("base-tower")]
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
    # circle, with the ground on its second. Its lower connection comes out
    # first: then the other never moves up a circle, and its code still reads
    # input_0 and input_1 as written.
    frame_nodes(page, [nid("buildings"), nid("ground"), editor, tower])
    _delete_edge(ctx, nid("ground"), tower)
    _delete_edge(ctx, nid("buildings"), tower)
    _connect(ctx, nid("buildings"), editor)
    _connect(ctx, editor, tower, target_handle="in")
    _connect(ctx, nid("ground"), tower, target_handle="in_1")
    _select(ctx, editor)
    ctx.focus(page.get_by_role("button", name="Scenario Catalog", exact=True), hold=400)
    open_in_project_tab(page)
    ctx.click(scenario_card_button(page, cards[1], "Add selected"))
    expect(page.locator(f'[data-testid="scenario-card-{cards[1]}"]')).to_contain_text(
        f"{len(chain) + 1} nodes", timeout=10000,
    )
    close_scenario_drawer(page)

    # The check table goes: the grid is right.
    frame_nodes(page, [nid("ground"), TABLE])
    _select(ctx, TABLE)
    page.keyboard.press("Delete")
    page.wait_for_function(
        "id => !document.querySelector(`.react-flow__node[data-id='${id}']`)", arg=TABLE, timeout=10000,
    )
    _frame_all(ctx)
    ctx.beat(2500)
    ctx.mark("clip", "end")

    save_dataflow(page)
    saved = _saved(ctx, token, project_id)
    scenarios = saved.get("scenarios") or []
    assert [(s["name"], s["color"]) for s in scenarios] == [
        (without["name"], without["color"]), (with_["name"], with_["color"]),
    ], f"the scenarios saved are {[(s['name'], s['color']) for s in scenarios]}"
    assert sorted(scenarios[0]["nodes"]) == sorted(chain), scenarios[0]
    assert sorted(scenarios[1]["nodes"]) == sorted([editor, *copies.values()]), scenarios[1]
    by_id = {node["id"]: node for node in saved["nodes"]}
    assert TABLE not in by_id, "the check table is still in the saved dataflow"
    for original, copied in copies.items():
        assert (by_id[copied].get("metadata") or {}).get("copiedFrom") == [original], by_id[copied]
    wiring = {(e["source"], e["target"], e.get("targetHandle") or "in") for e in saved["edges"]}
    assert (nid("buildings"), editor, "in") in wiring, "the buildings do not feed the Map Editor"
    # The copy reads what the example's second scenario reads, on the same
    # circles, with its code as the original's.
    ours = {nid("add-building"): editor}
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
            "Eastern Parkway, and its upper floors to 185 ft. Once applied and run, the "
            "map with the proposed building shows it.",
    tests=["test_frontend/test_map_edits_agent_e2e.py",
           "test_frontend/test_crown_heights_dashboard_e2e.py"],
    example=EXAMPLE,
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
        "I have proposed the two parts for your review.",
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
    _send(ctx, panel, TOWER_PROMPT)
    _apply(ctx, panel)
    _wait_for_code(page, editor, edits)
    _said_only_what_was_scripted(panel)
    _close_chat(ctx, panel)
    frame_nodes(page, [editor, with_map])
    _play(ctx, editor)
    wait_for_node_done(page, editor, node_type=EDIT_TYPE)
    expect(node_locator(page, editor).locator('li[data-edit-op="add"]')).to_have_count(2, timeout=30000)
    _wait_for_redraw(page, with_map, "the tower was added")
    ctx.beat(2500)
    ctx.mark("clip", "end")

    moved = _changed(before, _map_pixels(page, with_map))
    assert moved > 0, "the map with the proposed building drew again the same once the tower was added"
    ctx.capture_node("map-with-the-tower", with_map)
    save_dataflow(page)
    history = (_saved_spec_root(ctx, token, project_id).get("nodeProvenance") or {}).get(editor) or []
    named = [entry for entry in history if entry.get("label") == node_builder.name]
    assert named, f"the Map Editor's history has no entry named {node_builder.name!r}: {history}"
    assert _same_code(str(named[-1].get("code") or ""), edits), named[-1]


def _saved_spec_root(ctx: Ctx, token: str, project_id: str) -> dict:
    return api_json(f"{ctx.backend}/api/projects/{project_id}", token)["spec"]


@walkthrough(
    slug="crown-heights-build-plot-and-map",
    title="Crown Heights: an agent creates a plot and a map",
    premise="Asked for the block's share in shadow through the day and the shade the "
            "tower adds, the Dataflow Builder plans a Vega-Lite plot and an Autark map "
            "wired to the scenarios' results. Apply plan puts them on the canvas, Solve "
            "writes their specs, and both draw.",
    tests=["test_frontend/test_crown_heights_dashboard_e2e.py"],
    example=EXAMPLE,
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
    _send(ctx, panel, PLOT_AND_MAP_PROMPT)
    _apply_plan(ctx, panel, len(plan["nodes"]))
    nodes = _nodes(spec)
    titles = [nodes[node_id]["title"] for node_id in refs.values()]
    written = _solve(ctx, builder, panel, token, project_id, titles)
    _said_only_what_was_scripted(panel)
    _close_chat(ctx, panel)
    plot, added = (written[nodes[nid(key)]["title"]]["id"] for key in PLOT_AND_MAP)
    frame_nodes(page, [plot, added])
    # Each draws its spec from the results its inputs already hold; one that
    # has not drawn a moment after Solve is played.
    if not _drew(lambda: assert_vega_canvas_rendered(page, plot, timeout=8000)):
        _play(ctx, plot)
    if not _drew(lambda: assert_autark_map_drawn(page, added, timeout=8000)):
        _play(ctx, added)
    _plot_drew(page, plot, _colors())
    _wait_for_map_drawn(page, added, "Solve wrote its spec")
    ctx.beat(2500)
    ctx.mark("clip", "end")

    ctx.capture_node("plot", plot)
    ctx.capture_node("map", added)
    wrong = [
        title for title, node in written.items()
        if not _same_code(node.get("content") or "", nodes[nid(PLOT_AND_MAP[titles.index(title)])]["content"])
    ]
    assert not wrong, f"Solve wrote other specs than the example's for {wrong}"
    saved = _saved(ctx, token, project_id)
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
