"""Did this node's code produce anything? (memo dev/133)

``DEC-073``'s verified loop asks the sandbox to RUN a candidate and reads the
run's status. "It ran" and "it worked" are different claims, and for a join, a
filter, a spatial predicate or a groupby they come apart exactly when the model
guessed a key: the code is syntactically fine, the run is clean, and the result
is empty.

The field proof is the owner's ``e72c7080``. Its Python node holds

    joined_gdf = gdf_boundaries.merge(df_population,
                                      left_on='area_numbe', right_on='tract_id')

and the runtime journal records ``status: ok`` in 45 ms. On disk, the boundaries
carry ``area_numbe ∈ {32, 41}`` (integer community-area numbers) and the
population table carries ``tract_id ∈ {17031010100, …}`` (11-digit census
tracts): the key sets are disjoint by construction, so the merge returns **zero
rows**. Solve called that node *solved*, the Data Pool below it rendered
*"Nothing to display — this input is not tabular data"* (an empty GeoDataFrame
has no features to tabulate) and the Vega chart below it plotted an empty
values array. One defect, three symptoms, and a green dataflow built on nothing.

So an empty result is a **verdict**: a table or geotable with no rows, produced
from inputs that had rows, is a failed round whose diagnosis names the inputs'
key columns and their sample VALUES — the names looked joinable, the values
never did.

Pure over the summaries ``upstream_schema`` already builds: no I/O, no spec, no
network. Total — an unknown shape is never a failure.
"""

from __future__ import annotations

#: The summary kinds emptiness is defined for. A ``VALUE``, a ``dict``, a raster
#: or a plot has no row count, and inventing one would be a guess.
COUNTABLE_KINDS = ("table", "geotable")

_DETAIL_CHARS = 900
_MAX_SLOTS = 5
_MAX_COLUMNS_NAMED = 8


def row_count(summary: dict | None) -> int | None:
    """This summary's row count, or None when the shape has no such notion."""
    if not isinstance(summary, dict):
        return None
    kind = str(summary.get("kind") or "")
    if kind in COUNTABLE_KINDS:
        count = summary.get("rowCount")
        return int(count) if isinstance(count, int) else None
    if kind == "parts":
        # A merge hands a LIST of frames: its row count is the total across the
        # parts, so "empty" means every part is empty.
        total = 0
        seen = False
        for part in summary.get("parts") or []:
            part_count = row_count(part if isinstance(part, dict) else None)
            if part_count is not None:
                seen = True
                total += part_count
        return total if seen else None
    return None


def is_empty(summary: dict | None) -> bool:
    """Whether this node produced a countable result with **no rows in it**."""
    count = row_count(summary)
    return count == 0


def inputs_had_rows(upstream_outputs: list | None) -> bool | None:
    """``True`` / ``False`` / ``None`` — did everything this node consumed have
    rows?

    ``None`` means unknown (no upstream described, no preview): the caller must
    not blame the node for emptiness it cannot attribute. ``False`` means an
    input was itself empty, and the blame belongs upstream, where dev/118
    already reports it.
    """
    rows = [row for row in (upstream_outputs or []) if isinstance(row, dict)]
    if not rows:
        return None
    counts = [row_count(row.get("schema")) for row in rows]
    known = [c for c in counts if c is not None]
    if not known:
        return None
    if any(c == 0 for c in known):
        return False
    return True


def _columns_line(summary: dict | None) -> str:
    """``community str e.g. "Loop", area_numbe int e.g. 32`` — the columns AND
    a value each, because the names are what misled the author."""
    if not isinstance(summary, dict):
        return ""
    columns = [c for c in (summary.get("columns") or []) if isinstance(c, dict)]
    samples = [s for s in (summary.get("sampleRows") or []) if isinstance(s, dict)]
    first = samples[0] if samples else {}
    parts = []
    for column in columns[:_MAX_COLUMNS_NAMED]:
        name = str(column.get("name") or "")
        if not name:
            continue
        dtype = str(column.get("dtype") or "")
        value = first.get(name)
        piece = f"{name}{' ' + dtype if dtype else ''}"
        if value is not None:
            piece += f" e.g. {value!r}"
        parts.append(piece)
    if len(columns) > _MAX_COLUMNS_NAMED:
        parts.append(f"… {len(columns) - _MAX_COLUMNS_NAMED} more")
    return ", ".join(parts)


def _slot_line(index: int, row: dict) -> str:
    summary = row.get("schema") if isinstance(row.get("schema"), dict) else None
    goal = str(row.get("goal") or row.get("upstreamNodeId") or "an input")[:60]
    arg = row.get("argIndex")
    where = f"arg[{arg}]" if isinstance(arg, int) else f"input {index}"
    if summary is None:
        return f"{where} {goal!r} (shape unknown)"
    count = row_count(summary)
    kind = str(summary.get("kind") or "?")
    columns = _columns_line(summary)
    return (
        f"{where} {goal!r} ({kind}"
        + (f", {count} row{'s' if count != 1 else ''}" if count is not None else "")
        + (f": {columns}" if columns else "")
        + ")"
    )


def refusal_text(
    *,
    summary: dict | None,
    upstream_outputs: list | None,
    output_data_type: str = "",
) -> str:
    """What the model is told, and what a human reads in the trail (dev/133).

    Three things the text must do: state the cause CLASS (a join or a filter
    matched nothing), show the inputs' values (the column names looked joinable
    — the values never did), and offer the honest alternative, which the loop
    already treats as a terminal decline rather than something to retry
    forever.
    """
    kind = str((summary or {}).get("kind") or "result")
    head = (
        "the code ran but produced an EMPTY result — 0 rows"
        + (f" out of a {output_data_type}" if output_data_type else f" ({kind})")
    )
    rows = [row for row in (upstream_outputs or []) if isinstance(row, dict)]
    if rows:
        described = "; ".join(
            _slot_line(index, row) for index, row in enumerate(rows[:_MAX_SLOTS])
        )
        head += f". Its inputs were NOT empty: {described}"
    head += (
        ". A join, merge or filter matched nothing: compare the key columns' "
        "VALUES, not their names — two columns can both look like an id and "
        "describe different things (a community-area number is not a census "
        "tract id). Either join on columns whose values are the same kind of "
        "thing, or say plainly that these inputs cannot be joined."
    )
    return head[:_DETAIL_CHARS]
