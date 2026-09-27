"""Index a collection resource: one row per file, the files left where they are.

A folder of tiles, frames, photos or recordings is one dataset. What lands in
the Data Catalog is its index, a Parquet table with one row per file:

- who the file is: ``file_id`` (stable across re-indexing), ``relpath``,
  ``name``, ``ext``, ``kind``, ``bytes``, ``mtime``;
- every capture of the resource's template, typed (a ``year``, a ``sensor``);
- what the file says about itself, by kind: size and EXIF time and GPS for an
  image, duration and codec for video and audio, CRS, bands and a footprint
  for a raster;
- for frames, ``sequence``, ``frame`` and ``t_s``;
- the columns of a declared metadata table, joined on ``file_name``, ``frame``
  or a capture.

Rasters are indexed as GeoParquet with each tile's footprint, and so are
photos and frames that carry a position. Nothing is written to the source.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.datalakes.application import probe as probing
from utk_curio.backend.app.datalakes.application.scan import MatchedFile
from utk_curio.backend.app.datalakes.domain.errors import DataLakeError
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest, ResourceSpec
from utk_curio.backend.app.datalakes.domain.templates import compile_template

PROBE_WORKERS = 4

#: Enough of a remote file for Pillow to read an image's size and EXIF, and
#: for GDAL to read a Cloud-Optimized GeoTIFF's georeferencing.
PROBE_BYTES = 64 * 1024

#: Names the index uses, in the order its columns appear.
LEADING_COLUMNS = ("file_id", "relpath", "name", "ext", "kind")
TRAILING_COLUMNS = ("bytes", "mtime", "probe_error")


class IndexError_(DataLakeError):
    """A collection that cannot be indexed."""


def file_id(relpath: str) -> str:
    """Stable for a relpath, so re-indexing keeps every row's id."""
    return hashlib.sha1(relpath.encode("utf-8")).hexdigest()[:16]


def fingerprint(files: list[MatchedFile]) -> str:
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda f: f.relpath):
        digest.update(f"{f.relpath}\0{f.size}\0{f.mtime:.3f}\n".encode("utf-8"))
    return digest.hexdigest()


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


def build_rows(
    manifest: LakeSourceManifest,
    provider,
    spec: ResourceSpec,
    files: list[MatchedFile],
    *,
    items: Callable[[int, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """One dict per file, probed on a small pool, in relpath order."""
    kinds = [probing.file_kind(spec.kind, f.relpath) for f in files]

    def work(pair):
        found, kind = pair
        if cancelled is not None and cancelled():
            return {}
        local = provider.local_path(found.relpath)
        if local is not None:
            return probing.probe(kind, Path(local))
        if kind not in ("image", "frame", "raster"):
            return {"probe_error": "a video or recording in a bucket is indexed without being read"}
        return _probe_remote_head(provider, found, kind)

    rows: list[dict[str, Any]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        for found, kind, details in zip(files, kinds, pool.map(work, zip(files, kinds))):
            if cancelled is not None and cancelled():
                from utk_curio.backend.app.datalakes.application.storage_acquire import Cancelled

                raise Cancelled()
            name = found.relpath.rsplit("/", 1)[-1]
            row: dict[str, Any] = {
                "file_id": file_id(found.relpath),
                "relpath": found.relpath,
                "name": name,
                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                "kind": kind,
            }
            row.update(found.values)
            row.update(details)
            row["bytes"] = found.size
            row["mtime"] = _utc(found.mtime)
            rows.append(row)
            done += 1
            if items is not None and (done % 50 == 0 or done == len(files)):
                items(done, len(files))
    _fill_time(spec, rows)
    if spec.kind == "frames":
        _number_frames(spec, rows)
    return rows


def _probe_remote_head(provider, found: MatchedFile, kind: str) -> dict[str, Any]:
    """Probe a remote file from its first bytes, fetched with one Range read."""
    import tempfile

    try:
        head = provider.open(found.relpath, byte_range=(0, PROBE_BYTES)).read()
    except DataLakeError as exc:
        return {"probe_error": str(exc)[:200]}
    suffix = "." + found.relpath.rsplit(".", 1)[-1] if "." in found.relpath else ""
    with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
        handle.write(head)
        handle.flush()
        details = probing.probe(kind, Path(handle.name))
    if details.get("probe_error") and len(head) >= PROBE_BYTES:
        details["probe_error"] = f"its details are past the first {PROBE_BYTES // 1024} KiB read from the source"
    return details


def _fill_time(spec: ResourceSpec, rows: list[dict[str, Any]]) -> None:
    """A declared ``time`` capture is the file's timestamp."""
    if not spec.time:
        return
    column = "recorded_at" if spec.kind == "audio" else "taken_at"
    for row in rows:
        value = row.get(spec.time)
        if isinstance(value, datetime):
            row[column] = value
        elif isinstance(value, date):
            row[column] = datetime(value.year, value.month, value.day)


def _number_frames(spec: ResourceSpec, rows: list[dict[str, Any]]) -> None:
    """Every frame gets a sequence, a number and, with a frame rate, a time."""
    for row in rows:
        if not row.get("sequence"):
            parts = row["relpath"].split("/")
            row["sequence"] = parts[-2] if len(parts) > 1 else ""
    by_sequence: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_sequence.setdefault(str(row["sequence"]), []).append(row)
    for members in by_sequence.values():
        members.sort(key=lambda r: (r.get("frame") is None, r.get("frame") or 0, r["relpath"]))
        first = None
        for index, row in enumerate(members):
            if row.get("frame") is None:
                row["frame"] = index
            first = row["frame"] if first is None else first
            row["t_s"] = round((row["frame"] - first) / spec.fps, 6) if spec.fps else None


def join_metadata(
    manifest: LakeSourceManifest, provider, spec: ResourceSpec, frame
):
    """Join the resource's declared metadata table onto its index."""
    if not spec.metadata:
        return frame
    import pandas as pd

    template = compile_template(spec.metadata["path"], reserved=frozenset())
    on = spec.metadata.get("on") or "file_name"
    tables = []
    for entry in provider.scan(template.literal_prefix):
        values = template.match(entry.relpath)
        if values is None:
            continue
        local = provider.local_path(entry.relpath)
        if local is None:
            continue
        try:
            table = pd.read_csv(local, encoding="utf-8-sig")
        except (UnicodeDecodeError, ValueError):
            table = pd.read_csv(local, encoding="cp1252")
        for name, value in values.items():
            table[name] = value
        tables.append(table)
    if not tables:
        return frame
    meta = pd.concat(tables, ignore_index=True)
    left_key = "name" if on == "file_name" else on
    if on not in meta.columns:
        raise IndexError_(f"{spec.name}: the metadata table has no {on!r} column to join on")
    shared = [
        c.name for c in template.captures
        if c.name in frame.columns and c.name != left_key
    ]
    meta = meta.rename(columns={on: left_key})
    clash = {c: f"{c}_meta" for c in meta.columns if c in frame.columns and c not in shared + [left_key]}
    meta = meta.rename(columns=clash)
    for column in shared + [left_key]:
        if column in meta.columns and column in frame.columns:
            try:
                meta[column] = meta[column].astype(frame[column].dtype)
            except (TypeError, ValueError):
                meta[column] = meta[column].astype(str)
                frame[column] = frame[column].astype(str)
    joined = frame.merge(meta.drop_duplicates(subset=shared + [left_key]), how="left", on=shared + [left_key])
    # A telemetry table that says where each file was is where it was.
    for lat, lon in (("lat", "lon"), ("latitude", "longitude")):
        if lat in joined.columns and lon in joined.columns:
            joined["gps_lat"] = joined.get("gps_lat", pd.Series(index=joined.index, dtype=float))
            joined["gps_lon"] = joined.get("gps_lon", pd.Series(index=joined.index, dtype=float))
            joined["gps_lat"] = joined["gps_lat"].fillna(joined[lat])
            joined["gps_lon"] = joined["gps_lon"].fillna(joined[lon])
            break
    return joined


def to_frame(spec: ResourceSpec, rows: list[dict[str, Any]]):
    """The index as a DataFrame, or a GeoDataFrame when rows have a place."""
    import pandas as pd

    frame = pd.DataFrame(rows)
    if "transform" in frame.columns:
        frame["transform"] = frame["transform"].map(
            lambda t: json.dumps(t) if isinstance(t, list) else None
        )
    captures = [c.name for c in spec.template.captures]
    middle = [c for c in frame.columns if c not in LEADING_COLUMNS + TRAILING_COLUMNS + ("geometry",)]
    ordered_middle = [c for c in captures if c in middle] + [c for c in middle if c not in captures]
    columns = [c for c in LEADING_COLUMNS if c in frame.columns] + ordered_middle
    columns += [c for c in TRAILING_COLUMNS if c in frame.columns]
    if "probe_error" not in frame.columns:
        frame["probe_error"] = None
        columns.append("probe_error")
    return frame, columns


def write_index(spec: ResourceSpec, frame, columns, dest: Path) -> bool:
    """Write the index; returns whether it carries positions."""
    import geopandas as gpd
    from shapely.geometry import Point

    if "geometry" in frame.columns:
        gdf = gpd.GeoDataFrame(frame[columns], geometry=frame["geometry"], crs=4326)
        gdf.to_parquet(dest)
        return bool(gdf.geometry.notna().any())
    if {"gps_lat", "gps_lon"} <= set(frame.columns) and frame["gps_lat"].notna().any():
        points = [
            Point(lon, lat) if lat == lat and lon == lon and lat is not None and lon is not None else None
            for lat, lon in zip(frame["gps_lat"], frame["gps_lon"])
        ]
        gdf = gpd.GeoDataFrame(frame[columns], geometry=points, crs=4326)
        gdf.to_parquet(dest)
        return True
    frame[columns].to_parquet(dest, index=False)
    return False


def collection_block(
    manifest: LakeSourceManifest,
    spec: ResourceSpec,
    resource_id: str,
    selection,
    files: list[MatchedFile],
    frame,
    *,
    has_gps: bool,
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for kind in frame["kind"]:
        counts[kind] = counts.get(kind, 0) + 1
    errors = int(frame["probe_error"].notna().sum()) if "probe_error" in frame.columns else 0
    block: dict[str, Any] = {
        "kind": spec.kind,
        "sourceId": manifest.dir_name,
        "sourceName": manifest.name,
        "provider": manifest.provider.type,
        "resourceId": resource_id,
        "resource": spec.id,
        "path": spec.path,
        "fields": list(spec.template.names),
        "counts": counts,
        "fileCount": len(files),
        "totalBytes": sum(f.size for f in files),
        "hasGps": has_gps,
        "probeErrors": errors,
        "indexedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fingerprint": fingerprint(files),
    }
    if selection.split:
        block["split"] = dict(selection.split)
    if selection.narrowed:
        block["narrowedBy"] = selection.describe()
        if selection.files is not None:
            block["chosenFiles"] = len(selection.files)
    if spec.fps:
        block["fps"] = spec.fps
    if spec.kind == "frames" and "sequence" in frame.columns:
        block["sequences"] = int(frame["sequence"].nunique())
    if spec.kind == "audio" and "duration_s" in frame.columns:
        block["totalSeconds"] = round(float(frame["duration_s"].fillna(0).sum()), 3)
    return block
