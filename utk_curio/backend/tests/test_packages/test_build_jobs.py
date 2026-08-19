"""Tests for :mod:`utk_curio.backend.app.packages.build_jobs` (dev/89 commit 3):
digest-idempotent creation, backpressure, forward-only phases, execute with
cancellation checkpoints, sanitized events, expiry, and payload shape.
"""

from __future__ import annotations

import pytest

from utk_curio.backend.app.packages import build_jobs
from utk_curio.backend.app.packages.build_jobs import (
    JobError,
    JobRefused,
    advance,
    attach_result,
    cancel_job,
    create_job,
    execute,
    fail,
    get_job,
    list_jobs,
    sweep_expired_jobs,
)
from utk_curio.backend.app.packages.build_models import (
    PackageBuildResult,
    parse_build_request,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    build_jobs.reset_registry()
    yield
    build_jobs.reset_registry()


def _request(package_id: str = "ai.test.demo", note: str = "v1"):
    return parse_build_request({
        "mode": "create",
        "target": f"{package_id}@1",
        "manifest": {"id": package_id, "compatibility": {"major": 1},
                     "templates": [{"id": "demo-kind"}]},
        "files": {"sources/demo.py": {"text": f"# {note}\nreturn arg\n"}},
    })


class TestCreateAndIdempotency:
    def test_create_starts_queued_with_digest_identity(self):
        job, created = create_job("guest", _request())
        assert created is True
        assert job.phase == "queued"
        assert len(job.build_id) == 64
        assert get_job("guest", job.build_id) is job

    def test_same_request_reattaches(self):
        a, _ = create_job("guest", _request())
        b, created = create_job("guest", _request())
        assert b is a and created is False

    def test_ready_job_is_returned_cached(self):
        job, _ = create_job("guest", _request())
        execute(job, [])
        assert job.phase == "ready"
        again, created = create_job("guest", _request())
        assert again is job and created is False

    def test_failed_job_is_superseded_on_retry(self):
        job, _ = create_job("guest", _request())
        fail(job, "boom")
        retry, created = create_job("guest", _request())
        assert created is True and retry is not job
        assert retry.phase == "queued"

    def test_backpressure_caps_active_jobs_per_user(self):
        create_job("guest", _request(note="a"))
        create_job("guest", _request(note="b"))
        with pytest.raises(JobRefused, match="too many active builds"):
            create_job("guest", _request(note="c"))
        # Another user is unaffected.
        job, created = create_job("7", _request(note="c"))
        assert created is True and job.user_key == "7"

    def test_list_jobs_scoped_to_user(self):
        create_job("guest", _request(note="a"))
        create_job("7", _request(note="b"))
        assert [j.user_key for j in list_jobs("guest")] == ["guest"]


class TestPhases:
    def test_forward_only_with_skips(self):
        job, _ = create_job("guest", _request())
        advance(job, "resolving")
        advance(job, "packaging")  # skipping phases is legal
        with pytest.raises(JobError, match="forward-only"):
            advance(job, "compiling")
        with pytest.raises(JobError, match="unknown phase"):
            advance(job, "shipping")

    def test_terminal_jobs_refuse_movement(self):
        job, _ = create_job("guest", _request())
        fail(job, "boom")
        with pytest.raises(JobError, match="terminal"):
            advance(job, "resolving")
        with pytest.raises(JobError, match="terminal"):
            fail(job, "again")


class TestExecute:
    def test_runs_steps_in_order_and_lands_ready(self):
        job, _ = create_job("guest", _request())
        ran: list[str] = []
        execute(job, [
            ("resolving", lambda j: ran.append("resolve")),
            ("compiling", lambda j: ran.append("compile")),
            ("packaging", lambda j: ran.append("package")),
        ])
        assert ran == ["resolve", "compile", "package"]
        assert job.phase == "ready"
        phases = [e["phase"] for e in job.events]
        assert phases == ["queued", "resolving", "compiling", "packaging", "ready"]

    def test_failing_step_fails_the_job_and_stops(self):
        job, _ = create_job("guest", _request())
        ran: list[str] = []

        def _boom(_j):
            raise RuntimeError("compiler exploded")

        execute(job, [
            ("compiling", _boom),
            ("packaging", lambda j: ran.append("package")),
        ])
        assert job.phase == "failed" and ran == []
        assert any("compiler exploded" in e["message"] for e in job.events)

    def test_cancellation_checkpoint_between_steps(self):
        job, _ = create_job("guest", _request())
        ran: list[str] = []

        def _first(j):
            ran.append("first")
            j.cancel_event.set()

        execute(job, [
            ("resolving", _first),
            ("packaging", lambda j: ran.append("second")),
        ])
        assert job.phase == "cancelled" and ran == ["first"]

    def test_cancel_job_before_execution(self):
        job, _ = create_job("guest", _request())
        assert cancel_job("guest", job.build_id) is True
        assert job.phase == "cancelled"
        assert cancel_job("guest", job.build_id) is False  # already terminal

    def test_result_attaches_and_rides_the_payload(self):
        job, _ = create_job("guest", _request())
        result = PackageBuildResult(status="ready", input_digest=job.build_id,
                                    artifact_digest="a" * 64, archive_size=10)
        execute(job, [("packaging", lambda j: attach_result(j, result))])
        payload = job.to_payload()
        assert payload["phase"] == "ready" and payload["terminal"] is True
        assert payload["result"]["artifactDigest"] == "a" * 64


class TestHygieneAndExpiry:
    def test_event_messages_are_sanitized_and_bounded(self, tmp_path):
        import os

        job, _ = create_job("guest", _request())
        home = os.path.expanduser("~")
        fail(job, f"error at {home}/.ssh/id_rsa " + "x" * 1000)
        message = job.events[-1]["message"]
        assert home not in message
        assert "<home>/.ssh/id_rsa" in message
        assert len(message) <= 500

    def test_payload_has_no_request_body(self):
        job, _ = create_job("guest", _request())
        payload = job.to_payload()
        assert set(payload) == {"buildId", "phase", "terminal", "createdAt",
                                "updatedAt", "events", "result"}

    def test_sweep_expires_stale_ready_jobs(self):
        job, _ = create_job("guest", _request())
        execute(job, [])
        assert job.phase == "ready"
        assert sweep_expired_jobs("guest", now=job.updated_at + 1) == []
        expired = sweep_expired_jobs(
            "guest", now=job.updated_at + build_jobs.READY_JOB_TTL_SECONDS + 1)
        assert expired == [job.build_id]
        assert job.phase == "expired"
        # An expired job is superseded on retry — never trusted again.
        retry, created = create_job("guest", _request())
        assert created is True and retry.phase == "queued"

    def test_terminal_jobs_pruned_beyond_cap(self, monkeypatch):
        monkeypatch.setattr(build_jobs, "MAX_TERMINAL_JOBS_PER_USER", 2)
        for i in range(4):
            job, _ = create_job("guest", _request(note=f"n{i}"))
            fail(job, "boom")
        # One more create triggers pruning of the oldest terminal jobs.
        create_job("guest", _request(note="fresh"))
        terminal = [j for j in list_jobs("guest") if j.phase == "failed"]
        assert len(terminal) <= 2
