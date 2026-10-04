"""Playwright E2E: a per-node setting saved in a spec is live after the load.

``loadTrill`` read ``metadata.spatialJoin`` off every spec node and then handed
it to a node factory that builds ``node.data`` from an explicit option list the
setting was not on, so the Spatial Join's polygon property survived every save
and died on every load. Example 15 shipped with ``nameProperty: "zip"`` and ran
with ``name``, warning that no polygon had one (#262). ``metadata.simpleVis``
(#276) took the same path.

This asks the loaded node, not the file: right after the canvas opens, the
control on the Spatial Join must already read the persisted value. No run is
needed, which keeps it cheap enough to sit next to the unit tests in spirit.

The node settings modal's config (``metadata.packageTemplateConfig``, #412) is
the same kind of setting: it decides which editor tabs a node shows, and only
its label used to be saved.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_settings_survive_load_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    api_json,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

JOIN_ID = "settings-join"
CONFIGURED_ID = "settings-configured"
PLAIN_ID = "settings-plain"


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "Settings survive a load",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Settings survive a load",
            "nodes": [
                {
                    "id": JOIN_ID,
                    "type": "curio.builtin/spatial-join",
                    "x": 0,
                    "y": 0,
                    "content": "",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": [], "spatialJoin": {"nameProperty": "zip", "output": "polygons"}},
                }
            ],
            "edges": [],
        }
    }


def test_the_spatial_join_property_is_live_after_the_load(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Settings Load",
        username="settings_survive_load",
        project_name="Settings survive a load",
        project_spec=_spec(),
    )
    require_owner_view(page)

    control = node_locator(page, JOIN_ID).locator(
        'select[aria-label="Tag each point with this polygon column"]'
    )
    control.wait_for(state="visible", timeout=45000)
    assert control.input_value() == "zip", (
        "the Spatial Join opened with "
        f"{control.input_value()!r} although the spec persisted 'zip': the "
        "setting was dropped between loadTrill and the node factory"
    )

    # The second setting rides in the same metadata object and must survive too.
    output = node_locator(page, JOIN_ID).locator('select[aria-label="Output"]')
    output.wait_for(state="visible", timeout=15000)
    assert output.input_value() == "polygons", output.input_value()


def _python_node(node_id: str, x: int, metadata: dict) -> dict:
    return {
        "id": node_id,
        "type": "curio.builtin/computation-analysis",
        "x": x,
        "y": 0,
        "content": "return arg",
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "metadata": metadata,
    }


def _config_spec() -> dict:
    # Two Python nodes, whose template shows a Provenance tab. One turned it off
    # in the node settings modal; the other never opened the modal, so it shows
    # that the tab locator finds a tab that is there.
    return {
        "dataflow": {
            "name": "Node config survives a load",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Node config survives a load",
            "nodes": [
                _python_node(
                    CONFIGURED_ID,
                    0,
                    {"keywords": [], "packageTemplateConfig": {"hasProvenance": False}},
                ),
                _python_node(PLAIN_ID, 700, {"keywords": []}),
            ],
            "edges": [],
        }
    }


def _tab(page, node_id: str, key: str):
    return node_locator(page, node_id).locator(f'.nav-link[data-rr-ui-event-key="{key}"]')


def _assert_provenance_tab_follows_the_config(page, when: str) -> None:
    # The Code tab first: no tab at all would also mean no Provenance tab.
    for node_id in (CONFIGURED_ID, PLAIN_ID):
        _tab(page, node_id, "code").first.wait_for(state="visible", timeout=45000)
    _tab(page, PLAIN_ID, "provenance").first.wait_for(state="visible", timeout=15000)
    assert _tab(page, CONFIGURED_ID, "provenance").count() == 0, (
        f"{when}, the node shows a Provenance tab although its saved node "
        "settings turned it off: metadata.packageTemplateConfig did not reach "
        "node.data.packageTemplateConfig"
    )


def test_the_node_settings_config_is_live_after_the_load_and_survives_a_save(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Config Load",
        username="node_config_survives_load",
        project_name="Node config survives a load",
        project_spec=_config_spec(),
    )
    require_owner_view(page)
    project_id = session["project"]["id"]

    _assert_provenance_tab_follows_the_config(page, "Right after the load")

    # The canvas writes it back on a save, as the spec stores it...
    save_dataflow(page)
    saved = api_json(f"{current_server}/api/projects/{project_id}", session["token"])["spec"]
    by_id = {n["id"]: n for n in saved["dataflow"]["nodes"]}
    assert by_id[CONFIGURED_ID]["metadata"].get("packageTemplateConfig") == {
        "hasProvenance": False
    }, by_id[CONFIGURED_ID]["metadata"]
    assert "packageTemplateConfig" not in by_id[PLAIN_ID].get("metadata", {})

    # ...and the reopened dataflow still has the tab off. Left and reopened
    # rather than reloaded in place, so nothing survives in component state.
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    page.goto(f"{app_frontend.base_url}/dataflow/{project_id}")
    _assert_provenance_tab_follows_the_config(page, "After a save and reopen")
