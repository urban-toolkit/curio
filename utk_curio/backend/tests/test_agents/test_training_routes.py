"""dev/122 — the training lane through its real routes.

In-process Flask client, the scripted provider, and the fixtures on disk. What
is exercised is the ordering and the refusals: capability, preview, consent,
start, status, cancel — plus the properties that matter more than any of them,
namely that the consent record is on disk before anything is uploaded and that
no API key appears anywhere in any response.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import providers, testing_provider
from utk_curio.backend.app.agents.evaluation.fixtures import fixture_paths
from utk_curio.backend.app.agents.training import records as records_mod
from utk_curio.backend.app.agents.training import service as training_service

REPO_ROOT = Path(__file__).resolve().parents[4]
API_KEY = "sk-training-lane-secret-0001"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _user_key(user):
    from utk_curio.backend.app.projects.services import _user_dir_key

    return _user_dir_key(user)


@pytest.fixture()
def account(client, user_and_token, tmp_curio):
    """An account whose provider is the scripted one, with a key saved."""
    user, token = user_and_token
    response = client.patch(
        "/api/auth/me",
        json={
            "llm_api_type": "testing",
            "llm_model": "scripted",
            "llm_api_key": API_KEY,
            "llm_base_url": "http://scripted.example.com/v1",
        },
        headers=_auth(token),
    )
    assert response.status_code == 200, response.get_json()
    testing_provider.reset_fine_tuning()
    yield {"user": user, "token": token, "key": _user_key(user)}
    testing_provider.reset_fine_tuning()


@pytest.fixture()
def approved_corpus(monkeypatch):
    """The shipped fixtures, with their reviews approved in memory only.

    The files on disk stay `pending-owner-review` — approving them is the
    owner's act, not a test's — so the suite patches the loader instead.
    """
    from utk_curio.backend.app.agents.evaluation import fixtures as fixtures_mod

    def _approved():
        out = []
        for path in fixture_paths():
            fixture = fixtures_mod.load_fixture(path)
            data = json.loads(json.dumps(fixture.data))
            data["review"] = {
                "status": "approved", "draftedBy": data["review"].get("draftedBy"),
                "reviewedBy": "the owner", "reviewedAt": "2026-09-09T00:00:00Z",
            }
            out.append(fixtures_mod.Fixture(path=path, data=data))
        return out

    monkeypatch.setattr(
        "utk_curio.backend.app.agents.training.service.load_fixtures",
        lambda *a, **kw: _approved(),
    )
    return _approved()


class TestCapability:
    def test_a_scripted_endpoint_reports_supported_and_records_it(
        self, client, account
    ):
        testing_provider.script_fine_tuning(base_models=("scripted-base",))
        response = client.get(
            "/api/agents/training/capability", headers=_auth(account["token"])
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["supported"] is True
        assert payload["source"] == "live"
        assert payload["baseModels"] == ["scripted-base"]
        assert payload["provider"]["baseUrlHost"] == "scripted.example.com"

        replayed = client.get(
            "/api/agents/training/capability?refresh=0", headers=_auth(account["token"])
        ).get_json()
        assert replayed["source"] == "remembered"
        assert replayed["seenAt"], "a replay must carry the date it was true"

    def test_an_unsupported_endpoint_reports_its_own_reason(self, client, account):
        testing_provider.script_fine_tuning(
            supported=False, reason="This endpoint serves chat only."
        )
        payload = client.get(
            "/api/agents/training/capability", headers=_auth(account["token"])
        ).get_json()
        assert payload["supported"] is False
        assert payload["reason"] == "This endpoint serves chat only."

    def test_the_capability_response_carries_no_key(self, client, account):
        payload = client.get(
            "/api/agents/training/capability", headers=_auth(account["token"])
        ).get_json()
        assert API_KEY not in json.dumps(payload)


class TestPreview:
    def test_the_preview_names_what_would_be_sent(
        self, client, account, approved_corpus
    ):
        response = client.post(
            "/api/agents/training/dataset/preview",
            json={"split": "train"}, headers=_auth(account["token"]),
        )
        assert response.status_code == 200, response.get_json()
        payload = response.get_json()
        assert payload["dataset"]["rows"] > 0
        assert payload["dataset"]["sha256"]
        assert payload["consent"]["destinationHost"] == "scripted.example.com"
        assert payload["consent"]["rowsDigest"] == payload["dataset"]["sha256"]
        assert "identifiers" in payload["consent"]["note"].lower()
        assert payload["consent"]["licences"]
        # dev/125: the eight interaction fixtures are no longer excluded — the
        # contract expresses their edges now, so the same rule includes them.
        # The excluded LIST stays in the payload: whatever is left out is named
        # with its reason, which is the property this asserts.
        assert not [
            entry for entry in payload["dataset"]["excluded"]
            if entry["reason"] == "interaction-edge"
        ]
        assert all(
            entry.get("reason") and entry.get("fixtureId")
            for entry in payload["dataset"]["excluded"]
        )
        assert API_KEY not in json.dumps(payload)

    def test_the_preview_refuses_while_the_corpus_is_unreviewed(self, client, account):
        """The shipping state: the files on disk are pending review."""
        response = client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "review" in response.get_json()["error"]

    @pytest.mark.parametrize("split", ["heldout", "validation"])
    def test_the_evaluation_splits_are_refused_by_name(
        self, client, account, approved_corpus, split
    ):
        response = client.post(
            "/api/agents/training/dataset/preview", json={"split": split},
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "may not draw from" in response.get_json()["error"]


class TestStart:
    def _preview(self, client, token):
        return client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(token),
        ).get_json()

    def test_the_whole_lane_from_consent_to_a_submitted_job(
        self, client, account, approved_corpus
    ):
        testing_provider.script_fine_tuning()
        preview = self._preview(client, account["token"])
        response = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        )
        assert response.status_code == 201, response.get_json()
        record = response.get_json()
        assert record["status"] in ("queued", "running")
        assert record["providerJobId"]
        assert record["submitted"] is True
        assert [e["kind"] for e in record["events"]][:3] == [
            "consented", "uploaded", "submitted",
        ]
        assert record["consent"]["rowsDigest"] == preview["consent"]["rowsDigest"]
        assert API_KEY not in json.dumps(record)

        # What would have left the install is what the preview described.
        uploaded = testing_provider.uploaded_training_files()
        assert len(uploaded) == 1
        name, content = uploaded[0]
        assert name == f"{record['jobId']}.jsonl"
        assert len(content.decode("utf-8").strip().splitlines()) == (
            preview["dataset"]["rows"]
        )
        assert API_KEY not in content.decode("utf-8")

    def test_consent_must_echo_the_digest_and_be_confirmed(
        self, client, account, approved_corpus
    ):
        preview = self._preview(client, account["token"])
        unconfirmed = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "b", "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": False,
            },
            headers=_auth(account["token"]),
        )
        assert unconfirmed.status_code == 409
        assert "explicit confirmation" in unconfirmed.get_json()["error"]

        stale = client.post(
            "/api/agents/training/jobs",
            json={"baseModel": "b", "rowsDigest": "d" * 64, "confirmed": True},
            headers=_auth(account["token"]),
        )
        assert stale.status_code == 409
        assert "changed since it was shown" in stale.get_json()["error"]
        assert testing_provider.uploaded_training_files() == []

    def test_a_base_model_must_be_named_rather_than_guessed(
        self, client, account, approved_corpus
    ):
        preview = self._preview(client, account["token"])
        response = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "", "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        )
        assert response.status_code == 400
        assert "name the base model" in response.get_json()["error"]

    def test_an_unsupported_endpoint_cannot_start_a_job(
        self, client, account, approved_corpus
    ):
        preview = self._preview(client, account["token"])
        testing_provider.script_fine_tuning(supported=False, reason="chat only here")
        response = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "b", "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "chat only here" in response.get_json()["error"]
        assert testing_provider.uploaded_training_files() == []

    def test_only_one_job_may_be_in_flight(self, client, account, approved_corpus):
        testing_provider.script_fine_tuning()
        preview = self._preview(client, account["token"])
        body = {
            "baseModel": "scripted-base",
            "rowsDigest": preview["consent"]["rowsDigest"],
            "confirmed": True,
        }
        first = client.post(
            "/api/agents/training/jobs", json=body, headers=_auth(account["token"])
        )
        assert first.status_code == 201
        second = client.post(
            "/api/agents/training/jobs", json=body, headers=_auth(account["token"])
        )
        assert second.status_code == 409
        assert "already running" in second.get_json()["error"]
        assert len(testing_provider.uploaded_training_files()) == 1

    def test_the_consent_record_is_on_disk_before_anything_is_uploaded(
        self, client, account, approved_corpus, monkeypatch
    ):
        """dev/87's rule, proven by its failure mode: with the upload made to
        fail, the record must still say what was consented to and must NOT say
        anything was submitted."""
        testing_provider.script_fine_tuning()
        preview = self._preview(client, account["token"])

        def _boom(config, **kwargs):
            raise providers.FineTuningUnavailable("the upload failed on purpose")

        monkeypatch.setattr(providers, "upload_training_file", _boom)
        response = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        )
        assert response.status_code == 502
        records = records_mod.list_records(account["key"])
        assert len(records) == 1
        record = records[0]
        kinds = [event["kind"] for event in record.events]
        assert "consented" in kinds
        assert "submitted" not in kinds
        assert record.consented_only is True
        assert record.status == "failed"
        assert "failed on purpose" in (record.error or "")


class TestStatusAndCancel:
    def _start(self, client, account):
        testing_provider.script_fine_tuning()
        preview = client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(account["token"]),
        ).get_json()
        return client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        ).get_json()

    def test_status_follows_the_provider_and_carries_when_it_was_read(
        self, client, account, approved_corpus
    ):
        record = self._start(client, account)
        testing_provider.script_fine_tuning(statuses=["running", "succeeded"])
        first = client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        assert first["status"] == "running"
        assert first["statusReadAt"]
        second = client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        assert second["status"] == "succeeded"
        assert second["trainedModel"]
        assert second["usage"]["trainedTokens"] == 4321
        # Status events append; nothing is rewritten.
        assert [e["kind"] for e in second["events"]].count("status") >= 3

    def test_a_succeeded_job_records_the_trained_model_with_its_provenance(
        self, client, account, approved_corpus
    ):
        from utk_curio.backend.app.agents import model_catalog

        record = self._start(client, account)
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        final = client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        ).get_json()
        rows = model_catalog.trained_models(
            account["key"], "testing", "http://scripted.example.com/v1"
        )
        assert len(rows) == 1
        assert rows[0]["model"] == final["trainedModel"]
        assert rows[0]["origin"] == "trained-in-curio"
        assert rows[0]["jobId"] == record["jobId"]
        assert rows[0]["datasetSha256"] == record["dataset"]["sha256"]

    def test_no_cost_is_invented_and_an_operator_rate_is_labelled(
        self, client, account, approved_corpus
    ):
        testing_provider.script_fine_tuning()
        preview = client.post(
            "/api/agents/training/dataset/preview", json={},
            headers=_auth(account["token"]),
        ).get_json()
        plain = client.post(
            "/api/agents/training/jobs",
            json={
                "baseModel": "scripted-base",
                "rowsDigest": preview["consent"]["rowsDigest"],
                "confirmed": True,
            },
            headers=_auth(account["token"]),
        ).get_json()
        assert plain["cost"] is None
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        record = records_mod.read(account["key"], plain["jobId"])
        record.usage["trainedTokens"] = 1_000_000
        assert records_mod.estimate_cost(record, None) is None
        priced = records_mod.estimate_cost(record, [8.0])
        assert priced["operatorSupplied"] is True
        assert priced["estimatedUsd"] == 8.0

    def test_cancelling_asks_the_provider_and_records_its_answer(
        self, client, account, approved_corpus
    ):
        record = self._start(client, account)
        response = client.post(
            f"/api/agents/training/jobs/{record['jobId']}/cancel",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 200
        cancelled = response.get_json()
        assert cancelled["status"] == "cancelled"
        assert "cancelled" in [e["kind"] for e in cancelled["events"]]

    def test_a_cancel_the_provider_refuses_stays_refused(
        self, client, account, approved_corpus
    ):
        record = self._start(client, account)
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        )
        response = client.post(
            f"/api/agents/training/jobs/{record['jobId']}/cancel",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 409
        assert "already" in response.get_json()["error"]

    def test_an_unknown_job_is_a_404(self, client, account):
        response = client.get(
            "/api/agents/training/jobs/train-20260101T000000Z-deadbeef",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 404

    def test_a_malformed_job_id_is_refused_before_it_becomes_a_path(
        self, client, account
    ):
        """A traversal attempt does not even match the URL rule (Werkzeug
        refuses it), so the interesting case is an id that DOES reach the
        handler while not being a job id: it must be refused rather than
        turned into a filename."""
        response = client.get(
            "/api/agents/training/jobs/not-a-train-id",
            headers=_auth(account["token"]),
        )
        assert response.status_code == 400
        assert "invalid training job id" in response.get_json()["error"]

    def test_the_listing_names_the_in_flight_job(
        self, client, account, approved_corpus
    ):
        record = self._start(client, account)
        listing = client.get(
            "/api/agents/training/jobs", headers=_auth(account["token"])
        ).get_json()
        assert [job["jobId"] for job in listing["jobs"]] == [record["jobId"]]
        assert listing["inFlight"] == record["jobId"]

    def test_a_terminal_job_is_not_re_asked(self, client, account, approved_corpus):
        record = self._start(client, account)
        testing_provider.script_fine_tuning(statuses=["succeeded"])
        client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        )
        before = len(
            records_mod.read(account["key"], record["jobId"]).events
        )
        client.get(
            f"/api/agents/training/jobs/{record['jobId']}",
            headers=_auth(account["token"]),
        )
        after = len(records_mod.read(account["key"], record["jobId"]).events)
        assert after == before, "the provider has said its last word"


class TestTheRecordItself:
    def test_events_only_ever_append(self, tmp_curio):
        record = records_mod.TrainingRecord(job_id=records_mod.new_job_id())
        record.append("consented", rows=3)
        record.append("uploaded", fileId="f")
        records_mod.write("1", record)
        again = records_mod.read("1", record.job_id)
        again.append("submitted", providerJobId="j")
        records_mod.write("1", again)
        final = records_mod.read("1", record.job_id)
        assert [e["kind"] for e in final.events] == [
            "consented", "uploaded", "submitted",
        ]

    def test_an_unknown_event_kind_is_refused(self, tmp_curio):
        record = records_mod.TrainingRecord(job_id=records_mod.new_job_id())
        with pytest.raises(records_mod.TrainingRecordError):
            record.append("whatever")

    def test_a_record_from_a_newer_curio_is_read_but_flagged(self, tmp_curio):
        record = records_mod.TrainingRecord(job_id=records_mod.new_job_id())
        records_mod.write("1", record)
        path = records_mod.record_path("1", record.job_id)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["recordVersion"] = records_mod.RECORD_VERSION + 5
        path.write_text(json.dumps(payload), encoding="utf-8")
        read_back = records_mod.read("1", record.job_id)
        assert read_back is not None
        assert "newer Curio" in (read_back.error or "")

    def test_a_job_id_is_validated_before_it_becomes_a_path(self):
        for bad in ("../escape", "train-x", "", "train-20260101T000000Z-XYZ"):
            with pytest.raises(records_mod.TrainingRecordError):
                records_mod.record_path("1", bad)

    def test_the_service_owns_no_thread_queue_or_lease(self):
        """OQ-009 stays open: the provider owns the long-running work, so this
        package introduces no scheduler of its own."""
        import re

        forbidden = re.compile(r"\b(threading|Thread|Queue|asyncio|schedule|lease)\b")
        offenders = []
        for path in (
            REPO_ROOT / "utk_curio/backend/app/agents/training"
        ).glob("*.py"):
            if forbidden.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        assert not offenders, offenders
