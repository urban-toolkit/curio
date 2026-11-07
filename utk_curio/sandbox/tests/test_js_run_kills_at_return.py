"""Owner rule, 11-07: every process a JavaScript node starts ends when the node returns.

The owner: "Let's kill at return and make it strict so that no PR or later push
reverts this. This should never change, always kill at return." Then: "also
add tests for that so it does not revert back."

``worker.run_js_script`` runs a JavaScript node in one Node.js process. When
Node exits, whether the node returned or threw, and when it reaches its
timeout, the run kills every process the node started: Node's process group,
and every process whose environment carries the run's mark, which one that
left the group (a ``detached`` child, or a daemon whose parent has exited)
still does. These tests guard that rule: never weaken, skip or remove them,
and never add an option that turns it off.

Each test's node starts its processes and writes, for each, its pid and
whether it was running when the node looked, so a process that never started
fails the test, then the moment it returned. The test then gives everything
the node started ``BOUND`` seconds from that moment to be gone, and kills
whatever is left when it ends.
"""

import json
import os
import signal
import subprocess
import threading
import time

import pytest

#: How long after the node returns anything it started may still run.
BOUND = 3

#: How long a test waits for a run before it says the run never returned.
WAIT = 60

#: The timeout the timeout test gives its run.
TIMEOUT = 5

#: Node code for a process that runs ten minutes unless it is killed.
_FOREVER = "setTimeout(() => {}, 600000)"

#: Node code for a child that starts a daemon (a session of its own, its
#: output closed), prints the daemon's pid and exits, leaving it orphaned.
_STARTS_A_DAEMON = (
    "const daemon = require('child_process').spawn(process.execPath, ['-e', "
    + json.dumps(_FOREVER)
    + "], { detached: true, stdio: 'ignore' }); daemon.unref(); process.stdout.write(String(daemon.pid));"
)

#: How a test's node starts each process it can start, by name.
_STARTS = {
    # A background child: a session of its own, its output closed.
    "background": "keep('background', spawn(process.execPath, ['-e', FOREVER], "
                  "{ detached: true, stdio: 'ignore' }).pid);",
    # A daemon whose parent, a child of the node, has exited.
    "daemon": "keep('daemon', Number(execFileSync(process.execPath, ['-e', STARTS_A_DAEMON]).toString()));",
    # A child in the node's process group that closed its output.
    "closed_output": "keep('closed_output', spawn(process.execPath, ['-e', FOREVER], "
                     "{ stdio: 'ignore' }).pid);",
    # A child that holds Node's stdout and stderr.
    "holding_output": "keep('holding_output', spawn(process.execPath, ['-e', FOREVER], "
                      "{ stdio: ['ignore', 'inherit', 'inherit'] }).pid);",
}


def _node_code(record_file, names, end):
    """Node code that starts the processes *names*, writes the record to
    *record_file*, then ends with *end*."""
    lines = [
        "const { spawn, execFileSync } = await import('node:child_process');",
        "const fs = await import('node:fs');",
        f"const FOREVER = {json.dumps(_FOREVER)};",
        f"const STARTS_A_DAEMON = {json.dumps(_STARTS_A_DAEMON)};",
        "const running = (pid) => { try { return process.kill(pid, 0); } catch (e) { return false; } };",
        "const started = {};",
        "const keep = (name, pid) => { started[name] = { pid, running: Number.isInteger(pid) && running(pid) }; };",
        *(_STARTS[name] for name in names),
        f"fs.writeFileSync({json.dumps(str(record_file))}, JSON.stringify({{ started, at: Date.now() }}));",
        end,
    ]
    return "\n".join(lines) + "\n"


def _running(pid):
    """Whether *pid* is a live process. One killed and not yet reaped (a
    zombie, which a container's first process may never reap) is not."""
    if not isinstance(pid, int) or pid <= 0:
        return False
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


class _Record:
    """What a test's node started, as it wrote it."""

    def __init__(self, path):
        self.path = path

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def started(self):
        return self.read().get("started", {})

    def kill_the_rest(self):
        for process in self.started().values():
            if _running(process.get("pid")):
                try:
                    os.kill(process["pid"], signal.SIGKILL)
                except OSError:
                    pass


@pytest.fixture
def record(tmp_path):
    record = _Record(tmp_path / "started.json")
    yield record
    # Whatever a run left, so a failing test leaves nothing behind.
    record.kill_the_rest()


class _Run:
    """One run on a thread of its own, so a run that never returns fails the
    test instead of hanging it."""

    def __init__(self, code, cwd, node_type):
        from utk_curio.sandbox.app import worker

        self._outcome = None
        self.ended_at = None

        def run():
            try:
                self._outcome = (worker.run_js_script(code, {}, cwd=str(cwd), node_type=node_type), None)
            except BaseException as exc:  # noqa: BLE001 - handed to the test
                self._outcome = (None, exc)
            self.ended_at = time.time()

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


def _check_nothing_runs_after(record, moment, run):
    """Every process the node started was running when the node looked, and
    none runs ``BOUND`` seconds after *moment*."""
    started = record.started()
    assert started, "the node wrote no record of what it started"
    never = sorted(name for name, process in started.items() if not process["running"])
    assert not never, f"the node's {never} never ran, so this test proves nothing: {started}"
    late = run.ended_at - moment
    assert late <= BOUND, (
        f"the run ended {late:.1f} s after the node did: what the node started was not killed when it ended"
    )
    deadline = moment + BOUND
    while True:
        still = {name: process["pid"] for name, process in started.items() if _running(process["pid"])}
        if not still or time.time() > deadline:
            break
        time.sleep(0.05)
    assert not still, f"still running {BOUND} s after the node ended, though the node started them: {still}"


def test_every_process_a_javascript_node_starts_ends_when_it_returns(record, tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """A background child, a daemon whose parent has exited and a child that
    closed its output: none runs once the node has returned."""
    code = _node_code(record.path, ["background", "daemon", "closed_output"], "return 1;")
    run = _Run(code, tmp_path, "STARTS_AND_RETURNS")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None and json.loads(result)["value"] == 1, "\n".join(stderr)
    _check_nothing_runs_after(record, record.read()["at"] / 1000, run)


def test_a_process_holding_a_javascript_nodes_output_ends_when_the_node_returns(record, tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """A child that holds Node's stdout and stderr ends when the node returns,
    not after a wait for that output, and the run returns the node's value."""
    code = _node_code(record.path, ["holding_output"], "return 7;")
    run = _Run(code, tmp_path, "HOLDS_ITS_OUTPUT")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None and json.loads(result)["value"] == 7, "\n".join(stderr)
    _check_nothing_runs_after(record, record.read()["at"] / 1000, run)


def test_every_process_a_javascript_node_starts_ends_when_it_throws(record, tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """A node that throws after starting a background child and a child that
    closed its output fails with its error, and neither child runs on."""
    code = _node_code(record.path, ["background", "closed_output"], "throw new Error('the node fails on purpose');")
    run = _Run(code, tmp_path, "STARTS_AND_THROWS")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None, "\n".join(stderr)
    outcome = json.loads(result)
    assert not outcome["success"] and "the node fails on purpose" in outcome["error"], outcome
    _check_nothing_runs_after(record, record.read()["at"] / 1000, run)


def test_every_process_a_javascript_node_starts_ends_when_it_times_out(record, tmp_path, monkeypatch):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """A node that never ends, with a background child and a child holding its
    output: at the timeout the run raises ``TimeoutExpired``, and neither child
    runs on."""
    from utk_curio.sandbox.app import worker

    monkeypatch.setattr(worker, "JS_TIMEOUT_SECONDS", TIMEOUT)
    code = _node_code(
        record.path, ["background", "holding_output"],
        "setInterval(() => {}, 1000);\nawait new Promise(() => {});",
    )
    run = _Run(code, tmp_path, "STARTS_AND_TIMES_OUT")

    assert run.ended_within(TIMEOUT + WAIT), f"the run has not returned {TIMEOUT + WAIT} s after it started"
    with pytest.raises(subprocess.TimeoutExpired):
        run.result()
    _check_nothing_runs_after(record, run.ended_at, run)
