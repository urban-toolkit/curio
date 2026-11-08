"""The bucket mount service's one way out: a CONNECT proxy in the backend.

The mount service (``docker-compose.bucket-mounts.yml``) sits on an internal
network with Curio's container alone, and its ``HTTPS_PROXY`` names this
proxy, ``curio:3128`` (``bucket_mounts.PROXY_PORT``). The proxy listens where
the backend listens (``--backend-host``, every interface in a deployment; the
port is never published), on a thread of the backend that ``server.py``'s
``serve()`` starts when ``--bucket-mounts-dir`` and ``--bucket-mount-socket``
name a service (``application/bucket_mount_sources.py``).

It tunnels HTTPS, and only to where a source being mounted is:

- ``CONNECT host:port`` only; any other request is answered 405. Its head must
  come within :data:`HEAD_SECONDS` and hold at most :data:`MAX_HEAD_BYTES`.
- Only to a (host, port) admitted now (:meth:`MountProxy.admit`): the host of
  a source the backend mounts; 403 otherwise.
- Every address the host resolves to must pass Curio's egress policy
  (``egress_policy.public_addresses``), and the tunnel connects to one of
  those very addresses, never to the name, so a second lookup cannot send it
  elsewhere. A check before mounting alone would leave rclone's later lookups
  open to a name that turns private, and rclone would hand what an internal
  service answers to node code as a file.
- ``HTTP/1.1 200 Connection established``, then bytes both ways until either
  side closes or :data:`IDLE_SECONDS` pass with nothing sent; at most
  :data:`MAX_TUNNELS` at once (503 beyond).

Each refusal is logged with the host and why. Through a tunnel pass only TLS
bytes: no path, header or key of what rclone asks is read here.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import selectors
import socket
import threading
import time
from typing import Callable, Optional
from urllib.parse import urlsplit

from utk_curio.backend.app.common import egress_policy

log = logging.getLogger(__name__)

#: How long a connection has to send its request head, and its most bytes.
HEAD_SECONDS = 5.0
MAX_HEAD_BYTES = 8192
#: Tunnels open at once, at most; and connections still sending their head
#: beyond those, which more are closed at once to bound the threads.
MAX_TUNNELS = 64
MAX_WAITING = 16
#: A tunnel that sends nothing either way for this long is closed.
IDLE_SECONDS = 300.0
#: The deadline of the connection to each of the host's addresses.
CONNECT_SECONDS = 10.0
#: How much a tunnel reads from one side before it sends it to the other.
CHUNK_BYTES = 64 * 1024
#: How often the listening thread looks whether it should stop.
ACCEPT_POLL_SECONDS = 0.5
#: How long, and for how many reads, a refused connection is read and dropped
#: before it closes.
LINGER_SECONDS = 0.5
LINGER_READS = 4

_REASONS = {
    400: "Bad Request",
    403: "Forbidden",
    405: "Method Not Allowed",
    408: "Request Timeout",
    431: "Request Header Fields Too Large",
    502: "Bad Gateway",
    503: "Service Unavailable",
}

#: A host name as the proxy takes one: labels of letters, digits and dashes.
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$")


class _Refused(Exception):
    """A request the proxy answers with *status* and closes, and why."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status = status
        self.why = why


class _Gone(Exception):
    """The client closed before it said where to."""


class MountProxy:
    """A CONNECT proxy to the hosts of the sources being mounted.

    *addresses_of* is the host check: the addresses of a host to connect to,
    each one checked, or :class:`egress_policy.EgressRefused`. It is
    ``egress_policy.public_addresses`` unless a test gives its own rule.
    """

    def __init__(self, *, addresses_of: Optional[Callable[[str], list]] = None,
                 max_tunnels: int = MAX_TUNNELS, idle_seconds: float = IDLE_SECONDS,
                 head_seconds: float = HEAD_SECONDS, connect_seconds: float = CONNECT_SECONDS):
        self._addresses_of = addresses_of
        self.max_tunnels = max_tunnels
        self.idle_seconds = idle_seconds
        self.head_seconds = head_seconds
        self.connect_seconds = connect_seconds
        self._lock = threading.Lock()
        self._admitted: dict[tuple[str, int], set[str]] = {}
        self._tunnels = threading.BoundedSemaphore(max_tunnels)
        self._connections = threading.BoundedSemaphore(max_tunnels + MAX_WAITING)
        self._listener: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._open: set[socket.socket] = set()

    # ── who may be reached ─────────────────────────────────────────────────

    def admit(self, name: str, host: str, port: int) -> None:
        """Let tunnels reach *host* at *port*, for the source mounted as *name*."""
        with self._lock:
            self._admitted.setdefault((host.lower(), int(port)), set()).add(name)

    def withdraw(self, name: str) -> None:
        """The source mounted as *name* needs its host no more."""
        with self._lock:
            for key in list(self._admitted):
                names = self._admitted[key]
                names.discard(name)
                if not names:
                    del self._admitted[key]

    def admits(self, host: str, port: int) -> bool:
        with self._lock:
            return (host.lower(), int(port)) in self._admitted

    # ── serving ────────────────────────────────────────────────────────────

    def start(self, host: str, port: int) -> int:
        """Listen on *host* at *port* (0 picks a free one), on a thread of its
        own; the port it listens on. Raises ``OSError`` when it cannot."""
        with self._lock:
            if self._listener is not None:
                return self._listener.getsockname()[1]
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            listener = socket.create_server((host, port), family=family)
            listener.settimeout(ACCEPT_POLL_SECONDS)
            self._listener = listener
            self._stopping.clear()
            self._thread = threading.Thread(target=self._serve, args=(listener,),
                                            name="bucket-mount-proxy", daemon=True)
            self._thread.start()
            return listener.getsockname()[1]

    @property
    def listening(self) -> bool:
        with self._lock:
            return self._listener is not None

    def stop(self) -> None:
        """Stop listening and end every tunnel."""
        with self._lock:
            listener, self._listener = self._listener, None
            thread, self._thread = self._thread, None
            self._stopping.set()
            open_now = list(self._open)
        for sock in open_now:
            _shut(sock)
        if listener is not None:
            listener.close()
        if thread is not None:
            thread.join(timeout=5)

    def _serve(self, listener: socket.socket) -> None:
        while not self._stopping.is_set():
            try:
                client, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self._stopping.is_set():
                    return
                # Out of file descriptors, or a connection reset before it
                # was taken: wait a little rather than spin.
                time.sleep(ACCEPT_POLL_SECONDS)
                continue
            if not self._connections.acquire(blocking=False):
                log.warning("Bucket mount proxy refused a connection from %s: %d connections are open",
                            peer[0] if peer else "?", self.max_tunnels + MAX_WAITING)
                client.close()
                continue
            try:
                threading.Thread(target=self._handle, args=(client,),
                                 name="bucket-mount-proxy-tunnel", daemon=True).start()
            except RuntimeError as exc:
                log.warning("Bucket mount proxy could not start a tunnel's thread: %s", exc)
                client.close()
                self._connections.release()

    def _handle(self, client: socket.socket) -> None:
        self._track(client)
        upstream: Optional[socket.socket] = None
        where = "a request"
        try:
            head, rest = self._read_head(client)
            method, target = _request_line(head)
            if method != "CONNECT":
                where = _host_of_target(target) or where
                raise _Refused(405, f"it asked {method[:16]}, and the proxy takes CONNECT alone")
            host, port = _authority(target)
            where = f"{host}:{port}"
            if not self.admits(host, port):
                raise _Refused(403, "it is not the host and port of a source being mounted")
            addresses_of = self._addresses_of or egress_policy.public_addresses
            try:
                addresses = list(addresses_of(host))
            except egress_policy.EgressRefused as refused:
                raise _Refused(403, str(refused)) from None
            if not self._tunnels.acquire(blocking=False):
                raise _Refused(503, f"{self.max_tunnels} tunnels are open")
            try:
                upstream = self._connect(addresses, port)
                self._track(upstream)
                client.settimeout(self.idle_seconds)
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
                self._relay(client, upstream)
            finally:
                self._tunnels.release()
        except _Refused as refused:
            log.warning("Bucket mount proxy refused %s: %s", where, refused.why)
            _answer(client, refused.status)
        except _Gone:
            log.debug("Bucket mount proxy: a connection closed before it said where to")
        except OSError as exc:
            log.info("Bucket mount proxy: the tunnel to %s ended: %s", where, exc)
        finally:
            for sock in (upstream, client):
                if sock is not None:
                    self._untrack(sock)
                    sock.close()
            self._connections.release()

    def _read_head(self, client: socket.socket) -> tuple[bytes, bytes]:
        """The request head, and what came after it."""
        data = b""
        deadline = time.monotonic() + self.head_seconds
        while True:
            end = data.find(b"\r\n\r\n")
            if end > MAX_HEAD_BYTES or (end < 0 and len(data) > MAX_HEAD_BYTES):
                raise _Refused(431, f"its request head is over {MAX_HEAD_BYTES} bytes")
            if end >= 0:
                return data[:end], data[end + 4:]
            left = deadline - time.monotonic()
            if left <= 0:
                raise _Refused(408, f"it sent no request head within {self.head_seconds:g} s")
            client.settimeout(left)
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                raise _Refused(408, f"it sent no request head within {self.head_seconds:g} s") from None
            if not chunk:
                raise _Gone()
            data += chunk

    def _connect(self, addresses: list, port: int) -> socket.socket:
        """A connection to one of *addresses*, the checked ones, in turn:
        IPv4 first, since a container often has no route for IPv6."""
        last: Optional[OSError] = None
        for address in sorted(addresses, key=lambda text: ":" in str(text)):
            try:
                ip = ipaddress.ip_address(str(address))
            except ValueError:
                continue
            family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
            upstream = socket.socket(family, socket.SOCK_STREAM)
            upstream.settimeout(self.connect_seconds)
            try:
                upstream.connect((str(ip), port))
            except OSError as exc:
                upstream.close()
                last = exc
                continue
            return upstream
        raise _Refused(502, f"none of its addresses took a connection: {last}")

    def _relay(self, client: socket.socket, upstream: socket.socket) -> None:
        """Bytes both ways until a side closes or nothing passes for the idle bound."""
        for sock in (client, upstream):
            # A send the other side does not take for that long ends it too.
            sock.settimeout(self.idle_seconds)
        with selectors.DefaultSelector() as selector:
            selector.register(client, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, client)
            last = time.monotonic()
            while True:
                left = last + self.idle_seconds - time.monotonic()
                if left <= 0:
                    log.debug("Bucket mount proxy: a tunnel idle for %g s closed", self.idle_seconds)
                    return
                for key, _events in selector.select(left):
                    data = key.fileobj.recv(CHUNK_BYTES)
                    if not data:
                        return
                    key.data.sendall(data)
                    last = time.monotonic()

    def _track(self, sock: socket.socket) -> None:
        with self._lock:
            self._open.add(sock)

    def _untrack(self, sock: socket.socket) -> None:
        with self._lock:
            self._open.discard(sock)


def _request_line(head: bytes) -> tuple[str, str]:
    """The method and the target of the request line."""
    line = head.split(b"\r\n", 1)[0]
    try:
        text = line.decode("ascii")
    except UnicodeDecodeError:
        raise _Refused(400, "its request line is not ASCII") from None
    parts = text.split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/1.") or not parts[0].isalpha():
        raise _Refused(400, "its request line is malformed")
    return parts[0], parts[1]


def _authority(target: str) -> tuple[str, int]:
    """A CONNECT target's host, lowercased, and port."""
    if target.startswith("["):
        close = target.find("]")
        if close < 0 or target[close + 1:close + 2] != ":":
            raise _Refused(400, "its target is not host:port")
        host, port_text = target[1:close], target[close + 2:]
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            raise _Refused(400, "its target's address is malformed") from None
    else:
        host, colon, port_text = target.rpartition(":")
        if not colon or not _HOST_RE.match(host.lower()):
            raise _Refused(400, "its target is not host:port")
    if not (port_text.isdigit() and len(port_text) <= 5 and 0 < int(port_text) < 65536):
        raise _Refused(400, "its target's port is malformed")
    return host.lower(), int(port_text)


def _host_of_target(target: str) -> Optional[str]:
    """The host of a request's target, for the log: never its path or query."""
    try:
        return urlsplit(target).hostname
    except ValueError:
        return None


def _answer(client: socket.socket, status: int) -> None:
    """Answer *status* with no body, and say the connection closes. Then a
    lingering close: what the client still sends is read and dropped for a
    moment, so the close does not reset the connection before the client
    reads the answer."""
    allow = "Allow: CONNECT\r\n" if status == 405 else ""
    head = (f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}\r\n{allow}"
            "Content-Length: 0\r\nConnection: close\r\n\r\n")
    try:
        client.settimeout(1.0)
        client.sendall(head.encode("ascii"))
        client.shutdown(socket.SHUT_WR)
        client.settimeout(LINGER_SECONDS)
        for _ in range(LINGER_READS):
            if not client.recv(CHUNK_BYTES):
                return
    except OSError:
        # The client is gone, or sends on; the refusal is logged already.
        return


def _shut(sock: socket.socket) -> None:
    """Shut *sock* both ways, which wakes a thread waiting on it."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        # Not connected, or closed already: nothing waits on it.
        return
