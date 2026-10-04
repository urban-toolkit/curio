"""Choosing the runner for each job of a CI run.

``scripts/ci_pick_runners.py`` runs as the first job of the Full stack build and
writes the ``runs-on`` of the CPU jobs (GitHub-hosted first, then arcade) and
the GPU job (the arcade GPU pool first, then utk). A wrong answer sends jobs to a pool
that is full or down, and a crash would stop the whole run, so these feed it
job lists shaped like the GitHub jobs API's.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


picker = _load("ci_pick_runners")

NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)
CPU = ["build-image", "jest", "e2e-desktop-1", "e2e-desktop-2", "unit-backend-1"]
GPU = ["test-gpu"]


def _job(status, labels, runner=None, age_s=0):
    created = (NOW - timedelta(seconds=age_s)).isoformat().replace("+00:00", "Z")
    return {"status": status, "labels": labels, "runner_name": runner, "created_at": created}


def _hosted(status="in_progress", age_s=0):
    return _job(status, ["ubuntu-latest"], "GitHub Actions 1000008521" if status == "in_progress" else None, age_s)


def _arcade(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "cpu"], "arcade-cpu-03" if status == "in_progress" else None, age_s)


def _arcade_gpu(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "gpu", "h100"], "arcade-gpu-02" if status == "in_progress" else None, age_s)


def test_room_on_hosted_takes_every_cpu_job():
    assert set(picker.assign_cpu(CPU, 20).values()) == {"hosted"}


def test_jobs_past_the_hosted_room_go_to_arcade():
    chosen = picker.assign_cpu(CPU, 2)
    assert list(chosen.values()) == ["hosted", "hosted", "arcade", "arcade", "arcade"]


def test_a_free_arcade_gpu_runner_takes_the_gpu_job_and_none_free_sends_it_to_utk():
    assert picker.assign_gpu(GPU, 1) == {"test-gpu": "arcade-gpu"}
    assert picker.assign_gpu(GPU, 0) == {"test-gpu": "utk"}
    # A second GPU job finds the one free arcade runner taken by the first.
    assert picker.assign_gpu(["a", "b"], 1) == {"a": "arcade-gpu", "b": "utk"}


def test_gpu_jobs_fill_every_free_arcade_gpu_runner_before_utk():
    keys = [f"gpu-{i}" for i in range(picker.GPU_RUNNERS + 1)]
    chosen = picker.assign_gpu(keys, picker.GPU_RUNNERS)
    assert [chosen[k] for k in keys] == ["arcade-gpu"] * picker.GPU_RUNNERS + ["utk"]


def test_forced_pools_take_every_job():
    assert set(picker.assign_cpu(CPU, 20, "arcade").values()) == {"arcade"}
    assert set(picker.assign_cpu(CPU, 0, "hosted").values()) == {"hosted"}
    assert picker.assign_gpu(GPU, 0, "arcade") == {"test-gpu": "arcade-gpu"}
    assert picker.assign_gpu(GPU, picker.GPU_RUNNERS, "utk") == {"test-gpu": "utk"}


def test_jobs_are_counted_against_the_pool_they_hold():
    jobs = [_arcade(), _arcade("queued"), _arcade_gpu(),
            _job("in_progress", ["self-hosted", "linux", "gpu", "curio"], "utk-gpu"),
            _hosted(), _hosted("queued", age_s=5),
            _job("completed", ["self-hosted", "cpu"], "arcade-cpu-01")]
    counts = picker.busy(jobs, NOW)
    assert (counts["arcade"], counts["arcade-gpu"], counts["utk"], counts["hosted"]) == (2, 1, 1, 2)
    assert (counts["arcade_stuck"], counts["arcade_gpu_stuck"], counts["hosted_full"]) == (False, False, False)


def test_a_job_on_any_arcade_gpu_runner_counts_against_the_gpu_pool():
    jobs = [_job("in_progress", [], "arcade-gpu-01"), _job("in_progress", [], "arcade-gpu-03")]
    assert picker.busy(jobs, NOW)["arcade-gpu"] == 2


def test_hosted_room_left_by_other_runs_and_this_run_s_hosted_jobs_goes_first():
    jobs = [_hosted() for _ in range(15)] + [_arcade_gpu() for _ in range(picker.GPU_RUNNERS)]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs, hosted_reserved=3)
    # 20 slots, 15 held by other runs, 3 kept for this run's hosted-only jobs.
    assert [chosen[k] for k in CPU] == ["hosted", "hosted", "arcade", "arcade", "arcade"]
    assert chosen["test-gpu"] == "utk"
    assert any("2 of 20" in line for line in how)
    assert any(f"0 of {picker.GPU_RUNNERS} arcade GPU runners free" in line for line in how)


def test_one_free_arcade_gpu_runner_still_takes_the_gpu_job():
    jobs = [_arcade_gpu() for _ in range(picker.GPU_RUNNERS - 1)]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert chosen["test-gpu"] == "arcade-gpu"
    assert any(f"1 of {picker.GPU_RUNNERS} arcade GPU runners free" in line for line in how)


def test_a_hosted_job_queued_past_a_minute_means_the_hosted_limit_is_reached():
    # Other repositories' jobs fill the shared limit, which the count cannot see.
    jobs = [_hosted("queued", age_s=picker.HOSTED_FULL_AFTER_S + 30)]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert {chosen[k] for k in CPU} == {"arcade"}
    assert any("hosted limit" in line for line in how)


def test_an_arcade_job_queued_too_long_keeps_every_cpu_job_on_hosted():
    jobs = [_arcade("queued", age_s=picker.STUCK_AFTER_S + 60),
            _hosted("queued", age_s=picker.HOSTED_FULL_AFTER_S + 30)]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert {chosen[k] for k in CPU} == {"hosted"}
    assert chosen["test-gpu"] == "arcade-gpu"
    assert any("waited" in line for line in how)


def test_the_cpu_pool_is_stuck_only_while_a_runner_should_be_free():
    queued = _arcade("queued", age_s=picker.STUCK_AFTER_S + 60)
    # One runner should be free yet the queued job waits: runners are offline.
    some_running = [_arcade() for _ in range(picker.CPU_RUNNERS - 1)] + [queued]
    assert picker.busy(some_running, NOW)["arcade_stuck"] is True
    # Every runner is running a job: the queued one is just waiting its turn.
    all_running = [_arcade() for _ in range(picker.CPU_RUNNERS)] + [queued]
    assert picker.busy(all_running, NOW)["arcade_stuck"] is False


def test_an_arcade_gpu_job_queued_too_long_sends_test_gpu_to_utk():
    jobs = [_arcade_gpu("queued", age_s=picker.STUCK_AFTER_S + 60)]
    chosen, _ = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert chosen["test-gpu"] == "utk"


def test_the_gpu_pool_is_stuck_only_while_a_runner_should_be_free():
    queued = _arcade_gpu("queued", age_s=picker.STUCK_AFTER_S + 60)
    # One runner should be free yet the queued job waits: runners are offline.
    some_running = [_arcade_gpu() for _ in range(picker.GPU_RUNNERS - 1)] + [queued]
    assert picker.busy(some_running, NOW)["arcade_gpu_stuck"] is True
    # Every runner is running a job: the queued one is just waiting its turn.
    all_running = [_arcade_gpu() for _ in range(picker.GPU_RUNNERS)] + [queued]
    assert picker.busy(all_running, NOW)["arcade_gpu_stuck"] is False


def test_an_api_failure_still_picks_hosted_first():
    def broken():
        raise OSError("HTTP Error 502")

    chosen, how = picker.pick(CPU, GPU, "auto", "auto", broken)
    assert {chosen[k] for k in CPU} == {"hosted"} and chosen["test-gpu"] == "arcade-gpu"
    assert any("502" in line for line in how)


def test_main_writes_runs_on_values_for_every_key(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CURIO_CI_POOL", "Arcade")
    monkeypatch.setenv("CURIO_CI_GPU_POOL", "utk")
    assert picker.main(["ci_pick_runners.py", "--gpu", "test-gpu", *CPU]) == 0
    runners = json.loads(out.read_text().strip().removeprefix("runners="))
    assert runners == {"test-gpu": ["self-hosted", "gpu", "curio"], **{k: ["self-hosted", "cpu"] for k in CPU}}


def test_an_unknown_pool_value_falls_back_to_picking(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("CURIO_CI_POOL", "elsewhere")
    monkeypatch.delenv("CURIO_CI_GPU_POOL", raising=False)
    monkeypatch.setattr(picker, "active_jobs", lambda *a: [])
    monkeypatch.setenv("GITHUB_REPOSITORY", "urban-toolkit/curio")
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    assert picker.main(["ci_pick_runners.py", "--hosted-reserved", "3", "--gpu", "test-gpu", "jest"]) == 0
    assert "not one of auto" in capsys.readouterr().err
    runners = json.loads((tmp_path / "out").read_text().strip().removeprefix("runners="))
    assert runners == {"test-gpu": ["self-hosted", "gpu", "h100"], "jest": "ubuntu-latest"}
