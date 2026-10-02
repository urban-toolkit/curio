"""Add a storage resource to the Data Catalog.

The storage half of :mod:`application.acquire`. The manifest names the
resource; a fresh scan of that one resource finds its files as they are now;
and what is added depends on the kind:

- a **table** is copied, as every source copies data. One file lands as itself
  (a shapefile, a GeoPackage and a PBF are converted on the way in, as an
  upload of one is); several files combine into one Parquet table;
- every other kind is a **collection**: an index with one row per file,
  referenced where the files are.

Nothing here writes to the source.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.common.safe_paths import validate_component
from utk_curio.backend.app.common.user_storage import user_key_segment, users_base
from utk_curio.backend.app.discovery.application import combine_tables
from utk_curio.backend.app.discovery.application import index_collection
from utk_curio.backend.app.discovery.application import scan as scanning
from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    DownloadTooLarge,
    ResourceNotFound,
)
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure.transport import MAX_DISCOVERY_DOWNLOAD_BYTES
from utk_curio.backend.app.discovery.providers.storage_base import SHAPEFILE_PARTS

#: A file read from a folder on this machine costs no network, so its bound is
#: the disk's rather than the Discovery Catalog's download ceiling.
MAX_LOCAL_FILE_BYTES = 4 * 1024 * 1024 * 1024

#: GeoPackage and PBF conversion reads the whole file.
MAX_CONVERTED_FILE_BYTES = 512 * 1024 * 1024

CHUNK_BYTES = 1024 * 1024

#: Table formats installed as they are, without conversion.
DIRECT_FORMATS = ("csv", "json", "geojson", "parquet")

#: The manifest options that change how a CSV is read. A CSV declared with
#: any of them is read by them and lands as Parquet, the way many files do.
CSV_READ_OPTIONS = ("delimiter", "header")


class Cancelled(Exception):
    """The user asked for this to stop."""


def _iso_now() -> str:
    """Now, to the millisecond: a row added twice in one second is held by
    whichever add came last."""
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z"


def _narrowing(selection) -> dict[str, Any]:
    """Marks a dataset made from part of a row, so it never stands in for the row."""
    return {"narrowed": True} if selection.narrowed else {}


def _held_fingerprint(held: dict[str, Any]) -> str | None:
    """What the held dataset's files were when it was added."""
    return (held.get("collection") or {}).get("fingerprint") or (
        held.get("discoverySource") or {}
    ).get("fingerprint")


def _read_with_options(spec) -> bool:
    return spec.format == "csv" and any(key in spec.options for key in CSV_READ_OPTIONS)


class StorageAcquire:
    """Turns one storage resource row into Data Catalog datasets."""

    def __init__(
        self,
        *,
        user_key: str,
        storage_for: Callable[[DiscoverySourceManifest], Any],
        install_path: Callable[..., dict[str, Any]],
        import_layers: Callable[..., dict[str, Any]],
        find_held: Callable[[str, str, str | None], dict[str, Any] | None],
    ) -> None:
        self.user_key = user_key
        self._storage_for = storage_for
        self._install_path = install_path
        self._import_layers = import_layers
        self._find_held = find_held

    def acquire(
        self,
        manifest: DiscoverySourceManifest,
        resource_id: str,
        *,
        title: str | None = None,
        refresh: bool = False,
        filters: dict[str, Any] | None = None,
        files: list[str] | None = None,
        progress: Callable[[int, int | None], None] | None = None,
        items: Callable[[int, int | None], None] | None = None,
        stage: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        """Add the row *resource_id*. Returns ``{dataset, alreadyPresent, unchanged}``.

        *filters* and *files* narrow the row to some of its files. A narrowed
        add is always a new dataset: it is not the row, so holding one says
        nothing about holding the other.

        *refresh* adds a held row again. When its files are as they were, the
        held dataset is the answer; when they changed, a new dataset is added.
        """
        selection = scanning.narrow(
            scanning.parse_resource_id(manifest, resource_id), filters=filters, files=files
        )
        spec = selection.spec
        held = None if selection.narrowed else self._find_held(manifest.dir_name, resource_id, None)
        if held is not None and not refresh:
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        provider = self._storage_for(manifest)
        if stage:
            stage("Finding the files…")
        result = scanning.scan(manifest, provider, selection=selection, cancelled=cancelled)
        if cancelled is not None and cancelled():
            raise Cancelled()
        if result.truncated:
            raise DownloadTooLarge(
                f"{spec.name} has more than {manifest.max_files:,} files, the most "
                f"{manifest.name} adds at once; add part of it"
            )
        files = [f for group in result.groups for f in group.files]
        if not files:
            raise ResourceNotFound(f"no files of {manifest.name} match {resource_id}")
        name = scanning.group_name(result.groups[0]) if result.groups else spec.name
        fingerprint = index_collection.fingerprint(files)
        if held is not None and _held_fingerprint(held) == fingerprint:
            return {"dataset": held, "alreadyPresent": True, "unchanged": True}

        if spec.is_collection:
            dataset = self._add_collection(
                manifest, provider, spec, selection, files, resource_id=resource_id,
                title=title or name, items=items, stage=stage, cancelled=cancelled,
            )
            return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}
        if len(files) > 1 or _read_with_options(spec):
            dataset = self._add_combined(
                manifest, provider, spec, selection, files, resource_id=resource_id,
                title=title or name, items=items, stage=stage, cancelled=cancelled,
                fingerprint=fingerprint,
            )
            return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}

        only = files[0]
        discovery_source = {
            "sourceId": manifest.dir_name,
            "sourceName": manifest.name,
            "resourceId": resource_id,
            "sourcePath": only.relpath,
            "fileCount": 1,
            "fetchedAt": _iso_now(),
            "fingerprint": fingerprint,
            **_narrowing(selection),
        }
        dataset = self._add_file(
            manifest,
            provider,
            spec.format,
            only,
            title=title or name,
            discovery_source=discovery_source,
            held=held,
            progress=progress,
            cancelled=cancelled,
        )
        if dataset.get("alreadyPresent"):
            return dataset
        return {"dataset": dataset, "alreadyPresent": False, "unchanged": False}

    # ── a collection ───────────────────────────────────────────────────────

    def _add_collection(
        self, manifest, provider, spec, selection, files, *, resource_id, title, items, stage, cancelled
    ) -> dict[str, Any]:
        if stage:
            stage(f"Indexing {len(files):,} files…")
        rows = index_collection.build_rows(
            manifest, provider, spec, files, items=items, cancelled=cancelled
        )
        frame, columns = index_collection.to_frame(spec, rows)
        frame = index_collection.join_metadata(manifest, provider, spec, frame)
        if spec.metadata:
            columns = columns[:-3] + [
                c for c in frame.columns if c not in columns and c != "geometry"
            ] + columns[-3:]
        with tempfile.TemporaryDirectory(dir=self._tmp_dir()) as tmp:
            dest = Path(tmp) / "index.parquet"
            has_gps = index_collection.write_index(spec, frame, columns, dest)
            block = index_collection.collection_block(
                manifest, spec, resource_id, selection, files, frame, has_gps=has_gps
            )
            discovery_source = {
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": resource_id,
                "fileCount": len(files),
                "fields": ",".join(spec.template.names),
                "fetchedAt": _iso_now(),
                "fingerprint": block["fingerprint"],
                **_narrowing(selection),
            }
            label = scanning.KIND_LABEL.get(spec.kind, "Files").lower()
            return self._install_path(
                dest,
                "index.parquet",
                "collection",
                title=title,
                discovery_source=discovery_source,
                row_count=len(rows),
                collection=block,
                description=(
                    f"{len(files):,} {label} from {manifest.name}, indexed where they are."
                ),
            )

    # ── many table files ───────────────────────────────────────────────────

    def _add_combined(
        self, manifest, provider, spec, selection, files, *, resource_id, title, items, stage,
        cancelled, fingerprint,
    ) -> dict[str, Any]:
        local = manifest.provider.type == "folder"
        combine_tables.check_bounds(files, local=local)
        if stage:
            stage(f"Combining {len(files):,} files…")
        with tempfile.TemporaryDirectory(dir=self._tmp_dir()) as tmp:
            tmp_dir = Path(tmp)
            dest = tmp_dir / f"{spec.id}.parquet"
            combined = combine_tables.combine(
                spec,
                files,
                stage=lambda found, into, index: self._stage_for_combine(
                    manifest, provider, spec, found, into, index, cancelled
                ),
                tmp=tmp_dir,
                dest=dest,
                items=items,
                cancelled=cancelled,
            )
            discovery_source = {
                "sourceId": manifest.dir_name,
                "sourceName": manifest.name,
                "resourceId": resource_id,
                "fileCount": len(files),
                "fields": ",".join(spec.template.names),
                "fetchedAt": _iso_now(),
                "fingerprint": fingerprint,
                **_narrowing(selection),
            }
            if len(files) == 1:
                discovery_source["sourcePath"] = files[0].relpath
                description = f"Read from {files[0].relpath} of {manifest.name}."
            else:
                description = f"Combined from {len(files):,} {spec.format} files of {manifest.name}."
            return self._install_path(
                combined.path,
                dest.name,
                "parquet",
                title=title,
                discovery_source=discovery_source,
                row_count=combined.rows,
                description=description,
            )

    def _stage_for_combine(
        self, manifest, provider, spec, found, into: Path, index: int, cancelled
    ) -> Path:
        """A local path to read *found* from, UTF-8 when it is text."""
        from utk_curio.backend.app.datasets.infrastructure.text_encoding import (
            TextDecodeError,
            _first_invalid_utf8,
            transcode_file_to_utf8,
        )

        local = provider.local_path(found.relpath)
        if local is None:
            if spec.format == "shp":
                folder = into / f"part-{index:06d}"
                folder.mkdir()
                local, _sha = self._stage_shapefile(
                    provider, found, folder, self._bound(manifest), None, cancelled
                )
            else:
                local = into / f"part-{index:06d}{Path(found.relpath).suffix.lower()}"
                self._copy(provider, found.relpath, local, self._bound(manifest), found.size, None, cancelled)
        if spec.format in ("csv", "json", "geojson") and _first_invalid_utf8(local) is not None:
            target = into / f"part-{index:06d}-utf8{Path(found.relpath).suffix.lower()}"
            try:
                transcode_file_to_utf8(local, target, what=found.relpath)
            except TextDecodeError as exc:
                raise combine_tables.CombineError(str(exc)) from exc
            return target
        return Path(local)

    # ── one table file ─────────────────────────────────────────────────────

    def _bound(self, manifest: DiscoverySourceManifest) -> int:
        if manifest.provider.type == "folder":
            return MAX_LOCAL_FILE_BYTES
        return min(manifest.capabilities.max_download_bytes, MAX_DISCOVERY_DOWNLOAD_BYTES)

    def _add_file(
        self,
        manifest,
        provider,
        fmt: str,
        found,
        *,
        title: str,
        discovery_source: dict[str, Any],
        held,
        progress,
        cancelled,
    ) -> dict[str, Any]:
        bound = self._bound(manifest)
        if fmt in ("gpkg", "pbf"):
            bound = min(bound, MAX_CONVERTED_FILE_BYTES)
        if found.size > bound:
            raise DownloadTooLarge(
                f"{found.relpath} is {found.size:,} bytes; the limit here is {bound:,}"
            )
        filename = _filename(found.relpath)
        with tempfile.TemporaryDirectory(dir=self._tmp_dir()) as tmp:
            work = Path(tmp)
            if fmt == "shp":
                # Its sha covers every part, so a changed .dbf is a change.
                staged, sha = self._stage_shapefile(provider, found, work, bound, progress, cancelled)
            else:
                staged = work / filename
                sha = self._copy(provider, found.relpath, staged, bound, found.size, progress, cancelled)
            if held is not None and (held.get("discoverySource") or {}).get("contentSha256") == sha:
                return {"dataset": held, "alreadyPresent": True, "unchanged": True}
            discovery_source = {**discovery_source, "contentSha256": sha}
            if fmt in DIRECT_FORMATS:
                return self._install_path(staged, filename, fmt, title=title, discovery_source=discovery_source)
            if fmt == "shp":
                parquet = work / (Path(filename).stem + ".parquet")
                _shapefile_to_parquet(staged, parquet)
                return self._install_path(
                    parquet, parquet.name, "parquet", title=title, discovery_source=discovery_source
                )
            if fmt in ("gpkg", "pbf"):
                return self._import_layers(
                    fmt, staged.read_bytes(), filename, title=title, discovery_source=discovery_source
                )
        raise CapabilityUnsupported(f"{fmt} cannot be added from {manifest.name}")

    def _stage_shapefile(self, provider, found, work: Path, bound, progress, cancelled) -> tuple[Path, str]:
        """The shapefile and its parts, staged under one name, and one sha of them all.

        The parts are the ones the scan found beside it, in whatever case the
        source names them (``roads.DBF`` beside ``roads.SHP``), and are staged
        in lower case beside ``data.shp``, where the reader looks for them.
        """
        folder = work / "shapefile"
        folder.mkdir()
        shp = folder / "data.shp"
        digest = hashlib.sha256()
        sha = self._copy(provider, found.relpath, shp, bound, found.size, progress, cancelled)
        digest.update(f".shp {sha}\n".encode())
        parts = {part.relpath[-4:].lower(): part for part in found.parts}
        for suffix in SHAPEFILE_PARTS:
            part = parts.get(suffix)
            if part is None:
                if suffix in (".dbf", ".shx"):
                    raise ResourceNotFound(f"{found.relpath} needs its {suffix} beside it")
                continue
            part_sha = self._copy(provider, part.relpath, folder / f"data{suffix}", bound, part.size, None, cancelled)
            digest.update(f"{suffix} {part_sha}\n".encode())
        return shp, digest.hexdigest()

    def _copy(self, provider, relpath, dest: Path, bound, total, progress, cancelled) -> str:
        """Stream one file of the source into *dest*, capped and hashed."""
        digest = hashlib.sha256()
        written = 0
        with provider.open(relpath) as source, dest.open("wb") as out:
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > bound:
                    raise DownloadTooLarge(f"{relpath} is larger than the {bound:,}-byte limit")
                digest.update(chunk)
                out.write(chunk)
                if progress is not None:
                    progress(written, total)
        return digest.hexdigest()

    def _tmp_dir(self) -> Path:
        path = users_base() / user_key_segment(self.user_key) / "discovery" / "tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path


_SUFFIX_RE = re.compile(r"\.[a-z0-9]{1,16}")


def _filename(relpath: str) -> str:
    """A store-safe filename for *relpath*'s last part, keeping its extension."""
    from werkzeug.utils import secure_filename

    last = relpath.rsplit("/", 1)[-1]
    suffix = Path(last).suffix.lower()
    if not _SUFFIX_RE.fullmatch(suffix):
        suffix = ""
    stem = secure_filename(last[: len(last) - len(suffix)]) or "data"
    return validate_component(stem[: 120 - len(suffix)] + suffix, field="file name")


def _shapefile_to_parquet(shp: Path, dest: Path) -> None:
    """Convert a shapefile with its siblings to GeoParquet in EPSG:4326."""
    import geopandas as gpd

    frame = gpd.read_file(shp)
    if frame.crs is not None and frame.crs.to_epsg() != 4326:
        frame = frame.to_crs(4326)
    frame.to_parquet(dest)

