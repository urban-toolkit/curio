"""In-app dialogs: accept a catalog's confirmation, wait for a slide drawer to
close, take focus off the agent badge once its chat closes, open the menu of
the agent chat's plan line, and show the chat's run details.
"""

import re

from playwright.sync_api import (
    Locator,
    Page,
    expect,
)

#: The plan line's menu of builds, by its button's and its menu's name
#: (AgentBuilderStrip.tsx's PLAN_ACTIONS).
PLAN_ACTIONS = "More plan actions"


def accept_confirm_dialog(
    page: Page,
    *,
    title,
    button: str,
    timeout: float = 10000,
):
    """Accept the in-app confirmation a catalog raises (#196, #197).

    The three catalogs replaced ``window.confirm`` with a ``ConfirmDialog``
    built on ``ModalShell``, so ``page.once("dialog", ...)`` no longer fires -
    a test still relying on it clicks the card button and then silently does
    nothing, and fails later for the wrong reason.

    The drawers are themselves ``role="dialog"``, so a bare
    ``get_by_role("dialog")`` is ambiguous whenever one is open. The modal is
    located by its accessible name instead, which ConfirmDialog wires from its
    heading through ``aria-labelledby``.

    ``title`` takes a string or a compiled pattern; ``button`` is the confirm
    button's exact label (it often repeats the card's, e.g. "Add to project").
    Returns the dialog locator so a caller can assert on its body first.
    """
    dialog = page.get_by_role("dialog", name=title)
    expect(dialog).to_be_visible(timeout=timeout)
    dialog.get_by_role("button", name=button, exact=True).click()
    expect(dialog).to_have_count(0, timeout=timeout)
    return dialog


def wait_for_drawer_closed(page: Page, root: str, *, timeout: float = 10000) -> None:
    """Wait for a slide drawer to close after Escape or a close click.

    ``root`` is the attribute selector of the drawer's overlay root, such as
    ``'[data-curio-scenario-catalog-drawer="true"]'``; the helper appends to it.

    A drawer from ``useSlideDrawerPresentation`` closes in two forms: it stays
    mounted with ``aria-hidden="true"`` for its exit slide, then unmounts. Under
    reduced motion the exit timer is 0 ms, so the hidden form can be gone
    before a wait for it starts. This waits until no copy of the root is open
    (each one hidden, or none left), which either form satisfies, and then
    until the root is no longer visible. A drawer that stays open fails both.
    The second wait has to retry: the mounted root is a full-window box, so
    Playwright reports it visible until it unmounts.
    """
    expect(page.locator(f'{root}:not([aria-hidden="true"])')).to_have_count(0, timeout=timeout)
    expect(page.locator(root)).to_be_hidden(timeout=timeout)


def leave_agent_badge(page: Page) -> None:
    """Take focus and the pointer off the agent's badge after a chat closes.

    Closing the chat hands focus back to the button that opened it, and the
    badge shows its name label and detach x while it has focus or hover, so
    both would otherwise sit in a canvas capture.
    """
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.mouse.move(0, 400)
    page.wait_for_function(
        "() => !document.querySelector('[aria-label^=\"Open chat with\"]:focus')",
        timeout=5000,
    )


def open_plan_actions(panel: Locator, *, timeout: float = 20000) -> Locator:
    """Open the menu beside the Dataflow Builder's plan line in *panel*, More
    plan actions, and return it: Build & validate plan and Step, each a
    menuitem whose name starts with its own and goes on with what it does.
    The line offers it while a landed plan has nodes left to build and
    nothing runs over it. A menu already open stays open."""
    menu = panel.get_by_role("menu", name=PLAN_ACTIONS, exact=True)
    if menu.count():
        return menu
    toggle = panel.get_by_role("button", name=PLAN_ACTIONS, exact=True)
    expect(toggle).to_be_visible(timeout=timeout)
    toggle.click()
    expect(menu).to_be_visible(timeout=timeout)
    return menu


def open_plan_details(card: Locator, *, timeout: float = 20000) -> Locator:
    """Open a landed plan's **Details** on its *card* (a ``Change: Plan``
    group) and return them: the plan's goal, its checks, each node's template
    and what it reads and writes, its connections and its scenarios. Details
    already open stay open."""
    details = card.get_by_role("group", name="Plan details", exact=True)
    if details.count():
        return details
    toggle = card.get_by_role("button", name="Details", exact=True)
    expect(toggle).to_be_visible(timeout=timeout)
    toggle.click()
    expect(details).to_be_visible(timeout=timeout)
    return details


def show_run_details(panel: Locator, on: bool = True, *, timeout: float = 20000) -> None:
    """Turn Show run details on in *panel*'s More menu, or off with *on*
    False: each reply's skills, time, tokens and tools, and the cards of its
    trace. The viewer's own setting, kept in the browser for every chat, so a
    test whose page later tests share turns it off again; a setting already
    as asked is left as it is."""
    more = panel.get_by_role("button", name=re.compile(r"^More: "))
    more.click()
    item = panel.get_by_role("menuitemcheckbox", name=re.compile(r"^Show run details"))
    expect(item).to_be_visible(timeout=timeout)
    if (item.get_attribute("aria-checked") == "true") == on:
        # Already as asked: More closes its menu, and it stays so.
        more.click()
    else:
        item.click()
    expect(item).to_have_count(0, timeout=timeout)
