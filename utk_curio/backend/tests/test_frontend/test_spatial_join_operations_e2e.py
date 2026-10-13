"""Playwright E2E: example 25 runs every Spatial Join operation, one flow each (#576).

``docs/examples/25-spatial-join-operations.json`` has one Spatial Join per case:
- intersects, within (with the counts output), contains with polygons on
  input_0, touches with one loader on both circles, overlaps, crosses with
  lines on input_0, and nearest;
- two joins over a point on a shared edge, which show the boundary rule.

Each test opens the example, plays one flow's chart (which runs its loaders
and its join), or for a Simple View, which has no play button, the loaders.
It pins the join's own account of what it paired, then checks that the view
drew. ``test_spatial_join_example.py`` runs the same
flows through the route alone.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_spatial_join_operations_e2e.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    REPO_ROOT,
    assert_vega_canvas_rendered,
    dismiss_toasts,
    node_locator,
    play_node,
    require_owner_view,
    require_project_page,
    require_user_auth,
    run_node_and_wait,
    stub_login_and_enter_workflow,
    wait_for_node_done,
    wait_for_node_settled,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

EXAMPLE = os.path.join(REPO_ROOT, "docs", "examples", "25-spatial-join-operations.json")

#: Each case: its join, the view the join feeds, and the join's status line.
CASES = {
    "intersects": ("3269d5de-21d6-57e4-b811-e3ee90a27f49", "bb22d6d9-2c09-52a1-9ab5-e84f0155c0a6",
                   "359 pairs: 359 of 359 input_0 rows matched."),
    "within-counts": ("5ed28c6e-270b-54d5-85e8-3b5973552eab", "e9cc1cea-8afa-5709-9223-58523a7886d3",
                       "61 of 98 input_1 rows have pairs (235 in all); each row carries point_count."),
    "contains": ("e9c18033-f81d-527c-9624-7bdfb40123ec", "117943b9-497b-528c-b829-edfc95805a7a",
                 "235 pairs: 61 of 98 input_0 rows matched."),
    "touches": ("6e954c1d-9f2d-5e24-9144-22ddefc5d1fd", "9a85441a-9e12-5f7a-9336-9cbbe0dc2be9",
                "484 pairs: 98 of 98 input_0 rows matched."),
    "overlaps": ("292f8f9c-9fd8-57a3-8617-cf9aaad9225b", "4f09ca31-ec7b-5a81-bee0-9ce3555e37a6",
                 "311 pairs: 94 of 98 input_0 rows matched."),
    "crosses": ("d604f407-ecab-5495-a9d2-f777300c306d", "1ad71c29-3824-52a3-9896-f9091462f436",
                "311 pairs: 61 of 61 input_0 rows matched."),
    "nearest": ("0165bd33-0850-5d3e-9b86-fdfb7f359ac5", "3ec2adff-8f58-5e83-9055-f8918f7aa108",
                "359 pairs: 359 of 359 input_0 rows matched."),
    "edge-intersects": ("4e8407e1-d56b-59ea-ac6e-c61bdc73e308", "e469f1ae-c258-5ead-a240-a7d15e9832a9",
                               "3 pairs: 2 of 3 input_0 rows matched."),
    "edge-within": ("ae8ddaa2-f7ff-596f-b229-7789206ad513", "2bcc7dbd-c511-576d-a450-7bda1fe4b642",
                           "1 pair: 1 of 3 input_0 rows matched."),
}


def _example_spec() -> dict:
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def _node_type(spec: dict, node_id: str) -> str:
    return next(n["type"] for n in spec["dataflow"]["nodes"] if n["id"] == node_id)


@pytest.fixture()
def operations_canvas(app_frontend: "FrontendPage", current_server, page):
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Spatial Join Reader",
        username=f"sj_{uuid.uuid4().hex[:10]}",
        project_name="Spatial Join operations",
        project_spec=_example_spec(),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)
    dismiss_toasts(page)
    return page


def test_every_case_has_its_join_and_view():
    """#576: the cases above match the example, one per join, each feeding the view named for it."""
    spec = _example_spec()
    feeds = {(e["source"], e["target"]) for e in spec["dataflow"]["edges"]}
    joins = {n["id"] for n in spec["dataflow"]["nodes"] if n["type"] == "curio.builtin/spatial-join"}
    assert joins == {join for join, _, _ in CASES.values()}
    for case, (join, view, _) in CASES.items():
        assert (join, view) in feeds, f"{case}: join {join} does not feed view {view}"


@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
def test_each_spatial_join_case_pairs_and_draws(operations_canvas, case):
    """#576: one flow of example 25, played from its view."""
    page = operations_canvas
    spec = _example_spec()
    join, view, expected_status = CASES[case]
    simple_view = _node_type(spec, view) == "curio.builtin/vis-simple"

    if simple_view:
        # A Simple View has no play button. Run the loaders its join reads;
        # the join and the view follow on their own.
        for edge in spec["dataflow"]["edges"]:
            if edge["target"] == join:
                run_node_and_wait(page, edge["source"], node_type="DATA_LOADING", timeout_ms=120000)
    else:
        play_node(page, view)
    wait_for_node_done(page, join, node_type="SPATIAL_JOIN", timeout_ms=240000)
    status = node_locator(page, join).locator("[data-curio-spatial-join-status]")
    status.wait_for(state="visible", timeout=30000)
    assert status.inner_text() == expected_status, f"{case}: {status.inner_text()!r}"
    assert node_locator(page, join).locator("[data-curio-spatial-join-warning]").count() == 0

    if not simple_view:
        wait_for_node_done(page, view, node_type="VIS_VEGA", timeout_ms=120000)
        assert_vega_canvas_rendered(page, view)
    else:
        wait_for_node_settled(page, view, node_type="VIS_SIMPLE", timeout_ms=120000)
        # A Simple View says done when its input arrives, before its table
        # draws: wait for a row every case has. The point names are short
        # because the table cuts a long cell to its first characters.
        node_locator(page, view).get_by_text("inside", exact=True).first.wait_for(
            state="visible", timeout=30000
        )
        text = node_locator(page, view).inner_text()
        # The pairs the boundary rule gives: the edge point pairs with both
        # squares under intersects, and with neither under within.
        edge_rows = 2 if case == "edge-intersects" else 0
        assert text.count("on the edge") == edge_rows, text
        assert text.count("inside") == 1, text
        assert "outside" not in text, text
