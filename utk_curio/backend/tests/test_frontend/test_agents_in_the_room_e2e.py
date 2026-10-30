"""Playwright E2E: an agent at work is in the room, and holds what it changes.

Ana owns a dataflow of two Data Export nodes, each of which opens on its
controls, with the Node Builder on the first. Ben, an editor she invited, has it
open too. Ana asks the Node Builder, through its chat's route, to put a line in
each node's code.

While it works, Ben's dock has its chip, and his Activity says it joined; it
leaves before its reply is answered, and Activity says what it did. Each node
it writes shows its code in both tabs while the agent holds it, then the tab
it had: its Widgets tab, but its code in Ben's tab for the node where Ben had
picked its code. Nothing moves on the canvas: a content edit plays no drag.

What each tab shows is recorded in the page as it happens, and read once the
reply is back: a frame would race the agent.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from .utils import (
    api_json,
    node_locator,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_login,
    use_scripted_llm,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

OWNER, EDITOR = "room_agent_owner_e2e", "room_agent_editor_e2e"
OWNER_NAME, EDITOR_NAME = "Room Owner", "Room Editor"
AGENT = "agent.curio.node-builder@1"
FIRST, SECOND = "room-export-first", "room-export-second"
EXPORT = "curio.builtin/data-export"
STARTER = "return curio_export(input_0, [!! file_name !!])\n"
WRITTEN = "# Written by the Node Builder.\n" + STARTER

DOCK = '[role="toolbar"][aria-label="Canvas agents"]'
PEOPLE = f'{DOCK} [role="group"][aria-label="People here"]'
ACTIVITY = f'{PEOPLE} button[aria-label="Activity"]'
ACTIVITY_LIST = '[role="region"][aria-label="Activity"]'


def _export(node_id: str, y: int) -> dict:
    return {
        "id": node_id, "type": EXPORT, "x": 0, "y": y, "content": STARTER,
        "metadata": {
            "keywords": [], "packageTemplateLabel": "Data Export",
            "widgets": [{"name": "file_name", "type": "text", "label": "File name", "default": ""}],
        },
    }


def _spec() -> dict:
    return {
        "name": "Agents in the room",
        "dataflow": {"name": "Agents in the room", "nodes": [_export(FIRST, 0), _export(SECOND, 520)], "edges": []},
    }


def _write_tail(node_id: str, content: str) -> str:
    request = {"toolRequest": {"tool": "node.content.write", "params": {"nodeId": node_id, "content": content}}}
    return "```curio.v1\n" + json.dumps(request) + "\n```"


# What the page shows, each time it changes: the agents' chips in the dock,
# and each node's tab and lock chip; with whether an agent's cursor is drawn,
# and every agent state that points or carries something.
_RECORD_JS = """(nodes) => {
    const log = [];
    const moved = [];
    window.__curio_in_the_room = {log, moved};
    const snapshot = () => {
        const dock = document.querySelector('[role="toolbar"][aria-label="Canvas agents"]');
        const chips = Array.from(dock ? dock.querySelectorAll('[data-collab-agent]') : [])
            .map((chip) => chip.getAttribute('aria-label'));
        const tabs = {};
        const locks = {};
        for (const id of nodes) {
            const node = document.querySelector(`.react-flow__node[data-id="${id}"]`);
            const tab = node && node.querySelector('.nav-link.active');
            const lock = node && node.querySelector('.collab-lock-chip');
            tabs[id] = tab ? tab.getAttribute('data-rr-ui-event-key') : null;
            locks[id] = lock ? lock.getAttribute('data-tooltip') : null;
        }
        const cursors = document.querySelectorAll('[data-agent-cursor], [data-agent-ghost]').length;
        return {chips, tabs, locks, cursors};
    };
    let last = '';
    const record = () => {
        const now = snapshot();
        const key = JSON.stringify(now);
        if (key !== last) {
            last = key;
            log.push(now);
        }
    };
    record();
    new MutationObserver(record).observe(document.body, {subtree: true, childList: true, attributes: true});
    const awareness = window.__curio_awareness;
    awareness.on('change', () => {
        for (const state of awareness.getStates().values()) {
            if (state && state.user && state.user.agent && (state.pointer || state.carrying)) {
                moved.push({pointer: state.pointer || null, carrying: state.carrying || null});
            }
        }
        record();
    });
}"""


class _Room:
    """Ana's dataflow, and a browser for each person who opens it."""

    def __init__(self, base: str, backend: str, browser):
        self.base, self.backend, self.browser = base, backend, browser
        self.contexts = []
        self.tokens: dict[str, str] = {}
        self.project_id = None
        self.attachment_id = None

    def person(self, username: str, name: str, *, owns: bool = False):
        context = self.browser.new_context(viewport={"width": 1280, "height": 768}, reduced_motion="reduce")
        self.contexts.append(context)
        page = context.new_page()
        login = stub_db_login(
            page, frontend_url=self.base, backend_url=self.backend, username=username, name=name,
            **({"project_name": "Agents in the room", "project_spec": _spec()} if owns else {}),
        )
        self.tokens[username] = login["token"]
        if owns:
            self.project_id = login["project"]["id"]
        return page

    def attach_agent(self) -> None:
        """The Node Builder on the first node, answering on Ana's scripted model."""
        use_scripted_llm(self.backend, self.tokens[OWNER])
        base = f"{self.backend}/api/agents/projects/{self.project_id}"
        api_json(f"{base}/install", self.tokens[OWNER], method="POST", payload={"coord": AGENT})
        attached = api_json(f"{base}/attachments", self.tokens[OWNER], method="POST",
                            payload={"coord": AGENT, "target": {"kind": "node", "targetId": FIRST}})
        self.attachment_id = attached["attachmentId"]

    def invite(self, username: str) -> None:
        api_json(f"{self.backend}/api/projects/{self.project_id}/editors", self.tokens[OWNER],
                 method="POST", payload={"username": username})

    def open(self, page, role: str) -> None:
        """Open the dataflow's link, and wait until its room names this tab
        *role* and the canvas is bound to the dataflow's doc."""
        page.goto(f"{self.base}/dataflow/{self.project_id}", timeout=120000)
        for node_id in (FIRST, SECOND):
            node_locator(page, node_id).wait_for(timeout=30000)
        try:
            page.locator(f'[data-curio-room-role="{role}"]').wait_for(state="attached", timeout=30000)
            page.wait_for_function("() => !!window.__curio_awareness", timeout=30000)
        except Exception as exc:  # noqa: BLE001 - said in the test's words
            raise AssertionError(f"the dataflow's room never named this tab its {role}, with its doc bound") from exc

    def ask(self, *replies: str) -> dict:
        """Ana asks the Node Builder, through its chat's route, which answers
        once the turn is over; the model's replies are *replies*."""
        script_agent_replies(self.backend, *replies)
        return api_json(
            f"{self.backend}/api/agents/projects/{self.project_id}/attachments/{self.attachment_id}/run",
            self.tokens[OWNER], method="POST", payload={"message": "Put a line in each node's code."}, timeout=120,
        )

    def close(self) -> None:
        for context in self.contexts:
            context.close()


@pytest.fixture()
def room(app_frontend: "FrontendPage", current_server: str, browser):
    require_project_page()
    require_user_auth()
    opened = _Room(app_frontend.base_url, current_server, browser)
    try:
        yield opened
    finally:
        opened.close()


def _ready(room: _Room):
    """Ana's tab and Ben's, on her dataflow with the Node Builder on its first
    node, each recording what it shows from now on."""
    owner = room.person(OWNER, OWNER_NAME, owns=True)
    room.attach_agent()
    editor = room.person(EDITOR, EDITOR_NAME)
    room.invite(EDITOR)
    room.open(owner, "owner")
    room.open(editor, "editor")
    return owner, editor


def _record(*pages) -> None:
    for page in pages:
        page.evaluate(_RECORD_JS, [FIRST, SECOND])


def _recorded(page) -> tuple[list, list]:
    found = page.evaluate("() => window.__curio_in_the_room")
    return found["log"], found["moved"]


def _tab(page, node_id: str) -> str | None:
    return node_locator(page, node_id).locator(".nav-link.active").first.get_attribute("data-rr-ui-event-key")


def _wait_until_gone(page, what: str) -> None:
    """Wait until no agent is in *page*'s dock and no node is held."""
    try:
        page.wait_for_function(
            """() => !document.querySelector('[role="toolbar"][aria-label="Canvas agents"] [data-collab-agent]')
                && !document.querySelector('.collab-lock-chip')""",
            timeout=15000,
        )
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError(f"{what} still shows the agent at work after its reply") from exc


def _wait_for_tab(page, node_id: str, tab: str, what: str) -> None:
    deadline = time.time() + 15
    while _tab(page, node_id) != tab and time.time() < deadline:
        page.wait_for_timeout(100)
    assert _tab(page, node_id) == tab, f"{what} shows {node_id}'s {_tab(page, node_id)} tab, not its {tab} tab"


def _code_while_held(log: list, node_id: str, what: str) -> None:
    """In *log*, *node_id* showed its code while the agent held it, and only
    then: each snapshot that shows its code shows the agent's lock on it."""
    held = [s for s in log if (s["locks"][node_id] or "").startswith(f"Editing: Node Builder (asked by {OWNER_NAME})")]
    assert held, f"{what} never showed the agent's lock on {node_id}: {log}"
    assert any(s["tabs"][node_id] == "code" for s in held), (
        f"{what} never showed {node_id}'s code while the agent held it: {log}"
    )
    stray = [s for s in log if s["tabs"][node_id] == "code" and s not in held]
    assert not stray, f"{what} showed {node_id}'s code while the agent did not hold it: {stray}"


def test_the_agent_is_in_the_room_while_it_works_and_gone_before_its_reply(room):
    owner, editor = _ready(room)
    _record(owner, editor)

    reply = room.ask(_write_tail(FIRST, WRITTEN), "The node says who wrote it.")

    assert [card["status"] for card in reply["content"] if card.get("type") == "change"] == ["applied"], reply
    for page, what in ((owner, "Ana's tab"), (editor, "Ben's tab")):
        _wait_until_gone(page, what)
    log, moved = _recorded(editor)
    chips = [label for snapshot in log for label in snapshot["chips"]]
    assert any(label.startswith(f"Node Builder (asked by {OWNER_NAME})") for label in chips), (
        f"Ben's dock never showed the Node Builder at work: {log}"
    )
    assert log[-1]["chips"] == [], f"Ben's dock still shows the agent: {log[-1]}"

    # Ben's Activity: the agent joined, asked by Ana, then left saying what it did.
    editor.locator(ACTIVITY).click()
    activity = editor.locator(ACTIVITY_LIST)
    activity.wait_for(timeout=10000)
    lines = activity.locator("li").all_inner_texts()
    assert lines[:2] == ["Node Builder left: changed 1 node", f"Node Builder joined, asked by {OWNER_NAME}"], (
        f"Ben's Activity lists {lines}"
    )

    # A content edit plays no drag: no agent cursor or ghost, in either tab.
    for page, what in ((owner, "Ana's tab"), (editor, "Ben's tab")):
        log, moved = _recorded(page)
        assert moved == [], f"the agent pointed or carried something in {what}: {moved}"
        assert all(snapshot["cursors"] == 0 for snapshot in log), f"{what} drew an agent's cursor: {log}"


def test_a_node_the_agent_writes_shows_its_code_in_every_tab_while_held_then_the_tab_each_had(room):
    owner, editor = _ready(room)
    for page in (owner, editor):
        for node_id in (FIRST, SECOND):
            _wait_for_tab(page, node_id, "widgets", "a tab as the dataflow opened")
    # Ben picked the second node's code before the agent wrote it; nothing of
    # his holds the node, so the agent writes it.
    node_locator(editor, SECOND).locator('.nav-link[data-rr-ui-event-key="code"]').first.click()
    _wait_for_tab(editor, SECOND, "code", "Ben's tab, once he picked the second node's code")
    editor.evaluate("() => document.activeElement && document.activeElement.blur && document.activeElement.blur()")
    try:
        owner.wait_for_function("() => !document.querySelector('.collab-lock-chip')", timeout=15000)
    except Exception as exc:  # noqa: BLE001 - said in the test's words
        raise AssertionError("Ben still holds a node in Ana's tab after picking its code") from exc
    _record(owner, editor)

    reply = room.ask(_write_tail(FIRST, WRITTEN), _write_tail(SECOND, WRITTEN), "Both nodes say who wrote them.")

    assert [card["status"] for card in reply["content"] if card.get("type") == "change"] == ["applied", "applied"], reply
    for page, what in ((owner, "Ana's tab"), (editor, "Ben's tab")):
        _wait_until_gone(page, what)
    owners, owner_moved = _recorded(owner)
    editors, editor_moved = _recorded(editor)
    # Each node showed its code in Ana's tab while the agent held it, then its
    # Widgets tab again, as a node that opens on its controls.
    for node_id in (FIRST, SECOND):
        _code_while_held(owners, node_id, "Ana's tab")
        _wait_for_tab(owner, node_id, "widgets", "Ana's tab, once the agent let go")
    # The same in Ben's tab for the first node.
    _code_while_held(editors, FIRST, "Ben's tab")
    _wait_for_tab(editor, FIRST, "widgets", "Ben's tab, once the agent let go")
    # The second showed its code in Ben's tab all along, as he picked, and stays.
    assert all(snapshot["tabs"][SECOND] == "code" for snapshot in editors), (
        f"Ben's tab turned the second node from the code he picked: {editors}"
    )
    assert any((s["locks"][SECOND] or "").startswith("Editing: Node Builder") for s in editors), (
        f"Ben's tab never showed the agent holding the second node: {editors}"
    )
    _wait_for_tab(editor, SECOND, "code", "Ben's tab, once the agent let go")
    # Nothing moved: a content edit plays no drag.
    assert owner_moved == [] and editor_moved == [], (owner_moved, editor_moved)
    assert all(s["cursors"] == 0 for s in owners + editors), "a tab drew an agent's cursor"
    saved = api_json(f"{room.backend}/api/projects/{room.project_id}", room.tokens[OWNER])
    contents = {node["id"]: node["content"] for node in saved["spec"]["dataflow"]["nodes"]}
    assert contents == {FIRST: WRITTEN, SECOND: WRITTEN}, contents
