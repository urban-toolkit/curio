"""Sizing a CI job to the runner's free memory.

``scripts/ci_memory_budget.py`` runs at the start of test-gpu and of every
self-hosted stack. It picks test-gpu's e2e workers from free memory and video
memory, and the CI container's memory limit. Six workers stalled
utk-desktop-01 (30 GB) and blanked its maps (8 GB of video memory) on
2026-10-25, while the arcade and utk-gpu runners must keep all six. A crash
here would stop the job, so every reading that fails must leave the defaults.

On 10-28 utk-desktop-02 held one worker and ran two, because
test_shard_isolation_e2e needs a second shard. The limit left from the same
memory (6.1 GiB) was less than the two shards took, and the kernel killed
shard 0's sandbox at it while the machine still had 2.8 GiB free (run
40700358711). A second shard needs no worker: it now runs idle beside the one
worker such a runner holds.
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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
MIB = budget.MIB


def _gib(n: float) -> int:
    return int(n * GIB)


# Free memory and video memory as each runner had them when a job started
# (#1154's runs, 10-25).
ARCADE_GPU = dict(free=_gib(60.4), vram=_gib(77))
UTK_GPU = dict(free=_gib(300), vram=_gib(94))
DESKTOP_01 = dict(free=_gib(27.3), vram=_gib(7.1))
# Something outside CI held 6.5 of utk-desktop-01's 8 GiB that morning.
DESKTOP_01_CARD_TAKEN = dict(free=_gib(24.8), vram=_gib(1.2))
DESKTOP_02 = dict(free=_gib(10.9), vram=_gib(11.3))
# test-gpu job 122858342107 (run 40700358711, 10-28): "11.1 GiB free and
# 11.6 GiB of video memory", and a limit of 6283m with two workers, so free
# was 6283 MiB plus the 2 GiB reserve plus two workers' 1.5 GiB outside.
DESKTOP_02_10_28 = dict(free=(6283 + 5 * 1024) * MIB, vram=_gib(11.6))

RUNNERS = {
    "arcade-gpu": ARCADE_GPU,
    "utk-gpu": UTK_GPU,
    "utk-desktop-01": DESKTOP_01,
    "utk-desktop-01, card taken": DESKTOP_01_CARD_TAKEN,
    "utk-desktop-02": DESKTOP_02,
    "utk-desktop-02, 10-28": DESKTOP_02_10_28,
}


def test_the_arcade_and_utk_gpu_runners_keep_all_six_workers():
    assert budget.budget(workers_max=6, **ARCADE_GPU)["workers"] == 6
    assert budget.budget(workers_max=6, **UTK_GPU)["workers"] == 6


def test_a_30_gb_desktop_runs_six_workers():
    # 27.3 GiB: 2 reserved, 8 for the first worker, 2.5 for each further one.
    assert budget.workers_held(**DESKTOP_01) == 7
    assert budget.budget(workers_max=6, **DESKTOP_01)["workers"] == 6


def test_a_card_with_little_free_video_memory_holds_fewer_workers():
    assert budget.workers_held(**DESKTOP_01_CARD_TAKEN) == 1


def test_a_12_gb_desktop_holds_one_worker():
    assert budget.workers_held(**DESKTOP_02) == 1


def test_a_runner_that_holds_one_worker_runs_it_beside_a_second_shard():
    # test_shard_isolation_e2e needs a second shard, or it runs in no job, but
    # the shard needs no worker of its own.
    assert budget.MIN_SHARDS == 2
    for runner in (DESKTOP_02, DESKTOP_02_10_28, DESKTOP_01_CARD_TAKEN):
        chosen = budget.budget(workers_max=6, **runner)
        assert (chosen["workers"], chosen["shards"]) == (1, 2)
    # The 10-28 job: one worker, and 7.6 GiB for the container where two got 6.1.
    assert budget.budget(workers_max=6, **DESKTOP_02_10_28)["limit"] == (6283 + 5 * 1024 - 2048 - 1536) * MIB
    # A maximum below the shards still wins: asking for one worker is asking
    # for one, and the second shard still runs.
    chosen = budget.budget(workers_max=1, **ARCADE_GPU)
    assert (chosen["workers"], chosen["shards"]) == (1, 2)
    # Where several workers fit, every shard has its worker.
    assert budget.budget(workers_max=6, **DESKTOP_01)["shards"] == 6


@pytest.mark.parametrize("name", list(RUNNERS))
def test_no_runner_runs_more_workers_than_its_memory_and_video_memory_hold(name):
    # On 10-28 utk-desktop-02 held one and ran two; with its card taken,
    # utk-desktop-01 would run two Chromes on video memory for one.
    runner = RUNNERS[name]
    assert budget.budget(workers_max=6, **runner)["workers"] <= max(budget.workers_held(**runner), 1)


def _inside(workers: int) -> int:
    """What the model gives the stack of this many workers inside the
    container: each worker's share less what it holds outside."""
    first = budget.FIRST_WORKER_GIB - budget.WORKER_OUTSIDE_GIB
    further = (workers - 1) * (budget.WORKER_GIB - budget.WORKER_OUTSIDE_GIB)
    return _gib(first + further)


@pytest.mark.parametrize("name", list(RUNNERS))
def test_the_container_limit_holds_the_stacks_of_the_workers_it_runs(name):
    # On 10-28 the budget gave utk-desktop-02's two workers 6.1 GiB, where the
    # model gives their stacks 7.5. The two shards reached it (6.13 GiB at
    # 14:16:28) and the kernel killed shard 0's sandbox in example 11's PBF load.
    chosen = budget.budget(workers_max=6, **RUNNERS[name])
    assert chosen["limit"] >= _inside(chosen["workers"])


@pytest.mark.parametrize("name", list(RUNNERS))
def test_the_limit_also_holds_the_shards_no_worker_drives(name):
    chosen = budget.budget(workers_max=6, **RUNNERS[name])
    idle = chosen["shards"] - chosen["workers"]
    assert chosen["limit"] >= _inside(chosen["workers"]) + _gib(idle * budget.IDLE_SHARD_GIB)


def test_a_shard_no_worker_drives_counts_in_the_memory_one_worker_needs():
    one = budget.RESERVE_GIB + budget.FIRST_WORKER_GIB + budget.IDLE_SHARD_GIB
    assert budget.memory_needed(1) == _gib(one)
    assert budget.memory_needed(2) == _gib(one - budget.IDLE_SHARD_GIB + budget.WORKER_GIB)
    assert budget.workers_held(free=_gib(one) - 1, vram=None) == 0
    assert budget.workers_held(free=_gib(one), vram=None) == 1


def test_a_runner_without_nvidia_smi_is_sized_by_memory_alone():
    assert budget.budget(free=_gib(40), vram=None, workers_max=6)["workers"] == 6
    assert budget.workers_held(free=_gib(20), vram=None) == 5


def test_a_runner_with_almost_nothing_free_still_runs_one_worker_and_two_shards():
    chosen = budget.budget(free=_gib(3), vram=_gib(1), workers_max=6)
    assert (chosen["workers"], chosen["shards"]) == (1, budget.MIN_SHARDS)
    assert chosen["limit"] == _gib(budget.MIN_LIMIT_GIB)


def test_the_limit_leaves_the_reserve_and_what_each_worker_needs_outside():
    chosen = budget.budget(workers_max=6, **ARCADE_GPU)
    outside = 6 * _gib(budget.WORKER_OUTSIDE_GIB)
    assert chosen["limit"] == _gib(60.4) - _gib(budget.RESERVE_GIB) - outside


def test_a_stack_with_no_workers_to_size_gets_only_a_limit():
    chosen = budget.budget(free=_gib(9.5), vram=None, workers_max=None)
    assert chosen["workers"] is None
    assert chosen["limit"] == _gib(9.5 - budget.RESERVE_GIB - budget.WORKER_OUTSIDE_GIB)


def test_nothing_read_keeps_the_maximum_and_no_limit():
    assert budget.budget(free=None, vram=None, workers_max=6) == {"workers": 6, "shards": 6, "limit": None}


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


def test_the_job_gets_its_workers_and_limit_through_github_env(monkeypatch, tmp_path, capsys):
    env, summary = _size(monkeypatch, tmp_path, free=_gib(18), vram=_gib(7.2))
    # 18 GiB: 2 reserved, 8 for the first worker, 2.5 for each of three more.
    limit_mib = (_gib(18) - _gib(budget.RESERVE_GIB) - 4 * _gib(budget.WORKER_OUTSIDE_GIB)) // budget.MIB
    # No CURIO_E2E_SHARDS: under xdist pytest counts the shards from its
    # workers, and its controller must not take itself for a shard.
    assert env == {"CURIO_E2E_PARALLEL": "4", "CURIO_CI_MEM_LIMIT": f"{limit_mib}m"}
    assert "e2e workers: 4 of at most 6" in summary
    assert "::warning::" not in capsys.readouterr().out


def test_a_runner_that_holds_one_worker_gets_one_and_a_second_shard(monkeypatch, tmp_path, capsys):
    env, summary = _size(monkeypatch, tmp_path, **DESKTOP_02_10_28)
    assert env == {"CURIO_E2E_PARALLEL": "1", "CURIO_E2E_SHARDS": "2",
                   "CURIO_CI_MEM_LIMIT": f"{6283 + 5 * 1024 - 2048 - 1536}m"}
    assert "backend and sandbox pairs: 2, 1 of them for test_shard_isolation_e2e alone" in summary
    assert "::warning::" not in capsys.readouterr().out


def test_a_runner_that_holds_no_worker_runs_one_and_says_so(monkeypatch, tmp_path, capsys):
    env, _ = _size(monkeypatch, tmp_path, free=_gib(9.5), vram=_gib(8))
    assert (env["CURIO_E2E_PARALLEL"], env["CURIO_E2E_SHARDS"]) == ("1", "2")
    assert ("::warning::9.5 GiB free and 8.0 GiB of video memory hold no e2e worker; "
            "running 1") in capsys.readouterr().out


def test_a_serial_run_finds_the_second_shard_the_budget_starts(monkeypatch, tmp_path):
    from utk_curio.backend.tests import shards

    env, _ = _size(monkeypatch, tmp_path, **DESKTOP_02_10_28)
    assert env["CURIO_E2E_PARALLEL"] == "1"
    # test-gpu's pytest, without xdist: its base ports and the budget's lines.
    job = {"CURIO_E2E_HOST": "localhost", "CURIO_E2E_BACKEND_PORT": "5022",
           "CURIO_E2E_SANDBOX_PORT": "2020", **env}
    assert (shards.shard_count(job), shards.shard_index(job)) == (2, 0)
    assert shards.sibling_backend_urls(job) == [(1, "http://localhost:5023")]


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


# A cgroup v2 memory.events, as a container reads its own.
EVENTS = "low 0\nhigh 0\nmax 41\noom 1\noom_kill {kills}\noom_group_kill 0\n"


def test_memory_events_give_the_kills_at_the_limit():
    assert budget.oom_kills(EVENTS.format(kills=1)) == 1
    assert budget.oom_kills(EVENTS.format(kills=0)) == 0
    assert budget.oom_kills("") is None


def _kills(monkeypatch, tmp_path, events: str) -> str:
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("CURIO_CI_MEM_LIMIT", "6283m")
    monkeypatch.setattr("sys.stdin", io.StringIO(events))
    assert budget.main(["ci_memory_budget.py", "kills"]) == 0
    return summary.read_text()


def test_a_kill_at_the_limit_is_an_error_line_that_names_it(monkeypatch, tmp_path, capsys):
    # On 10-28 the test said only "Could not reach the sandbox on /execJs".
    summary = _kills(monkeypatch, tmp_path, EVENTS.format(kills=1))
    assert ("::error::The kernel killed 1 process(es) in the CI container at its "
            "6.1 GiB memory limit (memory.events oom_kill)") in capsys.readouterr().out
    assert "The kernel killed 1 process(es)" in summary


def test_no_kill_and_no_reading_give_no_error(monkeypatch, tmp_path, capsys):
    _kills(monkeypatch, tmp_path, EVENTS.format(kills=0))
    out = capsys.readouterr().out
    assert "::error::" not in out
    assert "The kernel killed no process in the CI container at its 6.1 GiB memory limit" in out
    _kills(monkeypatch, tmp_path, "")
    out = capsys.readouterr().out
    assert "::error::" not in out
    assert "No memory.events reading for the CI container" in out
