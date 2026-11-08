"""Read a JSON Lines file into Parquet parts, as its resource's options say.

The file is read a line at a time, and its rows are written as Parquet parts
of at most ``ROWS_PER_PART`` rows, or the rows of ``BYTES_PER_PART`` bytes of
lines, so a file of any size takes the memory of one part. A column with a
``type`` is written as that type in every part. Any other column takes its type
from the part's own values; one whose values in a part are not of one kind
(numbers and text, true and a number, a whole number past 64 bits) holds them
as text there. The parts of every file are then combined as any table's files
are (``combine_tables``), where DuckDB gives each column one type across them.

What each line gives is ``domain/json_rows.py``'s. A line that gives no rows
for a reason is skipped and counted by that reason, with the first line it
happened on (:class:`Skipped`), and the add says so in its message and in the
dataset's description, as it says how many values a column's type could not
read, left empty, by column and reason. A blank line is not counted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.discovery.domain import json_rows

#: Rows held before a part is written.
ROWS_PER_PART = 100_000

#: Bytes of lines read before a part is written, whatever its row count.
BYTES_PER_PART = 64 * 1024 * 1024

#: A longer line is skipped, so a file with no line breaks cannot fill memory.
MAX_LINE_BYTES = 16 * 1024 * 1024

#: Lines read between two looks at whether the add was cancelled.
LINES_PER_CHECK = 10_000


@dataclass
class Skipped:
    """The lines an add read and the rows they gave, across its files, and
    the lines it skipped, by why."""

    lines: int = 0
    rows: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    #: For each reason, where it first happened: ``line 220 of a/b.jsonl``.
    first: dict[str, str] = field(default_factory=dict)
    #: Values a column's type could not read, left empty, by column and why.
    empties: dict[tuple[str, str], int] = field(default_factory=dict)
    first_empty: dict[tuple[str, str], str] = field(default_factory=dict)

    def skip(self, reason: str, number: int, relpath: str) -> None:
        if reason not in self.counts:
            self.counts[reason] = 0
            self.first[reason] = f"line {number:,} of {relpath}"
        self.counts[reason] += 1

    def empty(self, column: str, reason: str, number: int, relpath: str) -> None:
        key = (column, reason)
        if key not in self.empties:
            self.empties[key] = 0
            self.first_empty[key] = f"line {number:,} of {relpath}"
        self.empties[key] += 1

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def note(self) -> str | None:
        """What the add says of the lines it skipped and the values it left
        empty, or None when it did neither."""
        said = []
        if self.total:
            reasons = "; ".join(
                f"{count:,} {reason} (first at {self.first[reason]})"
                for reason, count in sorted(self.counts.items(), key=lambda item: -item[1])
            )
            said.append(f"{self.total:,} of {self.lines:,} lines skipped: {reasons}")
        emptied = sum(self.empties.values())
        if emptied:
            reasons = "; ".join(
                f"{count:,} of {column} {reason} (first at {self.first_empty[(column, reason)]})"
                for (column, reason), count in sorted(self.empties.items(), key=lambda item: -item[1])
            )
            said.append(f"{emptied:,} {'value' if emptied == 1 else 'values'} left empty: {reasons}")
        return ". ".join(said) or None


@dataclass
class Reading:
    """How one add reads its JSON Lines files, and what they skipped."""

    rows: json_rows.LineRows
    skipped: Skipped = field(default_factory=Skipped)

    @classmethod
    def of(cls, spec) -> "Reading":
        """The reading a jsonl table resource *spec*'s options declare."""
        return cls(rows=json_rows.read_options(spec.options))

    def read(self, path: Path, relpath: str, into: Path, prefix: str, *, stage=None, cancelled=None) -> list[Path]:
        return read(path, relpath, self.rows, into, prefix, self.skipped, stage=stage, cancelled=cancelled)


def read(
    path: Path,
    relpath: str,
    rows: json_rows.LineRows,
    into: Path,
    prefix: str,
    skipped: Skipped,
    *,
    stage: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[Path]:
    """Write the rows of the JSON Lines file at *path* as Parquet parts in
    *into*, named ``<prefix>-00001.parquet`` on, in line order. Returns them;
    none when no line gave a row. *relpath* is how a skipped line names it."""
    names = rows.names
    types = rows.types
    parts: list[Path] = []
    pending: list[Any] = []
    pending_bytes = 0
    number = 0

    def empty(column: str, reason: str) -> None:
        skipped.empty(column, reason, number, relpath)

    def flush() -> None:
        nonlocal pending, pending_bytes
        if pending:
            part = into / f"{prefix}-{len(parts) + 1:05d}.parquet"
            _write_part(pending, names, types, part)
            parts.append(part)
            if stage is not None:
                stage(f"Reading {relpath}: {skipped.rows:,} rows")
        pending = []
        pending_bytes = 0

    with path.open("rb") as handle:
        while True:
            line = handle.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            number += 1
            if number % LINES_PER_CHECK == 0 and cancelled is not None and cancelled():
                from utk_curio.backend.app.discovery.application.storage_acquire import Cancelled

                raise Cancelled()
            if len(line) > MAX_LINE_BYTES:
                # Over the bound with no line break: the rest of it is dropped.
                while line and not line.endswith(b"\n"):
                    line = handle.readline(MAX_LINE_BYTES + 1)
                skipped.lines += 1
                skipped.skip(f"longer than {_size(MAX_LINE_BYTES)}", number, relpath)
                continue
            if not line.strip():
                continue
            skipped.lines += 1
            try:
                got = json_rows.rows_of(json_rows.read_line(line), rows, empty)
            except json_rows.LineSkipped as exc:
                skipped.skip(exc.reason, number, relpath)
                continue
            pending.extend(got)
            skipped.rows += len(got)
            pending_bytes += len(line)
            if len(pending) >= ROWS_PER_PART or pending_bytes >= BYTES_PER_PART:
                flush()
    flush()
    return parts


def _size(count: int) -> str:
    mib = 1024 * 1024
    return f"{count // mib} MiB" if count % mib == 0 else f"{count:,} bytes"


def _write_part(
    pending: list[Any], names: tuple[str, ...] | None, types: tuple[str | None, ...] | None, part: Path,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    if names is None or types is None:
        # Every line's own fields: the columns are each name a line used, in
        # the order they first came, and a line without one has null there.
        order: dict[str, None] = {}
        for row in pending:
            for name in row:
                order.setdefault(name, None)
        arrays = {name: _array([row.get(name) for row in pending]) for name in order}
    else:
        arrays = {
            name: _array(list(values)) if kind is None else pa.array(list(values), type=_arrow_type(kind))
            for name, kind, values in zip(names, types, zip(*pending))
        }
    pq.write_table(pa.table(arrays), part)


def _arrow_type(kind: str):
    """The Arrow type a typed column is written as. A ``timestamp`` is UTC
    nanoseconds with no zone attached, which the combine keeps to the
    nanosecond on every DuckDB; one with a zone it holds to the microsecond
    before DuckDB 2."""
    import pyarrow as pa

    return {
        "timestamp": pa.timestamp("ns"), "int": pa.int64(), "float": pa.float64(),
        "string": pa.string(), "bool": pa.bool_(),
    }[kind]


def _array(values: list[Any]):
    """One part's values of one column, as Arrow types them; as text when
    they are not all of one kind."""
    import pyarrow as pa

    try:
        array = pa.array(values)
    except (pa.ArrowInvalid, pa.ArrowTypeError, OverflowError):
        return _as_text(values)
    # Arrow reads [1.5, false] as [1.5, 0.0]: true and false are not numbers.
    if pa.types.is_floating(array.type) and any(value is True or value is False for value in values):
        return _as_text(values)
    return array


def _as_text(values: list[Any]):
    import pyarrow as pa

    return pa.array(
        [value if value is None or isinstance(value, str) else json.dumps(value) for value in values],
        type=pa.string(),
    )
