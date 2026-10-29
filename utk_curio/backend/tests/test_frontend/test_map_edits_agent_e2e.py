"""Playwright E2E: an agent's change to a Map Editor node (its type id is still
``curio.builtin/edit-features``) is an entry of the node's Provenance drawer,
named after the agent, and a reload keeps it.

The Node Builder, attached to the node, proposes code that removes a building;
the user applies it in the chat. The server writes the agent's code into the
dataflow's doc and keeps the change in the dataflow's history: the node holds
the agent's code, the history holds the entry with it, and after a reload the
drawer lists it under the agent's name. One close-up shows the drawer.

The dataflow has no map, so the test runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_map_edits_agent_e2e.py -v
"""
from __future__ import annotations

import json
import re
import time

from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin

from .test_agent_chat_e2e import _goto_when_served, _open_chat, _send
from .test_map_edits_e2e import _close_provenance, _entries, _open_provenance
from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    dismiss_toasts,
    frame_nodes,
    install_session_cookie,
    leave_agent_badge,
    node_locator,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_dataflow,
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)
from .walkthroughs.steps import PROVENANCE_PANEL, park_pointer_off_drawer

STEM = "map-edits-agent"
USERNAME = "mapeditsagent"
LOAD, EDIT = "mea-load", "mea-edit"
EDIT_TYPE = "curio.builtin/edit-features"
CHAT_PANEL = '[role="dialog"][aria-label^="Chat with"]'

#: Two buildings, by their building_id.
LOAD_CODE = 'import pandas as pd\nreturn pd.DataFrame({"building_id": [1, 2], "height": [20.0, 50.0]})\n'
#: The comment lines a Map Editor node's code starts with.
NOTE = (
    "# Map Editor writes this code from its edit list: each edit, in the\n"
    "# order it was made, on the features whose key is one of its ids. It is\n"
    "# written again when the list changes.\n"
)
NO_EDITS = NOTE + "return curio_edit_features(input_0, [])\n"
#: What the agent writes: building 2 removed.
AGENT_CODE = NOTE + (
    "return curio_edit_features(input_0, [\n"
    '    {"op": "remove", "ids": [2]},\n'
    '], key="building_id")\n'
)
#: The time column of the drawer's entries: hidden in the close-up, which
#: would otherwise change with the minute the test ran in.
ENTRY_TIMES = "[data-provenance-item] > button > span:nth-child(4) { visibility: hidden !important; }"


def _spec() -> dict:
    def node(node_id, node_type, x, content, title, goal=""):
        return {
            "id": node_id, "type": node_type, "x": x, "y": 0, "content": content, "title": title,
            "in": "DEFAULT", "out": "DEFAULT", "goal": goal,
            "metadata": {"keywords": [], "packageTemplateLabel": title},
        }

    return {
        "dataflow": {
            "name": "Map Editor by an agent",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "Map Editor by an agent",
            "nodes": [
                node(LOAD, "curio.builtin/data-loading", 0, LOAD_CODE, "Buildings"),
                node(EDIT, EDIT_TYPE, 700, NO_EDITS, "Map Editor", goal="Remove building 2 by its building_id"),
            ],
            "edges": [
                {"id": f"e-{LOAD}-{EDIT}", "source": LOAD, "target": EDIT, "sourceHandle": "out", "targetHandle": "in"},
            ],
        }
    }


def _write_reply() -> str:
    """The Node Builder's reply: a content replacement for the Map Editor node."""
    request = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": EDIT, "content": AGENT_CODE}}}
    return "I will remove building 2.\n\n```curio.v1\n" + json.dumps(request) + "\n```"


#: The code a canvas node holds, as a save writes it: its data, read from the
#: canvas, which a node showing its body rather than its editor holds too.
_NODE_CODE_JS = """(nodeId) => {
    const flow = window.__curio_reactFlow;
    const node = flow && flow.getNodes().find((n) => n.id === nodeId);
    const code = node && node.data ? (node.data.code ?? node.data.defaultCode) : null;
    return typeof code === "string" ? code : null;
}"""


def _wait_for_code(page, node_id: str, code: str, *, timeout: float = 30.0) -> None:
    """Wait until the node holds *code* on the canvas, as an apply writes an
    agent's code: without the blank lines around it."""
    page.wait_for_function("() => !!window.__curio_reactFlow", timeout=30000)
    deadline = time.time() + timeout
    held = None
    while time.time() < deadline:
        held = page.evaluate(_NODE_CODE_JS, node_id)
        if isinstance(held, str) and held.strip() == code.strip():
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"{node_id} never held the agent's code; it holds:\n{held}")


def test_an_agents_change_to_map_edits_is_an_entry_named_after_it_that_a_reload_keeps(
    page, frontend_server, current_server,
):
    """The Node Builder, attached to the Map Editor node, proposes a removal and
    the user applies it. The node holds the agent's code, and the dataflow's
    history keeps an entry of the node named after the agent with that code.
    Saved and opened again, the node's Provenance drawer lists it."""
    require_project_page()
    require_user_auth()
    agent = next(m for m in builtin.list_builtin_manifests() if m.agent_id == "agent.curio.node-builder")
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username=USERNAME, name="Map Editor Agent User")
    token = login["token"]
    install_session_cookie(page, frontend_server, token)
    use_scripted_llm(current_server, token)
    project_id = api_json(
        f"{current_server}/api/testing/stub-project", token, method="POST",
        payload={"username": USERNAME, "name": "Map Editor by an agent", "spec": _spec()},
    )["id"]
    base = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": agent.dir_name})
    api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": agent.dir_name, "target": {"kind": "node", "targetId": EDIT}},
    )
    script_agent_replies(current_server, _write_reply(), "I have proposed the change for your review.")

    _goto_when_served(page, f"{frontend_server}/dataflow/{project_id}")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    for node_id in (LOAD, EDIT):
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)

    # The agent proposes; the user applies.
    panel = _open_chat(page, agent)
    _send(panel, "Remove building 2 in this node.")
    apply = panel.get_by_role("button", name=re.compile(r"^Apply")).first
    expect(apply).to_be_visible(timeout=30000)
    with page.expect_response(
        lambda r: "/proposals/" in r.url and r.url.endswith("/apply") and r.request.method == "POST",
        timeout=30000,
    ) as applied:
        apply.click()
    assert applied.value.ok, f"the apply failed with HTTP {applied.value.status}: {applied.value.text()[:300]}"
    _wait_for_code(page, EDIT, AGENT_CODE)
    panel.get_by_role("button", name="Close chat").click()
    expect(page.locator(CHAT_PANEL)).to_have_count(0, timeout=10000)
    leave_agent_badge(page)

    # The node's history, which the server keeps, holds the agent's change,
    # named after it.
    history = api_json(f"{current_server}/api/projects/{project_id}/history/nodes/{EDIT}", token)["entries"]
    named = [entry for entry in history if entry.get("label") == agent.name]
    assert named, f"the history of the Map Editor node has no entry named {agent.name!r}: {history}"
    assert str(named[-1].get("code") or "").strip() == AGENT_CODE.strip(), named[-1]
    assert named[-1].get("kind") == "edit", named[-1]
    save_dataflow(page)

    # Opened again: the drawer lists it.
    page.reload()
    for node_id in (LOAD, EDIT):
        node_locator(page, node_id).wait_for(state="attached", timeout=45000)
    require_owner_view(page)
    frame_nodes(page, [EDIT])
    drawer = _open_provenance(page, EDIT)
    texts = [text for _entry, text in _entries(drawer)]
    assert any(agent.name in text for text in texts), (
        f"the Map Editor node's Provenance drawer lists {texts}, and no entry named {agent.name!r}"
    )
    dismiss_toasts(page)
    park_pointer_off_drawer(page)
    page.add_style_tag(content=ENTRY_TIMES)
    save_workflow_test_screenshot(
        page, STEM, test_name="map-edits-agent-entry", fit_reactflow=False, clip_selector=PROVENANCE_PANEL,
    )
    _close_provenance(page)
