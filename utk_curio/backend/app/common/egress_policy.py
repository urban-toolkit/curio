"""The address policy every outbound request in Curio passes through.

Extracted from ``agents/egress.py``, whose docstring opens "THE one module
that speaks HTTP **on an agent's behalf**". That is still true of that module,
and it is why this one exists: the Data Lake Catalog's transport is not an
agent, so it needs the policy without inheriting the agent framing or the
agent-shaped body bound. ``agents/egress.py`` re-exports every name defined
here, so its own callers are unchanged and see the same objects.

Default-deny:

- ``https``/``http`` only (no other schemes, ever);
- private, loopback, link-local, reserved, and multicast addresses are
  refused AFTER DNS resolution (a hostname that resolves to 169.254.169.254
  is refused even though the URL looks public - the classic SSRF shapes);
- redirects are followed manually by the caller, each hop re-checked here,
  capped at :data:`MAX_REDIRECTS`.

The resolver is injectable so tests never touch the network.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = ("https", "http")
MAX_REDIRECTS = 5
# The per-run tool budget (enforced by the agent run loop, named here).
MAX_CALLS_PER_RUN = 4


class EgressRefused(ValueError):
    """The URL violates the egress policy - refused before any connection."""


class EgressTooLarge(EgressRefused):
    """The response is larger than the caller's byte bound.

    A subclass so every existing ``except EgressRefused`` keeps catching it,
    while a caller that wants to tell "too big" from "policy said no" can.
    They deserve different HTTP statuses: an oversized dataset is the user's
    request being too big (4xx), not the server refusing an address (5xx).
    """


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


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


def trusted_host_of(url: str) -> tuple[str, int | None] | None:
    """The ``(hostname, port)`` key of an OPERATOR-declared URL (dev/90 A2).

    Only deployment configuration may mint this key (today: the
    ``CURIO_SEARCH_URL`` provider template) - never model output, and never a
    catalog manifest. None when the URL has no usable host.
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
    """``(ok, reason)`` - scheme allowlist + post-DNS address policy.

    ``trusted_host`` (dev/90 A2) exempts EXACTLY that (hostname, port) from
    the address policy: the operator declared the host by configuring it, so
    a loopback/private search provider (local SearXNG) is reachable. The
    scheme allowlist still applies, and any OTHER host - including every
    redirect hop off the provider - gets the full default-deny policy.
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
            f"host {host!r} resolves to a non-public address ({address}) - refused"
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


def confirm_peer(resp, url: str, trusted_host=None) -> None:
    """Re-check the address we actually connected to, after connecting.

    ``check_url`` resolved and validated the hostname, then discarded the
    addresses, and the HTTP client resolves again. A name server that answers
    with a public address for the first lookup and an internal one for the
    second passes the policy and connects somewhere else entirely. Pinning the
    checked address through ``requests`` means overriding urllib3's connection
    factory or patching a global resolver, neither of which is safe in a
    threaded server, so instead confirm the peer actually reached before
    reading anything from it.

    Residual, stated honestly: the request line and headers are already on the
    wire by this point, so a blind GET against an internal service is not
    prevented, only its response is withheld. Closing that needs the
    connection-factory work.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if trusted_host is not None and (host, parsed.port) == trusted_host:
        return
    peer = _peer_address(resp)
    if peer is None:
        return
    ok, reason = _address_is_public(peer, host)
    if not ok:
        raise EgressRefused(
            f"{reason} (connected peer differed from the checked address)"
        )
