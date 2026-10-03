"""Scenes on the visual claims of #218 to #227: node settings, the package pill,
empty nodes, node info, Data Export, the dataflow goal, the project drawer.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import require_owner_view, wait_for_projects_page
from .framework import Ctx, walkthrough


# ---------------------------------------------------------------------------
# #218-#227: the visual claims of this batch
# ---------------------------------------------------------------------------
#
# Baselines are for defects whose symptom is what the SCREEN looks like. The
# behavioural halves of these issues are asserted in jest and in the plain e2e
# suites, which say what happened rather than what it looked like; what is left
# here is the part only a picture settles -- a control that should not be there,
# a field cropped mid-word, a body that renders nothing at all.
#
# Every one of these clips to its subject, so the budget is spent on the
# control or field the claim is about rather than on surrounding chrome.


def _canvas_node(ctx: Ctx, index: int = 0):
    """The nth node element on the canvas."""
    node = ctx.page.locator(".react-flow__node").nth(index)
    node.wait_for(state="visible", timeout=30000)
    return node


def _add_builtin_node(ctx: Ctx, tile_id: str, at):
    """Drag a built-in palette tile onto the canvas, returning its LOCATOR.

    The scene opens on an example dataflow (the baseline harness waits for a
    node before handing over), so the canvas already has nodes and ``.nth(0)``
    would be one of those. ``drag_to_canvas`` hands back the id of the node it
    created, which is the only way to address the one this scene is about.
    """
    from ..utils import drag_to_canvas, node_locator

    # The built-in tiles live in the left rail and are present without opening
    # a palette -- the Packages dropdown lists third-party packages only.
    node_id = drag_to_canvas(ctx.page, ctx.page.locator(tile_id), at=at)
    return node_locator(ctx.page, node_id)


@walkthrough(
    slug="node-settings-reads-plainly",
    refs=[219],
    title="Node settings say what they mean",
    premise="Open a node's settings and read the capability boxes and the port editor.",
    note="The capability checkboxes rendered their own field names - hasCode, "
         "hasWidgets, hasGrammar - and because each input is wrapped in its "
         "label, the internal identifier was the accessible name too. The port "
         "types were a single free-text field whose placeholder was the only "
         "statement of both the vocabulary and the separator, so a typo passed "
         "the editor and was dropped on the way into the registry.",
    tests=["src/tests/components/nodeTemplateConfigModal.test.tsx",
           "src/tests/constants/supportedPortTypes.test.ts"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
    max_diff_ratio=0.03,
    example="01-vega-lite-chained-transforms.json",
)
def node_settings_reads_plainly(ctx: Ctx) -> None:
    from ..utils import activate_header_icon

    page = ctx.page

    ctx.say("Node settings", "The capability boxes used to read hasCode.")
    node = _canvas_node(ctx)
    node.scroll_into_view_if_needed()
    cog = node.locator('button[aria-label^="Node settings for"]')
    cog.wait_for(state="visible", timeout=20000)
    # The gear activates on pointerdown/pointerup and swallows the native
    # click (useHeaderIconDragClick), so a plain click does nothing.
    activate_header_icon(cog)
    expect(page.get_by_role("heading", name="Node settings")).to_be_visible(timeout=15000)
    ctx.beat(600)

    # The claim, stated as an assertion as well as a picture: a baseline alone
    # would pass on a dialog that had merely moved the old labels around.
    for name in ("Code", "Widgets", "Grammar"):
        expect(page.get_by_label(name, exact=True)).to_be_visible()
    # Output rather than input: a kind may declare no input ports, but the
    # config always carries an output (a synthetic JSON one when the descriptor
    # has none), so this row is there for any node the scene might open on.
    expect(page.locator('[aria-label="Output ports port 1 type 1"]')).to_be_visible()

    ctx.capture("capability-labels")

    # The port editor is below the fold of the modal, so the shot above proves
    # only the labels half of the claim.
    ctx.say("And the ports", "A type is chosen from the list, one per row.")
    page.locator('[aria-label="Output ports port 1 type 1"]').scroll_into_view_if_needed()
    ctx.beat(400)
    ctx.capture("port-rows")


@walkthrough(
    slug="package-pill-only-on-package-nodes",
    refs=[218],
    title="The PACKAGE pill only where it leads somewhere",
    premise="Look at the header of a built-in node.",
    note="Every palette node comes from a package now, curio.builtin "
         "included, so source === 'package' was true for all of them and the "
         "pill rendered everywhere. Its whole effect is to reveal its package "
         "in the Packages palette, which lists third-party packages only - so "
         "on a built-in it was a control for an action that could not happen.",
    tests=["src/tests/components/packageMetaHeader.test.tsx"],
    # Exactly one element: the scene opens on an example with six nodes and
    # ``_capture_element`` is strict about its selector.
    clip_selector=".react-flow__node >> nth=0",
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline - here a node-header clip, 3.9% on CI - so the pin
    # leaves room for that without waving through a real change.
    max_diff_ratio=0.08,
    example="dataflows/DefaultWorkflow.json",
)
def package_pill_only_on_package_nodes(ctx: Ctx) -> None:
    node = _canvas_node(ctx)

    ctx.say("A built-in node", "It used to carry a PACKAGE pill that led nowhere.")
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The category chip stays - it is informational. Only the button goes.
    expect(
        node.get_by_role("button", name=re.compile("Open package .* in Packages palette"))
    ).to_have_count(0)
    # And the controls that shared its gate survive, which is the trap: the
    # one-line version of this fix takes renaming and the cog with it.
    expect(node.locator('button[aria-label^="Node settings for"]')).to_be_visible()

    ctx.capture("builtin-header")
    ctx.say("No pill, and the cog still there",
            "Renaming and settings shared the pill's old gate.")


@walkthrough(
    slug="empty-nodes-say-why",
    refs=[224],
    title="An empty node says which kind of empty",
    premise="Drop a Simple View with nothing connected to it.",
    note="Data Pool and Simple View rendered a blank area, so an unconnected "
         "node, one whose upstream had not run, and a broken one all looked "
         "identical. Four states need four different things from the user, so "
         "they now say which one this is and what to do about it.",
    tests=["src/tests/utils/nodeEmptyState.test.ts",
           "src/tests/adapters/node/components/DataPoolContent.test.tsx"],
    # The node carrying the empty body: unambiguous (only one has the
    # attribute) and with enough around it to be legible, where clipping to the
    # message alone captured ~90px of unreadable text.
    clip_selector=".react-flow__node:has([data-curio-node-empty])",
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="dataflows/DefaultWorkflow.json",
)
def empty_nodes_say_why(ctx: Ctx) -> None:
    ctx.say("A Simple View with nothing wired in", "This used to be a blank box.")
    # Simple View's template id is ``vis-simple``.
    node = _add_builtin_node(ctx, "#tile-vis-simple", (260, 200))
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The reason is derived, so the picture and the assertion agree on which of
    # the four states this is.
    expect(node.locator('[data-curio-node-empty="disconnected"]')).to_be_visible(timeout=20000)

    ctx.capture("simple-view-disconnected")
    ctx.say("It names the state and the next step",
            "Connect a node to this input.")


@walkthrough(
    slug="spatial-join-explains-itself",
    refs=[225, 262],
    title="A node can explain itself",
    premise="Add a Spatial Join and open its info.",
    note="The help text already existed - the builtin manifest documents the "
         "two input handles, the join direction and the output columns - and "
         "DescriptionModal was already implemented and already mounted for "
         "every node. Nothing opened it, so every kind's documentation shipped "
         "unreachable.",
    tests=["src/tests/utils/nodeDescription.test.ts",
           "backend/tests/test_packages/test_builtin_descriptions.py"],
    clip_selector='[data-curio-modal-shell="true"]',
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # baseline is minted on CI, so a rewritten description is what moves it.
    max_diff_ratio=0.10,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
)
def spatial_join_explains_itself(ctx: Ctx) -> None:
    from ..utils import activate_header_icon

    page = ctx.page

    ctx.say("Spatial Join", "What goes in each handle was not stated anywhere.")
    node = _add_builtin_node(ctx, "#tile-spatial-join", (300, 220))
    node.scroll_into_view_if_needed()
    # The node gained a body and a header band in #262 (it was icon-only), so
    # the info button is the header's; hovering is harmless either way.
    node.hover()
    ctx.beat(400)
    info = node.locator('button[title^="About"]')
    info.wait_for(state="visible", timeout=20000)
    activate_header_icon(info)

    expect(page.get_by_role("heading", name="Description")).to_be_visible(timeout=15000)
    ctx.beat(600)
    ctx.capture("spatial-join-description")
    ctx.say("Both handles, the direction, the output",
            "Straight from the package manifest.")


@walkthrough(
    slug="data-export-is-one-button",
    refs=[226],
    title="Data Export names the file it will give you",
    premise="Drop a Data Export node and read its control.",
    note="It asked for a format in a dropdown and then wrote every file as "
         "data_export whatever the input was, so three exports from one "
         "dataflow collided under one name. The payload already declares its "
         "shape and the input already has a name, so the node decides both and "
         "shows the result. The node is that one button: no code, widgets or "
         "provenance tabs, and no play button.",
    tests=[
        "src/tests/utils/dataExportTarget.test.ts",
        "src/tests/adapters/node/behaviors.test.tsx",
    ],
    # The one node carrying a Download button, so the clip cannot land on one
    # of the example's six.
    clip_selector='.react-flow__node:has(button[aria-label^="Download"])',
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="dataflows/DefaultWorkflow.json",
)
def data_export_is_one_button(ctx: Ctx) -> None:
    ctx.say("Data Export", "One button, and nothing else on the node.")
    node = _add_builtin_node(ctx, "#tile-data-export", (260, 200))
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # The whole node is the button (#226): no tabs, no play button.
    expect(node.locator('[data-rr-ui-event-key]')).to_have_count(0)
    expect(node.locator("svg.fa-circle-play")).to_have_count(0)

    # Unconnected: one button, disabled, saying why rather than offering a
    # format for data that is not there.
    expect(node.get_by_role("button", name=re.compile("^Download"))).to_be_visible(timeout=20000)
    expect(node.get_by_text("Connect a dataset to export it")).to_be_visible()

    # Park the pointer off the node, so no hover tooltip sits in the frame:
    # one that may or may not have faded is 3% of a 3% budget.
    ctx.page.mouse.move(5, 5)
    ctx.beat(400)
    ctx.capture("data-export-unconnected")
    ctx.say("One button", "It names the file once something is connected.")


@walkthrough(
    slug="dataflow-goal-is-readable",
    refs=[227],
    title="The dataflow goal is readable, and says what it is",
    premise="Read the field that appears when an agent is attached.",
    note="Reported as a cropped placeholder plus 'which agent answers a "
         "question typed here'. The second rests on a misreading: nothing is "
         "sent from this field. It is a persisted property of the dataflow, "
         "handed to every agent that reads it - and it looked like a chat box "
         "because it sat among the agent chips with no label except a "
         "placeholder too long to fit.",
    tests=["src/tests/attach/AgentDock.test.tsx",
           "src/tests/styles/agentDockGoalGeometry.test.ts"],
    clip_selector='[role="toolbar"][aria-label="Canvas agents"]',
    fit_reactflow=False,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
    # The claim is asserted in code as geometry (scrollWidth against
    # clientWidth, below); the PNG documents it.
    max_diff_ratio=0.10,
)
def dataflow_goal_is_readable(ctx: Ctx) -> None:
    page = ctx.page

    # The dock renders the goal field only once something is ATTACHED
    # (``showGoal={ctx.attachments.length > 0}``), and attaching is not the same
    # as adding an agent to the project: the catalog's "Add to project" writes
    # the agent lockfile, while an attachment binds one to the canvas. So this
    # is a precondition of the scene rather than part of its claim, and it goes
    # over HTTP -- the drag that would do it in the UI belongs to a different
    # journey.
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the scene cannot attach an agent"
    project_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    base = f"{ctx.backend}/api/agents/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    coord = "agent.dataflow-builder@1.0.0"

    installed = page.request.post(f"{base}/install", headers=headers, data={"coord": coord})
    assert installed.ok, f"install failed: {installed.status} {installed.text()[:200]}"

    def attach_one() -> None:
        attached = page.request.post(
            f"{base}/attachments",
            headers=headers,
            data={"coord": coord, "target": {"kind": "canvas"}},
        )
        assert attached.ok, f"attach failed: {attached.status} {attached.text()[:200]}"

    attach_one()

    # The dock is rendered from the attachment list the page fetches, so reload
    # rather than wait for a push that may never come.
    page.reload()
    require_owner_view(page)
    ctx.beat(800)

    ctx.say("The dataflow goal", "Its placeholder used to be cut off mid-sentence.")
    goal = page.get_by_label("Dataflow goal")
    expect(goal).to_be_visible(timeout=30000)
    # A standing label, so the field keeps its name once a value is typed -
    # which is exactly when the placeholder used to stop carrying it.
    expect(page.get_by_text("Goal", exact=True)).to_be_visible()
    ctx.capture("goal-empty")

    # ``type_into`` is on the Narrator, not on Ctx (which passes through only
    # say / click / focus / beat).
    goal.fill("Find heat islands in Chicago")
    # Blur so the field scrolls back to the start: the caret sits at the end
    # after a fill, which hides the beginning of the very value this scene is
    # about.
    goal.blur()
    ctx.beat(500)
    ctx.capture("goal-filled")

    # The measurement, rather than the pixels (#355): scrollWidth vs
    # clientWidth is the same claim stated so a CSS regression cannot slip
    # through a tolerance.
    #
    # Checked with the placeholder AND with a value, because they crop for
    # different reasons: the placeholder is fixed-length copy, the value is
    # whatever the user typed.
    #
    # Two more agents, attached AFTER both captures: the squeeze is the reported
    # condition and one avatar does not squeeze anything, but crowding the dock
    # before the captures would leave the baseline PNGs documenting a state this
    # scene no longer produces. The pictures keep their subject; the assertions
    # get the harder case.
    attach_one()
    attach_one()
    page.reload()
    require_owner_view(page)
    goal = page.get_by_label("Dataflow goal")
    expect(goal).to_be_visible(timeout=30000)
    ctx.beat(400)

    avatars = page.locator(
        '[role="toolbar"][aria-label="Canvas agents"] button[aria-label^="Open chat"]'
    ).count()
    assert avatars >= 3, (
        f"the dock shows {avatars} avatars; the goal is not being squeezed by "
        "anything, so this measurement proves nothing"
    )

    # 1. The PLACEHOLDER must fit. It is fixed-length copy that #227 shortened
    #    precisely so it would, and it is the only thing naming the field
    #    before anything is typed. 1px of slack for sub-pixel rounding.
    #    Measured as text: a placeholder is not content, so the input's own
    #    scrollWidth never grows past it and cannot show the crop (#355).
    goal.fill("")
    goal.blur()
    ctx.beat(200)
    empty = goal.evaluate(
        "el => { const cs = getComputedStyle(el);"
        " const pen = document.createElement('canvas').getContext('2d');"
        " pen.font = cs.font;"
        " return { text: pen.measureText(el.placeholder).width,"
        " box: el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) }; }"
    )
    assert empty["text"] <= empty["box"] + 1, (
        f"the goal placeholder is cropped with {avatars} agents attached: "
        f"its text is {empty['text']:.0f}px in a {empty['box']:.0f}px box "
        "(#227/#355)"
    )

    # 2. A long VALUE is allowed to overflow - a goal longer than the field is
    #    the normal case, and the fix's own comment says so - but it must
    #    ellipsize rather than be cut mid-word, and the field must still be
    #    wide enough to read. Squeezed to nothing is the regression here, not
    #    overflow itself.
    goal.fill("Find heat islands in Chicago and rank them by population exposure")
    goal.blur()
    ctx.beat(200)
    filled = goal.evaluate(
        "el => ({ client: el.clientWidth,"
        " overflow: getComputedStyle(el).textOverflow,"
        " minWidth: getComputedStyle(el.parentElement).minWidth })"
    )
    assert filled["overflow"] == "ellipsis", (
        "a goal longer than the field would be cut mid-word rather than "
        f"ellipsized (text-overflow: {filled['overflow']})"
    )
    assert filled["client"] >= 120, (
        f"the goal field collapsed to {filled['client']}px with {avatars} "
        "agents attached - the placeholder cannot fit in that"
    )

    ctx.say("Named, and readable end to end",
            "Who sees it is on the tooltip, not in the width budget.")


@walkthrough(
    slug="project-drawer-offers-delete",
    refs=[221, 261],
    title="A project can be deleted from its own drawer",
    premise="Select a project and read the actions offered.",
    note="The drawer offered Archive only, and revealed deletion after the "
         "project was archived - while the right-click menu offered deletion "
         "to anything. The same project was told two different things about "
         "what could be done to it. Both surfaces render one list now (#221), "
         "and Archive itself is gone (#261): it never cleared, so it was a "
         "second permanent state that merely read as the cautious one. With no "
         "softer-sounding sibling left, Delete dropped its \"forever\".",
    tests=["src/tests/pages/projectActions.test.ts",
           "src/tests/pages/projectsPageChrome.test.tsx"],
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline - here a full frame, 6% on CI - so the pin
    # leaves room for that without waving through a real change.
    max_diff_ratio=0.08,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="01-vega-lite-chained-transforms.json",
)
def project_drawer_offers_delete(ctx: Ctx) -> None:
    page = ctx.page

    ctx.say("The projects list", "Its drawer offered Archive and nothing else.")
    page.goto(f"{ctx.frontend}/projects")
    wait_for_projects_page(page)

    card = page.locator("[data-project-id]").first
    card.wait_for(state="visible", timeout=30000)
    ctx.click(card)

    expect(page.get_by_role("button", name="Delete", exact=True)).to_be_visible(timeout=15000)
    expect(page.get_by_role("button", name="Archive", exact=True)).to_have_count(0)
    ctx.capture("drawer-actions")

    # "On every project" until #285: a dataflow Curio seeded offers no Delete,
    # because there is no way to get it back (the #270 marker never re-seeds a
    # deleted one). This scene opens on the dataflow the harness created, which
    # is the user's own and therefore still deletable.
    ctx.say("Delete, on the dataflows you made",
            "The confirm is what makes deleting deliberate.")
