"""SCOUT's high-rise shadow case with the towers removed in an Interaction node.

The shipped test dataflow ``WhatIfShadowsInteractive.json``
(``scripts/build_example_whatif_interactive.py``) is ``WhatIfShadows`` with
the "Towers removed" scenario's buildings edited in an Interaction node (the
Edit Features type), whose edit log holds one entry: remove SCOUT's 15
high-rise buildings. Run All runs it, and then an edit propagates:

1. With the shipped log, each scenario's mean accumulated shadow is SCOUT's
   (128.64 and 106.73 minutes, in summer), as WhatIfShadows gives.
2. Switching the entry off makes the Interaction node and every node after it
   stale; Update results runs them, and Towers removed's mean is Existing's:
   no building is removed.
3. Switching it back on and updating gives SCOUT's 106.73 again, and the
   Vega-Lite comparison draws both scenarios.

The dataflow draws Autark maps, so this runs where WebGPU is. The packages are
in the store because the stack starts ``--with-examples``.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_whatif_interactive_e2e.py --with-examples -v
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .utils import (
    OUTPUT_ARTIFACT_JS,
    REPO_ROOT,
    api_json,
    assert_scenario_colors_drawn,
    assert_vega_canvas_rendered,
    frame_nodes,
    load_artifact_as_dict,
    node_locator,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_all_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DATAFLOW = Path(REPO_ROOT) / "docs" / "examples" / "dataflows" / "WhatIfShadowsInteractive.json"
INTERACTION_TYPE = "curio.builtin/edit-features"
PICKER_TYPE = "curio.builtin/computation-analysis"
VEGA_TYPE = "curio.builtin/vis-vega"
PACKAGES = ("scout.raster-conversion@1", "scout.shadow@1")
SCOUT_MEANS = {"existing": 128.63593, "towers-removed": 106.73111}
#: Deep Umbra's output moves with onnxruntime's thread count (test_scout_shadow.py).
TOLERANCE = 0.1


def _mean(page, node_id: str) -> float | None:
    artifact = page.evaluate(OUTPUT_ARTIFACT_JS, node_id)
    if not artifact:
        return None
    stored = load_artifact_as_dict(artifact)
    (mean,) = stored["data"]["Mean Acc shadow"]
    return float(mean)


def _wait_for_mean(page, node_id: str, target: float, what: str, timeout_s: float = 300) -> float:
    deadline = time.time() + timeout_s
    mean = None
    while time.time() < deadline:
        mean = _mean(page, node_id)
        if mean is not None and abs(mean - target) <= TOLERANCE:
            return mean
        page.wait_for_timeout(1000)
    raise AssertionError(f"{what}: the mean accumulated shadow is {mean}, not {target}")


def test_an_edit_in_the_interaction_node_reaches_the_shadow_and_the_chart(
    app_frontend: "FrontendPage", current_server: str, page, record_property,
):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    spec = json.loads(DATAFLOW.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    nodes = {node["id"]: node for node in dataflow["nodes"]}
    (interaction,) = [n for n, node in nodes.items() if node["type"] == INTERACTION_TYPE]
    metrics = [n for n, node in nodes.items() if node["type"] == PICKER_TYPE
               and node["content"].splitlines()[-1] == "return input_0[1]"]
    (chart,) = [n for n, node in nodes.items() if node["type"] == VEGA_TYPE]
    scenario_of = {n: scenario["id"] for scenario in dataflow["scenarios"] for n in scenario["nodes"]}
    metric_of = {scenario_of[n]: n for n in metrics}
    colors = [scenario["color"] for scenario in dataflow["scenarios"]]

    session = stub_login_and_enter_workflow(
        page, frontend_url=app_frontend.base_url, backend_url=current_server,
        name="What-if shadows, interactive", username="whatif_interactive_e2e",
        project_name=dataflow["name"], project_spec=spec,
    )
    require_owner_view(page)
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node_id in nodes:
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    # 1. The shipped log: SCOUT's two means, as WhatIfShadows gives.
    run_all_and_wait(page, timeout_ms=600000)
    for node_id in [interaction, *metrics, chart]:
        status = wait_for_node_settled(page, node_id, node_type=nodes[node_id]["type"], timeout_ms=180000)
        assert status == "done", f"{node_id} ended {status}: {read_node_error_text(node_locator(page, node_id))}"
    means = {scenario: _mean(page, node_id) for scenario, node_id in metric_of.items()}
    record_property("mean accumulated shadow, shipped log", json.dumps(means))
    assert all(abs(means[k] - SCOUT_MEANS[k]) <= TOLERANCE for k in SCOUT_MEANS), means

    # 2. The entry switched off: the node and everything after it is stale,
    #    and Update results runs it with nothing removed.
    node = node_locator(page, interaction)
    frame_nodes(page, [interaction])
    node.get_by_label("Use edit 1").uncheck()
    node.locator('[data-edit-enabled="false"]').wait_for(state="attached", timeout=10000)
    update = node.get_by_test_id("interaction-update")
    page.wait_for_function(
        "(id) => /\\(\\d+\\)/.test(document.querySelector(`.react-flow__node[data-id=\"${id}\"] [data-testid=\"interaction-update\"]`)?.textContent || '')",
        arg=interaction, timeout=10000,
    )
    update.click()
    off = _wait_for_mean(page, metric_of["towers-removed"], SCOUT_MEANS["existing"], "with the removal switched off")
    record_property("towers removed, entry off", off)

    # 3. Back on: SCOUT's second scenario again, and the chart draws both.
    frame_nodes(page, [interaction])
    node.get_by_label("Use edit 1").check()
    node.locator('[data-edit-enabled="true"]').wait_for(state="attached", timeout=10000)
    update.click()
    _wait_for_mean(page, metric_of["towers-removed"], SCOUT_MEANS["towers-removed"], "with the removal on again")
    status = wait_for_node_settled(page, chart, node_type=VEGA_TYPE, timeout_ms=180000)
    assert status == "done", read_node_error_text(node_locator(page, chart))
    frame_nodes(page, [chart])
    assert_vega_canvas_rendered(page, chart, timeout=30000)
    assert_scenario_colors_drawn(page, chart, colors)
