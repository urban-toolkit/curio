"""The scenes on the catalog chrome: the details panel and the version badge,
and the scenario cards' kind color."""
from __future__ import annotations

import re
from contextlib import contextmanager

from playwright.sync_api import expect

from ..utils import api_json
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
    # The package cards and the drawer say how old each package is.
    catalog_calendar=True,
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

    badge = page.locator("span[data-tooltip]").filter(has_text=re.compile("isolated", re.I))
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


# ---------------------------------------------------------------------------
# Scenario cards wear one kind color
# ---------------------------------------------------------------------------

#: Two projects and their scenarios, in the colors the canvas gives them: each
#: project's scenarios take blue, orange and green in turn (``SCENARIO_COLORS``
#: in utils/scenarios/scenarioEdits.ts), so two projects repeat them.
RIVERSIDE_PROJECTS = {
    "Riverside heat": [("Cool roofs", "#3567c7"), ("Street trees", "#e86a3c")],
    "Riverside flood": [
        ("Levee raised", "#3567c7"),
        ("Pumps added", "#e86a3c"),
        ("Marsh restored", "#2f8f4a"),
    ],
}

#: ``--curio-kind-scenario-fg`` (#2E6822), as the browser computes it.
SCENARIO_KIND_FG = "rgb(46, 104, 34)"

#: Each card's name, its strip and border, and the swatches in its title, as
#: drawn. The strip is the card's first child.
#:
#: A selected card's border fades in from transparent over 0.15 s (``.card`` in
#: CatalogBrowseLayout.module.css), and a fade moves only when a frame is
#: drawn, which a busy runner can hold back (#1041). So every fade still
#: running is ended first, in the same evaluate: the read is the style each
#: card settles on, what the page shows 0.15 s later, without waiting for a
#: frame. Only transitions are ended, since each one has an end.
_CARD_PAINT = """() => {
  const cards = Array.from(document.querySelectorAll('main article[data-scenario-key]'));
  for (const card of cards) {
    for (const fade of card.getAnimations({ subtree: true })) {
      if (fade instanceof CSSTransition) fade.finish();
    }
  }
  return cards.map((card) => {
    const heading = card.querySelector('h2');
    const swatches = heading
      ? Array.from(heading.querySelectorAll('[data-curio-scenario-swatch]'))
      : [];
    return {
      name: heading ? heading.innerText.trim() : '',
      strip: card.firstElementChild
        ? getComputedStyle(card.firstElementChild).backgroundColor
        : '',
      border: getComputedStyle(card).borderTopColor,
      swatches: swatches.map((s) => getComputedStyle(s).backgroundColor),
    };
  });
}"""


def _rgb(hex_color: str) -> str:
    """``#3567c7`` as the browser computes it: ``rgb(53, 103, 199)``."""
    red, green, blue = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgb({red}, {green}, {blue})"


@contextmanager
def _animations_held(page):
    """The page's animations held still until the block ends, as on a runner
    that draws no frame: a transition only moves when a frame is drawn, so one
    that starts inside stays at its first value. Chromium's DevTools protocol,
    the one browser the scenes run in."""
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Animation.enable")
        cdp.send("Animation.setPlaybackRate", {"playbackRate": 0})
        yield
    finally:
        cdp.send("Animation.setPlaybackRate", {"playbackRate": 1})
        cdp.detach()


def _save_riverside_projects(page, backend: str) -> None:
    """Both projects, each a chain of code nodes with one scenario per node."""
    token = next(
        c["value"] for c in page.context.cookies() if c["name"] == "session_token"
    )
    for name, scenarios in RIVERSIDE_PROJECTS.items():
        nodes = [
            {"id": f"n{i}", "type": "curio.builtin/computation-analysis@1",
             "content": "return 1", "x": 300 * i, "y": 0}
            for i in range(len(scenarios))
        ]
        edges = [
            {"id": f"e{i}", "source": f"n{i - 1}", "target": f"n{i}"}
            for i in range(1, len(nodes))
        ]
        api_json(f"{backend}/api/projects", token, method="POST", payload={
            "name": name,
            "spec": {"dataflow": {
                "name": name,
                "nodes": nodes,
                "edges": edges,
                "scenarios": [
                    {"id": f"s{i}", "name": scenario, "color": color, "nodes": [f"n{i}"]}
                    for i, (scenario, color) in enumerate(scenarios)
                ],
            }},
            "outputs": [],
        })


@walkthrough(
    slug="scenario-cards-wear-one-kind-color",
    title="Every scenario card wears the scenario kind color",
    premise="Open the Scenario Catalog on two projects' scenarios and read the cards.",
    note="A card's strip and selected border wore the scenario's own color, and "
         "every project gives its scenarios the same few colors in turn, so the "
         "strips repeated across projects and told the cards apart by nothing. "
         "Every scenario card now takes one scenario kind color, as model and "
         "source cards take theirs, and the scenario's own color is the square "
         "before its name.",
    tests=["src/tests/styles/catalogKindPalette.test.ts",
           "src/tests/scenarioCatalog/ScenarioCatalogBrowse.test.tsx",
           "test_frontend/test_walkthrough_baselines.py"],
    fit_reactflow=False,
)
def scenario_cards_wear_one_kind_color(ctx: Ctx) -> None:
    page = ctx.page
    _save_riverside_projects(page, ctx.backend)

    ctx.say("Open the Scenario Catalog",
            "Two projects, five scenarios, three colors between them.")
    page.goto(f"{ctx.frontend}/catalog/scenarios")
    expect(page.get_by_role("heading", name="Scenario Catalog", level=1)).to_be_visible(
        timeout=30000
    )
    ctx.narrator.type_into(page.get_by_role("searchbox", name="Search scenarios"), "Riverside")

    cards = page.locator("main article[data-scenario-key]")
    # The drawer follows the first card. Its graph marks the scenario, and its
    # info rows grow, once the scenario's details answer.
    drawer = page.locator('[data-curio-browse-drawer="true"]')
    # "Recently edited" puts Riverside flood, saved last, first. Once its first
    # scenario is in the drawer, the cards are drawn, so the sort below moves
    # the selection onto Cool roofs on a drawn card, which fades its border in.
    expect(drawer.get_by_role("heading", name="Levee raised", level=2)).to_be_visible(
        timeout=30000
    )
    # Held from the sort through the read: every run meets what a busy runner
    # meets now and then, no frame between the selected card's style changing
    # and the read (#1041).
    with _animations_held(page):
        page.get_by_role("combobox", name="Sort scenarios").select_option("name")
        expect(cards).to_have_count(5, timeout=30000)
        expect(cards.locator("h2")).to_have_text(
            ["Cool roofs", "Levee raised", "Marsh restored", "Pumps added", "Street trees"],
            timeout=30000,
        )
        expect(drawer.get_by_role("heading", name="Cool roofs", level=2)).to_be_visible(
            timeout=30000
        )
        expect(drawer.get_by_text("Shared context", exact=True)).to_be_visible(timeout=30000)
        page.wait_for_load_state("networkidle")
        painted = page.evaluate(_CARD_PAINT)

    own = {
        scenario: _rgb(color)
        for scenarios in RIVERSIDE_PROJECTS.values()
        for scenario, color in scenarios
    }
    problems = [
        f"{card['name']}: the strip is {card['strip']}, not the scenario kind "
        f"color {SCENARIO_KIND_FG}"
        for card in painted
        if card["strip"] != SCENARIO_KIND_FG
    ]
    problems += [
        f"{card['name']}: the title holds swatches {card['swatches']}, not one "
        f"in the scenario's own {own.get(card['name'])}"
        for card in painted
        if card["swatches"] != [own.get(card["name"])]
    ]
    if painted and painted[0]["border"] != SCENARIO_KIND_FG:
        problems.append(
            f"{painted[0]['name']}, selected: the border is {painted[0]['border']}, "
            f"not the scenario kind color {SCENARIO_KIND_FG}"
        )
    assert not problems, "\n".join(problems)

    ctx.focus(cards.first, hold=900)
    ctx.say("One strip for every scenario",
            "The scenario's own color is the square before its name.")
