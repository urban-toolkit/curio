"""Playwright E2E: the provenance drawer's Graph keeps a line into every version.

The Graph draws each version as a box and joins it to the version it was made
from with a line. The lines are drawn from where the boxes landed, so anything
that moves a box (opening one, which pushes every row under it down, or
flipping between the List and the Graph) must move its lines with it. A line
that is missing, has no length, or stops short of its boxes is the failure the
old provenance window had (#504: edges gone while the cards stayed).

Every count is taken inside the drawer: the dataflow canvas behind it has
edges of its own. It runs on the fixed catalog date, so the times the drawer
shows read the same in every frame.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_provenance_lines_e2e.py -v
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .utils import (
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    stub_login_and_enter_workflow,
    wait_for_drawer_closed,
)
from .walkthroughs import load_example_spec
from .walkthroughs.steps import (
    PROVENANCE_DRAWER,
    PROVENANCE_ITEM,
    PROVENANCE_LINK,
    PROVENANCE_PANEL,
    await_drawer_at_rest,
    await_provenance_history,
    open_version,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Any example with a few nodes: loading it records a version per node and per
#: connection, one chain the Graph draws as a column of boxes.
EXAMPLE = "01-vega-lite-chained-transforms.json"

TEST_NAME = "test_provenance_graph_keeps_a_line_into_every_version"

#: How many times slower than the runner Chromium runs while the drawer opens.
#: A wait that sleeps a fixed time passes on a fast runner and fails here; a
#: wait for the drawn lines passes on both.
CPU_THROTTLE = 4


@contextmanager
def _throttled_cpu(page, rate: int):
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": rate})
    try:
        yield
    finally:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        cdp.detach()


def _open_graph(page):
    page.get_by_role("button", name="View menu", exact=True).click()
    page.get_by_test_id("provenance-menu-item").click()
    panel = page.locator(PROVENANCE_PANEL)
    panel.wait_for(state="visible", timeout=20000)
    await_drawer_at_rest(page)
    panel.get_by_role("button", name="Graph", exact=True).click()
    await_provenance_history(page)
    return panel


def _lines(page) -> list[dict]:
    """Every line of the Graph: how the browser draws it, and how far each end
    is from the edge of the box it should meet."""
    return page.evaluate(
        """([item, link]) => {
            const boxes = {};
            for (const el of document.querySelectorAll(item)) {
                boxes[el.dataset.provenanceItem] = {
                    x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight,
                };
            }
            const HEAD = 34;
            return Array.from(document.querySelectorAll(link)).map((g) => {
                const path = g.querySelector('path');
                const a = boxes[g.dataset.from];
                const b = boxes[g.dataset.to];
                const length = path ? path.getTotalLength() : 0;
                const start = path && length > 0 ? path.getPointAtLength(0) : {x: NaN, y: NaN};
                const end = path && length > 0 ? path.getPointAtLength(length) : {x: NaN, y: NaN};
                const next = g.dataset.provenanceLink === 'next';
                const want = !a || !b ? null : next
                    ? [a.x + a.w / 2, a.y + a.h, b.x + b.w / 2, b.y]
                    : [a.x + a.w, a.y + HEAD / 2, b.x, b.y + HEAD / 2];
                const r = path ? path.getBoundingClientRect() : {width: 0, height: 0};
                const cs = path ? getComputedStyle(path) : {};
                return {
                    from: g.dataset.from, to: g.dataset.to, kind: g.dataset.provenanceLink,
                    length: Math.round(length),
                    off: want ? Math.max(
                        Math.abs(start.x - want[0]), Math.abs(start.y - want[1]),
                        Math.abs(end.x - want[2]), Math.abs(end.y - want[3]),
                    ) : Infinity,
                    w: Math.round(r.width), h: Math.round(r.height),
                    display: cs.display, visibility: cs.visibility, opacity: cs.opacity,
                };
            });
        }""",
        [PROVENANCE_ITEM, PROVENANCE_LINK],
    )


def _assert_every_line_drawn(page, when: str) -> list[dict]:
    versions = page.locator(PROVENANCE_ITEM).count()
    lines = _lines(page)
    # Every version but the first is made from one other, so a whole Graph has
    # one line into each version after the first.
    assert len(lines) == versions - 1, (
        f"{when}, the Graph shows {len(lines)} lines for {versions} versions; "
        f"a whole one has {versions - 1}"
    )
    broken = [
        line for line in lines
        if line["length"] == 0
        or line["off"] > 1.5
        or line["display"] == "none"
        or line["visibility"] == "hidden"
        or float(line["opacity"] or 1) == 0
        or (line["w"] == 0 and line["h"] == 0)
    ]
    assert not broken, (
        f"{when}, {len(broken)} of {len(lines)} lines are missing, have no "
        f"length or stop short of their boxes: {broken}"
    )
    return lines


@pytest.mark.catalog_calendar
def test_provenance_graph_keeps_a_line_into_every_version(
    app_frontend: "FrontendPage", current_server: str, page
):
    require_project_page()
    require_user_auth()

    page.emulate_media(reduced_motion="reduce")
    stub_login_and_enter_workflow(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="Prov User",
        username="prov_lines",
        project_name="Provenance Lines",
        project_spec=load_example_spec(EXAMPLE),
    )
    require_owner_view(page)
    page.wait_for_selector(".react-flow__node", timeout=45000)

    with _throttled_cpu(page, CPU_THROTTLE):
        panel = _open_graph(page)
        lines = _assert_every_line_drawn(page, "as the drawer opens")
    if not lines:
        # One version means no line at all, and the test would pass vacuously.
        raise AssertionError(
            "the provenance history has one version, so this test cannot tell "
            "a missing line from an empty chain"
        )
    assert {line["kind"] for line in lines} == {"next"}, (
        f"a loaded dataflow's history is one chain, yet the Graph drew {lines}"
    )

    save_workflow_test_screenshot(
        page, "provenance-lines-graph",
        test_name=TEST_NAME,
        fit_reactflow=False,
        clip_selector=PROVENANCE_PANEL,
    )

    # Open a version near the top: its box grows by its details and pushes every
    # box under it down, so every line under it must move too.
    versions = panel.locator("[data-provenance-item]")
    third = versions.nth(2)
    tops_before = [versions.nth(i).evaluate("el => el.offsetTop") for i in range(versions.count())]
    open_version(page, third)
    assert third.locator("svg").count() == 1, "the opened version shows no thumbnail"
    tops_after = [versions.nth(i).evaluate("el => el.offsetTop") for i in range(versions.count())]
    assert all(after > before for before, after in zip(tops_before[3:], tops_after[3:])), (
        f"opening version 3 did not push the versions under it down: {tops_before} -> {tops_after}"
    )
    _assert_every_line_drawn(page, "with version 3 open")

    save_workflow_test_screenshot(
        page, "provenance-lines-opened",
        test_name=TEST_NAME,
        fit_reactflow=False,
        clip_selector=PROVENANCE_PANEL,
    )

    # Closed again, and through a flip to the List and back: opened versions
    # stay open across the flip, closed ones closed.
    third.locator("button").first.click()
    _assert_every_line_drawn(page, "with version 3 closed again")
    open_version(page, third)
    panel.get_by_role("button", name="List", exact=True).click()
    panel.get_by_role("button", name="Graph", exact=True).click()
    await_provenance_history(page)
    assert third.locator("button").first.get_attribute("aria-expanded") == "true", (
        "version 3, opened before the flip, came back closed"
    )
    _assert_every_line_drawn(page, "after a flip to the List and back")

    page.keyboard.press("Escape")
    wait_for_drawer_closed(page, PROVENANCE_DRAWER)
