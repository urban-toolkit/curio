"""Playwright: an agent attached to a connection is visible ON that connection.

Two affordances, one module (#296).

**The badge.** Before this, a connection-attached agent existed only as a row in
the canvas dock. The dock is viewport-anchored, so nothing on the canvas said
*which* connection the agent was about - a dataflow with four edges gave the same
picture whichever one you had attached to. A node attachment had its node badge
all along; a connection had nothing at the site.

**The drag-over highlight.** While dragging a palette row there was no way to
tell which connection would receive the drop until after letting go, and the
answer is a DOM hit-test through a wide invisible interaction path - not
something a user can predict by eye on a bezier passing close to two others.

The dock listing is asserted to SURVIVE, not to be replaced: the badge is only
reachable while its edge is on screen and unobscured, so dropping the roster
would strand an off-screen connection agent, undetachable.

Install and attach go over HTTP. They are covered assertion-by-assertion in
``test_agent_runs_e2e.py``; doing them through the drawer here would make this
module pay for the drawer's coverage to reach the thing it is actually about,
which is what renders afterwards.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_agent_connection_affordances_e2e.py -v
"""
from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import expect

from utk_curio.backend.app.agents import builtin

from .test_agent_runs_e2e import CODE_NODE_ID, _project_spec
from .utils import (
    CANVAS_DROP_TARGET,
    _wait_for_reactflow_ready,
    api_json,
    edge_client_point,
    install_session_cookie,
    require_owner_view,
    require_project_page,
    require_user_auth,
    stub_db_user,
)

USERNAME = "agentconnaff"
USER_NAME = "Connection Affordances User"

# The one built-in that declares ``connection`` among its compatibleTargets
# (builtin.py, targets=("node", "connection")). The fixture asserts that is
# still true, so a roster change fails loudly here instead of quietly attaching
# to a node and testing nothing.
AGENT_ID = "agent.connection-builder"

# The edge id in the shared spec both agent e2e modules build their canvas from.
EDGE_ID = "agent-e2e-edge"

DROP_HOVER = "[data-curio-drop-hover='true']"
EDGE_BADGES = "[data-curio-edge-badges]"


def _spec() -> builtin.BuiltinAgentSpec:
    for spec in builtin.BUILTIN_AGENTS:
        if spec.agent_id == AGENT_ID:
            return spec
    raise AssertionError(f"{AGENT_ID} is no longer in the built-in roster")


# Firing dragstart/dragover/drop in one page.evaluate is how the rest of the
# suite drives a drag (utils.py::_DRAG_TO_CANVAS_JS). That helper fires all four
# events back to back, which is right for testing a DROP and useless for testing
# what is true BETWEEN dragover and drop - so these stop after dragover and keep
# the DataTransfer on window, because a fresh one would read as a different drag.
_DRAG_OVER_JS = r"""({ source, targetSelector, clientX, clientY }) => {
    const target = document.querySelector(targetSelector);
    if (!target) return `no drop target matching ${targetSelector}`;
    const dragSource = source.hasAttribute("draggable")
        ? source
        : source.querySelector("[draggable]");
    if (!dragSource) return "source has no draggable element";
    window.__curioDragState = { dataTransfer: new DataTransfer(), dragSource };
    const dataTransfer = window.__curioDragState.dataTransfer;
    const fire = (el, type) => el.dispatchEvent(new DragEvent(type, {
        bubbles: true, cancelable: true, dataTransfer, clientX, clientY,
    }));
    fire(dragSource, "dragstart");
    fire(target, "dragover");
    return "ok";
}"""

_DRAG_MOVE_JS = r"""({ targetSelector, clientX, clientY }) => {
    const state = window.__curioDragState;
    if (!state) return "no drag in progress";
    const target = document.querySelector(targetSelector);
    if (!target) return `no drop target matching ${targetSelector}`;
    target.dispatchEvent(new DragEvent("dragover", {
        bubbles: true, cancelable: true,
        dataTransfer: state.dataTransfer, clientX, clientY,
    }));
    return "ok";
}"""

_DRAG_END_JS = r"""() => {
    const state = window.__curioDragState;
    if (!state) return "no drag in progress";
    state.dragSource.dispatchEvent(new DragEvent("dragend", {
        bubbles: true, cancelable: true, dataTransfer: state.dataTransfer,
    }));
    delete window.__curioDragState;
    return "ok";
}"""

_HOVERED_EDGE_IDS_JS = """(selector) =>
    Array.from(document.querySelectorAll(selector)).map((g) => {
        const edge = g.closest('.react-flow__edge');
        if (!edge) return null;
        const direct = edge.getAttribute('data-id');
        if (direct) return direct;
        const testId = edge.getAttribute('data-testid') || '';
        return testId.startsWith('rf__edge-')
            ? testId.slice('rf__edge-'.length)
            : null;
    })"""


def _agent_row(page, coord: str):
    return page.locator(f'#agents-palette [data-agent-coord="{coord}"]')


def _hovered_edge_ids(page) -> list:
    """Which edges are currently marked as the drag's target, by React Flow id."""
    return page.evaluate(_HOVERED_EDGE_IDS_JS, DROP_HOVER)


def _node_client_point(page, node_id: str):
    box = page.locator(f'.react-flow__node[data-id="{node_id}"]').bounding_box()
    assert box, f"node {node_id} has no layout box"
    return (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def _empty_canvas_point(page):
    """A point on the pane that resolves to neither a node nor an edge."""
    box = page.locator(CANVAS_DROP_TARGET).bounding_box()
    assert box, "the canvas drop target has no layout box"
    # Bottom-right corner: the shared spec puts both nodes along the top left,
    # and the left rail floats over the other side.
    return (box["x"] + box["width"] - 40, box["y"] + box["height"] - 40)


@pytest.fixture(scope="class")
def connection_agent_canvas(workflow_page, frontend_server, current_server):
    """A dataflow with two wired nodes and one agent attached to the edge."""
    require_project_page()
    require_user_auth()

    # The drawer providers and the chat panel both animate, and a
    # visible-but-still-moving element makes click() time out with nothing
    # useful to say. Emulated before the first navigation, per this directory's
    # README.
    workflow_page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username=USERNAME, name=USER_NAME)
    token = login["token"]
    install_session_cookie(workflow_page, frontend_server, token)

    project = api_json(
        f"{current_server}/api/testing/stub-project", token, method="POST",
        payload={
            "username": USERNAME,
            "name": "Connection Affordances",
            "spec": _project_spec(),
        },
    )
    project_id = project["id"]
    base = f"{current_server}/api/agents/projects/{project_id}"

    spec = _spec()
    assert "connection" in spec.target_kinds(), (
        f"{AGENT_ID} no longer accepts a connection target: {spec.target_kinds()}"
    )
    coord = f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": coord})
    attachment = api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": coord, "target": {"kind": "connection", "targetId": EDGE_ID}},
    )

    workflow_page.goto(f"{frontend_server}/dataflow/{project_id}")
    workflow_page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(workflow_page)
    _wait_for_reactflow_ready(workflow_page)

    return {
        "page": workflow_page,
        "backend": current_server,
        "token": token,
        "project_id": project_id,
        "coord": coord,
        "spec": spec,
        "attachment_id": attachment["attachmentId"],
    }


class TestConnectionAttachmentAffordances:
    """One canvas, one connection agent, both affordances."""

    def test_the_connection_carries_a_badge_and_the_dock_still_lists_it(
        self, connection_agent_canvas
    ):
        page = connection_agent_canvas["page"]
        name = connection_agent_canvas["spec"].name

        badges = page.locator(EDGE_BADGES)
        expect(badges).to_have_count(1, timeout=20000)
        assert badges.get_attribute("data-curio-edge-badges") == EDGE_ID, (
            "the badge is anchored to some other edge"
        )

        # TWO openers, not one: the badge on the connection AND the row in the
        # dock. The dock listing is the load-bearing half - the badge is only
        # reachable while its edge is on screen, so dropping the roster would
        # strand an off-screen connection agent.
        openers = page.get_by_role(
            "button", name=re.compile(rf"^Open chat with {re.escape(name)}")
        )
        expect(openers).to_have_count(2, timeout=20000)

        on_the_edge = badges.get_by_role(
            "button", name=re.compile(rf"^Open chat with {re.escape(name)}")
        )
        expect(on_the_edge).to_have_count(1)

        # And it is still detachable from the dock, which is the other half of
        # "remains listed (and detachable)".
        expect(
            page.get_by_role(
                "button", name=re.compile(rf"^Detach {re.escape(name)}")
            )
        ).to_have_count(2)

    def test_clicking_the_edge_badge_opens_that_attachment_chat(
        self, connection_agent_canvas
    ):
        page = connection_agent_canvas["page"]
        name = connection_agent_canvas["spec"].name

        page.locator(EDGE_BADGES).get_by_role(
            "button", name=re.compile(rf"^Open chat with {re.escape(name)}")
        ).click()
        panel = page.get_by_role(
            "dialog", name=re.compile(rf"^Chat with {re.escape(name)}")
        )
        expect(panel).to_be_visible(timeout=20000)
        # Closed again so the panel cannot occlude the canvas for the drag test.
        page.keyboard.press("Escape")
        expect(panel).to_have_count(0, timeout=20000)

    def test_dragging_an_agent_highlights_only_the_connection_under_it(
        self, connection_agent_canvas
    ):
        page = connection_agent_canvas["page"]
        coord = connection_agent_canvas["coord"]

        # The palette has to be open for its rows to exist; it is the same
        # dropdown the feature tour opens before its connection-attach beat.
        row = _agent_row(page, coord)
        if row.count() == 0 or not row.first.is_visible():
            page.get_by_role("button", name=re.compile("Agent Catalog")).first.click()
            row = _agent_row(page, coord)
        row.first.wait_for(state="visible", timeout=20000)
        row.first.scroll_into_view_if_needed()

        # A skip here used to be silent, which made it worth nothing: the
        # sampler starts at the curve's midpoint, which is exactly where this
        # edge's own badge now sits, so it found nothing and the whole claim
        # went untested. Carry the diagnostic into the skip reason so that
        # cannot happen quietly again.
        missed = {}
        point = edge_client_point(page, on_miss=lambda why: missed.update(why=why))
        if point is None:
            pytest.skip(f"no point on the edge resolves to an edge: {missed.get('why')}")

        result = page.evaluate(
            _DRAG_OVER_JS,
            {
                "source": row.first.element_handle(),
                "targetSelector": CANVAS_DROP_TARGET,
                "clientX": point[0],
                "clientY": point[1],
            },
        )
        assert result == "ok", f"the drag never started: {result}"

        # Exactly that connection, and no other.
        assert _hovered_edge_ids(page) == [EDGE_ID], (
            "dragging over the connection did not highlight exactly it: "
            f"{_hovered_edge_ids(page)}"
        )

        # A node under the pointer wins over any edge routed beneath it, and the
        # highlight follows the same precedence the drop does - it has to, they
        # call the same resolver.
        node_point = _node_client_point(page, CODE_NODE_ID)
        assert page.evaluate(_DRAG_MOVE_JS, {
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": node_point[0], "clientY": node_point[1],
        }) == "ok"
        assert _hovered_edge_ids(page) == [], (
            "an edge stayed highlighted while the pointer was over a node"
        )

        # Empty canvas highlights nothing.
        empty = _empty_canvas_point(page)
        assert page.evaluate(_DRAG_MOVE_JS, {
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": empty[0], "clientY": empty[1],
        }) == "ok"
        assert _hovered_edge_ids(page) == []

        # Back onto the edge, then end the drag WITHOUT dropping - the case only
        # the window-level dragend listener covers (Escape, or a release over
        # another application).
        assert page.evaluate(_DRAG_MOVE_JS, {
            "targetSelector": CANVAS_DROP_TARGET,
            "clientX": point[0], "clientY": point[1],
        }) == "ok"
        assert _hovered_edge_ids(page) == [EDGE_ID]

        assert page.evaluate(_DRAG_END_JS) == "ok"
        deadline = time.time() + 5
        while time.time() < deadline and _hovered_edge_ids(page):
            time.sleep(0.1)
        assert _hovered_edge_ids(page) == [], (
            "the highlight survived the end of the drag"
        )
