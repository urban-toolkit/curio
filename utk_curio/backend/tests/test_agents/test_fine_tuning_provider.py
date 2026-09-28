"""dev/122 — the provider fine-tuning contract, and what it refuses.

Every test here is offline. The point of the contract is that "can this
endpoint fine-tune" is ASKED rather than looked up in a table, so most of these
tests are about the four different answers a refusal can be — "no such
feature", "your key lacks the scope", "the host is unreachable", "there is no
key yet" — because each one has a different fix and a boolean would erase all
four.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import model_catalog, providers, testing_provider

REPO_ROOT = Path(__file__).resolve().parents[4]


def _config(api_type="openai_compatible", *, key="sk-test", base_url="", model="m"):
    return providers.ProviderConfig(
        api_key=key, api_type=api_type, base_url=base_url, model=model
    )


class _FakeJob:
    def __init__(self, **fields):
        for name, value in fields.items():
            setattr(self, name, value)


class _FakeJobs:
    def __init__(self, *, on_list=None, on_create=None, on_retrieve=None, on_cancel=None):
        self._on_list = on_list
        self._on_create = on_create
        self._on_retrieve = on_retrieve
        self._on_cancel = on_cancel
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        if callable(self._on_list):
            return self._on_list(**kwargs)
        return self._on_list

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return self._on_create(**kwargs) if callable(self._on_create) else self._on_create

    def retrieve(self, job_id):
        self.calls.append(("retrieve", job_id))
        return self._on_retrieve(job_id) if callable(self._on_retrieve) else self._on_retrieve

    def cancel(self, job_id):
        self.calls.append(("cancel", job_id))
        return self._on_cancel(job_id) if callable(self._on_cancel) else self._on_cancel


class _FakeFiles:
    def __init__(self, *, on_create=None):
        self._on_create = on_create
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._on_create(**kwargs) if callable(self._on_create) else self._on_create


class _FakeClient:
    def __init__(self, *, jobs=None, files=None, models=None):
        self.fine_tuning = type("FT", (), {"jobs": jobs or _FakeJobs()})()
        self.files = files or _FakeFiles()
        self._models = models

    @property
    def models(self):
        listing = self._models

        class _Models:
            @staticmethod
            def list():
                if isinstance(listing, Exception):
                    raise listing
                return type("Listing", (), {"data": listing or []})()

        return _Models()


class _HttpError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(providers, "_openai_client", lambda config, **kw: client)
    return client


class TestCapabilityIsProbedNotTabulated:
    def test_an_endpoint_that_answers_is_supported(self, monkeypatch):
        client = _patch_client(
            monkeypatch, _FakeClient(jobs=_FakeJobs(on_list=lambda **kw: []))
        )
        capability = providers.fine_tuning_capabilities(_config())
        assert capability.supported is True
        assert capability.surface == "openai_compatible_v1"
        assert capability.probed_at
        assert client.fine_tuning.jobs.calls[0] == ("list", {"limit": 1})

    @pytest.mark.parametrize("status", [404, 405, 501])
    def test_a_chat_only_endpoint_says_so_with_its_status(self, monkeypatch, status):
        """Ollama, LM Studio and vLLM answer chat and nothing else. Being
        OpenAI-compatible for chat says nothing about tuning."""
        def _raise(**kwargs):
            raise _HttpError(status)

        _patch_client(monkeypatch, _FakeClient(jobs=_FakeJobs(on_list=_raise)))
        capability = providers.fine_tuning_capabilities(_config())
        assert capability.supported is False
        assert str(status) in capability.reason
        assert "not fine-tuning" in capability.reason

    @pytest.mark.parametrize("status", [401, 403])
    def test_a_key_without_the_scope_is_a_scope_answer_not_a_capability_answer(
        self, monkeypatch, status
    ):
        """The fix is a different key, not a different endpoint, so the message
        must not say the feature is missing."""
        def _raise(**kwargs):
            raise _HttpError(status)

        _patch_client(monkeypatch, _FakeClient(jobs=_FakeJobs(on_list=_raise)))
        capability = providers.fine_tuning_capabilities(_config())
        assert capability.supported is False
        assert "cannot list fine-tuning jobs" in capability.reason
        assert "may still support tuning" in capability.reason

    def test_an_unreachable_host_is_a_third_answer(self, monkeypatch):
        def _raise(**kwargs):
            raise ConnectionError("no route to host")

        _patch_client(monkeypatch, _FakeClient(jobs=_FakeJobs(on_list=_raise)))
        capability = providers.fine_tuning_capabilities(_config())
        assert capability.supported is False
        assert "Could not ask this endpoint" in capability.reason
        assert "no route to host" in capability.reason

    def test_no_key_is_answered_before_any_socket_is_opened(self, monkeypatch):
        def _boom(config, **kwargs):
            raise AssertionError("the probe must not build a client with no key")

        monkeypatch.setattr(providers, "_openai_client", _boom)
        capability = providers.fine_tuning_capabilities(_config(key=""))
        assert capability.supported is False
        assert "Add an API key" in capability.reason

    def test_anthropic_is_refused_with_the_checked_fact(self):
        """Anthropic's API publishes Messages, Batches, Token Counting, Models,
        Files and Skills plus the beta agent APIs, and no tuning endpoint. The
        reason names that rather than guessing."""
        capability = providers.fine_tuning_capabilities(_config("anthropic"))
        assert capability.supported is False
        assert "no fine-tuning endpoint" in capability.reason
        assert "Messages" in capability.reason

    def test_gemini_names_the_contract_curio_has_not_implemented(self):
        capability = providers.fine_tuning_capabilities(_config("gemini"))
        assert capability.supported is False
        assert "tunedModels" in capability.reason

    def test_the_probe_never_raises(self, monkeypatch):
        def _raise(**kwargs):
            raise RuntimeError("something nobody anticipated")

        _patch_client(monkeypatch, _FakeClient(jobs=_FakeJobs(on_list=_raise)))
        assert providers.fine_tuning_capabilities(_config()).supported is False

    def test_base_models_are_only_ever_what_the_endpoint_advertised(self, monkeypatch):
        """A hand-written list of "probably tunable" ids is the drift #241 was
        filed about, so an endpoint that advertises nothing yields nothing."""
        silent = [_FakeJob(id="gpt-x"), _FakeJob(id="gpt-y")]
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_list=lambda **kw: []), models=silent),
        )
        assert providers.fine_tuning_capabilities(_config()).base_models == ()

        advertised = [
            _FakeJob(id="gpt-tunable", allow_fine_tuning=True),
            _FakeJob(id="gpt-plain", allow_fine_tuning=False),
            _FakeJob(id="gpt-cap", capabilities={"fine_tuning": True}),
        ]
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_list=lambda **kw: []), models=advertised),
        )
        assert providers.fine_tuning_capabilities(_config()).base_models == (
            "gpt-cap", "gpt-tunable",
        )

    def test_a_failed_model_listing_costs_the_hint_not_the_capability(self, monkeypatch):
        _patch_client(
            monkeypatch,
            _FakeClient(
                jobs=_FakeJobs(on_list=lambda **kw: []),
                models=RuntimeError("no models route"),
            ),
        )
        capability = providers.fine_tuning_capabilities(_config())
        assert capability.supported is True
        assert capability.base_models == ()

    def test_no_provider_capability_table_exists_in_the_agents_package(self):
        """The rule, enforced: capability comes from the endpoint. A dict or
        set literal mapping provider names to tuning support would be the
        drift this design exists to avoid."""
        import re

        pattern = re.compile(
            r"(SUPPORTS_FINE_TUNING|FINE_TUNING_PROVIDERS|TUNABLE_PROVIDERS)"
        )
        offenders = [
            path.name
            for path in (REPO_ROOT / "utk_curio/backend/app/agents").rglob("*.py")
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        assert not offenders, offenders


class TestJobPrimitives:
    def test_creating_a_job_sends_the_documented_shape(self, monkeypatch):
        created = _FakeJob(id="ftjob-1", status="validating_files", model="base-1")
        client = _patch_client(
            monkeypatch, _FakeClient(jobs=_FakeJobs(on_create=lambda **kw: created))
        )
        job = providers.create_fine_tuning_job(
            _config(), training_file="file-1", base_model="base-1", suffix="curio-plans",
        )
        assert client.fine_tuning.jobs.calls[0][1] == {
            "training_file": "file-1", "model": "base-1", "suffix": "curio-plans",
        }
        assert job.id == "ftjob-1"
        assert job.status == "queued"
        assert job.raw_status == "validating_files"
        assert job.terminal is False

    def test_a_suffix_is_omitted_when_absent_rather_than_sent_empty(self, monkeypatch):
        client = _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_create=lambda **kw: _FakeJob(id="j", status="queued"))),
        )
        providers.create_fine_tuning_job(
            _config(), training_file="f", base_model="b", suffix=None
        )
        assert "suffix" not in client.fine_tuning.jobs.calls[0][1]

    @pytest.mark.parametrize(
        "raw,expected",
        [("validating_files", "queued"), ("queued", "queued"), ("running", "running"),
         ("succeeded", "succeeded"), ("failed", "failed"), ("cancelled", "cancelled"),
         ("canceled", "cancelled")],
    )
    def test_statuses_are_normalized_and_the_endpoints_word_is_kept(
        self, monkeypatch, raw, expected
    ):
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_retrieve=lambda job_id: _FakeJob(id=job_id, status=raw))),
        )
        job = providers.get_fine_tuning_job(_config(), "ftjob-1")
        assert job.status == expected
        assert job.raw_status == raw

    def test_an_unknown_status_stays_running_rather_than_becoming_terminal(
        self, monkeypatch
    ):
        """Acting on a status we do not understand is worse than waiting: a
        job wrongly called terminal would let a trained model be looked for
        that does not exist."""
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(
                on_retrieve=lambda job_id: _FakeJob(id=job_id, status="paused_for_review")
            )),
        )
        job = providers.get_fine_tuning_job(_config(), "ftjob-1")
        assert job.status == "running"
        assert job.raw_status == "paused_for_review"
        assert job.terminal is False

    def test_a_succeeded_job_reports_its_model_and_trained_tokens(self, monkeypatch):
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_retrieve=lambda job_id: _FakeJob(
                id=job_id, status="succeeded", model="base-1",
                fine_tuned_model="ft:base-1:curio-plans:abc", trained_tokens=12345,
            ))),
        )
        job = providers.get_fine_tuning_job(_config(), "ftjob-1")
        assert job.trained_model == "ft:base-1:curio-plans:abc"
        assert job.trained_tokens == 12345
        assert job.terminal is True

    def test_a_failed_job_carries_the_endpoints_message(self, monkeypatch):
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(on_retrieve=lambda job_id: _FakeJob(
                id=job_id, status="failed",
                error=type("E", (), {"message": "training file was invalid"})(),
            ))),
        )
        job = providers.get_fine_tuning_job(_config(), "ftjob-1")
        assert job.status == "failed"
        assert job.error == "training file was invalid"

    def test_uploading_returns_the_endpoints_file_id(self, monkeypatch):
        client = _patch_client(
            monkeypatch,
            _FakeClient(files=_FakeFiles(on_create=lambda **kw: _FakeJob(id="file-9"))),
        )
        file_id = providers.upload_training_file(
            _config(), filename="train.jsonl", content=b'{"messages": []}\n'
        )
        assert file_id == "file-9"
        call = client.files.calls[0]
        assert call["purpose"] == "fine-tune"
        assert call["file"] == ("train.jsonl", b'{"messages": []}\n')

    def test_an_upload_with_no_file_id_is_a_refusal_not_a_silent_success(
        self, monkeypatch
    ):
        _patch_client(
            monkeypatch, _FakeClient(files=_FakeFiles(on_create=lambda **kw: _FakeJob()))
        )
        with pytest.raises(providers.FineTuningUnavailable) as refusal:
            providers.upload_training_file(_config(), filename="t.jsonl", content=b"{}")
        assert "no file id" in str(refusal.value)

    def test_cancelling_reports_what_the_endpoint_says_afterwards(self, monkeypatch):
        _patch_client(
            monkeypatch,
            _FakeClient(jobs=_FakeJobs(
                on_cancel=lambda job_id: _FakeJob(id=job_id, status="cancelled")
            )),
        )
        assert providers.cancel_fine_tuning_job(_config(), "ftjob-1").status == "cancelled"

    def test_a_refused_cancel_is_reported_never_forced_locally(self, monkeypatch):
        def _raise(job_id):
            raise _HttpError(409)

        _patch_client(monkeypatch, _FakeClient(jobs=_FakeJobs(on_cancel=_raise)))
        with pytest.raises(providers.FineTuningUnavailable) as refusal:
            providers.cancel_fine_tuning_job(_config(), "ftjob-1")
        assert "Could not cancel" in str(refusal.value)

    @pytest.mark.parametrize("api_type", ["anthropic", "gemini"])
    def test_a_provider_with_no_tuning_surface_refuses_every_primitive(
        self, monkeypatch, api_type
    ):
        def _boom(config, **kwargs):
            raise AssertionError("no client may be built for a provider without the surface")

        monkeypatch.setattr(providers, "_openai_client", _boom)
        config = _config(api_type)
        for call in (
            lambda: providers.upload_training_file(config, filename="t", content=b"{}"),
            lambda: providers.create_fine_tuning_job(
                config, training_file="f", base_model="b"
            ),
            lambda: providers.get_fine_tuning_job(config, "j"),
            lambda: providers.cancel_fine_tuning_job(config, "j"),
        ):
            with pytest.raises(providers.FineTuningUnavailable):
                call()


class TestTheScriptedLane:
    """The whole lane has an in-process answer, so no test of it costs money."""

    def setup_method(self):
        testing_provider.reset_fine_tuning()

    def teardown_method(self):
        testing_provider.reset_fine_tuning()

    def test_a_scripted_endpoint_walks_a_job_to_a_trained_model(self):
        config = _config("testing")
        testing_provider.script_fine_tuning(
            statuses=["queued", "running", "succeeded"]
        )
        assert providers.fine_tuning_capabilities(config).supported is True
        file_id = providers.upload_training_file(
            config, filename="train.jsonl", content=b'{"messages": []}\n'
        )
        job = providers.create_fine_tuning_job(
            config, training_file=file_id, base_model="scripted-base", suffix="curio-plans"
        )
        assert [
            providers.get_fine_tuning_job(config, job.id).status for _ in range(3)
        ] == ["queued", "running", "succeeded"]
        final = providers.get_fine_tuning_job(config, job.id)
        assert final.trained_model == "ft:scripted-base:curio-plans"
        assert final.trained_tokens == 4321

    def test_what_would_have_been_uploaded_is_inspectable(self):
        config = _config("testing")
        providers.upload_training_file(
            config, filename="train.jsonl", content=b'{"messages": [1]}\n'
        )
        assert testing_provider.uploaded_training_files() == [
            ("train.jsonl", b'{"messages": [1]}\n')
        ]

    def test_a_scripted_unsupported_endpoint_is_the_unavailable_case(self):
        testing_provider.script_fine_tuning(supported=False)
        capability = providers.fine_tuning_capabilities(_config("testing"))
        assert capability.supported is False
        assert "does not offer fine-tuning" in capability.reason

    def test_cancelling_a_finished_scripted_job_is_refused(self):
        config = _config("testing")
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        job = providers.create_fine_tuning_job(
            config, training_file="f", base_model="b"
        )
        providers.get_fine_tuning_job(config, job.id)
        with pytest.raises(providers.FineTuningUnavailable) as refusal:
            providers.cancel_fine_tuning_job(config, job.id)
        assert "already" in str(refusal.value)

    def test_reading_an_unknown_scripted_job_refuses(self):
        with pytest.raises(providers.FineTuningUnavailable):
            providers.get_fine_tuning_job(_config("testing"), "ftjob-nope")

    def test_reset_clears_the_training_state_too(self):
        config = _config("testing")
        providers.upload_training_file(config, filename="t", content=b"{}")
        testing_provider.reset()
        assert testing_provider.uploaded_training_files() == []


class TestRecording:
    """A capability is a recording, like a model listing — and a trained model
    is a different kind of fact, kept in its own file."""

    def test_a_capability_replays_with_the_date_it_was_true(self, tmp_curio):
        model_catalog.remember_capability(
            "1", "openai_compatible", "http://x/v1",
            {"supported": True, "reason": "answers", "baseModels": ["b"],
             "surface": "openai_compatible_v1"},
        )
        capability, seen_at = model_catalog.remembered_capability(
            "1", "openai_compatible", "http://x/v1"
        )
        assert capability["supported"] is True
        assert capability["baseModels"] == ["b"]
        assert seen_at

    def test_a_capability_is_keyed_by_endpoint_not_by_provider_name(self, tmp_curio):
        model_catalog.remember_capability(
            "1", "openai_compatible", "http://a/v1", {"supported": True, "reason": "a"}
        )
        other, _ = model_catalog.remembered_capability(
            "1", "openai_compatible", "http://b/v1"
        )
        assert other is None

    def test_nothing_remembered_is_an_honest_nothing(self, tmp_curio):
        assert model_catalog.remembered_capability("1", "openai_compatible") == (None, None)

    def test_a_trained_model_records_its_provenance_and_date(self, tmp_curio):
        model_catalog.remember_trained_model(
            "1", "openai_compatible", "http://x/v1",
            model="ft:base:curio-plans:abc", job_id="train-1",
            dataset_sha256="d" * 64, base_model="base",
        )
        rows = model_catalog.trained_models("1", "openai_compatible", "http://x/v1")
        assert len(rows) == 1
        assert rows[0]["origin"] == "trained-in-curio"
        assert rows[0]["jobId"] == "train-1"
        assert rows[0]["datasetSha256"] == "d" * 64
        assert rows[0]["trainedAt"]

    def test_recording_the_same_model_twice_replaces_rather_than_duplicates(
        self, tmp_curio
    ):
        for _ in range(3):
            model_catalog.remember_trained_model(
                "1", "openai_compatible", "", model="ft:a", job_id="t", dataset_sha256="x"
            )
        assert len(model_catalog.trained_models("1", "openai_compatible")) == 1

    def test_trained_models_live_beside_the_suggestions_never_inside_them(
        self, tmp_curio
    ):
        """The suggestions file promises to be "only ever a recording of what
        an endpoint said about itself". A model Curio caused to exist is a
        different claim and would blur that."""
        model_catalog.remember_models("1", "openai_compatible", "", ["a", "b"])
        model_catalog.remember_trained_model(
            "1", "openai_compatible", "", model="ft:a", job_id="t", dataset_sha256="x"
        )
        suggestions = json.loads(
            model_catalog._path("1").read_text(encoding="utf-8")
        )
        assert "ft:a" not in json.dumps(suggestions)
        assert model_catalog.trained_models("1", "openai_compatible")[0]["model"] == "ft:a"

    def test_a_corrupt_sidecar_is_an_empty_one(self, tmp_curio):
        path = model_catalog._sidecar_path("1", model_catalog._TRAINED_FILENAME)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert model_catalog.trained_models("1", "openai_compatible") == []
