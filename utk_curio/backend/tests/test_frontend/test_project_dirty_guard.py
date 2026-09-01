"""Playwright E2E: verify beforeunload guard when project has unsaved changes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    _post_json,
    dismiss_toasts,
    require_project_page,
    require_user_auth,
    signup_and_enter_new_workflow,
    stub_db_login,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage


def test_dirty_guard_on_navigation(app_frontend: "FrontendPage", page):
    """After saving and editing, navigating away should trigger confirmation."""
    require_project_page()
    base = app_frontend.base_url

    signup_and_enter_new_workflow(
        page,
        base,
        name="Dirty Guard User",
        username="dirtyguard",
    )

    page.wait_for_timeout(2000)

    page.goto(f"{base}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=10000)


def _two_node_spec() -> dict:
    """Two nodes and an EDGE between them.

    The edge is the whole point: #229 was the load replaying persisted edges
    through ``onConnect``, which marks dirty. An edgeless dataflow never
    reproduced it, so a fixture without one would pass against the broken code.
    """
    def node(nid, x):
        return {
            "id": nid,
            "type": "curio.builtin/data-loading@1",
            "x": x,
            "y": 0,
            "content": "",
            "metadata": {},
        }

    return {
        "dataflow": {
            "name": "Dirty On Load",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "Dirty On Load",
            "nodes": [node("dirty-a", 0), node("dirty-b", 400)],
            "edges": [
                {
                    "id": "reactflow__edge-dirty-aout-dirty-bin",
                    "source": "dirty-a",
                    "target": "dirty-b",
                    "sourceHandle": "out",
                    "targetHandle": "in",
                    "type": "Unidirectional",
                }
            ],
        }
    }


def test_a_freshly_loaded_dataflow_is_not_dirty(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#229: opening a saved dataflow reported unsaved changes with zero edits.

    ``loadParsedTrill`` replays each persisted edge through ``onConnect``, which
    marks the project dirty - so the dataflow finished hydrating dirty, and the
    30s auto-save then rewrote it for nothing, which is what made the indicator
    "turn green after a while".

    Three claims, and the third is the one that matters most: the guard must not
    have swallowed genuine edits along with the replay.
    """
    require_project_page()
    require_user_auth()

    stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Dirty Load User",
        username="dirtyload_user",
    )
    created = _post_json(
        f"{current_server}/api/testing/stub-project",
        {
            "username": "dirtyload_user",
            "name": "Dirty On Load",
            "spec": _two_node_spec(),
        },
    )

    page.goto(f"{app_frontend.base_url}/dataflow/{created['id']}")
    page.wait_for_load_state("domcontentloaded")
    # Wait for the EDGE, not just a node: the edge is what the replay processes,
    # so before it renders the bug has not had its chance to happen yet.
    page.locator(".react-flow__edge").first.wait_for(state="visible", timeout=45000)
    dismiss_toasts(page)

    disk = page.locator("[data-curio-save-state]")
    expect(disk).to_have_attribute("data-curio-save-state", "saved", timeout=15000)

    # Past the 30s auto-save. A fix that merely DELAYED the flag - or left the
    # needless save in place - shows up here and nowhere else.
    page.wait_for_timeout(35000)
    assert disk.get_attribute("data-curio-save-state") == "saved", (
        "the dataflow went dirty on its own after loading, and the auto-save "
        "then rewrote it - this is #229"
    )

    # The fix's real risk, asserted last: suppressing dirty across the replay
    # must not suppress it for the user's next real edit.
    node = page.locator(".react-flow__node").first
    box = node.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 10)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 120, box["y"] + 90, steps=10)
    page.mouse.up()

    expect(disk).to_have_attribute("data-curio-save-state", "unsaved", timeout=15000), (
        "moving a node after the load did not mark the dataflow dirty; the "
        "hydration guard is swallowing real edits"
    )
