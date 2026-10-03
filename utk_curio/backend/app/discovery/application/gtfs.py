"""A GTFS feed as Data Catalog layers.

Each table of the feed becomes one Parquet file, named after the table:

- ``stops`` is points, from ``stop_lon`` and ``stop_lat``, in EPSG:4326. A stop
  GTFS lets go without coordinates (a generic node, a boarding area) keeps its
  row, with no geometry;
- ``shapes`` is lines, one per ``shape_id``, through its points in
  ``shape_pt_sequence`` order. A shape of one point is not a line and is left
  out;
- every other table is a table.

Every column is read as text, so an id keeps its leading zeros (``0042``), and
only the coordinate and sequence columns are cast to numbers. DuckDB reads the
tables, as it does when a storage source's files are combined
(``combine_tables.py``): a big feed's ``stop_times.txt`` is hundreds of
megabytes, which a DataFrame would hold whole.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from utk_curio.backend.app.discovery.domain.errors import UnsupportedFormatError

#: Read as numbers; every other column is text.
COORDINATE_COLUMNS = ("stop_lat", "stop_lon", "shape_pt_lat", "shape_pt_lon")
SEQUENCE_COLUMNS = ("stop_sequence", "shape_pt_sequence")

#: The tables the GTFS reference defines. Another ``.txt`` beside them is a
#: table too when it reads as CSV, and is left out when it does not.
GTFS_TABLES = frozenset({
    "agency", "stops", "routes", "trips", "stop_times", "calendar", "calendar_dates",
    "fare_attributes", "fare_rules", "timeframes", "fare_media", "fare_products",
    "fare_leg_rules", "fare_leg_join_rules", "fare_transfer_rules", "areas",
    "stop_areas", "networks", "route_networks", "shapes", "frequencies", "transfers",
    "pathways", "levels", "location_groups", "location_group_stops", "booking_rules",
    "translations", "feed_info", "attributions",
})

_CSV_OPTIONS = (
    "header=true, all_varchar=true, delim=',', quote='\"', escape='\"', "
    "null_padding=true, strict_mode=false"
)


@dataclass(frozen=True)
class GtfsLayer:
    """One table of a feed, written as Parquet."""

    name: str
    path: Path
    rows: int
    #: Points or lines, rather than a plain table.
    geometry: bool


def convert(
    tables: dict[str, Path],
    work: Path,
    *,
    check: Callable[[], None] | None = None,
) -> list[GtfsLayer]:
    """Write each of *tables* (name to ``.txt``) as Parquet under *work*.

    Stops first, then shapes, then the rest by name.
    """
    import duckdb

    out = work / "layers"
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    layers: list[GtfsLayer] = []
    try:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET temp_directory=?", [str(work / "duckdb")])
        for name in sorted(tables, key=lambda t: (t != "stops", t != "shapes", t)):
            if check is not None:
                check()
            source = _as_utf8(tables[name], name)
            if source.stat().st_size == 0:
                continue
            try:
                columns = _columns(con, source)
            except duckdb.Error as exc:
                if name in GTFS_TABLES:
                    raise UnsupportedFormatError(
                        f"the GTFS feed's {name}.txt could not be read as CSV ({exc})"
                    ) from exc
                continue
            try:
                layer = None
                if name == "shapes":
                    layer = _shapes(con, source, columns, out)
                elif name == "stops":
                    layer = _stops(con, source, columns, out)
                if layer is None and name != "shapes":
                    layer = _table(con, name, source, columns, out)
            except duckdb.Error as exc:
                raise UnsupportedFormatError(
                    f"the GTFS feed's {name}.txt could not be converted ({exc})"
                ) from exc
            if layer is not None:
                layers.append(layer)
    finally:
        con.close()
    if not any(layer.name == "stops" for layer in layers):
        raise UnsupportedFormatError("the GTFS feed's stops.txt holds no table")
    return layers


def _as_utf8(path: Path, name: str) -> Path:
    """*path*, or a UTF-8 copy of it: text is stored as UTF-8 (#280)."""
    from utk_curio.backend.app.datasets.infrastructure.text_encoding import (
        TextDecodeError,
        _first_invalid_utf8,
        transcode_file_to_utf8,
    )

    if _first_invalid_utf8(path) is None:
        return path
    target = path.with_name(f"{path.stem}.utf8.txt")
    try:
        transcode_file_to_utf8(path, target, what=f"{name}.txt")
    except TextDecodeError as exc:
        raise UnsupportedFormatError(str(exc)) from exc
    return target


def _columns(con, source: Path) -> dict[str, str]:
    """The table's columns: their names cleaned of spaces, each to its name in
    the file. A second column of the same name is numbered."""
    described = con.execute(
        f"DESCRIBE SELECT * FROM read_csv(?, {_CSV_OPTIONS})", [str(source)]
    ).fetchall()
    columns: dict[str, str] = {}
    for row in described:
        raw = str(row[0])
        clean = raw.replace("﻿", "").strip() or "column"
        name, n = clean, 1
        while name in columns:
            n += 1
            name = f"{clean}_{n}"
        columns[name] = raw
    return columns


def _select(columns: dict[str, str]) -> str:
    """Each column as text, the coordinates and sequences as numbers."""
    parts = []
    for name, raw in columns.items():
        if name in COORDINATE_COLUMNS:
            parts.append(f"TRY_CAST(trim({_ident(raw)}) AS DOUBLE) AS {_ident(name)}")
        elif name in SEQUENCE_COLUMNS:
            parts.append(f"TRY_CAST(trim({_ident(raw)}) AS BIGINT) AS {_ident(name)}")
        else:
            parts.append(f"{_ident(raw)} AS {_ident(name)}")
    return ", ".join(parts)


def _table(con, name: str, source: Path, columns, out: Path) -> GtfsLayer:
    dest = out / f"{name}.parquet"
    con.execute(
        f"COPY (SELECT {_select(columns)} FROM read_csv(?, {_CSV_OPTIONS})) "
        f"TO {_literal(str(dest))} (FORMAT parquet)",
        [str(source)],
    )
    rows = con.execute("SELECT count(*) FROM read_parquet(?)", [str(dest)]).fetchone()[0]
    return GtfsLayer(name=name, path=dest, rows=int(rows), geometry=False)


def _stops(con, source: Path, columns, out: Path) -> GtfsLayer | None:
    """Stops as points. None when the table has no coordinates to make them."""
    if not {"stop_lat", "stop_lon"} <= set(columns):
        return None
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import shapely

    staged = out / "stops.table.parquet"
    con.execute(
        f"COPY (SELECT {_select(columns)} FROM read_csv(?, {_CSV_OPTIONS})) "
        f"TO {_literal(str(staged))} (FORMAT parquet)",
        [str(source)],
    )
    frame = pd.read_parquet(staged)
    staged.unlink(missing_ok=True)
    lon = frame["stop_lon"].to_numpy(dtype=float, na_value=np.nan)
    lat = frame["stop_lat"].to_numpy(dtype=float, na_value=np.nan)
    placed = np.isfinite(lon) & np.isfinite(lat)
    geometry = np.full(len(frame), None, dtype=object)
    if placed.any():
        geometry[placed] = shapely.points(lon[placed], lat[placed])
    stops = gpd.GeoDataFrame(frame, geometry=gpd.GeoSeries(geometry, crs="EPSG:4326"))
    dest = out / "stops.parquet"
    stops.to_parquet(dest)
    return GtfsLayer(name="stops", path=dest, rows=len(stops), geometry=True)


def _shapes(con, source: Path, columns, out: Path) -> GtfsLayer | None:
    """Shapes as lines, or None when no shape has two points. A ``shapes.txt``
    without the columns that make lines is a table."""
    needed = {"shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"}
    if not needed <= set(columns):
        return _table(con, "shapes", source, columns, out)
    import geopandas as gpd
    import numpy as np
    import shapely

    con.execute(
        "CREATE OR REPLACE TEMP TABLE _shape_points AS SELECT "
        f"{_ident(columns['shape_id'])} AS shape_id, "
        f"TRY_CAST(trim({_ident(columns['shape_pt_lon'])}) AS DOUBLE) AS x, "
        f"TRY_CAST(trim({_ident(columns['shape_pt_lat'])}) AS DOUBLE) AS y, "
        f"TRY_CAST(trim({_ident(columns['shape_pt_sequence'])}) AS BIGINT) AS seq "
        f"FROM read_csv(?, {_CSV_OPTIONS})",
        [str(source)],
    )
    try:
        con.execute(
            "DELETE FROM _shape_points WHERE shape_id IS NULL OR x IS NULL OR y IS NULL "
            "OR isnan(x) OR isnan(y)"
        )
        ids = [row[0] for row in con.execute(
            "SELECT shape_id FROM _shape_points GROUP BY shape_id ORDER BY shape_id"
        ).fetchall()]
        points = con.execute(
            "SELECT dense_rank() OVER (ORDER BY shape_id) - 1 AS g, x, y "
            "FROM _shape_points ORDER BY shape_id, seq NULLS LAST"
        ).fetchnumpy()
    finally:
        con.execute("DROP TABLE IF EXISTS _shape_points")
    group = np.asarray(points["g"], dtype=np.int64)
    if not ids or group.size == 0:
        return None
    counts = np.bincount(group, minlength=len(ids))
    lines_kept = counts >= 2
    if not lines_kept.any():
        return None
    rows = lines_kept[group]
    coords = np.column_stack([
        np.asarray(points["x"], dtype=float)[rows],
        np.asarray(points["y"], dtype=float)[rows],
    ])
    renumbered = (np.cumsum(lines_kept) - 1)[group[rows]]
    lines = shapely.linestrings(coords, indices=renumbered)
    shapes = gpd.GeoDataFrame(
        {
            "shape_id": [ids[i] for i in np.flatnonzero(lines_kept)],
            "point_count": counts[lines_kept].astype("int64"),
        },
        geometry=gpd.GeoSeries(lines, crs="EPSG:4326"),
    )
    dest = out / "shapes.parquet"
    shapes.to_parquet(dest)
    return GtfsLayer(name="shapes", path=dest, rows=len(shapes), geometry=True)


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
