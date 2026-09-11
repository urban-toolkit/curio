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


def column_names(summary: dict | None) -> list[str]:
    """Every column a summary names (its parts' included)."""
    names: list[str] = []
    if not isinstance(summary, dict):
        return names
    for column in summary.get("columns") or []:
        name = column.get("name") if isinstance(column, dict) else None
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    for part in summary.get("parts") or []:
        for name in column_names(part if isinstance(part, dict) else None):
            if name not in names:
                names.append(name)
    return names


def null_columns(summary: dict | None) -> list[str]:
    """Columns whose every SAMPLED value is null (memo dev/137).

    dev/133's own **F1**: a result can be non-empty and still contain nothing.
    The owner's `7a27b702` is the proof — a ``how="left"`` join on keys that
    cannot match kept two rows and filled every population column with null, so
    the row count passed, the chart's field check passed (the column exists),
    and both plots were empty.

    Read from dev/127's bounded preview only: "every SAMPLED value is null" is
    what the evidence supports, and that is what the refusal says. A summary
    with no sample rows yields nothing — an unverifiable claim is never made.
    """
    if not isinstance(summary, dict):
        return []
    # A merge hands a LIST of frames; a column is all-null when it is all-null
    # in every part that has it, so the samples are gathered across them.
    samples: list[dict] = [
        row for row in (summary.get("sampleRows") or []) if isinstance(row, dict)
    ]
    for part in summary.get("parts") or []:
        if isinstance(part, dict):
            samples.extend(
                row for row in (part.get("sampleRows") or []) if isinstance(row, dict)
            )
    if not samples:
        return []
    empty: list[str] = []
    for name in column_names(summary):
        seen = [row[name] for row in samples if name in row]
        if seen and all(value is None for value in seen):
            empty.append(name)
    return empty


def created_null_columns(
    summary: dict | None, upstream_outputs: list | None
) -> list[str]:
    """The all-null columns THIS node emptied — never one that arrived empty.

    dev/133's attribution rule, applied to values. The comparison is about
    null-ness, not about presence: in the owner's `7a27b702` the joined frame's
    ``population`` column is all null while the population TABLE it came from
    had values (4521, 3890, …), so "the name exists upstream" would have
    excluded exactly the case this check is for. A column is this node's doing
    when it is all-null here and was NOT all-null in any input that had it.
    With no upstream described, every all-null column counts — a loader that
    read nothing useful is the loader's problem.
    """
    nulls = null_columns(summary)
    if not nulls:
        return []
    arrived_empty: set = set()
    for row in (upstream_outputs or []):
        if not isinstance(row, dict):
            continue
        schema = row.get("schema")
        upstream_nulls = set(null_columns(schema))
        present = set(column_names(schema))
        for name in nulls:
            if name in present and name in upstream_nulls:
                arrived_empty.add(name)
    return [name for name in nulls if name not in arrived_empty]


def null_refusal_text(
    *,
    columns: list,
    summary: dict | None,
    upstream_outputs: list | None = None,
) -> str:
    """What the model is told about rows that hold nothing (dev/137)."""
    count = row_count(summary)
    named = ", ".join(str(c) for c in columns[:_MAX_COLUMNS_NAMED])
    head = (
        f"the code ran and produced {count if count is not None else 'some'} "
        f"row{'' if count == 1 else 's'}, but every sampled value of {named} is "
        "NULL — the result has rows and no data in them"
    )
    rows = [row for row in (upstream_outputs or []) if isinstance(row, dict)]
    if rows:
        described = "; ".join(
            _slot_line(index, row) for index, row in enumerate(rows[:_MAX_SLOTS])
        )
        head += f". Its inputs were: {described}"
    head += (
        ". A join that matched nothing with how=\"left\" (or a fill) does exactly "
        "this: compare the key columns' VALUES, not their names, and join on "
        "columns whose values are the same kind of thing. Never keep rows of "
        "nulls, fabricate values, or let a join that matched nothing stand so "
        "the dataflow can proceed — if these inputs cannot be joined, say so in "
        "one line and return no code."
    )
    return head[:_DETAIL_CHARS]


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


# --- dev/136: the RENDER half of "this produced nothing" ----------------------
#
# dev/133 answers it for an artifact; a grammar node produces none. What it
# produces is a picture, and a picture can be empty while its document is
# perfectly valid — so the renderer counts what it drew (frontend
# ``renderOutcome``) and reports the verdict here as a journal record whose
# ``kind`` is ``empty-render:<cause>``. The cause decides who is at fault, and
# therefore what the harness does next.

#: The kind a renderer stamps on an empty render, with its cause appended.
EMPTY_RENDER_KIND = "empty-render"
#: The causes the frontend's ``renderOutcome`` can report, in its own words.
CAUSE_NO_LAYERS = "no-layers"
CAUSE_NO_INPUT_ROWS = "no-input-rows"
CAUSE_NOTHING_DRAWN = "nothing-drawn"
EMPTY_RENDER_CAUSES = (CAUSE_NO_LAYERS, CAUSE_NO_INPUT_ROWS, CAUSE_NOTHING_DRAWN)


def empty_render_cause(kind: object) -> str | None:
    """``"empty-render:no-input-rows"`` → ``"no-input-rows"``, else None.

    An unrecognized cause reads as ``""`` (an empty render whose reason this
    build does not know) and a kind that is not an empty render at all reads as
    None — so a caller can always tell "not this" from "this, reason unknown".
    """
    text = str(kind or "")
    if not text.startswith(EMPTY_RENDER_KIND):
        return None
    _, _, cause = text.partition(":")
    cause = cause.strip()
    return cause if cause in EMPTY_RENDER_CAUSES else ""


def is_document_at_fault(cause: object) -> bool:
    """Whether an empty render is the DOCUMENT's problem (dev/136).

    ``no-input-rows`` is the one that is not: nothing arrived, so no document
    could have drawn anything and rewriting it would be the wrong repair —
    dev/133's rule, applied to a picture.
    """
    return str(cause or "") != CAUSE_NO_INPUT_ROWS


def empty_render_refusal(
    *,
    message: str,
    cause: object = "",
    upstream_outputs: list | None = None,
) -> str:
    """What the model is told about a render that drew nothing (dev/136).

    The renderer's own sentence first — it holds the counts — then what this
    node's inputs actually contain, so the correction is written against the
    data rather than against the goal.
    """
    head = "the document is valid and its last render drew NOTHING: " + str(message or "").strip()
    rows = [row for row in (upstream_outputs or []) if isinstance(row, dict)]
    if rows and is_document_at_fault(cause):
        described = "; ".join(
            _slot_line(index, row) for index, row in enumerate(rows[:_MAX_SLOTS])
        )
        head += f". This node's input holds: {described}"
        head += (
            ". Encode fields that exist and hold values, and remove any filter "
            "or scale domain that excludes every row; return the whole document."
        )
    return head[:_DETAIL_CHARS]
