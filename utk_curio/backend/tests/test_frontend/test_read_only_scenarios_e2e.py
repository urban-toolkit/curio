"""Playwright E2E: a read-only canvas shows a dataflow's scenarios as they are.

A visitor with no account opens another user's dataflow: the shared guest's
read-only canvas. Its scenarios and their set's shared groups are drawn as the
owner left them, and nothing there collapses or expands them:

* an expanded scenario's frame and an expanded shared group's frame have no
  Collapse;
* a double-click on a collapsed scenario's box, or on a collapsed shared
  group's box, leaves it collapsed.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_read_only_scenarios_e2e.py -v
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from .utils import (
    allow_guest_login_env,
    auth_enabled_env,
    dismiss_toasts,
    frame_nodes,
    node_locator,
    require_project_page,
    stub_db_user,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

SET = "ro-set"
OPEN = "ro-open"
SHUT = "ro-shut"


def _node(node_id: str, node_type: str, x: int, y: int, content: str) -> dict:
    return {
        "id": node_id, "type": node_type, "x": x, "y": y, "content": content,
        "in": "DEFAULT", "out": "DEFAULT", "goal": "", "metadata": {"keywords": []},
    }


def _spec() -> dict:
    """A loader read by two scenarios, Open (expanded) and Shut (collapsed),
    whose comparison is their set's shared outcome, drawn collapsed."""
    py = "curio.builtin/computation-analysis"
    edge = lambda s, t, h="in": {"id": f"e-{s}-{t}", "source": s, "target": t, "sourceHandle": "out", "targetHandle": h}  # noqa: E731
    return {"dataflow": {
        "name": "Read-only scenarios", "task": "", "timestamp": 1789193389280, "provenance_id": "ro",
        "nodes": [
            _node("ro-load", "curio.builtin/data-loading", 0, 0, "return 1"),
            _node("ro-a", py, 640, 0, "return input_0"),
            _node("ro-b", py, 640, 480, "return input_0"),
            _node("ro-compare", py, 1280, 240, "return input_0 + input_1"),
        ],
        "edges": [
            edge("ro-load", "ro-a"), edge("ro-load", "ro-b"),
            edge("ro-a", "ro-compare", "in"), edge("ro-b", "ro-compare", "in_1"),
        ],
        "scenarioSets": [{"id": SET, "name": "Read only", "shared": {"outcomes": {"collapsed": True}}}],
        "scenarios": [
            {"id": OPEN, "name": "Open", "color": "#3567c7", "nodes": ["ro-a"], "set": SET,
             "context": ["ro-load"], "outcomes": ["ro-compare"]},
            {"id": SHUT, "name": "Shut", "color": "#e86a3c", "nodes": ["ro-b"], "set": SET,
             "context": ["ro-load"], "outcomes": ["ro-compare"], "collapsed": True},
        ],
    }}


def _enter_read_only(page, app_frontend, current_server) -> None:
    if auth_enabled_env() and not allow_guest_login_env():
        pytest.skip("A visitor with no account needs guest sign-in (ALLOW_GUEST_LOGIN)")
    owner = stub_db_user(
        current_server,
        name="Scenario Owner",
        username=f"ro_scenarios_{uuid.uuid4().hex[:8]}",
        project_name="Read-only scenarios",
        project_spec=_spec(),
    )
    page.goto(f"{app_frontend.base_url}/dataflow/{owner['project']['id']}", timeout=120000)
    page.wait_for_load_state("domcontentloaded")
    banner = page.get_by_test_id("shared-view-banner")
    banner.wait_for(state="visible", timeout=30000)
    assert "read-only" in (banner.inner_text() or "").lower(), banner.inner_text()
    node_locator(page, "ro-a").wait_for(state="visible", timeout=45000)
    dismiss_toasts(page)
    frame_nodes(page, ["ro-load", "ro-a"])


def test_on_a_read_only_canvas_scenarios_and_shared_groups_neither_collapse_nor_expand(
    app_frontend: "FrontendPage", current_server, page,
):
    require_project_page()
    _enter_read_only(page, app_frontend, current_server)

    # The expanded scenario's frame and the expanded shared context's frame
    # are drawn, headers and all: what follows is about their controls.
    page.locator(f'[data-scenario-header="{OPEN}"]').wait_for(state="visible", timeout=15000)
    page.locator(f'[data-shared-header="group:{SET}:context"]').wait_for(state="visible", timeout=15000)

    # The expanded ones offer no Collapse.
    assert page.get_by_test_id(f"scenario-collapse-{OPEN}").count() == 0, (
        "the expanded scenario's frame offers Collapse on a read-only canvas"
    )
    assert page.get_by_test_id(f"shared-collapse-{SET}-context").count() == 0, (
        "the expanded shared context's frame offers Collapse on a read-only canvas"
    )

    # A double-click on a collapsed one leaves it collapsed.
    for box, hidden in ((f"scenario-box-{SHUT}", "ro-b"), (f"shared-box-{SET}-outcomes", "ro-compare")):
        target = page.get_by_test_id(box)
        target.wait_for(state="visible", timeout=15000)
        target.dispatch_event("dblclick")
        page.wait_for_timeout(500)
        assert target.is_visible(), f"a double-click on {box} expanded it on a read-only canvas"
        member = node_locator(page, hidden)
        member.wait_for(state="attached", timeout=10000)
        assert not member.is_visible(), f"{hidden} shows after a double-click on {box} on a read-only canvas"
