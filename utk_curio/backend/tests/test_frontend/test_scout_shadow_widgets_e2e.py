"""Playwright E2E: Accumulated Shadow's widgets, on the model package's node.

Example 24's chain from SCOUT's buildings to their shadow statistics, without
its maps: Data Loading, Rasterize Buildings, Accumulated Shadow and the Raster
Calculator of statistics. The shadow node is the node of the model package
``model.scout.deep-umbra@1`` as the Node Catalog drops it: its three-line cell
and its Season widget. This drives the widgets as a user does:

1. Run the statistics node. The chain runs, and the shadow is summer's: its
   raster says summer, a day in shadow counting 720 minutes.
2. Set Season to winter in the Widgets tab. The shadow node is stale (its
   Executed mark goes), and running the statistics node again runs it again:
   the shadow is winter's (360 minutes), and its mean over the ground differs.
3. Add a widget in the Widgets tab, a choice named ``when``, and give the call
   that widget in place of Season: the next run reads it (spring, 540
   minutes, a third mean).
4. Save and reopen: Season reads winter, ``when`` reads spring, and the code
   still reads ``when``.

The packages are in every account's store and their libraries are installed
because the stack starts with ``--with-examples`` and the example declares the
packages.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_scout_shadow_widgets_e2e.py -v
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .test_widget_tags_e2e import _add_widget, _open_tab, _panel, _wait_for_code_containing
from .utils import (
    REPO_ROOT,
    api_json,
    load_artifact_as_dict,
    node_locator,
    play_node,
    read_node_code,
    read_node_error_text,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    sandbox_auth_header,
    sandbox_base_url,
    save_dataflow,
    set_node_code,
    stub_login_and_enter_workflow,
    wait_for_node_run_to_end,
    watch_node_run,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = Path(REPO_ROOT) / "docs" / "examples" / "24-scout-building-rasters.json"
PACKAGE = Path(REPO_ROOT) / "packages" / "model.scout.deep-umbra@1"
SHADOW_TYPE = "model.scout.deep-umbra/accumulated-shadow"
#: The node that takes the shadow's statistics: example 24's one Raster Calculator.
STATISTICS_TYPE = "curio.builtin/raster-calculator"
#: The nodes of the example's chain, from the buildings to their statistics.
CHAIN_TYPES = {
    "curio.builtin/data-loading",
    "scout.raster-conversion/rasterize-buildings",
    SHADOW_TYPE,
    STATISTICS_TYPE,
}
PACKAGES = ("model.scout.deep-umbra@1", "scout.raster-conversion@1")
#: The first run rasterizes the buildings and runs Deep Umbra on four tiles.
FIRST_RUN_MS = 300000
RERUN_MS = 180000

#: The artifact a node's last run saved, from what its output pane says.
_OUTPUT_ARTIFACT_JS = """(id) => {
    const node = window.__curio_reactFlow.getNodes().find((n) => n.id === id);
    const content = node && node.data && node.data.output && node.data.output.content;
    const match = typeof content === "string" ? content.match(/Saved to file: (\\S+)/) : null;
    return match ? match[1] : null;
}"""


def _template() -> tuple[dict, str]:
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    (template,) = manifest["templates"]
    return template, (PACKAGE / template["source"]).read_text(encoding="utf-8")


def _chain() -> dict:
    """Example 24 with only its chain from the buildings to the statistics."""
    spec = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    dataflow = spec["dataflow"]
    kept = [node for node in dataflow["nodes"] if node["type"] in CHAIN_TYPES]
    ids = {node["id"] for node in kept}
    dataflow["nodes"] = kept
    dataflow["edges"] = [edge for edge in dataflow["edges"] if edge["source"] in ids and edge["target"] in ids]
    dataflow["name"] = "Shadow widgets"
    spec["name"] = "Shadow widgets"
    return spec


def _shadow_raster(page, node_id: str) -> dict:
    """The season and minutes the shadow node's raster was written with: the
    tags of the GeoTIFF the sandbox serves for it."""
    import requests

    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "the shadow node shows no saved output"
    reply = requests.get(
        f"{sandbox_base_url()}/raster", params={"fileName": artifact}, headers=sandbox_auth_header(), timeout=120,
    )
    assert reply.ok, f"/raster {artifact} -> {reply.status_code}: {reply.text[:500]}"
    # GDAL keeps a GeoTIFF's tags as XML in the file's GDAL_METADATA tag.
    tags = dict(re.findall(rb'<Item name="(season|minutes)">([^<]*)</Item>', reply.content))
    return {name.decode(): value.decode() for name, value in tags.items()}


def _mean(page, node_id: str) -> float:
    artifact = page.evaluate(_OUTPUT_ARTIFACT_JS, node_id)
    assert artifact, "the statistics node shows no saved output"
    stored = load_artifact_as_dict(artifact)
    assert stored["dataType"] == "dataframe", stored["dataType"]
    (mean,) = stored["data"]["mean"]
    return float(mean)


def _executed(page, node_id: str):
    return node_locator(page, node_id).locator('span[title="Executed"]')


def _rerun(page, shadow: str, statistics: str) -> None:
    """Run the statistics node, which runs the stale shadow node first. Both
    show a result from the run before, so each is watched from before the
    click until a run of its own has ended."""
    watch_node_run(page, shadow)
    watch_node_run(page, statistics)
    play_node(page, statistics)
    for node_id, node_type in ((shadow, SHADOW_TYPE), (statistics, STATISTICS_TYPE)):
        status = wait_for_node_run_to_end(page, node_id, node_type=node_type, timeout_ms=RERUN_MS)
        assert status == "done", (
            f"{node_type} ran again and ended {status}: {read_node_error_text(node_locator(page, node_id))}"
        )


def test_the_season_and_an_added_widget_reach_deep_umbra_and_survive_a_reopen(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    template, cell = _template()
    spec = _chain()
    nodes = spec["dataflow"]["nodes"]
    shadows = [node for node in nodes if node["type"] == SHADOW_TYPE]
    assert len(shadows) == 1, (
        f"example 24 holds no {SHADOW_TYPE} node: its types are {sorted({node['type'] for node in nodes})}"
    )
    (shadow_node,) = shadows
    assert shadow_node["content"] == cell and len(cell.splitlines()) == 3, shadow_node["content"]
    assert shadow_node["metadata"]["widgets"] == template["widgets"]
    shadow = shadow_node["id"]
    (statistics_node,) = [node for node in nodes if node["type"] == STATISTICS_TYPE]
    assert "\nreturn curio_raster_statistics(" in statistics_node["content"], statistics_node["content"]
    statistics = statistics_node["id"]

    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Shadow Widgets",
        username="scout_shadow_widgets_e2e",
        project_name=spec["dataflow"]["name"],
        project_spec=spec,
    )
    require_owner_view(page)
    project_id = session["project"]["id"]
    store = [p.get("dirName") for p in api_json(f"{current_server}/api/packages", session["token"])["packages"]]
    missing = [package for package in PACKAGES if package not in store]
    assert not missing, f"{missing} are not in the account's store {store}: start the stack --with-examples"
    for node in nodes:
        node_locator(page, node["id"]).wait_for(state="attached", timeout=45000)
    assert read_node_code(page, shadow) == cell

    # 1. The chain runs with the Season widget at its default.
    run_node_and_wait(page, statistics, node_type=STATISTICS_TYPE, timeout_ms=FIRST_RUN_MS)
    expect(_executed(page, shadow)).to_have_count(1, timeout=30000)
    assert _shadow_raster(page, shadow) == {"season": "summer", "minutes": "720"}
    summer = _mean(page, statistics)

    # 2. Winter: the node is stale, and the next run runs it again in winter.
    _open_tab(page, shadow, "widgets")
    _panel(page, shadow).locator('[data-widget-row="season"]').get_by_label("winter").check()
    expect(_executed(page, shadow)).to_have_count(0, timeout=10000)
    _rerun(page, shadow, statistics)
    assert _shadow_raster(page, shadow) == {"season": "winter", "minutes": "360"}
    winter = _mean(page, statistics)
    assert winter != summer, (summer, winter)

    # 3. A widget added in the Widgets tab, which the call reads in place of
    # Season: the next run is spring's.
    def seasons(form) -> None:
        form.get_by_label("Widget choices").fill("spring, summer, winter")
        form.get_by_label("Widget display").select_option("radio")

    _add_widget(page, shadow, name="when", kind="choice", label="When", fill=seasons)
    reads_when = cell.replace("[!! season !!]", "[!! when !!]")
    assert reads_when != cell
    _open_tab(page, shadow, "code")
    set_node_code(page, shadow, reads_when)
    _wait_for_code_containing(page, shadow, "[!! when !!]")
    _rerun(page, shadow, statistics)
    assert _shadow_raster(page, shadow) == {"season": "spring", "minutes": "540"}
    spring = _mean(page, statistics)
    assert len({summer, winter, spring}) == 3, (summer, winter, spring)

    # 4. Saved, then back after a reopen: both widgets and the code.
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    (saved_shadow,) = [node for node in saved["dataflow"]["nodes"] if node["id"] == shadow]
    values = {w["name"]: w.get("value", w.get("default")) for w in saved_shadow["metadata"]["widgets"]}
    assert values == {"season": "winter", "when": "spring"}, saved_shadow["metadata"]["widgets"]
    assert saved_shadow["content"] == reads_when

    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    node_locator(page, shadow).wait_for(state="visible", timeout=45000)
    _wait_for_code_containing(page, shadow, "[!! when !!]", timeout=45000)
    _open_tab(page, shadow, "widgets")
    panel = _panel(page, shadow)
    season = panel.locator('[data-widget-row="season"]').get_by_label("winter")
    season.wait_for(state="visible", timeout=15000)
    reopened = {
        "season": season.is_checked(),
        "when": panel.locator('[data-widget-row="when"]').get_by_label("spring").is_checked(),
    }
    assert reopened == {"season": True, "when": True}, reopened
