"""dev/115 (DEC-073 / DEC-021 single-process slice) — the detached agent-job
registry: replay + tail subscription, one live job per attachment, per-user
backpressure, finished-job replay window, and reconciliation of a builder
session whose execution this process does not hold."""

from __future__ import annotations

import threading
import time

import pytest

from utk_curio.backend.app.agents import agent_jobs


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
