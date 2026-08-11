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


def check_url(url: str, *, resolver=None) -> tuple[bool, str]:
    """``(ok, reason)`` — scheme allowlist + post-DNS address policy."""
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
    try:
        addresses = resolver(host)
    except OSError as exc:
        return False, f"the host does not resolve: {exc}"
    if not addresses:
        return False, "the host does not resolve"
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, f"unparseable resolved address {address!r}"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False, (
                f"host {host!r} resolves to a non-public address ({address}) — refused"
            )
    return True, ""


def _default_request(method: str, url: str):
    """One non-redirecting HTTP request; returns (status, headers, body_bytes,
    location). Import stays local so tests never need requests installed."""
    import requests

    resp = requests.request(
        method, url, timeout=TIMEOUT_S, allow_redirects=False, stream=True
    )
    body = b""
    for chunk in resp.iter_content(chunk_size=8192):
        body += chunk
        if len(body) > MAX_BODY_BYTES + 1:
            break
    return resp.status_code, dict(resp.headers), body, resp.headers.get("Location")


def fetch(
    url: str,
    *,
    method: str = "GET",
    request_fn=None,
    resolver=None,
    audit: list | None = None,
) -> EgressResult:
    """Fetch one URL under the full policy. Raises :class:`EgressRefused` on
    a policy violation (any hop); transport errors propagate (the caller maps
    them to an unreachable/infrastructure outcome)."""
    request_fn = request_fn or _default_request
    started = time.monotonic()
    current = url
    redirects = 0
    while True:
        ok, reason = check_url(current, resolver=resolver)
        if not ok:
            raise EgressRefused(reason)
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
