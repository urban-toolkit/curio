"""Scenes on the visual claims of #218 to #227: node settings, the package pill,
empty nodes, node info, Data Export, the dataflow goal, the project drawer.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import require_owner_view, wait_for_changes_kept, wait_for_projects_page
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
    from ..utils import drag_builtin_to_canvas, node_locator

    # The built-in tiles are in the rail's Built-in palette. The helper opens
    # it for the drag and closes it again, so the scene's frames show no panel.
    node_id = drag_builtin_to_canvas(ctx.page, tile_id, at=at)
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
    # The dialog's heading, exactly: the canvas title is the scene's dataflow
    # name, "Node settings say what they mean", a heading too.
    expect(page.get_by_role("heading", name="Node settings", exact=True)).to_be_visible(timeout=15000)
    ctx.beat(600)

    # The claim, stated as an assertion as well as a picture: a baseline alone
    # would pass on a dialog that had merely moved the old labels around. In
    # the dialog: the node's own tabs carry those names too.
    dialog = page.locator('[data-curio-modal-shell="true"]')
    for name in ("Code", "Widgets", "Grammar"):
        expect(dialog.get_by_label(name, exact=True)).to_be_visible()
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
    example="dataflows/default-workflow.json",
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
    example="dataflows/default-workflow.json",
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
    info = node.locator('button[data-tooltip^="About"]')
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
    premise="Drop a Data Export node and read the Widgets tab it opens on.",
    note="It asked for a format in a dropdown and then wrote every file as "
         "data_export whatever the input was, so three exports from one "
         "dataflow collided under one name. The node's Python code writes the "
         "file, curio_export(input_0, [!! file_name !!], part=[!! part !!]): a "
         "table as CSV, a GeoDataFrame as GeoJSON, a raster as GeoTIFF, a "
         "bundle as one zip. The node opens on its Widgets tab, which shows "
         "only its File name and one Download button under it, with a Part "
         "dropdown when its input holds several parts, and the button names "
         "the file once a run wrote it. Its code "
         "is on its Code tab, and it has a play, as any code node has.",
    tests=[
        "src/tests/utils/dataExportTarget.test.ts",
        "src/tests/adapters/node/dataExportBehavior.test.tsx",
        "src/tests/components/nodeEditorOpensOnControls.test.tsx",
        "sandbox/tests/test_data_export_files.py",
    ],
    # The one node carrying a Download button, so the clip cannot land on one
    # of the example's six.
    clip_selector='.react-flow__node:has(button[aria-label^="Download"])',
    max_diff_ratio=0.03,
    # The baseline harness waits for ``.react-flow__node`` before handing over
    # (test_walkthrough_baselines), so a scene cannot open on an empty canvas
    # even when it brings its own node.
    example="dataflows/default-workflow.json",
)
def data_export_is_one_button(ctx: Ctx) -> None:
    from ..utils import assert_shows_only_controls, drag_builtin_to_canvas, node_locator, wait_for_node_code

    ctx.say("Data Export", "Its File name and one Download button, on its Widgets tab.")
    node_id = drag_builtin_to_canvas(ctx.page, "#tile-data-export", at=(260, 200))
    node = node_locator(ctx.page, node_id)
    node.scroll_into_view_if_needed()
    ctx.focus(node, hold=1000)

    # A code node: its Code and Widgets tabs and its play, and the code that
    # writes the file. It opens on its Widgets tab.
    for tab in ("code", "widgets"):
        expect(node.locator(f'.nav-link[data-rr-ui-event-key="{tab}"]')).to_have_count(1)
    expect(node.locator("svg.fa-circle-play")).to_have_count(1)
    wait_for_node_code(ctx.page, node_id, "return curio_export(input_0, [!! file_name !!], part=[!! part !!])\n")
    expect(node.locator('.nav-link[data-rr-ui-event-key="widgets"]')).to_have_class(
        re.compile(r"\bactive\b"), timeout=20000,
    )

    # On the Widgets tab, alone: the File name, and under it the one Download
    # button. Unconnected, it has no parts to offer: no Part.
    panel = node.locator("[data-widget-controls]")
    expect(panel.get_by_text("File name", exact=True)).to_be_visible(timeout=20000)
    expect(panel.get_by_text("Part", exact=True)).to_have_count(0)
    assert_shows_only_controls(ctx.page, node_id)
    download = panel.locator('[data-node-controls] button[aria-label^="Download"]')
    expect(download).to_have_count(1)
    expect(node.locator('button[aria-label^="Download"]')).to_have_count(1)
    # Unconnected: disabled, saying why rather than offering a file that
    # cannot be written.
    expect(download).to_be_disabled()
    expect(panel.get_by_text("Connect a dataset to export it")).to_be_visible()

    # Park the pointer off the node, so no hover tooltip sits in the frame:
    # one that may or may not have faded is 3% of a 3% budget.
    ctx.page.mouse.move(5, 5)
    ctx.beat(400)
    ctx.capture("data-export-unconnected")
    ctx.say("One button", "It names the file once a run wrote it.")


#: The Goal line under the header of every agent's chat.
CHAT_GOAL = "[data-curio-chat-goal]"
#: What the line offers while the dataflow has no goal.
GOAL_EMPTY = "Add what this dataflow is for"
LONG_GOAL = "Find heat islands in Chicago and rank them by population exposure"
#: A window narrow enough that the chat panel is 92% of it, below its 560px.
NARROW_WINDOW = 520


def _write_goal(line, goal: str) -> None:
    """Write *goal* on the Goal line as a person does: its button, the field,
    then Enter, which keeps it and closes the field."""
    line.get_by_role("button", name=re.compile(rf"^(Edit the goal|{GOAL_EMPTY})$")).click()
    field = line.get_by_label("Dataflow goal")
    expect(field).to_be_focused()
    field.fill(goal)
    field.press("Enter")
    expect(field).to_have_count(0)


def _goal_line_reads_whole(line, width: int) -> None:
    """The Goal line's claims (#227/#355) in a window *width* pixels wide,
    measured, since a tolerance on pixels can let a crop through."""
    where = f"in a {width}px window"

    # 1. With no goal, the line offers to add one, in words read whole. 1px of
    #    slack for sub-pixel rounding.
    _write_goal(line, "")
    add = line.get_by_role("button", name=GOAL_EMPTY)
    expect(add).to_be_visible()
    offer = add.evaluate(
        "el => ({ scroll: el.scrollWidth, client: el.clientWidth,"
        " right: el.getBoundingClientRect().right,"
        " lineRight: el.parentElement.getBoundingClientRect().right })"
    )
    assert offer["scroll"] <= offer["client"] + 1 and offer["right"] <= offer["lineRight"] + 1, (
        f"'{GOAL_EMPTY}' is cropped {where}: {offer}"
    )

    # 2. The field's placeholder fits. Measured as text: a placeholder is not
    #    content, so the field's own scrollWidth never grows past it and cannot
    #    show the crop (#355).
    add.click()
    field = line.get_by_label("Dataflow goal")
    expect(field).to_be_focused()
    empty = field.evaluate(
        "el => { const cs = getComputedStyle(el);"
        " const pen = document.createElement('canvas').getContext('2d');"
        " pen.font = cs.font;"
        " return { text: pen.measureText(el.placeholder).width,"
        " box: el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) }; }"
    )
    assert empty["text"] <= empty["box"] + 1, (
        f"the goal field's placeholder is cropped {where}: its text is "
        f"{empty['text']:.0f}px in a {empty['box']:.0f}px box (#227/#355)"
    )
    # Escape ends the edit, keeps nothing, and leaves the chat open.
    field.press("Escape")
    expect(field).to_have_count(0)
    expect(line.get_by_role("button", name=GOAL_EMPTY)).to_be_visible()

    # 3. A long goal is cut short with an ellipsis rather than mid-word, is
    #    still wide enough to read, and leaves its Edit button on the line.
    _write_goal(line, LONG_GOAL)
    shown = line.get_by_text(LONG_GOAL, exact=True).evaluate(
        "el => ({ client: el.clientWidth, scroll: el.scrollWidth,"
        " overflow: getComputedStyle(el).textOverflow })"
    )
    assert shown["overflow"] == "ellipsis", (
        f"a goal longer than the line is cut mid-word {where} "
        f"(text-overflow: {shown['overflow']})"
    )
    assert shown["client"] >= 120, (
        f"the goal is squeezed to {shown['client']}px {where}, too narrow to read"
    )
    edit = line.get_by_role("button", name="Edit the goal")
    expect(edit).to_be_visible()
    boxes = edit.evaluate(
        "el => ({ right: el.getBoundingClientRect().right,"
        " lineRight: el.parentElement.getBoundingClientRect().right })"
    )
    assert boxes["right"] <= boxes["lineRight"] + 0.5, (
        f"the Edit button is pushed off the Goal line {where}: {boxes}"
    )


@walkthrough(
    slug="dataflow-goal-is-readable",
    refs=[227],
    title="The dataflow goal is readable, and says what it is",
    premise="Open an agent's chat and read the Goal line under its header.",
    note="Reported as a cropped placeholder plus 'which agent answers a "
         "question typed here'. Nothing is sent from the goal: it is a "
         "persisted property of the dataflow, handed to every agent that "
         "reads it. In the canvas's dock, among the agent chips, it looked "
         "like a chat box, so it is a labelled line under the header of "
         "every agent's chat, with its own Edit button.",
    tests=["src/tests/attach/AgentChatPanel.test.tsx",
           "src/tests/styles/chatGoalLineGeometry.test.ts"],
    clip_selector=CHAT_GOAL,
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

    # The goal is a line of every agent's chat, so the scene needs an agent
    # ATTACHED, and attaching is not the same as adding an agent to the
    # project: the catalog's "Add to project" writes the agent lockfile, while
    # an attachment binds one to the canvas. So this is a precondition of the
    # scene rather than part of its claim, and it goes over HTTP -- the drag
    # that would do it in the UI belongs to a different journey.
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the scene cannot attach an agent"
    project_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    base = f"{ctx.backend}/api/agents/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    coord = "agent.curio.dataflow-builder@1"

    installed = page.request.post(f"{base}/install", headers=headers, data={"coord": coord})
    assert installed.ok, f"install failed: {installed.status} {installed.text()[:200]}"
    attached = page.request.post(
        f"{base}/attachments",
        headers=headers,
        data={"coord": coord, "target": {"kind": "canvas"}},
    )
    assert attached.ok, f"attach failed: {attached.status} {attached.text()[:200]}"

    # The dock is rendered from the attachment list the page fetches, so reload
    # rather than wait for a push that may never come.
    page.reload()
    require_owner_view(page)
    ctx.beat(800)

    ctx.say("The dataflow goal", "The line under the header of every agent's chat.")
    chip = page.locator(
        '[role="toolbar"][aria-label="Canvas agents"] button[aria-label^="Open chat"]'
    ).first
    expect(chip).to_be_visible(timeout=30000)
    ctx.click(chip)
    line = page.locator(CHAT_GOAL)
    expect(line).to_be_visible(timeout=30000)
    # A standing label, so the line keeps its name once a goal is written.
    expect(line.get_by_text("Goal", exact=True)).to_be_visible()
    add = line.get_by_role("button", name=GOAL_EMPTY)
    expect(add).to_be_visible()
    ctx.capture("goal-empty")

    ctx.click(add)
    field = line.get_by_label("Dataflow goal")
    expect(field).to_be_focused()
    field.fill("Find heat islands in Chicago")
    field.press("Enter")
    expect(line.get_by_text("Find heat islands in Chicago", exact=True)).to_be_visible()
    # Nothing was sent: the conversation is as empty as it was.
    expect(page.get_by_text("Ask this agent something to get started.")).to_be_visible()
    # Enter hands the focus back to the Edit button, with its keyboard focus
    # ring; the frames show the line at rest.
    edit = line.get_by_role("button", name="Edit the goal")
    expect(edit).to_be_focused()
    edit.blur()
    ctx.beat(300)
    ctx.capture("goal-filled")

    # The measurement, rather than the pixels (#355), so a CSS regression
    # cannot slip through a tolerance: in this window, and in one narrow
    # enough that the panel is 92% of it, where the line has less room than
    # anywhere else a chat opens. After both captures, so the pictures keep
    # their subject. A recording keeps its window.
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    widths = [viewport["width"]] if ctx.recording else [viewport["width"], NARROW_WINDOW]
    for width in widths:
        page.set_viewport_size({"width": width, "height": viewport["height"]})
        ctx.beat(200)
        _goal_line_reads_whole(line, width)
    page.set_viewport_size(viewport)

    # Saved with the dataflow: once the server has this tab's changes, a
    # reload shows the goal on the line. A goal kept only in the tab came back
    # empty, though the top bar said Saved (the dev check of 11-25).
    wait_for_changes_kept(page)
    page.reload()
    require_owner_view(page)
    expect(chip).to_be_visible(timeout=30000)
    ctx.click(chip)
    expect(line.get_by_text(LONG_GOAL, exact=True)).to_be_visible(timeout=30000)
    # The scene's last frame: the long goal cut short, at rest.
    ctx.beat(200)

    ctx.say("Named, and readable end to end",
            "Who reads it is on the label's tooltip.")


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
