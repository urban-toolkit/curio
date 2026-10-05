"""Playwright E2E: API Settings keeps named LLM configurations, and no key ever
reaches the page.

Covers the panel's lasting promises:

- **#241** - the Model field offers what the endpoint serves. Fetch models asks
  Anthropic and Gemini too, and when it cannot it replays what that endpoint
  last reported, labelled as a replay.
- **#242** - a saved key belongs to one endpoint. A configuration reports
  whether it holds a key and never the key; the editor says "saved" only on the
  configuration's own endpoint, and moving the configuration elsewhere never
  carries the key along.
- The default chosen on Agent configuration is the configuration that answers
  the next run, and an agent given a configuration of its own there runs on
  it, even when another agent delegates to it.

Nothing here reaches a provider. The #241 cases use the no-key short circuit
(the backend refuses without opening a socket) and stubbed responses for the
shapes that would otherwise need a live key; the configuration cases only
exercise ``/api/agents/llm``, and the run uses the scripted provider.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_api_settings_e2e.py -v
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from utk_curio.backend.app.agents.domain import builtin

from .utils import (
    api_json,
    captured_agent_calls,
    require_project_page,
    require_user_auth,
    script_agent_replies,
    stub_db_login,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

#: Long enough to be unmistakable in a page dump, and never a real key.
KEY = "AIza-e2e-" + "k" * 24
SAVED = "(saved - leave blank to keep)"


@pytest.fixture()
def signed_in(app_frontend: "FrontendPage", current_server: str, page, request):
    """Sign in and land on the projects page, whose header links API Settings.

    From a section page the header goes to the settings page, which holds the
    same panel the canvas opens in a drawer (test_canvas_header_e2e.py).
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    login = stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="API Settings User",
        username=f"apisettings_{abs(hash(request.node.name)) % 10**8}",
        project_name="ApiSettings",
    )
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=15000)
    return SimpleNamespace(page=page, token=login["token"], backend=current_server)


def _wait_for_keys(page):
    expect(
        page.get_by_role("heading", name="API Settings", level=1)
    ).to_be_visible(timeout=15000)
    # The list has loaded once its Add button is there.
    expect(_section(page).get_by_role("button", name="Add configuration")).to_be_visible(
        timeout=15000
    )


def _open_api_settings(page):
    page.get_by_role("link", name="API Settings", exact=True).click()
    page.wait_for_url(re.compile(r"/settings/keys$"), timeout=15000)
    _wait_for_keys(page)


def _show_tab(page, name: str):
    page.get_by_role("tab", name=name, exact=True).click()
    expect(page.get_by_role("tab", name=name, exact=True)).to_have_attribute(
        "aria-selected", "true"
    )


@pytest.fixture()
def api_settings(signed_in):
    _open_api_settings(signed_in.page)
    return signed_in


def _section(page):
    return page.get_by_test_id("api-keys-tab")


def _editor(page):
    return page.get_by_test_id("llm-config-editor")


def _open_editor(page):
    _section(page).get_by_role("button", name="Add configuration").click()
    expect(_editor(page)).to_be_visible(timeout=15000)
    return _editor(page)


def _edit(page, label: str):
    button = _section(page).get_by_role("button", name=f"Edit {label}", exact=True)
    # Buttons stay disabled while the table reloads after the last action.
    expect(button).to_be_enabled(timeout=15000)
    button.click()
    expect(_editor(page)).to_be_visible(timeout=15000)
    return _editor(page)


def _tab(editor, name: str):
    return editor.get_by_role("button", name=name, exact=True)


def _key_box(editor):
    return editor.get_by_label(re.compile(r"^API key"))


def _fetch_models(editor):
    editor.get_by_role("button", name=re.compile(r"^(Fetch|Refresh) models")).click()


def _row(page, label: str):
    return _section(page).get_by_role("row").filter(
        has=page.get_by_role("button", name=f"Edit {label}", exact=True)
    )


def _add_configuration(page, *, label: str, tab: str, model: str, key: str = "",
                       base_url: str | None = None) -> dict:
    editor = _open_editor(page)
    editor.get_by_label("Label").fill(label)
    _tab(editor, tab).click()
    if base_url is not None:
        editor.get_by_label("Base URL").fill(base_url)
    if key:
        _key_box(editor).fill(key)
    editor.get_by_label("Model").fill(model)
    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/llm/configs") and r.request.method == "POST",
        timeout=30000,
    ) as created:
        editor.get_by_role("button", name="Add configuration", exact=True).click()
    assert created.value.status == 201, created.value.text()
    expect(_editor(page)).to_be_hidden(timeout=15000)
    expect(_row(page, label)).to_be_visible(timeout=15000)
    return created.value.json()["config"]


def _listing(session) -> dict:
    return api_json(f"{session.backend}/api/agents/llm", session.token)


# ---------------------------------------------------------------------------
# #241 - there is always a model to pick
# ---------------------------------------------------------------------------


def test_anthropic_is_no_longer_declared_unlistable(api_settings):
    """The exact copy from the issue must be gone, and the reason must be real.

    A fresh account has no key and nothing recorded for Anthropic, so there is
    genuinely nothing to offer - and saying so is the point. The old panel
    claimed the *provider* published no list, which was untrue; the honest
    answer names the missing key, which the user can act on.
    """
    page = api_settings.page
    editor = _open_editor(page)
    _tab(editor, "Anthropic").click()

    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/provider-models")
        and r.request.method == "POST",
        timeout=30000,
    ) as listed:
        _fetch_models(editor)

    note = editor.get_by_role("status")
    expect(note).to_be_visible(timeout=15000)
    body = editor.inner_text()
    assert "does not publish a model list" not in body, (
        "the panel still makes the claim #241 was filed about"
    )
    assert re.search(r"API key", note.inner_text(), re.I), (
        f"the reason should name what is missing, got: {note.inner_text()!r}"
    )
    # Nothing was ever recorded for this endpoint, so the route says so rather
    # than inventing suggestions.
    assert listed.value.status == 400, (
        f"expected the honest cold-start 400, got {listed.value.status}"
    )
    # And configuring is still possible: the field never stops being free text.
    assert editor.get_by_label("Model").evaluate("el => el.tagName") == "INPUT"


def test_a_replay_is_labelled_as_one(api_settings):
    """A recording must never read as the present tense.

    Reaching the replay path for real needs a prior successful listing, which
    needs a live provider key, so the response is stubbed. What is under test is
    the panel's honesty about *which* source answered, which is exactly what a
    stub can establish.
    """
    page = api_settings.page

    def _stub(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "models": ["claude-sonnet-5", "claude-haiku-4-5"],
                "listable": False,
                "source": "remembered",
                "remembered": ["claude-sonnet-5", "claude-haiku-4-5"],
                "rememberedAt": "2026-09-01T12:00:00+00:00",
                "warning": "Add an API key above to ask this provider what it serves.",
            }),
        )

    page.route("**/api/agents/provider-models", _stub)
    editor = _open_editor(page)
    _tab(editor, "Anthropic").click()
    _fetch_models(editor)

    label = editor.get_by_text(re.compile(r"^Last reported by this endpoint"))
    expect(label).to_be_visible(timeout=15000)
    assert "2026" in label.inner_text(), (
        f"a replay must say when it was true: {label.inner_text()!r}"
    )
    # The reason the live call did not happen sits beside it, actionable.
    expect(editor.get_by_text(re.compile("Add an API key above", re.I))).to_be_visible()


def test_a_live_listing_is_offered_as_suggestions_not_a_replay(api_settings):
    page = api_settings.page

    def _stub(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "models": ["endpoint-model-a", "endpoint-model-b"],
                "listable": True,
                "source": "live",
                "remembered": [],
                "rememberedAt": None,
                "warning": None,
            }),
        )

    page.route("**/api/agents/provider-models", _stub)
    editor = _open_editor(page)
    model = editor.get_by_label("Model")
    # Fetch stays the trigger: until asked, the field offers nothing.
    assert model.get_attribute("list") is None
    _fetch_models(editor)

    expect(editor.get_by_text("From this endpoint: 2 models")).to_be_visible(timeout=15000)
    assert editor.get_by_text(re.compile("Last reported", re.I)).count() == 0
    # Suggestions, never a gate: still a text box, now with a list behind it.
    assert model.evaluate("el => el.tagName") == "INPUT"
    offered = model.evaluate(
        "el => Array.from(el.list ? el.list.options : []).map(o => o.value)"
    )
    assert offered == ["endpoint-model-a", "endpoint-model-b"], offered


# ---------------------------------------------------------------------------
# #242 - a saved key belongs to one endpoint
# ---------------------------------------------------------------------------


def test_a_configuration_is_saved_and_its_key_never_reaches_the_page(api_settings):
    page = api_settings.page
    config = _add_configuration(
        page, label="Work Gemini", tab="Gemini", key=KEY, model="gemini-2.0-flash",
    )
    assert config["apiType"] == "gemini" and config["hasApiKey"] is True, config
    assert "apiKey" not in config

    # The first configuration becomes the default, and the list says so.
    row = _row(page, "Work Gemini")
    expect(row).to_contain_text("Default", timeout=15000)
    expect(row).to_contain_text("saved")
    expect(row).to_contain_text("Language model")
    _show_tab(page, "Agent configuration")
    expect(page.get_by_test_id("llm-active")).to_contain_text("Work Gemini", timeout=15000)

    listing = _listing(api_settings)
    [saved] = [c for c in listing["configs"] if c["id"] == config["id"]]
    assert saved["hasApiKey"] and listing["default"] == config["id"], listing
    assert KEY not in json.dumps(listing)

    # Nowhere on the page: not in the markup, and not left in any input.
    assert KEY not in page.content()
    values = page.evaluate(
        "() => Array.from(document.querySelectorAll('input')).map(i => i.value)"
    )
    assert not any(KEY in value for value in values)


def test_the_editor_says_saved_only_on_the_configurations_own_endpoint(api_settings):
    page = api_settings.page
    _add_configuration(
        page, label="Work Gemini", tab="Gemini", key=KEY, model="gemini-2.0-flash",
    )
    editor = _edit(page, "Work Gemini")

    # It reopens on its own provider, which is where the key lives.
    expect(editor.get_by_text(SAVED)).to_be_visible()
    expect(_key_box(editor)).to_have_value("")

    for tab in ("OpenAI", "Anthropic", "Custom"):
        _tab(editor, tab).click()
        assert editor.get_by_text(SAVED).count() == 0, (
            f"{tab} claims a key it does not have"
        )
        expect(
            editor.get_by_text(re.compile("never follows a configuration to another endpoint"))
        ).to_be_visible()
        expect(_key_box(editor)).to_have_value("")


def test_moving_a_configuration_never_carries_its_key(api_settings):
    """The defect under the cosmetics.

    With one key per account, switching provider and saving kept the Gemini
    key under Anthropic's name, and the next run sent it to Anthropic. A
    configuration moved without a new key now drops the old one: a provider
    that needs a key refuses the save, and a keyless server saves without one.
    """
    page = api_settings.page
    config = _add_configuration(
        page, label="Work Gemini", tab="Gemini", key=KEY, model="gemini-2.0-flash",
    )
    editor = _edit(page, "Work Gemini")
    _tab(editor, "Anthropic").click()
    editor.get_by_label("Model").fill("claude-haiku-4-5")

    with page.expect_response(
        lambda r: f"/api/agents/llm/configs/{config['id']}" in r.url
        and r.request.method == "PATCH",
        timeout=30000,
    ) as answered:
        editor.get_by_role("button", name="Save configuration").click()

    sent = json.loads(answered.value.request.post_data or "{}")
    assert sent.get("apiType") == "anthropic", sent
    assert "apiKey" not in sent and sent.get("clearApiKey") is True, (
        f"a blank box on another endpoint must drop the stored key: {sent}"
    )
    assert answered.value.status == 400, answered.value.text()
    expect(editor.get_by_role("alert")).to_contain_text("API key")
    [kept] = [c for c in _listing(api_settings)["configs"] if c["id"] == config["id"]]
    assert kept["apiType"] == "gemini" and kept["hasApiKey"], kept

    # A keyless server takes the move, and the key stays behind.
    _tab(editor, "Custom").click()
    editor.get_by_label("Base URL").fill("http://localhost:11434/v1")
    editor.get_by_label("Model").fill("llama3")
    with page.expect_response(
        lambda r: f"/api/agents/llm/configs/{config['id']}" in r.url
        and r.request.method == "PATCH",
        timeout=30000,
    ) as moved:
        editor.get_by_role("button", name="Save configuration").click()
    assert moved.value.status == 200, moved.value.text()
    expect(_editor(page)).to_be_hidden(timeout=15000)
    expect(_row(page, "Work Gemini")).to_contain_text("none", timeout=15000)
    [now] = [c for c in _listing(api_settings)["configs"] if c["id"] == config["id"]]
    assert now["baseUrlHost"] == "localhost:11434" and now["hasApiKey"] is False, now


# ---------------------------------------------------------------------------
# The default answers the next run
# ---------------------------------------------------------------------------


def test_the_default_chosen_here_answers_the_next_run(signed_in):
    """Two scripted configurations; the one made default in the panel answers.

    The scripted provider records which configuration each call ran on, so the
    run itself says where it went, not only the listing.
    """
    session = signed_in
    made = {}
    for label, model in (("Scripted A", "scripted-a"), ("Scripted B", "scripted-b")):
        made[label] = api_json(
            f"{session.backend}/api/agents/llm/configs", session.token, method="POST",
            payload={"label": label, "apiType": "testing", "model": model},
        )["config"]
    api_json(
        f"{session.backend}/api/agents/llm/default", session.token, method="PUT",
        payload={"configId": made["Scripted A"]["id"]},
    )

    page = session.page
    _open_api_settings(page)
    _show_tab(page, "Agent configuration")
    default = page.get_by_label("Default for agents", exact=True)
    expect(default).to_have_value(made["Scripted A"]["id"], timeout=15000)
    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/llm/default") and r.request.method == "PUT",
        timeout=30000,
    ) as chosen:
        default.select_option(made["Scripted B"]["id"])
    assert chosen.value.ok, chosen.value.text()
    expect(page.get_by_test_id("llm-active")).to_contain_text("Scripted B", timeout=15000)
    _show_tab(page, "API keys")
    expect(_row(page, "Scripted B")).to_contain_text("Default", timeout=15000)

    project = api_json(
        f"{session.backend}/api/projects", session.token, method="POST",
        payload={"name": "Default answers",
                 "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                 "outputs": []},
    )["id"]
    coord = f"agent.chat-agent@{builtin.BUILTIN_VERSION}"
    base = f"{session.backend}/api/agents/projects/{project}"
    api_json(f"{base}/install", session.token, method="POST", payload={"coord": coord})
    attachment = api_json(
        f"{base}/attachments", session.token, method="POST",
        payload={"coord": coord, "target": {"kind": "canvas"}},
    )["attachmentId"]
    script_agent_replies(session.backend, "Answered by the default.")
    api_json(
        f"{base}/attachments/{attachment}/run", session.token, method="POST",
        payload={"message": "hello"}, timeout=60.0,
    )

    calls = captured_agent_calls(session.backend)
    assert calls, "the run never reached the scripted provider"
    assert calls[0] == {"configId": made["Scripted B"]["id"], "model": "scripted-b"}, calls


# ---------------------------------------------------------------------------
# Agent models: a configuration per agent
# ---------------------------------------------------------------------------


def _delegate_tail(capability: str, inputs: dict) -> str:
    return (
        "```curio.v1\n"
        + json.dumps({"delegateRequest": {"capability": capability, "inputs": inputs}})
        + "\n```"
    )


def test_each_agent_runs_on_the_configuration_chosen_for_it(signed_in):
    """The Dataflow Builder on one scripted configuration, Node Content Builder
    on another, both chosen in the panel. A Builder run that delegates the
    content shows each model in the scripted provider's call log, and the
    choices survive a reload with no key on the page."""
    session = signed_in
    made = {}
    for label, model, key in (
        ("Scripted A", "scripted-a", "sk-scripted-a-" + "0" * 16),
        ("Scripted B", "scripted-b", "sk-scripted-b-" + "0" * 16),
    ):
        made[label] = api_json(
            f"{session.backend}/api/agents/llm/configs", session.token, method="POST",
            payload={"label": label, "apiType": "testing", "model": model, "apiKey": key},
        )["config"]

    page = session.page
    _open_api_settings(page)
    _show_tab(page, "Agent configuration")
    models = page.get_by_test_id("agent-models-section")
    for agent, label in (("Dataflow Builder", "Scripted A"), ("Node Content Builder", "Scripted B")):
        with page.expect_response(
            lambda r: r.url.endswith("/api/agents/llm/assignments") and r.request.method == "PUT",
            timeout=30000,
        ) as chosen:
            models.get_by_label(agent, exact=True).select_option(made[label]["id"])
        assert chosen.value.ok, chosen.value.text()
        expect(models.get_by_label(agent, exact=True)).to_be_enabled(timeout=15000)

    # The tab is in the URL, so a reload lands back on it.
    page.wait_for_url(re.compile(r"/settings/agents$"), timeout=15000)
    page.reload()
    models = page.get_by_test_id("agent-models-section")
    expect(models.get_by_label("Dataflow Builder", exact=True)).to_have_value(made["Scripted A"]["id"])
    expect(models.get_by_label("Node Content Builder", exact=True)).to_have_value(made["Scripted B"]["id"])
    expect(models).to_contain_text("Runs on Scripted B · scripted-b")
    for key in ("sk-scripted-a-", "sk-scripted-b-"):
        assert key not in page.content()

    project = api_json(
        f"{session.backend}/api/projects", session.token, method="POST",
        payload={"name": "Two models",
                 "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}},
                 "outputs": []},
    )["id"]
    coord = f"agent.dataflow-builder@{builtin.BUILTIN_VERSION}"
    base = f"{session.backend}/api/agents/projects/{project}"
    api_json(f"{base}/install", session.token, method="POST", payload={"coord": coord})
    attachment = api_json(
        f"{base}/attachments", session.token, method="POST",
        payload={"coord": coord, "target": {"kind": "canvas"}},
    )["attachmentId"]
    script_agent_replies(
        session.backend,
        _delegate_tail("node.content.generate", {"intent": "sum a column"}),
        "result = df.sum(axis=0)",
        "The content is ready.",
    )
    reply = api_json(
        f"{base}/attachments/{attachment}/run", session.token, method="POST",
        payload={"message": "write the content"}, timeout=60.0,
    )

    calls = captured_agent_calls(session.backend)
    builder = {"configId": made["Scripted A"]["id"], "model": "scripted-a"}
    content = {"configId": made["Scripted B"]["id"], "model": "scripted-b"}
    assert [c for c in calls if c != builder] == [content], calls
    assert builder in calls
    turns = api_json(f"{base}/attachments/{attachment}/session", session.token)["turns"]
    part = next(
        p for t in turns for p in (t.get("content") or []) if p.get("type") == "delegation"
    )
    assert (part["model"], part["llmLabel"]) == ("scripted-b", "Scripted B")
    for key in ("sk-scripted-a-", "sk-scripted-b-"):
        assert key not in json.dumps(reply) and key not in json.dumps(turns)

