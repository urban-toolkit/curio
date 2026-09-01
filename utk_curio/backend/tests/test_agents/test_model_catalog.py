"""The curated half of model discovery (#241).

These entries only ever appear when the endpoint could not be asked or could not
answer, so the bar is low and specific: they must be non-empty where a fallback
is promised, usable verbatim as a model id, and absent where guessing would be
wrong.

Deliberately *not* asserted: the exact ids. Pinning them would turn every
routine refresh of the list into a test edit, and the list is a suggestion
rather than a contract - a live listing supersedes it, and nothing anywhere
rejects a model that is missing from it.
"""

from utk_curio.backend.app.agents.model_catalog import CURATED_MODELS, curated_for


class TestCuratedModels:
    def test_every_listed_provider_has_a_usable_list(self):
        for provider, models in CURATED_MODELS.items():
            assert models, f"{provider} has an empty curated list"
            assert len(set(models)) == len(models), f"{provider} repeats an id"
            for model in models:
                assert model, f"{provider} has a blank id"
                assert model.strip() == model, f"{provider}: {model!r} has stray space"

    def test_ids_are_bare_and_ready_to_send(self):
        # Gemini's listing returns "models/gemini-2.0-flash" and the route
        # strips that prefix, so a curated entry carrying one would be the odd
        # value out in the same dropdown.
        for provider, models in CURATED_MODELS.items():
            for model in models:
                assert not model.startswith("models/"), f"{provider}: {model}"
                assert "/" not in model, f"{provider}: {model} looks path-like"


class TestCuratedFor:
    def test_the_three_named_providers_answer(self):
        assert curated_for("anthropic")
        assert curated_for("gemini")
        assert curated_for("openai_compatible")

    def test_openai_and_openai_compatible_are_the_same_list(self):
        # The UI splits them (an "OpenAI" tab and a "Custom" tab); the backend
        # only ever sees openai_compatible.
        assert curated_for("openai") == curated_for("openai_compatible")

    def test_a_custom_endpoint_gets_nothing(self):
        # A base URL means "some other OpenAI-compatible server", and there is
        # no such thing as a model it probably serves. Suggesting gpt-4o to
        # someone pointing at Ollama would be worse than suggesting nothing.
        assert curated_for("openai_compatible", "http://localhost:11434/v1") == []
        assert curated_for("openai", "https://llm.example.test/") == []

    def test_a_blank_base_url_is_still_plain_openai(self):
        # The panel sends "" for every non-custom tab.
        assert curated_for("openai_compatible", "") == curated_for("openai_compatible")
        assert curated_for("openai_compatible", "   ") == curated_for("openai_compatible")

    def test_an_unknown_provider_gets_nothing_rather_than_a_guess(self):
        assert curated_for("some-future-provider") == []

    def test_a_blank_api_type_falls_back_to_openai(self):
        # The route defaults an unset apiType to openai_compatible, so this
        # keeps the two in step.
        assert curated_for("") == curated_for("openai_compatible")

    def test_the_caller_cannot_mutate_the_table(self):
        # It is returned as a list for JSON's sake; the source stays a tuple.
        first = curated_for("anthropic")
        first.append("not-a-real-model")
        assert "not-a-real-model" not in curated_for("anthropic")
