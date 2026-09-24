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

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_node_settings_survive_load_e2e.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .utils import (
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

JOIN_ID = "settings-join"


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
        'input[aria-label="Tag each point with this polygon column"]'
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
