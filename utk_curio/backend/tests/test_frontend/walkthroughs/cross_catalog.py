"""Scenes on what the Data, Node and Agent catalogs share: confirming an add,
the remove dialog, and the toast that reports an add.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import accept_confirm_dialog
from .framework import Ctx, walkthrough
from .agent_catalog import open_agent_drawer


# ---------------------------------------------------------------------------
# Cross-catalog consistency (#196, #197, #198)
# ---------------------------------------------------------------------------

DATA_DRAWER_ROOT = '[data-curio-dataset-catalog-drawer="true"]'
NODE_DRAWER_ROOT = '[data-curio-node-catalog-drawer="true"]'

#: The toast region ToastProvider portals into. Clipping to it keeps a 0.02
#: budget spent on the toast rather than on the whole canvas behind it.
TOAST_REGION = '[aria-label="Notifications"]'


def open_data_drawer(ctx: Ctx):
    """The top bar's Data Catalog button, returning the drawer dialog."""
    page = ctx.page
    ctx.click(page.get_by_role("button", name="Data Catalog", exact=True))
    root = page.locator(DATA_DRAWER_ROOT)
    root.wait_for(state="attached", timeout=15000)
    # aria-hidden IS the presented signal: until the rAF flips it, every role
    # query inside the subtree returns zero matches.
    expect(root).to_have_attribute("aria-hidden", "false", timeout=10000)
    dialog = page.get_by_role("dialog").filter(
        has=page.get_by_role("heading", name="Data Catalog", exact=True)
    )
    dialog.wait_for(state="visible", timeout=15000)
    ctx.beat(600)
    return dialog


def confirm_modal(ctx: Ctx, title):
    """The open ConfirmDialog, by accessible name.

    A bare ``get_by_role("dialog")`` cannot be used while a drawer is open:
    the drawers carry ``role="dialog"`` too, so the query matches both.
    ConfirmDialog wires its heading through ``aria-labelledby``, which makes
    the name unique.
    """
    modal = ctx.page.get_by_role("dialog", name=title)
    modal.wait_for(state="visible", timeout=15000)
    return modal


@walkthrough(
    slug="catalog-add-is-confirmed",
    refs=[196],
    title="Adding from a catalog asks first",
    premise="Add a dataset and an agent, and read the confirmation each one raises.",
    note="Only the Node catalog confirmed an add, through its permissions "
         "dialog; Data and Agent committed a lockfile write on a single "
         "click with nothing to cancel. Both now raise a ConfirmDialog, and "
         "the agent one lists the dependencies the add will pull in with it.",
    tests=["src/tests/catalog/useDatasetCatalogDrawer.import.test.ts",
           "src/tests/catalog/AgentCatalogDrawer.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def catalog_add_is_confirmed(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The Data Catalog", "Adding a dataset used to commit on one click.")
    drawer = open_data_drawer(ctx)

    add = drawer.get_by_role("button", name="Add to project", exact=True).first
    add.wait_for(state="visible", timeout=20000)
    ctx.click(add)

    modal = confirm_modal(ctx, re.compile(r"^Add "))
    ctx.focus(modal, hold=1400)
    ctx.say("It asks first", "Cancel leaves the dataflow exactly as it was.")
    ctx.capture("data-add-confirm")

    # Cancel really cancels: the card still offers Add afterwards.
    ctx.click(modal.get_by_role("button", name="Cancel", exact=True))
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.get_by_role("button", name="Add to project", exact=True).first
    ).to_be_visible(timeout=10000)

    close = drawer.get_by_role("button", name="Close Data Catalog drawer")
    if close.count():
        ctx.click(close.first)
        page.locator(DATA_DRAWER_ROOT).wait_for(state="detached", timeout=10000)

    ctx.say("The Agent Catalog", "The same question, and it discloses more.")
    agent_drawer = open_agent_drawer(ctx)
    # An agent that requires others, so the dialog has dependencies to name.
    agent_add = agent_drawer.get_by_role(
        "button", name=re.compile(r"^Add to project \(\+\d+ required\)")
    ).first
    agent_add.wait_for(state="visible", timeout=20000)
    ctx.click(agent_add)

    agent_modal = confirm_modal(ctx, re.compile(r"^Add "))
    ctx.focus(agent_modal, hold=1400)
    ctx.say("Dependencies are named before the click commits",
            "An agent that requires another says so here, not afterwards.")
    ctx.capture("agent-add-confirm")

    ctx.click(agent_modal.get_by_role("button", name="Cancel", exact=True))
    expect(agent_modal).to_have_count(0, timeout=10000)


@walkthrough(
    slug="catalog-remove-is-an-app-dialog",
    refs=[197],
    title="Removing uses the app's own dialog",
    premise="Remove an agent from the dataflow and read the confirmation.",
    note="Every confirmation in the catalogs was a native `window.confirm`: "
         "unstyled, unthemed, outside the app's modal stack, and carrying the "
         "browser's own chrome and origin line. They are ConfirmDialogs now, "
         "built on the same ModalShell as every other modal, so Escape and "
         "the backdrop cancel and the drawer behind stays put.",
    tests=["src/tests/components/ConfirmDialog.test.tsx",
           "src/tests/catalog/canvasDrawerParity.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    fit_reactflow=False,
    max_diff_ratio=0.03,
)
def catalog_remove_is_an_app_dialog(ctx: Ctx) -> None:
    page = ctx.page

    drawer = open_agent_drawer(ctx)

    # Put one in the dataflow first, so there is something to remove.
    add = drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    add.wait_for(state="visible", timeout=20000)
    ctx.click(add)
    accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to project")

    remove = drawer.get_by_role("button", name="Remove from project", exact=True).first
    remove.wait_for(state="visible", timeout=30000)

    ctx.say("Remove it again", "This is where the browser's own box used to appear.")
    ctx.click(remove)

    modal = confirm_modal(ctx, re.compile(r"^Remove "))
    ctx.focus(modal, hold=1500)
    ctx.say("The app's dialog, not the browser's",
            "Same shell, same theme, same Escape-to-cancel as every other modal.")
    ctx.capture("remove-confirm")

    ctx.click(modal.get_by_role("button", name="Remove", exact=True))
    expect(modal).to_have_count(0, timeout=10000)
    expect(
        drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    ).to_be_visible(timeout=30000)
    ctx.say("Removed", "And the drawer behind it never went anywhere.")


@walkthrough(
    slug="catalog-add-reports-success",
    refs=[198],
    title="A completed add says so",
    premise="Add an agent and watch the catalog confirm it landed.",
    note="Only the Data catalog reported an add. The Node and Agent catalogs "
         "finished in silence, which on a slow install reads as nothing "
         "having happened. All three now toast the same two sentences, and "
         "ask for the success variant explicitly - showToast defaults to "
         "error, so an omitted variant painted a successful add red.",
    tests=["src/tests/catalog/useAgentCatalogDrawer.test.ts",
           "src/tests/catalog/catalogDrawerParity.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    clip_selector=TOAST_REGION,
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline (5.8% of pixels on CI, run to run stable), so the pin
    # must leave room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def catalog_add_reports_success(ctx: Ctx) -> None:
    page = ctx.page

    drawer = open_agent_drawer(ctx)
    add = drawer.get_by_role("button", name=re.compile(r"^Add to project")).first
    add.wait_for(state="visible", timeout=20000)

    ctx.say("Add an agent", "The Agent catalog used to finish in silence.")
    ctx.click(add)
    accept_confirm_dialog(page, title=re.compile(r"^Add "), button="Add to project")

    toast = page.locator(TOAST_REGION).get_by_text(
        re.compile(r"^Added .+ to this project\.$")
    )
    toast.first.wait_for(state="visible", timeout=30000)
    ctx.focus(toast.first, hold=1500)
    ctx.say("It says so now",
            "The same sentence the Data catalog has always used.")
    ctx.capture("add-toast")
