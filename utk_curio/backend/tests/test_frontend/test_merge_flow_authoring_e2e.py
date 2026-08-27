"""Playwright E2E for #159: a Merge Flow dragged off the tool rail must work.

The issue's own reproduction, built the way a user builds it. That matters here
more than usual, because the bug was *specific to how the node was created*:

  * a palette drag stores the versioned canonical id (``…/merge-flow@1``)
  * the Jupyter converter and legacy trills store the bare ``…/merge-flow``

Every merge branch in FlowProvider compared ``data.nodeType`` against the
unversioned ``NodeType.MERGE_FLOW`` with ``===``, so the palette-dragged node
matched none of them: its ``data.input`` never became a slot array, the merge
never emitted, and the downstream Python node hit the sandbox's "received no
input but its code references ``arg``" guard. Loading the same graph from a
trill worked fine, which is why the whole existing e2e matrix missed it.

So this test refuses to take the shortcut of seeding a spec: it drags, wires and
runs, then asserts the saved node still carries ``@1``. Without that last
assertion the test could pass against a build that "fixed" the bug by stripping
the suffix on save, which would leave the runtime comparison just as broken for
anyone whose spec still has it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_merge_flow_authoring_e2e.py -v
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .utils import (
    api_json,
    dismiss_toasts,
    canvas_node_type,
    connect_nodes,
    drag_to_canvas,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_workflow_test_screenshot,
    set_node_code,
    require_owner_view,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#step-analysis"
MERGE_TILE = "#step-merge"

ANALYSIS_TYPE = "curio.builtin/computation-analysis"
MERGE_TYPE = "curio.builtin/merge-flow"

# Node geometry: 525x350 at zoom 1 in a 1280x720 viewport, so columns need to be
# ~600px apart or a later node's body covers an earlier one's handle and the
# connection drag becomes a silent no-op. Three columns do not fit side by side,
# so the two producers are stacked in the left column instead.
POS_UP_A = (120, 60)
POS_UP_B = (120, 430)
POS_MERGE = (720, 60)
POS_DOWN = (720, 430)

# The inline output box shows stdout, never the return value, so the downstream
# node has to print what the assertion checks.
MARKER = "CURIO_E2E_MERGED"
UP_A_CODE = "return 11\n"
UP_B_CODE = "return 31\n"
# `arg` is the merged tuple. Summing it proves BOTH upstream values crossed the
# merge - a test that only checked `arg is not None` would pass on a merge that
# dropped one slot, which is half of what #159 broke.
DOWN_CODE = (
    "values = list(arg) if isinstance(arg, (list, tuple)) else [arg]\n"
    f'print("{MARKER}", len(values), sum(int(v) for v in values))\n'
    "return sum(int(v) for v in values)\n"
)


def _unversioned(node_type: str | None) -> str:
    return (node_type or "").split("@", 1)[0]


def test_palette_dragged_merge_flow_feeds_its_downstream_node(
    app_frontend: "FrontendPage",
    current_server: str,
    page,
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    session = stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Merge Author",
        username="merge_author",
        project_name="Merge Flow Authoring",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    # 1. Two producers and a merge, all off the built-in tool rail — the creation
    #    path that carries the `@1` suffix.
    up_a = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP_A)
    up_b = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP_B)
    merge = drag_to_canvas(page, page.locator(MERGE_TILE), at=POS_MERGE)
    down = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_DOWN)

    merge_type = canvas_node_type(page, merge)
    assert _unversioned(merge_type) == MERGE_TYPE, merge_type
    # The premise of the whole test. If the palette ever stops minting the
    # versioned form this stops reproducing #159, and we want to be told.
    assert merge_type != MERGE_TYPE, (
        "expected the palette drag to carry a versioned canonical id "
        f"(…@<major>), got {merge_type!r} — this test no longer reproduces #159"
    )

    # 2. Wire both producers into the merge, then the merge into the consumer.
    #    A merge node renders one handle per slot (`in_0`..`in_4`, see
    #    mergeFlowBehavior) rather than a single generic 'in', so a real drag -
    #    and therefore this one - always names a slot. onConnect's auto-resolution
    #    of a bare 'in' to the next free slot is the imported-trill path and is
    #    covered by the Merge*.json workflows in the e2e matrix.
    connect_nodes(page, up_a, merge, target_handle="in_0")
    connect_nodes(page, up_b, merge, target_handle="in_1")
    connect_nodes(page, merge, down)

    set_node_code(page, up_a, UP_A_CODE)
    set_node_code(page, up_b, UP_B_CODE)
    set_node_code(page, down, DOWN_CODE)

    # 3. Run upstream first, then the consumer. Pre-fix the consumer raised
    #    "This node received no input but its code references `arg`".
    run_node_and_wait(page, up_a, node_type=ANALYSIS_TYPE)
    run_node_and_wait(page, up_b, node_type=ANALYSIS_TYPE)
    down_output = run_node_and_wait(page, down, node_type=ANALYSIS_TYPE)

    assert f"{MARKER} 2 42" in down_output, (
        "the merged tuple did not reach the downstream node with both values.\n"
        f"expected '{MARKER} 2 42', got:\n{down_output}"
    )

    # 4. Server truth: the saved spec keeps the versioned type. A fix that
    #    normalized on save would make step 3 pass while leaving every existing
    #    saved dataflow broken, so this is the assertion that pins the real fix.
    file_btn = page.get_by_role("button", name=re.compile("File"))
    file_btn.wait_for(state="visible", timeout=15000)
    file_btn.click(force=True)
    save_btn = page.get_by_role("button", name="Save dataflow", exact=True)
    save_btn.wait_for(state="visible", timeout=10000)
    save_btn.click()
    save_btn.wait_for(state="hidden", timeout=30000)

    dataflow = api_json(f"{current_server}/api/projects/{project_id}", token)["spec"]["dataflow"]
    saved = {node["id"]: node for node in dataflow["nodes"]}
    assert saved[merge]["type"] == merge_type, (
        f"the merge node's type changed on save: {saved[merge]['type']!r} != {merge_type!r}"
    )

    # Both producers must land on *distinct* merge slots - dropping one input is
    # the other half of what #159 broke. The trill stores only id/source/target
    # (TrillGenerator), but React Flow derives the id as
    # `reactflow__edge-<source><sourceHandle>-<target><targetHandle>`, so the
    # slot is recoverable from persisted data alone.
    merge_edges = [e for e in dataflow["edges"] if e["target"] == merge]
    assert len(merge_edges) == 2, merge_edges
    assert {f"{up_a}out-{merge}in_0", f"{up_b}out-{merge}in_1"} == {
        e["id"].removeprefix("reactflow__edge-") for e in merge_edges
    }, [e["id"] for e in merge_edges]

    # Visual baseline. The semantic assertions above cover what each node
    # computed; this covers what the canvas *looks* like — most usefully that
    # three edges are actually drawn into the merge's separate slot handles,
    # which a store-level assertion cannot see.
    # Transient "couldn't generate dataset" toasts sit bottom-right, exactly over
    # the canvas, and appearing or not is a matter of timing - so they would make
    # the pixel comparison flaky rather than meaningful.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "merge-flow-authoring",
        test_name="test_palette_dragged_merge_flow_feeds_its_downstream_node",
    )
