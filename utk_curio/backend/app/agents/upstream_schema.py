"""What a node's inputs actually contain — columns, dtypes, shape.

Memo dev/127. The owner's failing node had to join two frames and was told
neither's columns: ``_upstream_outputs_for`` supplied ``outputDataType:
dataframe`` and nothing else, and only for upstreams that had EXECUTED — its
own upstream was a ``merge-flow``, written but never executed (``DEC-075``), so
the list was empty. Three correction rounds went into guessing a join key
(``community_area``), then raising the code's own ``KeyError('No common column
found…')``, then asking a plain ``DataFrame`` for ``.crs``.

The answer was one bounded request away the whole time: the sandbox stores every
artifact and serves a preview at ``GET /get?fileName=<id>&maxRows=<n>``. This
module turns that preview into the smallest honest description of a frame — its
columns, their dtypes, its row count, a couple of rows — so the child reads what
it has instead of inventing it. This is ``DEC-063`` again: an input the agent
needs must be supplied on the path it runs on.

Pure over the preview payload; the fetching is the runner's (bounded there).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: Bounds. A schema is a description, never a copy of the data.
MAX_COLUMNS = 60
MAX_SAMPLE_ROWS = 3
MAX_VALUE_CHARS = 80
MAX_MERGE_PARTS = 5


def _clip(value: object) -> object:
    """A sample cell: JSON-native and short, or its clipped text."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value
    text = str(value)
    return text[:MAX_VALUE_CHARS] + "…" if len(text) > MAX_VALUE_CHARS else text


def _dtype_of(values: list) -> str:
    """A column's dtype, named from what the preview actually holds."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        if isinstance(value, (dict, list)):
            return "object"
        return "str"
    return "unknown"


def _from_column_dict(data: dict, *, row_count: object = None) -> dict:
    """A ``dataframe`` preview: ``{column: [values…]}`` (pandas orient="list")."""
    names = [str(k) for k in list(data.keys())[:MAX_COLUMNS]]
    columns = []
    rows = 0
    for name in names:
        values = data.get(name)
        values = values if isinstance(values, list) else []
        rows = max(rows, len(values))
        columns.append({"name": name, "dtype": _dtype_of(values)})
    sample = []
    for index in range(min(rows, MAX_SAMPLE_ROWS)):
        sample.append({
            name: _clip((data.get(name) or [None] * (index + 1))[index])
            for name in names
            if isinstance(data.get(name), list) and index < len(data[name])
        })
    out: dict = {"kind": "table", "columns": columns, "sampleRows": sample}
    out["rowCount"] = int(row_count) if isinstance(row_count, int) else rows
    if len(data) > MAX_COLUMNS:
        out["columnsElided"] = len(data) - MAX_COLUMNS
    return out


def _from_geojson(data: dict) -> dict:
    """A ``geodataframe`` preview: a GeoJSON FeatureCollection."""
    features = data.get("features")
    features = features if isinstance(features, list) else []
    props = {}
    for feature in features[:MAX_SAMPLE_ROWS]:
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict):
            props.update(feature["properties"])
    names = [str(k) for k in list(props.keys())[:MAX_COLUMNS]]
    columns = [{"name": name, "dtype": _dtype_of([props.get(name)])} for name in names]
    columns.append({"name": "geometry", "dtype": "geometry"})
    sample = []
    for feature in features[:MAX_SAMPLE_ROWS]:
        if not isinstance(feature, dict):
            continue
        row = {k: _clip(v) for k, v in (feature.get("properties") or {}).items()
               if str(k) in names}
        geom = (feature.get("geometry") or {}).get("type") if isinstance(
            feature.get("geometry"), dict) else None
        if geom:
            row["geometry"] = f"<{geom}>"
        sample.append(row)
    out = {
        "kind": "geotable",
        "columns": columns,
        "sampleRows": sample,
        "rowCount": len(features),
    }
    crs = data.get("crs")
    if isinstance(crs, dict):
        name = ((crs.get("properties") or {}).get("name")) if isinstance(
            crs.get("properties"), dict) else None
        if name:
            out["crs"] = str(name)[:MAX_VALUE_CHARS]
    if len(props) > MAX_COLUMNS:
        out["columnsElided"] = len(props) - MAX_COLUMNS
    return out


def summarize(preview: object) -> dict | None:
    """The smallest honest description of a ``/get`` preview payload, or None.

    Handles the three shapes the sandbox's ``parseOutput`` produces for node
    output: a dataframe (columns → lists), a geodataframe (GeoJSON), and
    ``outputs`` — a tuple/list, which is what a ``merge-flow`` hands the next
    node as ``arg``. Anything else yields its ``dataType`` alone: honest
    absence beats a description of a shape this module does not know.
    """
    if not isinstance(preview, dict):
        return None
    data_type = str(preview.get("dataType") or "")
    data = preview.get("data")
    total_rows = preview.get("totalRows")
    try:
        if data_type == "dataframe" and isinstance(data, dict):
            return _from_column_dict(data, row_count=total_rows)
        if data_type == "geodataframe" and isinstance(data, dict):
            return _from_geojson(data)
        if data_type in ("outputs", "list", "tuple") and isinstance(data, list):
            parts = [summarize(part) for part in data[:MAX_MERGE_PARTS]]
            parts = [p for p in parts if p]
            if not parts:
                return {"kind": data_type or "list", "parts": []}
            return {"kind": "parts", "parts": parts}
        if data_type:
            return {"kind": data_type}
    except Exception:  # noqa: BLE001
        log.warning("Could not summarize an artifact preview (%s)", data_type, exc_info=True)
        return None
    return None


def describe(summary: object) -> str:
    """One line for a card or a log: ``table · 77 rows · area_numbe, community…``."""
    if not isinstance(summary, dict):
        return ""
    if summary.get("kind") == "parts":
        return " | ".join(describe(part) for part in summary.get("parts") or [])
    bits = [str(summary.get("kind") or "?")]
    if isinstance(summary.get("rowCount"), int):
        bits.append(f"{summary['rowCount']} rows")
    names = [str(c.get("name")) for c in (summary.get("columns") or [])][:8]
    if names:
        bits.append(", ".join(names))
    return " · ".join(bits)


#: dev/134: how many column names a document's field check is given. A wide
#: frame's whole header is not evidence, and the refusal names what it lists.
MAX_KNOWN_COLUMNS = 200


def columns_of(upstream_outputs: list | None) -> list[str]:
    """Every column name this node's inputs actually have (memo dev/134).

    Read from the same rows the generation request was handed — each carries
    the ``schema`` this module summarized — so the instruction and the check
    cannot disagree (``DEC-063``). An input whose artifact could not be
    described contributes nothing rather than a guess, so an unknown shape
    yields an EMPTY list, which callers must read as "do not check".
    """
    names: list[str] = []
    for row in upstream_outputs or []:
        if not isinstance(row, dict):
            continue
        schema = row.get("schema")
        if not isinstance(schema, dict):
            continue
        for column in schema.get("columns") or []:
            name = column.get("name") if isinstance(column, dict) else None
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        # A merge hands a LIST of frames (``kind: "parts"``); each part's own
        # columns are what a downstream document could read.
        for part in schema.get("parts") or []:
            for column in (part or {}).get("columns") or []:
                name = column.get("name") if isinstance(column, dict) else None
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
    return names[:MAX_KNOWN_COLUMNS]
