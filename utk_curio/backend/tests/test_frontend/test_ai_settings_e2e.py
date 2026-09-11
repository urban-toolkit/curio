"""Playwright E2E: AI Settings offers a model list, and scopes the saved key.

Covers two issues that live in the same panel:

- **#241** - the Model field said "This provider does not publish a model list"
  for Anthropic and Gemini. Nobody had asked them. It now asks, and when it
  cannot it replays what that endpoint last reported, labelled as a replay.
- **#242** - the account holds one API key, but the panel showed "saved" on
  every provider tab, and saving from a different tab quietly kept the previous
  provider's key under the new provider's name.

Nothing here reaches a provider. The #241 cases use the no-key short circuit
(the backend refuses without opening a socket) and stubbed responses for the
shapes that would otherwise need a live key; the #242 cases only exercise
``PATCH /api/auth/me``.

Run::

    CURIO_TESTING=1 pytest \
        utk_curio/backend/tests/test_frontend/test_ai_settings_e2e.py -v
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import expect

from .utils import (
    require_project_page,
    require_user_auth,
    stub_db_login,
    wait_for_projects_page,
)

if TYPE_CHECKING:
    from .utils import FrontendPage

API_KEY = "#ai-settings-api-key"
MODEL = "#ai-settings-model"


@pytest.fixture()
def ai_settings(app_frontend: "FrontendPage", current_server: str, page, request):
    """Sign in and open AI Settings from the projects page header.

    The header button is the entry point that exists on /projects; on the canvas
    the only route is the Agent Catalog drawer's cog, which is more machinery
    than these assertions need.
    """
    require_project_page()
    require_user_auth()
    page.emulate_media(reduced_motion="reduce")
    stub_db_login(
        page,
        frontend_url=app_frontend.base_url,
        backend_url=current_server,
        name="AI Settings User",
        username=f"aisettings_{abs(hash(request.node.name)) % 10**8}",
        project_name="AiSettings",
    )
    page.goto(f"{app_frontend.base_url}/projects")
    page.wait_for_load_state("domcontentloaded")
    wait_for_projects_page(page, timeout=15000)

    page.get_by_role("button", name="AI Settings", exact=True).first.click()
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_be_visible(timeout=15000)
    return page


def _tab(page, name: str):
    return page.get_by_role("button", name=name, exact=True)


def _fetch_models(page):
    page.get_by_role("button", name=re.compile(r"^(Fetch|Refresh) models")).click()


def _wait_for_model_menu(page, timeout: float = 20000):
    """Wait until the Model control is actually the menu, not still the box.

    Both render under the same ``#ai-settings-model`` id, so ``to_be_visible``
    is satisfied by the free-text input that is already on screen and tells you
    nothing about whether the fetch has landed. Reading the option groups
    without this gate is a race the test loses on a slow machine.
    """
    page.wait_for_function(
        "() => document.querySelector('#ai-settings-model')?.tagName === 'SELECT'",
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# #241 - there is always a model to pick
# ---------------------------------------------------------------------------


def test_anthropic_is_no_longer_declared_unlistable(ai_settings):
    """The exact copy from the issue must be gone, and the reason must be real.

    A fresh account has no key and nothing recorded for Anthropic, so there is
    genuinely nothing to offer - and saying so is the point. The old panel
    claimed the *provider* published no list, which was untrue; the honest
    answer names the missing key, which the user can act on.
    """
    page = ai_settings
    _tab(page, "Anthropic").click()

    with page.expect_response(
        lambda r: r.url.endswith("/api/agents/provider-models")
        and r.request.method == "POST",
        timeout=30000,
    ) as listed:
        _fetch_models(page)

    body = page.locator('[role="dialog"]').inner_text()
    assert "does not publish a model list" not in body, (
        "the panel still makes the claim #241 was filed about"
    )
    assert re.search(r"API key", body, re.I), (
        f"the reason should name what is missing, got: {body[-400:]!r}"
    )
    # Nothing was ever recorded for this endpoint, so the route says so rather
    # than inventing suggestions.
    assert listed.value.status == 400, (
        f"expected the honest cold-start 400, got {listed.value.status}"
    )
    # And configuring is still possible: the field never stops being free text.
    assert page.locator(MODEL).evaluate("el => el.tagName") == "INPUT"


def test_a_replay_is_labelled_as_one(ai_settings, page):
    """A recording must never read as the present tense.

    Reaching the replay path for real needs a prior successful listing, which
    needs a live provider key, so the response is stubbed. What is under test is
    the panel's honesty about *which* source answered, which is exactly what a
    stub can establish.
    """
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
    _tab(ai_settings, "Anthropic").click()
    _fetch_models(ai_settings)

    _wait_for_model_menu(ai_settings)
    label = ai_settings.locator(f"{MODEL} optgroup").first.get_attribute("label")
    assert label and "Last reported" in label, f"unlabelled replay: {label!r}"
    assert "2026" in label, f"a replay must say when it was true: {label!r}"

    # The reason the live call did not happen sits beside it, actionable.
    expect(
        ai_settings.get_by_text(re.compile("Add an API key above", re.I))
    ).to_be_visible()


def test_a_live_listing_is_not_labelled_as_a_replay(ai_settings, page):
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
    _fetch_models(ai_settings)

    _wait_for_model_menu(ai_settings)
    label = ai_settings.locator(f"{MODEL} optgroup").first.get_attribute("label")
    assert label == "From this endpoint", f"live list mislabelled: {label!r}"
    assert ai_settings.get_by_text(re.compile("Last reported", re.I)).count() == 0


def test_the_model_field_is_free_text_until_asked(ai_settings):
    """Fetch stays the trigger: suggestions are a convenience, not a gate."""
    model = ai_settings.locator(MODEL)
    assert model.evaluate("el => el.tagName") == "INPUT"
    _tab(ai_settings, "Anthropic").click()
    assert ai_settings.locator(MODEL).evaluate("el => el.tagName") == "INPUT"


# ---------------------------------------------------------------------------
# #242 - the saved key belongs to one provider
# ---------------------------------------------------------------------------


def _save_key_on(page, tab: str, key: str):
    _tab(page, tab).click()
    page.locator(API_KEY).fill(key)
    with page.expect_response(
        lambda r: "/api/auth/me" in r.url and r.request.method == "PATCH",
        timeout=30000,
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, f"saving failed: HTTP {saved.value.status}"


def _reopen(page):
    # handleSave closes the panel on a 2s timer.
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_be_hidden(timeout=15000)
    page.get_by_role("button", name="AI Settings", exact=True).first.click()
    expect(
        page.get_by_role("heading", name="AI Settings", level=2)
    ).to_be_visible(timeout=15000)


def test_a_saved_key_shows_only_on_its_own_provider(ai_settings):
    page = ai_settings
    _save_key_on(page, "Gemini", "AIza-e2e-test-key")
    _reopen(page)

    # The panel reopens on the saved provider, which is where the key lives.
    expect(page.get_by_text(re.compile(r"saved - leave blank to keep", re.I))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Remove saved key"))).to_be_visible()

    for tab in ("OpenAI", "Anthropic", "Custom"):
        _tab(page, tab).click()
        assert page.get_by_text(
            re.compile(r"saved - leave blank to keep", re.I)
        ).count() == 0, f"{tab} claims a key it does not have"
        assert page.get_by_role(
            "button", name=re.compile("Remove saved key")
        ).count() == 0, f"{tab} offers to remove a key it does not have"
        assert page.locator(API_KEY).input_value() == ""


def test_it_explains_that_there_is_only_one_key(ai_settings):
    page = ai_settings
    _save_key_on(page, "Gemini", "AIza-e2e-test-key")
    _reopen(page)
    _tab(page, "Anthropic").click()

    expect(page.get_by_text(re.compile("one provider key per account", re.I))).to_be_visible()
    expect(page.get_by_text(re.compile("belongs to Gemini", re.I))).to_be_visible()


def test_switching_provider_and_saving_blank_clears_the_stale_key(ai_settings):
    """The defect under the cosmetics.

    ``patch_me`` leaves ``llm_api_key`` alone when the field is absent but still
    writes the new ``llm_api_type``, so the Gemini key used to survive as an
    Anthropic key and get sent to Anthropic.
    """
    page = ai_settings
    _save_key_on(page, "Gemini", "AIza-e2e-test-key")
    _reopen(page)
    _tab(page, "Anthropic").click()

    with page.expect_request(
        lambda r: "/api/auth/me" in r.url and r.method == "PATCH",
        timeout=30000,
    ) as sent:
        page.get_by_role("button", name="Save", exact=True).click()

    body = json.loads(sent.value.post_data or "{}")
    assert body.get("llm_api_type") == "anthropic", body
    assert body.get("llm_api_key") == "", (
        "a blank box on a different provider has to clear the stored key, "
        f"not leave it to be relabelled: {body}"
    )
