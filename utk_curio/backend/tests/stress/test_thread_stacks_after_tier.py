"""After a tier with any failure, the harness saves the backend's thread stacks.

The 11-07 stress run's backend stalled in its fourth pass and the job's
artifacts held no stacks, so which lock each thread waited on could only be
read from the code. The harness (``run.py``) now asks the backend, through the
probe, after each tier with a failure, and writes the dump into ``--out``,
which the stress jobs upload; a clean tier asks for nothing. ``--stacks-only``
asks once and runs no tier, as a job does after a failed step, without waiting
on a backend that may be stalled. These drive ``run.main`` with the backend's
side stood in for. Names are imported in each test, so a checkout without
them fails test by test.
"""

import pytest

_DUMP = ("=== thread stacks of pid 7 at 2026-11-07T17:33:02Z: 2 thread(s), 1 different stack(s) ===\n"
         "\n2 thread(s): Thread-1 [1], Thread-2 [2]\n"
         '  File "room_state.py", line 88, in join\n    with self._lock:\n'
         "\n=== end of the thread stacks of pid 7 ===\n")


class _Probe:
    """The probe, answering for a backend that dumps its stacks."""

    def __init__(self):
        self.asked = 0

    def thread_stacks(self):
        self.asked += 1
        return {"pid": 7, "path": "/app/.curio/backend-thread-stacks.txt", "stacks": _DUMP}


def _harness(monkeypatch, failed_tiers):
    """``run`` with the backend stood in for: each tier fails when
    *failed_tiers*, read in order, says so; and the probe."""
    from utk_curio.backend.tests.stress import run
    from utk_curio.backend.tests.stress.driver import Sample, UserResult

    probe = _Probe()
    outcomes = iter(failed_tiers)

    def probe_tier(_probe, _run):
        failed = next(outcomes)
        result = UserResult(user="u", example="e.json", started_at=0.0, seconds=1.0,
                            completed=not failed)
        result.samples.append(Sample(endpoint="/processPythonCode", node_id="n", seconds=0.1,
                                     status=500 if failed else 200, ok=not failed,
                                     error="refused" if failed else None,
                                     kind="http_error" if failed else None))
        return ([result], 1.0, []), None, None, None

    monkeypatch.setattr(run, "make_probe", lambda args: probe)
    monkeypatch.setattr(run, "wait_for_backend", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "load_mix", lambda names: [])
    monkeypatch.setattr(run, "run_baseline", lambda *args, **kwargs: {})
    monkeypatch.setattr(run, "read_exec_lock", lambda *args, **kwargs: None)
    monkeypatch.setattr(run, "probe_tier", probe_tier)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return run, probe


def test_a_tier_with_failures_saves_the_stacks_and_a_clean_tier_does_not(monkeypatch, tmp_path):
    run, probe = _harness(monkeypatch, [True, False])

    code = run.main(["--tiers", "5,10", "--room-size", "0", "--out", str(tmp_path)])

    assert code == 1
    assert probe.asked == 1
    saved = sorted(path.name for path in tmp_path.glob("thread-stacks-*"))
    assert saved == ["thread-stacks-tier-1-5-users.txt"]
    text = (tmp_path / saved[0]).read_text(encoding="utf-8")
    assert "asked the backend for its thread stacks at " in text
    assert "(pid 7, its file /app/.curio/backend-thread-stacks.txt)" in text
    assert text.endswith(_DUMP)


def test_a_probe_that_cannot_ask_leaves_the_reason_in_the_file(monkeypatch, tmp_path):
    from utk_curio.backend.tests.stress.backend_probe import ProbeError

    run, probe = _harness(monkeypatch, [True])

    def cannot_ask():
        probe.asked += 1
        raise ProbeError("exit 1: no such container")

    probe.thread_stacks = cannot_ask
    assert run.main(["--tiers", "5", "--room-size", "0", "--out", str(tmp_path)]) == 1
    assert probe.asked == 1
    text = (tmp_path / "thread-stacks-tier-1-5-users.txt").read_text(encoding="utf-8")
    assert "Problem: the probe could not ask: exit 1: no such container" in text


def test_stacks_only_asks_once_and_waits_on_no_backend(monkeypatch, tmp_path):
    run, probe = _harness(monkeypatch, [])

    def stalled(*args, **kwargs):
        raise AssertionError("--stacks-only waited on the backend")

    monkeypatch.setattr(run, "wait_for_backend", stalled)
    monkeypatch.setattr(run, "run_baseline", stalled)

    assert run.main(["--stacks-only", "failed-job", "--out", str(tmp_path)]) == 0
    assert probe.asked == 1
    assert (tmp_path / "thread-stacks-failed-job.txt").read_text(encoding="utf-8").endswith(_DUMP)


def test_stacks_only_needs_the_probe(capsys, tmp_path):
    from utk_curio.backend.tests.stress import run

    with pytest.raises(SystemExit):
        run.main(["--stacks-only", "failed-job", "--no-probe", "--out", str(tmp_path)])
    assert "--stacks-only asks through the probe" in capsys.readouterr().err
