"""Playwright E2E: an agent added to an UNSAVED dataflow reaches the palette.

Reported symptom: agents were added, but they do not show in the agent catalog
on the left side (the AGENTS palette in the tools rail).

``test_agent_catalog.py::test_add_agent_propagates_to_palette`` already covers
this on a dataflow that has already been saved, and it passes. The path it does
not cover is the one #190/#199 opened up: adding to a dataflow that has NEVER
been saved, where the drawer creates and saves the project as part of the click.

That ordering is what makes it interesting. ``useAgentCatalogDrawer.run``
dispatches the refresh the instant the install returns::

    notifyAgentCatalogRefresh();   // palette re-reads NOW
    await refreshAll(actedOn);

while ``AgentsPaletteDropdown.load`` reads ``projectId`` out of
``useFlowContext()`` and gives up when it is null::

    if (!projectId) { setAgents([]); return; }

On a first save the project id is created inside the click, so the provider has
not necessarily re-rendered with it by the time the event fires - and the
palette answers the refresh by clearing itself. The drawer's own hook already
carries a ``createdProjectIdRef`` for exactly this window; the palette has no
equivalent.

Whether that window is observable is what this test decides, so it is written
to fail loudly rather than to be reassuring: it opens the palette first, adds
from an unsaved dataflow, and then requires the agent to appear in the rail.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_agent_palette_unsaved_dataflow_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    signup_and_enter_new_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

DRAWER_ROOT = '[data-curio-agent-catalog-drawer="true"]'
PALETTE_ROW = "#agents-palette [data-agent-coord]"


def _open_drawer_from_menu(page):
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    page.get_by_role("button", name="Agent Catalog", exact=True).click()
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    dialog.wait_for(state="visible", timeout=15000)
    return dialog


def test_agent_added_to_an_unsaved_dataflow_reaches_the_palette(
    app_frontend: "FrontendPage", frontend_server: str, page
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    signup_and_enter_new_workflow(
        page,
        frontend_server,
        name="Palette User",
        username="agent_palette_unsaved",
    )
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)

    # THE PRECONDITION: nothing saved yet. If the harness ever starts landing on
    # a saved dataflow this test silently becomes a duplicate of the existing
    # one, so assert it rather than assume it.
    assert "/dataflow/new" in page.url, (
        f"expected an unsaved dataflow, but the URL is {page.url} - this test "
        f"is specifically about the first-save path"
    )

    # Open the palette FIRST and leave it mounted underneath, so what follows is
    # a claim about a live repaint rather than about a fresh fetch on mount.
    open_tools_palette(page, "agents")

    drawer = _open_drawer_from_menu(page)
    card = drawer.locator("article[data-agent-coord]").first
    card.wait_for(state="visible", timeout=20000)
    coord = card.get_attribute("data-agent-coord")
    assert coord, "the first agent card carries no coordinate"

    card.get_by_role("button", name=re.compile(r"^Add to dataflow")).click()
    with page.expect_response(
        lambda r: "/api/agents/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST"
        and r.ok,
        timeout=60000,
    ):
        accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to dataflow")

    # The drawer agrees the add landed.
    expect(
        drawer.locator(f'article[data-agent-coord="{coord}"]').get_by_role(
            "button", name="Remove from dataflow", exact=True
        )
    ).to_be_visible(timeout=30000)

    # The save really happened, so the palette has a project id to read.
    page.wait_for_url(lambda url: "/dataflow/new" not in url, timeout=30000)

    # Close the drawer: its overlay is inset:0 with pointer-events:auto and
    # would swallow a palette interaction.
    drawer.get_by_role("button", name="Close Agent Catalog drawer").click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=10000)

    # THE POINT: the rail lists the agent that was just added.
    expect(
        page.locator(f'#agents-palette [data-agent-coord="{coord}"]')
    ).to_have_count(1, timeout=30000)

    save_workflow_test_screenshot(
        page, "agent-palette-after-first-save",
        test_name="test_agent_added_to_an_unsaved_dataflow_reaches_the_palette",
        # A brand-new dataflow has no nodes, so the default wait for a
        # `.react-flow__node` would time out on an empty canvas.
        fit_reactflow=False,
    )

    # And the rail's own count agrees with the row it is showing - a palette
    # that cleared itself and never refilled shows 0 beside a visible row.
    rows = page.locator(PALETTE_ROW).count()
    assert rows >= 1, f"the agents palette lists {rows} rows after an add"
