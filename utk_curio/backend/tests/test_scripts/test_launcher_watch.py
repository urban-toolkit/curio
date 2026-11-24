"""A server that exits after the start stops the launcher with an error.

``curio.py start`` starts its servers, then waits until it is asked to stop.
With ``--backend-processes`` above 1 the backend group watches its backend
processes and nginx: when one exits, it stops every server and the launcher
exits 1 (``backend_group.watch``). The servers ``main()`` starts itself, the
one backend, the sandbox and the page or dev server, had no such watch. One of
them could exit while the launcher kept running without it, and the next
Ctrl-C or SIGTERM ended the start with 0, so a script, a service manager or
Docker's restart policy never learned that a server had stopped.

``stream_output`` stopped reading a server at the first look that saw it had
exited, so the lines it wrote last, often why it stopped, could miss the log.

The backend group stops every server on its own thread, a daemon one, one
server after the other, and the launcher's wait exited as soon as it saw that
stop begin. Its exit ended the thread, so the servers the thread had not
stopped yet outlived the launcher.
"""
from __future__ import annotations

import logging
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import utk_curio.main as launcher
from utk_curio.cli import backend_group, frontend_build, lifecycle, logs


class _Server:
    """A started server, running until :attr:`code` is the code it exited with."""

    def __init__(self, name, code=None):
        self.args = [name]
        self.code = code
        self.calls = []

    def poll(self):
        return self.code

    def terminate(self):
        self.calls.append("terminate")
        if self.code is None:
            self.code = -signal.SIGTERM

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.calls.append("kill")


def _interrupted(seconds):
    raise KeyboardInterrupt


def _launcher_starting_nothing(monkeypatch, *argv):
    """Ready ``main()`` to run as ``curio.py <argv>``, with what would set up,
    install, build or start something faked. The launcher's stop flag, a
    fresh one."""
    flag = threading.Event()

    # What main() changes outside itself, each put back after the test.
    monkeypatch.setattr("sys.argv", ["curio.py", *argv])
    monkeypatch.setattr(logs, "verbosity", logs.verbosity)
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(lifecycle, "exit_status", 0)
    monkeypatch.setattr(lifecycle, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, signal=lambda *args: None,
    ))
    # What would set up, install, build or start something.
    monkeypatch.setattr(launcher, "setup_logging", lambda server: None)
    monkeypatch.setattr(launcher, "set_environment_variables", lambda **kwargs: None)
    monkeypatch.setattr(launcher, "_require_supported_node", lambda: None)
    monkeypatch.delenv("CURIO_DEV", raising=False)
    monkeypatch.setattr(frontend_build, "_frontend_needs_build", lambda: False)
    monkeypatch.setattr(frontend_build, "_frontend_tree_is_stale", lambda: False)
    monkeypatch.setattr(launcher, "_skip_dep_install", lambda: True)
    monkeypatch.setattr(launcher, "seed_duckdb_extensions", lambda: None)
    monkeypatch.setattr(launcher, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    return flag


def _start(monkeypatch, *, server, deploy, exits):
    """Run ``curio.py start <server>`` with its servers faked, *exits* among
    them already exited with code 3, and the wait ended as Ctrl-C ends it at
    its first sleep. The servers by name, and the code main() exited with."""
    servers = {name: _Server(name) for name in ("backend", "sandbox", "frontend")}
    servers[exits].code = 3

    _launcher_starting_nothing(monkeypatch, "start", server, *(["--deploy"] if deploy else []))
    monkeypatch.setattr(launcher, "start_backend", lambda host, port: servers["backend"])
    monkeypatch.setattr(launcher, "start_sandbox", lambda host, port: servers["sandbox"])
    monkeypatch.setattr(launcher, "start_frontend", lambda host, port, **kwargs: servers["frontend"])
    # The wait's first sleep is where Ctrl-C lands.
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(sleep=_interrupted))

    with pytest.raises(SystemExit) as exited:
        launcher.main()
    return servers, exited.value.code


@pytest.mark.parametrize("server, deploy, exits", [
    pytest.param("all", False, "backend", id="all, the backend"),
    pytest.param("all", False, "sandbox", id="all, the sandbox"),
    pytest.param("all", False, "frontend", id="all, the frontend"),
    pytest.param("all", True, "frontend", id="all --deploy, the frontend it starts first"),
    pytest.param("backend", False, "backend", id="backend"),
    pytest.param("sandbox", False, "sandbox", id="sandbox"),
    pytest.param("frontend", False, "frontend", id="frontend"),
])
def test_a_server_that_exits_after_the_start_stops_every_server_with_an_error(
        server, deploy, exits, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    servers, code = _start(monkeypatch, server=server, deploy=deploy, exits=exits)

    assert code == 1, f"the start went on without its {exits}, and ended as if nothing had gone wrong"
    said = f"{exits.capitalize()} exited with code 3"
    assert any(said in record.getMessage() for record in caplog.records), (
        f"the launcher did not say that the {exits} exited, and with which code: {caplog.text}"
    )
    started = ("backend", "sandbox", "frontend") if server == "all" else (server,)
    for name in started:
        if name != exits:
            assert servers[name].calls[:1] == ["terminate"], (name, servers[name].calls)


#: A server that writes why it stops, then exits.
_LAST_WORDS = (
    "import sys\n"
    "print('starting')\n"
    "print('why it stopped')\n"
    "sys.exit(3)\n"
)


def test_what_an_exited_server_wrote_last_is_in_the_log_before_every_server_stops(monkeypatch):
    """The sandbox exited before its reader first looked at it, so what it
    wrote is still in the pipe. The watch, here the backend group's, stops
    every server only once those lines are in the log."""
    flag = threading.Event()
    monkeypatch.setattr(lifecycle, "shutdown_flag", flag)
    monkeypatch.setattr(backend_group, "shutdown_flag", flag)
    said = []
    monkeypatch.setattr(lifecycle, "log_info", lambda message, color, verbose_level=1: said.append(message))
    monkeypatch.setattr(backend_group, "clean_shutdown",
                        lambda status=0: said.append(f"every server stopped with {status}"))

    sandbox = subprocess.Popen([sys.executable, "-c", _LAST_WORDS], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True)
    assert sandbox.wait(timeout=60) == 3
    threading.Thread(target=lifecycle.stream_output, args=(sandbox, "Sandbox", ""), daemon=True).start()

    backend_group.watch([("Sandbox", sandbox)])

    assert "every server stopped with 1" in said, said
    before_the_stop = said[:said.index("every server stopped with 1")]
    assert "[Sandbox] why it stopped" in before_the_stop, said


#: A server that stops 1.5 s after SIGTERM, later than the launcher's wait
#: looks again, once it said it is ready for SIGTERM.
_SLOW_TO_STOP = (
    "import signal, sys, time\n"
    "def stop(signum, frame):\n"
    "    time.sleep(1.5)\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, stop)\n"
    "print('ready', flush=True)\n"
    "while True:\n"
    "    time.sleep(0.1)\n"
)


def _the_groups_thread(watch, started):
    """*watch* of *started*, ended as ``clean_shutdown`` ends a thread other
    than the main one: by SystemExit, once it stopped every server."""
    try:
        watch(started)
    except SystemExit:
        pass  # the end of the backend group's thread


def test_a_start_the_backend_group_stops_exits_once_every_server_stopped(monkeypatch):
    """``start backend --backend-processes 2``, whose Backend 1 exited with 3.
    The group's own watch, on its thread, stops every server one after the
    other, each 1.5 s after its SIGTERM. The launcher exits 1, and only once
    none of them runs."""
    flag = _launcher_starting_nothing(monkeypatch, "start", "backend", "--backend-processes", "2")
    monkeypatch.setattr(backend_group, "shutdown_flag", flag)
    # What the stop sets once it stopped every server, a fresh one.
    monkeypatch.setattr(lifecycle, "servers_stopped", threading.Event(), raising=False)
    monkeypatch.setattr(backend_group, "refuse_without_nginx", lambda processes: None)
    for name in ("start_backend", "start_sandbox", "start_frontend"):
        monkeypatch.setattr(launcher, name, lambda *args, **kwargs: pytest.fail("a server started outside the group"))
    servers = []
    threads = []

    def start_backend_group(host, port, processes):
        for name in ("Backend 0", "Backend 1", "nginx"):
            if name == "Backend 1":
                server = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(3)"])
                assert server.wait(timeout=60) == 3
            else:
                server = subprocess.Popen([sys.executable, "-c", _SLOW_TO_STOP], stdout=subprocess.PIPE, text=True)
                assert server.stdout.readline().strip() == "ready"
            servers.append((name, backend_group._kept(server)))
        threads.append(threading.Thread(target=_the_groups_thread, args=(backend_group.watch, list(servers)),
                                        name="backend-group", daemon=True))
        threads[0].start()

    monkeypatch.setattr(backend_group, "start_backend_group", start_backend_group)

    try:
        with pytest.raises(SystemExit) as exited:
            launcher.main()
        still_running = [name for name, server in servers if server.poll() is None]
    finally:
        for _, server in servers:
            if server.poll() is None:
                server.kill()
            server.wait(timeout=60)
            if server.stdout:
                server.stdout.close()
        for thread in threads:
            thread.join(timeout=60)

    assert exited.value.code == 1
    assert still_running == [], (
        f"the launcher exited before the backend group's thread stopped {', '.join(still_running)}, "
        "which outlived it"
    )
