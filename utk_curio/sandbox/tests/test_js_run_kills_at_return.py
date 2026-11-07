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

On Linux, Node and every process it starts are denied ``setsid`` and
``setpgid`` (``worker._node_command``, ``isolation/seccomp_filter.py``), so
none leaves Node's process group, and the kill of that group reaches a
process without the run's mark too: one started with an environment of its
own. The tests marked ``linux_only`` guard that.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the seccomp filter that keeps Node's processes in its group exists only on Linux",
)

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

#: Python code for a process that leaves its process group by itself, with
#: ``CALL``, carries on when it is refused, says it tried on its output and
#: closes it, then runs ten minutes unless it is killed.
_LEAVES_BY_ITSELF = (
    "import os, time\n"
    "try:\n"
    "    CALL\n"
    "except OSError:\n"
    "    pass\n"
    "os.write(1, b'tried')\n"
    "os.close(1)\n"
    "time.sleep(600)\n"
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
    # A background child given an environment without the run's mark.
    "unmarked_background": "keepUnmarked('unmarked_background', spawn(process.execPath, ['-e', FOREVER], "
                           "{ detached: true, stdio: 'ignore', env: UNMARKED }).pid);",
    # A process without the mark that calls setsid itself, once it has.
    "unmarked_own_session": "keepUnmarked('unmarked_own_session', await leaving('os.setsid()'));",
    # A process without the mark that calls setpgid itself, once it has.
    "unmarked_own_group": "keepUnmarked('unmarked_own_group', await leaving('os.setpgid(0, 0)'));",
}

#: Node code that the unmarked processes above use: a Python to run, an
#: environment without the run's mark, whether a process carries the mark,
#: and a process that leaves its group by itself (``_LEAVES_BY_ITSELF``),
#: given once it has tried.
_UNMARKED_HELPERS = [
    f"const PYTHON = {json.dumps(sys.executable)};",
    f"const LEAVES_BY_ITSELF = {json.dumps(_LEAVES_BY_ITSELF)};",
    "const UNMARKED = { PATH: process.env.PATH };",
    ("const carriesTheMark = (pid) => { try { return fs.readFileSync(`/proc/${pid}/environ`, 'latin1')"
     ".split(String.fromCharCode(0)).some((entry) => entry.startsWith('CURIO_JS_RUN=')); } "
     "catch (e) { return null; } };"),
    "const keepUnmarked = (name, pid) => { keep(name, pid); started[name].marked = carriesTheMark(pid); };",
    ("const leaving = (call) => new Promise((resolve) => { "
     "const child = spawn(PYTHON, ['-I', '-S', '-c', LEAVES_BY_ITSELF.replace('CALL', call)], "
     "{ stdio: ['ignore', 'pipe', 'ignore'], env: UNMARKED }); "
     "child.stdout.resume(); child.stdout.on('close', () => resolve(child.pid)); });"),
]


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
        *(_UNMARKED_HELPERS if any(name.startswith("unmarked_") for name in names) else []),
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


@linux_only
def test_every_process_a_javascript_node_starts_ends_when_it_returns_without_the_runs_mark(record, tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """A background child started with an environment of its own, and
    processes that call setsid or setpgid themselves, none of them carrying
    the run's mark: none runs once the node has returned. None can leave
    Node's process group, which the run kills when Node exits."""
    names = ["unmarked_background", "unmarked_own_session", "unmarked_own_group"]
    code = _node_code(record.path, names, "return 1;")
    run = _Run(code, tmp_path, "STARTS_UNMARKED_AND_RETURNS")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None and json.loads(result)["value"] == 1, "\n".join(stderr)
    marked = {name: process.get("marked") for name, process in record.started().items()}
    assert marked == dict.fromkeys(names, False), (
        f"these processes carry the run's mark, so the mark, not Node's process group, could end them: {marked}"
    )
    _check_nothing_runs_after(record, record.read()["at"] / 1000, run)


#: Python code that tries each way out of its process group, each in a fresh
#: process of its own, so one that got out cannot spoil the next, and prints
#: its group and what each try got. Node starts it in Node's group, and it
#: leads no group, so nothing but a filter refuses a try.
_TRIES_TO_LEAVE_NODES_GROUP = r'''
import json, os, subprocess
group = os.getpgid(0)

def tried(leave):
    read_end, write_end = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            os.close(read_end)
            try:
                leave()
                outcome = "allowed"
            except OSError as error:
                outcome = type(error).__name__
            where = "in" if os.getpgid(0) == group else "out of"
            os.write(write_end, f"{outcome}, {where} Node's group".encode())
        finally:
            os._exit(0)
    os.close(write_end)
    os.waitpid(pid, 0)
    with os.fdopen(read_end, "rb") as reading:
        return reading.read().decode()

seen = {
    "os.setsid()": tried(os.setsid),
    "os.setpgid(0, 0)": tried(lambda: os.setpgid(0, 0)),
    "os.setpgrp()": tried(os.setpgrp),
}
for keyword, value in (("start_new_session", True), ("process_group", 0)):
    try:
        subprocess.Popen(["true"], **{keyword: value}).wait()
        seen[f"Popen({keyword}={value})"] = "allowed"
    except OSError as error:
        seen[f"Popen({keyword}={value})"] = type(error).__name__
print(json.dumps({"group": group, "seen": seen}))
'''


@linux_only
def test_no_process_a_javascript_node_starts_can_leave_nodes_process_group(tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """In a process a JavaScript node starts, each way out of Node's process
    group fails with PermissionError and leaves the process in the group:
    ``setsid``, ``setpgid``, glibc's ``setpgrp`` (``setpgid(0, 0)``), and
    ``subprocess.Popen`` asked for a session or a process group of its own."""
    code = (
        "const { execFileSync } = await import('node:child_process');\n"
        f"const tried = JSON.parse(execFileSync({json.dumps(sys.executable)}, "
        f"['-I', '-S', '-c', {json.dumps(_TRIES_TO_LEAVE_NODES_GROUP)}]).toString());\n"
        "return { node: process.pid, ...tried };\n"
    )
    run = _Run(code, tmp_path, "TRIES_TO_LEAVE_NODES_GROUP")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None, "\n".join(stderr)
    outcome = json.loads(result)
    assert outcome["success"], outcome
    value = outcome["value"]
    assert value["group"] == value["node"], f"the tries did not run in Node's process group: {value}"
    assert value["seen"] == {
        "os.setsid()": "PermissionError, in Node's group",
        "os.setpgid(0, 0)": "PermissionError, in Node's group",
        "os.setpgrp()": "PermissionError, in Node's group",
        "Popen(start_new_session=True)": "PermissionError",
        "Popen(process_group=0)": "PermissionError",
    }, f"a process a JavaScript node started could leave Node's process group: {value['seen']}"


@linux_only
def test_a_detached_child_of_a_javascript_node_starts_in_nodes_process_group(tmp_path):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """``spawn(..., { detached: true })`` still starts its child, and the
    child stays in Node's session and process group. libuv's child calls
    ``setsid()`` before its exec and ignores what it returns
    (``deps/uv/src/unix/process.c``, ``uv__process_child_init``, libuv 1.52.1
    in every Node 26 release), so the EPERM the filter gives it leaves the
    child where it is, where the run's kill reaches it."""
    code = (
        "const { spawn } = await import('node:child_process');\n"
        "const fs = await import('node:fs');\n"
        "const ids = (pid) => { const [, , group, session] = fs.readFileSync(`/proc/${pid}/stat`, 'utf8')"
        ".split(')').pop().trim().split(' '); return { group: Number(group), session: Number(session) }; };\n"
        f"const child = spawn(process.execPath, ['-e', {json.dumps(_FOREVER)}], "
        "{ detached: true, stdio: 'ignore' });\n"
        "const outcome = await new Promise((resolve) => { child.once('spawn', () => resolve('started')); "
        "child.once('error', (error) => resolve(String(error.code || error))); });\n"
        "const seen = { outcome, node: process.pid, nodeIds: ids(process.pid), "
        "childIds: outcome === 'started' ? ids(child.pid) : null };\n"
        "if (outcome === 'started') child.kill('SIGKILL');\n"
        "return seen;\n"
    )
    run = _Run(code, tmp_path, "STARTS_A_DETACHED_CHILD")

    assert run.ended_within(WAIT), f"the run has not returned {WAIT} s after it started"
    result, _logs, stderr = run.result()
    assert result is not None, "\n".join(stderr)
    outcome = json.loads(result)
    assert outcome["success"], outcome
    seen = outcome["value"]
    assert seen["outcome"] == "started", f"a detached spawn did not start its child: {seen}"
    assert seen["nodeIds"] == {"group": seen["node"], "session": seen["node"]}, (
        f"Node does not lead a session and a process group of its own: {seen}"
    )
    assert seen["childIds"] == seen["nodeIds"], f"a detached child left Node's process group: {seen}"


@linux_only
def test_a_javascript_run_whose_filter_cannot_be_installed_fails_only_under_fork_isolation(tmp_path, monkeypatch):
    # Owner rule, 11-07: every process a node starts ends when the node returns. Never weaken, skip or remove these tests.
    """Where the filter cannot be installed (here a stand-in ``pyseccomp``
    that cannot load libseccomp), a run under ``CURIO_ISOLATION=fork`` does
    not start Node and says why, as an isolated child that cannot confine
    itself fails; with isolation off, Node runs without the filter."""
    stand_in = tmp_path / "without-libseccomp"
    stand_in.mkdir()
    (stand_in / "pyseccomp.py").write_text(
        "raise ImportError('a stand-in pyseccomp that cannot load libseccomp')\n", encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
        path for path in (str(stand_in), os.environ.get("PYTHONPATH")) if path
    ))
    got = {}
    for isolation in ("fork", "off"):
        monkeypatch.setenv("CURIO_ISOLATION", isolation)
        run = _Run("return 2;", tmp_path, f"WITHOUT_ITS_FILTER_{isolation.upper()}")
        assert run.ended_within(WAIT), f"the run under {isolation} has not returned {WAIT} s after it started"
        result, _logs, stderr = run.result()
        outcome = json.loads(result) if result is not None else None
        got[isolation] = outcome.get("value", outcome) if outcome is not None else "\n".join(stderr)
    assert got["off"] == 2, f"with isolation off, a run whose filter cannot be installed did not run: {got['off']}"
    assert "could not install the seccomp filter" in str(got["fork"]), (
        f"under CURIO_ISOLATION=fork, a run whose filter cannot be installed ran, or failed for another reason: "
        f"{got['fork']}"
    )
