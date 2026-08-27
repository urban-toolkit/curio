"""Playwright: one baseline screenshot per agent, plus the review round trip.

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
    pytest utk_curio/backend/tests/test_frontend/test_agent_chat_e2e.py -k node-explainer -v --headed
"""
from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import expect

from utk_curio.backend.app.agents import builtin

from .test_agent_runs_e2e import (
    CODE_NODE_ID,
    CREATED_CONTENT,
    DATA_NODE_ID,
    PLAN_NODE_TITLES,
    PROPOSED_CONTENT,
    VISIBLE_PROSE,
    _mint_node_id,
    _project_spec,
    _scripted_replies,
    _target_for,
)
from .utils import (
    _wait_for_reactflow_ready,
    api_json,
    read_node_code,
    dismiss_toasts,
    install_session_cookie,
    require_owner_view,
    require_project_page,
    require_user_auth,
    save_workflow_test_screenshot,
    script_agent_replies,
    stub_db_user,
    use_scripted_llm,
)

SCREENSHOT_STEM = "agent-run"
REVIEW_STEM = "agent-review-card"

# The gallery baseline is the chat panel, not the viewport. A full-page capture
# here was more than half canvas and left rail - nothing about the agent - and a
# regression inside the panel then had to move 20% of a frame it only occupies
# part of before the comparison would notice.
CHAT_PANEL_SELECTOR = '[role="dialog"][aria-label^="Chat with"]' 

USERNAME = "agentchat"
USER_NAME = "Agent Chat User"

def _spec_id(spec: builtin.BuiltinAgentSpec) -> str:
    return spec.agent_id


def _coord(spec: builtin.BuiltinAgentSpec) -> str:
    return f"{spec.agent_id}@{builtin.BUILTIN_VERSION}"


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


def _open_dataflow_with_agent(session, spec, *, project_name, replies):
    """A fresh project carrying exactly this one agent, open on the canvas.

    Install and attach go over HTTP - they are covered assertion-by-assertion in
    the headless module, and doing them through the drawer here would make every
    parameter pay for the drawer's own coverage. The browser's job starts at the
    rendered attachment.
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
    script_agent_replies(backend, *replies)

    _goto_when_served(page, f"{session['frontend']}/dataflow/{project_id}")
    page.wait_for_url(f"**/dataflow/{project_id}", timeout=20000)
    require_owner_view(page)
    _wait_for_reactflow_ready(page)
    return project_id, attachment["attachmentId"], base


def _saved_nodes(backend, token, project_id) -> list:
    """The nodes as the SERVER has them.

    Read from the saved dataflow rather than the React Flow store: an Apply that
    only reached the browser's state would be a bug, and the store cannot tell
    us that. ``canvas_nodes`` exists for store questions; this is a persistence
    question.
    """
    saved = api_json(f"{backend}/api/projects/{project_id}", token)
    return saved["spec"]["dataflow"]["nodes"]


def _wait_for_saved(backend, token, project_id, predicate, *, what: str, timeout=40.0):
    """Poll the saved dataflow until *predicate* holds, or fail saying what it
    was waiting for.

    Apply answers before the project save that carries it to disk, so the
    change lands on a later round trip.
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


def _apply_the_proposal(page, panel, tool: str):
    """Press the review control this proposal kind offers, and wait for the POST.

    A plan is applied per node (``apply-node``) rather than in one shot, so its
    control is the planned row's own button; every other kind has the card's
    single Apply. Matched without ``r.ok`` so a rejected apply reports its
    status instead of timing out with nothing to say.
    """
    if tool == "dataflow.plan.write":
        control = panel.get_by_role(
            "button", name=f"Create node {PLAN_NODE_TITLES[0]}"
        ).first
        expected = "/apply-node"
    else:
        control = panel.get_by_role("button", name=re.compile(r"^Apply")).first
        expected = "/apply"
    expect(control).to_be_visible(timeout=30000)
    with page.expect_response(
        lambda r: "/proposals/" in r.url
        and r.url.endswith(expected)
        and r.request.method == "POST",
        timeout=40000,
    ) as info:
        control.click()
    response = info.value
    assert response.ok, (
        f"applying {tool} failed with HTTP {response.status}: "
        f"{response.text()[:300]}"
    )


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
    """One rendered chat turn, and one committed baseline, per built-in agent."""

    @pytest.mark.parametrize("spec", builtin.BUILTIN_AGENTS, ids=_spec_id)
    def test_agent_chat_panel_baseline(self, spec, agent_chat_session):
        require_project_page()
        require_user_auth()
        page = agent_chat_session["page"]
        backend, token = agent_chat_session["backend"], agent_chat_session["token"]

        leg, tool, replies = _scripted_replies(spec)
        project_id, _attachment_id, _base = _open_dataflow_with_agent(
            agent_chat_session, spec,
            project_name=f"Chat {spec.name}", replies=replies,
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

        # A mutate-capable agent gets held to the real thing: apply its proposal
        # and prove the CANVAS changed. Testing that a chat looks right would
        # stop one step short of what the agent is for.
        _apply_the_proposal(page, panel, tool)

        if tool == "node.content.write":
            node_id = _mint_node_id(spec)
            _wait_for_saved(
                backend, token, project_id,
                lambda nodes: any(
                    n["id"] == node_id and PROPOSED_CONTENT in (n.get("content") or "")
                    for n in nodes
                ),
                what=f"the proposed content for node {node_id}",
            )
            # And the canvas shows it, through the node's own Monaco instance.
            assert PROPOSED_CONTENT in read_node_code(page, node_id), (
                "the applied content is on the server but not on the canvas"
            )
        else:
            # node.create and an applied plan node both ADD a node.
            expected_content = (
                CREATED_CONTENT if tool == "node.create" else None
            )
            after = _wait_for_saved(
                backend, token, project_id,
                lambda nodes: len(nodes) > len(before),
                what=f"a node added by {tool}",
            )
            added = [n for n in after if n["id"] not in {b["id"] for b in before}]
            assert len(added) == 1, f"expected one new node, got {len(added)}"
            if expected_content is not None:
                assert expected_content in (added[0].get("content") or ""), (
                    f"the new node carries {added[0].get('content')!r}"
                )
            # The canvas really renders it, not just the saved spec.
            expect(page.locator(f'[data-id="{added[0]["id"]}"]')).to_be_visible(
                timeout=20000
            )

        dismiss_toasts(page)
        # Two captures, because there are two things worth seeing. First the
        # chat: the card flipped to "Applied" and the runtime's result turn
        # naming the node and proposal it created.
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
        save_workflow_test_screenshot(
            page, SCREENSHOT_STEM, test_name=spec.agent_id,
        )


class TestAgentReviewCard:
    """A proposal is reviewed, then applied - the one claim no capture makes.

    Deliberately its own class, so it gets a clean DB and a fresh user: it
    asserts against the saved dataflow, and sharing the gallery's long-lived
    session would leave that assertion reading state 21 projects deep.
    """

    def test_review_before_apply_proposal_renders_and_applies(
        self, page, frontend_server, current_server,
    ):
        require_project_page()
        require_user_auth()
        spec = next(
            s for s in builtin.BUILTIN_AGENTS
            if s.agent_id == "agent.node-content-builder"
        )
        assert "node.content.write" in spec.tools, (
            "this test needs an agent that can propose a content replacement; "
            f"{spec.agent_id} no longer declares node.content.write"
        )

        page.emulate_media(reduced_motion="reduce")
        login = stub_db_user(
            current_server, username="agentreview", name="Agent Review User",
        )
        install_session_cookie(page, frontend_server, login["token"])
        use_scripted_llm(current_server, login["token"])

        session = {
            "page": page, "frontend": frontend_server,
            "backend": current_server, "token": login["token"],
            "username": "agentreview",
        }
        node_id = DATA_NODE_ID if spec.node_requires else CODE_NODE_ID
        replies = [
            VISIBLE_PROSE
            + "\n\n```curio.v1\n"
            + (
                '{"toolRequest": {"tool": "node.content.write", "params": '
                f'{{"nodeId": "{node_id}", "content": "{PROPOSED_CONTENT}"}}}}}}'
            )
            + "\n```",
            "I have proposed the change for your review.",
        ]
        project_id, _attachment_id, _base = _open_dataflow_with_agent(
            session, spec, project_name="Agent Review", replies=replies,
        )

        panel = _open_chat(page, spec)
        _send(panel, "Rewrite this node for me.")

        # 1. The review card renders, and it offers an Apply.
        apply_button = panel.get_by_role("button", name=re.compile(r"^Apply"))
        expect(apply_button.first).to_be_visible(timeout=30000)

        # 2. Nothing has changed yet (DEC-006: a mutate request mints a review,
        #    it never executes). Read the server, not the canvas - this is the
        #    state an Apply is supposed to be the only path to.
        saved = api_json(
            f"{current_server}/api/projects/{project_id}", login["token"]
        )
        before = next(
            n for n in saved["spec"]["dataflow"]["nodes"] if n["id"] == node_id
        )
        assert PROPOSED_CONTENT not in (before.get("content") or ""), (
            "the proposal was applied before the user approved it"
        )

        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, REVIEW_STEM, test_name="pending_review",
        )

        # 3. Apply, and the node really changes.
        # Matched WITHOUT r.ok on purpose. Requiring it turns a rejected apply
        # into a 30-second "waiting for event" timeout that names nothing; this
        # way the status is asserted where it can be reported. A 401 here means
        # the session died mid-test - the usual cause is a second E2E run
        # sharing this stack's ports and test DB, whose own e2e_clean_db
        # truncates user_session out from under this one.
        with page.expect_response(
            lambda r: "/proposals/" in r.url
            and r.url.endswith("/apply")
            and r.request.method == "POST",
            timeout=30000,
        ) as apply_response:
            apply_button.first.click()
        response = apply_response.value
        assert response.ok, (
            f"the apply request failed with HTTP {response.status}: "
            f"{response.text()[:300]}"
        )

        def _content_now() -> str:
            fresh = api_json(
                f"{current_server}/api/projects/{project_id}", login["token"]
            )
            node = next(
                n for n in fresh["spec"]["dataflow"]["nodes"] if n["id"] == node_id
            )
            return node.get("content") or ""

        # The apply response has returned, but the project save that carries it
        # to disk is a separate round trip.
        deadline = 30
        for _ in range(deadline * 4):
            if PROPOSED_CONTENT in _content_now():
                break
            page.wait_for_timeout(250)
        assert PROPOSED_CONTENT in _content_now(), (
            f"Apply did not reach the saved dataflow; node {node_id} still holds "
            f"{_content_now()!r}"
        )

        dismiss_toasts(page)
        save_workflow_test_screenshot(
            page, REVIEW_STEM, test_name="applied",
        )
