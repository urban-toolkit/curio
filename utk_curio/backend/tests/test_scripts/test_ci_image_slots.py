"""Turns among a server's runners for writing a whole image to its disk.

``scripts/ci_image_slots.py`` runs start-stack's pull in one of 8 slots: lock
files in the folder every arcade runner mounts from the server
(RUNNER_SHARED_DIR), since each runner has a Docker daemon of its own and 16
to 25 pulls of the CI image at once slowed every `docker run` on arcade from
3 s to 13 (11-15). A job takes a free slot and holds it while its command
runs, waits for one when all are taken, goes on without one when its wait is
over, and runs at once on a runner with no such folder. The kernel frees a
slot when the process holding it ends, so a job killed mid-pull leaves none
taken, and the command itself never holds it.

A failed pull is tried again, 10 s and then 30 s later, in the slot it took,
and fails the job only when all 3 attempts failed: on 11-17 GitHub's registry
reset two pulls of one run 5 s apart (run 44017255256), and each lost its job
before any test ran. The tests that run a pull in this process replace the
script's ``pause``, its one wait between attempts, so none sleeps.

Other jobs' slots are held here the way the script holds them: a lock on the
slot's file. Docker is a stand-in that logs what it is asked.
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_image_slots.py"
SLOTS = range(1, 9)
IMAGE = "ghcr.io/urban-toolkit/curio-ci:584ee988783fdb22f4468d698b42e235d0b3fb72"

#: A command run in a slot: prints the slots another job would find taken.
PROBE = (
    "import fcntl, os, sys\n"
    "taken = []\n"
    "for n in range(1, 9):\n"
    "    fd = os.open(os.path.join(sys.argv[1], f'image-slot-{n}'), os.O_RDONLY | os.O_CREAT, 0o644)\n"
    "    try:\n"
    "        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    except BlockingIOError:\n"
    "        taken.append(n)\n"
    "    os.close(fd)\n"
    "print('taken', *taken)\n"
)

#: All that docker pull printed when GitHub's registry reset e2e-desktop
#: (10)'s pull in run 44017255256. The stand-in ends the local port with the
#: pull's number, so that each attempt prints a line of its own.
RESET = "failed to copy: read tcp 10.1.0.34:5803{}->185.199.111.154:443: read: connection reset by peer"

#: Logs every call. A pull fails as that one did when FAKE_PULL_FAILS is set,
#: or while it is one of the first FAKE_FAILED_PULLS pulls; else it prints the
#: image, as `docker pull --quiet` does. image inspect answers a size.
FAKE_DOCKER = f"""#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$1" in
  pull)
    pulls=$(grep -c '^pull ' "$DOCKER_LOG")
    if [ -n "${{FAKE_PULL_FAILS:-}}" ] || [ "$pulls" -le "${{FAKE_FAILED_PULLS:-0}}" ]; then
      echo "{RESET.format('$pulls')}" >&2
      exit 1
    fi
    echo "$3" ;;
  image) echo 6670989293 ;;
esac
exit 0
"""


def _env(shared, wait_s=None, **extra):
    """The job's environment: the shared folder, if any, and the wait."""
    env = {k: v for k, v in os.environ.items() if k not in ("RUNNER_SHARED_DIR", "CURIO_CI_SLOT_WAIT_S")}
    if shared is not None:
        env["RUNNER_SHARED_DIR"] = str(shared)
    if wait_s is not None:
        env["CURIO_CI_SLOT_WAIT_S"] = str(wait_s)
    return {**env, **extra}


def _run(args, env):
    """Run the script to its end; return its result and how long it took."""
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True,
                            text=True, timeout=60)
    return result, time.monotonic() - started


def _start(args, env, out):
    """Start the script in a session of its own, its output going to ``out``."""
    with open(out, "w") as fh:
        return subprocess.Popen([sys.executable, str(SCRIPT), *args], env=env, stdout=fh,
                                stderr=subprocess.STDOUT, start_new_session=True)


def _wait_for(out, text, timeout=30.0):
    deadline = time.monotonic() + timeout
    while text not in out.read_text():
        assert time.monotonic() < deadline, f"no {text!r} in: {out.read_text()}"
        time.sleep(0.05)


def _hold(folder, numbers):
    """Take these slots as other jobs would; closing what comes back frees them."""
    fds = []
    for n in numbers:
        fd = os.open(folder / f"image-slot-{n}", os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            _free(fds)
            raise
        fds.append(fd)
    return fds


def _free(fds):
    for fd in fds:
        os.close(fd)


def _docker(tmp_path):
    """PATH with the stand-in docker first, and where it logs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return f"{bin_dir}{os.pathsep}{os.environ['PATH']}", tmp_path / "docker.log"


def _slots():
    """The script as a module, loaded anew by each test that runs it here, so
    that a copy of it with no retries fails those tests on what it does rather
    than at their collection."""
    spec = importlib.util.spec_from_file_location("_scripts_ci_image_slots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _taken(folder):
    """The slots another job would find taken now."""
    taken = []
    for n in SLOTS:
        fd = os.open(folder / f"image-slot-{n}", os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            taken.append(n)
        finally:
            os.close(fd)
    return taken


def _pull_here(tmp_path, monkeypatch, shared=None, **fake):
    """The script's pull of IMAGE, run in this process with the stand-in
    docker first on PATH and ``fake`` its settings: the script's exit status,
    the calls docker got, and each wait between attempts with the slots
    another job found taken during it. The wait is the script's ``pause``,
    replaced here; set without ``raising``, so that a script with no retries
    fails on the pulls it makes."""
    path, log = _docker(tmp_path)
    for name in ("RUNNER_SHARED_DIR", "CURIO_CI_SLOT_WAIT_S", "FAKE_PULL_FAILS", "FAKE_FAILED_PULLS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("DOCKER_LOG", str(log))
    if shared is not None:
        monkeypatch.setenv("RUNNER_SHARED_DIR", str(shared))
    for name, value in fake.items():
        monkeypatch.setenv(name, value)
    slots = _slots()
    waits = []

    def pause(seconds):
        waits.append((seconds, None if shared is None else _taken(shared)))

    monkeypatch.setattr(slots, "pause", pause, raising=False)
    code = slots.main(["ci_image_slots.py", "pull", IMAGE])
    return code, log.read_text().splitlines(), waits


def test_a_free_slot_is_taken_and_held_while_the_command_runs(tmp_path):
    result, _ = _run(["run", sys.executable, "-c", PROBE, str(tmp_path)], _env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert re.search(r"^image slot 1 of 8 taken after \d+ s$", result.stdout, re.M), result.stdout
    assert "waiting" not in result.stdout
    assert "taken 1\n" in result.stdout
    _free(_hold(tmp_path, SLOTS))


def test_a_job_takes_whichever_slot_is_free_without_waiting(tmp_path):
    held = _hold(tmp_path, [1, 2, 4, 5, 6, 7, 8])
    try:
        result, _ = _run(["run", sys.executable, "-c", PROBE, str(tmp_path)], _env(tmp_path))
    finally:
        _free(held)
    assert result.returncode == 0, result.stderr
    assert re.search(r"^image slot 3 of 8 taken after \d+ s$", result.stdout, re.M), result.stdout
    assert "waiting" not in result.stdout
    assert "taken 1 2 3 4 5 6 7 8\n" in result.stdout


def test_a_job_that_finds_every_slot_taken_waits_for_the_first_one_freed(tmp_path):
    held = _hold(tmp_path, SLOTS)
    out = tmp_path / "out.txt"
    proc = _start(["run", sys.executable, "-c", PROBE, str(tmp_path)], _env(tmp_path, wait_s=120), out)
    try:
        _wait_for(out, "image slots: all 8 are taken; waiting up to 120 s for one\n")
        time.sleep(1.5)
        assert proc.poll() is None
        assert "taken 1" not in out.read_text()
        os.close(held.pop(4))
        assert proc.wait(timeout=60) == 0
    finally:
        _free(held)
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
    text = out.read_text()
    waited = re.search(r"^image slot 5 of 8 taken after (\d+) s$", text, re.M)
    assert waited and int(waited.group(1)) >= 1, text
    # Its own slot 5 and the seven still held, seen only once it had a slot.
    assert text.index("taken 1 2 3 4 5 6 7 8\n") > waited.end()
    assert "::warning::" not in text


def test_a_job_that_finds_no_slot_within_its_wait_goes_on_without_one(tmp_path):
    held = _hold(tmp_path, SLOTS)
    try:
        result, took = _run(["run", "sh", "-c", "echo ran"], _env(tmp_path, wait_s=2))
    finally:
        _free(held)
    assert result.returncode == 0, result.stderr
    assert f"::warning::image slots: all 8 in {tmp_path} stayed taken for 2 s, so this goes on without one\n" \
        in result.stdout
    assert result.stdout.endswith("ran\n")
    assert took >= 2


@pytest.mark.parametrize("folder", [None, "missing"])
def test_a_runner_with_no_shared_folder_runs_the_command_at_once(tmp_path, folder):
    shared = None if folder is None else tmp_path / folder
    result, _ = _run(["run", "sh", "-c", "echo ran"], _env(shared, wait_s=600))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("image slots: this runner shares no folder with other runners "
                             "(RUNNER_SHARED_DIR), so it goes on at once\nran\n")
    assert not (tmp_path / "missing").exists()


def test_the_job_exits_as_its_command_does_and_its_slot_is_free_after(tmp_path):
    result, _ = _run(["run", "sh", "-c", "exit 3"], _env(tmp_path))
    assert result.returncode == 3
    _free(_hold(tmp_path, SLOTS))


def test_a_killed_job_leaves_its_slot_free_and_its_command_never_held_it(tmp_path):
    out = tmp_path / "out.txt"
    proc = _start(["run", "sleep", "60"], _env(tmp_path), out)
    try:
        _wait_for(out, "image slot 1 of 8 taken after ")
        with pytest.raises(BlockingIOError):
            _hold(tmp_path, [1])
        # The script alone, as a runner's kill of a cancelled job can leave
        # the command running: the slot is free at once.
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
        _free(_hold(tmp_path, [1]))
    finally:
        # The command left running, or whatever is left of the session.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)


def test_pull_pulls_in_a_slot_and_its_seconds_leave_the_wait_out(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    path, log = _docker(tmp_path)
    held = _hold(shared, SLOTS)
    try:
        result, took = _run(["pull", IMAGE], _env(shared, wait_s=3, PATH=path, DOCKER_LOG=str(log)))
    finally:
        _free(held)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [f"pull --quiet {IMAGE}", f"image inspect --format {{{{.Size}}}} {IMAGE}"]
    pulled = re.search(r"^Pulled in (\d+) s, 6670989293 bytes on this daemon, at attempt 1 of 3$",
                       result.stdout, re.M)
    assert pulled, result.stdout
    assert int(pulled.group(1)) < 3 <= took


def test_a_pull_the_registry_resets_is_tried_again_10_s_later_in_its_slot(tmp_path, monkeypatch, capfd):
    shared = tmp_path / "shared"
    shared.mkdir()
    code, calls, waits = _pull_here(tmp_path, monkeypatch, shared, FAKE_FAILED_PULLS="1")
    out, err = capfd.readouterr()
    assert code == 0, out + err
    assert calls == [f"pull --quiet {IMAGE}"] * 2 + [f"image inspect --format {{{{.Size}}}} {IMAGE}"]
    # The slot stayed held through the wait: the retry is still this runner's turn.
    assert waits == [(10, [1])], out + err
    # docker's own line, then why the attempt failed, then the second attempt's pull.
    assert re.fullmatch(
        r"image slot 1 of 8 taken after \d+ s\n"
        + re.escape(f"{RESET.format(1)}\n"
                    f"::warning::docker pull failed at attempt 1 of 3, with exit 1: {RESET.format(1)}; "
                    f"trying again in 10 s\n"
                    f"{IMAGE}\n")
        + r"Pulled in \d+ s, 6670989293 bytes on this daemon, at attempt 2 of 3\n",
        out,
    ), out + err
    assert err == ""
    _free(_hold(shared, SLOTS))


def test_a_pull_that_fails_at_every_attempt_fails_the_job_and_names_no_size(tmp_path, monkeypatch, capfd):
    code, calls, waits = _pull_here(tmp_path, monkeypatch, tmp_path, FAKE_PULL_FAILS="1")
    out, err = capfd.readouterr()
    assert code == 1, out + err
    assert "Pulled in" not in out
    # 3 pulls, 10 s and then 30 s apart, all in the job's slot, and no size asked for.
    assert calls == [f"pull --quiet {IMAGE}"] * 3, out + err
    assert waits == [(10, [1]), (30, [1])], out + err
    # Each attempt's own last line, then the job's failure, which names the attempts.
    failed = "".join(
        f"{RESET.format(n)}\n"
        f"::warning::docker pull failed at attempt {n} of 3, with exit 1: {RESET.format(n)}; "
        f"trying again in {wait} s\n"
        for n, wait in ((1, 10), (2, 30))
    )
    last = (f"{RESET.format(3)}\n"
            f"::error::docker pull failed at all 3 attempts, the last with exit 1: {RESET.format(3)}\n")
    assert re.fullmatch(r"image slot 1 of 8 taken after \d+ s\n" + re.escape(failed + last), out), out + err
    assert err == ""
    _free(_hold(tmp_path, SLOTS))


def test_a_pull_that_works_at_once_is_one_attempt_and_says_so(tmp_path, monkeypatch, capfd):
    # A runner that shares no folder, as GitHub-hosted ones (test-desktop-stress's) do.
    code, calls, waits = _pull_here(tmp_path, monkeypatch)
    out, err = capfd.readouterr()
    assert code == 0, out + err
    assert calls == [f"pull --quiet {IMAGE}", f"image inspect --format {{{{.Size}}}} {IMAGE}"]
    assert waits == []
    assert re.fullmatch(
        re.escape("image slots: this runner shares no folder with other runners (RUNNER_SHARED_DIR), "
                  f"so it goes on at once\n{IMAGE}\n")
        + r"Pulled in \d+ s, 6670989293 bytes on this daemon, at attempt 1 of 3\n",
        out,
    ), out + err
    assert err == ""


@pytest.mark.parametrize("args", [[], ["pull"], ["pull", IMAGE, "more"], ["run"], ["push", IMAGE]])
def test_a_call_it_does_not_know_says_how_to_call_it(tmp_path, args):
    result, _ = _run(args, _env(tmp_path))
    assert result.returncode == 2
    assert result.stderr.startswith("usage: ci_image_slots.py pull <image> | run <command>")
    assert not list(tmp_path.iterdir())
