"""Scenes on a dataflow's name and save state."""
from __future__ import annotations

from ..utils import api_json, canvas_nodes, drag_to_canvas, wait_for_projects_page
from .framework import Ctx, walkthrough
from .provenance import PROVENANCE_EXAMPLE


# ---------------------------------------------------------------------------
# Dataflow identity
# ---------------------------------------------------------------------------

@walkthrough(
    slug="renaming-a-dataflow-renames-it-everywhere",
    example=PROVENANCE_EXAMPLE,
    refs=[230, 270],
    title="A renamed dataflow is renamed on the projects page too",
    premise="Rename a dataflow on the canvas, save it, then go and look at the list.",
    note="The name is stored twice - the project row the Projects list renders, "
         "and `spec.dataflow.name` the canvas title renders. Committing the "
         "title wrote only the second, and the save sent `projectName`, which "
         "only loading ever set - so the save re-sent the name the dataflow was "
         "opened under. The reverse direction was broken too: a name-only PUT, "
         "which is what the list's own rename sends, never reached the spec.",
    tests=["src/tests/hook/useWorkflowOperations.rename.test.ts",
           "src/tests/components/upMenuRename.test.ts",
           "tests/test_projects/test_routes.py",
           "test_frontend/test_project_save_load.py"],
    fit_reactflow=False,
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline - here full frames, 5% of pixels on CI - so the pin
    # leaves room for that without waving through a real change.
    max_diff_ratio=0.08,
)
def renaming_a_dataflow_renames_it_everywhere(ctx: Ctx) -> None:
    """Three captures because the bug spans two pages and two directions.

    A canvas-only shot cannot show the symptom at all - the canvas was the one
    surface that always looked right.
    """
    page = ctx.page

    ctx.say("Rename it on the canvas", "Click the title, type, click away.")
    title = page.locator("h1").first
    title.wait_for(state="visible", timeout=30000)
    ctx.click(title)

    box = page.locator("input[type='text']").last
    box.wait_for(state="visible", timeout=10000)
    box.fill("Renamed Dataflow")
    # Commit on blur - the path #270 was reported on; Enter is the other one.
    box.blur()

    disk = page.locator("[data-curio-save-state]")
    state = disk.get_attribute("data-curio-save-state")
    assert state == "unsaved", (
        f"the rename left the indicator reading {state!r}; a rename diverges "
        f"from disk and has to say so, or the user is told their edit is saved"
    )
    ctx.focus(disk, hold=900)
    ctx.say("Unsaved, as it should be", "The rename is an edit like any other.")
    ctx.capture("renamed-on-canvas")

    ctx.say("Save it", "")
    ctx.click(disk)
    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'saved'",
        timeout=30000,
    )

    ctx.say("Now the projects page", "This is where the old name used to survive.")
    # Through the logo, as a user would - an in-app navigation, not a reload
    # (#270). Falls back to a plain visit for the recorder, which shares the
    # page across scenes and may not have the top bar in view.
    logo = page.get_by_role("link", name="Curio", exact=True)
    if logo.count():
        ctx.click(logo.first)
        wait_for_projects_page(page, timeout=30000)
    else:
        page.goto(f"{ctx.frontend}/projects")
    page.get_by_text("Renamed Dataflow").first.wait_for(state="visible", timeout=30000)
    ctx.focus(page.get_by_text("Renamed Dataflow").first, hold=1200)
    ctx.capture("renamed-in-the-list")

    ctx.say("And back the other way",
            "Renaming from the list has to reach the canvas title too.")
    # Straight through the API: the subject is what the canvas reads back, not
    # the context menu that gets there. The token is the `session_token` cookie
    # the app itself authenticates with (utils/authApi), read off the live
    # context rather than threaded through Ctx, which the video runner shares.
    token = next(
        c["value"] for c in page.context.cookies() if c["name"] == "session_token"
    )
    listed = api_json(f"{ctx.backend}/api/projects", token)
    target = next(p for p in listed if p["name"] == "Renamed Dataflow")
    api_json(
        f"{ctx.backend}/api/projects/{target['id']}",
        token,
        method="PUT",
        payload={"name": "Renamed From The List"},
    )

    page.goto(f"{ctx.frontend}/dataflow/{target['id']}")
    heading = page.locator("h1").filter(has_text="Renamed From The List")
    heading.wait_for(state="visible", timeout=30000)
    ctx.focus(heading, hold=1200)
    ctx.say("The canvas title followed", "Both stores hold one name now.")
    ctx.capture("canvas-follows-a-list-rename")


@walkthrough(
    slug="a-loaded-dataflow-is-not-dirty",
    example=PROVENANCE_EXAMPLE,
    refs=[229],
    title="Opening a saved dataflow leaves nothing to save",
    premise="Open a dataflow you already saved and read the save indicator.",
    note="`loadParsedTrill` replays every persisted edge through the same "
         "`onConnect` a user drag goes through, and onConnect marks the project "
         "dirty - rightly, for a real connection. So any dataflow with even one "
         "edge came back from disk reading 'Unsaved changes', and the 30s "
         "auto-save then rewrote it for nothing, which is what made the disk "
         "turn green a while after opening.",
    tests=["src/tests/hook/useWorkflowOperations.dirtyOnLoad.test.ts",
           "src/tests/components/loadPathsMarkDirty.test.ts",
           "test_frontend/test_project_dirty_guard.py"],
    clip_selector="[data-curio-save-state]",
    # The claim above is asserted in code; the PNG only documents it. The
    # Linux runner antialiases text differently from the machine that captured
    # the baseline - here a 1230px clip of the save indicator, where one antialiased edge is 4-5% - so the pin
    # leaves room for that without waving through a real change.
    max_diff_ratio=0.10,
)
def a_loaded_dataflow_is_not_dirty(ctx: Ctx) -> None:
    """Two captures, clipped to the disk: the subject is one glyph's colour.

    At the suite's default 0.10 an amber disk and a green one are the same
    picture, so a single wide shot could document the fix without ever being
    able to police it. The pair is what makes the two states legible in review.

    The runner has already entered `/dataflow/<id>` through the real
    ProjectLoader path, so this scene only has to read the result.
    """
    page = ctx.page

    # The edge is what the replay processes; before it renders, the bug has not
    # had its chance to happen.
    #
    # `attached`, not `visible`: an edge between two nodes the layout has aligned
    # is a perfectly horizontal line, whose SVG geometry box is zero-height. The
    # stroke is drawn and a human sees it, but Playwright measures the box and
    # calls it hidden. Example 01's first edge is exactly that case. Existence is
    # what this wait is actually about.
    page.locator(".react-flow__edge").first.wait_for(state="attached", timeout=45000)

    disk = page.locator("[data-curio-save-state]")
    state = disk.get_attribute("data-curio-save-state")
    assert state == "saved", (
        f"a freshly loaded dataflow reads {state!r} with no edits made - #229"
    )

    ctx.say("Just opened, nothing edited", "The disk is green: what you see is on disk.")
    ctx.focus(disk, hold=1200)
    ctx.capture("loaded")

    ctx.say("Now add a node", "A real edit still has to register.")
    # `drag_to_canvas`, the suite's proven drop path, rather than a raw mouse drag
    # of an existing node: the drag is what would be flaky here, and adding a node
    # is just as much a real edit for the purpose of the claim.
    before = len(canvas_nodes(page))
    drag_to_canvas(page, page.locator("#tile-computation-analysis"), at=(150, 150))
    assert len(canvas_nodes(page)) == before + 1, "the drop created no node"

    page.wait_for_function(
        "() => document.querySelector('[data-curio-save-state]')"
        "?.getAttribute('data-curio-save-state') === 'unsaved'",
        timeout=15000,
    )
    ctx.focus(disk, hold=1200)
    ctx.say("Amber, as it should be",
            "The guard covers the load's own replay, not the user's edits.")
    ctx.capture("after-an-edit")
