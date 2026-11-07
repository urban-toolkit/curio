"""A JavaScript run cannot hold its slot forever.

``worker.run_js_script`` runs a JavaScript node in one Node.js process, under
one of the ``CURIO_JS_PARALLELISM`` slots (``worker._js_slot()``), and reads
what Node prints until its stdout and stderr end. A process Node starts gets
those pipes too (``stdio: 'inherit'``, ``child_process.fork``). One that
outlived Node kept them open, and the run waited for their end with no bound,
after Node exited or after the timeout had killed Node alone. All that time it
kept its slot, and enough such runs left no slot for any JavaScript node.

Node now runs in a process group of its own. When Node exits, or when it
reaches ``JS_TIMEOUT_SECONDS``, the run kills every process Node started (the
owner's rule, guarded by ``test_js_run_kills_at_return.py``), gives the pipes
``JS_OUTPUT_GRACE_SECONDS`` to end, and returns. The tests make both bounds
short with ``raising=False``: a checkout without them keeps its own, so there
the run still never returns, and the test fails on that.

Each test's Node starts a child that holds Node's stdout and stderr for ten
minutes and writes both pids to a file, so the test can tell whether the run
killed them, and kills whatever is left when it ends.
"""

import contextlib
import json
import os
import signal
import subprocess
import threading
import time

import pytest

#: The bounds the tests give a run: the wait after Node exits, and the timeout.
GRACE = 0.5
TIMEOUT = 5

#: How long a test waits past those bounds before it says the run never returned.
WAIT = 30


def _starts_a_child(pids_file):
    """Node code that starts a child holding Node's stdout and stderr for ten
    minutes, then writes Node's pid and the child's to *pids_file*."""
    return (
        "const { spawn } = await import('node:child_process');\n"
        "const fs = await import('node:fs');\n"
        "const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 600000)'],\n"
        "  { stdio: ['ignore', 'inherit', 'inherit'] });\n"
        f"fs.writeFileSync({json.dumps(str(pids_file))},\n"
        "  JSON.stringify({ node: process.pid, child: child.pid }));\n"
    )


def _running(pid):
    """Whether *pid* is a live process. One killed and not yet reaped (a
    zombie, which a container's first process may never reap) is not."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stat:
            return stat.read().rpartition(")")[2].split()[0] != "Z"
    except OSError:
        return True  # no /proc here, and the process exists


def _gone(pid, seconds=10):
    deadline = time.monotonic() + seconds
    while _running(pid):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def _is_free(slots):
    if not slots.acquire(blocking=False):
        return False
    slots.release()
    return True


class _Pids:
    """The pids a test's Node writes."""

    def __init__(self, path):
        self.path = path

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def kill_the_rest(self):
        for pid in self.read().values():
            if _running(pid):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)


class _Run:
    """One call on a thread of its own, so a run that never returns fails the
    test instead of hanging it."""

    def __init__(self, call):
        self._outcome = None

        def run():
            try:
                self._outcome = (call(), None)
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                self._outcome = (None, exc)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def ended_within(self, seconds):
        self._thread.join(seconds)
        return not self._thread.is_alive()

    def result(self):
        value, error = self._outcome
        if error is not None:
            raise error
        return value


@pytest.fixture
def js_slot(monkeypatch):
    """One slot for Node runs, the test's own."""
    from utk_curio.sandbox.app import worker

    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(worker, "_js_slots", slots)
    return slots


@pytest.fixture
def pids(tmp_path):
    pids = _Pids(tmp_path / "pids.json")
    yield pids
    # Whatever the run left. Where the run never returned, the child holds its
    # pipes, and only this lets it end.
    pids.kill_the_rest()


def test_a_run_whose_child_holds_its_output_returns_and_frees_its_slot(js_slot, pids, tmp_path, monkeypatch):
    """Node returns 7 and exits while its child holds Node's stdout and
    stderr. The run kills the child and returns 7, its slot is free, and the
    next JavaScript node runs."""
    from utk_curio.sandbox.app import worker

    monkeypatch.setattr(worker, "JS_OUTPUT_GRACE_SECONDS", GRACE, raising=False)
    code = _starts_a_child(pids.path) + "return 7;\n"
    run = _Run(lambda: worker.run_js_script(code, {}, cwd=str(tmp_path), node_type="HOLDS_ITS_OUTPUT"))

    assert run.ended_within(WAIT), (
        f"the run has not returned {WAIT} s after it started: a child of Node holds Node's "
        "output, and the run holds its slot"
    )
    result, _logs, stderr = run.result()
    assert result is not None, "\n".join(stderr)
    assert json.loads(result)["value"] == 7, result
    child = pids.read()["child"]
    assert _gone(child), f"the child Node started ({child}) still runs after the run returned"
    assert _is_free(js_slot), "the run returned and kept its slot"

    following = _Run(lambda: worker.run_js_script("return 40 + 2;", {}, cwd=str(tmp_path), node_type="NEXT"))
    assert following.ended_within(WAIT), "the next JavaScript node did not get the slot"
    result, _logs, stderr = following.result()
    assert result is not None and json.loads(result)["value"] == 42, "\n".join(stderr)


def test_a_run_past_its_timeout_is_killed_with_all_it_started(js_slot, pids, tmp_path, monkeypatch):
    """Node starts its child and never ends. At the timeout the run kills
    Node's group, the child with it, raises ``TimeoutExpired`` as before, and
    its slot is free."""
    from utk_curio.sandbox.app import worker

    monkeypatch.setattr(worker, "JS_TIMEOUT_SECONDS", TIMEOUT, raising=False)
    monkeypatch.setattr(worker, "JS_OUTPUT_GRACE_SECONDS", GRACE, raising=False)
    code = _starts_a_child(pids.path) + "setInterval(() => {}, 1000);\nawait new Promise(() => {});\n"
    run = _Run(lambda: worker.run_js_script(code, {}, cwd=str(tmp_path), node_type="PAST_ITS_TIMEOUT"))

    assert run.ended_within(TIMEOUT + WAIT), (
        f"the run has not returned {TIMEOUT + WAIT} s after it started, with a timeout of "
        f"{TIMEOUT} s: Node or its child is still running, and the run holds its slot"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run.result()
    started = pids.read()
    assert set(started) == {"node", "child"}, (
        f"Node had not started its child {TIMEOUT} s in, so this run proves nothing: {started}"
    )
    for name, pid in started.items():
        assert _gone(pid), f"{name} ({pid}) still runs after the run timed out"
    assert _is_free(js_slot), "the run timed out and kept its slot"
