"""The part of remote GeoParquet files that an area needs.

Overture's files, a Direct URL link and a bucket row are read the same way:

1. each file's footer, and the row groups whose box statistics meet the area;
2. a refusal, before any row group is fetched, when the footers and those row
   groups take more bytes than one download reads;
3. those row groups, one range request each, keeping the rows whose bounding
   box meets the area: from the file's box columns, or from each geometry's
   own bounds when it has none;
4. one GeoParquet file of the rows kept, whose ``geo`` metadata is the file's
   own with the box of the rows kept.

The area is a box in longitude and latitude. A file in another coordinate
system is read with the box moved into it, and keeps its own.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

from utk_curio.backend.app.discovery.domain.errors import (
    DownloadTooLarge,
    ProviderError,
    UnsupportedFormatError,
)
from utk_curio.backend.app.discovery.infrastructure.remote_parquet import RemoteParquet

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Part:
    """What one file gives an area: the row groups to read, and the area in
    the file's own coordinates."""

    remote: RemoteParquet
    groups: tuple[int, ...]
    box: Box


def name_of(remote: RemoteParquet) -> str:
    """The file's name, the last segment of its address."""
    return unquote(posixpath.basename(urlsplit(remote.url).path)) or remote.url


def plan(remotes, area, *, bound: int, what: str) -> list[Part]:
    """The row groups of each of *remotes* that meet *area*, read from their
    footers. Refused before any row group is read when the footers and those
    row groups take more than *bound* bytes; *what* names the data in the
    refusal. Files with no row group in the area are left out."""
    parts = []
    planned = 0
    for remote in remotes:
        box = area_in(remote, area)
        groups = tuple(remote.row_groups_meeting(box))
        planned += sum(len(span) for span in remote.requests) + remote.planned_bytes(groups)
        parts.append(Part(remote=remote, groups=groups, box=box))
    if planned > bound:
        raise DownloadTooLarge(
            f"this area needs {_size(planned)} of {what}, more than one download reads "
            f"({_size(bound)}); draw a smaller area"
        )
    return [part for part in parts if part.groups]


def area_in(remote: RemoteParquet, area) -> Box:
    """*area*, a box in longitude and latitude, in the file's coordinates.

    A GeoParquet column with no ``crs`` is in longitude and latitude; one
    whose ``crs`` is null says nothing, and cannot be placed.
    """
    column = _geometry_column(remote)
    box = tuple(float(v) for v in area)
    if "crs" not in column:
        return box
    crs = column["crs"]
    if crs is None:
        raise UnsupportedFormatError(
            f"{name_of(remote)} does not say which coordinates its geometries use, "
            "so an area cannot be placed on it; download it without an Area"
        )
    from pyproj import CRS, Transformer

    try:
        target = CRS.from_json_dict(crs) if isinstance(crs, dict) else CRS.from_user_input(crs)
    except Exception as exc:  # noqa: BLE001 - pyproj's own words
        raise UnsupportedFormatError(
            f"{name_of(remote)} names a coordinate system Curio cannot read ({exc})"
        ) from exc
    lonlat = CRS("OGC:CRS84")
    if target.equals(lonlat, ignore_axis_order=True):
        return box
    moved = Transformer.from_crs(lonlat, target, always_xy=True).transform_bounds(*box, densify_pts=21)
    return tuple(float(v) for v in moved)


def write(
    parts: list[Part],
    path: Path,
    *,
    keep: Callable[[Any], Any] | None = None,
    stage: Callable[[str], None] | None = None,
) -> int:
    """The rows of *parts* whose box meets each part's area (and that *keep*
    keeps, when given), written to *path* as GeoParquet. Returns the rows
    kept; with none, *path* is not written."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    total_groups = sum(len(part.groups) for part in parts)
    # The rows are written here first: the box of the rows kept, which the
    # final file's metadata carries, is known only once they all are.
    staged = path.with_name(path.name + ".part")
    writer = None
    schema = None
    geo: dict[str, Any] = {}
    extent = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    rows = 0
    done = 0
    try:
        for part in parts:
            boxes = _row_boxes(part.remote)
            west, south, east, north = part.box
            for g in part.groups:
                done += 1
                if stage is not None:
                    stage(f"Downloading part {done:,} of {total_groups:,}…")
                table = part.remote.read_row_group(g)
                xmin, ymin, xmax, ymax = boxes(table)
                kept = (xmin <= east) & (xmax >= west) & (ymin <= north) & (ymax >= south)
                if keep is not None:
                    kept &= _mask(keep(table))
                if not kept.any():
                    continue
                table = table.filter(pa.array(kept))
                extent = [
                    min(extent[0], float(np.min(xmin[kept]))), min(extent[1], float(np.min(ymin[kept]))),
                    max(extent[2], float(np.max(xmax[kept]))), max(extent[3], float(np.max(ymax[kept]))),
                ]
                if writer is None:
                    geo = part.remote.geo()
                    schema = table.schema.remove_metadata()
                    writer = pq.ParquetWriter(staged, schema)
                try:
                    table = table.replace_schema_metadata(None).cast(schema)
                except (ValueError, TypeError) as exc:
                    raise ProviderError("the files read for this area disagree on their columns") from exc
                writer.write_table(table)
                rows += table.num_rows
        if writer is not None:
            writer.close()
            writer = None
            with_geo(staged, path, geo, extent)
    finally:
        if writer is not None:
            writer.close()
        staged.unlink(missing_ok=True)
    return rows


def combined_geo(paths: list[Path], *, what: str) -> tuple[dict[str, Any], list[float]]:
    """The ``geo`` metadata for one table of the GeoParquet files *paths*
    (each written by :func:`write`), and the box of all their rows.

    Files in different coordinate systems, or with different geometry
    columns, are refused. The combined table names no box columns: a file
    without them leaves them empty in its rows.
    """
    import pyarrow.parquet as pq

    geo: dict[str, Any] | None = None
    extent = [float("inf"), float("inf"), float("-inf"), float("-inf")]
    for path in paths:
        own = json.loads(pq.read_metadata(path).metadata[b"geo"])
        column = own["columns"][own["primary_column"]]
        if geo is None:
            geo = own
        else:
            first = geo["columns"][geo["primary_column"]]
            if own["primary_column"] != geo["primary_column"] or column.get("crs") != first.get("crs"):
                raise UnsupportedFormatError(
                    f"{what}: its files differ in their geometry column or coordinate system; "
                    "declare the resource with datasets: per-file"
                )
        box = column["bbox"]
        extent = [min(extent[0], box[0]), min(extent[1], box[1]), max(extent[2], box[2]), max(extent[3], box[3])]
    if geo is None:
        raise UnsupportedFormatError(f"{what}: no file to combine")
    geo["columns"][geo["primary_column"]].pop("covering", None)
    return geo, extent


def _geometry_column(remote: RemoteParquet) -> dict[str, Any]:
    """The ``geo`` metadata of the file's primary geometry column."""
    geo = remote.geo()
    column = (geo.get("columns") or {}).get(geo.get("primary_column") or "")
    if not isinstance(column, dict):
        raise UnsupportedFormatError(
            f"{name_of(remote)} is not a GeoParquet file: it has no geometry to place an area on; "
            "download it without an Area"
        )
    return column


def _row_boxes(remote: RemoteParquet) -> Callable[[Any], tuple]:
    """How to read each row's box from a row group of *remote*: its box
    columns, or the bounds of its WKB geometries when it has none."""
    import numpy as np
    import pyarrow.compute as pc

    names = remote.covering()
    if names is not None:
        def from_columns(table):
            out = []
            for dotted in names:
                head, *fields = dotted.split(".")
                array = table.column(head).combine_chunks()
                for field in fields:
                    array = pc.struct_field(array, field)
                out.append(np.asarray(array.to_numpy(zero_copy_only=False), dtype="float64"))
            return tuple(out)

        return from_columns

    column = _geometry_column(remote)
    primary = remote.geo()["primary_column"]
    encoding = str(column.get("encoding") or "WKB")
    if encoding.upper() != "WKB":
        raise UnsupportedFormatError(
            f"{name_of(remote)} keeps its geometries as {encoding} and has no box column; "
            "Curio reads an area from a box column or from WKB geometries"
        )

    def from_geometries(table):
        import shapely

        geometries = shapely.from_wkb(table.column(primary).to_numpy(zero_copy_only=False))
        bounds = shapely.bounds(geometries)
        return bounds[:, 0], bounds[:, 1], bounds[:, 2], bounds[:, 3]

    return from_geometries


def _mask(values):
    """A keep answer as a numpy mask: null is not kept."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.compute as pc

    if isinstance(values, (pa.Array, pa.ChunkedArray)):
        values = pc.fill_null(values, False).to_numpy(zero_copy_only=False)
    return np.asarray(values, dtype=bool)


def with_geo(part: Path, path: Path, geo: dict[str, Any], extent: list[float]) -> None:
    """*part*'s rows, copied a row group at a time to *path* with GeoParquet
    ``geo`` metadata: the source file's, its geometry column's box made the
    box of the rows kept."""
    import pyarrow.parquet as pq

    geo = json.loads(json.dumps(geo)) if geo else {}
    primary = geo.get("primary_column") or "geometry"
    geo.setdefault("version", "1.1.0")
    geo["primary_column"] = primary
    column = geo.setdefault("columns", {}).setdefault(primary, {"encoding": "WKB", "geometry_types": []})
    column["bbox"] = [float(v) for v in extent]
    source = pq.ParquetFile(part)
    schema = source.schema_arrow.with_metadata({b"geo": json.dumps(geo).encode("utf-8")})
    with pq.ParquetWriter(path, schema) as writer:
        for g in range(source.num_row_groups):
            writer.write_table(source.read_row_group(g).replace_schema_metadata(schema.metadata))


def _size(n: int) -> str:
    if n < 1024 * 1024:
        return f"{n / 1024:,.0f} KB"
    if n < 10 * 1024 * 1024:
        return f"{n / 2**20:,.1f} MB"
    return f"{n / 2**20:,.0f} MB"


__all__ = ["Part", "plan", "write", "combined_geo", "with_geo", "area_in", "name_of"]
