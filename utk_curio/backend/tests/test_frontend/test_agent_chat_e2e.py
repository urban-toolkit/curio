"""Playwright: one baseline screenshot per agent, plus a change and its Undo.

``test_agent_runs_e2e.py`` is the correctness gate - it proves every built-in
installs, attaches, composes its own prompt and runs, and it does so headless in
about a second per agent. This module covers what no assertion can see: that the
turn actually *renders*. Each parameter drives a real chat turn in the browser
and captures a committed baseline under the ``agent-run`` stem, so a restyle or a
broken panel shows up as an image diff for the agent it affected.

The screenshot is never the only check. A capture of an empty transcript or an
error banner would be written and passed just as silently as a good one (a
missing baseline becomes the baseline), so every parameter asserts the scripted
reply reached the transcript first.

**One login for all parameters.** ``TestAgentChatGallery`` holds a class-scoped
page, and ``fixtures.py::_clean_db`` names it in ``_SHARED_SESSION_CLASSES`` so
the DB is not truncated between methods - a reset would invalidate the stub
user's token while the browser still holds the cookie. Each parameter gets its
own stubbed *project* instead, so a canvas carries exactly one agent and the
captures stay legible.

Run::

    pytest utk_curio/backend/tests/test_frontend/test_agent_chat_e2e.py -v
    pytest utk_curio/backend/tests/test_frontend/test_agent_chat_e2e.py -k researcher -v --headed
"""
from __future__ import annotations

import re
import time
import uuid

import pytest
from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.manifest import AgentManifest, parse_agent_manifest

from .test_agent_runs_e2e import (
    CODE_NODE_ID,
    CREATED_CONTENT,
    DATA_NODE_ID,
    PLAN_NODE_TITLES,
    PROPOSED_CONTENT,
    VISIBLE_PROSE,
    _kinds,
    _mint_node_id,
    _native_replies,
    _node_requires,
    _project_spec,
    _scripted_replies,
    _target_for,
    _tool_ids,
)
from .utils import (
    NODE_ONLY_AGENT,
    NODE_ONLY_AGENT_NAME,
    _wait_for_reactflow_ready,
    api_json,
    captured_agent_offers,
    captured_agent_prompts,
    read_node_code,
    dismiss_toasts,
    ensure_node_only_agent,
    install_session_cookie,
    leave_agent_badge,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)

SCREENSHOT_STEM = "agent-run"
CHANGE_STEM = "agent-change-card"
NATIVE_STEM = "agent-native-call"

# The gallery baseline is the chat panel, not the viewport. A full-page capture
# here was more than half canvas and left rail - nothing about the agent - and a
# regression inside the panel then had to move 10% of a frame it only occupies
# part of before the comparison would notice.
CHAT_PANEL_SELECTOR = '[role="dialog"][aria-label^="Chat with"]'

USERNAME = "agentchat"
USER_NAME = "Agent Chat User"

def _spec_id(spec: AgentManifest) -> str:
    return spec.agent_id


def _coord(spec: AgentManifest) -> str:
    return spec.dir_name


@pytest.fixture(scope="class")
def agent_chat_session(workflow_page, frontend_server, current_server):
    """One authenticated browser session, shared by every parameter.

    Motion is disabled before the first navigation: the chat panel and the
    canvas both animate, and a visible-but-still-moving element makes ``click``
    time out with no useful message. The provider reads
    ``prefers-reduced-motion`` through ``useSyncExternalStore``, so emulating it
    makes presentation synchronous.
    """
    workflow_page.emulate_media(reduced_motion="reduce")
    login = stub_db_user(
        current_server, username=USERNAME, name=USER_NAME,
    )
    install_session_cookie(workflow_page, frontend_server, login["token"])
    use_scripted_llm(current_server, login["token"])
    return {
        "page": workflow_page,
        "frontend": frontend_server,
        "backend": current_server,
        "token": login["token"],
        "username": USERNAME,
    }


def _goto_when_served(page, url: str, *, timeout: float = 90.0) -> None:
    """Navigate, tolerating a frontend that has not bound its port yet.

    ``curio_servers`` gates on ``wait_for_port(frontend_port)``, and that gate
    can pass for the wrong reason: when a STALE process still holds 8080,
    ``curio.py start`` logs "Port 8080 in use by PID ...; Terminating stale
    process" and kills it, so the port answers, the fixture proceeds, and
    webpack binds several seconds later. The window is real - it produced a
    ``net::ERR_CONNECTION_REFUSED`` here while ``.curio/messages.log`` showed
    "Frontend server started successfully" four seconds AFTER the navigation.

    Retrying is the fix that belongs in a test; the gate itself is shared
    harness code and every browser module has the same exposure.
    """
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            page.goto(url)
            return
        except Exception as exc:  # noqa: BLE001 - narrowed below
            if "ERR_CONNECTION_REFUSED" not in str(exc):
                raise
            last = exc
            time.sleep(0.5)
    raise AssertionError(
        f"the frontend never accepted a connection at {url} within {timeout}s "
        f"(last: {last})"
    )


def _open_dataflow_with_agent(
    session, spec, *, project_name, replies, native_tools=False, node_ids=(),
):
    """A fresh project carrying exactly this one agent, open on the canvas.

    Install and attach go over HTTP - they are covered assertion-by-assertion in
    the headless module, and doing them through the drawer here would make every
    parameter pay for the drawer's own coverage. The browser's job starts at the
    rendered attachment.

    *node_ids* are the ids the nodes the agent's change creates are given
    (see :func:`_created_node_id`).
    """
    page, backend, token = session["page"], session["backend"], session["token"]
    # stub-project is keyed on the USERNAME, not the token, so the session has
    # to carry the account it was stubbed for - two classes here use different
    # users and a hardcoded name 404s as "unknown user".
    project = api_json(
        f"{backend}/api/testing/stub-project", token, method="POST",
        payload={
            "username": session["username"],
            "name": project_name,
            "spec": _project_spec(),
        },
    )
    project_id = project["id"]
    base = f"{backend}/api/agents/projects/{project_id}"

    coord = _coord(spec)
    api_json(f"{base}/install", token, method="POST", payload={"coord": coord})
    attachment = api_json(
        f"{base}/attachments", token, method="POST",
        payload={"coord": coord, "target": _target_for(spec)},
    )

    # Scripted before the page can send anything, so no turn can race ahead of
    # its reply and pick up the provider's fallback instead.
    script_agent_replies(backend, *replies, native_tools=native_tools, node_ids=node_ids)

    _goto_when_served(page, f"{session['frontend']}/dataflow/{project_id}")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    return project_id, attachment["attachmentId"], base


def _created_node_id(spec: AgentManifest) -> str:
    """The id the node this agent's change creates is given, the same every run.

    The change card prints it ("node <id>"), and that line sits near the
    width of the chat. A fresh uuid4 wraps it or not by how wide
    its letters render, one line more or less, and the transcript, pinned to the
    bottom, then moves everything above that line by a line height, so the
    ``_chat`` frame changed from run to run with nothing else changed.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"curio-e2e/agent-chat/{spec.agent_id}"))


def _saved_nodes(backend, token, project_id) -> list:
    """The nodes as the SERVER has them.

    Read from the saved dataflow rather than the React Flow store: a change
    that only reached the browser's state would be a bug, and the store cannot
    tell us that. ``canvas_nodes`` exists for store questions; this is a persistence
    question.
    """
    saved = api_json(f"{backend}/api/projects/{project_id}", token)
    return saved["spec"]["dataflow"]["nodes"]


def _wait_for_saved(backend, token, project_id, predicate, *, what: str, timeout=40.0):
    """Poll the saved dataflow until *predicate* holds, or fail saying what it
    was waiting for.

    The page can show a change before a later round trip reads it back from
    disk, so this waits instead of reading once.
    """
    deadline = time.time() + timeout
    nodes: list = []
    while time.time() < deadline:
        nodes = _saved_nodes(backend, token, project_id)
        if predicate(nodes):
            return nodes
        time.sleep(0.25)
    raise AssertionError(
        f"{what} never reached the saved dataflow within {timeout}s; nodes are "
        + repr([(n.get("id"), (n.get("content") or "")[:40]) for n in nodes])
    )


def _the_change_landed(panel):
    """The card of the change the turn's agent landed, with its Undo: an
    agent's node, code or plan lands with its reply and needs no Apply."""
    card = panel.get_by_role("group", name=re.compile(r"^Change: ")).first
    expect(card).to_be_visible(timeout=30000)
    expect(card.get_by_role("button", name="Undo")).to_be_visible(timeout=10000)
    return card


def _open_chat(page, spec):
    """Click the attachment's avatar and return its chat panel.

    Both entry points - the canvas dock and a node's badges - render the same
    ``AgentAvatarBadge``, so one locator covers either. Matched by prefix: once
    a turn has run, an auto-generated conversation title is appended to the
    display name (``"<Name>: <Title>"``).
    """
    opener = page.get_by_role(
        "button", name=re.compile(rf"^Open chat with {re.escape(spec.name)}")
    ).first
    expect(opener).to_be_visible(timeout=20000)
    opener.click()
    panel = page.get_by_role(
        "dialog", name=re.compile(rf"^Chat with {re.escape(spec.name)}")
    )
    expect(panel).to_be_visible(timeout=20000)
    return panel


def _send(panel, message: str):
    panel.get_by_role("textbox", name="Message this agent").fill(message)
    panel.get_by_role("button", name="Send", exact=True).click()


class TestAgentChatGallery:
    """One rendered chat turn, and one committed baseline, per catalog card."""

    @pytest.mark.parametrize(
        "spec", [m for m in builtin.list_builtin_manifests() if m.catalog.listed], ids=_spec_id,
    )
    def test_agent_chat_panel_baseline(self, spec, agent_chat_session):
        require_project_page()
        require_user_auth()
        page = agent_chat_session["page"]
        backend, token = agent_chat_session["backend"], agent_chat_session["token"]

        leg, tool, replies = _scripted_replies(spec)
        created_id = _created_node_id(spec) if tool == "node.create" else None
        project_id, _attachment_id, _base = _open_dataflow_with_agent(
            agent_chat_session, spec,
            project_name=f"Chat {spec.name}", replies=replies,
            node_ids=(created_id,) if created_id else (),
        )
        before = _saved_nodes(backend, token, project_id)

        panel = _open_chat(page, spec)
        _send(panel, f"Hello {spec.name}, show me what you do.")

        # The claim a screenshot cannot make on its own: the reply arrived and
        # rendered. Without it an empty panel would be captured as a baseline.
        expect(panel.get_by_text(VISIBLE_PROSE, exact=False)).to_be_visible(
            timeout=30000
        )

        if leg != "mint":
            # A report-only agent must NOT touch the canvas - that is its
            # contract, and it is the meaningful claim for these fifteen. The
            # panel is the only evidence there is, so it is what gets captured.
            assert _saved_nodes(backend, token, project_id) == before, (
                f"{spec.agent_id} is report-only but the dataflow changed"
            )
            dismiss_toasts(page)
            save_workflow_test_screenshot(
                page, SCREENSHOT_STEM, test_name=spec.agent_id,
                clip_selector=CHAT_PANEL_SELECTOR,
            )
            return

        # A mutate-capable agent gets held to the real thing: its change lands
        # with the reply, and the CANVAS changed. Testing that a chat looks
        # right would stop one step short of what the agent is for.
        _the_change_landed(panel)

        if tool == "node.content.write":
            node_id = _mint_node_id(spec)
            _wait_for_saved(
                backend, token, project_id,
                lambda nodes: any(
                    n["id"] == node_id and PROPOSED_CONTENT in (n.get("content") or "")
                    for n in nodes
                ),
                what=f"the agent's content for node {node_id}",
            )
            # And the canvas shows it, through the node's own Monaco instance.
            assert PROPOSED_CONTENT in read_node_code(page, node_id), (
                "the agent's content is on the server but not on the canvas"
            )
        else:
            # node.create ADDS a node; a plan adds all of its nodes at once.
            count = len(PLAN_NODE_TITLES) if tool == "dataflow.plan.write" else 1
            expected_content = (
                CREATED_CONTENT if tool == "node.create" else None
            )
            after = _wait_for_saved(
                backend, token, project_id,
                lambda nodes: len(nodes) >= len(before) + count,
                what=f"the node(s) added by {tool}",
            )
            added = [n for n in after if n["id"] not in {b["id"] for b in before}]
            assert len(added) == count, f"expected {count} new node(s), got {len(added)}"
            if expected_content is not None:
                assert expected_content in (added[0].get("content") or ""), (
                    f"the new node carries {added[0].get('content')!r}"
                )
            if created_id is not None:
                # Else the frame below is back to wrapping by chance.
                assert added[0]["id"] == created_id, (
                    f"the new node is {added[0]['id']}, not the scripted id "
                    f"{created_id}"
                )
            # The canvas really renders them, not just the saved spec.
            for node in added:
                expect(page.locator(f'[data-id="{node["id"]}"]')).to_be_visible(
                    timeout=20000
                )
            if created_id is not None:
                # And the change card names it: it is in the capture.
                expect(panel.get_by_text(f"node {created_id}")).to_be_visible(timeout=20000)

        dismiss_toasts(page)
        # Two captures, because there are two things worth seeing. First the
        # chat: the change card, naming what it changed, with its Undo.
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name=f"{spec.agent_id}_chat",
            clip_selector=CHAT_PANEL_SELECTOR,
        )
        # Then the canvas, which is the headline evidence and needs the panel out
        # of the way to be evidence at all: fitView spreads the nodes across the
        # whole viewport while the panel covers its right ~44%, so the node the
        # agent just created sits behind it.
        panel.get_by_role("button", name="Close chat").click()
        expect(page.locator(CHAT_PANEL_SELECTOR)).to_have_count(0, timeout=10000)
        leave_agent_badge(page)
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name=spec.agent_id,
        )


class TestAgentChangeCard:
    """A change lands with its reply, and its Undo takes it back: the one
    claim no capture makes.

    Deliberately its own class, so it gets a clean DB and a fresh user: it
    asserts against the saved dataflow, and sharing the gallery's long-lived
    session would leave that assertion reading state 21 projects deep.
    """

    def test_a_change_lands_with_the_reply_and_its_undo_puts_the_code_back(
        self, page, frontend_server, current_server,
    ):
        require_project_page()
        require_user_auth()
        spec = next(
            s for s in builtin.list_builtin_manifests()
            if s.agent_id == "agent.curio.node-builder"
        )
        assert "node.content.write" in _tool_ids(spec), (
            "this test needs an agent that writes a node's content; "
            f"{spec.agent_id} no longer declares node.content.write"
        )

        page.emulate_media(reduced_motion="reduce")
        login = stub_db_user(
            current_server, username="agentchange", name="Agent Change User",
        )
        install_session_cookie(page, frontend_server, login["token"])
        use_scripted_llm(current_server, login["token"])

        session = {
            "page": page, "frontend": frontend_server,
            "backend": current_server, "token": login["token"],
            "username": "agentchange",
        }
        node_id = DATA_NODE_ID if _node_requires(spec) else CODE_NODE_ID
        replies = [
            VISIBLE_PROSE
            + "\n\n```curio.v1\n"
            + (
                '{"toolRequest": {"tool": "node.content.write", "params": '
                f'{{"nodeId": "{node_id}", "content": "{PROPOSED_CONTENT}"}}}}}}'
            )
            + "\n```",
            "The node holds the new code.",
        ]
        project_id, _attachment_id, _base = _open_dataflow_with_agent(
            session, spec, project_name="Agent Change", replies=replies,
        )

        def _content_now() -> str:
            fresh = api_json(
                f"{current_server}/api/projects/{project_id}", login["token"]
            )
            node = next(
                n for n in fresh["spec"]["dataflow"]["nodes"] if n["id"] == node_id
            )
            return node.get("content") or ""

        def _wait_for(predicate, what: str) -> None:
            for _ in range(30 * 4):
                if predicate(_content_now()):
                    return
                page.wait_for_timeout(250)
            raise AssertionError(f"{what}; node {node_id} holds {_content_now()!r}")

        before = _content_now()
        assert PROPOSED_CONTENT not in before

        panel = _open_chat(page, spec)
        _send(panel, "Rewrite this node for me.")

        # 1. The change card renders with its Undo, and the node holds the
        #    agent's code at once: no Apply is the path to it.
        card = _the_change_landed(panel)
        _wait_for(lambda content: PROPOSED_CONTENT in content, "the change never reached the saved dataflow")
        # And the canvas shows it, through the node's own Monaco instance.
        assert PROPOSED_CONTENT in read_node_code(page, node_id), (
            "the change is on the server but not on the canvas"
        )

        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, CHANGE_STEM, test_name="landed",
        )

        # 2. Undo, and the node holds its code before again. Matched WITHOUT
        #    r.ok on purpose: a refused Undo reports its status here instead of
        #    timing out with nothing to say.
        with page.expect_response(
            lambda r: "/changes/" in r.url
            and r.url.endswith("/undo")
            and r.request.method == "POST",
            timeout=30000,
        ) as undo_response:
            card.get_by_role("button", name="Undo").click()
        response = undo_response.value
        assert response.ok, (
            f"the Undo request failed with HTTP {response.status}: "
            f"{response.text()[:300]}"
        )
        expect(card.get_by_text("Undone", exact=True)).to_be_visible(timeout=20000)
        _wait_for(lambda content: content == before, "the Undo never reached the saved dataflow")
        assert PROPOSED_CONTENT not in read_node_code(page, node_id), (
            "the Undo is on the server but not on the canvas"
        )

        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, CHANGE_STEM, test_name="undone",
        )


class TestNodeAttachedChatHeader:
    """What the header of a node-attached chat says it is attached to (#228).

    The panel used to compose that line from the attachment alone -
    ``Attached to node 6bea6863-…`` beside a ``session 8f2a1c33`` chip. Both
    ids are diagnostic, and a canvas holds several nodes of one type, so
    neither told the user which node they were talking to. The name now comes
    from ``resolveNodeDisplayLabel``, the same function the node's own header
    renders.
    """

    # Never a canvas agent (it attaches to nodes only), so the server cannot
    # answer a node attachment with a canvas one and leave this reading the
    # wrong header. Every card accepts the canvas, so a made-up agent, uploaded
    # to the account, stands in; this manifest only describes it to the helpers.
    SPEC = parse_agent_manifest({
        "id": NODE_ONLY_AGENT.split("@", 1)[0],
        "name": NODE_ONLY_AGENT_NAME,
        "category": "node",
        "version": "1.0.0",
        "purpose": "Answer questions about the node it is attached to.",
        "capabilities": [{"id": "node.explain", "contractVersion": "1"}],
        "compatibleTargets": [{"kind": "node", "requires": []}],
        "prompts": {"instruction": {"path": "prompts/instruction.md"}},
        "provenance": {"publisher": "e2e"},
    })

    def test_the_header_names_the_node_and_keeps_the_ids_on_the_tooltip(
        self, agent_chat_session,
    ):
        require_project_page()
        require_user_auth()
        assert "canvas" not in _kinds(self.SPEC), (
            f"{self.SPEC.agent_id} attaches to the canvas; this test needs an "
            "agent that never does"
        )
        page = agent_chat_session["page"]
        assert ensure_node_only_agent(
            agent_chat_session["backend"], agent_chat_session["token"],
        ) == _coord(self.SPEC)

        _open_dataflow_with_agent(
            agent_chat_session, self.SPEC,
            project_name="Chat header names its node", replies=(),
        )
        node_id = _mint_node_id(self.SPEC)
        panel = _open_chat(page, self.SPEC)

        subtitle = panel.get_by_text(re.compile(r"^Attached to "))
        expect(subtitle).to_be_visible(timeout=20000)
        header = subtitle.inner_text().strip()
        label = header[len("Attached to "):].strip()

        # The id itself, not just a uuid shape: this fixture mints readable
        # node ids ("agent-e2e-code"), so a regex over 36-char uuids would pass
        # here no matter what the header said. Both checks earn their place -
        # the uuid one is what a real project's ids look like.
        assert node_id not in header, f"the node id is still in the header: {header!r}"
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", header
        ), f"a uuid reached the header: {header!r}"
        assert label and label != "node", f"the header names nothing: {header!r}"

        # The canvas is the authority on what that node is called; the point of
        # the fix is that both surfaces read the same function.
        node = page.locator(f'.react-flow__node[data-id="{node_id}"]')
        expect(node).to_contain_text(label, timeout=20000)

        # Diagnostic, not gone: support still has to be able to recover both.
        tooltip = subtitle.get_attribute("data-tooltip") or ""
        assert node_id in tooltip, f"the node id left the tooltip too: {tooltip!r}"
        assert "session " in tooltip, f"the session id left the tooltip: {tooltip!r}"


class TestNativeToolCall:
    """A turn whose model calls its tool natively renders and lands like a
    fenced one: the reply, the change card, and the node it adds.

    What reached the model is read back from the scripted provider, since the
    page cannot show how the tool was asked for. Its own class, so it gets a
    clean DB and a fresh user, as the change-card test does.
    """

    def test_a_native_create_call_lands_its_node(
        self, page, frontend_server, current_server,
    ):
        from utk_curio.backend.app.agents.application import tools

        require_project_page()
        require_user_auth()
        spec = next(s for s in builtin.list_builtin_manifests() if s.agent_id == "agent.curio.node-builder")
        leg, tool, replies = _native_replies(spec)
        assert (leg, tool) == ("mint", "node.create"), (
            f"this test needs an agent whose characteristic call is node.create; "
            f"{spec.agent_id} now calls {tool!r}"
        )

        page.emulate_media(reduced_motion="reduce")
        login = stub_db_user(current_server, username="agentnative", name="Agent Native User")
        install_session_cookie(page, frontend_server, login["token"])
        use_scripted_llm(current_server, login["token"])
        session = {
            "page": page, "frontend": frontend_server,
            "backend": current_server, "token": login["token"],
            "username": "agentnative",
        }
        project_id, _attachment_id, _base = _open_dataflow_with_agent(
            session, spec, project_name="Native tool call", replies=replies,
            native_tools=True,
        )
        before = _saved_nodes(current_server, login["token"], project_id)

        panel = _open_chat(page, spec)
        _send(panel, "Add a node that prints a line.")

        # 1. The reply and the change card render, as for a fenced request.
        expect(panel.get_by_text(VISIBLE_PROSE, exact=False)).to_be_visible(timeout=30000)
        _the_change_landed(panel)

        # 2. It really was a native call: the tool was offered, the system turn
        #    taught no fenced syntax, and a tool message answered the call.
        offers = captured_agent_offers(current_server)
        assert tools.wire_name(tool) in offers[0]["tools"], offers[0]
        captured = captured_agent_prompts(current_server)
        assert '"toolRequest"' not in captured[0][0]["content"]
        result = captured[1][-1]
        assert result["role"] == "tool" and result["is_error"] is False, result

        # 3. The node the call added is saved and on the canvas, at once.
        after = _wait_for_saved(
            current_server, login["token"], project_id,
            lambda nodes: len(nodes) > len(before),
            what="the node the native call added",
        )
        added = [n for n in after if n["id"] not in {b["id"] for b in before}]
        assert len(added) == 1 and CREATED_CONTENT in (added[0].get("content") or ""), added
        expect(page.locator(f'[data-id="{added[0]["id"]}"]')).to_be_visible(timeout=20000)

        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, NATIVE_STEM, test_name="landed",
            clip_selector=CHAT_PANEL_SELECTOR,
        )

        panel.get_by_role("button", name="Close chat").click()
        expect(page.locator(CHAT_PANEL_SELECTOR)).to_have_count(0, timeout=10000)
        leave_agent_badge(page)
        save_workflow_test_screenshot(page, NATIVE_STEM, test_name="applied")
