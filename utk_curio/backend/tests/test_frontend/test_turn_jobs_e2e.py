"""Playwright E2E: a chat turn runs on the server, and every editor's tab follows it (step 15b).

Ana owns a dataflow with the Researcher on its canvas. Ben, an editor she
invited, has it open too, and both have the Researcher's chat open.

Ben asks the Researcher something: Ana's open chat shows his message, named
after him, and then the reply, as the turn runs, with no reload. Ben asks
again, and this time the model takes its time. Ana reloads her page meanwhile
and opens the chat: Ben's message is there, his turn still running. She asks
too, and her message waits its turn. Ben closes his tab. His turn goes on: its
reply reaches Ana's chat after he left, and only then does her own turn start
and answer. The chat as the server keeps it says the four messages in that
order.

The model is the scripted one, its replies kept for the Researcher's
attachment; Ben's second reply is held at the model until the test lets it go.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    api_json,
    held_agent_calls,
    node_locator,
    release_agent_hold,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_login,
    use_scripted_llm,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER, EDITOR = "turns_owner_e2e", "turns_editor_e2e"
OWNER_NAME, EDITOR_NAME = "Turns Owner", "Turns Editor"
RESEARCHER = "agent.curio.researcher@1"
CA = "curio.builtin/computation-analysis"
NODE = "turns-node"
CHAT = '[role="dialog"][aria-label^="Chat with Researcher"]'
#: The hold Ben's second reply waits on at the model.
HOLD = "ben-second"


def _spec() -> dict:
    node = {"id": NODE, "type": CA, "x": 0, "y": 0, "content": "return 1", "goal": "One"}
    return {"name": "Turns as jobs", "dataflow": {"name": "Turns as jobs", "nodes": [node], "edges": []}}


class _Room:
    """Ana's dataflow, its Researcher, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.tokens: dict[str, str] = {}
        self.project_id = None

    def person(self, username: str, name: str, *, owns: bool = False):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
        self.contexts.append(context)
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Turns as jobs", "project_spec": _spec()} if owns else {}),
        )
        self.tokens[username] = login["token"]
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def attach(self, coord: str) -> str:
        """*coord* on Ana's canvas, answering on her scripted model; its attachment's id."""
        use_scripted_llm(self.backend, self.tokens[OWNER])
        base = f"{self.backend}/api/agents/projects/{self.project_id}"
        api_json(f"{base}/install", self.tokens[OWNER], method="POST", payload={"coord": coord})
        return api_json(f"{base}/attachments", self.tokens[OWNER], method="POST",
                        payload={"coord": coord, "target": {"kind": "canvas"}})["attachmentId"]

    def invite(self, username: str) -> None:
        api_json(f"{self.backend}/api/projects/{self.project_id}/editors", self.tokens[OWNER],
                 method="POST", payload={"username": username})

    def bound(self, page, role: str) -> None:
        """Wait until the dataflow's room names this tab *role* and its canvas
        is bound to the dataflow's doc."""
        node_locator(page, NODE).wait_for(timeout=30000)
        try:
            page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
            page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError(f"the dataflow's room never named this tab its {role}") from exc

    def open(self, page, role: str) -> None:
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        self.bound(page, role)

    def turns(self, attachment_id: str) -> list[tuple[str, str]]:
        """The chat as the server keeps it: each turn's role and text."""
        session = api_json(
            f"{self.backend}/api/agents/projects/{self.project_id}/attachments/{attachment_id}/session",
            self.tokens[OWNER],
        )
        return [(turn["role"], turn["text"]) for turn in session["turns"]]

    def close(self) -> None:
        for context in self.contexts:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - a context the test closed already
                pass


@pytest.fixture()
def room(app_frontend: "FrontendPage", current_server: str, browser):
    require_project_page()
    require_user_auth()
    opened = _Room(app_frontend.base_url, current_server, browser)
    try:
        yield opened
    finally:
        opened.close()


def _open_chat(page):
    """The Researcher's chat, opened from its badge in the canvas's dock."""
    opener = page.get_by_role("button", name="Open chat with Researcher").first
    expect(opener).to_be_visible(timeout=20000)
    opener.click()
    panel = page.locator(CHAT)
    expect(panel).to_be_visible(timeout=20000)
    return panel


def _send(panel, message: str) -> None:
    panel.get_by_role("textbox", name="Message this agent").fill(message)
    panel.get_by_role("button", name="Send", exact=True).click()


def _wait_until_held(backend: str, name: str, timeout: float = 30.0) -> None:
    """Wait until a turn's model call waits on the hold *name*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if held_agent_calls(backend).get(name):
            return
        time.sleep(0.1)
    raise AssertionError(f"no turn reached the model's hold {name!r}: {held_agent_calls(backend)}")


def test_an_editors_turn_goes_on_after_he_leaves_and_a_second_ask_waits_its_turn(room):
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    researcher = room.attach(RESEARCHER)
    editor = room.person(EDITOR, EDITOR_NAME)
    room.invite(EDITOR)
    room.open(owner, "owner")
    room.open(editor, "editor")
    ana, ben = _open_chat(owner), _open_chat(editor)

    # Ben asks: Ana's open chat follows his turn, his message named after him.
    script_agent_replies(room.backend, "The parks are in the loader.", attachment=researcher)
    _send(ben, "Where are the parks?")
    expect(ana.locator(f'[data-curio-writer="{EDITOR_NAME}"]', has_text="Where are the parks?")).to_be_visible(
        timeout=30000)
    expect(ana.get_by_text("The parks are in the loader.")).to_be_visible(timeout=30000)

    # Ben asks again, and the model takes its time.
    script_agent_replies(room.backend, {"text": "Ben's answer, after he left.", "hold": HOLD},
                         "Ana's answer.", attachment=researcher)
    _send(ben, "And the trees?")
    _wait_until_held(room.backend, HOLD)

    # Ana opens the chat mid-turn: Ben's message is there, his turn running.
    owner.reload()
    room.bound(owner, "owner")
    ana = _open_chat(owner)
    expect(ana.locator(f'[data-curio-writer="{EDITOR_NAME}"]', has_text="And the trees?")).to_be_visible(
        timeout=30000)
    expect(ana.get_by_role("button", name="Stop")).to_be_visible(timeout=20000)

    # Ana asks too: her message waits its turn.
    _send(ana, "Ana asks meanwhile.")
    waiting = ana.locator('[data-agent-ask-status="waiting"]')
    expect(waiting).to_contain_text("Ana asks meanwhile.", timeout=20000)
    expect(waiting).to_contain_text("Waiting its turn")

    # Ben closes his tab. His turn goes on, and Ana's waits for it.
    editor.context.close()
    expect(ana.get_by_text("Ana's answer.")).to_have_count(0)
    release_agent_hold(room.backend, HOLD)
    expect(ana.get_by_text("Ben's answer, after he left.")).to_be_visible(timeout=60000)
    expect(ana.get_by_text("Ana's answer.")).to_be_visible(timeout=60000)
    expect(waiting).to_have_count(0)

    deadline = time.monotonic() + 30
    said = room.turns(researcher)
    while len(said) < 6 and time.monotonic() < deadline:
        time.sleep(0.2)
        said = room.turns(researcher)
    assert said == [
        ("user", "Where are the parks?"), ("agent", "The parks are in the loader."),
        ("user", "And the trees?"), ("agent", "Ben's answer, after he left."),
        ("user", "Ana asks meanwhile."), ("agent", "Ana's answer."),
    ], said
