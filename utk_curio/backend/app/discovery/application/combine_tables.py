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

from utk_curio.backend.app.discovery.domain.errors import (
    CapabilityUnsupported,
    DiscoveryError,
    DownloadTooLarge,
)
from utk_curio.backend.app.discovery.domain.manifest import ResourceSpec

MAX_COMBINED_FILES = 10_000
MAX_COMBINED_LOCAL_BYTES = 16 * 1024 * 1024 * 1024
MAX_COMBINED_REMOTE_BYTES = 2 * 1024 * 1024 * 1024

#: A column Curio adds whose name a file already uses (a capture, or
#: ``source_file``) keeps its value under this suffix, so neither is lost.
COLLISION_SUFFIX = "_from_path"

DUCKDB_READERS = {"csv": "read_csv", "json": "read_json", "parquet": "read_parquet"}

#: Columns that exist only while the files are combined.
FILE_COLUMN = "__curio_file"
ROW_COLUMN = "__curio_row"


class CombineError(DiscoveryError):
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
            from utk_curio.backend.app.discovery.application.storage_acquire import Cancelled

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


def _derived_names(spec: ResourceSpec, data_columns) -> tuple[dict[str, str], str]:
    """The columns a combined table adds, clear of the files' own.

    Returns capture name -> its column, and the column that names each row's
    file. Names are compared without case, as DuckDB and most readers of the
    result compare them.
    """
    taken = {str(c).lower() for c in data_columns}

    def claim(name: str) -> str:
        column = name
        while column.lower() in taken:
            column += COLLISION_SUFFIX
        taken.add(column.lower())
        return column

    captures = {capture.name: claim(capture.name) for capture in spec.template.captures}
    return captures, claim("source_file")


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
        options = f"union_by_name=true, filename={_sql_literal(FILE_COLUMN)}"
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
        data_columns = [row[0] for row in described if row[0] != FILE_COLUMN]
        clash = next((c for c in data_columns if c.lower() in (FILE_COLUMN, ROW_COLUMN)), None)
        if clash is not None:
            raise CombineError(f"{spec.name}: a file has a column {clash!r}, which combining uses")
        columns, source_column = _derived_names(spec, data_columns)

        # The files table's own columns are positional, so no name a file or a
        # capture uses can meet them; the output names are the aliases.
        con.execute(
            "CREATE TABLE _files (p VARCHAR, s VARCHAR"
            + "".join(f", c{i} {_sql_type(c.type)}" for i, c in enumerate(spec.template.captures))
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
        captured = "".join(
            f", f.c{i} AS {_ident(columns[c.name])}" for i, c in enumerate(spec.template.captures)
        )
        # The scan keeps each file's rows in order, and the sort does not: it
        # is only by file. So the rows are numbered as they are read, and
        # sorted by file and then by that number.
        # COPY takes its target as a literal; it is our own temp path.
        con.execute(
            f"COPY (SELECT t.* EXCLUDE ({FILE_COLUMN}, {ROW_COLUMN}){captured}, "
            f"f.s AS {_ident(source_column)} "
            f"FROM (SELECT *, row_number() OVER () AS {ROW_COLUMN} FROM {source}) t "
            f"JOIN _files f ON t.{FILE_COLUMN} = f.p "
            f"ORDER BY f.s, t.{ROW_COLUMN}) TO {_sql_literal(str(dest))} (FORMAT parquet)",
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
        columns, source_column = _derived_names(spec, frame.columns)
        for capture in spec.template.captures:
            frame[columns[capture.name]] = found.values[capture.name]
        frame[source_column] = found.relpath
        frames.append(frame)
    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=crs)
    if combined.crs is not None and combined.crs.to_epsg() != 4326:
        combined = combined.to_crs(4326)
    combined.to_parquet(dest)
    return Combined(path=dest, rows=len(combined), columns=tuple(combined.columns))


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value
    return value
