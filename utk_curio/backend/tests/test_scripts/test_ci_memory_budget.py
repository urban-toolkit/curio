"""Sizing a CI job to the runner's free memory.

``scripts/ci_memory_budget.py`` runs at the start of test-gpu and of every
self-hosted stack. It picks test-gpu's e2e workers from free memory and video
memory, and the CI container's memory limit. Six workers lost utk-desktop-02's
runner (12 GB) and blanked utk-desktop-01's maps (8 GB of video memory) on
2026-10-25, while the arcade and utk-gpu runners must keep all six. A crash
here would stop the job, so every reading that fails must leave the defaults.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


budget = _load("ci_memory_budget")
GIB = budget.GIB


def _gib(n: float) -> int:
    return int(n * GIB)


# Free memory and video memory as each runner has them when a job starts.
ARCADE_GPU = dict(free=_gib(55), vram=_gib(70))
UTK_GPU = dict(free=_gib(300), vram=_gib(94))
DESKTOP_01 = dict(free=_gib(25), vram=_gib(7.2))
DESKTOP_02 = dict(free=_gib(9.5), vram=_gib(11))


def test_the_arcade_and_utk_gpu_runners_keep_all_six_workers():
    assert budget.budget(workers_max=6, **ARCADE_GPU)["workers"] == 6
    assert budget.budget(workers_max=6, **UTK_GPU)["workers"] == 6


def test_a_12_gb_desktop_runs_as_many_workers_as_its_memory_holds():
    assert budget.budget(workers_max=6, **DESKTOP_02)["workers"] == 2


def test_an_8_gb_card_runs_as_many_workers_as_its_video_memory_holds():
    assert budget.budget(workers_max=6, **DESKTOP_01)["workers"] == 4


def test_a_runner_without_nvidia_smi_is_sized_by_memory_alone():
    assert budget.budget(free=_gib(25), vram=None, workers_max=6)["workers"] == 6


def test_a_runner_with_almost_nothing_free_still_runs_one_worker():
    chosen = budget.budget(free=_gib(3), vram=_gib(1), workers_max=6)
    assert chosen["workers"] == 1
    assert chosen["limit"] == _gib(budget.MIN_LIMIT_GIB)


def test_the_limit_leaves_the_reserve_and_what_each_worker_needs_outside():
    chosen = budget.budget(workers_max=6, **ARCADE_GPU)
    outside = 6 * budget.WORKER_OUTSIDE_GIB
    assert chosen["limit"] == _gib(55 - budget.RESERVE_GIB - outside)


def test_a_stack_with_no_workers_to_size_gets_only_a_limit():
    chosen = budget.budget(free=_gib(9.5), vram=None, workers_max=None)
    assert chosen["workers"] is None
    assert chosen["limit"] == _gib(9.5 - budget.RESERVE_GIB - budget.WORKER_OUTSIDE_GIB)


def test_nothing_read_keeps_the_maximum_and_no_limit():
    assert budget.budget(free=None, vram=None, workers_max=6) == {"workers": 6, "limit": None}


def test_meminfo_gives_memavailable_in_bytes():
    text = "MemTotal:       12000000 kB\nMemFree:  100 kB\nMemAvailable:    9000000 kB\n"
    assert budget.meminfo_available(text) == 9000000 * 1024
    assert budget.meminfo_available("MemTotal: 1 kB\n") is None


def test_a_cgroup_s_file_cache_counts_as_free():
    # 64 GiB limit, 60 GiB charged, 40 of it file cache: 44 GiB of room.
    stat = f"anon {_gib(20)}\ninactive_file {_gib(30)}\nactive_file {_gib(10)}\n"
    assert budget.cgroup_room(str(_gib(64)), str(_gib(60)), stat) == _gib(44)


def test_a_cgroup_without_a_limit_gives_no_room_reading():
    assert budget.cgroup_room("max\n", "123", "") is None
    assert budget.cgroup_room("garbage", "123", "") is None


def _cgroup(directory: Path, limit: str, current: int, stat: str = ""):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "memory.max").write_text(limit + "\n")
    (directory / "memory.current").write_text(f"{current}\n")
    (directory / "memory.stat").write_text(stat)


def test_in_a_container_the_namespace_root_is_the_container_s_limit(tmp_path):
    _cgroup(tmp_path, str(_gib(64)), _gib(10))
    assert budget.own_cgroup_rooms(tmp_path, "0::/\n") == [_gib(54)]


def test_on_a_host_every_limit_above_the_runner_s_service_counts(tmp_path):
    service = tmp_path / "system.slice" / "actions.runner.service"
    _cgroup(service, "max", _gib(1))
    _cgroup(service.parent, str(_gib(8)), _gib(5))
    rooms = budget.own_cgroup_rooms(tmp_path, "0::/system.slice/actions.runner.service\n")
    assert rooms == [_gib(3)]


def test_no_cgroup_v2_line_gives_no_cgroup_readings(tmp_path):
    assert budget.own_cgroup_rooms(tmp_path, "12:memory:/docker/abc\n") == []


def _run_returning(stdout: str):
    def run(*_args, **_kwargs):
        return SimpleNamespace(stdout=stdout)
    return run


def _run_raising(exc: Exception):
    def run(*_args, **_kwargs):
        raise exc
    return run


def test_free_video_memory_is_the_fullest_gpu_s(monkeypatch):
    monkeypatch.setattr(budget.subprocess, "run", _run_returning("7400\n61000\n"))
    assert budget.free_vram() == 7400 * budget.MIB


def test_no_nvidia_smi_gives_no_video_memory_reading(monkeypatch):
    monkeypatch.setattr(budget.subprocess, "run", _run_raising(FileNotFoundError("nvidia-smi")))
    assert budget.free_vram() is None
    monkeypatch.setattr(budget.subprocess, "run",
                        _run_raising(subprocess.CalledProcessError(9, "nvidia-smi")))
    assert budget.free_vram() is None


def test_stack_memory_adds_up_the_ci_containers_only(monkeypatch):
    stats = ("curio-ci-curio-1\t2.5GiB / 62GiB\n"
             "evl-monitor-agent\t80MiB / 30GiB\n"
             "curio-ci-other-1\t512MiB / 62GiB\n")
    monkeypatch.setattr(budget.subprocess, "run", _run_returning(stats))
    assert budget.stack_memory("curio-ci") == int(2.5 * GIB) + 512 * budget.MIB


def _size(monkeypatch, tmp_path, workers_max=6, free=None, vram=None, fail=None):
    env_file, summary = tmp_path / "env", tmp_path / "summary"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    if fail:
        monkeypatch.setattr(budget, "free_memory", _run_raising(fail))
    else:
        monkeypatch.setattr(budget, "free_memory", lambda: free)
    monkeypatch.setattr(budget, "free_vram", lambda: vram)
    argv = ["ci_memory_budget.py", "--github-env"]
    if workers_max is not None:
        argv += ["--workers-max", str(workers_max)]
    assert budget.main(argv) == 0
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    return dict(line.split("=", 1) for line in lines), summary.read_text()


def test_the_job_gets_its_workers_and_limit_through_github_env(monkeypatch, tmp_path):
    env, summary = _size(monkeypatch, tmp_path, **DESKTOP_02)
    limit_mib = (_gib(9.5) - _gib(budget.RESERVE_GIB) - 2 * _gib(budget.WORKER_OUTSIDE_GIB)) // budget.MIB
    assert env == {"CURIO_E2E_PARALLEL": "2", "CURIO_CI_MEM_LIMIT": f"{limit_mib}m"}
    assert "e2e workers: 2 of at most 6" in summary


def test_a_stack_step_writes_only_the_limit(monkeypatch, tmp_path):
    env, _ = _size(monkeypatch, tmp_path, workers_max=None, free=_gib(30))
    assert list(env) == ["CURIO_CI_MEM_LIMIT"]


def test_a_reading_that_raises_keeps_the_maximum_and_no_limit(monkeypatch, tmp_path, capsys):
    env, _ = _size(monkeypatch, tmp_path, fail=PermissionError("/proc/meminfo"))
    assert env == {"CURIO_E2E_PARALLEL": "6"}
    assert "::warning::" in capsys.readouterr().out


def test_the_report_gives_the_least_free_memory_and_the_most_of_the_rest():
    header = "\t".join(budget.COLUMNS)
    rows = ["1\t9000\t100\t50\t40\t\t300", "2\t7000\t900\t450\t60\t10\t1200", "3\t8000\t700\t\t50\t5\t800"]
    found = budget.peaks("\n".join([header, *rows]) + "\n")
    assert found["free"] == {"first": 9000, "peak": 7000}
    assert found["stack"] == {"first": 100, "peak": 900}
    assert found["chrome"] == {"first": 50, "peak": 450}
    assert found["node"] == {"first": 10, "peak": 10}
    assert found["vram_used"] == {"first": 300, "peak": 1200}
    assert found["samples"] == 3
