"""Choosing the runner for each job of a CI run.

``scripts/ci_pick_runners.py`` runs as the first job of the Full stack build, and
again as build-image's last step for the jobs that wait on the image. It
writes the ``runs-on`` of the CPU jobs (GitHub-hosted first, then arcade, then
the utk-desktop runners) and the GPU job (the arcade GPU pool first, then utk,
then the utk-desktop runners). A wrong answer sends jobs to a pool
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


def _utk(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "gpu", "curio"], "utk-gpu" if status == "in_progress" else None, age_s)


def _desktop(status="in_progress", age_s=0, runner="utk-desktop-02"):
    return _job(status, ["self-hosted", "desktop"], runner if status == "in_progress" else None, age_s)


def _desktop_gpu(status="in_progress", age_s=0):
    return _job(status, ["self-hosted", "gpu", "desktop"], "utk-desktop-01" if status == "in_progress" else None,
                age_s)


def _full_hosted_and_arcade():
    return ([_hosted("queued", age_s=picker.HOSTED_FULL_AFTER_S + 30)]
            + [_arcade() for _ in range(picker.CPU_RUNNERS)])


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


def test_cpu_jobs_past_hosted_and_arcade_go_to_a_free_desktop_and_then_wait_on_arcade():
    chosen = picker.assign_cpu(CPU, 1, free_arcade=1, free_desktop=2)
    assert [chosen[k] for k in CPU] == ["hosted", "arcade", "desktop", "desktop", "arcade"]


def test_the_gpu_job_goes_to_a_desktop_only_when_arcade_and_utk_are_busy():
    keys = ["a", "b", "c", "d"]
    chosen = picker.assign_gpu(keys, 1, free_utk=1, free_desktop_gpu=1)
    assert [chosen[k] for k in keys] == ["arcade-gpu", "utk", "desktop-gpu", "utk"]
    # With the desktops busy as well, the job waits on utk, as before.
    assert picker.assign_gpu(GPU, 0, free_utk=0, free_desktop_gpu=0) == {"test-gpu": "utk"}


def test_both_desktops_take_the_gpu_job():
    assert picker.GPU_DESKTOPS == ("utk-desktop-01", "utk-desktop-02")
    assert picker.DESKTOP_GPU_RUNNERS == picker.DESKTOP_RUNNERS == 2


def test_forced_desktop_pools_take_every_job():
    assert set(picker.assign_cpu(CPU, 20, "desktop").values()) == {"desktop"}
    assert picker.assign_gpu(GPU, picker.GPU_RUNNERS, "desktop") == {"test-gpu": "desktop-gpu"}


def test_desktop_jobs_are_counted_against_the_desktops_not_arcade():
    jobs = [_desktop(), _desktop("queued"), _desktop_gpu(),
            # A job's labels can be missing; the runner's name still places it.
            _job("in_progress", [], "utk-desktop-02")]
    counts = picker.busy(jobs, NOW)
    assert (counts["desktop"], counts["desktop-gpu"], counts["arcade"], counts["utk"]) == (3, 1, 0, 0)
    assert counts["desktop_stuck"] is False


def test_each_desktop_takes_one_job_of_either_kind():
    def room(jobs):
        return picker.desktop_room(picker.busy(jobs, NOW))

    assert room([]) == (2, 2)
    # One CPU job holds one desktop, whichever it runs on; the other takes either kind.
    assert room([_desktop()]) == (1, 1)
    assert room([_desktop(runner="utk-desktop-01")]) == (1, 1)
    # A queued one has no desktop yet, but will hold one.
    assert room([_desktop("queued")]) == (1, 1)
    # Two CPU jobs hold both desktops.
    assert room([_desktop(), _desktop(runner="utk-desktop-01")]) == (0, 0)
    # The GPU job holds one desktop; the other can take a CPU job or another GPU job.
    assert room([_desktop_gpu()]) == (1, 1)
    assert room([_desktop_gpu(), _desktop()]) == (0, 0)


def test_the_desktops_are_stuck_only_while_one_should_be_free():
    queued = _desktop("queued", age_s=picker.STUCK_AFTER_S + 60)
    # One desktop runs a job, yet the queued one waits: the other is asleep or off.
    assert picker.busy([_desktop(), queued], NOW)["desktop_stuck"] is True
    assert picker.desktop_room(picker.busy([_desktop(), queued], NOW)) == (0, 0)
    # Both run a job: the queued one is just waiting its turn.
    assert picker.busy([_desktop(), _desktop_gpu(), queued], NOW)["desktop_stuck"] is False
    # The GPU job can take either desktop: queued that long while one of them
    # runs nothing, the desktops are not taking jobs; with both busy it waits.
    queued_gpu = _desktop_gpu("queued", age_s=picker.STUCK_AFTER_S + 60)
    assert picker.busy([_desktop(runner="utk-desktop-01"), queued_gpu], NOW)["desktop_stuck"] is True
    both_busy = [_desktop(runner="utk-desktop-01"), _desktop(runner="utk-desktop-02"), queued_gpu]
    assert picker.busy(both_busy, NOW)["desktop_stuck"] is False
    assert picker.busy([queued_gpu], NOW)["desktop_stuck"] is True


def test_with_hosted_and_arcade_full_the_desktops_take_the_next_jobs():
    jobs = _full_hosted_and_arcade() + [_arcade_gpu() for _ in range(picker.GPU_RUNNERS)] + [_utk()]
    chosen, how = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    # arcade's GPU runners and utk-gpu are busy, so test-gpu takes a desktop,
    # and the other desktop takes the first CPU job; the rest wait on arcade.
    assert chosen["test-gpu"] == "desktop-gpu"
    assert [chosen[k] for k in CPU] == ["desktop", "arcade", "arcade", "arcade", "arcade"]
    assert any("hosted limit" in line and "2 of 2" in line for line in how)
    assert any("then the desktops, 2 of 2 free" in line for line in how)


def test_with_utk_gpu_free_the_gpu_job_goes_there_and_not_to_a_desktop():
    jobs = [_arcade_gpu() for _ in range(picker.GPU_RUNNERS)]
    chosen, _ = picker.pick(CPU, GPU, "auto", "auto", lambda: jobs)
    assert chosen["test-gpu"] == "utk"


def test_stuck_desktops_get_no_jobs():
    jobs = _full_hosted_and_arcade() + [_desktop("queued", age_s=picker.STUCK_AFTER_S + 60)]
    chosen, how = picker.pick(CPU, [], "auto", "auto", lambda: jobs)
    assert {chosen[k] for k in CPU} == {"arcade"}
    assert any(line.startswith("No job goes to the desktops") for line in how)


def test_main_writes_the_desktops_runs_on_values(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CURIO_CI_POOL", "desktop")
    monkeypatch.setenv("CURIO_CI_GPU_POOL", "Desktop")
    assert picker.main(["ci_pick_runners.py", "--gpu", "test-gpu", *CPU]) == 0
    runners = json.loads(out.read_text().strip().removeprefix("runners="))
    assert runners == {"test-gpu": ["self-hosted", "gpu", "desktop"], **{k: ["self-hosted", "desktop"] for k in CPU}}


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


# build-image's pick, made when the jobs that wait on the image are about to start.
LATE = ["e2e-desktop-1", "e2e-desktop-2", "unit-backend-1", "test-isolated", "test-exec-user"]
THIS_RUN, OTHER_RUN = 101, 202


def _in_run(run_id, name, job):
    return {**job, "run_id": run_id, "name": name}


def _serve(monkeypatch, runs):
    """The GitHub API, answering with these in-progress runs and their jobs."""
    def get(url, token):
        if "/jobs?" in url:
            return {"jobs": runs[int(url.split("/runs/")[1].split("/")[0])]}
        return {"workflow_runs": [{"id": run_id} for run_id in runs] if "status=in_progress" in url else []}

    monkeypatch.setattr(picker, "_get", get)


def _both_runs():
    return {
        THIS_RUN: [_in_run(THIS_RUN, "pick-runners", _hosted("completed")),
                   _in_run(THIS_RUN, "build-image", _hosted()),
                   _in_run(THIS_RUN, "jest", _hosted()),
                   _in_run(THIS_RUN, "test-gpu", _arcade_gpu())],
        OTHER_RUN: [_in_run(OTHER_RUN, "build-image", _hosted()),
                    _in_run(OTHER_RUN, "e2e-desktop (1)", _arcade())],
    }


def _listed(jobs):
    return [(job["run_id"], job["name"]) for job in jobs]


def test_by_default_a_pick_leaves_out_every_job_of_its_own_run(monkeypatch):
    _serve(monkeypatch, _both_runs())
    jobs = picker.active_jobs("https://api.github.com", "urban-toolkit/curio", "unused", str(THIS_RUN))
    assert _listed(jobs) == [(OTHER_RUN, "build-image"), (OTHER_RUN, "e2e-desktop (1)")]


def test_this_run_except_counts_this_run_s_jobs_but_the_named_one_and_only_in_this_run(monkeypatch):
    _serve(monkeypatch, _both_runs())
    jobs = picker.active_jobs("https://api.github.com", "urban-toolkit/curio", "unused", str(THIS_RUN),
                              "build-image")
    # This run's build-image ends with the pick. The other run's is still
    # building and holds its runner, so it counts.
    assert _listed(jobs) == [(THIS_RUN, "pick-runners"), (THIS_RUN, "jest"), (THIS_RUN, "test-gpu"),
                             (OTHER_RUN, "build-image"), (OTHER_RUN, "e2e-desktop (1)")]


def test_the_late_pick_leaves_the_hosted_room_this_run_s_running_jobs_hold(monkeypatch):
    other = [_in_run(OTHER_RUN, f"e2e-desktop ({i})", _hosted()) for i in range(1, 16)]
    mine = [_in_run(THIS_RUN, "build-image", _hosted()), _in_run(THIS_RUN, "jest", _hosted()),
            _in_run(THIS_RUN, "test-gpu", _arcade_gpu())]
    _serve(monkeypatch, {THIS_RUN: mine, OTHER_RUN: other})

    def fetch():
        return picker.active_jobs("https://api.github.com", "urban-toolkit/curio", "unused", str(THIS_RUN),
                                  "build-image")

    chosen, how = picker.pick(LATE, [], "auto", "auto", fetch, hosted_reserved=2)
    # 20 slots: 15 held by the other run, 1 by this run's jest, 2 kept for
    # unit (sandbox) and test-desktop-stress, which do not exist yet.
    assert [chosen[k] for k in LATE] == ["hosted", "hosted", "arcade", "arcade", "arcade"]
    assert any("2 of 20" in line for line in how)
    # No GPU job in this pick, so nothing is said about the GPU pools.
    assert not any(line.startswith("GPU") for line in how)


def test_main_hands_this_run_except_to_the_jobs_count(tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(picker, "active_jobs", lambda *a: seen.append(a) or [])
    monkeypatch.delenv("CURIO_CI_POOL", raising=False)
    monkeypatch.delenv("CURIO_CI_GPU_POOL", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "urban-toolkit/curio")
    monkeypatch.setenv("GITHUB_TOKEN", "unused")
    monkeypatch.setenv("GITHUB_RUN_ID", str(THIS_RUN))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "early"))
    assert picker.main(["ci_pick_runners.py", "--hosted-reserved", "1", "--gpu", "test-gpu", "jest"]) == 0
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "late"))
    assert picker.main(["ci_pick_runners.py", "--this-run-except", "build-image", "--hosted-reserved", "2",
                        *LATE]) == 0
    assert [call[3:] for call in seen] == [(str(THIS_RUN), None), (str(THIS_RUN), "build-image")]
    assert "except build-image" in capsys.readouterr().out
    runners = json.loads((tmp_path / "late").read_text().strip().removeprefix("runners="))
    assert runners == {key: "ubuntu-latest" for key in LATE}
