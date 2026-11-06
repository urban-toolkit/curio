"""Playwright E2E: a hosted guest's edits on an example are kept in its own copy.

On a Curio started with ``--deploy`` every visitor signs in to the one shared
guest account, which owns the examples. A visitor's canvas of an example is
bound to its own copy's doc: what it types is kept for that visit, survives a
reload, reaches its agents, and never reaches another visitor. The example
here is a dataflow the shared guest account owns, as a shipped one is, and
the language model is scripted.
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
#: What the scripted Researcher answers.
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


def _example(backend: str) -> str:
    """A dataflow the shared guest account owns, as every shipped example is."""
    signed_in = api_json(f"{backend}/api/auth/signin/guest", "", method="POST", payload={})
    return api_json(
        f"{backend}/api/testing/stub-project", "", method="POST",
        payload={"username": signed_in["user"]["username"], "name": "Guest edits", "spec": _spec()},
    )["id"]


def _session_token(page) -> str:
    for cookie in page.context.cookies():
        if cookie["name"] == "session_token":
            return cookie["value"]
    raise AssertionError("the guest's browser holds no session_token cookie")


def _open(page, base: str, example: str) -> None:
    """Open the example's link, which signs a browser with no account in to the
    shared guest account, and wait until its tab owns its own copy's room and
    the canvas is bound to that doc."""
    page.goto(f"{base}/dataflow/{example}", timeout=120000)
    node_locator(page, NODE).wait_for(timeout=30000)
    try:
        page.locator('[data-curio-room-role="owner"]').wait_for(state="attached", timeout=30000)
        page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError("the guest's tab never owned its own copy's room, with its doc bound") from exc


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


def test_a_hosted_guests_edit_is_kept_for_it_alone_and_its_agent_reads_it(app_frontend, current_server, browser):
    assert auth_enabled_env(), "this stack has no sign-in, so it has no hosted guest"
    assert allow_guest_login_env(), "this stack turns guest login off, so it has no hosted guest"
    base, backend = app_frontend.base_url, current_server
    example = _example(backend)
    contexts = []
    try:
        # A visitor changes the node's code: it is kept for its visit.
        contexts.append(browser.new_context(viewport={"width": 1280, "height": 768}))
        mine = contexts[-1].new_page()
        _open(mine, base, example)
        set_node_code(mine, NODE, EDITED)
        wait_for_changes_kept(mine)
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
        script_agent_replies(backend, QUOTE)
        answered = api_json(
            f"{backend}/api/agents/projects/{example}/attachments/{attached[0]['attachmentId']}/run",
            my_token, method="POST", payload={"message": "Quote this node's code."}, timeout=120,
        )
        assert QUOTE in json.dumps(answered), answered
        asked = json.dumps(captured_agent_prompts(backend))
        assert "trees = 13" in asked, "the Researcher was not handed the visitor's own code"
        # The other visitor's copy, and the example, are as they were.
        assert _spec_code(backend, their_token, example) == ORIGINAL
        assert read_node_code(theirs, NODE) == ORIGINAL
    finally:
        _request_json(f"{backend}/api/testing/llm-deployment", method="DELETE")
        for context in contexts:
            context.close()
