"""A connection that sends no request is closed; one that does keeps its server.

Werkzeug's request handler under the backend and the standard library's under
the page server waited for a request line with no timeout. On 11-06 the hosted
stable backend held 867 connections from the internet that had sent nothing,
its 1024 open files were gone, and every request after them failed with "Too
many open files": every node showed "Missing node package".

Each test serves with the handler that server really uses, its deadline
(``request_start_timeout``) cut to a fraction of a second, and checks what a
client sees: a silent connection is closed by the server and its file goes,
while a request whose body comes late, a kept page connection's next request
and a Socket.IO WebSocket are not cut.
"""
from __future__ import annotations

import http.client
import os
import socket
import threading
import time
import urllib.request

import pytest
from werkzeug.serving import WSGIRequestHandler, make_server

DEADLINE_S = 0.5
SILENT = 20


def _open_files():
    for folder in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(folder):
            return len(os.listdir(folder))
    pytest.skip("this platform does not list a process's open files")
    return None


def _quick(handler):
    """*handler*, with a deadline a test can wait out."""
    return type(f"Quick{handler.__name__}", (handler,), {"request_start_timeout": DEADLINE_S})


def _ended_by_server(sock):
    """True when the server has closed *sock*: its read ends, or is reset."""
    sock.settimeout(0.2)
    try:
        return sock.recv(1) == b""
    except socket.timeout:
        return False
    except ConnectionResetError:
        return True


def _backend_handler():
    """The request handler the backend hands Werkzeug through Socket.IO."""
    from utk_curio.backend import server as backend_server

    return backend_server._socketio_run_kwargs().get("request_handler") or WSGIRequestHandler


def _serve(app, handler):
    httpd = make_server("127.0.0.1", 0, app, threaded=True, request_handler=_quick(handler))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


@pytest.fixture(scope="module")
def backend():
    """The backend app on its own request handler, in a thread."""
    from utk_curio.backend import server as backend_server

    httpd = _serve(backend_server.app, _backend_handler())
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_the_backend_closes_connections_that_send_no_request(backend):
    port = backend.server_port
    before = _open_files()
    silent = [socket.create_connection(("127.0.0.1", port)) for _ in range(SILENT)]
    try:
        time.sleep(DEADLINE_S + 1.5)
        still_open = sum(1 for sock in silent if not _ended_by_server(sock))
        assert still_open == 0, (
            f"{still_open} of {SILENT} connections that sent nothing were still open "
            f"{DEADLINE_S + 1.5:.1f}s after connecting, past the {DEADLINE_S}s deadline"
        )
        # The clients' own sockets are still open here; the server's are gone.
        assert _open_files() <= before + SILENT + 3
    finally:
        for sock in silent:
            sock.close()

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        assert response.status == 200
        assert response.read() == b"OK"


def test_a_request_whose_body_comes_after_the_deadline_is_answered():
    """The deadline covers the request line and headers only."""
    def echo(environ, start_response):
        body = environ["wsgi.input"].read(int(environ.get("CONTENT_LENGTH") or 0))
        start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
        return [body]

    httpd = _serve(echo, _backend_handler())
    try:
        with socket.create_connection(("127.0.0.1", httpd.server_port), timeout=10) as sock:
            sock.sendall(b"POST / HTTP/1.1\r\nHost: curio\r\nContent-Length: 5\r\n\r\n")
            time.sleep(DEADLINE_S * 3)
            sock.sendall(b"hello")
            reply = b""
            while chunk := sock.recv(4096):
                reply += chunk
        assert reply.startswith(b"HTTP/1.1 200"), reply[:80]
        assert reply.endswith(b"hello")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_socketio_websocket_outlives_the_deadline(backend):
    socketio = pytest.importorskip("socketio")
    client = socketio.Client(reconnection=False)
    client.connect(f"http://127.0.0.1:{backend.server_port}", transports=["websocket"], wait_timeout=10)
    try:
        time.sleep(DEADLINE_S * 4)
        assert client.connected, "the backend cut a WebSocket at the request deadline"
        assert client.transport() == "websocket"
    finally:
        client.disconnect()


@pytest.fixture
def page_server(tmp_path, monkeypatch):
    """``run_spa_static_server`` on its own handler, in a thread; returns its port."""
    from http.server import ThreadingHTTPServer

    from utk_curio.cli import static_server

    class QuickServer(ThreadingHTTPServer):
        def __init__(self, address, handler):
            super().__init__(address, _quick(handler))

    (tmp_path / "index.html").write_text("<!doctype html><title>curio</title>", encoding="utf-8")
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(static_server, "ThreadingHTTPServer", QuickServer)
    threading.Thread(
        target=static_server.run_spa_static_server, args=(str(tmp_path), port), daemon=True,
    ).start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=1).read()
            return port
        except OSError:
            time.sleep(0.05)
    pytest.fail("run_spa_static_server never came up")
    return None


def test_the_page_server_closes_connections_that_send_no_request(page_server):
    with socket.create_connection(("127.0.0.1", page_server)) as silent:
        time.sleep(DEADLINE_S + 1.5)
        assert _ended_by_server(silent), "the page server kept a connection that sent nothing"


def test_the_page_server_closes_a_kept_connection_once_it_goes_quiet(page_server):
    connection = http.client.HTTPConnection("127.0.0.1", page_server, timeout=10)
    try:
        connection.request("GET", "/index.html")
        first = connection.getresponse()
        assert first.status == 200
        first.read()
        # A second request inside the deadline is served on the same connection.
        connection.request("GET", "/index.html")
        second = connection.getresponse()
        assert second.status == 200
        second.read()
        time.sleep(DEADLINE_S + 1.5)
        assert _ended_by_server(connection.sock), "the page server kept an idle connection open"
    finally:
        connection.close()
