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


def _start(monkeypatch, *, server, deploy, exits):
    """Run ``curio.py start <server>`` with its servers faked, *exits* among
    them already exited with code 3, and the wait ended as Ctrl-C ends it at
    its first sleep. The servers by name, and the code main() exited with."""
    servers = {name: _Server(name) for name in ("backend", "sandbox", "frontend")}
    servers[exits].code = 3
    flag = threading.Event()

    # What main() changes outside itself, each put back after the test.
    monkeypatch.setattr("sys.argv", ["curio.py", "start", server, *(["--deploy"] if deploy else [])])
    monkeypatch.setattr(logs, "verbosity", logs.verbosity)
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(lifecycle, "exit_status", 0)
    monkeypatch.setattr(lifecycle, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "shutdown_flag", flag)
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
    monkeypatch.setattr(launcher, "start_backend", lambda host, port: servers["backend"])
    monkeypatch.setattr(launcher, "start_sandbox", lambda host, port: servers["sandbox"])
    monkeypatch.setattr(launcher, "start_frontend", lambda host, port, **kwargs: servers["frontend"])
    monkeypatch.setattr(launcher, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    # The wait's sleep, wherever the launcher keeps it, is where Ctrl-C lands.
    for module in (launcher, lifecycle):
        monkeypatch.setattr(module, "time", SimpleNamespace(sleep=_interrupted), raising=False)

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
