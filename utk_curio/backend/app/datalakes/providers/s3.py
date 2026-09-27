"""A public S3 bucket, or any endpoint that speaks S3's ListObjectsV2.

Listed with ``GET {base}/?list-type=2&prefix=...``, one page of up to 1000 keys
at a time, and read with a plain GET (with a ``Range`` header for a probe of a
file's header). Every request goes through the lake transport, so the egress
policy applies to each one, redirects included. Anonymous access only: a
bucket that needs a signed request is not one this provider reads.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import BinaryIO, ClassVar, Iterator
from urllib.parse import quote

from utk_curio.backend.app.datalakes.domain.errors import ProviderError, ResourceNotFound
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest
from utk_curio.backend.app.datalakes.infrastructure.transport import (
    MAX_LAKE_DOWNLOAD_BYTES,
    LakeTransportError,
)
from utk_curio.backend.app.datalakes.providers.storage_base import (
    FileEntry,
    is_skipped,
    validate_relpath,
)

_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

#: Pages listed per scan at most: 1000 keys each.
MAX_PAGES = 400


class S3Storage:
    type: ClassVar[str] = "s3"

    def __init__(self, manifest: LakeSourceManifest, transport) -> None:
        self.manifest = manifest
        self.transport = transport
        self.base = manifest.provider.base_url
        self.prefix = str(manifest.provider.options.get("prefix") or "")

    # ── urls ───────────────────────────────────────────────────────────────

    def _list_url(self, prefix: str, token: str | None) -> str:
        url = f"{self.base}/?list-type=2&max-keys=1000&prefix={quote(self.prefix + prefix, safe='')}"
        if token:
            url += f"&continuation-token={quote(token, safe='')}"
        return url

    def object_url(self, relpath: str) -> str:
        validate_relpath(relpath)
        url = f"{self.base}/{quote(self.prefix + relpath, safe='/')}"
        if not url.startswith(self.base + "/"):
            raise ResourceNotFound("not a file of this source")
        return url

    # ── the contract ───────────────────────────────────────────────────────

    def scan(self, prefix: str = "") -> Iterator[FileEntry]:
        token = None
        for _page in range(MAX_PAGES):
            body = self.transport.json_get(self._list_url(prefix, token))
            try:
                root = ET.fromstring(body if isinstance(body, str) else str(body))
            except ET.ParseError as exc:
                raise ProviderError(f"{self.manifest.name} answered a listing that is not XML") from exc
            for item in root.iter(f"{_NS}Contents"):
                key = item.findtext(f"{_NS}Key") or ""
                if not key.startswith(self.prefix) or key.endswith("/"):
                    continue
                relpath = key[len(self.prefix):]
                if not relpath or any(is_skipped(part) for part in relpath.split("/")):
                    continue
                yield FileEntry(
                    relpath=relpath,
                    size=int(item.findtext(f"{_NS}Size") or 0),
                    mtime=_timestamp(item.findtext(f"{_NS}LastModified")),
                    etag=(item.findtext(f"{_NS}ETag") or "").strip('"') or None,
                )
            if (root.findtext(f"{_NS}IsTruncated") or "").lower() != "true":
                return
            token = root.findtext(f"{_NS}NextContinuationToken")
            if not token:
                return

    def open(self, relpath: str, *, byte_range: tuple[int, int] | None = None,
             max_bytes: int = MAX_LAKE_DOWNLOAD_BYTES, ceiling: int | None = None) -> BinaryIO:
        headers = None
        if byte_range is not None:
            start, end = byte_range
            headers = {"Range": f"bytes={max(0, start)}-{max(0, end - 1)}"}
            max_bytes = max(1, end - start)
        buffer = io.BytesIO()
        try:
            result = self.transport.download(
                self.object_url(relpath), buffer.write, max_bytes=max_bytes,
                headers=headers, ceiling=ceiling,
            )
        except LakeTransportError as exc:
            raise ResourceNotFound(f"{relpath}: {exc}") from exc
        if not 200 <= result.status < 300:
            raise ResourceNotFound(f"{relpath}: {self.manifest.name} answered {result.status}")
        buffer.seek(0)
        return buffer

    def stream(self, relpath: str, sink, *, max_bytes: int, ceiling: int, progress=None):
        """Write one file straight to *sink*, for caching it to disk."""
        result = self.transport.download(
            self.object_url(relpath), sink, max_bytes=max_bytes, ceiling=ceiling, progress=progress,
        )
        if not 200 <= result.status < 300:
            raise ResourceNotFound(f"{relpath}: {self.manifest.name} answered {result.status}")
        return result

    def local_path(self, relpath: str):
        return None


def _timestamp(text: str | None) -> float:
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0
