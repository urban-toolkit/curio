"""Choosing the runner for each job of a CI run: arcade first.

``scripts/ci_pick_runners.py`` runs as the first job of the Full stack build and
writes the ``runs-on`` of the CPU jobs and the GPU job. A wrong answer sends
jobs to a pool that is full or down, and a crash would stop the whole run, so
these feed it job lists shaped like the GitHub jobs API's.
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


def _arcade(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "cpu"], "arcade-cpu-03" if status == "in_progress" else None, age_s)


def _arcade_gpu(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "gpu", "h100"], "arcade-gpu" if status == "in_progress" else None, age_s)


def test_an_idle_arcade_takes_every_cpu_job():
    assert set(picker.assign_cpu(CPU, 20).values()) == {"arcade"}


def test_jobs_past_arcade_s_free_runners_go_to_hosted():
    chosen = picker.assign_cpu(CPU, 2)
    assert list(chosen.values()) == ["arcade", "arcade", "hosted", "hosted", "hosted"]


def test_an_idle_arcade_gpu_takes_the_gpu_job_and_a_busy_one_sends_it_to_utk():
    assert picker.assign_gpu(GPU, False) == {"test-gpu": "arcade-gpu"}
    assert picker.assign_gpu(GPU, True) == {"test-gpu": "utk"}
    # A second GPU job finds arcade-gpu taken by the first.
    assert picker.assign_gpu(["a", "b"], False) == {"a": "arcade-gpu", "b": "utk"}


def test_forced_pools_take_every_job():
    assert set(picker.assign_cpu(CPU, 20, "hosted").values()) == {"hosted"}
    assert set(picker.assign_cpu(CPU, 0, "arcade").values()) == {"arcade"}
    assert picker.assign_gpu(GPU, True, "arcade") == {"test-gpu": "arcade-gpu"}
    assert picker.assign_gpu(GPU, False, "utk") == {"test-gpu": "utk"}


def test_jobs_are_counted_against_the_pool_they_hold():
    jobs = [_arcade(), _arcade("queued"), _arcade_gpu(),
            _job("in_progress", ["self-hosted", "linux", "gpu", "curio"], "utk-gpu"),
            _job("in_progress", ["ubuntu-latest"], "GitHub Actions 1000008521"),
            _job("completed", ["self-hosted", "cpu"], "arcade-cpu-01")]
    counts = picker.busy(jobs, NOW)
    assert (counts["arcade"], counts["arcade-gpu"], counts["utk"], counts["hosted"]) == (2, 1, 1, 1)
    assert (counts["arcade_stuck"], counts["arcade_gpu_stuck"]) == (False, False)


def test_a_busy_arcade_sends_the_rest_to_hosted_and_test_gpu_to_utk():
    jobs = [_arcade() for _ in range(18)] + [_arcade_gpu()]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert [chosen[k] for k in CPU] == ["arcade", "arcade", "hosted", "hosted", "hosted"]
    assert chosen["test-gpu"] == "utk"
    assert any("2 of 20" in line for line in how)


def test_an_arcade_job_queued_too_long_with_idle_runners_means_arcade_is_down():
    jobs = [_arcade("queued", age_s=picker.STUCK_AFTER_S + 60)]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert {chosen[k] for k in CPU} == {"hosted"}
    assert chosen["test-gpu"] == "arcade-gpu"
    assert any("waited" in line for line in how)


def test_an_arcade_gpu_job_queued_too_long_sends_test_gpu_to_utk():
    jobs = [_arcade_gpu("queued", age_s=picker.STUCK_AFTER_S + 60)]
    chosen, _ = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert chosen["test-gpu"] == "utk"


def test_an_api_failure_still_picks_arcade_first():
    def broken():
        raise OSError("HTTP Error 502")

    chosen, how = picker.pick(CPU, GPU, "auto", "auto", broken)
    assert {chosen[k] for k in CPU} == {"arcade"} and chosen["test-gpu"] == "arcade-gpu"
    assert any("502" in line for line in how)


def test_main_writes_runs_on_values_for_every_key(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CURIO_CI_POOL", "Hosted")
    monkeypatch.setenv("CURIO_CI_GPU_POOL", "utk")
    assert picker.main(["ci_pick_runners.py", "--gpu", "test-gpu", *CPU]) == 0
    runners = json.loads(out.read_text().strip().removeprefix("runners="))
    assert runners == {"test-gpu": ["self-hosted", "gpu", "curio"], **{k: "ubuntu-latest" for k in CPU}}


def test_an_unknown_pool_value_falls_back_to_picking(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    monkeypatch.setenv("CURIO_CI_POOL", "elsewhere")
    monkeypatch.delenv("CURIO_CI_GPU_POOL", raising=False)
    monkeypatch.setattr(picker, "active_jobs", lambda *a: [])
    monkeypatch.setenv("GITHUB_REPOSITORY", "urban-toolkit/curio")
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    assert picker.main(["ci_pick_runners.py", "--gpu", "test-gpu", "jest"]) == 0
    assert "not one of auto" in capsys.readouterr().err
    runners = json.loads((tmp_path / "out").read_text().strip().removeprefix("runners="))
    assert runners == {"test-gpu": ["self-hosted", "gpu", "h100"], "jest": ["self-hosted", "cpu"]}
