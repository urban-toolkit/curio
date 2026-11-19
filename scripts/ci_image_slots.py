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
    python3 scripts/ci_image_slots.py run <command> [<argument>...]

pull is the CI image's pull, start-stack's, test-desktop-stress's and that of
build-image's collection on a filtered run: `docker pull --quiet <image>` in a
slot, tried up to PULL_ATTEMPTS times. On 11-17 GitHub's registry reset two
pulls of one run 5 s apart (run 44017255256), and each lost its job before any
test ran. A failed attempt says why as a warning, with the last line docker
printed, and the next attempt comes PULL_WAITS_S later; the job fails only
when every attempt failed, with the last one's exit status and a line that
names the attempts. The retries keep the slot: the pull is still that runner's
turn, and a slot given back could keep the next attempt waiting up to WAIT_S
for another. Once it has the image, pull says how long the pull took from its
first attempt, the wait for the slot left out, the image's size and the
attempt that pulled it: "Pulled in N s, B bytes on this daemon, at attempt K
of 3".

run runs any command in a slot, once, and exits as the command does.
test-gpu's image build takes no slot: it would hold one for its 2 to 4
minutes, though a build from the runner's cache writes only its new layers,
and replayed with the builds holding slots, the last CPU job of a run got its
image 60 s later instead of 28 (median, 11-15).

A job waits for a slot at most WAIT_S, then goes on without one, so a slot
never holds a job up longer than that. A slot is a lock that the kernel frees
when the process holding it ends: a job cancelled or killed mid-pull leaves
none taken, and the command run in a slot does not hold it. Where the runner
names no shared folder (GitHub-hosted runners, utk-gpu, the utk-desktop
runners, an arcade runner made before the folder), the command runs at once,
as before. CURIO_CI_SLOT_WAIT_S sets another wait for a slot, and the tests
replace pause, the wait between a pull's attempts.
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
#: Attempts at a pull before the job fails, and the waits before the second
#: and the third: 40 s at most, where a job lost to one reset ran again only
#: when someone re-ran it by hand.
PULL_ATTEMPTS = 3
PULL_WAITS_S = (10, 30)

USAGE = "usage: ci_image_slots.py pull <image> | run <command> [<argument>...]"


def say(line: str) -> None:
    print(line, flush=True)


def pause(seconds: float) -> None:
    """The wait before a pull's next attempt."""
    time.sleep(seconds)


def exit_status(code: int) -> int:
    """A process's exit status as a shell gives it: 128 and the signal's
    number for one that a signal ended."""
    return 128 - code if code < 0 else code


def last_line(output: str) -> str:
    """The last line of a command's output that holds more than spaces."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "(no output)"


def pull(command: list[str]) -> tuple[int, int]:
    """Run the pull up to PULL_ATTEMPTS times, until one works: the last
    attempt's exit status and its number. All that docker prints goes to the
    job's log, as it does without retries."""
    attempt = 1
    while True:
        done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              errors="replace", check=False)
        if done.stdout:
            sys.stdout.write(done.stdout if done.stdout.endswith("\n") else done.stdout + "\n")
            sys.stdout.flush()
        code = exit_status(done.returncode)
        if code == 0:
            return 0, attempt
        why = f"with exit {code}: {last_line(done.stdout)}"
        if attempt == PULL_ATTEMPTS:
            say(f"::error::docker pull failed at all {PULL_ATTEMPTS} attempts, the last {why}")
            return code, attempt
        wait = PULL_WAITS_S[attempt - 1]
        say(f"::warning::docker pull failed at attempt {attempt} of {PULL_ATTEMPTS}, {why}; "
            f"trying again in {wait} s")
        pause(wait)
        attempt += 1


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
            say(f"::warning::image slots: all {SLOTS} in {folder} stayed taken for {wait_s:.0f} s, "
                "so this goes on without one")
            return None
        if not said_waiting:
            say(f"image slots: all {SLOTS} are taken; waiting up to {wait_s:.0f} s for one")
            said_waiting = True
        time.sleep(POLL_S)


def main(argv: list[str]) -> int:
    mode, rest = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if mode == "pull" and len(rest) == 1:
        command = ["docker", "pull", "--quiet", rest[0]]
    elif mode == "run" and rest:
        command = rest
    else:
        print(USAGE, file=sys.stderr)
        return 2
    fd = take(float(os.environ.get("CURIO_CI_SLOT_WAIT_S") or WAIT_S))
    started = time.monotonic()
    attempt = 1
    try:
        if mode == "pull":
            # Every attempt in the one slot: the pull is still this runner's turn.
            code, attempt = pull(command)
        else:
            code = exit_status(subprocess.run(command, check=False).returncode)
    finally:
        if fd is not None:
            os.close(fd)
    took = time.monotonic() - started
    if mode == "pull" and code == 0:
        size = subprocess.run(["docker", "image", "inspect", "--format", "{{.Size}}", rest[0]],
                              capture_output=True, text=True, check=False).stdout.strip()
        say(f"Pulled in {took:.0f} s, {size} bytes on this daemon, at attempt {attempt} of {PULL_ATTEMPTS}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
