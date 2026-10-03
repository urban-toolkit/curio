"""In-app dialogs: accept a catalog's confirmation, and take focus off the agent
badge once its chat closes.
"""

from playwright.sync_api import (
    Page,
    expect,
)


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
