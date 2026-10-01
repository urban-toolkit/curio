"""The only code in this package that speaks HTTP, and the only code that
materialises a credential.

Two implementations behind one protocol:

- :class:`HttpDiscoveryTransport` - the real one, over ``common/egress_policy`` via
  ``agents.egress``. Same default-deny address policy every other outbound
  request in Curio passes through.
- :class:`FixtureDiscoveryTransport` - reads a recorded corpus from disk. Selected
  only under ``CURIO_TESTING``, so the whole backend stack can be driven end to
  end without a socket.

The second is the same move ``agents/testing_provider.py`` makes for the LLM,
and for the same reason its docstring gives: pointing the one non-deterministic
leg at a script "keeps the WHOLE backend loop under test while making the model
the one part that cannot vary". Here HTTP is that leg. Routes, provider
parsing, the federated fan-out, format detection, the caps, the download and
the hand-off to the Data Catalog all run for real; only the socket is replaced.

**A transport is never defaulted.** Every provider takes one as a constructor
argument and ``build_provider`` requires it, so forgetting to inject a fake in
a test is a ``TypeError`` at construction rather than a silent real request.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol

from utk_curio.backend.app.agents.infrastructure import egress
from utk_curio.backend.app.discovery.domain.errors import (
    DownloadTooLarge,
    ProviderError,
)

#: Portal metadata is not prompt text, so it does not take the agent-shaped
#: 256 KiB bound. A CKAN ``package_search?rows=20`` routinely exceeds it, and
#: GeoSampa's WFS capabilities document is 425 KB.
MAX_METADATA_BYTES = 1024 * 1024

#: The server's hard ceiling. A manifest may lower it, never raise it.
MAX_DISCOVERY_DOWNLOAD_BYTES = 64 * 1024 * 1024

METADATA_TIMEOUT_S = 15

ENV_FIXTURES = "CURIO_DISCOVERY_FIXTURES"


class DiscoveryTransportError(ProviderError):
    """The portal could not be reached, or did not answer usefully."""


class FixtureMissing(DiscoveryTransportError):
    """No recorded response for this URL. Names it, and how to record one."""


#: The ceiling for caching one file of a storage collection to disk. Nothing
#: passes through memory on that path, so it is a disk bound rather than the
#: download ceiling above, which exists because an import used to read the
#: file whole.
MAX_COLLECTION_OBJECT_BYTES = 4 * 1024 * 1024 * 1024


class DiscoveryTransport(Protocol):
    def json_get(self, url: str, *, credential: str | None = None,
                 headers: dict[str, str] | None = None) -> Any: ...

    def get_page(self, url: str, *, credential: str | None = None,
                 headers: dict[str, str] | None = None) -> tuple[str, dict]:
        """The body and the response headers, for a paginated listing."""
        ...

    def download(self, url: str, sink: Callable[[bytes], None], *, max_bytes: int,
                 credential: str | None = None, headers: dict[str, str] | None = None,
                 progress=None, ceiling: int | None = None) -> "egress.DownloadResult": ...


class HttpDiscoveryTransport:
    """Real HTTP, under the full address policy.

    ``trusted_host`` is never passed. That exemption exists for a host an
    operator configured deliberately (a local search provider); a public data
    portal has no claim on it, and allowing one would let a manifest declare
    ``169.254.169.254`` a "portal".
    """

    def __init__(self, *, budget: "egress.CallBudget | None" = None) -> None:
        self.budget = budget

    def json_get(self, url, *, credential=None, headers=None):
        return self.get_page(url, credential=credential, headers=headers)[0]

    def get_page(self, url, *, credential=None, headers=None):
        try:
            result = egress.fetch(
                url,
                max_bytes=MAX_METADATA_BYTES,
                budget=self.budget,
                request_fn=_metadata_request,
                headers=headers,
                secret_headers=_merge(None, credential),
            )
        except egress.EgressRefused:
            raise
        except Exception as exc:  # transport: unreachable, never a policy claim
            raise DiscoveryTransportError(f"could not reach {_host(url)}: {exc}") from exc
        if not (200 <= result.status < 300):
            raise DiscoveryTransportError(f"{_host(url)} answered {result.status}")
        if result.truncated:
            raise DiscoveryTransportError(
                f"{_host(url)} returned more than {MAX_METADATA_BYTES} bytes of metadata"
            )
        return result.body, dict(result.headers or {})

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None,
                 ceiling=None):
        bound = min(int(max_bytes), int(ceiling or MAX_DISCOVERY_DOWNLOAD_BYTES))
        try:
            return egress.download(
                url,
                sink=sink,
                max_bytes=bound,
                budget=self.budget,
                headers=headers,
                secret_headers=_merge(None, credential),
                progress=progress,
            )
        except egress.EgressTooLarge as exc:
            raise DownloadTooLarge(str(exc)) from exc
        except egress.EgressRefused:
            raise
        except Exception as exc:
            raise DiscoveryTransportError(f"could not download from {_host(url)}: {exc}") from exc


class FixtureDiscoveryTransport:
    """Recorded responses, read from disk. Test rigs only.

    The corpus is an index plus files, so a lookup is exact and a miss is loud:

    .. code-block:: json

        {"https://portal/api?q=bike": {"file": "socrata/bike.json",
                                       "status": 200,
                                       "headers": {"Content-Type": "application/json"}},
         "https://portal/slow":       {"error": "timeout"}}

    An ``error`` entry raises what the real transport would, which is how the
    federated partial-failure path and the oversized-download path get tested
    deterministically instead of being mocked at a higher level.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        index_path = self.root / "index.json"
        if not index_path.is_file():
            raise DiscoveryTransportError(f"no fixture index at {index_path}")
        self.index: dict[str, dict] = json.loads(index_path.read_text(encoding="utf-8"))
        #: Every URL asked for, in order. Lets a test assert that a cached
        #: search issued ZERO requests, which is otherwise unobservable.
        self.calls: list[str] = []

    def _entry(self, url: str) -> dict:
        self.calls.append(url)
        entry = self.index.get(url)
        if entry is None:
            raise FixtureMissing(
                f"no recorded response for {url!r}. Record one with "
                f"scripts/record_discovery_fixtures.py, or add it to "
                f"{self.root / 'index.json'}."
            )
        error = entry.get("error")
        if error == "too-large":
            raise DownloadTooLarge(f"recorded as oversized: {url}")
        if error:
            raise DiscoveryTransportError(f"recorded as {error}: {url}")
        return entry

    def json_get(self, url, *, credential=None, headers=None):
        return self.get_page(url, credential=credential, headers=headers)[0]

    def get_page(self, url, *, credential=None, headers=None):
        entry = self._entry(url)
        status = int(entry.get("status", 200))
        if not (200 <= status < 300):
            raise DiscoveryTransportError(f"{_host(url)} answered {status}")
        body = (self.root / entry["file"]).read_text(encoding="utf-8")
        return body, dict(entry.get("headers") or {})

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None,
                 ceiling=None):
        import hashlib

        # A Range request is recorded under its own key, so a probe of a file's
        # header and a download of the whole file are separate entries.
        byte_range = (headers or {}).get("Range")
        entry = self._entry(f"{url} {byte_range}" if byte_range else url)
        status = int(entry.get("status", 200))
        if not (200 <= status < 300):
            raise DiscoveryTransportError(f"{_host(url)} answered {status}")
        blob = (self.root / entry["file"]).read_bytes()
        bound = min(int(max_bytes), int(ceiling or MAX_DISCOVERY_DOWNLOAD_BYTES))
        recorded = dict(entry.get("headers") or {})
        declared = recorded.get("Content-Length")
        # The real transport refuses on Content-Length BEFORE reading a body,
        # so the fixture one must too or that branch is never exercised.
        if declared is not None and int(declared) > bound:
            raise DownloadTooLarge(
                f"the response declares {declared} bytes, over the {bound}-byte bound"
            )
        if len(blob) > bound:
            raise DownloadTooLarge(
                f"the response exceeded the {bound}-byte bound while streaming"
            )
        sink(blob)
        if progress is not None:
            progress(len(blob), len(blob))
        return egress.DownloadResult(
            url=url,
            final_url=entry.get("finalUrl", url),
            status=status,
            content_type=recorded.get("Content-Type", ""),
            bytes_written=len(blob),
            sha256=hashlib.sha256(blob).hexdigest(),
            headers=recorded,
        )


class CredentialedTransport:
    """Binds one source's credential to a transport.

    Providers call ``json_get(url)`` and know nothing about credentials - that
    is deliberate, and it is what keeps a token out of provider code, out of
    the URLs providers build, and out of anything a provider might log. Binding
    it here means the one place that materialises a secret stays the one place,
    while every provider stays ignorant of it.

    *hosts* are where the credential may go: the source's own host. A request
    to any other host (a Mapillary thumbnail on a CDN, a file a portal links
    to elsewhere) is sent without it. Required, so a binding cannot forget it.
    """

    def __init__(self, inner: DiscoveryTransport, credential: str | None, *, hosts) -> None:
        self._inner = inner
        self._credential = credential
        self._hosts = frozenset(str(h).lower() for h in hosts if h)

    # Exposed for tests that assert on what was requested; carries no secret.
    @property
    def calls(self):
        return getattr(self._inner, "calls", [])

    def _for(self, url: str, credential: str | None) -> str | None:
        if credential:
            return credential
        return self._credential if _host(url).lower() in self._hosts else None

    def json_get(self, url, *, credential=None, headers=None):
        return self._inner.json_get(
            url, credential=self._for(url, credential), headers=headers
        )

    def get_page(self, url, *, credential=None, headers=None):
        return self._inner.get_page(
            url, credential=self._for(url, credential), headers=headers
        )

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None,
                 ceiling=None):
        return self._inner.download(
            url,
            sink,
            max_bytes=max_bytes,
            credential=self._for(url, credential),
            headers=headers,
            progress=progress,
            ceiling=ceiling,
        )


def fixture_root() -> str | None:
    """The recorded-response corpus this process should answer from, or None.

    Double-gated exactly as ``app/testing/routes.py`` is: a fixture corpus is
    honoured only when the process declares itself a test rig AND is not a
    production deployment. Checked at call time rather than import, so a stray
    env var on a real deployment cannot quietly start serving stale fixtures.
    The OpenStreetMap loader, which sends its requests from Node, asks the same
    question.
    """
    from utk_curio.backend import config

    fixtures = os.environ.get(ENV_FIXTURES)
    if fixtures and fixtures.strip():
        if not config._is_testing() or not config._is_dev():
            raise DiscoveryTransportError(
                f"{ENV_FIXTURES} is set but this process is not a test rig - "
                "refusing to serve recorded responses"
            )
        return fixtures.strip()
    return None


def build_transport(*, budget=None) -> DiscoveryTransport:
    """The transport this process should use: the corpus ``fixture_root`` names,
    or the network."""
    fixtures = fixture_root()
    if fixtures:
        return FixtureDiscoveryTransport(fixtures)
    return HttpDiscoveryTransport(budget=budget)


def _merge(headers: dict[str, str] | None, credential: str | None) -> dict[str, str]:
    """Request headers, with the credential added if there is one.

    The one place a token becomes a value. Providers hand over a header NAME
    and the slot; they never see what is in it.
    """
    out = dict(headers or {})
    if credential:
        name, _, value = credential.partition(":")
        if name and value:
            out[name] = value
    return out


def _metadata_request(method: str, url: str, *, trusted_host=None, headers=None):
    """An ``egress.fetch`` transport for metadata: the catalog's timeout, an
    unencoded body read to :data:`MAX_METADATA_BYTES`, and the headers ``fetch``
    sends on this hop (a source's key only while the hop is on its origin)."""
    import requests

    from utk_curio.backend.app.common.egress_policy import confirm_peer

    resp = requests.request(
        method, url, timeout=METADATA_TIMEOUT_S, allow_redirects=False,
        stream=True, headers={**(headers or {}), "Accept-Encoding": "identity"},
    )
    try:
        confirm_peer(resp, url, trusted_host)
        body = b""
        for chunk in resp.iter_content(chunk_size=8192):
            if len(body) + len(chunk) > MAX_METADATA_BYTES:
                body += chunk[: max(0, MAX_METADATA_BYTES + 1 - len(body))]
                break
            body += chunk
        return resp.status_code, dict(resp.headers), body, resp.headers.get("Location")
    finally:
        resp.close()


def _host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
