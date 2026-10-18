"""Playwright E2E: every scenario Curio ships drops from a project that never
ran, and runs where it lands.

The shipped dataflows with scenarios are example 06 and the test dataflows
``Scenarios``, ``ScoutShadows``, ``FloodScenarios`` and ``WeatherRouting``;
there is one test per scenario. Each signs in a fresh account, whose first
listing seeds its own copies of the shipped dataflows. Those have never run,
so the scenario's fixed context has no saved output. Then, in an empty
dataflow:

1. The scenario is dragged in from the Scenario Catalog drawer. The drop runs
   its context on the server, in the seeded project: the plan lists those
   nodes to run, and the page asks for a run of exactly them and runs nothing
   itself. It lands as one collapsed box, and the context arrives with the
   output that run saved.
2. Run scenario ends with every outcome done.
3. Expanded, every outcome shows its output: a map drawn, a chart drawn, or
   the result of a code node. Each map gets a close-up. An Interaction node
   among the levers has drawn its own map, and a frame of the whole dataflow
   is taken.

A test whose dataflow has an Autark node runs on the GPU runner
(``runner_split.SHIPPED_DROPS_MODULE``), the others on the CPU runners.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_shipped_scenario_drops_e2e.py --with-examples -v
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .test_scenario_drop_e2e import (
    _box,
    _copies,
    _drag_scenario_onto_canvas,
    _expand,
    _open_scenario_catalog,
    _record_python_runs,
    _record_run_starts,
    _run_scenario,
    _saved_spec,
    _status,
    _toast,
)
from .test_widget_tags_e2e import _open_tab
from .utils import (
    REPO_ROOT,
    api_json,
    assert_autark_map_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    require_webgpu,
    save_dataflow,
    save_dataflow_and_settle_header,
    save_node_closeup,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
    wait_for_node_run_to_end,
    wait_for_run_guard_released,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: The shipped dataflows that hold scenarios.
SHIPPED = (
    "docs/examples/06-autark-what-if-shadow-study.json",
    "docs/examples/dataflows/Scenarios.json",
    "docs/examples/dataflows/ScoutShadows.json",
    "docs/examples/dataflows/FloodScenarios.json",
    "docs/examples/dataflows/WeatherRouting.json",
)

DRAWER = '[data-curio-scenario-catalog-drawer="true"]'
AUTARK = "curio.builtin/autk-grammar"
VEGA = "curio.builtin/vis-vega"
#: The Interaction node, a lever that draws its input on a map of its own.
INTERACTION = "curio.builtin/edit-features"
TEST_NAME = "test_a_shipped_scenario_drops_from_a_project_never_run_and_runs"

#: How long the drop may take, its run of the context on the server included.
DROP_MS = 420000
#: How long Run scenario may take to end an outcome (the shadow model runs on
#: the CPU).
RUN_MS = 600000

EMPTY = {"dataflow": {
    "name": "Elsewhere", "task": "", "timestamp": 1789193389280,
    "provenance_id": "Elsewhere", "nodes": [], "edges": [],
}}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _spec(dataflow: str) -> dict:
    return json.loads((Path(REPO_ROOT) / dataflow).read_text(encoding="utf-8"))


def _cases():
    """One case per scenario of the shipped dataflows, read from the files."""
    cases = []
    for dataflow in SHIPPED:
        for scenario in _spec(dataflow)["dataflow"].get("scenarios") or []:
            name = f"{Path(dataflow).stem}-{_slug(scenario['name'])}"
            cases.append(pytest.param(dataflow, scenario["id"], id=name))
    return cases


def _listed(labels: list[str]) -> str:
    """How the drop's toast names several nodes: "A", "A and B", "A, B and C"."""
    return labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"


# Every toast the page shows from now on, so one that clears itself while a
# test waits on something else is still seen.
_RECORD_TOASTS_JS = r"""() => {
    if (window.__curioDropToasts) return;
    const region = document.querySelector('[aria-label="Notifications"]');
    window.__curioDropToasts = [];
    const record = () => region.querySelectorAll('.toast').forEach((toast) => {
        const text = (toast.textContent || '').trim();
        if (text && !window.__curioDropToasts.includes(text)) window.__curioDropToasts.push(text);
    });
    new MutationObserver(record).observe(region, { childList: true, subtree: true });
    record();
}"""

# What a code node holds after a run: its output's code and the file it saved.
_OUTPUT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const output = node && node.data && node.data.output;
    return output ? { code: output.code, content: String(output.content || '') } : null;
}"""


@pytest.mark.examples
@pytest.mark.parametrize("dataflow,scenario", _cases())
def test_a_shipped_scenario_drops_from_a_project_never_run_and_runs(
    app_frontend: "FrontendPage", current_server: str, page, dataflow: str, scenario: str,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    project = _spec(dataflow)["dataflow"]["name"]
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Shipped Scenario Drop",
        username="shipped_scenario_drop_e2e",
        project_name="Elsewhere",
        project_spec=EMPTY,
    )
    require_owner_view(page)
    token, target = session["token"], session["project"]["id"]
    # The first listing seeds the account's copies of the shipped dataflows.
    listed = api_json(f"{current_server}/api/projects", token, timeout=120)
    seeded = [p["id"] for p in listed if p.get("name") == project]
    assert len(seeded) == 1, f"the account has {len(seeded)} seeded {project!r}: {sorted(p.get('name') for p in listed)}"
    source = seeded[0]

    # Never run: every context node has no saved output, so the drop must run
    # each one in the seeded project before it can bring it.
    plan = api_json(f"{current_server}/api/scenarios/{source}/{scenario}/copy?target={target}", token)
    assert plan["problems"] == [], f"the drop is refused: {plan['problems']}"
    sources: list[str] = []
    for entry in plan["context"]:
        if entry.get("source") and entry["source"]["nodeId"] not in sources:
            sources.append(entry["source"]["nodeId"])
    assert sources, f"{plan['scenario']['name']} has no context to run: {plan['context']}"
    to_run = plan.get("toRun", [])
    assert [node["nodeId"] for node in to_run] == sources, (
        f"the drop would not run the context first: to run {to_run}, context sources {sources}"
    )
    name = plan["scenario"]["name"]
    types = {node["id"]: node["type"] for node in plan["dataflow"]["nodes"]}
    if any(node_type.startswith(AUTARK) for node_type in types.values()):
        require_webgpu(page)

    # 1. The drop runs the context on the server, then brings the scenario.
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=45000)
    page.locator(".react-flow__pane").wait_for(state="visible", timeout=45000)
    page.wait_for_selector('[aria-label="Notifications"]', state="attached", timeout=20000)
    page.evaluate(_RECORD_TOASTS_JS)
    started = _record_run_starts(page, source)
    sent, _outputs, stop = _record_python_runs(page)
    _open_scenario_catalog(page)
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith(f"/api/scenarios/{source}/{scenario}/copy"),
        timeout=DROP_MS,
    ) as copied:
        _drag_scenario_onto_canvas(page, source, scenario)
    assert copied.value.ok, copied.value.text()
    _toast(page, f'Added "{name}" from {project}.')
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, DRAWER)
    stop()
    assert started == [{"targets": sources}], f"the drop asked for {started} to run the context"
    assert sent == [], f"the page ran {sent}: the context runs on the server, in its own project"
    running = f"Running {_listed([node['label'] for node in to_run])} in {project} for {name}"
    toasts = page.evaluate("() => window.__curioDropToasts")
    assert any(running in toast for toast in toasts), f"no {running!r} among {toasts}"

    # One collapsed box, and the context arrived with the output its run saved:
    # a Data Loading node copied from each node that ran.
    copies = _copies(page)
    restored = {output["node_id"] for output in copied.value.json()["outputs"]}
    for entry in plan["context"]:
        if not entry.get("source"):
            continue
        loader = copies.get(entry["source"]["nodeId"])
        assert loader, f"nothing stands for {entry['label']} ({entry['source']['nodeId']}): {copies}"
        assert loader in restored, f"{entry['label']} arrived without its output: restored {sorted(restored)}"
        assert _status(page, loader) == "done", f"{entry['label']} ({loader}) does not show its output"
    save_dataflow(page)
    [dropped] = _saved_spec(current_server, token, target)["dataflow"]["scenarios"]
    assert dropped["source"] == {"project": source, "scenario": scenario}, dropped
    assert dropped["collapsed"] is True, dropped
    assert page.locator('[data-testid^="scenario-box-"]').count() == 1
    _box(page, dropped["id"]).wait_for(state="visible", timeout=15000)
    members = dropped["nodes"]
    assert sorted(members) == sorted(copies[lever] for lever in plan["levers"]), (members, copies)
    for member in members:
        node_locator(page, member).wait_for(state="attached", timeout=15000)
        assert not node_locator(page, member).is_visible(), f"{member} shows, though the scenario is collapsed"

    # 2. Run scenario ends with every outcome done.
    outcomes = [(copies[outcome["nodeId"]], outcome) for outcome in plan["outcomes"]]
    assert outcomes, f"{name} has no outcomes"
    for node_id, _outcome in outcomes:
        watch_node_run(page, node_id)
    # From its card in the In project tab; the drawer, which lies over the
    # right of the canvas where the outcomes are, is closed again.
    _run_scenario(page, dropped["id"])
    for node_id, outcome in outcomes:
        status = wait_for_node_run_to_end(page, node_id, node_type=types[outcome["nodeId"]], timeout_ms=RUN_MS)
        assert status == "done", (
            f"{outcome['label']} ({node_id}) ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )
    wait_for_run_guard_released(page, timeout_ms=60000)

    # 3. Expanded, each outcome shows its output.
    _expand(page, dropped["id"], members)
    for node_id, outcome in outcomes:
        node_type = types[outcome["nodeId"]]
        if node_type.startswith(AUTARK):
            frame_nodes(page, [node_id])
            assert_autark_map_drawn(page, node_id, timeout=60000, attach_as=f"{name}: {outcome['label']}")
            # A map's own close-up: in the full page it is a thumbnail.
            save_node_closeup(
                page, f"shipped-drop-{Path(dataflow).stem}-{_slug(name)}-{outcome['nodeId']}", node_id,
                test_name=TEST_NAME, sweep_toasts=True,
            )
        elif node_type.startswith(VEGA):
            frame_nodes(page, [node_id])
            assert_vega_canvas_rendered(page, node_id)
        else:
            output = page.evaluate(_OUTPUT_JS, node_id)
            assert output and output["code"] == "success" and "Saved to file:" in output["content"], (
                f"{outcome['label']} ({node_id}) shows no output: {output}"
            )
    # A lever that draws a map of its own, an Interaction node, has drawn it
    # before the whole dataflow is framed.
    for lever in plan["levers"]:
        if types[lever].startswith(INTERACTION):
            box = node_locator(page, copies[lever])
            _open_tab(page, copies[lever], "output")
            box.locator('[data-edit-map-state]:not([data-edit-map-state="drawing"])').wait_for(
                state="attached", timeout=90000,
            )
            state = box.locator("[data-edit-map-state]").get_attribute("data-edit-map-state")
            problem = box.locator("[data-edit-map-problem]").all_inner_texts()
            assert state == "drawn", f"{name}: the Interaction node {copies[lever]}'s map ended {state!r}: {problem}"
    # Saved first, so the header shows the save whatever the autosave reached (#584).
    save_dataflow_and_settle_header(page)
    save_workflow_test_screenshot(
        page, f"shipped-drop-{Path(dataflow).stem}-{_slug(name)}", test_name=TEST_NAME, sweep_toasts=True,
    )
