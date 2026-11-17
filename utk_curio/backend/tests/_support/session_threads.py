"""The onnxruntime sessions a piece of Curio's code makes, read from a child of its own.

onnxruntime reads no ``OMP_NUM_THREADS``: a session that names no thread count
starts a thread for every core it sees. An arcade CI runner shows the 192 CPUs
of a machine its 44 runners share, so a session there ran on 96 threads beside
every other job's (run 44027626125, where example 10's Image Segmentation took
129 s against 11 s on a quiet runner). The CI stacks give node code their
runner's share as ``OMP_NUM_THREADS``, which torch and OpenBLAS read for
themselves, so the code that makes a session hands that count to onnxruntime.
With no ``OMP_NUM_THREADS``, as on a user's Curio, the session keeps
onnxruntime's own choice, a thread per core.

A test hands :func:`sessions_made` a script that makes a session the way the
code under test makes it. The script runs in a child whose ``OMP_NUM_THREADS``
is the test's, after :data:`RECORD_SESSIONS`, and
:func:`assert_the_session_takes_the_named_count` holds what the children said
to the rule above.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

#: What a child runs before a test's script. Every onnxruntime session made
#: after it is listed in ``SESSIONS``: the intra-op thread count it was made
#: with (0 is onnxruntime's own choice), and how many threads the process had
#: gained, from before the session was made to the end of its runs (Linux lists
#: a process's threads in /proc/self/task). The script ends with
#: ``report(...)``, which prints them with the CPUs the child sees and what the
#: script adds.
RECORD_SESSIONS = """
import json
import os

import onnxruntime

SESSIONS = []


def _threads():
    return len(os.listdir("/proc/self/task"))


class _Recorded(onnxruntime.InferenceSession):
    def __init__(self, *args, **kwargs):
        before = _threads()
        super().__init__(*args, **kwargs)
        self._threads_before = before
        self._seen = {
            "intra_op": self.get_session_options().intra_op_num_threads,
            "added": _threads() - before,
        }
        SESSIONS.append(self._seen)

    def run(self, *args, **kwargs):
        answer = super().run(*args, **kwargs)
        self._seen["added"] = max(self._seen["added"], _threads() - self._threads_before)
        return answer


onnxruntime.InferenceSession = _Recorded


def report(**more):
    print("RESULT " + json.dumps({"sessions": SESSIONS, "cpus": os.cpu_count(), **more}))
"""


def sessions_made(script: str, *args, omp_num_threads: str | None, timeout: int = 600) -> dict:
    """What *script* reports, run on *args* after :data:`RECORD_SESSIONS` in a
    child whose ``OMP_NUM_THREADS`` is *omp_num_threads*, unset when None:
    ``{"sessions": [{"intra_op", "added"}], "cpus", ...}``. The child starts
    in the repository's root with it on its path, as the suites do, and writes
    no bytecode."""
    assert platform.system() == "Linux", (
        f"This test counts a child's threads in /proc/self/task, which Linux has; this machine is {platform.system()}."
    )
    env = {name: value for name, value in os.environ.items() if name != "OMP_NUM_THREADS"}
    if omp_num_threads is not None:
        env["OMP_NUM_THREADS"] = omp_num_threads
    env["PYTHONPATH"] = os.pathsep.join(path for path in (str(REPO), env.get("PYTHONPATH")) if path)
    done = subprocess.run(
        [sys.executable, "-B", "-c", RECORD_SESSIONS + script, *(str(arg) for arg in args)],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=timeout,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert done.returncode == 0 and lines, (
        f"the child exited {done.returncode} and reported nothing:\n{done.stdout[-1000:]}\n{done.stderr[-3000:]}"
    )
    return json.loads(lines[-1][len("RESULT "):])


def assert_the_session_takes_the_named_count(made, session: str) -> dict:
    """Hold the one session *made* makes to the count ``OMP_NUM_THREADS`` names.

    *made(omp_num_threads)* is :func:`sessions_made` for the code under test,
    and *session* names its session in a sentence. Under ``OMP_NUM_THREADS=1``
    the session runs on the calling thread alone, which starts no thread, on
    any machine of more than one core; under ``2,1``, a count for each level of
    nested parallel regions, it takes the first; with none, it is made with no
    count, as it was before any count was handed on. Returns what the three
    children reported, by the value each ran under (``"unset"`` for none).
    """
    one, listed, unset = made("1"), made("2,1"), made(None)

    def seen(reported):
        return [(made_one["added"], made_one["intra_op"]) for made_one in reported["sessions"]]

    assert seen(one) == [(0, 1)], (
        f"Under OMP_NUM_THREADS=1, {session} gave (threads started, intra-op thread count) {seen(one)}, not "
        f"[(0, 1)]: one session, on the calling thread alone (a count of 0 is onnxruntime's own choice). With "
        f"OMP_NUM_THREADS unset it gave {seen(unset)}, on a machine of {unset['cpus']} CPUs. onnxruntime reads no "
        "OMP_NUM_THREADS: the code that makes the session has to give it the count the variable names."
    )
    assert [count for _added, count in seen(listed)] == [2], (
        f"Under OMP_NUM_THREADS=2,1, {session} was made with the intra-op thread counts "
        f"{[count for _added, count in seen(listed)]}, not [2], the first count the variable lists."
    )
    assert [count for _added, count in seen(unset)] == [0], (
        f"With OMP_NUM_THREADS unset, {session} was made with the intra-op thread counts "
        f"{[count for _added, count in seen(unset)]}, not [0], onnxruntime's own choice: a Curio that sets no "
        "OMP_NUM_THREADS, as a user's does, keeps a thread per core."
    )
    return {"1": one, "2,1": listed, "unset": unset}
