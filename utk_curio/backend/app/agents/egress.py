"""Policy-gated HTTP egress for agents (memo dev/67-4, DEC-053).

THE one module that speaks HTTP on an agent's behalf - no other agents-side
code may open a connection.

The **address policy** (scheme allowlist, post-DNS SSRF refusal, the redirect
re-check, the peer-rebinding confirmation, ``CallBudget``) now lives in
``app/common/egress_policy.py`` so non-agent callers can reuse it without
importing this module, and every one of those names is re-exported here.
Unchanged for existing callers: ``egress.check_url``, ``egress.EgressRefused``,
``egress.CallBudget`` and friends are the same objects they always were.

What stays here is the agent-shaped transport on top of that policy:

- response bodies are capped at :data:`MAX_BODY_BYTES` (truncation is marked);
- every call is auditable: the caller may pass an ``audit`` list that
  receives ``{url, finalUrl, status, bytes}`` per fetch.

The transport and the resolver are injectable for tests - CI never touches
the network, and since the socket guard landed
(``utk_curio/backend/tests/netguard.py``) a test that forgets to inject one
fails loudly instead of quietly reaching a third party.

Two byte bounds, deliberately separate:

- :data:`MAX_BODY_BYTES` (256 KiB) is the DEFAULT for :func:`fetch`. It is a
  *model-context* bound, not an address-policy one: it exists because a tool
  result becomes prompt text. That is exactly why it is a per-call parameter -
  raising it for a caller who is not feeding a model loosens nothing about
  who may be contacted.
- :func:`download` takes an explicit ``max_bytes`` and streams to a sink
  rather than returning a body, because a dataset file is not prompt text and
  must never be held in a string. Its cap is the caller's to choose and is
  enforced against bytes actually written.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

from utk_curio.backend.app.common.egress_policy import (  # noqa: F401 - re-exported
    ALLOWED_SCHEMES,
    MAX_CALLS_PER_RUN,
    MAX_REDIRECTS,
    CallBudget,
    EgressRefused,
    EgressTooLarge,
    _address_is_public,
    _default_resolver,
    _peer_address,
    check_url,
    confirm_peer,
    trusted_host_of,
)

MAX_BODY_BYTES = 256 * 1024
TIMEOUT_S = 10
# A dataset download is not a metadata probe: portals are slow and the payload
# is orders of magnitude larger, so it gets its own timeout rather than
# stretching the one that bounds an agent's verification call.
DOWNLOAD_TIMEOUT_S = 120
_TRUNCATION_MARKER = "\n…[truncated: response exceeded the egress body bound]"
_STREAM_CHUNK = 64 * 1024


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


@dataclass
class DownloadResult:
    """What :func:`download` wrote, and what it was told it was writing.

    No ``body``: the bytes went to the caller's sink. ``sha256`` is computed
    over what was actually written, which is what makes "have I already got
    this exact resource?" answerable without re-reading the file.
    """

    url: str
    final_url: str
    status: int
    content_type: str
    bytes_written: int
    sha256: str
    headers: dict = field(default_factory=dict)
    redirects: int = 0
    elapsed_ms: int = 0
    audit: dict = field(default_factory=dict)


def _default_request(method: str, url: str, *, trusted_host=None):
    """One non-redirecting HTTP request; returns (status, headers, body_bytes,
    location). Import stays local so tests never need requests installed."""
    import requests

    resp = requests.request(
        method, url, timeout=TIMEOUT_S, allow_redirects=False, stream=True
    )
    try:
        confirm_peer(resp, url, trusted_host)
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


def _default_stream_request(
    method: str, url: str, *, trusted_host=None, headers=None, timeout_s=DOWNLOAD_TIMEOUT_S
):
    """One non-redirecting request whose body is left UNREAD.

    Returns ``(status, headers, location, chunks)`` where ``chunks`` is an
    iterator and ``close`` is its companion. Separate from
    :func:`_default_request` rather than an extra parameter on it, so the
    ``fetch`` transport seam keeps the exact two-argument shape every existing
    test double implements.

    ``Accept-Encoding: identity`` because the cap counts bytes written to the
    sink: a server that gzips a 10 GB file into a 40 MB response would
    otherwise sail past a byte bound that was meant to protect the disk.
    """
    import requests

    sent = {"Accept-Encoding": "identity"}
    sent.update(headers or {})
    resp = requests.request(
        method, url, timeout=timeout_s, allow_redirects=False, stream=True, headers=sent
    )
    try:
        confirm_peer(resp, url, trusted_host)
    except BaseException:
        resp.close()
        raise
    return (
        resp.status_code,
        dict(resp.headers),
        resp.headers.get("Location"),
        _ResponseStream(resp),
    )


class _ResponseStream:
    """A closeable chunk iterator over a streamed response."""

    def __init__(self, resp):
        self._resp = resp

    def __iter__(self):
        return self._resp.iter_content(chunk_size=_STREAM_CHUNK)

    def close(self):
        self._resp.close()


def _accepts_trusted_host(request_fn) -> bool:
    """Whether *request_fn* takes a ``trusted_host`` keyword.

    Test doubles and older injected callables take ``(method, url)`` only.
    Decided by signature rather than by catching TypeError, which would also
    swallow a TypeError raised inside the callable and then call it a second
    time.
    """
    import inspect

    try:
        params = inspect.signature(request_fn).parameters
    except (TypeError, ValueError):
        return False
    if "trusted_host" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _policy_hop(url: str, *, resolver, trusted_host, budget) -> None:
    """Clear one hop through the policy, or raise.

    The single implementation of "check this URL, then charge it", shared by
    :func:`fetch` and :func:`download` so the SSRF walk, the scheme allowlist
    and the budget accounting cannot drift between the two.
    """
    ok, reason = check_url(url, resolver=resolver, trusted_host=trusted_host)
    if not ok:
        raise EgressRefused(reason)
    # Charged per hop, so a redirect chain costs what it actually costs.
    if budget is not None:
        budget.spend()


def _next_redirect(status, location, current: str, redirects: int) -> str | None:
    if status in (301, 302, 303, 307, 308) and location:
        if redirects + 1 > MAX_REDIRECTS:
            raise EgressRefused(f"more than {MAX_REDIRECTS} redirects")
        return urljoin(current, location)
    return None


def _content_type(headers: dict) -> str:
    return str(headers.get("Content-Type") or headers.get("content-type") or "")


def fetch(
    url: str,
    *,
    method: str = "GET",
    request_fn=None,
    resolver=None,
    audit: list | None = None,
    trusted_host: tuple[str, int | None] | None = None,
    budget: "CallBudget | None" = None,
    max_bytes: int = MAX_BODY_BYTES,
) -> EgressResult:
    """Fetch one URL under the full policy. Raises :class:`EgressRefused` on
    a policy violation (any hop); transport errors propagate (the caller maps
    them to an unreachable/infrastructure outcome).

    ``trusted_host`` (dev/90 A2): the operator-declared provider key from
    :func:`trusted_host_of` - every hop is still re-checked, so a redirect
    off the provider host falls back to the full default-deny policy.

    ``max_bytes`` defaults to :data:`MAX_BODY_BYTES`, so every existing caller
    is unchanged. A caller whose result is not going into a prompt may raise
    it - a portal's ``package_search`` page routinely exceeds 256 KiB - and
    doing so loosens nothing about *who* may be contacted.
    """
    request_fn = request_fn or _default_request
    started = time.monotonic()
    current = url
    redirects = 0
    while True:
        _policy_hop(current, resolver=resolver, trusted_host=trusted_host, budget=budget)
        # ``trusted_host`` is threaded through so the peer check knows which
        # host the operator exempted.
        if _accepts_trusted_host(request_fn):
            status, headers, body, location = request_fn(
                method, current, trusted_host=trusted_host
            )
        else:
            status, headers, body, location = request_fn(method, current)
        following = _next_redirect(status, location, current, redirects)
        if following is not None:
            redirects += 1
            current = following
            continue
        truncated = len(body) > max_bytes
        text = body[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text += _TRUNCATION_MARKER
        result = EgressResult(
            url=url,
            final_url=current,
            status=int(status),
            content_type=_content_type(headers),
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


def download(
    url: str,
    *,
    sink,
    max_bytes: int,
    method: str = "GET",
    request_fn=None,
    resolver=None,
    audit: list | None = None,
    trusted_host: tuple[str, int | None] | None = None,
    budget: "CallBudget | None" = None,
    headers: dict | None = None,
    timeout_s: int = DOWNLOAD_TIMEOUT_S,
    progress=None,
) -> DownloadResult:
    """Stream one URL to *sink* under the same policy :func:`fetch` uses.

    ``sink`` is any callable taking ``bytes`` - a file object's ``.write`` is
    one. Nothing is buffered in memory beyond a chunk, which is the whole
    point: a dataset file must not become a Python string on its way to disk.

    ``max_bytes`` is required, not defaulted. A download without a byte bound
    is a way to fill the disk, and there is no sensible universal value: the
    caller knows what it is fetching.

    Refusals, both :class:`EgressTooLarge`:

    - ``Content-Length`` already exceeds ``max_bytes`` - refused before a
      single body byte is read;
    - the stream exceeds it anyway (a lying or absent ``Content-Length``) -
      refused at the chunk that would cross the line, so the sink never
      receives more than the bound.
    """
    request_fn = request_fn or _default_stream_request
    started = time.monotonic()
    current = url
    redirects = 0
    while True:
        _policy_hop(current, resolver=resolver, trusted_host=trusted_host, budget=budget)
        status, response_headers, location, chunks = request_fn(
            method, current, trusted_host=trusted_host, headers=headers, timeout_s=timeout_s
        )
        following = _next_redirect(status, location, current, redirects)
        if following is not None:
            _close(chunks)
            redirects += 1
            current = following
            continue

        declared = _declared_length(response_headers)
        if declared is not None and declared > max_bytes:
            _close(chunks)
            raise EgressTooLarge(
                f"the response declares {declared} bytes, over the {max_bytes}-byte bound"
            )

        digest = hashlib.sha256()
        written = 0
        try:
            for chunk in chunks:
                if not chunk:
                    continue
                # Checked BEFORE writing, so the sink never sees a byte past
                # the bound even when Content-Length lied or was absent.
                if written + len(chunk) > max_bytes:
                    raise EgressTooLarge(
                        f"the response exceeded the {max_bytes}-byte bound while streaming"
                    )
                sink(chunk)
                digest.update(chunk)
                written += len(chunk)
                if progress is not None:
                    progress(written, declared)
        finally:
            _close(chunks)

        result = DownloadResult(
            url=url,
            final_url=current,
            status=int(status),
            content_type=_content_type(response_headers),
            bytes_written=written,
            sha256=digest.hexdigest(),
            headers=dict(response_headers),
            redirects=redirects,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        result.audit = {
            "url": url,
            "finalUrl": current,
            "status": result.status,
            "bytes": written,
        }
        if audit is not None:
            audit.append(result.audit)
        return result


def _declared_length(headers: dict) -> int | None:
    raw = headers.get("Content-Length") or headers.get("content-length")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _close(chunks) -> None:
    closer = getattr(chunks, "close", None)
    if closer is not None:
        closer()
