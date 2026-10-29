"""The open dataflow's scenarios: the Scenario Catalog drawer's In project tab.

Each scenario is a card there with Run scenario, Collapse or Expand, Add
selected, Remove selected and Delete, and its details hold its name, color and
description and list its fixed context, levers and outcomes. Every scenario
test reaches them through these helpers.

The drawer's scrim covers the whole window, the top bar and the canvas
included, so a test closes it (:func:`close_scenario_drawer`) before it saves,
runs, drags or captures anything on the canvas.
"""

import re

from playwright.sync_api import Page, expect

from .dialogs import wait_for_drawer_closed

#: The drawer's overlay root.
SCENARIO_DRAWER = '[data-curio-scenario-catalog-drawer="true"]'

_OPEN = f'{SCENARIO_DRAWER}[aria-hidden="false"]'
_IN_PROJECT_TAB = re.compile(r"^In project")
_DETAILS = "Scenario details"

# Open, or not there at all: not sliding in or out.
_SETTLED_JS = """(root) => {
    const el = document.querySelector(root);
    return !el || el.getAttribute('aria-hidden') === 'false';
}"""


def open_in_project_tab(page: Page, *, opened_by_command: bool = False, timeout: float = 15000):
    """Show the open dataflow's scenarios, and return the drawer.

    The drawer opens from the top bar's Scenario Catalog button, unless it is
    open already. Save selection as scenario, Save dataflow as scenario and
    Duplicate as scenario open it on this tab themselves: after one of them,
    *opened_by_command* checks that it did, with no click on the button and
    no click on the tab. A drawer still sliding in or out is waited for
    first, so the button is never clicked under its scrim.
    """
    page.wait_for_function(_SETTLED_JS, arg=SCENARIO_DRAWER, timeout=timeout)
    drawer = page.locator(_OPEN)
    if opened_by_command:
        expect(drawer).to_have_count(1, timeout=timeout)
        expect(drawer.get_by_role("button", name=_IN_PROJECT_TAB)).to_have_attribute(
            "aria-pressed", "true", timeout=timeout
        )
        return drawer
    if drawer.count() == 0:
        page.get_by_role("button", name="Scenario Catalog", exact=True).click()
    expect(drawer).to_have_count(1, timeout=timeout)
    tab = drawer.get_by_role("button", name=_IN_PROJECT_TAB)
    if tab.get_attribute("aria-pressed") != "true":
        tab.click()
    expect(tab).to_have_attribute("aria-pressed", "true", timeout=timeout)
    return drawer


def in_project_card(page: Page, scenario_id: str):
    """The scenario's card in the open drawer's In project tab."""
    return page.locator(f'{_OPEN} [data-testid="scenario-card-{scenario_id}"]')


def scenario_card_button(page: Page, scenario_id: str, name: str):
    """One of the card's buttons: Run scenario, Collapse, Expand, Add
    selected, Remove selected or Delete."""
    return in_project_card(page, scenario_id).get_by_role("button", name=name, exact=True)


def close_scenario_drawer(page: Page, *, timeout: float = 10000) -> None:
    """Close the drawer with Escape, and wait until it is gone."""
    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, SCENARIO_DRAWER, timeout=timeout)


def open_scenario_details(page: Page, scenario_id: str, *, timeout: float = 10000):
    """Open the scenario's details from its In project card, and return them."""
    card = in_project_card(page, scenario_id)
    card.get_by_role("button", name=re.compile(r"^View .+ details$")).click()
    modal = page.get_by_role("dialog", name=_DETAILS)
    expect(modal).to_be_visible(timeout=timeout)
    return modal


def close_scenario_details(page: Page, *, timeout: float = 10000) -> None:
    """Close the details with their Close button. The drawer stays open."""
    modal = page.get_by_role("dialog", name=_DETAILS)
    modal.get_by_role("button", name="Close", exact=True).click()
    expect(modal).to_have_count(0, timeout=timeout)


def scenario_part(modal, part: str) -> str:
    """The text of one list in the details: "Shared context", "Scenario-specific nodes" or
    "Shared outcomes"."""
    return modal.get_by_role("region", name=part).inner_text()
