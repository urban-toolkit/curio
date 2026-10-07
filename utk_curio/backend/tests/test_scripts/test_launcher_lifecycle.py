"""The launcher frees a held port and shuts its servers down on the rare paths.

``_kill_port`` (``utk_curio/cli/services.py``) runs before each server starts
and stops whatever still listens on its port. A process can exit on its own
between two of its steps, and each of those three moments has a debug line.
The ``logger`` those lines called was the queue printer of
``utk_curio/cli/logs.py``, which shadowed the logging logger of the same name,
so the AttributeError cut the cleanup short: the remaining processes were
never signalled, and the launcher reported "Could not check port" (#652).

``main()`` ends its wait loop in ``clean_shutdown()`` when a KeyboardInterrupt
reaches it, and used to pass an argument ``clean_shutdown`` does not take.
"""
from __future__ import annotations

import logging
import signal
import threading
from types import SimpleNamespace

import pytest

import utk_curio.main as launcher
from utk_curio.cli import lifecycle, logs, services

PORT = 5002


class _Clock:
    """``time`` as _kill_port uses it: its three-second wait passes at once."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Host:
    """The processes lsof lists on the port, and every signal sent to them.

    Each pid's fate is one of:

    * ``"gone"``: exited after lsof listed it, before anything reached it;
    * ``"exits on SIGTERM"``;
    * ``"ignores SIGTERM"``: only SIGKILL ends it;
    * ``"exits before SIGKILL"``: ignores SIGTERM, then exits on its own
      just before the SIGKILL arrives.
    """

    def __init__(self, fates):
        self.fates = dict(fates)
        self.alive = {pid for pid, fate in self.fates.items() if fate != "gone"}
        self.sent = []

    def lsof(self, cmd, **kwargs):
        assert cmd == ["lsof", "-t", f"-i:{PORT}"]
        return "".join(f"{pid}\n" for pid in self.fates)

    def kill(self, pid, sig):
        self.sent.append((pid, sig))
        if sig == signal.SIGKILL and self.fates[pid] == "exits before SIGKILL":
            self.alive.discard(pid)
        if pid not in self.alive:
            raise ProcessLookupError(pid)
        if sig == signal.SIGKILL or (
            sig == signal.SIGTERM and self.fates[pid] == "exits on SIGTERM"
        ):
            self.alive.discard(pid)


@pytest.fixture
def held_port(monkeypatch, caplog):
    """Put processes with the given fates on PORT, as lsof and kill see them."""
    caplog.set_level(logging.DEBUG, logger=logs.__name__)

    def hold(fates):
        host = _Host(fates)
        monkeypatch.setattr(services.platform, "system", lambda: "Linux")
        monkeypatch.setattr(services.subprocess, "check_output", host.lsof)
        monkeypatch.setattr(services.os, "kill", host.kill)
        monkeypatch.setattr(services, "time", _Clock())
        return host

    return hold


def _assert_skipped_quietly(caplog, pid):
    """No "Could not check port", and a debug line naming *pid* instead."""
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not [w for w in warnings if "Could not check port" in w], warnings
    debug = [
        r.getMessage() for r in caplog.records
        if r.name == logs.__name__ and r.levelno == logging.DEBUG
    ]
    assert any(str(pid) in line for line in debug), debug


def test_a_pid_gone_before_its_sigterm_is_skipped_and_the_next_is_stopped(held_port, caplog):
    host = held_port({111: "gone", 222: "exits on SIGTERM"})

    services._kill_port(PORT)

    assert (222, signal.SIGTERM) in host.sent, host.sent
    _assert_skipped_quietly(caplog, 111)


def test_a_pid_gone_after_its_sigterm_leaves_the_wait_for_the_others(held_port, caplog):
    host = held_port({222: "exits on SIGTERM", 333: "ignores SIGTERM"})

    services._kill_port(PORT)

    assert (333, signal.SIGKILL) in host.sent, host.sent
    _assert_skipped_quietly(caplog, 222)


def test_a_pid_gone_before_its_sigkill_is_skipped(held_port, caplog):
    host = held_port({444: "exits before SIGKILL"})

    services._kill_port(PORT)

    assert host.sent[0] == (444, signal.SIGTERM)
    assert host.sent[-1] == (444, signal.SIGKILL)
    _assert_skipped_quietly(caplog, 444)


class _Server:
    """A started server, as clean_shutdown handles it."""

    def __init__(self, name):
        self.args = [name]
        self.calls = []

    def terminate(self):
        self.calls.append("terminate")

    def wait(self, timeout=None):
        self.calls.append("wait")
        return 0

    def kill(self):
        self.calls.append("kill")


def _interrupted(seconds):
    raise KeyboardInterrupt


def test_an_interrupt_in_the_wait_loop_shuts_the_servers_down(monkeypatch):
    servers = {name: _Server(name) for name in ("backend", "sandbox", "frontend")}
    flag = threading.Event()

    # What main() changes outside itself, each put back after the test.
    monkeypatch.setattr("sys.argv", ["curio.py", "start"])
    monkeypatch.setenv("CURIO_DEV", "0")
    monkeypatch.setattr(logs, "verbosity", logs.verbosity)
    monkeypatch.setattr(lifecycle, "processes", [])
    monkeypatch.setattr(lifecycle, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "shutdown_flag", flag)
    monkeypatch.setattr(launcher, "signal", SimpleNamespace(
        SIGINT=signal.SIGINT, SIGTERM=signal.SIGTERM, signal=lambda *args: None,
    ))
    # What would set up, install, build or start something.
    monkeypatch.setattr(launcher, "setup_logging", lambda server: None)
    monkeypatch.setattr(launcher, "set_environment_variables", lambda **kwargs: None)
    monkeypatch.setattr(launcher, "_require_supported_node", lambda: None)
    monkeypatch.setattr(launcher, "_skip_dep_install", lambda: True)
    monkeypatch.setattr(launcher, "seed_duckdb_extensions", lambda: None)
    monkeypatch.setattr(launcher, "start_backend", lambda host, port: servers["backend"])
    monkeypatch.setattr(launcher, "start_sandbox", lambda host, port: servers["sandbox"])
    monkeypatch.setattr(
        launcher, "start_frontend", lambda host, port, **kwargs: servers["frontend"],
    )
    monkeypatch.setattr(launcher, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    # The wait loop's first sleep is where the interrupt lands.
    monkeypatch.setattr(launcher, "time", SimpleNamespace(sleep=_interrupted))

    with pytest.raises(SystemExit) as exited:
        launcher.main()

    assert exited.value.code == 0
    assert flag.is_set()
    for name, server in servers.items():
        assert server.calls[:2] == ["terminate", "wait"], (name, server.calls)
