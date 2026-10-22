"""Open and close the canvas's left-rail tool palettes."""

from playwright.sync_api import expect


_TOOLS_PALETTES = {
    "builtin": ("#builtin-palette", "Open built-in palette", "Built-in palette"),
    "packages": ("#packages-palette", "Open node package palette", "Package templates"),
    "datasets": ("#datasets-palette", "Open dataset palette", "Dataset palette"),
    "agents": ("#agents-palette", "Open agent palette", "Agent palette"),
    "models": ("#models-palette", "Open model palette", "Model palette"),
}


def open_tools_palette(page, kind: str):
    """Open one of the left-rail tool palettes and return its panel locator.

    Re-callable: the trigger's ``title`` flips to ``Close …`` once open, so this
    matches either title and only clicks when the panel is not already showing.
    That matters for a test that needs both palettes, because they are mutually
    exclusive (``ToolsMenu`` keeps a single ``activePalette``) and opening one
    closes the other, so coming back to the first one is a normal thing to do.

    No ``force`` (#994). A forced click skips Playwright's stable and hit-target
    checks, so a press aimed at a trigger that moves before the press lands on
    whatever took its place. In #994 the built-in tiles still filled in the
    rail after each load and pushed the triggers about 240 px down, and the
    press landed on the Data Pool tile. Without ``force``, Playwright waits for
    the trigger to hold still and retries a press that anything else would
    receive. The dock sits above the canvas pane (``position: fixed``,
    ``z-index: 100``), so nothing else covers a trigger.
    ``test_rail_fills_in_e2e`` holds both: this click under a trigger that
    moves, and a rail that no answer of the registry moves.
    """
    try:
        root_sel, trigger_title, panel_name = _TOOLS_PALETTES[kind]
    except KeyError:
        raise ValueError(
            f"kind must be one of {sorted(_TOOLS_PALETTES)}, got {kind!r}"
        ) from None
    close_title = trigger_title.replace("Open ", "Close ", 1)
    trigger = page.locator(
        f'{root_sel} button[data-tooltip="{trigger_title}"], '
        f'{root_sel} button[data-tooltip="{close_title}"]'
    )
    trigger.wait_for(state="visible", timeout=30000)
    panel = page.locator(root_sel).get_by_role("region", name=panel_name)
    if panel.count() == 0 or not panel.first.is_visible():
        trigger.click()
    panel.wait_for(state="visible", timeout=10000)
    return panel


def tools_palette_is_open(page, kind: str) -> bool:
    """Whether one of the left-rail tool palettes is showing its panel."""
    try:
        root_sel, _trigger_title, panel_name = _TOOLS_PALETTES[kind]
    except KeyError:
        raise ValueError(
            f"kind must be one of {sorted(_TOOLS_PALETTES)}, got {kind!r}"
        ) from None
    panel = page.locator(root_sel).get_by_role("region", name=panel_name)
    return panel.count() > 0 and panel.first.is_visible()


def click_package_summary_action(page, anchor, title: str):
    """Click one of a package row's summary actions ("Export package", "Edit
    package metadata") only once the row has stopped moving.

    Not a plain ``click(force=True)``, because that is issue #334's "download
    never arrives".

    The palette renders its rows from the installed-package registry, but the
    ``CatalogPublishPill`` in each row's summary waits on a separate catalog
    snapshot (three parallel API calls behind one ``setState``). The summary's
    actions live in a flex cluster whose title is ``flex: 1``, so it absorbs the
    slack: when that pill finally mounts, every button to its left jumps ~65px
    left - measured, not estimated.

    ``force=True`` turns off Playwright's hit-target check, so a click aimed at
    Export and dispatched just after that jump lands on Publish instead. The
    confirm dialog opens, its overlay covers the palette, the export is never
    requested, and the test sits out its whole budget waiting for a download
    that was never going to come. Under CI load the snapshot lands later, which
    is why it read as "CI load".

    Two guards, so neither has to be perfect: wait for the palette to report
    its catalog snapshot in, and then click WITHOUT ``force`` so Playwright
    verifies the button is what actually receives the click.
    """
    expect(
        page.locator('#packages-palette [data-curio-palette-catalog]')
    ).to_have_attribute("data-curio-palette-catalog", "loaded", timeout=30000)
    button = anchor.locator(f'button[data-tooltip="{title}"]')
    expect(button).to_be_visible(timeout=20000)
    button.click()


def close_tools_palette(page, kind: str) -> None:
    """Close a left-rail tool palette, if it is open.

    The open panel is ~545px wide and floats *over* the canvas, so it covers the
    left third of the drop area. That is invisible to ``drag_to_canvas`` (which
    dispatches its drop on the pane directly, without hit-testing) but not to
    ``connect_nodes``, which fails when another element is topmost at a handle's
    centre. A test that drops a dataset row and then wires the graph therefore
    has to give the canvas back once the row has been dragged.

    Idempotent and safe to call when nothing is open, mirroring
    ``open_tools_palette``.
    """
    try:
        root_sel, trigger_title, panel_name = _TOOLS_PALETTES[kind]
    except KeyError:
        raise ValueError(
            f"kind must be one of {sorted(_TOOLS_PALETTES)}, got {kind!r}"
        ) from None
    panel = page.locator(root_sel).get_by_role("region", name=panel_name)
    if panel.count() == 0 or not panel.first.is_visible():
        return
    close_title = trigger_title.replace("Open ", "Close ", 1)
    # No ``force``, for the reason ``open_tools_palette`` gives (#994).
    page.locator(f'{root_sel} button[data-tooltip="{close_title}"]').click()
    panel.first.wait_for(state="hidden", timeout=10000)
