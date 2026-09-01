"""Playwright E2E: the Agent Catalog drawer.

The claim only a browser can settle is the last one in
``test_add_agent_propagates_to_palette``: adding an agent from the drawer
repaints the tools palette with no reload. That path crosses a React portal
(the drawer is a ``createPortal`` child of ``<body>``), a window CustomEvent
(``curio:agent-catalog-refresh``), and two independently-mounted surfaces
holding their own caches. Nothing below this level spans that graph.

``test_requires_agents_closure`` is the other one worth a browser: the
disclosure the drawer shows before the click has to match what the server
actually does on it, and that agreement lives across the wire.

Covered more cheaply elsewhere, and deliberately not re-asserted here:
``test_agents/test_routes.py`` owns the route contract and the closure's
server-side refusal, ``test_agents/test_delegation.py`` owns the closure
computation, and ``src/tests/catalog/AgentCatalogDrawer.test.tsx`` owns which
button a card shows for a given prop set.

Agents are safe to install in a way node packages are not: no pip, no archive
extraction, no behavior script. The install writes a coordinate into the
project's lockfile and copies prompt files into the user store, so there is no
equivalent of the node suite's "only curio.example-ui@1 may be installed" rule.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_agent_catalog.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    accept_confirm_dialog,
    api_json,
    open_tools_palette,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

# A built-in with no requiresAgents: the plain install path.
AGENT_COORD = "agent.node-explainer@1.0.0"
AGENT_ID = "agent.node-explainer"
AGENT_NAME = "Node Explainer"

# The one built-in that declares a hard dependency (on agent.node-content-builder),
# which is what makes the closure assertable end to end.
DEPENDENT_COORD = "agent.dataflow-builder@1.0.0"
REQUIRED_ID = "agent.node-content-builder"

DRAWER_ROOT = '[data-curio-agent-catalog-drawer="true"]'
SEARCH_PLACEHOLDER = "Search agents, publishers, tags…"


def _one_node_spec() -> dict:
    """A single node so the canvas is not empty.

    ``save_workflow_test_screenshot`` pins the viewport with
    ``_wait_for_reactflow_ready`` before capturing, and that waits for at least
    one ``.react-flow__node``. An empty dataflow therefore times out.
    """
    return {
        "dataflow": {
            "name": "AgentCatalogBaseline",
            "task": "",
            "nodes": [
                {
                    "id": "agent-baseline-node",
                    "type": "curio.builtin/computation-analysis",
                    "x": 420,
                    "y": 300,
                    "content": "return [1]",
                    "in": "DEFAULT",
                    "out": "DEFAULT",
                    "goal": "",
                    "metadata": {"keywords": []},
                }
            ],
            "edges": [],
        }
    }


def _enter_dataflow(page, app_frontend, current_server, *, username, project):
    """Authenticated owner session on a saved dataflow, with motion disabled.

    ``reduced_motion`` is set BEFORE navigating: the drawer slides in via
    ``transform: translate3d(100%)``, which keeps a full bounding box
    off-screen, so ``to_be_visible`` would pass before the panel is reachable.
    The provider reads prefers-reduced-motion through ``useSyncExternalStore``,
    so emulating it makes presentation synchronous.
    """
    page.emulate_media(reduced_motion="reduce")
    result = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Agent Catalog User",
        username=username,
        project_name=project,
        project_spec=_one_node_spec(),
    )
    require_owner_view(page)
    return result


def _open_drawer_from_menu(page):
    """Data menu -> Agent Catalog."""
    page.get_by_role("button", name="Data ⏷", exact=True).click(force=True)
    # "Agent Catalog" also labels the palette trigger, whose accessible name
    # includes a count span - exact=True picks out the menu row's own button.
    page.get_by_role("button", name="Agent Catalog", exact=True).click()
    return _drawer(page)


def _drawer(page):
    root = page.locator(DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # Resolved by heading rather than by role name: other dialogs on the page
    # carry no accessible name, so a bare get_by_role would be a strict-mode
    # violation whenever one is open.
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    expect(dialog).to_be_visible(timeout=10000)
    return dialog


def _card(drawer, coord: str):
    return drawer.locator(f'article[data-agent-coord="{coord}"]')


def _installed_coords(current_server: str, token: str, project_id: str) -> set[str]:
    """The project's agent lockfile, as coordinates.

    ``GET /api/agents/projects/<id>`` answers with full cards rather than a
    list of strings - unlike the packages route, whose ``{"packages": [...]}``
    really is a list of dir names. Reducing to coordinates here keeps that
    difference in one place instead of in every assertion.
    """
    rows = api_json(f"{current_server}/api/agents/projects/{project_id}", token)["agents"]
    return {row["dirName"] for row in rows}


def test_drawer_lists_catalog_agents(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="agentcat_list", project="Agent Catalog List",
    )

    drawer = _open_drawer_from_menu(page)

    expect(_card(drawer, AGENT_COORD)).to_have_count(1, timeout=15000)
    expect(
        _card(drawer, AGENT_COORD).get_by_role("button", name="Add to project")
    ).to_be_visible()

    # A wedged user store surfaces here as an error banner. Asserting its
    # absence turns that into a legible failure instead of a button that
    # mysteriously never flips.
    expect(drawer.locator('[role="alert"]')).to_have_count(0)

    # Visual baseline of the drawer in its listing state. The assertions above
    # cover which cards and buttons exist; this covers the layout they sit in,
    # which no locator can see - and it is the artifact that shows the drawer
    # is the same screen as its two peers.
    save_workflow_test_screenshot(
        page, "agent-catalog-drawer", test_name="test_drawer_lists_catalog_agents",
    )

    # Escape closes and the portal unmounts; reopening mounts exactly one.
    page.keyboard.press("Escape")
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    _open_drawer_from_menu(page)
    expect(page.locator(DRAWER_ROOT)).to_have_count(1)


def test_drawer_search_filters_by_agent_id(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    _enter_dataflow(
        page, app_frontend, current_server,
        username="agentcat_search", project="Agent Catalog Search",
    )

    drawer = _open_drawer_from_menu(page)
    expect(_card(drawer, AGENT_COORD)).to_have_count(1, timeout=15000)

    # Filtering is client-side and synchronous (agentListUtils.matchesAgentSearch),
    # so no debounce budget is needed. Searching the id proves it matches on
    # more than the display name.
    drawer.get_by_placeholder(SEARCH_PLACEHOLDER).fill(AGENT_ID)
    expect(_card(drawer, AGENT_COORD)).to_have_count(1, timeout=10000)
    expect(drawer.locator("article")).to_have_count(1)

    drawer.get_by_placeholder(SEARCH_PLACEHOLDER).fill("")
    # Count-free on purpose: adding a built-in must not break this.
    expect(_card(drawer, AGENT_COORD)).to_have_count(1, timeout=10000)


def test_add_agent_propagates_to_palette(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server,
        username="agentcat_add", project="Agent Catalog Add",
    )
    token = result["token"]
    project_id = result["project"]["id"]

    # 1. Precondition from the API: this agent must need nothing else, or the
    #    install below would write more coordinates than the assertion expects.
    catalog = api_json(f"{current_server}/api/agents/catalog", token)
    row = next(a for a in catalog["items"] if a["dirName"] == AGENT_COORD)
    assert row["requiresAgents"] == [], (
        f"{AGENT_COORD} gained requiresAgents {row['requiresAgents']}; this test "
        f"asserts a single-coordinate install. Use the closure test instead."
    )

    lock_before = _installed_coords(current_server, token, project_id)

    # 2. Open the palette FIRST and leave it mounted, then reach the drawer
    #    from the Data menu. Opening the drawer does not change ToolsMenu's
    #    `activePalette`, so the palette survives underneath - which is what
    #    makes the post-condition below a claim about a live repaint rather
    #    than about a fresh fetch on mount.
    #
    #    Entering from the menu rather than the palette's own "Browse Agent
    #    Catalog +" footer is what keeps the palette mounted underneath, which
    #    is the whole point here. (The footer is reachable now that the panel is
    #    positioned against the dock like its two peers; it was below the fold
    #    while the panel still hung off its own trigger.)
    open_tools_palette(page, "agents")
    drawer = _open_drawer_from_menu(page)
    card = _card(drawer, AGENT_COORD)
    expect(card).to_have_count(1, timeout=15000)

    # 3. Adding confirms first (#196), as the Data and Node catalogs do, so the
    #    card click only opens the dialog - the POST follows the confirm.
    card.get_by_role("button", name="Add to project").click()
    with page.expect_response(
        lambda r: "/api/agents/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST"
        and r.ok,
        timeout=30000,
    ):
        accept_confirm_dialog(
            page, title=f"Add {AGENT_NAME}?", button="Add to project"
        )

    # 4. The card flips. Never target a busy label; wait for the settled state.
    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_be_visible(timeout=20000)

    # 5. THE POINT: close the drawer (its overlay is inset:0 with
    #    pointer-events:auto and would swallow the palette click), then the
    #    palette must already show the new agent with no reload.
    drawer.get_by_role("button", name="Close Agent Catalog drawer").click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#agents-palette [data-agent-coord="{AGENT_COORD}"]')
    ).to_have_count(1, timeout=20000)

    # 6. Diagnostic read: localises a UI failure to backend vs frontend.
    lock_after = _installed_coords(current_server, token, project_id)
    assert lock_after == lock_before | {AGENT_COORD}, (
        f"lockfile went from {sorted(lock_before)} to {sorted(lock_after)}"
    )

    # 7. The round trip back. Removal confirms, as it does in the Node and Data
    #    drawers - an in-app ConfirmDialog now (#197), not a native one, so it
    #    is driven by clicking its button rather than by a `dialog` handler.
    drawer = _open_drawer_from_menu(page)
    card = _card(drawer, AGENT_COORD)
    expect(card).to_have_count(1, timeout=20000)

    card.get_by_role("button", name="Remove from project", exact=True).click()
    with page.expect_response(
        lambda r: "/api/agents/projects/" in r.url
        and r.request.method == "DELETE"
        and r.ok,
        timeout=30000,
    ):
        accept_confirm_dialog(page, title=f"Remove {AGENT_NAME}?", button="Remove")

    expect(
        card.get_by_role("button", name=re.compile(r"^Add to project"))
    ).to_be_visible(timeout=20000)

    # The palette empties without a reload, the mirror of step 5.
    drawer.get_by_role("button", name="Close Agent Catalog drawer").click()
    expect(page.locator(DRAWER_ROOT)).to_have_count(0, timeout=5000)
    expect(
        page.locator(f'#agents-palette [data-agent-coord="{AGENT_COORD}"]')
    ).to_have_count(0, timeout=20000)

    assert _installed_coords(current_server, token, project_id) == lock_before


def test_requires_agents_closure_is_disclosed_and_installed(
    app_frontend: "FrontendPage", current_server: str, page
):
    """The one claim unique to this catalog.

    An agent may declare a hard dependency on another. The drawer discloses
    what an Add will also bring in BEFORE the click, and the server resolves
    the whole closure before writing anything. Both halves have to agree, and
    that agreement spans the wire.
    """
    require_project_page()
    require_user_auth()
    result = _enter_dataflow(
        page, app_frontend, current_server,
        username="agentcat_closure", project="Agent Catalog Closure",
    )
    token = result["token"]
    project_id = result["project"]["id"]

    catalog = api_json(f"{current_server}/api/agents/catalog", token)
    row = next(a for a in catalog["items"] if a["dirName"] == DEPENDENT_COORD)
    required = [r["id"] for r in row["requiresAgents"]]
    assert REQUIRED_ID in required, (
        f"{DEPENDENT_COORD} no longer requires {REQUIRED_ID} (requires {required}); "
        f"pick another dependent built-in or this test proves nothing."
    )

    drawer = _open_drawer_from_menu(page)
    card = _card(drawer, DEPENDENT_COORD)
    expect(card).to_have_count(1, timeout=15000)

    # Disclosed before the click: the card names what else the install adds.
    expect(card.get_by_text(re.compile("Requires", re.I))).to_be_visible()

    card.get_by_role("button", name=re.compile(r"^Add to project")).click()
    with page.expect_response(
        lambda r: "/api/agents/projects/" in r.url
        and r.url.endswith("/install")
        and r.request.method == "POST"
        and r.ok,
        timeout=30000,
    ):
        # The confirmation lists the closure it is about to pull in (dev/106).
        accept_confirm_dialog(
            page, title=re.compile(r"^Add "), button="Add to project"
        )

    expect(
        card.get_by_role("button", name="Remove from project", exact=True)
    ).to_be_visible(timeout=20000)

    # The server wrote the whole closure, not just the row that was clicked.
    installed = _installed_coords(current_server, token, project_id)
    assert DEPENDENT_COORD in installed, sorted(installed)
    assert any(coord.startswith(REQUIRED_ID) for coord in installed), (
        f"the required {REQUIRED_ID} was not installed alongside it: {sorted(installed)}"
    )
