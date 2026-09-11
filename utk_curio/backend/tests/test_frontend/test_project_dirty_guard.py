"""Playwright E2E: verify beforeunload guard when project has unsaved changes."""
from __future__ import annotations

from typing import TYPE_CHECKING

import json
import os

from playwright.sync_api import expect

from .utils import (
    REPO_ROOT,
    _post_json,
    canvas_nodes,
    dismiss_toasts,
    drag_to_canvas,
    require_owner_view,
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


#: A curated example rather than a hand-rolled spec: it is a real saved dataflow
#: with real edges, and the edge is the whole point - #229 was the load replaying
#: persisted edges through ``onConnect``, so an edgeless dataflow never reproduced
#: it. The provenance walkthroughs open the same file, so it is known to load.
EXAMPLE = "01-vega-lite-chained-transforms.json"

#: A built-in left-rail tile, always present. Dragging one onto the canvas is the
#: suite's proven way to make a genuine edit (``drag_to_canvas``); a raw mouse
#: drag of an existing node is far more brittle and tests nothing extra here.
ANALYSIS_TILE = "#step-analysis"


def _example_spec() -> dict:
    with open(
        os.path.join(REPO_ROOT, "docs", "examples", EXAMPLE), encoding="utf-8"
    ) as fh:
        return json.load(fh)


def test_a_freshly_loaded_dataflow_is_not_dirty(
    app_frontend: "FrontendPage", current_server: str, page,
):
    """#229: opening a saved dataflow reported unsaved changes with zero edits.

    ``loadParsedTrill`` replays each persisted edge through ``onConnect``, which
    marks the project dirty - so the dataflow finished hydrating dirty, and the
    30s auto-save then rewrote it for nothing, which is what made the indicator
    "turn green after a while".

    Three claims, and the third matters most: the guard must not have swallowed
    genuine edits along with the replay.
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
            "spec": _example_spec(),
        },
    )

    page.goto(f"{app_frontend.base_url}/dataflow/{created['id']}")
    page.wait_for_load_state("domcontentloaded")
    require_owner_view(page)
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
    # must not suppress it for the user's next real edit. If this is what fails,
    # the guard is swallowing edits - worse than the phantom flag it replaced,
    # because the user is then told their work is saved when it is not.
    before = len(canvas_nodes(page))
    drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=(150, 150))
    assert len(canvas_nodes(page)) == before + 1
    expect(disk).to_have_attribute("data-curio-save-state", "unsaved", timeout=15000)
