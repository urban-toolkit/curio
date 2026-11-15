"""Requests and sockets through a real nginx, with the config the launcher
writes at each start of several backend processes
(``utk_curio/cli/backend_group.nginx_config``).

nginx runs in front of four stand-ins for the backend processes of a start:
each a Flask app with Socket.IO in threading mode, served by Werkzeug with the
backend's own request handler, as a backend is, that says which process it is.
Through nginx:

* each request reaches the process that owns its dataflow: by the
  ``X-Curio-Dataflow`` header, else the ``dataflow`` query argument, else a
  dataflow id in the path; one that names no dataflow reaches home, and a call
  meant for a backend's internal route is answered 404 by nginx and reaches
  none;
* an upload larger than nginx's own default cap reaches its backend while it
  is still being sent;
* an event stream's first event reaches the page while the stream is open;
* a Socket.IO connection upgrades to a WebSocket at the process its handshake
  names, and one that polls first stays with that process;
* the backend sees the host the page asked for, and the address nginx was
  reached from last in ``X-Forwarded-For``.

The CI image installs nginx (Dockerfile) and the backend suite runs inside it,
so these run on every run of the suite. Without nginx or the launcher's
module they fail; they never skip.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest
from flask import Flask, Response, jsonify, request
from flask_socketio import SocketIO
from werkzeug.serving import WSGIRequestHandler, make_server

from utk_curio.common.request_deadline import RequestHeadDeadline

#: The backend processes of the start nginx fronts here.
PROCESSES = 4
MEGABYTE = 1024 * 1024
#: Three times what nginx takes by default (``client_max_body_size 1m``).
UPLOAD = 3 * MEGABYTE
#: How long a step may wait on another before the test fails.
PATIENCE_S = 20.0
#: A dataflow id each process owns: its first two hex digits, 0x40 and up,
#: modulo the process count.
OWNED = {number: f"{0x40 + number:02x}3a5c1e-0b4d-4c8e-9a7f-2d6b8e1c5a90" for number in range(PROCESSES)}

#: Never through a proxy the environment names: nginx is on 127.0.0.1.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class _Handler(RequestHeadDeadline, WSGIRequestHandler):
    """The backend's request handler (``backend/server.RequestHandler``)."""


class _Backend:
    """A stand-in for backend process *number*: it says which process it is
    and keeps the path of each request it gets, reads an upload as it comes,
    streams events, and serves Socket.IO."""

    def __init__(self, number: int):
        self.number = number
        self.paths: list[str] = []
        self.got_a_megabyte = threading.Event()
        self.first_event_read = threading.Event()
        app = Flask(f"backend-process-{number}")
        sockets = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

        @app.before_request
        def keep_the_path():
            self.paths.append(request.path)

        @app.post("/api/upload")
        def upload():
            digest, total = hashlib.sha256(), 0
            while chunk := request.stream.read(64 * 1024):
                digest.update(chunk)
                total += len(chunk)
                if total >= MEGABYTE:
                    self.got_a_megabyte.set()
            return jsonify(process=number, bytes=total, sha256=digest.hexdigest())

        @app.get("/api/stream")
        def stream():
            def events():
                yield "data: first\n\n"
                said = "second" if self.first_event_read.wait(PATIENCE_S * 2) else "nobody-read-the-first"
                yield f"data: {said}\n\n"

            return Response(events(), mimetype="text/event-stream")

        @app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
        @app.route("/<path:path>", methods=["GET", "POST"])
        def anything(path):
            return jsonify(process=number, path=request.path, host=request.headers.get("Host"),
                           forwardedFor=request.headers.get("X-Forwarded-For"))

        @sockets.on("which")
        def which():
            return {"process": number}

        self.server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=_Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, name=f"backend-process-{number}", daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _wait_until_it_listens(port: int, proxy: subprocess.Popen, log) -> None:
    deadline = time.monotonic() + PATIENCE_S
    while time.monotonic() < deadline:
        if proxy.poll() is not None:
            pytest.fail(f"nginx exited with code {proxy.returncode}:\n{log.read_text(errors='replace')}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.05)
    pytest.fail(f"nginx never listened on {port}:\n{log.read_text(errors='replace')}")


@pytest.fixture(scope="module")
def router(tmp_path_factory):
    """nginx, as the launcher configures it, in front of :data:`PROCESSES`
    stand-ins for the backend processes."""
    nginx = shutil.which("nginx")
    if not nginx:
        pytest.fail("nginx is not on PATH; the Docker image installs it, and the backend suite runs in that image")
    backend_group = importlib.import_module("utk_curio.cli.backend_group")
    backends = [_Backend(number) for number in range(PROCESSES)]
    folder = tmp_path_factory.mktemp("state") / "backend-router"
    folder.mkdir()
    port = _a_free_port()
    config = folder / "nginx.conf"
    config.write_text(backend_group.nginx_config(
        host="127.0.0.1", port=port, ports=[backend.port for backend in backends], folder=folder,
    ), encoding="utf-8")
    log = folder / "nginx.log"
    with open(log, "wb") as out:
        proxy = subprocess.Popen([nginx, "-c", str(config), "-e", "stderr"], stdout=out, stderr=subprocess.STDOUT)
    try:
        _wait_until_it_listens(port, proxy, log)
        yield SimpleNamespace(port=port, backends=backends, log=log)
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait()
        for backend in backends:
            backend.stop()


def _ask(router, path: str, *, headers=None, method: str = "GET") -> tuple[int, bytes]:
    asked = urllib.request.Request(f"http://127.0.0.1:{router.port}{path}", method=method, headers=headers or {})
    try:
        with _OPENER.open(asked, timeout=PATIENCE_S) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read()


def _process(router, path: str, headers=None) -> int:
    status, body = _ask(router, path, headers=headers)
    assert status == 200, f"{path} {headers}: {status} {body[:300]!r}"
    return json.loads(body)["process"]


def _read_to_the_end(sock: socket.socket) -> bytes:
    got = b""
    while chunk := sock.recv(65536):
        got += chunk
    return got


def _unchunked(head: bytes, body: bytes) -> bytes:
    if b"transfer-encoding: chunked" not in head.lower():
        return body
    out = b""
    while body:
        size_line, _, body = body.partition(b"\r\n")
        size = int(size_line.split(b";")[0], 16)
        if size == 0:
            break
        out, body = out + body[:size], body[size + 2:]
    return out


# ---------------------------------------------------------------------------
# Where each request goes
# ---------------------------------------------------------------------------

def test_each_dataflow_reaches_the_process_that_owns_it(router):
    from utk_curio.common.backend_processes import shard_of

    wrong = {}
    for lead in range(256):
        for prefix in (f"{lead:02x}", f"{lead:02X}"):
            dataflow = f"{prefix}000000-0000-4000-8000-000000000000"
            reached = _process(router, "/api/runs/1", headers={"X-Curio-Dataflow": dataflow})
            if reached != shard_of(dataflow, PROCESSES):
                wrong[dataflow] = reached
    assert wrong == {}, f"nginx sent these dataflows to a process that does not own them: {wrong}"


def test_the_header_decides_then_the_query_then_the_path_and_a_request_with_none_is_homes(router):
    from utk_curio.common.backend_processes import shard_of

    assert [shard_of(OWNED[number], PROCESSES) for number in range(PROCESSES)] == list(range(PROCESSES))
    one, two, three = OWNED[1], OWNED[2], OWNED[3]
    for why, path, headers, owner in (
        ("the header, over the query and the path", f"/api/projects/{three}/history?dataflow={two}",
         {"X-Curio-Dataflow": one}, 1),
        ("the query, over the path", f"/api/projects/{three}/history?dataflow={two}", {}, 2),
        ("a dataflow id after /projects/", f"/api/projects/{three}/history", {}, 3),
        ("the dataflow itself", f"/api/projects/{three}", {}, 3),
        ("a dataflow id after /dataflows/", f"/api/dataflows/{three}/datasets/install", {}, 3),
        ("no dataflow", "/api/packages", {}, 0),
        ("a run's id, which is no dataflow's", f"/api/runs/{three}", {}, 0),
        ("a route whose name starts with hex digits", "/api/projects/defaults", {}, 0),
        ("a header that names a dataflow with no hex start", f"/api/projects/{three}",
         {"X-Curio-Dataflow": "example-06-shadow-study"}, 0),
        ("a query that names a guest's new dataflow", f"/api/projects/{three}?dataflow=new-{three}", {}, 0),
    ):
        assert _process(router, path, headers) == owner, f"{why}: {path} {headers} did not reach process {owner}"


def test_a_call_to_a_backends_internal_route_is_answered_by_nginx_and_reaches_none(router):
    for path in (f"/internal/dataflows/{OWNED[1]}/agents.install",
                 f"/%69nternal/dataflows/{OWNED[2]}/agents.install",
                 f"//internal/dataflows/{OWNED[3]}/agents.install"):
        status, body = _ask(router, path, method="POST", headers={"X-Curio-Dataflow": OWNED[1]})
        assert status == 404, f"{path}: {status} {body[:300]!r}"
    reached = [path for backend in router.backends for path in backend.paths if "nternal" in path]
    assert reached == [], f"nginx passed calls to the backends' internal route on: {reached}"


def test_the_backend_sees_the_pages_host_and_the_address_nginx_was_reached_from(router):
    status, body = _ask(router, f"/api/projects/{OWNED[1]}", headers={"X-Forwarded-For": "203.0.113.9"})
    assert status == 200
    answer = json.loads(body)
    assert answer["process"] == 1
    assert answer["host"] == f"127.0.0.1:{router.port}"
    assert answer["forwardedFor"] == "203.0.113.9, 127.0.0.1", (
        "nginx must add the address it was reached from, the one the backend reads with one more proxy hop"
    )


# ---------------------------------------------------------------------------
# Uploads, event streams and sockets, as the backend serves them today
# ---------------------------------------------------------------------------

def test_an_upload_over_a_megabyte_reaches_its_backend_while_it_is_still_being_sent(router):
    backend = router.backends[2]
    backend.got_a_megabyte.clear()
    body = bytes(range(256)) * (UPLOAD // 256)
    half = len(body) // 2
    with socket.create_connection(("127.0.0.1", router.port), timeout=PATIENCE_S) as sock:
        sock.sendall((
            f"POST /api/upload HTTP/1.1\r\nHost: 127.0.0.1:{router.port}\r\n"
            f"X-Curio-Dataflow: {OWNED[2]}\r\nContent-Type: application/octet-stream\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode("ascii"))
        sock.sendall(body[:half])
        assert backend.got_a_megabyte.wait(PATIENCE_S), (
            "the backend had no megabyte of an upload half sent: nginx holds an upload until it is whole"
        )
        sock.sendall(body[half:])
        reply = _read_to_the_end(sock)
    head, _, rest = reply.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200"), reply[:500]
    assert json.loads(_unchunked(head, rest)) == {
        "process": 2, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
    }


def test_an_event_reaches_the_page_while_its_stream_is_open(router):
    backend = router.backends[3]
    backend.first_event_read.clear()
    got = b""
    with socket.create_connection(("127.0.0.1", router.port), timeout=PATIENCE_S) as sock:
        sock.sendall((
            f"GET /api/stream HTTP/1.1\r\nHost: 127.0.0.1:{router.port}\r\n"
            f"X-Curio-Dataflow: {OWNED[3]}\r\nAccept: text/event-stream\r\nConnection: close\r\n\r\n"
        ).encode("ascii"))
        try:
            while b"data: first" not in got:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            # No first event in time: the assertion below says nginx held it.
            pass
        assert b"data: first" in got, (
            f"no event reached the page while its stream was open: nginx holds a stream's events: {got[:500]!r}"
        )
        backend.first_event_read.set()
        got += _read_to_the_end(sock)
    assert b"data: second" in got, got[-500:]


@pytest.mark.parametrize("transports", [["websocket"], ["polling", "websocket"]])
def test_a_socket_reaches_the_process_its_handshake_names_and_upgrades(router, transports):
    import socketio

    client = socketio.Client(reconnection=False)
    client.connect(f"http://127.0.0.1:{router.port}?dataflow={OWNED[1]}", transports=transports,
                   wait_timeout=PATIENCE_S)
    try:
        answered = client.call("which", timeout=PATIENCE_S)
        transport = client.transport()
    finally:
        client.disconnect()
    assert answered == {"process": 1}, f"the socket reached {answered}, not the process its handshake names"
    if transports == ["websocket"]:
        assert transport == "websocket", "nginx did not pass the WebSocket upgrade"


def test_a_socket_that_names_no_dataflow_is_homes(router):
    import socketio

    client = socketio.Client(reconnection=False)
    client.connect(f"http://127.0.0.1:{router.port}", transports=["websocket"], wait_timeout=PATIENCE_S)
    try:
        answered = client.call("which", timeout=PATIENCE_S)
    finally:
        client.disconnect()
    assert answered == {"process": 0}, f"a socket that names no dataflow reached {answered}"
