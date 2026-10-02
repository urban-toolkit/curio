"""A dataset repo on the Hugging Face Hub, read file by file.

Listed with the Hub's tree API, ``/api/datasets/<repo>/tree/<revision>/<path>``,
which pages with a ``Link: <...>; rel="next"`` header, and read with
``/datasets/<repo>/resolve/<revision>/<path>``, which redirects to a CDN. Each
hop is re-checked by the egress policy. A token is optional: the account's
Hugging Face token (the one Street Vision uses) opens gated and private repos.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from typing import BinaryIO, ClassVar, Iterator
from urllib.parse import quote

from utk_curio.backend.app.discovery.domain.errors import ProviderError, ResourceNotFound
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure.transport import (
    MAX_DISCOVERY_DOWNLOAD_BYTES,
    DiscoveryTransportError,
)
from utk_curio.backend.app.discovery.providers.storage_base import (
    FileEntry,
    is_skipped,
    validate_relpath,
)

MAX_PAGES = 400

_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')


class HuggingFaceStorage:
    type: ClassVar[str] = "huggingface"

    def __init__(self, manifest: DiscoverySourceManifest, transport) -> None:
        self.manifest = manifest
        self.transport = transport
        self.base = manifest.provider.base_url
        options = manifest.provider.options
        self.repo = str(options["repo"])
        self.revision = str(options.get("revision") or "main")

    def _tree_url(self, prefix: str) -> str:
        path = quote(prefix.rstrip("/"), safe="/")
        tail = f"/{path}" if path else ""
        return (
            f"{self.base}/api/datasets/{quote(self.repo, safe='/')}/tree/"
            f"{quote(self.revision, safe='')}{tail}?recursive=true&expand=false"
        )

    def file_url(self, relpath: str) -> str:
        validate_relpath(relpath)
        return (
            f"{self.base}/datasets/{quote(self.repo, safe='/')}/resolve/"
            f"{quote(self.revision, safe='')}/{quote(relpath, safe='/')}"
        )

    def scan(self, prefix: str = "") -> Iterator[FileEntry]:
        url: str | None = self._tree_url(prefix)
        for _page in range(MAX_PAGES):
            if url is None:
                return
            body, headers = self.transport.get_page(url)
            try:
                entries = json.loads(body)
            except ValueError as exc:
                raise ProviderError(f"{self.manifest.name} answered a listing that is not JSON") from exc
            if not isinstance(entries, list):
                raise ProviderError(f"{self.manifest.name} answered a listing in an unknown shape")
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") != "file":
                    continue
                relpath = str(entry.get("path") or "")
                if not relpath or any(is_skipped(part) for part in relpath.split("/")):
                    continue
                lfs = entry.get("lfs") if isinstance(entry.get("lfs"), dict) else {}
                yield FileEntry(
                    relpath=relpath,
                    size=int(lfs.get("size") or entry.get("size") or 0),
                    mtime=_timestamp((entry.get("lastCommit") or {}).get("date")),
                    etag=str(entry.get("oid") or "") or None,
                )
            url = _next_link(headers, self.base)

    def open(self, relpath: str, *, byte_range: tuple[int, int] | None = None,
             max_bytes: int = MAX_DISCOVERY_DOWNLOAD_BYTES, ceiling: int | None = None) -> BinaryIO:
        headers = None
        if byte_range is not None:
            start, end = byte_range
            headers = {"Range": f"bytes={max(0, start)}-{max(0, end - 1)}"}
            max_bytes = max(1, end - start)
        buffer = io.BytesIO()
        try:
            result = self.transport.download(
                self.file_url(relpath), buffer.write, max_bytes=max_bytes,
                headers=headers, ceiling=ceiling,
            )
        except DiscoveryTransportError as exc:
            raise ResourceNotFound(f"{relpath}: {exc}") from exc
        if not 200 <= result.status < 300:
            raise ResourceNotFound(f"{relpath}: {self.manifest.name} answered {result.status}")
        buffer.seek(0)
        return buffer

    def stream(self, relpath: str, sink, *, max_bytes: int, ceiling: int, progress=None):
        result = self.transport.download(
            self.file_url(relpath), sink, max_bytes=max_bytes, ceiling=ceiling, progress=progress,
        )
        if not 200 <= result.status < 300:
            raise ResourceNotFound(f"{relpath}: {self.manifest.name} answered {result.status}")
        return result

    def local_path(self, relpath: str):
        return None


def _next_link(headers: dict, base: str) -> str | None:
    """The next page, only when it is on the Hub itself."""
    for name, value in (headers or {}).items():
        if name.lower() != "link":
            continue
        match = _NEXT_RE.search(str(value))
        if match and match.group(1).startswith(base + "/"):
            return match.group(1)
    return None


def _timestamp(text: str | None) -> float:
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
