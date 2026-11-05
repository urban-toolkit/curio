"""dev/115 (DEC-073 / DEC-021 single-process slice) — the detached agent-job
registry: replay + tail subscription, one live job per attachment, per-user
backpressure, finished-job replay window, and reconciliation of a builder
session whose execution this process does not hold."""

from __future__ import annotations

import threading
import time

import pytest

from utk_curio.backend.app.agents.infrastructure import agent_jobs


def _gen(items, gate: threading.Event | None = None, fail_after: int | None = None):
    def _events():
        for i, item in enumerate(items):
            if gate is not None and i == 1:
                gate.wait(timeout=5)
            if fail_after is not None and i == fail_after:
                raise RuntimeError("boom")
            yield item
    return _events()


def _drain(gen, limit=50):
    out = []
    for item in gen:
        out.append(item)
        if len(out) >= limit:
            break
    return out


class TestRegistry:
    def test_replay_then_tail_then_sentinel(self):
        gate = threading.Event()
        job = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="e1",
            events=_gen([("solve_started", {"n": 1}), ("node_result", {"n": 2}), ("done", {})], gate=gate),
        )
        time.sleep(0.05)  # the first event is published before the gate
        sub = agent_jobs.subscribe(job)
        first = next(sub)
        assert first == ("solve_started", {"n": 1})  # replayed
        gate.set()
        rest = list(sub)  # tails to the sentinel
        assert rest == [("node_result", {"n": 2}), ("done", {})]
        job.thread.join(timeout=5)
        assert job.status == "done" and job.finished_at is not None
        # A finished job replays everything and ends.
        assert list(agent_jobs.subscribe(job)) == [
            ("solve_started", {"n": 1}), ("node_result", {"n": 2}), ("done", {}),
        ]
        assert agent_jobs.is_live("e1") is False

    def test_early_exit_only_unsubscribes(self):
        gate = threading.Event()
        job = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="e2",
            events=_gen([("a", {}), ("b", {}), ("done", {})], gate=gate),
        )
        time.sleep(0.05)
        sub = agent_jobs.subscribe(job)
        assert next(sub) == ("a", {})
        sub.close()  # the client went away
        assert job.live and job.subscribers == []
        gate.set()
        job.thread.join(timeout=5)
        assert job.status == "done"
        assert len(job.events) == 3  # the job finished on its own

    def test_generator_failure_is_a_terminal_error_event(self):
        job = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-node", job_id="e3",
            events=_gen([("x", {}), ("y", {})], fail_after=1),
        )
        job.thread.join(timeout=5)
        assert job.status == "error"
        events = list(agent_jobs.subscribe(job))
        assert events[0] == ("x", {})
        assert events[1][0] == "error" and "boom" in events[1][1]

    def test_one_live_job_per_attachment_and_per_user_cap(self):
        gates = [threading.Event() for _ in range(3)]
        jobs = []
        for i in range(2):
            jobs.append(agent_jobs.start_job(
                user_key="u", project_id="p", attachment_id=f"a{i}", kind="solve-batch", job_id=f"j{i}",
                events=_gen([("a", {}), ("done", {})], gate=gates[i]),
            ))
        with pytest.raises(agent_jobs.JobRefused) as same:
            agent_jobs.check_can_start("u", "a0")
        assert same.value.status == 409
        with pytest.raises(agent_jobs.JobRefused) as cap:
            agent_jobs.check_can_start("u", "a9")
        assert cap.value.status == 429
        # Another user is unaffected.
        agent_jobs.check_can_start("v", "a0")
        for g in gates:
            g.set()
        for job in jobs:
            job.thread.join(timeout=5)
        agent_jobs.check_can_start("u", "a0")  # finished jobs free the slot
        assert agent_jobs.live_job("u", "a0") is None
        assert agent_jobs.latest_job("u", "a0") is jobs[0]  # replayable within the TTL

    def test_live_jobs_are_the_running_ones_of_every_user(self):
        """What a test rig's reset stops: every job still running, whoever
        started it; a finished one is only replayed."""
        gates = [threading.Event(), threading.Event()]
        running = [
            agent_jobs.start_job(
                user_key=user, project_id="p", attachment_id="a", kind="solve-batch",
                job_id=f"running-{user}", events=_gen([("a", {}), ("done", {})], gate=gate),
            )
            for user, gate in zip(("u", "v"), gates)
        ]
        finished = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="b", kind="solve-node",
            job_id="finished", events=_gen([("done", {})]),
        )
        finished.thread.join(timeout=5)
        try:
            assert sorted(job.job_id for job in agent_jobs.live_jobs()) == ["running-u", "running-v"]
        finally:
            for gate in gates:
                gate.set()
            for job in running:
                job.thread.join(timeout=5)
        assert agent_jobs.live_jobs() == []

    def test_bad_kind_refused(self):
        with pytest.raises(ValueError):
            agent_jobs.start_job(user_key="u", project_id="p", attachment_id="a",
                                 kind="nope", job_id="e", events=iter(()))

    def test_sweep_drops_stale_finished_jobs(self):
        job = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-node", job_id="e4",
            events=_gen([("done", {})]),
        )
        job.thread.join(timeout=5)
        assert agent_jobs.sweep_finished(now=time.time()) == 0
        assert agent_jobs.sweep_finished(now=time.time() + agent_jobs.FINISHED_TTL_SECONDS + 1) == 1
        assert agent_jobs.latest_job("u", "a") is None


class TestReconcileBuilderSession:
    def test_solving_without_a_live_execution_becomes_interrupted(self):
        session = {"phase": "solving", "solveExecutionId": "dead", "solvingSince": 1.0,
                   "cancelRequested": True, "nodeRuns": {"n1": "pending", "n2": "solved"}}
        assert agent_jobs.reconcile_builder_session(session, now=42.0) is True
        assert session["phase"] == "interrupted"
        assert session["interruptedExecutionId"] == "dead"
        assert session["interruptedAt"] == 42.0
        assert "solveExecutionId" not in session and "solvingSince" not in session
        assert "cancelRequested" not in session
        assert session["nodeRuns"] == {"n1": "pending", "n2": "solved"}  # untouched: Retry targets pending

    def test_live_execution_is_left_alone(self):
        gate = threading.Event()
        job = agent_jobs.start_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="live",
            events=_gen([("a", {}), ("done", {})], gate=gate),
        )
        session = {"phase": "solving", "solveExecutionId": "live"}
        assert agent_jobs.reconcile_builder_session(session) is False
        assert session["phase"] == "solving"
        gate.set()
        job.thread.join(timeout=5)

    def test_other_phases_and_shapes_are_untouched(self):
        for session in ({"phase": "ready"}, {"phase": "applied", "solveExecutionId": "x"}, {}, None):
            assert agent_jobs.reconcile_builder_session(session) is False

    def test_an_execution_registered_before_its_job_runs_is_left_alone(self):
        # The Solve's request registers its job, writes the session, and only
        # then runs the job; a read in between finds the execution live.
        job = agent_jobs.register_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="starting",
        )
        session = {"phase": "solving", "solveExecutionId": "starting", "solvingSince": 1.0}
        assert agent_jobs.reconcile_builder_session(session) is False
        assert session == {"phase": "solving", "solveExecutionId": "starting", "solvingSince": 1.0}
        agent_jobs.run_job(job, _gen([("done", {})]))
        job.thread.join(timeout=5)
        assert job.status == "done"


class TestAJobRegisteredBeforeItRuns:
    def test_it_holds_its_attachment_from_its_registration_until_its_events_end(self):
        gate = threading.Event()
        job = agent_jobs.register_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="r1",
        )
        assert job.thread is None and agent_jobs.is_live("r1")
        assert agent_jobs.live_job("u", "a") is job
        with pytest.raises(agent_jobs.JobRefused) as busy:
            agent_jobs.check_can_start("u", "a")
        assert busy.value.status == 409
        assert agent_jobs.run_job(job, _gen([("a", {}), ("done", {})], gate=gate)) is job
        gate.set()
        job.thread.join(timeout=5)
        assert job.status == "done"
        assert list(agent_jobs.subscribe(job)) == [("a", {}), ("done", {})]
        agent_jobs.check_can_start("u", "a")  # its end frees the slot

    def test_one_whose_caller_fails_before_it_runs_ends_with_the_error_and_frees_its_attachment(self):
        key = "sk-job-secret-0123456789"
        job = agent_jobs.register_job(
            user_key="u", project_id="p", attachment_id="a", kind="solve-batch", job_id="r2",
            redact_values={"llm-api-key": key},
        )
        agent_jobs.fail_job(job, f"the Solve did not start: 401 for key {key}")
        assert job.status == "error" and job.finished_at is not None
        assert not agent_jobs.is_live("r2") and agent_jobs.live_job("u", "a") is None
        events = list(agent_jobs.subscribe(job))
        assert len(events) == 1
        kind, message = events[0]
        assert kind == "error" and message.startswith("the Solve did not start: 401 for key")
        assert key not in message
        agent_jobs.check_can_start("u", "a")  # nothing holds the attachment


class TestRedaction:
    def test_a_failure_neither_publishes_nor_logs_the_key(self, caplog):
        import logging

        key = "sk-job-secret-0123456789"

        def _events():
            yield ("started", {})
            raise RuntimeError(f"401 from the provider for key {key}")

        caplog.set_level(logging.ERROR)
        job = agent_jobs.start_job(
            user_key="u-redact", project_id="p", attachment_id="a-redact", kind="solve-batch",
            job_id="e-redact", events=_events(), redact_values={"llm-api-key": key},
        )
        job.thread.join(timeout=5)
        events = list(agent_jobs.subscribe(job))
        kind, message = events[-1]
        assert kind == "error" and "401 from the provider" in message
        assert key not in repr(events)
        assert key not in caplog.text
        assert key not in repr(job)
