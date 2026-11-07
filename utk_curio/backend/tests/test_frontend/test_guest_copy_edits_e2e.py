"""Playwright E2E: a hosted guest's edits on an example are kept in its own copy.

On a Curio started with ``--deploy`` every visitor signs in to the one shared
guest account, which owns the examples. A visitor's canvas of an example is
bound to its own copy's doc: what it types is kept for that visit, survives a
reload, reaches its agents, and never reaches another visitor. The example
here is a dataflow the shared guest account owns, as a shipped one is, and
the language model is scripted.

On a stack without sign-in (CI's test-isolated job) the shared guest is the
one local user, which owns that dataflow: no copy is made, and its edit is the
dataflow's own, which every tab opens.
"""

from __future__ import annotations

import json

from playwright.sync_api import expect

from .utils import (
    allow_guest_login_env,
    api_json,
    auth_enabled_env,
    captured_agent_prompts,
    close_tools_palette,
    node_locator,
    open_tools_palette,
    read_node_code,
    script_agent_replies,
    set_node_code,
    wait_for_changes_kept,
    wait_for_node_code,
)
from .utils.canvas_authoring import _DRAG_TO_CANVAS_JS, CANVAS_DROP_TARGET
from .utils.db_stubs import _post_json, _request_json

NODE = "guest-trees"
ORIGINAL = "trees = 12\n"
EDITED = "trees = 13  # this visitor's own change\n"
RESEARCHER = "agent.curio.researcher@1"
#: The scripted Researcher's first reply: it reads the dataflow, its nodes'
#: code included, on the server. A turn's prompt holds no node's code by itself:
#: the model reads it (``dataflow.read``), or the chat panel sends the canvas.
READ_THE_DATAFLOW = (
    "Let me read the dataflow.\n\n```curio.v1\n"
    + json.dumps({"toolRequest": {"tool": "dataflow.read", "params": {"include": ["content"]}}})
    + "\n```"
)
#: Where the next call's messages hand the model what its read returned.
READ_RESULT = "[tool result] dataflow.read: ok\n"
#: What the scripted Researcher answers once it has read the dataflow.
QUOTE = "The node sets trees = 13."


def _spec() -> dict:
    return {
        "name": "Guest edits",
        "dataflow": {
            "name": "Guest edits",
            "nodes": [{
                "id": NODE, "type": "curio.builtin/python-computation", "x": 0, "y": 0,
                "content": ORIGINAL, "title": "Street trees",
            }],
            "edges": [],
        },
    }


def _example(backend: str, hosted: bool) -> tuple[str, str]:
    """A dataflow the shared guest account owns, as every shipped example is,
    and the token of the sign-in that asked for it: a hosted guest's with
    sign-in, the local guest's without."""
    route = "signin/guest" if hosted else "signin/auto-guest"
    signed_in = api_json(f"{backend}/api/auth/{route}", "", method="POST", payload={})
    example = api_json(
        f"{backend}/api/testing/stub-project", "", method="POST",
        payload={"username": signed_in["user"]["username"], "name": "Guest edits", "spec": _spec()},
    )["id"]
    return example, signed_in["token"]


def _session_token(page) -> str:
    for cookie in page.context.cookies():
        if cookie["name"] == "session_token":
            return cookie["value"]
    raise AssertionError("the guest's browser holds no session_token cookie")


def _open(page, base: str, example: str) -> None:
    """Open the example's link, which signs a browser with no account in to the
    shared guest account, and wait until its tab owns the room it joined (a
    hosted guest's, its own copy's) and the canvas is bound to that doc."""
    page.goto(f"{base}/dataflow/{example}", timeout=120000)
    node_locator(page, NODE).wait_for(timeout=30000)
    try:
        page.locator('[data-curio-room-role="owner"]').wait_for(state="attached", timeout=30000)
        page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError("the guest's tab never owned the room it joined, with its doc bound") from exc


def _spec_code(backend: str, token: str, example: str) -> str:
    """The node's code as the canvas of the visitor signed in as *token* opens it."""
    spec = api_json(f"{backend}/api/projects/{example}", token)["spec"]
    return next(n for n in spec["dataflow"]["nodes"] if n["id"] == NODE)["content"]


def _drop_on_the_node(page, coord: str) -> None:
    """Drag the agent *coord* from the rail's agent palette onto the node."""
    open_tools_palette(page, "agents")
    row = page.locator(f'#agents-palette [data-agent-coord="{coord}"]')
    row.wait_for(state="visible", timeout=20000)
    box = node_locator(page, NODE).bounding_box()
    assert box, f"node {NODE} has no layout box"
    dropped = page.evaluate(_DRAG_TO_CANVAS_JS, {
        "source": row.element_handle(), "targetSelector": CANVAS_DROP_TARGET,
        "clientX": box["x"] + box["width"] / 2, "clientY": box["y"] + box["height"] / 2,
    })
    assert dropped == "ok", f"the agent's drag failed: {dropped}"
    close_tools_palette(page, "agents")


def _code_the_read_returned(prompts: list) -> str:
    """The node's code in what the Researcher's ``dataflow.read`` returned, as
    the run's next call hands it to the model."""
    results = [
        message["content"][len(READ_RESULT):]
        for call in prompts for message in call
        if isinstance(message, dict) and isinstance(message.get("content"), str)
        and message["content"].startswith(READ_RESULT)
    ]
    assert results, f"the Researcher's dataflow.read never answered it: {json.dumps(prompts)[-3000:]}"
    try:
        read, _end = json.JSONDecoder().raw_decode(results[0])
    except ValueError as exc:
        raise AssertionError(f"the Researcher's dataflow.read returned no dataflow: {results[0][:3000]}") from exc
    nodes = (read.get("dataflow") or {}).get("nodes") or []
    found = [node.get("content") for node in nodes if isinstance(node, dict) and node.get("id") == NODE]
    assert found, f"the Researcher's dataflow.read holds no node {NODE}: {results[0][:3000]}"
    return found[0]


def _the_local_guests_edit_is_the_dataflows_own(browser, contexts, mine, base, backend, example, token) -> None:
    """Without sign-in the shared guest is the one local user and owns the
    dataflow: the edit is the dataflow's own, which a reload and another
    browser open, and the bar says Saved, never Kept for this visit."""
    save_state = mine.locator("[data-curio-save-state]")
    expect(save_state).to_have_text("Saved")
    expect(save_state).not_to_have_attribute("data-tooltip", "Sign in to save dataflows.")
    mine.reload()
    node_locator(mine, NODE).wait_for(timeout=30000)
    wait_for_node_code(mine, NODE, EDITED)
    assert _spec_code(backend, token, example) == EDITED
    contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}))
    another = contexts[-1].new_page()
    _open(another, base, example)
    wait_for_node_code(another, NODE, EDITED)


def test_a_hosted_guests_edit_is_kept_for_it_alone_and_its_agent_reads_it(app_frontend, current_server, browser):
    """With sign-in, a browser with no account is a hosted guest: its edit of
    an example is kept in its own copy, which a reload opens, another guest
    never sees, and its agent reads. Without sign-in the shared guest is the
    one local user: its edit is the dataflow's own
    (:func:`_the_local_guests_edit_is_the_dataflows_own`)."""
    hosted = auth_enabled_env()
    if hosted:
        assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
    base, backend = app_frontend.base_url, current_server
    example, made_by = _example(backend, hosted)
    contexts = []
    try:
        # A visitor changes the node's code.
        contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}))
        mine = contexts[-1].new_page()
        _open(mine, base, example)
        set_node_code(mine, NODE, EDITED)
        wait_for_changes_kept(mine)
        if not hosted:
            _the_local_guests_edit_is_the_dataflows_own(browser, contexts, mine, base, backend, example, made_by)
            return

        # A hosted guest's change is kept for its visit.
        expect(mine.locator("[data-curio-save-state]")).to_have_text("Kept for this visit")
        expect(mine.locator("[data-curio-save-state]")).to_have_attribute("data-tooltip", "Sign in to save dataflows.")

        # A reload opens the visitor's own copy, with the change.
        mine.reload()
        node_locator(mine, NODE).wait_for(timeout=30000)
        wait_for_node_code(mine, NODE, EDITED)
        my_token = _session_token(mine)
        assert _spec_code(backend, my_token, example) == EDITED

        # Another visitor opens the example as it was.
        contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}))
        theirs = contexts[-1].new_page()
        _open(theirs, base, example)
        wait_for_node_code(theirs, NODE, ORIGINAL)
        their_token = _session_token(theirs)
        assert their_token != my_token
        assert _spec_code(backend, their_token, example) == ORIGINAL

        # A Researcher the first visitor drops on the node reads its copy.
        _post_json(f"{backend}/api/testing/llm-deployment", {"scripted": True})
        api_json(f"{backend}/api/agents/projects/{example}/install", my_token, method="POST",
                 payload={"coord": RESEARCHER})
        _open(mine, base, example)
        wait_for_node_code(mine, NODE, EDITED)
        _drop_on_the_node(mine, RESEARCHER)
        expect(mine.get_by_text("Agent attached to the node.")).to_be_visible(timeout=30000)
        listed = api_json(f"{backend}/api/agents/projects/{example}/attachments", my_token)["attachments"]
        attached = [a for a in listed if (a.get("target") or {}).get("targetId") == NODE]
        assert attached, f"the guest's drop on the node attached no agent to it: {listed}"
        script_agent_replies(backend, READ_THE_DATAFLOW, QUOTE)
        answered = api_json(
            f"{backend}/api/agents/projects/{example}/attachments/{attached[0]['attachmentId']}/run",
            my_token, method="POST", payload={"message": "Quote this node's code."}, timeout=120,
        )
        assert QUOTE in json.dumps(answered), answered
        prompts = captured_agent_prompts(backend)
        # Its read on the server is of the visitor's own copy, not the example.
        read = _code_the_read_returned(prompts)
        assert read == EDITED, f"the Researcher's read of the dataflow holds {read!r}, not the visitor's own code"
        asked = json.dumps(prompts)
        assert "trees = 13" in asked, "the Researcher was not handed the visitor's own code"
        # The other visitor's copy, and the example, are as they were.
        assert _spec_code(backend, their_token, example) == ORIGINAL
        assert read_node_code(theirs, NODE) == ORIGINAL
    finally:
        _request_json(f"{backend}/api/testing/llm-deployment", method="DELETE")
        for context in contexts:
            context.close()
