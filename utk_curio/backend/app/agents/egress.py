"""Policy-gated HTTP egress for agents (memo dev/67-4, DEC-053).

THE one module that speaks HTTP on an agent's behalf — no other agents-side
code may open a connection. Default-deny policy:

- ``https``/``http`` only (no other schemes, ever);
- private, loopback, link-local, reserved, and multicast addresses are
  refused AFTER DNS resolution (a hostname that resolves to 169.254.169.254
  is refused even though the URL looks public — the classic SSRF shapes);
- redirects are followed manually, each hop re-checked against the policy,
  capped at ``MAX_REDIRECTS``;
- response bodies are capped at ``MAX_BODY_BYTES`` (truncation is marked);
- every call is auditable: the caller may pass an ``audit`` list that
  receives ``{url, finalUrl, status, bytes}`` per fetch.

The transport and the resolver are injectable for tests — CI never touches
the network.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

ALLOWED_SCHEMES = ("https", "http")
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 256 * 1024
TIMEOUT_S = 10
# The per-run tool budget (enforced by the run loop, named here).
MAX_CALLS_PER_RUN = 4
_TRUNCATION_MARKER = "\n…[truncated: response exceeded the egress body bound]"


class EgressRefused(ValueError):
    """The URL violates the egress policy — refused before any connection."""


class CallBudget:
    """Counts the HTTP requests a run has actually made.

    The per-run bound used to be counted by the *caller*, one tick per
    candidate row, while a single row could issue a dozen real requests: a
    Socrata verification fetched twice and each fetch followed up to
    ``MAX_REDIRECTS`` hops. Counting here, at the one place a request is
    issued, makes ``MAX_CALLS_PER_RUN`` mean what it says.
    """

    __slots__ = ("limit", "used")

    def __init__(self, limit: int = MAX_CALLS_PER_RUN) -> None:
        self.limit = limit
        self.used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def spend(self) -> None:
        if self.exhausted:
            raise EgressRefused(
                f"the per-run egress budget of {self.limit} requests is spent"
            )
        self.used += 1


@dataclass
class EgressResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: str
    truncated: bool = False
    redirects: int = 0
    elapsed_ms: int = 0
    audit: dict = field(default_factory=dict)


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


def trusted_host_of(url: str) -> tuple[str, int | None] | None:
    """The ``(hostname, port)`` key of an OPERATOR-declared URL (dev/90 A2).

    Only deployment configuration may mint this key (today: the
    ``CURIO_SEARCH_URL`` provider template) — never model output. None when
    the URL has no usable host.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    return (parsed.hostname.lower(), parsed.port)


def check_url(
    url: str, *, resolver=None,
    trusted_host: tuple[str, int | None] | None = None,
) -> tuple[bool, str]:
    """``(ok, reason)`` — scheme allowlist + post-DNS address policy.

    ``trusted_host`` (dev/90 A2) exempts EXACTLY that (hostname, port) from
    the address policy: the operator declared the host by configuring it, so
    a loopback/private search provider (local SearXNG) is reachable. The
    scheme allowlist still applies, and any OTHER host — including every
    redirect hop off the provider — gets the full default-deny policy.
    """
    resolver = resolver or _default_resolver
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return False, f"unparseable URL: {exc}"
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"scheme {parsed.scheme!r} is not allowed (https/http only)"
    host = parsed.hostname
    if not host:
        return False, "the URL has no host"
    if trusted_host is not None and (host.lower(), parsed.port) == trusted_host:
        return True, ""  # operator-declared provider host (dev/90 A2)
    try:
        addresses = resolver(host)
    except OSError as exc:
        return False, f"the host does not resolve: {exc}"
    if not addresses:
        return False, "the host does not resolve"
    for address in addresses:
        ok, reason = _address_is_public(address, host)
        if not ok:
            return False, reason
    return True, ""


def _address_is_public(address: str, host: str) -> tuple[bool, str]:
    """``(ok, reason)`` for one resolved address.

    An ALLOWLIST (``is_global``) rather than a denylist of the private ranges.
    A denylist has to enumerate every non-public range and stay correct as new
    ones are assigned, and it was already missing one: RFC 6598 carrier-grade
    NAT space ``100.64.0.0/10`` is not private, loopback, link-local, reserved,
    multicast or unspecified, so it passed every check while being directly
    reachable internal space on CGNAT and cloud-NAT deployments. ``is_global``
    is the property actually wanted, and CPython keeps it current.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False, f"unparseable resolved address {address!r}"
    # IPv4-mapped IPv6 (``::ffff:169.254.169.254``) is unwrapped first. Modern
    # CPython delegates the address properties for these, but the floor in
    # requires-python does not, and the mapped form is a classic bypass.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if not ip.is_global:
        return False, (
            f"host {host!r} resolves to a non-public address ({address}) — refused"
        )
    return True, ""


def _peer_address(resp) -> str | None:
    """The IP this response is actually connected to, or None if unavailable.

    Reaches through requests into urllib3's socket. Best-effort by nature: the
    attribute chain is private and varies by version, so a None means "could
    not confirm" rather than "not connected".
    """
    try:
        sock = resp.raw._connection.sock  # type: ignore[attr-defined]
        return sock.getpeername()[0]
    except Exception:  # noqa: BLE001 - any failure means "unknown"
        return None


def _default_request(method: str, url: str, *, trusted_host=None):
    """One non-redirecting HTTP request; returns (status, headers, body_bytes,
    location). Import stays local so tests never need requests installed."""
    import requests

    resp = requests.request(
        method, url, timeout=TIMEOUT_S, allow_redirects=False, stream=True
    )
    try:
        # ── Rebinding check ────────────────────────────────────────────────
        # ``check_url`` resolved and validated the hostname, then discarded the
        # addresses, and ``requests`` resolves again here. A name server that
        # answers with a public address for the first lookup and an internal one
        # for the second passes the policy and connects somewhere else entirely.
        # Pinning the checked address through requests means overriding
        # urllib3's connection factory or patching a global resolver, neither of
        # which is safe in a threaded server, so instead confirm the peer we
        # actually reached before reading anything from it.
        #
        # Residual, stated honestly: the request line and headers are already on
        # the wire by this point, so a blind GET against an internal service is
        # not prevented, only its response is withheld. Closing that needs the
        # connection-factory work.
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        exempt = trusted_host is not None and (host, parsed.port) == trusted_host
        peer = _peer_address(resp)
        if peer is not None and not exempt:
            ok, reason = _address_is_public(peer, host)
            if not ok:
                raise EgressRefused(
                    f"{reason} (connected peer differed from the checked address)"
                )
        body = b""
        for chunk in resp.iter_content(chunk_size=8192):
            # Checked BEFORE appending: appending first let a whole extra chunk
            # past the bound on every iteration, so the cap overshot by up to a
            # chunk (and ``chunk_size`` is only a hint, so possibly more).
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                body += chunk[: max(0, MAX_BODY_BYTES + 1 - len(body))]
                break
            body += chunk
        return resp.status_code, dict(resp.headers), body, resp.headers.get("Location")
    finally:
        # ``stream=True`` leaves the connection open until the body is drained;
        # breaking out of the loop above skipped that and leaked it.
        resp.close()


def _accepts_trusted_host(request_fn) -> bool:
    """Whether *request_fn* takes a ``trusted_host`` keyword.

    Test doubles and older injected callables take ``(method, url)`` only.
    """
    import inspect

    try:
        params = inspect.signature(request_fn).parameters
    except (TypeError, ValueError):
        return False
    if "trusted_host" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def fetch(
    url: str,
    *,
    method: str = "GET",
    request_fn=None,
    resolver=None,
    audit: list | None = None,
    trusted_host: tuple[str, int | None] | None = None,
    budget: "CallBudget | None" = None,
) -> EgressResult:
    """Fetch one URL under the full policy. Raises :class:`EgressRefused` on
    a policy violation (any hop); transport errors propagate (the caller maps
    them to an unreachable/infrastructure outcome).

    ``trusted_host`` (dev/90 A2): the operator-declared provider key from
    :func:`trusted_host_of` — every hop is still re-checked, so a redirect
    off the provider host falls back to the full default-deny policy."""
    request_fn = request_fn or _default_request
    started = time.monotonic()
    current = url
    redirects = 0
    while True:
        ok, reason = check_url(current, resolver=resolver, trusted_host=trusted_host)
        if not ok:
            raise EgressRefused(reason)
        # Charged per hop, so a redirect chain costs what it actually costs.
        if budget is not None:
            budget.spend()
        # ``trusted_host`` is threaded through so the peer check knows which
        # host the operator exempted. Decided by signature rather than by
        # catching TypeError, which would also swallow a TypeError raised
        # inside the callable and then call it a second time.
        if _accepts_trusted_host(request_fn):
            status, headers, body, location = request_fn(
                method, current, trusted_host=trusted_host
            )
        else:
            status, headers, body, location = request_fn(method, current)
        if status in (301, 302, 303, 307, 308) and location:
            redirects += 1
            if redirects > MAX_REDIRECTS:
                raise EgressRefused(f"more than {MAX_REDIRECTS} redirects")
            current = urljoin(current, location)
            continue
        truncated = len(body) > MAX_BODY_BYTES
        text = body[:MAX_BODY_BYTES].decode("utf-8", errors="replace")
        if truncated:
            text += _TRUNCATION_MARKER
        content_type = str(
            headers.get("Content-Type") or headers.get("content-type") or ""
        )
        result = EgressResult(
            url=url,
            final_url=current,
            status=int(status),
            content_type=content_type,
            body=text,
            truncated=truncated,
            redirects=redirects,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        result.audit = {
            "url": url,
            "finalUrl": current,
            "status": result.status,
            "bytes": len(body),
        }
        if audit is not None:
            audit.append(result.audit)
        return result
