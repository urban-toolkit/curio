"""The only code in this package that speaks HTTP, and the only code that
materialises a credential.

Two implementations behind one protocol:

- :class:`HttpLakeTransport` - the real one, over ``common/egress_policy`` via
  ``agents.egress``. Same default-deny address policy every other outbound
  request in Curio passes through.
- :class:`FixtureLakeTransport` - reads a recorded corpus from disk. Selected
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

from utk_curio.backend.app.agents import egress
from utk_curio.backend.app.datalakes.domain.errors import (
    DownloadTooLarge,
    ProviderError,
)

#: Portal metadata is not prompt text, so it does not take the agent-shaped
#: 256 KiB bound. A CKAN ``package_search?rows=20`` routinely exceeds it, and
#: GeoSampa's WFS capabilities document is 425 KB.
MAX_METADATA_BYTES = 1024 * 1024

#: The server's hard ceiling. A manifest may lower it, never raise it.
MAX_LAKE_DOWNLOAD_BYTES = 64 * 1024 * 1024

METADATA_TIMEOUT_S = 15

ENV_FIXTURES = "CURIO_DATALAKE_FIXTURES"


class LakeTransportError(ProviderError):
    """The portal could not be reached, or did not answer usefully."""


class FixtureMissing(LakeTransportError):
    """No recorded response for this URL. Names it, and how to record one."""


class LakeTransport(Protocol):
    def json_get(self, url: str, *, credential: str | None = None,
                 headers: dict[str, str] | None = None) -> Any: ...

    def download(self, url: str, sink: Callable[[bytes], None], *, max_bytes: int,
                 credential: str | None = None, headers: dict[str, str] | None = None,
                 progress=None) -> "egress.DownloadResult": ...


class HttpLakeTransport:
    """Real HTTP, under the full address policy.

    ``trusted_host`` is never passed. That exemption exists for a host an
    operator configured deliberately (a local search provider); a public data
    portal has no claim on it, and allowing one would let a manifest declare
    ``169.254.169.254`` a "portal".
    """

    def __init__(self, *, budget: "egress.CallBudget | None" = None) -> None:
        self.budget = budget

    def json_get(self, url, *, credential=None, headers=None):
        try:
            result = egress.fetch(
                url,
                max_bytes=MAX_METADATA_BYTES,
                budget=self.budget,
                request_fn=_metadata_request(_merge(headers, credential)),
            )
        except egress.EgressRefused:
            raise
        except Exception as exc:  # transport: unreachable, never a policy claim
            raise LakeTransportError(f"could not reach {_host(url)}: {exc}") from exc
        if not (200 <= result.status < 300):
            raise LakeTransportError(f"{_host(url)} answered {result.status}")
        if result.truncated:
            raise LakeTransportError(
                f"{_host(url)} returned more than {MAX_METADATA_BYTES} bytes of metadata"
            )
        return result.body

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None):
        bound = min(int(max_bytes), MAX_LAKE_DOWNLOAD_BYTES)
        try:
            return egress.download(
                url,
                sink=sink,
                max_bytes=bound,
                budget=self.budget,
                headers=_merge(headers, credential),
                progress=progress,
            )
        except egress.EgressTooLarge as exc:
            raise DownloadTooLarge(str(exc)) from exc
        except egress.EgressRefused:
            raise
        except Exception as exc:
            raise LakeTransportError(f"could not download from {_host(url)}: {exc}") from exc


class FixtureLakeTransport:
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
            raise LakeTransportError(f"no fixture index at {index_path}")
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
                f"scripts/record_datalake_fixtures.py, or add it to "
                f"{self.root / 'index.json'}."
            )
        error = entry.get("error")
        if error == "too-large":
            raise DownloadTooLarge(f"recorded as oversized: {url}")
        if error:
            raise LakeTransportError(f"recorded as {error}: {url}")
        return entry

    def json_get(self, url, *, credential=None, headers=None):
        entry = self._entry(url)
        status = int(entry.get("status", 200))
        if not (200 <= status < 300):
            raise LakeTransportError(f"{_host(url)} answered {status}")
        return (self.root / entry["file"]).read_text(encoding="utf-8")

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None):
        import hashlib

        entry = self._entry(url)
        status = int(entry.get("status", 200))
        if not (200 <= status < 300):
            raise LakeTransportError(f"{_host(url)} answered {status}")
        blob = (self.root / entry["file"]).read_bytes()
        bound = min(int(max_bytes), MAX_LAKE_DOWNLOAD_BYTES)
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


def build_transport(*, budget=None) -> LakeTransport:
    """The transport this process should use.

    Double-gated exactly as ``app/testing/routes.py`` is: a fixture corpus is
    honoured only when the process declares itself a test rig AND is not a
    production deployment. Checked at call time rather than import, so a stray
    env var on a real deployment cannot quietly start serving stale fixtures.
    """
    from utk_curio.backend import config

    fixtures = os.environ.get(ENV_FIXTURES)
    if fixtures and fixtures.strip():
        if not config._is_testing() or not config._is_dev():
            raise LakeTransportError(
                f"{ENV_FIXTURES} is set but this process is not a test rig - "
                "refusing to serve recorded responses"
            )
        return FixtureLakeTransport(fixtures.strip())
    return HttpLakeTransport(budget=budget)


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


def _metadata_request(headers: dict[str, str]):
    """An ``egress.fetch`` transport that sends *headers*.

    ``fetch``'s default request function takes no headers, and widening its
    signature would break every two-argument test double in the existing suite.
    A closure is cheaper than that churn.
    """

    def _request(method: str, url: str, *, trusted_host=None):
        import requests

        from utk_curio.backend.app.common.egress_policy import confirm_peer

        resp = requests.request(
            method, url, timeout=METADATA_TIMEOUT_S, allow_redirects=False,
            stream=True, headers={**headers, "Accept-Encoding": "identity"},
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

    return _request


def _host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url
