"""Download a portal resource into the Data Catalog.

The seam between the two catalogs, and the only place this package writes
anything. What comes out the far end is an **ordinary dataset** - manifest,
preview, schema, ``curio_data_path()`` loader - so nothing downstream has to
learn that portals exist. It carries a ``discoverySource`` block recording where it
came from, which is what makes "do I already hold this?" answerable.

The shape of the work:

    already held? ─ yes ─> return it, having made no request at all
         │ no
         v
    describe ──> download_url ──> stream to a temp file under the user's own
                                  tree, capped, hashed
                                        │
                                        v
                                  a zip or a gzip is unpacked (archives.py)
                                        │
                                        v
                                  resolve the format from what actually arrived
                                        │
                                        v
                                  _install_imported_path  (moves the file into
                                                           the Data Catalog)

An archive Curio does not unpack is refused as early as it can be told apart:
by the resource's name before any request, and by the response's headers
before its body.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from utk_curio.backend.app.common.safe_paths import validate_component
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.discovery.application import archives
from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    DownloadTooLarge,
    ResourceNotFound,
    UnsupportedFormatError,
)
from utk_curio.backend.app.datasets.domain.constants import (
    GTFS_GROUP_ID_PREFIX,
    SUPPORTED_SUFFIXES,
)
from utk_curio.backend.app.discovery.domain.formats import (
    SNIFF_BYTES,
    archive_kind,
    content_type_of,
    disposition_filename,
    refuse_archives,
    refuse_sniffed_archive,
    resolve_format,
    safe_remote_filename,
    sniff_archive,
)
from utk_curio.backend.app.discovery.domain import parameters as P
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure import ratelimit
from utk_curio.backend.app.discovery.infrastructure.transport import (
    MAX_DISCOVERY_DOWNLOAD_BYTES,
)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class DiscoveryAcquire:
    """Turns a portal resource into a Data Catalog dataset."""

    def __init__(
        self,
        *,
        user,
        user_key: str,
        transport_for: Callable[[DiscoverySourceManifest], Any],
        download_target: Callable[[DiscoverySourceManifest, str, str | None], Any],
        install_path: Callable[..., dict[str, Any]],
        find_held: Callable[[str, str, str | None], dict[str, Any] | None],
        describe: Callable[[DiscoverySourceManifest, str], Any] | None = None,
        find_by_content: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.user = user
        self.user_key = user_key
        self._transport_for = transport_for
        self._download_target = download_target
        self._install_path = install_path
        self._find_held = find_held
        self._describe = describe
        self._find_by_content = find_by_content

    # ── the check that avoids the network entirely ─────────────────────────

    def already_held(
        self,
        manifest: DiscoverySourceManifest,
        resource_id: str,
        fmt: str | None,
        *,
        parameters_hash: str | None = None,
    ) -> dict[str, Any] | None:
        return self._find_held(manifest.dir_name, resource_id, fmt, parameters_hash)

    # ── the work ───────────────────────────────────────────────────────────

    def acquire(
        self,
        manifest: DiscoverySourceManifest,
        resource_id: str,
        *,
        fmt: str | None = None,
        title: str | None = None,
        refresh: bool = False,
        parameters: dict[str, Any] | None = None,
        progress: Callable[[int, int | None], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        stage: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Download and register. Returns ``{dataset, alreadyPresent, unchanged}``.

        *parameters* are answers already checked against the manifest
        (``service.start_acquire``): the provider narrows the download by them,
        and the dataset records them. *stage* is told what the work is doing
        once the bytes are in, while an archive is unpacked.
        """
        if not manifest.capabilities.download:
            raise CapabilityUnsupported(f"{manifest.name} does not offer downloads")

        values = dict(parameters or {})
        values_hash = P.values_hash(values) if values else None
        held = self.already_held(manifest, resource_id, fmt, parameters_hash=values_hash)
        if held is not None and not refresh:
            # The whole point of recording the resource id: this path issues no
            # request at all, so re-clicking Download costs a portal nothing.
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        target = self._download_target(manifest, resource_id, fmt, values)
        if not target or not target.url:
            raise ResourceNotFound(f"{resource_id} has no download URL")

        # An archive Curio does not unpack, named as one, costs no request.
        refuse_archives("", target.filename_hint)
        refuse_archives("", _url_name(target.url))

        def before_body(headers: dict, final_url: str) -> None:
            # Named or labelled as one by the response: refused before its body.
            refuse_archives(
                content_type_of(headers), disposition_filename(headers) or _url_name(final_url)
            )

        def check() -> None:
            if cancelled is not None and cancelled():
                raise _Cancelled()

        bound = min(manifest.capabilities.max_download_bytes, MAX_DISCOVERY_DOWNLOAD_BYTES)
        transport = self._transport_for(manifest)

        tmp_dir = self._tmp_dir()
        tmp_path = tmp_dir / f"{validate_component(_token())}.part"
        work: Path | None = None
        head = bytearray()
        written = 0

        def sink_factory(handle):
            def sink(chunk: bytes) -> None:
                nonlocal written
                check()
                if len(head) < SNIFF_BYTES:
                    head.extend(chunk[: SNIFF_BYTES - len(head)])
                handle.write(chunk)
                written += len(chunk)

            return sink

        try:
            with open(tmp_path, "wb") as handle:
                result = transport.download(
                    target.url,
                    sink_factory(handle),
                    max_bytes=bound,
                    progress=progress,
                    before_body=before_body,
                )

            headers = dict(result.headers or {})
            final_url = getattr(result, "final_url", target.url)
            allowed = tuple(manifest.capabilities.formats)
            discovery_source = {
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": resource_id,
                "resourceUrl": target.url,
                "finalUrl": final_url,
                "fetchedAt": _iso_now(),
                "contentSha256": result.sha256,
                # What the download was narrowed by, so the Data Catalog
                # can say it and an identical add finds it held.
                **({"parameters": values, "parametersHash": values_hash} if values else {}),
            }
            kind, inner_name = _archive_of(headers, final_url, target.filename_hint, bytes(head))
            source_path = tmp_path
            default_title = target.filename_hint
            if kind is None:
                fmt_detected, filename = resolve_format(
                    declared=target.declared_format,
                    final_url=final_url,
                    headers=headers,
                    head=bytes(head),
                    allowed=allowed,
                    # A gzip's name, and its bytes already unpacked on the way.
                    **({"filename": inner_name} if inner_name else {}),
                )
            else:
                # The archive's bytes decide whether it is held, before the
                # work of unpacking it.
                same = self._held_by_content(held, result.sha256)
                if same is not None:
                    return same
                if stage is not None:
                    stage("Unpacking…")
                work = Path(tempfile.mkdtemp(prefix="unpack", dir=tmp_dir))
                unpacked = archives.unpack(kind, tmp_path, name=inner_name, work=work, check=check)
                # Named after the archive, less its .zip or .gz: the page names
                # a pasted link's download after the link's last segment.
                default_title = _without_archive_suffix(target.filename_hint or "") or None
                title = _without_archive_suffix(title.strip()) if title else title
                if isinstance(unpacked, archives.GtfsFeed):
                    _offers(allowed, "parquet", "a GTFS feed")
                    if stage is not None:
                        stage("Converting the GTFS feed…")
                    dataset = self._add_feed(
                        unpacked, work,
                        prefix=(title or "").strip() or default_title or "GTFS feed",
                        discovery_source=discovery_source,
                        check=check,
                    )
                    return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}
                if isinstance(unpacked, archives.Shapefile):
                    _offers(allowed, "parquet", "a zipped shapefile")
                    from utk_curio.backend.app.discovery.application.storage_acquire import (
                        _shapefile_to_parquet,
                    )

                    source_path = work / "shapefile.parquet"
                    try:
                        _shapefile_to_parquet(unpacked.path, source_path)
                    except Exception as exc:  # noqa: BLE001 - the reader's own words
                        raise UnsupportedFormatError(
                            f"the shapefile {unpacked.name!r} could not be read ({exc})"
                        ) from exc
                    fmt_detected = "parquet"
                    filename = safe_remote_filename(
                        f"{Path(unpacked.name).stem}.parquet", fallback="shapefile.parquet"
                    )
                else:
                    with open(unpacked.path, "rb") as inner:
                        inner_head = inner.read(SNIFF_BYTES)
                    named = os.path.splitext(unpacked.name.lower())[1] in SUPPORTED_SUFFIXES
                    fmt_detected, filename = resolve_format(
                        # What the provider asked for, only when the file's own
                        # name says nothing.
                        declared=None if named else target.declared_format,
                        final_url=final_url,
                        headers={},
                        head=inner_head,
                        allowed=allowed,
                        filename=unpacked.name,
                    )
                    source_path = unpacked.path

            # Held again, now that the real format is known: a caller who asked
            # for no particular format may already hold what the portal chose.
            if not refresh:
                held = self.already_held(
                    manifest, resource_id, fmt_detected, parameters_hash=values_hash
                )
                if held is not None:
                    return {"dataset": held, "alreadyPresent": True, "unchanged": True}

            if kind is None:
                same = self._held_by_content(held, result.sha256)
                if same is not None:
                    return same

            # The file moves into the Data Catalog as it is, never through
            # memory: the install consumes the temp file.
            dataset = self._install_path(
                source_path,
                filename,
                fmt_detected,
                title=title or (default_title or filename),
                discovery_source=discovery_source,
            )
        except _Cancelled:
            raise
        finally:
            tmp_path.unlink(missing_ok=True)
            if work is not None:
                shutil.rmtree(work, ignore_errors=True)

        # A changed resource mints a NEW dataset rather than overwriting the
        # held one: a saved dataflow loads that dataset by id, and rewriting its
        # bytes would change that dataflow's results with nothing on screen to
        # explain it.
        return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}

    def _held_by_content(self, held, sha256: str) -> dict[str, Any] | None:
        """The answer when these bytes are already held, else None."""
        if held is not None and held.get("discoverySource", {}).get("contentSha256") == sha256:
            # A refresh that found nothing new. The bytes were paid for; a
            # second identical row would not be.
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}
        # The same bytes may already be here from another path: a file the
        # person downloaded by hand and imported with its origin.
        same = self._find_by_content(sha256) if self._find_by_content else None
        if same is not None:
            return {"dataset": same, "alreadyPresent": True, "unchanged": True}
        return None

    def _add_feed(
        self,
        feed: archives.GtfsFeed,
        work: Path,
        *,
        prefix: str,
        discovery_source: dict[str, Any],
        check: Callable[[], None],
    ) -> dict[str, Any]:
        """A GTFS feed as one layer group: a dataset per table, sharing a
        ``gtfs.x<hex>`` group id, each titled ``<prefix> (<table>)``.

        Returns the first, with how many there are, as an OSM download does.
        """
        from utk_curio.backend.app.discovery.application import gtfs

        layers = gtfs.convert(feed.tables, work, check=check)
        # One group per download, never derived from content, so the same feed
        # downloaded again forms its own group.
        group_id = f"{GTFS_GROUP_ID_PREFIX}x{uuid.uuid4().hex[:8]}"
        items = []
        for layer in layers:
            check()
            counts = {"feature_count": layer.rows} if layer.geometry else {"row_count": layer.rows}
            items.append(
                self._install_path(
                    layer.path,
                    f"{layer.name}.parquet",
                    "parquet",
                    title=f"{prefix} ({layer.name})",
                    discovery_source=discovery_source,
                    group_id=group_id,
                    layer_name=layer.name,
                    **counts,
                )
            )
        primary = items[0]
        primary["importedDatasetCount"] = len(items)
        return primary

    # ── where the bytes land on the way in ─────────────────────────────────

    def _tmp_dir(self) -> Path:
        """A per-user staging directory, not /tmp.

        These are user data under a tree we already own and can scope, and a
        crashed job leaves an orphan somewhere a sweep can find it rather than
        in a shared system directory.
        """
        # ``user_key_segment`` rather than ``validate_component``: it is
        # stricter, allowing only a numeric id or the guest key, so a username
        # passed where an id belongs cannot become a directory name.
        path = users_base() / user_key_segment(self.user_key) / "discovery" / "tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path


class _Cancelled(Exception):
    """The user asked for this download to stop."""


def _token() -> str:
    return f"dl{uuid.uuid4().hex[:16]}"


def _url_name(url: str | None) -> str | None:
    """The last segment of *url*'s path, decoded, or None."""
    try:
        name = posixpath.basename(urlparse(url or "").path or "")
    except ValueError:
        return None
    return unquote(name) or None


def _archive_of(
    headers: dict, final_url: str, hint: str | None, head: bytes
) -> tuple[str | None, str | None]:
    """``(kind, name)`` for what arrived.

    ``("zip", name)`` and ``("gzip", inner name)`` are unpacked; any other
    archive raises. ``(None, inner name)`` is a file named or labelled as a
    gzip whose bytes are not one, which a server that compressed it for the
    journey hands over already unpacked; ``(None, None)`` is not an archive.
    """
    content_type = content_type_of(headers)
    name = disposition_filename(headers) or _url_name(final_url) or hint
    refuse_archives(content_type, name)
    refuse_sniffed_archive(head)
    kind = archive_kind(content_type, name, head)
    sniffed = sniff_archive(head)
    if kind == "zip":
        if sniffed != "zip":
            raise UnsupportedFormatError(
                "that resource is labelled a zip archive, and its bytes are not a zip archive"
            )
        return "zip", name
    if kind == "gzip":
        inner = archives.gzip_member_name(name, head)
        return ("gzip", inner) if sniffed == "gzip" else (None, inner)
    return None, None


def _without_archive_suffix(name: str) -> str:
    lowered = name.lower()
    for suffix in (".zip", ".gz"):
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _offers(allowed: tuple[str, ...], fmt: str, what: str) -> None:
    """Refuse *what* when the source does not deliver *fmt*, the format it lands as."""
    if fmt not in allowed:
        raise UnsupportedFormatError(
            f"that resource is {what}, which lands as {fmt.upper()}, and this source is "
            f"not configured to deliver it (it offers {', '.join(allowed) or 'nothing'})."
        )
