"""Combine a table resource's files into one Parquet table.

A folder of daily readings split by sensor is one table the user means, so a
``table`` resource whose template matches many files becomes a single
dataset. Columns are matched by name across the files, and a column a file
lacks is null in its rows. Each capture of the template becomes a column (a
``sensor`` from ``{sensor}``, a ``day`` from ``{day:date}``), and
``source_file`` says which file each row came from.

Text files are read as UTF-8, transcoded on the way when they are not, the
same rule every import follows (#280). DuckDB reads csv, json and parquet;
geopandas reads geojson and shapefiles, which combine into GeoParquet when
their CRS agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.datalakes.domain.errors import (
    CapabilityUnsupported,
    DataLakeError,
    DownloadTooLarge,
)
from utk_curio.backend.app.datalakes.domain.manifest import ResourceSpec
from utk_curio.backend.app.datalakes.providers.storage_base import SHAPEFILE_PARTS

MAX_COMBINED_FILES = 10_000
MAX_COMBINED_LOCAL_BYTES = 16 * 1024 * 1024 * 1024
MAX_COMBINED_REMOTE_BYTES = 2 * 1024 * 1024 * 1024

#: A capture whose name a file already uses as a column keeps its value
#: under this suffix, so neither is lost.
COLLISION_SUFFIX = "_from_path"

DUCKDB_READERS = {"csv": "read_csv", "json": "read_json", "parquet": "read_parquet"}


class CombineError(DataLakeError):
    """The files cannot be combined into one table."""


@dataclass(frozen=True)
class Combined:
    path: Path
    rows: int
    columns: tuple[str, ...]


def check_bounds(files, *, local: bool) -> None:
    if len(files) > MAX_COMBINED_FILES:
        raise DownloadTooLarge(
            f"{len(files):,} files is more than one table combines ({MAX_COMBINED_FILES:,}); "
            "split the resource with datasets: per:<field>"
        )
    bound = MAX_COMBINED_LOCAL_BYTES if local else MAX_COMBINED_REMOTE_BYTES
    total = sum(f.size for f in files)
    if total > bound:
        raise DownloadTooLarge(
            f"these files total {total:,} bytes; one combined table is limited to {bound:,}"
        )


def combine(
    spec: ResourceSpec,
    files,
    *,
    stage: Callable[[Any, Path, int], Path],
    tmp: Path,
    dest: Path,
    items: Callable[[int, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Combined:
    """Write *files* of *spec* as one table at *dest*.

    ``stage(found, into_dir, index)`` returns a local path to read one file
    from: the file itself for a folder whose bytes are already UTF-8, or a
    staged copy.
    """
    fmt = spec.format
    staged: list[tuple[Path, Any]] = []
    for index, found in enumerate(files, start=1):
        if cancelled is not None and cancelled():
            from utk_curio.backend.app.datalakes.application.storage_acquire import Cancelled

            raise Cancelled()
        staged.append((stage(found, tmp, index), found))
        if items is not None:
            items(index, len(files))
    if fmt in DUCKDB_READERS:
        return _combine_with_duckdb(spec, staged, tmp=tmp, dest=dest)
    if fmt in ("geojson", "shp"):
        return _combine_geo(spec, staged, dest=dest)
    raise CapabilityUnsupported(
        f"{spec.name}: {fmt} files hold layers of their own and are added one at a time; "
        "declare the resource with datasets: per-file"
    )


def _capture_columns(spec: ResourceSpec, data_columns: set[str]) -> dict[str, str]:
    """Capture name -> the column it becomes, clear of the files' own columns."""
    out = {}
    for capture in spec.template.captures:
        name = capture.name
        out[name] = name + COLLISION_SUFFIX if name in data_columns else name
    return out


def _sql_type(capture_type: str) -> str:
    return {"int": "BIGINT", "date": "DATE", "datetime": "TIMESTAMP"}.get(capture_type, "VARCHAR")


def _combine_with_duckdb(spec: ResourceSpec, staged, *, tmp: Path, dest: Path) -> Combined:
    import duckdb

    reader = DUCKDB_READERS[spec.format]
    paths = [str(path) for path, _found in staged]
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='1GB'")
        con.execute("SET temp_directory=?", [str(tmp / "duckdb")])
        options = "union_by_name=true, filename=true"
        if spec.format == "csv":
            delimiter = spec.options.get("delimiter")
            header = spec.options.get("header", True)
            options += f", header={'true' if header else 'false'}"
            if isinstance(delimiter, str) and len(delimiter) == 1:
                options += ", delim=" + _sql_literal(delimiter)
        source = f"{reader}(?, {options})"
        try:
            described = con.execute(f"DESCRIBE SELECT * FROM {source}", [paths]).fetchall()
        except duckdb.Error as exc:
            raise CombineError(f"{spec.name}: the files could not be read as {spec.format} ({exc})") from exc
        data_columns = {row[0] for row in described} - {"filename"}
        columns = _capture_columns(spec, data_columns)

        con.execute(
            "CREATE TABLE _files (_path VARCHAR, source_file VARCHAR"
            + "".join(
                f", {_ident(columns[c.name])} {_sql_type(c.type)}" for c in spec.template.captures
            )
            + ")"
        )
        rows = []
        for path, found in staged:
            rows.append(
                [str(path), found.relpath]
                + [_sql_value(found.values[c.name]) for c in spec.template.captures]
            )
        if rows:
            placeholders = ", ".join("?" for _ in rows[0])
            con.executemany(f"INSERT INTO _files VALUES ({placeholders})", rows)
        captured = "".join(f", f.{_ident(columns[c.name])}" for c in spec.template.captures)
        # The scan keeps each file's rows in order, and the sort does not: it
        # is only by file. So the rows are numbered as they are read, and
        # sorted by file and then by that number.
        # COPY takes its target as a literal; it is our own temp path.
        con.execute(
            f"COPY (SELECT t.* EXCLUDE (filename, _curio_row){captured}, f.source_file "
            f"FROM (SELECT *, row_number() OVER () AS _curio_row FROM {source}) t "
            f"JOIN _files f ON t.filename = f._path "
            f"ORDER BY f.source_file, t._curio_row) TO {_sql_literal(str(dest))} (FORMAT parquet)",
            [paths],
        )
        count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(dest)]).fetchone()[0]
        names = tuple(r[0] for r in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(dest)]).fetchall())
    except duckdb.Error as exc:
        raise CombineError(f"{spec.name}: the files could not be combined ({exc})") from exc
    finally:
        con.close()
    return Combined(path=dest, rows=int(count), columns=names)


def _combine_geo(spec: ResourceSpec, staged, *, dest: Path) -> Combined:
    import geopandas as gpd
    import pandas as pd

    frames = []
    crs = None
    for path, found in staged:
        frame = gpd.read_file(path, engine="pyogrio")
        if crs is None:
            crs = frame.crs
        elif frame.crs is not None and crs is not None and frame.crs != crs:
            raise CombineError(
                f"{spec.name}: {found.relpath} is in {frame.crs.to_string()}, "
                f"the others in {crs.to_string()}; declare the resource with datasets: per-file"
            )
        columns = _capture_columns(spec, set(frame.columns))
        for capture in spec.template.captures:
            frame[columns[capture.name]] = found.values[capture.name]
        frame["source_file"] = found.relpath
        frames.append(frame)
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=crs)
    if combined.crs is not None and combined.crs.to_epsg() != 4326:
        combined = combined.to_crs(4326)
    combined.to_parquet(dest)
    return Combined(path=dest, rows=len(combined), columns=tuple(combined.columns))


def shapefile_parts(relpath: str) -> list[str]:
    stem = relpath[: -len(".shp")] if relpath.lower().endswith(".shp") else relpath
    return [stem + suffix for suffix in SHAPEFILE_PARTS]


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value
    return value
