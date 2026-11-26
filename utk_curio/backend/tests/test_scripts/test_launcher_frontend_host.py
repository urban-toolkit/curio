"""The frontend listens on ``--frontend-host``, as the backend and the sandbox
listen on theirs.

``--frontend-host`` (default ``localhost``) reached only the launcher's
"Starting frontend on ..." line. The page server bound ``0.0.0.0`` and the
webpack dev server, given no host, every interface, so a plain local
``curio.py start`` served the canvas to every machine on the network. A
container, whose published port needs the wider address, now asks for it with
``--frontend-host 0.0.0.0``, as it asks with ``--backend-host 0.0.0.0``
(``frontendHostInContainers.test.ts`` checks each one). ``localhost`` is
``127.0.0.1`` for both servers, as an IPv4 client such as
``scripts/test.sh``'s wait reaches it.
"""
from __future__ import annotations

import io
import socket
import subprocess
from types import SimpleNamespace

import pytest

from utk_curio.cli import services, static_server

PORT = 18123


class _Bound(Exception):
    """Raised by the stand-in for the page server's socket, once it is bound."""


@pytest.fixture
def launched(monkeypatch, tmp_path):
    """``start_frontend`` with nothing to build, no port to free and no thread
    to stream a server's output; each command it starts, in a list."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(services, "_kill_port", lambda port: None)
    monkeypatch.setattr(services, "_frontend_must_build", lambda force_rebuild: False)
    monkeypatch.setattr(services, "_frontend_is_built", lambda: True)
    monkeypatch.setattr(services, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: None),
    ))
    commands = []

    def popen(cmd, **kwargs):
        commands.append(cmd)
        return SimpleNamespace(args=cmd, poll=lambda: None, stdout=io.StringIO(""))

    monkeypatch.setattr(services, "subprocess", SimpleNamespace(
        Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT,
        CalledProcessError=subprocess.CalledProcessError,
        TimeoutExpired=subprocess.TimeoutExpired,
    ))
    return commands


HOSTS = ["127.0.0.1", "localhost", "0.0.0.0"]


def _listens_on(host):
    """The address for *host*: ``localhost`` as ``127.0.0.1``, which both
    servers then take, where Node alone would take ``::1`` on macOS."""
    return "127.0.0.1" if host == "localhost" else host


@pytest.mark.parametrize("host", HOSTS)
def test_the_page_server_listens_on_the_frontend_host(host, launched, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "0")
    services.start_frontend(host, PORT)

    [command] = launched
    assert command[1:3] == ["-u", "-c"]
    # The page server's own process runs this code: run it here, with its
    # server's socket in place of the real one.
    bound = []

    def server(address, handler):
        bound.append(address)
        raise _Bound

    monkeypatch.setattr(static_server, "ThreadingHTTPServer", server)
    with pytest.raises(_Bound):
        exec(command[3], {})
    assert bound == [(_listens_on(host), PORT)]


@pytest.mark.parametrize("host", HOSTS)
def test_the_dev_server_listens_on_the_frontend_host(host, launched, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "1")
    monkeypatch.delenv("CURIO_NO_OPEN", raising=False)
    services.start_frontend(host, PORT)

    [command] = launched
    assert command[:3] == ["npm", "run", "start"]
    options = command[command.index("--") + 1:]
    assert options[options.index("--port") + 1] == str(PORT)
    assert "--host" in options
    assert options[options.index("--host") + 1] == _listens_on(host)
    # The page it opens keeps the origin of --frontend-host.
    if _listens_on(host) != host:
        assert options[-3:] == ["--open-reset", "--open-target", f"http://{host}:{PORT}/"]
    else:
        assert "--open-target" not in options


def test_a_dev_server_that_opens_no_page_is_given_no_page_to_open(launched, monkeypatch):
    monkeypatch.setenv("CURIO_DEV", "1")
    monkeypatch.setenv("CURIO_NO_OPEN", "1")
    services.start_frontend("localhost", PORT)

    [command] = launched
    assert "--no-open" in command
    assert "--open-target" not in command


@pytest.mark.parametrize("host, family", [
    ("127.0.0.1", socket.AF_INET),
    ("0.0.0.0", socket.AF_INET),
    ("::1", socket.AF_INET6),
    ("::", socket.AF_INET6),
])
def test_the_page_server_takes_an_ipv6_host_on_an_ipv6_socket(host, family):
    # The IPv4 socket of ThreadingHTTPServer cannot bind an IPv6 address.
    assert static_server._server_class(host).address_family == family
