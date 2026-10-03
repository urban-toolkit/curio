"""Scenes on the Agent Catalog drawer and page, on a dataflow not yet saved."""
from __future__ import annotations

import re

from ..utils import accept_confirm_dialog
from .framework import Ctx, walkthrough


# ---------------------------------------------------------------------------
# Agent Catalog
# ---------------------------------------------------------------------------

AGENT_DRAWER_ROOT = '[data-curio-agent-catalog-drawer="true"]'

#: The catalog PAGES' detail drawer (/catalog/data, /catalog/nodes,
#: /catalog/agents). Distinct from the canvas drawers above: the account-level
#: actions live here, not on a card and not in the canvas.
BROWSE_DRAWER_ROOT = '[data-curio-browse-drawer="true"]'

#: The tag row inside a browse card, on any of the three catalog pages. Every
#: page renders many cards, and a clip must resolve to exactly one element, so
#: the scene takes the first: the claim is about chips *within one card*, and any
#: card demonstrates it.
TAG_ROW_FIRST_CARD = '[data-curio-tag-row="true"] >> nth=0'

#: The browse drawer's CTA row, where the long "Remove from all projects" label
#: lives. One drawer is open at a time, so this is unambiguous.
BROWSE_DRAWER_CTAS = '[data-curio-drawer-ctas="true"]' 


def open_agent_drawer(ctx: Ctx):
    """The top bar's Agent Catalog button, returning the drawer dialog."""
    page = ctx.page
    # "Agent Catalog" also labels the left-rail palette trigger, whose
    # accessible name carries a count; exact=True picks the top bar's button.
    ctx.click(page.get_by_role("button", name="Agent Catalog", exact=True))
    page.locator(AGENT_DRAWER_ROOT).wait_for(state="attached", timeout=15000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Agent Catalog", exact=True)
    )
    dialog.wait_for(state="visible", timeout=15000)
    ctx.beat(600)
    return dialog


def fits_on_one_line(button) -> dict:
    """Whether a button's label stays inside its box.

    ``scrollHeight`` beyond ``clientHeight`` is the wrap; ``scrollWidth`` beyond
    ``clientWidth`` is the ellipsis. Reported together so a failure says which.
    """
    return button.evaluate(
        "el => ({ text: el.textContent.trim(),"
        " clientH: el.clientHeight, scrollH: el.scrollHeight,"
        " clientW: el.clientWidth, scrollW: el.scrollWidth,"
        " fontSize: getComputedStyle(el).fontSize })"
    )


@walkthrough(
    slug="agent-catalog-adding-to-an-unsaved-dataflow",
    refs=[190, 199],
    title="Adding an agent to a dataflow you have not saved",
    premise="Open the Agent Catalog on a fresh dataflow and add an agent to it.",
    note="The Add button was disabled whenever `projectId` was null, which is "
         "the ordinary state of a dataflow you just made. It now resolves the "
         "dataflow at click time through the shared `ensureProjectId`, the way "
         "the Data and Node catalogs already did.",
    tests=["src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=AGENT_DRAWER_ROOT,
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def agent_catalog_adding_to_an_unsaved_dataflow(ctx: Ctx) -> None:
    page = ctx.page

    # The harness seeds a SAVED project, and on one of those the button was
    # never disabled - so this journey has to leave it. `/dataflow/new` is the
    # route a brand-new dataflow sits on until something persists it, and
    # `projectId` is null for exactly that long.
    page.goto(f"{ctx.frontend}/dataflow/new")
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    # Narrate after the navigation, not before: captioning "a brand-new
    # dataflow" over the previous one is a recording that argues with itself.
    ctx.say("A brand-new dataflow", "Nothing has saved it yet.")
    assert page.url.rstrip("/").endswith("/dataflow/new"), (
        f"expected to be on an unsaved dataflow, but the URL is {page.url} - "
        f"something saved it and this journey would prove nothing"
    )
    ctx.beat(700)

    # The save indicator states what is on disk, so it is most worth reading
    # exactly here - where the answer is "nothing". It used to be absent on a
    # never-saved dataflow, which is how this went unnoticed.
    disk = page.locator("[data-curio-save-state]")
    disk.wait_for(state="visible", timeout=15000)
    assert disk.get_attribute("data-curio-save-state") == "unsaved", (
        f"the save indicator reads "
        f"{disk.get_attribute('data-curio-save-state')!r} on a dataflow that "
        f"has never been saved"
    )
    ctx.focus(disk, hold=1100)
    ctx.say("Nothing is on disk yet", "The save indicator is orange.")

    dialog = open_agent_drawer(ctx)

    ctx.say("The Agent Catalog", "Open on a dataflow that has never been saved.")
    # The unsaved-dataflow banner was removed from all three catalogs: it only
    # ever appeared on an unsaved dataflow, so it read as a state the other
    # surfaces did not have, and the add already explains itself twice over -
    # the confirmation says what it will do, the save indicator shows it done.
    assert not dialog.get_by_text("isn't saved yet", exact=False).count(), (
        "the unsaved-dataflow banner is back; it was removed for repeating "
        "what the confirmation and the save indicator already say"
    )

    add = dialog.get_by_role("button", name="Add to project").first
    add.wait_for(state="visible", timeout=15000)
    assert add.is_enabled(), (
        "Add to project is disabled on an unsaved dataflow - the drawer is "
        "still gating on a project id instead of creating one on the click"
    )
    ctx.capture("add-enabled")

    ctx.say("Add it", "The dataflow is saved first, then the agent goes in.")
    ctx.click(add)

    # Adding confirms first now (#196), the way all three catalogs do.
    accept_confirm_dialog(
        ctx.page, title=re.compile(r"^Add "), button="Add to project"
    )
    # The confirm button sat over a card, which would stay hovered.
    page.mouse.move(0, 400)

    installed = dialog.get_by_role("button", name="Remove from project").first
    installed.wait_for(state="visible", timeout=30000)

    # The save really happened: the route carries a project id now.
    page.wait_for_url(lambda url: "/dataflow/new" not in url, timeout=20000)
    assert "/dataflow/new" not in page.url, (
        f"the agent was added but the dataflow was never saved (still at "
        f"{page.url})"
    )
    ctx.capture("agent-added")

    # And the indicator agrees: the add wrote the dataflow to disk.
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=20000,
    )
    ctx.say("Added, and the dataflow saved itself",
            "The URL carries a real id now, and the indicator has gone green.")


@walkthrough(
    slug="agent-catalog-account-agent-on-an-unsaved-dataflow",
    refs=[190, 199],
    title="An agent you already have, on a dataflow you have not saved",
    premise="Add an agent to every project, then open the Agent Catalog on a new dataflow.",
    note="The sibling scene covers a fresh account, where every card offers Add. "
         "An account that already holds the agent takes the other branch: "
         "`inThisDataflow` counts it as present, so the card renders Remove - and "
         "Remove was still gated on `hasProject`, which is null until the first "
         "save. The result was a disabled control and nothing else, which is the "
         "symptom #190 and #199 both report, reached through a different door. "
         "Remove now creates the dataflow on the click, exactly as Add does.",
    tests=["src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=AGENT_DRAWER_ROOT,
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def agent_catalog_account_agent_on_an_unsaved_dataflow(ctx: Ctx) -> None:
    page = ctx.page

    # Put the agent in the ACCOUNT first, through the UI. "Add to all projects"
    # on the catalog page posts /api/agents/imports, which is what sets
    # `imported` - the flag the drawer then reads to decide Add versus Remove.
    ctx.say("Add an agent to every project", "An account-level decision, made on the catalog page.")
    page.goto(f"{ctx.frontend}/catalog/agents")
    page.wait_for_load_state("domcontentloaded")
    browse_drawer = page.locator(BROWSE_DRAWER_ROOT)
    browse_drawer.wait_for(state="visible", timeout=30000)

    add_to_all = browse_drawer.get_by_role("button", name="Add to all projects")
    if add_to_all.count():
        ctx.click(add_to_all.first)
        browse_drawer.get_by_role(
            "button", name="Remove from all projects"
        ).first.wait_for(state="visible", timeout=30000)
    coord = page.locator("article[data-agent-coord]").first.get_attribute(
        "data-agent-coord"
    )
    assert coord, "no agent card to read a coordinate from"

    # Now a dataflow that has never been saved.
    ctx.say("A brand-new dataflow", "Nothing has saved it yet.")
    page.goto(f"{ctx.frontend}/dataflow/new")
    page.wait_for_url("**/dataflow/new", timeout=20000)
    page.locator("#tools-menu").wait_for(state="visible", timeout=45000)
    disk = page.locator("[data-curio-save-state]")
    disk.wait_for(state="visible", timeout=15000)
    assert disk.get_attribute("data-curio-save-state") == "unsaved", (
        f"the save indicator reads "
        f"{disk.get_attribute('data-curio-save-state')!r} on a dataflow that "
        f"has never been saved"
    )

    dialog = open_agent_drawer(ctx)
    card = dialog.locator(f'article[data-agent-coord="{coord}"]')
    card.wait_for(state="visible", timeout=30000)

    # THE POINT: the account already holds it, so this card shows Remove - and
    # that control has to be usable. It was disabled, with a tooltip telling the
    # user to go and save first, on a surface whose Add button saves for them.
    remove = card.get_by_role("button", name="Remove from project", exact=True)
    remove.wait_for(state="visible", timeout=30000)
    assert remove.is_enabled(), (
        "Remove from project is disabled on an unsaved dataflow, so an agent "
        "the account already holds offers no usable control at all - the drawer "
        "is still gating on a project id instead of creating one on the click"
    )
    ctx.focus(remove, hold=1200)
    ctx.capture("remove-enabled-on-unsaved-dataflow")

    ctx.say("Remove it", "The dataflow is saved first, then the agent comes out.")
    ctx.click(remove)
    accept_confirm_dialog(page, title=re.compile(r"^Remove "), button="Remove")
    # The confirm button sat over a card, which would stay hovered.
    page.mouse.move(0, 400)

    # The save really happened, and the card flipped to the other branch.
    page.wait_for_url(lambda url: "/dataflow/new" not in url, timeout=30000)
    card.get_by_role("button", name=re.compile(r"^Add to project")).first.wait_for(
        state="visible", timeout=30000
    )
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=20000,
    )
    ctx.capture("removed-and-saved")
    ctx.say("Removed, and the dataflow saved itself",
            "The same one-click save the Add path already did.")


@walkthrough(
    slug="agent-catalog-action-labels-fit",
    refs=[191],
    title="Agent action labels fit their button",
    premise="Read the account-level actions on an agent, where the longest label lives.",
    note="The reported overflow was on the agent drawer's card column, pinned at "
         "140px, where \"Remove from all projects\" wrapped inside a 30px box and "
         "spilled out. That control has since moved: account-level actions are "
         "decisions about an item, not about one dataflow, so they live on the "
         "Agent Catalog page's detail drawer now. This scene follows the label - "
         "the claim is unchanged, only its address.",
    tests=["src/tests/styles/agentDrawerButtonGeometry.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    # The claim is whether one label fits one button, so the capture is that
    # button's row rather than the whole 320x607 drawer (#333). At the drawer
    # size the CTA row was a few percent of the frame, so a 10% budget could not
    # have seen the label wrap that this scene exists to catch. On the row
    # itself, a wrap is most of the picture.
    clip_selector=BROWSE_DRAWER_CTAS,
    fit_reactflow=False,
    # Measured, not guessed. The baseline was minted on Linux and compared
    # against the render CI actually produced (recovered from the full-page
    # baseline this PR replaces, 9f27df5e): 5.89%. The same crop taken on macOS
    # scores 10.05% against that render, i.e. a macOS baseline would have failed
    # here outright, which is why these are minted on Linux.
    #
    # 5.89% leaves less headroom than the sibling scene below, so this one keeps
    # the wider budget. Part of that 5.89% is probably drift in the drawer since
    # that baseline was recorded rather than platform, but it cannot be
    # separated from here, and a budget set from the pessimistic reading is the
    # one that does not page someone at 3am.
    max_diff_ratio=0.08,
)
def agent_catalog_action_labels_fit(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The Agent Catalog page", "Where the account-level actions live.")
    page.goto(f"{ctx.frontend}/catalog/agents")
    page.wait_for_load_state("domcontentloaded")

    # The page auto-selects the first card so the drawer arrives populated.
    drawer = page.locator(BROWSE_DRAWER_ROOT)
    drawer.wait_for(state="visible", timeout=30000)

    # "Remove from all projects" is the longest label in the product, and it
    # only renders once the agent is in the account. Whether it already is
    # depends on leftover per-user state, so reach the state rather than assume
    # it: `primaryAction` toggles on `agent.imported`.
    add = drawer.get_by_role("button", name="Add to all projects")
    if add.count():
        ctx.say("Add it to every project", "That is what puts the long label on screen.")
        ctx.click(add.first)

    remove = drawer.get_by_role("button", name="Remove from all projects").first
    remove.wait_for(state="visible", timeout=30000)
    ctx.focus(remove, hold=1200)

    box = fits_on_one_line(remove)
    assert box["scrollH"] <= box["clientH"] + 1, (
        f"\"{box['text']}\" wraps inside its button at {box['fontSize']}: "
        f"content is {box['scrollH']}px tall in a {box['clientH']}px box, so it "
        f"spills past the border"
    )
    assert box["scrollW"] <= box["clientW"] + 1, (
        f"\"{box['text']}\" is clipped at {box['fontSize']}: content is "
        f"{box['scrollW']}px wide in a {box['clientW']}px box"
    )

    # Every button in the drawer's action bar, not just the reported one.
    for name in ("Remove from all projects", "Add to all projects", "View details"):
        button = drawer.get_by_role("button", name=name).first
        if not button.count():
            continue
        metrics = fits_on_one_line(button)
        assert metrics["scrollH"] <= metrics["clientH"] + 1, (
            f"\"{metrics['text']}\" overflows its button: {metrics}"
        )

    ctx.capture("labels-fit")
    ctx.say("Every label inside its button",
            "The longest one in the product, on the surface that now owns it.")
