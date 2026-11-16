"""The launcher's start of several backend processes, with every process faked
(``utk_curio/cli/backend_group.py``).

:func:`boot` runs ``backend_group.boot`` as the launcher's thread runs it, on
the test's own thread: no process starts, no server's ``/health`` is asked and
nginx never runs. Each start keeps what it would have started (its command and
its environment), and the starts, the waits for each server and nginx's check
of its config are kept in the order they came. The launcher's modules are
imported inside :func:`boot`, so a checkout without them fails each test that
boots, on its own.

:class:`AnotherBackend` is another backend process of a start, as the process
under test reaches it over 127.0.0.1: a server in the test that keeps each
call it gets.
"""

from __future__ import annotations

import importlib
import itertools
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Callable, Optional

#: Where the faked nginx is said to be; nothing runs it.
NGINX = "/usr/sbin/nginx"

_pids = itertools.count(40000)


class FakeProcess:
    """A server that never ran: ``poll`` answers :attr:`exit_code`, None while
    it is said to run. :attr:`env` is the environment it was given, None when
    it was given none and so would inherit the launcher's."""

    def __init__(self, args, env):
        self.args = list(args)
        self.env = None if env is None else dict(env)
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
    #: Each ``nginx -t``: its command and its environment, None when it was
    #: given none.
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
        env = kwargs.get("env")
        booted.checks.append((list(args), None if env is None else dict(env)))
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


class AnotherBackend:
    """Another backend process of a start, as the process under test reaches
    it over 127.0.0.1 at the port ``CURIO_BACKEND_PORTS`` names for it: a
    server in the test that keeps each call it gets in :attr:`calls` and
    answers it as a backend's internal route does, ``{"ok": true, "result":
    ...}``. The last part of a call's path is its step. :attr:`results` says
    what a step answers, a value or a function of the call's ``arguments``,
    and ``{}`` otherwise; :attr:`failing` names the steps that fail, with
    their error. A context manager: it serves inside the block."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.results: dict = {}
        self.failing: dict = {}
        self._lock = threading.Lock()
        self._server = None
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._server.server_port

    def steps(self) -> list:
        """Each call's step and arguments, in the order they came."""
        with self._lock:
            return [(call["step"], call["arguments"]) for call in self.calls]

    def __call__(self, environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = json.loads(environ["wsgi.input"].read(length) or b"{}")
        path = environ.get("PATH_INFO", "")
        step, arguments = path.rsplit("/", 1)[-1], body.get("arguments")
        with self._lock:
            self.calls.append({"path": path, "step": step, "arguments": arguments, "at": time.monotonic(),
                               "token": environ.get("HTTP_X_CURIO_BACKEND_TOKEN")})
        if step in self.failing:
            answer = {"ok": False, "error": self.failing[step]}
        else:
            result = self.results.get(step, {})
            answer = {"ok": True, "result": result(arguments) if callable(result) else result}
        reply = json.dumps(answer).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(reply)))])
        return [reply]

    def __enter__(self) -> "AnotherBackend":
        from werkzeug.serving import make_server

        self._server = make_server("127.0.0.1", 0, self, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, name="another-backend", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc) -> bool:
        self._server.shutdown()
        self._thread.join(timeout=5)
        return False
