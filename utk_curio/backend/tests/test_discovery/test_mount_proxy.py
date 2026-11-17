"""The bucket mount service's way out: the backend's CONNECT proxy
(``discovery/infrastructure/mount_proxy.py``).

Everything runs on loopback, which the suite's network guard lets through:
the proxy on 127.0.0.1, and an upstream on 127.0.0.1 that the tests admit
under a made-up name. The host check is injected. The tunnels' tests pass the
tests' own rule, which takes the upstream's loopback address as public and
leaves every other answer to Curio's policy; the refusals of a private
address use the policy itself.
"""

from __future__ import annotations

import logging
import socket
import socketserver
import threading
import time

import pytest

from utk_curio.backend.app.common import egress_policy
from utk_curio.backend.app.discovery.infrastructure import mount_proxy
from utk_curio.backend.app.discovery.infrastructure.mount_proxy import MountProxy

UPSTREAM_NAME = "bucket.example.org"

#: The tests' DNS: the upstream's name answers its loopback address.
DNS = {
    UPSTREAM_NAME: ["127.0.0.1"],
    "private.example.org": ["10.0.0.5"],
    "metadata.example.org": ["169.254.169.254"],
}


def fake_dns(host):
    try:
        return DNS[host]
    except KeyError:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None


def loopback_upstream_is_public(host):
    """The tests' rule: the upstream's own loopback answer passes; any other
    answer is Curio's policy's to judge."""
    if fake_dns(host) == ["127.0.0.1"]:
        return ["127.0.0.1"]
    return egress_policy.public_addresses(host, resolver=fake_dns)


class _Shouter(socketserver.BaseRequestHandler):
    """The upstream: answers each read with it in capitals, so a reply proves
    it went there and back."""

    def handle(self):
        self.request.settimeout(10)
        while True:
            try:
                data = self.request.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.request.sendall(data.upper())


class _Upstream(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def handle_error(self, request, client_address):
        # A tunnel the test closed mid-read; nothing to report.
        return


@pytest.fixture
def upstream():
    server = _Upstream(("127.0.0.1", 0), _Shouter)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest.fixture
def start_proxy():
    """Start a proxy on loopback with the given settings; the port it listens on."""
    started = []

    def start(**settings):
        settings.setdefault("addresses_of", loopback_upstream_is_public)
        proxy = MountProxy(**settings)
        port = proxy.start("127.0.0.1", 0)
        started.append(proxy)
        return proxy, port

    yield start
    for proxy in started:
        proxy.stop()


def connect(port):
    client = socket.create_connection(("127.0.0.1", port), timeout=10)
    client.settimeout(10)
    return client


def head_of(client):
    """The proxy's answer head, read a byte at a time, so nothing the tunnel
    sends after it is taken with it."""
    data = b""
    while not data.endswith(b"\r\n\r\n"):
        chunk = client.recv(1)
        if not chunk:
            break
        data += chunk
    return data.decode("latin-1")


def tunnel(port, target, extra=b""):
    client = connect(port)
    client.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode() + extra)
    return client, head_of(client)


def read_exactly(client, size):
    data = b""
    while len(data) < size:
        chunk = client.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


class TestTunnels:
    def test_an_admitted_host_is_tunnelled_both_ways(self, start_proxy, upstream):
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)

        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}")
        try:
            assert head == "HTTP/1.1 200 Connection established\r\n\r\n"
            client.sendall(b"tls hello")
            assert read_exactly(client, 9) == b"TLS HELLO"
            client.sendall(b"and more")
            assert read_exactly(client, 8) == b"AND MORE"
        finally:
            client.close()

    def test_bytes_sent_with_the_head_go_through_too(self, start_proxy, upstream):
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)

        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}", extra=b"early")
        try:
            assert head.startswith("HTTP/1.1 200 ")
            assert read_exactly(client, 5) == b"EARLY"
        finally:
            client.close()

    def test_it_connects_to_the_address_it_checked_and_never_looks_the_name_up_again(
            self, start_proxy, upstream, monkeypatch):
        looked_up = []
        real = socket.getaddrinfo

        def getaddrinfo(host, *args, **kwargs):
            looked_up.append(host)
            return real(host, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
        checked = []

        def check(host):
            checked.append(host)
            return loopback_upstream_is_public(host)

        proxy, port = start_proxy(addresses_of=check)
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)

        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}")
        client.close()

        assert head.startswith("HTTP/1.1 200 ")
        assert checked == [UPSTREAM_NAME]
        assert UPSTREAM_NAME not in looked_up

    def test_a_withdrawn_host_is_refused_again(self, start_proxy, upstream):
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)
        proxy.admit("source.example.other@1", UPSTREAM_NAME, upstream)

        proxy.withdraw("source.example.bucket@1")
        assert proxy.admits(UPSTREAM_NAME, upstream)
        proxy.withdraw("source.example.other@1")
        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}")
        client.close()

        assert head.startswith("HTTP/1.1 403 ")

    def test_an_idle_tunnel_is_closed(self, start_proxy, upstream):
        proxy, port = start_proxy(idle_seconds=0.3)
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)

        # Measured from before the tunnel opens, so the bound holds however
        # late this thread reads.
        started = time.monotonic()
        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}")
        try:
            assert head.startswith("HTTP/1.1 200 ")
            assert client.recv(1) == b""
            assert 0.3 <= time.monotonic() - started < 5
        finally:
            client.close()


class TestRefusals:
    def _refused(self, start_proxy, upstream, target, *, request=None):
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)
        client = connect(port)
        try:
            client.sendall(request or f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
            return head_of(client)
        finally:
            client.close()

    def test_a_host_not_admitted(self, start_proxy, upstream, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)

        head = self._refused(start_proxy, upstream, f"other.example.org:{upstream}")

        # Curio's proxy refused it, which rclone's error repeats: never a
        # bare Forbidden, which reads as the bucket's own answer.
        assert head.startswith(
            "HTTP/1.1 403 Curio's bucket mount proxy refused the request: "
            "it is not the host and port of a source being mounted\r\n"
        ), head
        assert any(f"other.example.org:{upstream}" in record.getMessage()
                   and "not the host and port of a source being mounted" in record.getMessage()
                   for record in caplog.records)

    def test_another_port_of_an_admitted_host(self, start_proxy, upstream):
        head = self._refused(start_proxy, upstream, f"{UPSTREAM_NAME}:{upstream + 1}")

        assert head.startswith("HTTP/1.1 403 ")

    @pytest.mark.parametrize("host", ["private.example.org", "metadata.example.org"])
    def test_an_admitted_host_whose_address_is_not_public(self, start_proxy, upstream, host, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)
        policy = lambda name: egress_policy.public_addresses(name, resolver=fake_dns)  # noqa: E731
        proxy, port = start_proxy(addresses_of=policy)
        proxy.admit("source.example.bucket@1", host, upstream)

        client, head = tunnel(port, f"{host}:{upstream}")
        client.close()

        assert head.startswith("HTTP/1.1 403 Curio's bucket mount proxy refused the request: "), head
        assert "non-public address" in head.split("\r\n", 1)[0]
        assert any(host in record.getMessage() and "non-public address" in record.getMessage()
                   for record in caplog.records)

    def test_a_request_that_is_not_connect(self, start_proxy, upstream, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)
        request = f"GET http://{UPSTREAM_NAME}:{upstream}/key?token=abc HTTP/1.1\r\nHost: x\r\n\r\n".encode()

        head = self._refused(start_proxy, upstream, None, request=request)

        assert head.startswith(
            "HTTP/1.1 405 Curio's bucket mount proxy refused the request: "
            "it asked GET, and the proxy takes CONNECT alone\r\n"
        ), head
        assert "Allow: CONNECT\r\n" in head
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert UPSTREAM_NAME in messages
        # The host alone is logged, never the path or the query, and the
        # answer holds neither.
        assert "token" not in messages and "/key" not in messages
        assert "token" not in head and "/key" not in head

    @pytest.mark.parametrize("request_line", [
        b"CONNECT bucket.example.org HTTP/1.1",
        b"CONNECT bucket.example.org:99999 HTTP/1.1",
        b"CONNECT bad_host!:443 HTTP/1.1",
        b"CONNECT [::1 HTTP/1.1",
        b"NOT A REQUEST",
    ], ids=["no-port", "port-too-big", "bad-host", "unclosed-bracket", "not-a-request"])
    def test_a_malformed_request(self, start_proxy, upstream, request_line):
        head = self._refused(start_proxy, upstream, None, request=request_line + b"\r\n\r\n")

        assert head.startswith("HTTP/1.1 400 ")

    def test_a_head_that_does_not_end_in_time(self, start_proxy):
        _proxy, port = start_proxy(head_seconds=0.3)
        client = connect(port)
        try:
            client.sendall(b"CONNECT bucket.example.org:443 HTTP/1.1\r\n")
            assert head_of(client).startswith("HTTP/1.1 408 ")
        finally:
            client.close()

    def test_a_head_that_is_too_long(self, start_proxy):
        _proxy, port = start_proxy()
        client = connect(port)
        try:
            client.sendall(b"CONNECT bucket.example.org:443 HTTP/1.1\r\nX: " + b"a" * 9000)
            assert head_of(client).startswith("HTTP/1.1 431 ")
        finally:
            client.close()

    def test_a_65th_tunnel(self, start_proxy, upstream):
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)
        target = f"{UPSTREAM_NAME}:{upstream}"
        open_now = []
        try:
            for _ in range(mount_proxy.MAX_TUNNELS):
                client, head = tunnel(port, target)
                open_now.append(client)
                assert head.startswith("HTTP/1.1 200 "), head
            extra, head = tunnel(port, target)
            open_now.append(extra)
            assert head.startswith(
                f"HTTP/1.1 503 Curio's bucket mount proxy refused the request: "
                f"{mount_proxy.MAX_TUNNELS} tunnels are open\r\n"
            ), head
            # The 64 still work.
            open_now[0].sendall(b"ok")
            assert read_exactly(open_now[0], 2) == b"OK"
        finally:
            for client in open_now:
                client.close()

    def test_an_admitted_host_that_takes_no_connection(self, start_proxy, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)
        # A port of loopback that nothing listens on: the upstream refuses.
        with socket.create_server(("127.0.0.1", 0)) as gone:
            closed = gone.getsockname()[1]
        proxy, port = start_proxy()
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, closed)

        client, head = tunnel(port, f"{UPSTREAM_NAME}:{closed}")
        client.close()

        assert head.startswith(
            "HTTP/1.1 502 Curio's bucket mount proxy refused the request: "
            "none of the host's addresses took a connection: "
        ), head
        assert any(f"{UPSTREAM_NAME}:{closed}" in record.getMessage()
                   and "none of the host's addresses took a connection" in record.getMessage()
                   for record in caplog.records)

    def test_why_is_one_line_of_printable_ascii_in_the_answer(self):
        """A reason holds what the host check or the system said, which
        could hold anything: the status line stays one line a client reads."""
        phrase = mount_proxy._phrase("line one\r\nX-Injected: yes é" + "x" * 500)

        assert phrase.startswith("Curio's bucket mount proxy refused the request: line one??X-Injected: yes ?")
        assert all(" " <= char <= "~" for char in phrase)
        assert len(phrase) == len(mount_proxy.REFUSAL) + 2 + mount_proxy.WHY_CHARS

    def test_a_tunnel_closed_frees_its_place(self, start_proxy, upstream):
        proxy, port = start_proxy(max_tunnels=1)
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)
        target = f"{UPSTREAM_NAME}:{upstream}"

        first, head = tunnel(port, target)
        assert head.startswith("HTTP/1.1 200 ")
        second, head = tunnel(port, target)
        second.close()
        assert head.startswith("HTTP/1.1 503 ")
        first.close()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            third, head = tunnel(port, target)
            third.close()
            if head.startswith("HTTP/1.1 200 "):
                break
            time.sleep(0.05)
        assert head.startswith("HTTP/1.1 200 ")


class TestTheSelfTestsAsk:
    """A host the self-test expects (``bucket_mounts.reaches_proxy``) is
    heard, then refused, and never admitted, looked up or connected to."""

    HOST = "selftest-0123456789abcdef0123456789abcdef.curio-bucket-mounts.invalid"

    def test_an_expected_host_is_heard_then_refused_and_never_looked_up(self, start_proxy, caplog):
        caplog.set_level(logging.INFO, logger=mount_proxy.__name__)
        checked = []

        def check(host):
            checked.append(host)
            return loopback_upstream_is_public(host)

        proxy, port = start_proxy(addresses_of=check)
        proxy.expect(self.HOST, 443)
        assert not proxy.heard(self.HOST, 443)

        client, head = tunnel(port, f"{self.HOST}:443")
        client.close()

        assert head.startswith(
            "HTTP/1.1 403 Curio's bucket mount proxy refused the request: the self-test reached it\r\n"
        ), head
        assert proxy.heard(self.HOST, 443)
        assert checked == []
        assert not proxy.admits(self.HOST, 443)
        messages = " ".join(record.getMessage() for record in caplog.records)
        # Its name, which only the self-test may know, is neither logged nor answered.
        assert "self-test" in messages and self.HOST not in messages
        assert self.HOST not in head

    def test_another_port_of_it_is_refused_as_any_host_and_not_heard(self, start_proxy, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)
        proxy, port = start_proxy()
        proxy.expect(self.HOST, 443)

        client, head = tunnel(port, f"{self.HOST}:8443")
        client.close()

        assert head.startswith("HTTP/1.1 403 ")
        assert not proxy.heard(self.HOST, 443)
        assert any("not the host and port of a source being mounted" in record.getMessage()
                   for record in caplog.records)

    def test_a_host_forgotten_is_refused_as_any_host_and_not_heard(self, start_proxy, caplog):
        caplog.set_level(logging.WARNING, logger=mount_proxy.__name__)
        proxy, port = start_proxy()
        proxy.expect(self.HOST, 443)
        proxy.forget(self.HOST, 443)

        client, head = tunnel(port, f"{self.HOST}:443")
        client.close()

        assert head.startswith("HTTP/1.1 403 ")
        assert not proxy.heard(self.HOST, 443)
        assert any("not the host and port of a source being mounted" in record.getMessage()
                   for record in caplog.records)


class TestStopping:
    def test_stop_ends_its_tunnels_and_listens_no_more(self, upstream):
        proxy = MountProxy(addresses_of=loopback_upstream_is_public)
        port = proxy.start("127.0.0.1", 0)
        proxy.admit("source.example.bucket@1", UPSTREAM_NAME, upstream)
        client, head = tunnel(port, f"{UPSTREAM_NAME}:{upstream}")
        assert head.startswith("HTTP/1.1 200 ")

        proxy.stop()

        try:
            assert client.recv(1) == b""
        finally:
            client.close()
        assert not proxy.listening
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=2).close()
