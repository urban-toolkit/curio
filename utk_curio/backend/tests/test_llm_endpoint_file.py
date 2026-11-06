"""The endpoint file ``--llm-endpoint-file`` names: one section per endpoint.

``utk_curio/common/llm_endpoint.py`` reads it for the launcher, which refuses
to start on a file it cannot use, and for the backend's ``config.py``. Every
refusal names the file and the section or line, never a URL or a key.

Fake names, hosts and keys only.
"""

from __future__ import annotations

import pytest

from utk_curio.common import llm_endpoint
from utk_curio.common.llm_endpoint import Endpoint, EndpointFileError

TWO_ENDPOINTS = """\
# This Curio's endpoints.
[Lab gateway]
base_url=https://llm.example.test/v1
api_key=fake-gateway-key-0001
models=model-a, model-b,model-c

; A second endpoint, on the provider's own URL.
[Hosted]
provider=anthropic
api_key=fake-hosted-key-0002
models=model-b
"""


def _read(tmp_path, text):
    path = tmp_path / "llm-endpoints"
    path.write_text(text, encoding="utf-8")
    return llm_endpoint.read_endpoint_file(path)


def _refusal(tmp_path, text) -> str:
    with pytest.raises(EndpointFileError) as refused:
        _read(tmp_path, text)
    return str(refused.value)


class TestWhatTheFileHolds:
    def test_each_section_is_an_endpoint_in_the_files_order(self, tmp_path):
        assert _read(tmp_path, TWO_ENDPOINTS) == (
            Endpoint(name="Lab gateway", api_type="openai_compatible", base_url="https://llm.example.test/v1",
                     api_key="fake-gateway-key-0001", models=("model-a", "model-b", "model-c")),
            Endpoint(name="Hosted", api_type="anthropic", base_url="", api_key="fake-hosted-key-0002",
                     models=("model-b",)),
        )

    def test_the_provider_is_openai_compatible_unless_the_section_names_one(self, tmp_path):
        for provider in llm_endpoint.PROVIDERS:
            (endpoint,) = _read(tmp_path, f"[E]\nprovider={provider}\napi_key=k\nmodels=m\n")
            assert endpoint.api_type == provider
        (endpoint,) = _read(tmp_path, "[E]\napi_key=k\nmodels=m\n")
        assert endpoint.api_type == "openai_compatible"

    def test_an_empty_or_absent_base_url_is_the_providers_own_endpoint(self, tmp_path):
        assert _read(tmp_path, "[E]\nbase_url=\napi_key=k\nmodels=m\n")[0].base_url == ""
        assert _read(tmp_path, "[E]\napi_key=k\nmodels=m\n")[0].base_url == ""
        assert _read(tmp_path, "[E]\nbase_url=http://localhost:11434/v1/\napi_key=ollama\nmodels=m\n")[0].base_url \
            == "http://localhost:11434/v1"

    def test_a_key_and_a_url_may_hold_percent_signs_and_equals_signs(self, tmp_path):
        (endpoint,) = _read(
            tmp_path, "[E]\nbase_url=https://llm.example.test/v1/%7Ebeta\napi_key=k%20ey=with=equals\nmodels=m\n",
        )
        assert (endpoint.base_url, endpoint.api_key) == ("https://llm.example.test/v1/%7Ebeta", "k%20ey=with=equals")

    def test_a_section_name_is_the_label_users_see(self, tmp_path):
        assert [e.name for e in _read(tmp_path, TWO_ENDPOINTS)] == ["Lab gateway", "Hosted"]

    def test_one_model_name_may_be_on_two_endpoints(self, tmp_path):
        first, second = _read(tmp_path, TWO_ENDPOINTS)
        assert "model-b" in first.models and "model-b" in second.models

    def test_the_url_and_key_stay_out_of_the_repr(self, tmp_path):
        text = repr(_read(tmp_path, TWO_ENDPOINTS))
        assert "llm.example.test" not in text and "fake-gateway-key" not in text and "fake-hosted-key" not in text


class TestWhatStopsTheStart:
    @pytest.mark.parametrize("text, fragment", [
        pytest.param("", "names no endpoint", id="no-section"),
        pytest.param("# only a comment\n", "names no endpoint", id="only-comments"),
        pytest.param("api_key=fake-orphan-key\n[E]\nmodels=m\n", "line 1 of the LLM endpoint file",
                     id="line-before-a-section"),
        pytest.param("[E]\nmodels=m\n", "[E] in the LLM endpoint file", id="no-api-key"),
        pytest.param("[E]\napi_key=\nmodels=m\n", "has no api_key", id="empty-api-key"),
        pytest.param("[E]\napi_key=fake-key-0003\n", "has no models", id="no-models"),
        pytest.param("[E]\napi_key=fake-key-0003\nmodels= , \n", "names no model", id="empty-models"),
        pytest.param("[E]\napi_key=fake-key-0003\nmodels=m,n,m\n", "names the model 'm' twice", id="repeated-model"),
        pytest.param("[E]\napi_key=fake-key-0003\nmodels=m\nmodel=m\n", "has 'model', which is not one of",
                     id="unknown-key"),
        pytest.param("[E]\nprovider=mistral\napi_key=fake-key-0003\nmodels=m\n",
                     "names the provider 'mistral', which is not one of", id="unknown-provider"),
        pytest.param("[E]\nbase_url=llm.example.test\napi_key=fake-key-0003\nmodels=m\n",
                     "is not an http(s) URL with a host", id="url-without-a-scheme"),
        pytest.param("[E]\napi_key=fake-key-0003\nmodels=m\n[E]\napi_key=fake-key-0004\nmodels=n\n",
                     "has the section [E] twice", id="repeated-section"),
        pytest.param("[E]\napi_key=fake-key-0003\napi_key=fake-key-0004\nmodels=m\n", "gives api_key twice",
                     id="repeated-key"),
        pytest.param("[ ]\napi_key=fake-key-0003\nmodels=m\n", "has no name", id="empty-section-name"),
        pytest.param("[E]\nfake-key-without-a-name\nmodels=m\n", "line 2 of the LLM endpoint file",
                     id="line-without-equals"),
        pytest.param("[DEFAULT]\napi_key=fake-key-0003\n[E]\nmodels=m\n", "which is not an endpoint",
                     id="default-section"),
    ])
    def test_a_file_it_cannot_use_says_why_without_a_value(self, tmp_path, text, fragment):
        message = _refusal(tmp_path, text)
        assert fragment in message, message
        assert str(tmp_path) in message
        for value in ("fake-orphan-key", "fake-key-0003", "fake-key-0004", "fake-key-without-a-name",
                      "llm.example.test"):
            assert value not in message, message

    def test_each_refusal_names_the_section(self, tmp_path):
        assert "[Second]" in _refusal(tmp_path, TWO_ENDPOINTS.replace("[Hosted]", "[Second]").replace(
            "provider=anthropic", "provider=nobody"))

    def test_a_missing_or_unreadable_file(self, tmp_path):
        with pytest.raises(EndpointFileError, match="does not exist"):
            llm_endpoint.read_endpoint_file(tmp_path / "no-such-file")
        # A directory cannot be read as a file, even by root, which CI runs as.
        with pytest.raises(EndpointFileError, match="cannot be read"):
            llm_endpoint.read_endpoint_file(tmp_path)


class TestOfferedModels:
    def test_a_refusal_names_every_endpoint_and_its_models(self, tmp_path):
        assert llm_endpoint.offered_models(_read(tmp_path, TWO_ENDPOINTS)) == (
            "Lab gateway: model-a, model-b, model-c; Hosted: model-b"
        )
        assert llm_endpoint.offered_models(()) == "none"
