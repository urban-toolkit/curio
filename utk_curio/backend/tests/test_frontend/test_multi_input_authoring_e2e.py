"""Playwright E2E: two palette-dragged producers wired straight into one node (#159, #662).

The fan-in a user builds by hand: three Python nodes dragged off the tool rail,
two of them wired into the third, which reads each input through a chip. That
matters because #159 was specific to how a node was created:

  * a palette drag stores the versioned canonical id (``.../computation-analysis@1``)
  * the Jupyter converter and legacy trills store the bare id

#159 was a canvas check that compared the bare id with ``===``, so a
palette-dragged node matched none of its branches and dropped its inputs.
Which nodes grow an input circle per edge is now read from the node's
descriptor, looked up by ``data.nodeType``: a palette-dragged node whose
versioned id missed that lookup would draw one circle, refuse the second edge,
and never see its second input. Loading the same graph from a trill would work,
which is why the e2e matrix alone does not cover it.

So this test does not seed a spec: it drags, wires and runs, then asserts the
saved node still carries ``@1``. Without that last assertion the test could pass
against a build that stripped the suffix on save, which would leave the lookup
just as broken for anyone whose spec still has it.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_multi_input_authoring_e2e.py -v
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .test_multi_input_e2e import _edge_handles, _wait_for_circles, _wait_for_output
from .utils import (
    api_json,
    canvas_node_type,
    connect_nodes,
    dismiss_toasts,
    drag_to_canvas,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    save_dataflow,
    save_workflow_test_screenshot,
    set_node_code,
    stub_login_and_enter_workflow,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

ANALYSIS_TILE = "#tile-computation-analysis"
ANALYSIS_TYPE = "curio.builtin/computation-analysis"

# Node geometry: 525x350 at zoom 1 in a 1280x720 viewport, so columns need to be
# ~600px apart or a later node's body covers an earlier one's handle and the
# connection drag becomes a silent no-op. The two producers stack in the left
# column, so the consumer's circles stay clear of them.
POS_UP_A = (120, 60)
POS_UP_B = (120, 430)
POS_DOWN = (720, 60)

# The inline output box shows stdout, never the return value, so the downstream
# node has to print what the assertion checks.
MARKER = "CURIO_E2E_FAN_IN"
UP_A_CODE = "return 11\n"
UP_B_CODE = "return 31\n"
# Each input printed on its own, in circle order, and the number of inputs the
# node received: a test that only checked the sum would pass on a node that
# swapped its inputs, and one that only checked a value would pass on a node
# that dropped the other.
DOWN_CODE = (
    "a = [!! input 0 !!]\n"
    "b = [!! input 1 !!]\n"
    "count = sum(x is not None for x in (input_0, input_1))\n"
    f'print("{MARKER}", count, int(a), int(b), int(a) + int(b))\n'
    "return int(a) + int(b)\n"
)


def _unversioned(node_type: str | None) -> str:
    return (node_type or "").split("@", 1)[0]


def test_palette_dragged_producers_feed_one_node_through_its_circles(
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
        name="Fan-in Author",
        username="fan_in_author",
        project_name="Several Inputs Authoring",
    )
    require_owner_view(page)
    token = session["token"]
    project_id = session["project"]["id"]

    # 1. Two producers and a consumer, all off the built-in tool rail: the
    #    creation path that carries the `@1` suffix.
    up_a = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP_A)
    up_b = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_UP_B)
    down = drag_to_canvas(page, page.locator(ANALYSIS_TILE), at=POS_DOWN)

    down_type = canvas_node_type(page, down)
    assert _unversioned(down_type) == ANALYSIS_TYPE, down_type
    # The premise of the whole test. If the palette ever stops minting the
    # versioned form this stops covering the #159 creation path, and we want
    # to be told.
    assert down_type != ANALYSIS_TYPE, (
        "expected the palette drag to carry a versioned canonical id "
        f"(...@<major>), got {down_type!r}: this test no longer covers the "
        "palette-dragged node of #159"
    )

    # 2. Wire both producers straight into the consumer. Each edge takes a
    #    circle and a new empty one appears below it; the circles are
    #    `in`, `in_1`, `in_2`, top to bottom.
    _wait_for_circles(page, down, ["in"])
    connect_nodes(page, up_a, down)
    _wait_for_circles(page, down, ["in", "in_1"])
    connect_nodes(page, up_b, down, target_handle="in_1")
    _wait_for_circles(page, down, ["in", "in_1", "in_2"])
    assert _edge_handles(page, down) == {up_a: "in", up_b: "in_1"}, _edge_handles(page, down)

    set_node_code(page, up_a, UP_A_CODE)
    set_node_code(page, up_b, UP_B_CODE)
    set_node_code(page, down, DOWN_CODE)
    # Both chips name a wired circle, so the editor flags neither.
    node_locator(page, down).locator(".monaco-editor .curio-input-ref").first.wait_for(
        state="attached", timeout=10000
    )
    assert node_locator(page, down).locator(".monaco-editor .curio-input-ref-problem").count() == 0

    # 3. Run upstream first, then the consumer. A node that drew one circle
    #    would have refused the second edge, and `[!! input 1 !!]` would name
    #    nothing.
    run_node_and_wait(page, up_a, node_type=ANALYSIS_TYPE)
    run_node_and_wait(page, up_b, node_type=ANALYSIS_TYPE)
    run_node_and_wait(page, down, node_type=ANALYSIS_TYPE)
    _wait_for_output(
        page, down, f"{MARKER} 2 11 31 42",
        "Both inputs did not reach the consumer, in circle order",
    )

    # 4. Server truth: the saved spec keeps the versioned type. A fix that
    #    normalized on save would make step 3 pass while leaving every existing
    #    saved dataflow broken, so this is the assertion that pins the real fix.
    save_dataflow(page)
    dataflow = api_json(f"{current_server}/api/projects/{project_id}", token)["spec"]["dataflow"]
    saved = {node["id"]: node for node in dataflow["nodes"]}
    assert saved[down]["type"] == down_type, (
        f"the consumer's type changed on save: {saved[down]['type']!r} != {down_type!r}"
    )

    # Both producers must land on *distinct* circles: dropping one input is the
    # other half of what #159 broke. React Flow derives the edge id as
    # `reactflow__edge-<source><sourceHandle>-<target><targetHandle>`, and the
    # saved edge keeps its handle, so each circle is read from both.
    down_edges = [e for e in dataflow["edges"] if e["target"] == down]
    assert len(down_edges) == 2, down_edges
    assert {f"{up_a}out-{down}in", f"{up_b}out-{down}in_1"} == {
        e["id"].removeprefix("reactflow__edge-") for e in down_edges
    }, [e["id"] for e in down_edges]
    assert {e["source"]: e.get("targetHandle") for e in down_edges} == {
        up_a: "in", up_b: "in_1",
    }, down_edges

    # Visual baseline. The semantic assertions above cover what each node
    # computed; this covers what the canvas *looks* like: most usefully that
    # two edges are actually drawn into the consumer's separate circles, with
    # the empty third circle below them, which a store-level assertion cannot
    # see.
    # Transient "couldn't generate dataset" toasts sit bottom-right, exactly over
    # the canvas, and appearing or not is a matter of timing, so they would make
    # the pixel comparison flaky rather than meaningful.
    dismiss_toasts(page)
    save_workflow_test_screenshot(
        page, "multi-input-authoring",
        test_name="test_palette_dragged_producers_feed_one_node_through_its_circles",
    )
