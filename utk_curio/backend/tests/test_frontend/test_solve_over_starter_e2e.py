"""Playwright: a starter is not an edit, so Solve writes a chart and a map whose
inputs have run.

A Vega-Lite chart or an Autark map whose input arrives while its editor is
empty shows a starter chosen in the tab from that input
(``hook/useStarterSpec``). The starter is not the node's spec: the dataflow's
doc, and so the server's copy, takes it only once someone edits it
(``components/editing/useYMonacoBinding``). Before, the editor's binding wrote
it into the server's copy, where Solve kept it as a person's edit and dropped
its own spec without a word.

1. **A planned chart and map.** On a saved dataflow whose loader has run, the
   scripted Dataflow Builder plans a ``curio.builtin/vis-vega`` chart and a
   ``curio.builtin/autk-grammar`` map wired to the loader. They land with no
   spec, the loader's result reaches them over the plan's connections, and
   each editor shows its starter. Solve then writes each node's
   scripted spec into the server's copy, its outcome is solved, not skipped,
   and each editor shows that spec whole.
2. **A chart and a map dropped from the Built-in palette** and wired to the
   loader show their starters while the server's copy holds no spec for
   either, not even the spec editor's empty ``{}``. An edit of the chart's
   starter then reaches the server's copy.

Driven by the scripted provider, so no model is called. Nothing is drawn, so
no WebGPU is needed.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_solve_over_starter_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    api_json,
    connect_nodes,
    dismiss_toasts,
    drag_builtin_to_canvas,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    script_agent_replies,
    set_canvas_zoom,
    set_node_code,
    stub_db_login,
    use_scripted_llm,
    wait_for_changes_kept,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DFB_COORD = "agent.curio.dataflow-builder@1"
DFB_NAME = "Dataflow Builder"
LOADER_ID = "starter-points"
CHART_TYPE = "curio.builtin/vis-vega"
MAP_TYPE = "curio.builtin/autk-grammar"

#: Three points with a name and a number each, from which a chart and a map
#: both choose a starter.
LOADER = (
    "import geopandas as gpd\n"
    "from shapely.geometry import Point\n"
    "\n"
    "return gpd.GeoDataFrame(\n"
    '    {"name": ["north", "centre", "south"], "pop": [1, 2, 3]},\n'
    "    geometry=[Point(-87.63, 41.88), Point(-87.62, 41.89), Point(-87.61, 41.87)],\n"
    '    crs="EPSG:4326",\n'
    ")\n"
)

#: What Solve writes, over the loader's own columns: neither is a starter.
CHART_SPEC = {
    "mark": "bar",
    "encoding": {
        "x": {"field": "name", "type": "nominal"},
        "y": {"field": "pop", "type": "quantitative"},
    },
}
MAP_SPEC = {
    "map": {"layerRefs": [{
        "dataRef": "input_0",
        "title": "Population",
        "getFnv": "pop",
        "getFnvType": "quantitative",
        "colorMapInterpolator": "interpolateViridis",
    }]},
}

CHART_TITLE = "Population by point"
MAP_TITLE = "Points on a map"
PLAN = {
    "goal": "chart and map the loaded points",
    "nodes": [
        {"ref": "chart", "nodeType": CHART_TYPE, "title": CHART_TITLE,
         "intent": "a bar chart of each point's population by its name"},
        {"ref": "map", "nodeType": MAP_TYPE, "title": MAP_TITLE,
         "intent": "a map of the points, each colored by its population"},
    ],
    "edges": [
        {"from": LOADER_ID, "to": "chart", "toHandle": "in"},
        {"from": LOADER_ID, "to": "map", "toHandle": "in"},
    ],
}
#: Solve's call for each node, answered by a part of its intent.
SOLVED = {
    "bar chart of each point": json.dumps(CHART_SPEC, indent=2),
    "map of the points, each colored": json.dumps(MAP_SPEC, indent=2),
}

#: How long Solve may take to write and check both nodes.
SOLVE_S = 300.0

#: The zoom and the drop points of the dropped chart and map, right of the
#: loader, which sits at the first point at this zoom: each node is 289 px
#: wide here, so their facing handles stay clear.
ZOOM = 0.55
LOADER_AT = (190, 140)
CHART_AT = (550, 140)
MAP_AT = (550, 400)

# The text of a node's spec editor, found by its model's path.
_SPEC_EDITOR_JS = """(nodeId) => {
    const editors = (window.monaco && window.monaco.editor.getEditors()) || [];
    const ed = editors.find((e) => {
        const model = e.getModel();
        const path = model && model.uri && model.uri.path;
        return !!path && path.includes(`grammar-${nodeId}`);
    });
    return ed ? ed.getValue() : null;
}"""


def _spec(loader_at: tuple[float, float] = (0, 0)) -> dict:
    """A saved dataflow holding the loader alone."""
    return {"dataflow": {
        "name": "Starters", "task": "", "timestamp": 1789193389280, "provenance_id": "Starters",
        "nodes": [{"id": LOADER_ID, "type": "curio.builtin/data-loading", "x": loader_at[0], "y": loader_at[1],
                   "content": LOADER, "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []}}],
        "edges": [],
    }}


def _open(page, app_frontend, backend: str, *, username: str, spec: dict) -> dict:
    """Sign in as *username* and make the dataflow *spec*; the page is not
    opened yet. The stub's login: its ``token`` and ``project``."""
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    return stub_db_login(
        page, frontend_url=app_frontend.base_url, backend_url=backend,
        username=username, name="Starter Owner", project_name="Starters", project_spec=spec,
    )


def _enter(page, app_frontend, project_id: str) -> None:
    """Open the dataflow, bound to its doc, and run its loader."""
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}", timeout=120000)
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    node_locator(page, LOADER_ID).wait_for(state="visible", timeout=45000)
    run_node_and_wait(page, LOADER_ID, node_type="DATA_LOADING", timeout_ms=120000)
    dismiss_toasts(page)


def _saved(backend: str, token: str, project_id: str) -> dict:
    """The dataflow as the server holds it now."""
    return api_json(f"{backend}/api/projects/{project_id}", token)["spec"]["dataflow"]


def _nodes(backend: str, token: str, project_id: str) -> dict[str, dict]:
    return {node["id"]: node for node in _saved(backend, token, project_id)["nodes"]}


def _by_title(nodes: dict[str, dict], title: str) -> str:
    found = [node_id for node_id, node in nodes.items() if node.get("title") == title]
    assert len(found) == 1, f"{len(found)} nodes are titled {title!r}: {sorted(nodes)}"
    return found[0]


def _document(text) -> object:
    """*text* as the document it holds, or the text itself when it is none."""
    try:
        return json.loads(text) if isinstance(text, str) else text
    except ValueError:
        return text


def _shown(page, node_id: str) -> str | None:
    return page.evaluate(_SPEC_EDITOR_JS, node_id)


def _wait_until(predicate, *, what: str, timeout: float, step: float = 1.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(step)
    raise AssertionError(f"{what} did not happen within {timeout:.0f} s (last: {last!r})")


def _shows_starter(page, node_id: str, mark: str) -> str:
    """Wait until the node's spec editor shows the starter it chose from its
    input, which holds *mark*, and return it."""
    return _wait_until(
        lambda: (lambda text: text if text and mark in text else None)(_shown(page, node_id)),
        what=f"{node_id}'s editor showing a starter from its input", timeout=60.0, step=0.5,
    )


def _builder(backend: str, token: str, project_id: str, attachment_id: str) -> dict:
    """The Dataflow Builder's session on the dataflow: its phase and the plan's nodeRuns."""
    cards = api_json(f"{backend}/api/agents/projects/{project_id}/attachments", token)["attachments"]
    card = next(c for c in cards if c["attachmentId"] == attachment_id)
    return card.get("builderSession") or {}


def test_solve_writes_a_planned_chart_and_map_whose_inputs_have_run(
    app_frontend: "FrontendPage", current_server: str, page,
):
    login = _open(page, app_frontend, current_server, username="solve_over_starter_planned", spec=_spec())
    token, project_id = login["token"], login["project"]["id"]
    use_scripted_llm(current_server, token)
    agents = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{agents}/install", token, method="POST", payload={"coord": DFB_COORD})
    attachment_id = api_json(f"{agents}/attachments", token, method="POST",
                             payload={"coord": DFB_COORD, "target": {"kind": "canvas"}})["attachmentId"]
    reply = "A chart and a map of the loaded points.\n```curio.v1\n" + json.dumps({"dataflowPlan": PLAN}) + "\n```"
    script_agent_replies(current_server, reply, "The points, charted and mapped", by_intent=SOLVED)
    _enter(page, app_frontend, project_id)

    opener = page.get_by_role("button", name=re.compile(rf"^Open chat with {re.escape(DFB_NAME)}")).first
    expect(opener).to_be_visible(timeout=20000)
    opener.click()
    panel = page.get_by_role("dialog", name=re.compile(rf"^Chat with {re.escape(DFB_NAME)}"))
    expect(panel).to_be_visible(timeout=20000)
    panel.get_by_role("textbox", name="Message this agent").fill("Chart and map these points.")
    panel.get_by_role("button", name="Send", exact=True).click()
    card = panel.get_by_role("group", name=re.compile(r"^Change: Plan")).first
    expect(card).to_be_visible(timeout=90000)
    page.wait_for_function("() => window.__curio_reactFlow.getNodes().length === 3", timeout=90000)

    # The loader's result reaches both planned nodes over the plan's
    # connections: each editor shows a starter chosen from it, and the server
    # has every change the tab made by then.
    planned = _nodes(current_server, token, project_id)
    chart, mapped = _by_title(planned, CHART_TITLE), _by_title(planned, MAP_TITLE)
    _shows_starter(page, chart, '"mark"')
    _shows_starter(page, mapped, "layerRefs")
    wait_for_changes_kept(page)
    before = _nodes(current_server, token, project_id)
    held = {node_id: before[node_id].get("content") for node_id in (chart, mapped)}

    strip = page.get_by_role("group", name=DFB_NAME).first
    solve = strip.get_by_role("button", name=re.compile(r"^(Solve|Retry \d+ \w+)$"))
    expect(solve).to_be_visible(timeout=30000)
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/solve/stream"), timeout=60000,
    ) as answered:
        solve.click()
    assert answered.value.status == 200, f"the server refused Solve: HTTP {answered.value.status}"
    session = _wait_until(
        lambda: (lambda s: s if s.get("phase") != "solving" and not s.get("solveExecutionId") else None)(
            _builder(current_server, token, project_id, attachment_id)),
        what="Solve ending", timeout=SOLVE_S, step=2.0,
    )

    runs = session.get("nodeRuns") or {}
    after = _nodes(current_server, token, project_id)
    for node_id, title, wanted in ((chart, CHART_TITLE, CHART_SPEC), (mapped, MAP_TITLE, MAP_SPEC)):
        written = after[node_id].get("content")
        assert runs.get(node_id) == "solved" and _document(written) == wanted, (
            f"{title}: Solve's outcome is {runs.get(node_id)!r} and the server holds {written!r}, not Solve's "
            f"spec {wanted!r}. Before Solve, with the starter in its editor, the server held {held[node_id]!r}."
        )
    # The canvas shows what Solve wrote, whole: the starter gave way to it.
    for node_id, wanted in ((chart, CHART_SPEC), (mapped, MAP_SPEC)):
        _wait_until(lambda: _document(_shown(page, node_id)) == wanted,
                    what=f"{node_id}'s editor showing Solve's spec", timeout=60.0, step=0.5)


def test_a_dropped_chart_and_map_keep_their_starters_in_the_tab(
    app_frontend: "FrontendPage", current_server: str, page,
):
    login = _open(page, app_frontend, current_server, username="solve_over_starter_dropped",
                  spec=_spec((LOADER_AT[0] / ZOOM, LOADER_AT[1] / ZOOM)))
    token, project_id = login["token"], login["project"]["id"]
    _enter(page, app_frontend, project_id)

    # Dropped from the Built-in palette and wired to the loader, which has
    # run: each takes its result at once.
    set_canvas_zoom(page, ZOOM)
    chart = drag_builtin_to_canvas(page, "#tile-vis-vega", at=CHART_AT)
    set_canvas_zoom(page, ZOOM)
    mapped = drag_builtin_to_canvas(page, "#tile-autk-grammar", at=MAP_AT)
    set_canvas_zoom(page, ZOOM)
    connect_nodes(page, LOADER_ID, chart)
    connect_nodes(page, LOADER_ID, mapped)

    starters = {chart: _shows_starter(page, chart, '"mark"'), mapped: _shows_starter(page, mapped, "layerRefs")}
    wait_for_changes_kept(page)
    held = _nodes(current_server, token, project_id)
    for node_id, starter in starters.items():
        assert node_id in held, f"the server has no node {node_id}"
        content = held[node_id].get("content")
        assert not (content or "").strip(), (
            f"the server's copy of {held[node_id].get('type')} holds {content!r}, while its editor shows the "
            f"starter it chose from its input: {starter!r}"
        )

    # An edit of the starter is the chart's spec, which the server keeps.
    edited = json.dumps(CHART_SPEC, indent=2)
    node_locator(page, chart).locator('.nav-link[data-rr-ui-event-key="grammar"]').first.dispatch_event("click")
    set_node_code(page, chart, edited)
    wait_for_changes_kept(page)
    kept = _nodes(current_server, token, project_id)[chart].get("content")
    assert _document(kept) == CHART_SPEC, f"the server holds {kept!r} for the chart, not its edit"
