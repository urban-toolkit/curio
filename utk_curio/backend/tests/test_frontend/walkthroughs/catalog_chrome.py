"""The scene on the catalog details panel and the version badge."""
from __future__ import annotations

import re

from .framework import Ctx, walkthrough
from .provenance import PROVENANCE_EXAMPLE


# ---------------------------------------------------------------------------
# Catalog chrome (#236)
# ---------------------------------------------------------------------------

@walkthrough(
    slug="catalog-details-clear-the-version-badge",
    refs=[236],
    title="The details panel leaves the version badge alone",
    premise="Open a catalog item's details panel and read the bottom-right corner.",
    note="The badge is `position: fixed` at bottom-right with a bare z-index of "
         "9999, and nothing between it and the page makes a stacking context - "
         "so it painted ON TOP of the details drawer, grey monospace over the "
         "drawer's dark primary button. The height chain to the drawer is "
         "unbroken to the viewport (.pageShell is 100vh, .browseDrawer is "
         "height:100%), so nothing reserved the corner. The shell now does, "
         "once, for every catalog and both drawers, and the badge sits on the "
         "documented z-scale instead of above everything.",
    tests=["src/tests/styles/zLayerScale.test.ts",
           "test_frontend/test_walkthrough_baselines.py"],
    # The scene leaves for /catalog immediately and has nothing to do with this
    # dataflow. It is named only because the runner waits for a canvas node
    # before handing over, and an empty dataflow never produces one.
    example=PROVENANCE_EXAMPLE,
    fit_reactflow=False,
    # A restored 30px gutter is a small number of pixels; the 0.10 default
    # would not notice it going away again.
    max_diff_ratio=0.05,
)
def catalog_details_clear_the_version_badge(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("Open the Node Catalog", "Any catalog will do - they share one shell.")
    page.goto(f"{ctx.frontend}/catalog/nodes")
    page.wait_for_load_state("networkidle")

    # The first card, whatever it is: the claim is about the drawer's geometry,
    # not about any particular package. `article[data-pkg-dir]` is the card's
    # own hook (PackageBrowseCard), not a hashed CSS-module class.
    card = page.locator("article[data-pkg-dir]").first
    card.wait_for(state="visible", timeout=30000)
    ctx.click(card)

    drawer = page.locator('[data-curio-browse-drawer="true"]').first
    drawer.wait_for(state="visible", timeout=30000)

    ctx.say("Scroll to the bottom of the details",
            "This is where the two used to collide.")
    # The body scrolls, not the drawer (#526).
    drawer.locator('[data-curio-drawer-body="true"]').evaluate(
        "el => el.scrollTo({ top: el.scrollHeight })"
    )
    page.wait_for_timeout(600)

    badge = page.locator("span[title]").filter(has_text=re.compile("isolated", re.I))
    if badge.count() == 0:
        raise AssertionError(
            "no version badge on /catalog - the scene cannot show #236. The "
            "badge only renders once GET /version answers, so this usually "
            "means the backend is unreachable rather than that the badge moved."
        )

    badge_box = badge.first.bounding_box()
    drawer_box = drawer.bounding_box()
    assert badge_box and drawer_box, "could not measure the badge or the drawer"

    # The whole fix is that the drawer stops short of the badge. Overlap is
    # measured rather than eyeballed, so a failure says which way it went.
    overlap = (
        badge_box["x"] < drawer_box["x"] + drawer_box["width"]
        and badge_box["x"] + badge_box["width"] > drawer_box["x"]
        and badge_box["y"] < drawer_box["y"] + drawer_box["height"]
        and badge_box["y"] + badge_box["height"] > drawer_box["y"]
    )
    assert not overlap, (
        f"the details drawer still runs under the version badge: "
        f"badge={badge_box}, drawer={drawer_box}"
    )

    ctx.focus(badge.first, hold=1200)
    ctx.say("The corner is its own", "The drawer ends above it, not behind it.")
    ctx.capture("details-panel-and-version-badge")
