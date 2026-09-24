"""Right-click answers the same way on every browse grid (#285).

The projects page has opened an app menu on right-click for a long time - Open,
Rename, Duplicate, Delete. Its three siblings did not: the Node, Data and Agent
Catalogs let the event through, so the identical gesture on an identically
shaped card produced Back / Reload / View Page Source from the browser instead.

The menu markup lived inline in ``ProjectsList``, which is why nothing else
could have one. It is ``CardContextMenu`` now, and each grid supplies the
actions its own detail drawer offers. Two of the three new surfaces are
exercised here, on rows that ship with every deployment and need no fixture:
the Node Catalog's shipped package and the Agent Catalog's built-in.

The Data Catalog is left to the Jest wiring tests - its grid needs datasets
seeded into the account first, which says nothing more about the menu.
"""
from __future__ import annotations

from playwright.sync_api import expect

from .utils import (
    require_project_page,
    require_user_auth,
    stub_db_login,
)

#: Shipped in packages/, referenced by no example, so nothing installs it and
#: the menu's primary action is the way in rather than the update.
PACKAGE_NAME = "Urban Heat Vulnerability Index"

#: A built-in from the roster, listed without ever being imported.
AGENT_NAME = "Node Researcher"


def _login(page, app_frontend, current_server):
    require_project_page()
    require_user_auth()
    return stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        username="card_context_menu_user",
        name="Card Context Menu User",
    )


def _card(page, base: str, path: str, heading: str, name: str):
    page.goto(f"{base}{path}")
    expect(page.get_by_role("heading", name=heading, level=1)).to_be_visible(timeout=20000)
    card = page.locator("article").filter(
        has=page.get_by_role("heading", name=name, level=2, exact=True),
    )
    card.first.wait_for(state="visible", timeout=20000)
    return card.first


def _menu(page, name: str):
    menu = page.get_by_role("menu", name=name)
    expect(menu).to_be_visible(timeout=10000)
    return menu


def test_a_node_card_opens_an_app_menu_on_right_click(
    app_frontend, current_server, page
):
    """The Node Catalog answers the gesture itself, with the drawer's actions."""
    _login(page, app_frontend, current_server)
    card = _card(page, app_frontend.base_url, "/catalog/nodes", "Node Catalog", PACKAGE_NAME)

    card.click(button="right")
    menu = _menu(page, "Package actions")

    # Exactly what the drawer offers for an uninstalled package, in the drawer's
    # own order: the primary action, then the way out. No Publish - that control
    # carries a confirmation of its own and stays in the drawer.
    expect(menu.get_by_role("menuitem")).to_have_text(
        ["Add to all projects", "View details"], timeout=10000
    )

    # And the rows do something: this is the same modal the card's own "View
    # details" button opens.
    menu.get_by_role("menuitem", name="View details").click()
    expect(page.get_by_role("dialog")).to_be_visible(timeout=10000)


def test_an_agent_card_opens_an_app_menu_on_right_click(
    app_frontend, current_server, page
):
    """Same gesture, same shape of answer, on the third catalog."""
    _login(page, app_frontend, current_server)
    card = _card(page, app_frontend.base_url, "/catalog/agents", "Agent Catalog", AGENT_NAME)

    card.click(button="right")
    menu = _menu(page, "Agent actions")
    expect(menu.get_by_role("menuitem")).to_have_text(
        ["Add to all projects", "View details"], timeout=10000
    )


def test_escape_closes_the_menu(app_frontend, current_server, page):
    """The projects page's inline menu had no Escape; the shared one does."""
    _login(page, app_frontend, current_server)
    card = _card(page, app_frontend.base_url, "/catalog/nodes", "Node Catalog", PACKAGE_NAME)

    card.click(button="right")
    menu = _menu(page, "Package actions")
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0, timeout=10000)
