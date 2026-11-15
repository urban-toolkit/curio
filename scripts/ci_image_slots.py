"""Turns, among the runners of a server, for writing a whole image to its disk.

Each arcade runner is a container with a Docker daemon of its own
(uic-evl/evl-github-runners), so each of a run's jobs pulls the CI image
itself, and every pull writes its 6.7 GB to the one disk all of arcade's
runners share. On 11-15 a run's 16 to 25 pulls at once made a `docker run`
anywhere on arcade take 13 s instead of 3 (26 s at worst); on 11-09, beside
three image builds, 166 s, and a test's synced write waited 27 s. Every runner
there mounts one folder of the server's and names it to its jobs as
RUNNER_SHARED_DIR. In it, SLOTS lock files let only that many such writes run
at once on the server, whatever run they belong to: a job takes a free slot,
or waits for one.

    python3 scripts/ci_image_slots.py pull <image>
    python3 scripts/ci_image_slots.py run [--no-wait] <command> [<argument>...]

pull is start-stack's `docker pull --quiet <image>` in a slot. It then says how
long the pull took, the wait for the slot left out, and the image's size:
"Pulled in N s, B bytes on this daemon". run runs any command in a slot and
exits as the command does. With --no-wait it takes a slot only when one is free
at once, and otherwise goes on without one: test-gpu's image build starts with
its run and is the run's longest job, so it never waits for CPU jobs' pulls.

A job waits for a slot at most WAIT_S, then goes on without one, so a slot
never holds a job up longer than that. A slot is a lock that the kernel frees
when the process holding it ends: a job cancelled or killed mid-pull leaves
none taken, and the command run in a slot does not hold it. Where the runner
names no shared folder (GitHub-hosted runners, utk-gpu, the utk-desktop
runners, an arcade runner made before the folder), the command runs at once,
as before. CURIO_CI_SLOT_WAIT_S sets another wait (tests).
"""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
import sys
import time

#: Whole images written to one server's disk at once, by all of its runs. With
#: 9 or fewer pulls at once on arcade (11-15), a pull took 46 to 54 s and a
#: `docker run` 2 to 5 s; with 16 to 25, 68 s and 13 s (26 at worst).
#: Replayed with 8 slots, that day's 270 pulls never ran more than 8 at once
#: (34 had), and the last image of a run of ten pulls or more came 28 s later
#: (median, 65 s at most). With 6 it came 72 s later; with 10 to 15 pulls at
#: once, image-env's helper container took 2.3 s to start against 0.9.
SLOTS = 8
#: How long a job waits for a slot before it goes on without one: about five
#: turns of a 48 s pull. In the replays of 11-09 and 11-15 with 8 slots, no
#: pull waited more than 101 s.
WAIT_S = 240
#: How often a waiting job looks for a free slot.
POLL_S = 1.0

USAGE = "usage: ci_image_slots.py pull <image> | run [--no-wait] <command> [<argument>...]"


def say(line: str) -> None:
    print(line, flush=True)


def try_slots(folder: str) -> tuple[int, int] | None:
    """The first free slot, now held: its number and the file descriptor
    holding it, which frees it when closed. None when every slot is taken.
    Raises OSError when the folder holds no locks for this job."""
    for number in range(1, SLOTS + 1):
        fd = os.open(os.path.join(folder, f"image-slot-{number}"), os.O_RDONLY | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                continue
            raise
        return number, fd
    return None


def take(wait_s: float) -> int | None:
    """Hold a slot, waiting up to wait_s for one, and say which: the file
    descriptor holding it, or None when the job goes on without one."""
    folder = os.environ.get("RUNNER_SHARED_DIR", "")
    if not folder or not os.path.isdir(folder):
        say("image slots: this runner shares no folder with other runners (RUNNER_SHARED_DIR), "
            "so it goes on at once")
        return None
    started = time.monotonic()
    said_waiting = False
    while True:
        try:
            held = try_slots(folder)
        except OSError as exc:
            say(f"::warning::image slots: no lock could be taken in {folder} ({exc}), "
                "so this goes on without a slot")
            return None
        waited = time.monotonic() - started
        if held is not None:
            number, fd = held
            say(f"image slot {number} of {SLOTS} taken after {waited:.0f} s")
            return fd
        if waited >= wait_s:
            if wait_s > 0:
                say(f"::warning::image slots: all {SLOTS} in {folder} stayed taken for {wait_s:.0f} s, "
                    "so this goes on without one")
            else:
                say(f"image slots: all {SLOTS} are taken, and this never waits, so it goes on without one")
            return None
        if not said_waiting:
            say(f"image slots: all {SLOTS} are taken; waiting up to {wait_s:.0f} s for one")
            said_waiting = True
        time.sleep(POLL_S)


def main(argv: list[str]) -> int:
    mode, rest = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    no_wait = mode == "run" and rest[:1] == ["--no-wait"]
    if no_wait:
        rest = rest[1:]
    if mode == "pull" and len(rest) == 1:
        command = ["docker", "pull", "--quiet", rest[0]]
    elif mode == "run" and rest:
        command = rest
    else:
        print(USAGE, file=sys.stderr)
        return 2
    fd = take(0.0 if no_wait else float(os.environ.get("CURIO_CI_SLOT_WAIT_S") or WAIT_S))
    started = time.monotonic()
    try:
        code = subprocess.run(command, check=False).returncode
    finally:
        if fd is not None:
            os.close(fd)
    took = time.monotonic() - started
    if code < 0:
        # Ended by a signal, which a shell reports as 128 and its number.
        code = 128 - code
    if mode == "pull" and code == 0:
        size = subprocess.run(["docker", "image", "inspect", "--format", "{{.Size}}", rest[0]],
                              capture_output=True, text=True, check=False).stdout.strip()
        say(f"Pulled in {took:.0f} s, {size} bytes on this daemon")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
