"""The launcher's start of several backend processes, with every process faked
(``utk_curio/cli/backend_group.py``).

:func:`boot` runs ``backend_group.boot`` as the launcher's thread runs it, on
the test's own thread: no process starts, no server's ``/health`` is asked and
nginx never runs. Each start keeps what it would have started (its command and
its environment), and the starts, the waits for each server and nginx's check
of its config are kept in the order they came. The launcher's modules are
imported inside :func:`boot`, so a checkout without them fails each test that
boots, on its own.
"""

from __future__ import annotations

import importlib
import itertools
import subprocess
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, Optional

#: Where the faked nginx is said to be; nothing runs it.
NGINX = "/usr/sbin/nginx"

_pids = itertools.count(40000)


class FakeProcess:
    """A server that never ran: ``poll`` answers :attr:`exit_code`, None while
    it is said to run."""

    def __init__(self, args, env):
        self.args = list(args)
        self.env = dict(env or {})
        self.pid = next(_pids)
        self.stdout = None
        self.stderr = None
        self.exit_code: Optional[int] = None
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        if self.exit_code is None:
            self.exit_code = -15

    kill = terminate

    def wait(self, timeout=None):
        return self.exit_code


@dataclass
class Booted:
    #: What ``boot`` returned: ``[(name, process)]`` of every server it
    #: started, or None.
    started: object = None
    #: In the order they came: ``("start", name)``, ``("answers", name)`` and
    #: ``("check", "nginx -t")``.
    events: list = field(default_factory=list)
    #: Each backend's faked process, by its number.
    backends: dict = field(default_factory=dict)
    #: nginx's faked process, once started.
    nginx: Optional[FakeProcess] = None
    #: Each ``nginx -t``: its command and its environment.
    checks: list = field(default_factory=list)
    #: Where each wait for a server asked: ``(name, host, port)``.
    asked: list = field(default_factory=list)
    #: The name each server's output is kept under in the launcher's log.
    streams: list = field(default_factory=list)
    #: Each status the launcher stopped every server with.
    stopped: list = field(default_factory=list)

    def env(self, number: int) -> dict:
        """The environment backend process *number* was started with."""
        return self.backends[number].env


def boot(monkeypatch, *, processes: int = 2, host: str = "127.0.0.1", port: int = 5999,
         answers: Callable[[str], bool] = lambda name: True, check_status: int = 0) -> Booted:
    """``backend_group.boot(host, port, processes)`` with every process faked.
    *answers* says whether the server it names answers ``/health``;
    *check_status* is what ``nginx -t`` exits with."""
    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    services = importlib.import_module("utk_curio.cli.services")
    lifecycle = importlib.import_module("utk_curio.cli.lifecycle")
    booted = Booted()

    def start_backend(args, **kwargs):
        process = FakeProcess(args, kwargs.get("env"))
        number = int(process.env["CURIO_BACKEND_PROCESS"])
        booted.backends[number] = process
        booted.events.append(("start", f"Backend {number}"))
        return process

    def start_nginx(args, **kwargs):
        process = FakeProcess(args, kwargs.get("env"))
        booted.nginx = process
        booted.events.append(("start", "nginx"))
        return process

    def check(args, **kwargs):
        booted.checks.append((list(args), dict(kwargs.get("env") or {})))
        booted.events.append(("check", "nginx -t"))
        return SimpleNamespace(returncode=check_status, stdout="", stderr="")

    def answered(name, asked_host, asked_port, process):
        booted.asked.append((name, asked_host, asked_port))
        booted.events.append(("answers", name))
        return answers(name)

    def thread(*args, target=None, **kwargs):
        given = kwargs.get("args") or ()
        if len(given) >= 2 and isinstance(given[1], str):
            booted.streams.append(given[1])
        return SimpleNamespace(start=lambda: None, daemon=True)

    quiet = SimpleNamespace(Thread=thread, Event=threading.Event, Lock=threading.Lock)
    monkeypatch.setattr(services, "subprocess", SimpleNamespace(
        Popen=start_backend, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(services, "threading", quiet)
    monkeypatch.setattr(backend_group, "subprocess", SimpleNamespace(
        Popen=start_nginx, run=check, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT))
    monkeypatch.setattr(backend_group, "threading", quiet)
    monkeypatch.setattr(backend_group, "_answers", answered)
    monkeypatch.setattr(backend_group, "clean_shutdown", lambda status=0: booted.stopped.append(status))
    # A start of its own: no flag an earlier test set, and no faked process
    # in the launcher's real list.
    monkeypatch.setattr(backend_group, "shutdown_flag", threading.Event())
    monkeypatch.setattr(lifecycle, "processes", [])
    booted.started = backend_group.boot(host, port, processes, nginx=NGINX)
    return booted
