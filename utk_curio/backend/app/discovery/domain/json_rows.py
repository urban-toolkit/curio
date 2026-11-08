"""How the lines of a JSON Lines table become rows (``"format": "jsonl"``).

A JSON Lines file holds one JSON object per line. A ``table`` resource of
format ``jsonl`` reads each line as one row, its fields as the row's columns,
unless the resource's ``options`` say otherwise:

- ``parse``: fields of the line that hold JSON as text, such as
  ``"value": "{\\"a\\": 1}"``, read as the JSON they hold before anything else;
- ``columns``: the columns the line keeps, each a name and the path to its
  value, or ``{"path": ..., "type": ...}`` to give the column a type
  (:data:`COLUMN_TYPES`);
- ``unpack``: nested lists or objects whose items are the rows, outermost
  first. Each level names its ``path`` from the level above (from the line,
  for the first), a ``key`` column for each item's name in an object or its
  position in a list, and the ``columns`` it keeps of each item.

A path names keys from where it starts, joined by dots. A number picks an item
of a list (``bbox.0``). A key may itself hold dots (``meta.site``): the longest
key that is there is taken first. The empty path is the item itself.

With ``unpack``, a row holds only the columns the line and the levels name.
Without it, ``columns`` names the line's columns, and with neither, every
field of the line is a column. A value that is an object or a list lands as
its JSON text, and ``NaN``, ``Infinity`` and ``-Infinity``, which JSON does
not have but some writers write, read as null.

A line that is not a JSON object, a ``parse`` field whose text is not JSON,
and a line where an ``unpack`` path holds no list or object (in any item it
reaches) give no rows: :class:`LineSkipped` says why. A list or object that
is there and empty gives no rows and is not skipped.

A typed column's value is converted as its type says. A ``timestamp`` reads
ISO 8601 text with its offset and is held as nanoseconds since 1970 in UTC.
A value its type cannot read is left empty, and the caller is told the
column and why (:func:`rows_of`'s ``empty``); a missing or null value is
null, as in any column.
"""

from __future__ import annotations

import calendar
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

#: What a jsonl table's ``options`` may hold, what each ``unpack`` level may,
#: and what a column given as an object may.
OPTION_KEYS = ("parse", "columns", "unpack")
LEVEL_KEYS = ("path", "key", "columns")
COLUMN_KEYS = ("path", "type")

#: The types a column may take.
COLUMN_TYPES = ("timestamp", "int", "float", "string", "bool")

#: Bounds on what one resource declares.
MAX_PARSE = 16
MAX_LEVELS = 8
MAX_COLUMNS = 256
MAX_PATH_CHARS = 256
MAX_NAME_CHARS = 128

#: Columns a combined table uses while it is made (``combine_tables``) start so.
RESERVED_PREFIX = "__curio_"

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

_MISSING = object()


class OptionError(ValueError):
    """A jsonl table's ``options`` that cannot be read."""


class LineSkipped(Exception):
    """A line that gives no rows, and why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class JsonPath:
    """A path into a JSON value, compiled for the lookups :func:`resolve` makes."""

    text: str
    #: For each name, the keys to try there, longest first, and the name each
    #: one leads on to: ``meta.site`` tries ``"meta.site"``, then ``"meta"``.
    keys: tuple[tuple[tuple[str, int], ...], ...]
    #: For each name, the list position it picks, or None for a name that
    #: picks none.
    positions: tuple[int | None, ...]


@dataclass(frozen=True)
class Column:
    name: str
    path: JsonPath
    #: One of :data:`COLUMN_TYPES`, or None for a column typed by its values.
    type: str | None = None


@dataclass(frozen=True)
class Level:
    path: JsonPath
    key: str | None
    columns: tuple[Column, ...]
    #: How a skipped line names it: ``items under value.results``.
    where: str


@dataclass(frozen=True)
class LineRows:
    """What a jsonl table's ``options`` say each line gives."""

    parse: tuple[JsonPath, ...] = ()
    #: The line's own columns; None keeps every field, when nothing is unpacked.
    columns: tuple[Column, ...] | None = None
    levels: tuple[Level, ...] = ()

    @property
    def names(self) -> tuple[str, ...] | None:
        """Each row's columns in order, or None when they are the lines' fields."""
        if self.columns is None and not self.levels:
            return None
        names = [column.name for column in self.columns or ()]
        for level in self.levels:
            if level.key is not None:
                names.append(level.key)
            names.extend(column.name for column in level.columns)
        return tuple(names)

    @property
    def types(self) -> tuple[str | None, ...] | None:
        """Each column's type in :attr:`names` order (None for one typed by
        its values, a level's key among them), or None with :attr:`names`."""
        if self.columns is None and not self.levels:
            return None
        types = [column.type for column in self.columns or ()]
        for level in self.levels:
            if level.key is not None:
                types.append(None)
            types.extend(column.type for column in level.columns)
        return tuple(types)


# ── reading the options ────────────────────────────────────────────────────


def check_options(fmt: str | None, options: dict[str, Any]) -> None:
    """Refuse a table's *options* that its format *fmt* does not read."""
    if fmt == "jsonl":
        read_options(options)
        return
    named = [key for key in OPTION_KEYS if key in options]
    if named:
        raise OptionError(
            f"{f'a {fmt} table' if fmt else 'a collection'} reads no {', '.join(named)}: "
            "parse, columns and unpack are options of a jsonl table"
        )


def read_options(options: dict[str, Any]) -> LineRows:
    """The rows a jsonl table's *options* say each line gives."""
    unknown = sorted(set(options) - set(OPTION_KEYS))
    if unknown:
        raise OptionError(
            f"a jsonl table reads no {', '.join(unknown)}; its options are parse, columns and unpack"
        )
    parse = _parse_list(options.get("parse"))
    columns = _columns(options["columns"], "columns") if "columns" in options else None
    levels = _levels(options.get("unpack"))
    rows = LineRows(parse=parse, columns=columns, levels=levels)
    names = rows.names
    if names is not None:
        if not names:
            raise OptionError("unpack names no column: name the columns a row keeps")
        if len(names) > MAX_COLUMNS:
            raise OptionError(f"a row keeps at most {MAX_COLUMNS} columns")
        seen: set[str] = set()
        for name in names:
            if name.casefold() in seen:
                raise OptionError(f"the column {name!r} is named twice")
            seen.add(name.casefold())
    return rows


def _parse_list(raw: object) -> tuple[JsonPath, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw or len(raw) > MAX_PARSE:
        raise OptionError(f"parse must list 1 to {MAX_PARSE} fields")
    return tuple(compile_path(item, "parse", empty=False) for item in raw)


def _columns(raw: object, where: str) -> tuple[Column, ...]:
    if not isinstance(raw, dict) or not raw:
        raise OptionError(f"{where} must name at least one column, as an object of names and paths")
    return tuple(_column(_column_name(name, where), spec, f"{where}.{name}") for name, spec in raw.items())


def _column(name: str, spec: object, where: str) -> Column:
    """A column given as a path, or as ``{"path": ..., "type": ...}``."""
    if not isinstance(spec, dict):
        return Column(name=name, path=compile_path(spec, where, empty=True))
    unknown = sorted(set(spec) - set(COLUMN_KEYS))
    if unknown:
        raise OptionError(f"{where} reads no {', '.join(unknown)}; a column takes path and type")
    if "path" not in spec:
        raise OptionError(f"{where} needs a path")
    kind = spec.get("type")
    if kind is not None and kind not in COLUMN_TYPES:
        raise OptionError(f"{where}.type must be one of {', '.join(COLUMN_TYPES)}")
    return Column(name=name, path=compile_path(spec["path"], f"{where}.path", empty=True), type=kind)


def _levels(raw: object) -> tuple[Level, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw or len(raw) > MAX_LEVELS:
        raise OptionError(f"unpack must list 1 to {MAX_LEVELS} levels")
    levels: list[Level] = []
    for index, item in enumerate(raw):
        where = f"unpack[{index}]"
        if not isinstance(item, dict):
            raise OptionError(f"{where} must be an object with a path")
        unknown = sorted(set(item) - set(LEVEL_KEYS))
        if unknown:
            raise OptionError(f"{where} reads no {', '.join(unknown)}; a level takes path, key and columns")
        if "path" not in item:
            raise OptionError(f"{where} needs a path")
        path = compile_path(item["path"], f"{where}.path", empty=True)
        key = item.get("key")
        if key is not None:
            key = _column_name(key, f"{where}.key")
        columns = _columns(item["columns"], f"{where}.columns") if "columns" in item else ()
        here = path.text or "the item"
        levels.append(Level(
            path=path, key=key, columns=columns,
            where=f"{here} under {levels[-1].where}" if levels else here,
        ))
    return tuple(levels)


def _column_name(raw: object, where: str) -> str:
    if not isinstance(raw, str) or not raw or len(raw) > MAX_NAME_CHARS or _CONTROL_RE.search(raw):
        raise OptionError(f"{where}: a column name is 1 to {MAX_NAME_CHARS} characters, with no control characters")
    if raw.casefold().startswith(RESERVED_PREFIX):
        raise OptionError(f"{where}: a column name may not start with {RESERVED_PREFIX}")
    return raw


def compile_path(raw: object, where: str, *, empty: bool) -> JsonPath:
    """*raw* as a path. *empty* allows the empty path, the item itself."""
    if not isinstance(raw, str) or len(raw) > MAX_PATH_CHARS or _CONTROL_RE.search(raw):
        raise OptionError(f"{where} must be a path of at most {MAX_PATH_CHARS} characters")
    if raw == "":
        if not empty:
            raise OptionError(f"{where} must name a field")
        return JsonPath(text="", keys=(), positions=())
    names = raw.split(".")
    if any(name == "" for name in names):
        raise OptionError(f"{where}: {raw!r} has an empty name between dots")
    count = len(names)
    keys = tuple(
        tuple((".".join(names[start:end]), end) for end in range(count, start, -1))
        for start in range(count)
    )
    positions = tuple(int(name) if name.isascii() and name.isdigit() else None for name in names)
    return JsonPath(text=raw, keys=keys, positions=positions)


# ── reading a line ─────────────────────────────────────────────────────────


def _no_number(_constant: str) -> None:
    """``NaN``, ``Infinity`` or ``-Infinity``, which read as null."""
    return None


def read_line(raw: bytes | str) -> dict[str, Any]:
    """One line's JSON object, ``NaN`` read as null."""
    try:
        record = json.loads(raw, parse_constant=_no_number)
    except UnicodeDecodeError as exc:
        raise LineSkipped("not UTF-8 text") from exc
    except (ValueError, RecursionError) as exc:
        raise LineSkipped("not JSON") from exc
    if not isinstance(record, dict):
        raise LineSkipped("not a JSON object")
    return record


def resolve(value: Any, path: JsonPath) -> Any:
    """What *path* names in *value*; ``_MISSING`` when nothing is there."""
    index = 0
    count = len(path.keys)
    while index < count:
        if isinstance(value, dict):
            for key, following in path.keys[index]:
                if key in value:
                    value = value[key]
                    index = following
                    break
            else:
                return _MISSING
        elif isinstance(value, list):
            position = path.positions[index]
            if position is None or position >= len(value):
                return _MISSING
            value = value[position]
            index += 1
        else:
            return _MISSING
    return value


def _holder(value: Any, path: JsonPath) -> tuple[Any, Any] | None:
    """The object or list holding what *path* names, and its key there."""
    holder: Any = None
    at: Any = None
    index = 0
    count = len(path.keys)
    while index < count:
        if isinstance(value, dict):
            for key, following in path.keys[index]:
                if key in value:
                    holder, at = value, key
                    value = value[key]
                    index = following
                    break
            else:
                return None
        elif isinstance(value, list):
            position = path.positions[index]
            if position is None or position >= len(value):
                return None
            holder, at = value, position
            value = value[position]
            index += 1
        else:
            return None
    return (holder, at) if holder is not None else None


def cell(value: Any) -> Any:
    """A value as a table holds it: an object or a list as its JSON text."""
    if value is _MISSING:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


# ── a column's type ────────────────────────────────────────────────────────


class _Unread(Exception):
    """A value a column's type cannot read, and why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


#: ISO 8601 with its offset: ``2025-07-17T03:00:16.492384585+00:00``, with a
#: space allowed for the ``T``, a fraction of 1 to 9 digits, and an offset of
#: ``Z``, ``+HH:MM`` or ``+HHMM``.
_TIMESTAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,9}))?"
    r"(?:([Zz])|([+-])(\d{2}):?(\d{2}))"
)
_INT_RE = re.compile(r"[+-]?\d+")
_FLOAT_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_INT64_LOW, _INT64_HIGH = -(2 ** 63), 2 ** 63
_NOT_A_TIME = "not an ISO 8601 time with an offset"


def _timestamp(value: Any) -> int:
    """Nanoseconds since 1970 in UTC."""
    match = _TIMESTAMP_RE.fullmatch(value.strip()) if isinstance(value, str) else None
    if match is None:
        raise _Unread(_NOT_A_TIME)
    year, month, day, hour, minute, second = (int(match.group(index)) for index in range(1, 7))
    try:
        seconds = calendar.timegm(datetime(year, month, day, hour, minute, second).timetuple())
    except ValueError as exc:
        raise _Unread(_NOT_A_TIME) from exc
    if match.group(8) is None:
        hours, minutes = int(match.group(10)), int(match.group(11))
        if hours > 23 or minutes > 59:
            raise _Unread(_NOT_A_TIME)
        seconds -= (hours * 3600 + minutes * 60) * (1 if match.group(9) == "+" else -1)
    nanoseconds = seconds * 1_000_000_000 + int((match.group(7) or "").ljust(9, "0"))
    if not _INT64_LOW <= nanoseconds < _INT64_HIGH:
        raise _Unread("outside the years 1678 to 2261")
    return nanoseconds


def _int(value: Any) -> int:
    if isinstance(value, bool):
        raise _Unread("not a whole number")
    if isinstance(value, float):
        if not value.is_integer():
            raise _Unread("not a whole number")
        value = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if not _INT_RE.fullmatch(text):
            raise _Unread("not a whole number")
        try:
            value = int(text)
        except ValueError as exc:
            # Past the digits Python converts at all, so past 64 bits too.
            raise _Unread("a whole number past 64 bits") from exc
    elif not isinstance(value, int):
        raise _Unread("not a whole number")
    if not _INT64_LOW <= value < _INT64_HIGH:
        raise _Unread("a whole number past 64 bits")
    return value


def _float(value: Any) -> float:
    if isinstance(value, bool):
        raise _Unread("not a number")
    if isinstance(value, str):
        value = value.strip()
        if not _FLOAT_RE.fullmatch(value):
            raise _Unread("not a number")
    elif not isinstance(value, (int, float)):
        raise _Unread("not a number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise _Unread("not a number") from exc
    if not math.isfinite(number):
        raise _Unread("not a number")
    return number


def _bool(value: Any) -> bool:
    if value is True or value is False:
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise _Unread("not true or false")


def _string(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


_CONVERT: dict[str, Callable[[Any], Any]] = {
    "timestamp": _timestamp, "int": _int, "float": _float, "string": _string, "bool": _bool,
}


def _typed(item: Any, column: Column, unread: list[tuple[str, str]]) -> Any:
    """Typed *column*'s value in *item*; one its type cannot read is None,
    noted in *unread*."""
    raw = resolve(item, column.path)
    if raw is _MISSING or raw is None:
        return None
    try:
        return _CONVERT[column.type](raw)
    except _Unread as exc:
        unread.append((column.name, exc.reason))
        return None


def rows_of(
    record: dict[str, Any], rows: LineRows, empty: Callable[[str, str], None] | None = None,
) -> list[Any]:
    """The rows *record* gives: tuples in :attr:`LineRows.names` order, or one
    dict of the line's fields when the lines' fields are the columns.

    ``empty(column, reason)`` is called for each value a column's type could
    not read, which the row holds as null, once the line gives its rows."""
    for path in rows.parse:
        found = _holder(record, path)
        if found is None:
            continue
        holder, at = found
        text = holder[at]
        if isinstance(text, str):
            try:
                holder[at] = json.loads(text, parse_constant=_no_number)
            except (ValueError, RecursionError) as exc:
                raise LineSkipped(f"{path.text} is not JSON text") from exc
    if rows.columns is None and not rows.levels:
        # A line with no fields has nothing to hold.
        return [{name: cell(value) for name, value in record.items()}] if record else []
    unread: list[tuple[str, str]] = []
    own = tuple(
        cell(resolve(record, column.path)) if column.type is None else _typed(record, column, unread)
        for column in rows.columns or ()
    )
    out: list[tuple] = []
    if rows.levels:
        _unpack(record, rows.levels, 0, own, out, unread)
    else:
        out.append(own)
    if empty is not None:
        for name, reason in unread:
            empty(name, reason)
    return out


def _unpack(
    item: Any, levels: tuple[Level, ...], depth: int, kept: tuple, out: list, unread: list[tuple[str, str]],
) -> None:
    level = levels[depth]
    found = resolve(item, level.path)
    if isinstance(found, list):
        entries: Any = enumerate(found)
    elif isinstance(found, dict):
        entries = found.items()
    else:
        raise LineSkipped(f"no list or object at {level.where}")
    last = depth == len(levels) - 1
    for key, child in entries:
        row = kept + (key,) if level.key is not None else kept
        if level.columns:
            row = row + tuple(
                cell(resolve(child, column.path)) if column.type is None else _typed(child, column, unread)
                for column in level.columns
            )
        if last:
            out.append(row)
        else:
            _unpack(child, levels, depth + 1, row, out, unread)
