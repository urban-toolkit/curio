"""Turns among a server's runners for writing a whole image to its disk.

``scripts/ci_image_slots.py`` runs start-stack's pull, and test-gpu's image
build, in one of 8 slots: lock files in the folder every arcade runner mounts
from the server (RUNNER_SHARED_DIR), since each runner has a Docker daemon of
its own and 16 to 25 pulls of the CI image at once slowed every `docker run`
on arcade from 3 s to 13 (11-15). A job takes a free slot and holds it while
its command runs, waits for one when all are taken, goes on without one when
its wait is over, and runs at once on a runner with no such folder. The kernel
frees a slot when the process holding it ends, so a job killed mid-pull leaves
none taken, and the command itself never holds it.

Other jobs' slots are held here the way the script holds them: a lock on the
slot's file. Docker is a stand-in that logs what it is asked.
"""
from __future__ import annotations

import contextlib
import fcntl
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

#: Logs every call; a pull fails when FAKE_PULL_FAILS is set, and image
#: inspect answers a size.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$1" in
  pull) [ -z "${FAKE_PULL_FAILS:-}" ] || exit 1 ;;
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


def test_a_free_slot_is_taken_and_held_while_the_command_runs(tmp_path):
    result, _ = _run(["run", sys.executable, "-c", PROBE, str(tmp_path)], _env(tmp_path))
    assert result.returncode == 0, result.stderr
    assert "image slot 1 of 8 taken after 0 s\n" in result.stdout
    assert "taken 1\n" in result.stdout
    _free(_hold(tmp_path, SLOTS))


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


def test_no_wait_takes_a_free_slot_or_goes_on_at_once(tmp_path):
    held = _hold(tmp_path, [1, 2, 4, 5, 6, 7, 8])
    try:
        result, _ = _run(["run", "--no-wait", sys.executable, "-c", PROBE, str(tmp_path)],
                         _env(tmp_path, wait_s=600))
        assert "image slot 3 of 8 taken after 0 s\n" in result.stdout
        assert "taken 1 2 3 4 5 6 7 8\n" in result.stdout
        held += _hold(tmp_path, [3])
        # With every slot taken it goes on at once: a wait of 600 s would
        # outlast the run's timeout.
        result, _ = _run(["run", "--no-wait", "sh", "-c", "echo ran"], _env(tmp_path, wait_s=600))
    finally:
        _free(held)
    assert result.returncode == 0, result.stderr
    assert "image slots: all 8 are taken, and this never waits, so it goes on without one\n" in result.stdout
    assert "::warning::" not in result.stdout
    assert result.stdout.endswith("ran\n")


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
        _wait_for(out, "image slot 1 of 8 taken after 0 s\n")
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
    pulled = re.search(r"^Pulled in (\d+) s, 6670989293 bytes on this daemon$", result.stdout, re.M)
    assert pulled, result.stdout
    assert int(pulled.group(1)) < 3 <= took


def test_a_failed_pull_fails_the_job_and_names_no_size(tmp_path):
    path, log = _docker(tmp_path)
    result, _ = _run(["pull", IMAGE], _env(tmp_path, PATH=path, DOCKER_LOG=str(log), FAKE_PULL_FAILS="1"))
    assert result.returncode == 1
    assert "Pulled in" not in result.stdout
    assert log.read_text().splitlines() == [f"pull --quiet {IMAGE}"]


@pytest.mark.parametrize("args", [[], ["pull"], ["pull", IMAGE, "more"], ["run"], ["run", "--no-wait"],
                                  ["push", IMAGE]])
def test_a_call_it_does_not_know_says_how_to_call_it(tmp_path, args):
    result, _ = _run(args, _env(tmp_path))
    assert result.returncode == 2
    assert result.stderr.startswith("usage: ci_image_slots.py pull <image> | run [--no-wait]")
    assert not list(tmp_path.iterdir())
