"""Playwright E2E: an agent's change to a Python node is an entry of the node's
Provenance drawer, named after the agent, holding the code it replaced.

The Node Builder, attached to a Python node that keeps the years from 2020 on,
writes code that drops that filter, and the change lands with its reply. The
server writes the code into the dataflow's doc and keeps the change in the
dataflow's history as an edit named after the agent, with the code it left and
the code it replaced, and the node's Provenance drawer lists it. One close-up
shows the drawer.

The dataflow runs nothing, so the test runs on any runner.

Run::

    CURIO_TESTING=1 pytest utk_curio/backend/tests/test_frontend/test_agent_provenance_e2e.py -v
"""
from __future__ import annotations

import json
import re

from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin

from .test_agent_chat_e2e import _goto_when_served, _open_chat, _send
from .test_map_edits_agent_e2e import ENTRY_TIMES, _wait_for_code
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
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)
from .walkthroughs.steps import PROVENANCE_PANEL, park_pointer_off_drawer

STEM = "agent-provenance"
USERNAME = "agentprovenance"
YEARS = "apv-years"
CHAT_PANEL = '[role="dialog"][aria-label^="Chat with"]'

#: What the node holds: the years from 2020 on.
BEFORE = (
    "import pandas as pd\n"
    'years = pd.DataFrame({"year": [2018, 2019, 2020, 2021]})\n'
    'return years[years["year"] >= 2020]\n'
)
#: What the agent writes: every year, the filter dropped.
AFTER = (
    "import pandas as pd\n"
    'years = pd.DataFrame({"year": [2018, 2019, 2020, 2021]})\n'
    "return years\n"
)


def _spec() -> dict:
    return {
        "dataflow": {
            "name": "An agent's change in a node's history",
            "task": "",
            "timestamp": 1789193389280,
            "provenance_id": "An agent's change in a node's history",
            "nodes": [{
                "id": YEARS, "type": "curio.builtin/computation-analysis", "x": 0, "y": 0,
                "content": BEFORE, "title": "Years", "in": "DEFAULT", "out": "DEFAULT",
                "goal": "Keep every year",
                "metadata": {"keywords": [], "packageTemplateLabel": "Years"},
            }],
            "edges": [],
        }
    }


def _write_reply() -> str:
    """The Node Builder's reply: a content replacement for the Python node."""
    request = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": YEARS, "content": AFTER}}}
    return "I will drop the filter on years.\n\n```curio.v1\n" + json.dumps(request) + "\n```"


def test_an_agents_change_to_a_python_node_is_an_entry_named_after_it_holding_the_code_it_replaced(
    page, frontend_server, current_server,
):
    """The Node Builder, attached to the Python node, writes new code, which
    lands with its reply. The node holds the agent's code; the dataflow's
    history keeps an edit of the node named after the agent, with the code it
    left and the code it replaced; the node's Provenance drawer lists it."""
    require_project_page()
    require_user_auth()
    agent = next(m for m in builtin.list_builtin_manifests() if m.agent_id == "agent.curio.node-builder")
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(current_server, username=USERNAME, name="Agent Provenance User")
    token = login["token"]
    install_session_cookie(page, frontend_server, token)
    use_scripted_llm(current_server, token)
    project_id = api_json(
        f"{current_server}/api/testing/stub-project", token, method="POST",
        payload={"username": USERNAME, "name": "An agent's change in a node's history", "spec": _spec()},
    )["id"]
    base = f"{current_server}/api/agents/projects/{project_id}"
    api_json(f"{base}/install", token, method="POST", payload={"coord": agent.dir_name})
    api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": agent.dir_name, "target": {"kind": "node", "targetId": YEARS}},
    )
    script_agent_replies(current_server, _write_reply(), "The node keeps every year now.")

    _goto_when_served(page, f"{frontend_server}/dataflow/{project_id}")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    node_locator(page, YEARS).wait_for(state="attached", timeout=45000)

    # The agent's change lands with its reply: its card, with its Undo.
    panel = _open_chat(page, agent)
    _send(panel, "Keep every year in this node.")
    card = panel.get_by_role("group", name=re.compile(r"^Change: ")).first
    expect(card).to_be_visible(timeout=30000)
    expect(card.get_by_role("button", name="Undo")).to_be_visible(timeout=10000)
    _wait_for_code(page, YEARS, AFTER)
    panel.get_by_role("button", name="Close chat").click()
    expect(page.locator(CHAT_PANEL)).to_have_count(0, timeout=10000)
    leave_agent_badge(page)

    # The node's history, which the server keeps, holds the agent's change,
    # named after it, with the code it left and the code it replaced.
    history = api_json(f"{current_server}/api/projects/{project_id}/history/nodes/{YEARS}", token)["entries"]
    named = [entry for entry in history if entry.get("label") == agent.name]
    assert named, f"the history of the Python node has no entry named {agent.name!r}: {history}"
    assert named[-1].get("kind") == "edit", named[-1]
    assert str(named[-1].get("code") or "").strip() == AFTER.strip(), named[-1]
    assert str(named[-1].get("before") or "").strip() == BEFORE.strip(), named[-1]

    # The node's Provenance drawer lists it.
    frame_nodes(page, [YEARS])
    drawer = _open_provenance(page, YEARS)
    texts = [text for _entry, text in _entries(drawer)]
    assert any(agent.name in text for text in texts), (
        f"the Python node's Provenance drawer lists {texts}, and no entry named {agent.name!r}"
    )
    dismiss_toasts(page)
    park_pointer_off_drawer(page)
    page.add_style_tag(content=ENTRY_TIMES)
    save_workflow_test_screenshot(
        page, STEM, test_name="agent-provenance-entry", fit_reactflow=False, clip_selector=PROVENANCE_PANEL,
    )
    _close_provenance(page)
