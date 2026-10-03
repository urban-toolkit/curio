"""The scene on a node-attached chat naming its node."""
from __future__ import annotations

import re

from playwright.sync_api import expect

from ..utils import require_owner_view
from .framework import Ctx, walkthrough
from .steps import first_node_of_type, frame_until_on_top


AGENT_CHAT_EXAMPLE = "01-vega-lite-chained-transforms.json"
AGENT_CHAT_NODE_NAME = "Crash counts by hour"


@walkthrough(
    slug="agent-chat-names-its-node",
    refs=[228],
    title="A node-attached chat names its node",
    premise="Rename a node, attach an agent to it, then read the chat header.",
    note="The header composed its subtitle from the attachment alone - "
         "\"Attached to node cd3b6afc-900d-417c-8064-375ed01a912f\", beside a "
         "\"session 8f2a1c33\" chip. Neither id says which node the user is "
         "talking to, and a canvas can hold several nodes of the same type. "
         "The name now comes from resolveNodeDisplayLabel, the function the "
         "node's own header renders, so the chat and the canvas say the same "
         "thing - including after a rename, because the overlay reads it off "
         "the React Flow store rather than a snapshot. Both ids moved to the "
         "subtitle's tooltip, where support can still recover them.",
    tests=["src/tests/attach/AgentChatPanel.test.tsx",
           "test_frontend/test_agent_chat_e2e.py"],
    example=AGENT_CHAT_EXAMPLE,
    # The header, not the canvas and not the whole panel: the claim is one line
    # of it. A full-page capture would spend the budget on six nodes that are
    # not the subject, and the panel itself is mostly empty transcript - the
    # header line was under 3% of it, so a budget loose enough for a Linux
    # runner would have waved a reverted header straight through. Every capture
    # in this scene therefore has to happen with the chat open.
    clip_selector='[data-curio-chat-header="true"]',
    fit_reactflow=False,
    # The subject fills the frame, so a header that went back to a uuid moves
    # far more than a tenth of it. The claim is asserted in code below either
    # way.
    max_diff_ratio=0.10,
)
def agent_chat_names_its_node(ctx: Ctx) -> None:
    page = ctx.page
    node_id = first_node_of_type(AGENT_CHAT_EXAMPLE, "curio.builtin/vis-vega")
    node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
    node.wait_for(state="visible", timeout=45000)

    # Attaching goes over HTTP, as in dataflow-goal-is-readable: dragging an
    # agent from the roster onto a node is a different journey, and this scene
    # is about what the header says once one is attached.
    token = page.evaluate(
        "() => (document.cookie.match(/(?:^|; )session_token=([^;]*)/) || [])[1] || ''"
    )
    assert token, "no session cookie; the scene cannot attach an agent"
    project_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    base = f"{ctx.backend}/api/agents/projects/{project_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Node-only by roster, so the server cannot quietly fall back to a canvas
    # attachment and leave this scene photographing the wrong header.
    coord = "agent.node-content-builder@1.0.0"

    installed = page.request.post(f"{base}/install", headers=headers, data={"coord": coord})
    assert installed.ok, f"install failed: {installed.status} {installed.text()[:200]}"
    attached = page.request.post(
        f"{base}/attachments",
        headers=headers,
        data={"coord": coord, "target": {"kind": "node", "targetId": node_id}},
    )
    assert attached.ok, f"attach failed: {attached.status} {attached.text()[:200]}"

    # The badge is rendered from the attachment list the page fetches, so
    # reload rather than wait for a push that may never come.
    page.reload()
    require_owner_view(page)
    # React Flow rebuilds the canvas after the reload; the scene needs the node
    # back before it can rename it.
    node.wait_for(state="visible", timeout=45000)
    ctx.beat(800)

    # Rename AFTER the reload. A type label ("Vega-Lite") would appear in the
    # header whether or not the lookup reached the canvas, so a name only this
    # node carries is what proves it did - and renaming here proves the second
    # half too: the overlay reads the label off the React Flow store, so an
    # open chat follows a rename without a round trip. Renaming BEFORE the
    # reload proved neither: the save is debounced, the reload beat it, and the
    # header came back reading "Attached to Vega-Lite".
    rename = node.get_by_role("button", name=re.compile("^Edit node title: "))
    # At fit zoom the chart's header sits under the menu bar (#493), where the
    # rename click would land on the bar. The capture is clipped to the chat
    # header, so framing the node changes no frame.
    frame_until_on_top(page, node_id, rename)
    ctx.focus(rename, hold=700)
    ctx.say("Name the node", "The chat header should follow this, not a uuid.")
    rename.click()
    title_input = node.get_by_role("textbox", name="Node title")
    title_input.fill(AGENT_CHAT_NODE_NAME)
    title_input.press("Enter")
    expect(node).to_contain_text(AGENT_CHAT_NODE_NAME)

    opener = page.get_by_role(
        "button", name=re.compile("^Open chat with Node Content Builder")
    ).first
    ctx.focus(opener, hold=700)
    ctx.say("Open its chat", "One agent, attached to that one node.")
    opener.click()

    panel = page.get_by_role("dialog", name=re.compile("^Chat with Node Content Builder"))
    expect(panel).to_be_visible(timeout=20000)

    subtitle = panel.get_by_text(re.compile(r"^Attached to "))
    expect(subtitle).to_have_text(f"Attached to {AGENT_CHAT_NODE_NAME}")
    # Both ids are still recoverable, just not in the reading line.
    tooltip = subtitle.get_attribute("title") or ""
    assert node_id in tooltip, f"the node id left the tooltip too: {tooltip!r}"
    assert "session " in tooltip, f"the session id left the tooltip: {tooltip!r}"

    ctx.say("It names the node", "The ids are on the tooltip, not in the header.")
    ctx.capture("names-the-node")
