"""The Compare Scenarios node's difference step (#662).

In Difference the node compares exactly two inputs: input 0 is the reference
and input 1 the comparison, and every number it gives is comparison minus
reference. Its code calls ``curio_difference_scenarios`` with one
``(scenario id, scenario name, input)`` entry per input, as the stacking step
(``scenario_stack.py``) takes them, and reads its inputs the same way.

- Two layers (GeoDataFrames) or two tables are joined on a stable id: ``key``
  when the node names one, else ``osm_id`` or ``building_id``, the first both
  have. A row on both sides holds, in each number column both have, the
  comparison's value minus the reference's, and ``change`` says ``changed`` or
  ``unchanged``. A column both have whose cells are dicts, such as the
  ``compute`` an Autark compute step writes its outputs under, is read the same
  way inside: each number both dicts hold is a difference too. A row only in
  the reference is ``removed`` and one only in the comparison ``added``; their
  numbers are empty, nested ones included. Every other column and value, and
  the geometry, is the comparison's (the reference's for a removed row).
- Two rasters are subtracted cell by cell by Curio's Autark adapter
  (``utils/raster/rasterArithmetic.ts``), on the band arrays autk-db's
  ``getRaster`` exports once its ``loadGeoTiff`` has loaded both, in the
  sandbox's Node process, where Autark data sections run. Node code may run in
  an isolated child that cannot start Node, so the step returns a request
  instead (``RASTER_DIFFERENCE``: JSON only, each raster's GeoTIFF bytes and
  its description), and the sandbox completes it once the code has returned
  (:func:`complete_raster_difference`). The result is the envelope a raster
  travels in between nodes (``utils/raster/rasterWire.ts``): an Autark map
  draws it, and a Python node receives it as a rasterio dataset.

Anything else is refused with a sentence naming both inputs.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from utk_curio.sandbox.util.scenario_stack import (
    _EMPTY,
    _GEO,
    _TABLE,
    _VALUE,
    _crs_name,
    _is_raster,
    _label,
    _rows_of,
    _unwrap,
)

#: What the node's code returns for two rasters, for the sandbox to complete.
RASTER_DIFFERENCE = "raster-difference"

#: The column a difference of layers or tables adds, and what it holds.
CHANGE_COLUMN = "change"
ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"
UNCHANGED = "unchanged"

#: The ids rows are joined on when the node names no key, the first both have.
STABLE_IDS = ("osm_id", "building_id")

#: The most cells, and the longest side, an Autark map loads from one raster:
#: ``RASTER_MAX_CELLS`` and ``RASTER_MAX_SIDE`` in ``utils/raster/rasterLoad.ts``.
MAX_CELLS = 2048 * 2048
MAX_SIDE = 8192

_RASTER = "raster"

#: How each kind is named in a refusal.
_WORDS = {_RASTER: "a raster", _GEO: "a layer", _TABLE: "a table", _VALUE: "a value", _EMPTY: "empty"}

#: The program the sandbox's Node process runs for two rasters, and where the
#: frontend's raster modules it imports are.
_PROGRAM = Path(__file__).with_name("raster_difference.js")
_RASTER_MODULES = (
    Path(__file__).resolve().parents[2] / "frontend" / "urban-workflows" / "src" / "utils" / "raster"
)

#: The frontend's modules have no package type of their own; Node reads them as
#: ES modules by their syntax and would say so on every run.
_NODE_FLAGS = ("--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",)


class RasterDifferenceFailed(Exception):
    """Two rasters the sandbox could not subtract, with the reason in words."""


def _side(position: int, entry) -> dict:
    if not isinstance(entry, (tuple, list)) or len(entry) != 3:
        raise TypeError(
            f"Compare Scenarios: entry {position} is not (scenario, name, input). "
            "Its code is written for it; connect the inputs again to write it anew."
        )
    scenario, name, value = entry
    name = "" if name is None else str(name)
    label = _label(position, name)
    side = {"scenario": scenario, "name": name, "label": label}
    value = _unwrap(value)
    if value is not None and _is_raster(value):
        return {**side, "kind": _RASTER, "value": value}
    kind, frame = _rows_of(label, value)
    return {**side, "kind": kind, "frame": frame}


def difference_scenarios(entries, key=None):
    """The second input minus the first: a difference layer or table, or, for
    two rasters, the request the sandbox completes.

    *entries* lists ``(scenario_id, scenario_name, value)`` per input, in
    circle order. *key* names the column rows are joined on.
    """
    entries = list(entries or [])
    if len(entries) != 2:
        raise ValueError(
            "Compare Scenarios in Difference compares two inputs, a reference and a comparison, "
            f"and it has {len(entries)}. Connect two outcomes, or show them as a Chart."
        )
    reference, comparison = (_side(position, entry) for position, entry in enumerate(entries))
    if reference["kind"] == _RASTER and comparison["kind"] == _RASTER:
        return _raster_request(reference, comparison)
    if reference["kind"] == comparison["kind"] and reference["kind"] in (_GEO, _TABLE):
        return _join(reference, comparison, key)
    raise ValueError(
        "Compare Scenarios in Difference compares two rasters, two layers or two tables, and "
        f"{reference['label']} is {_WORDS[reference['kind']]} while {comparison['label']} is "
        f"{_WORDS[comparison['kind']]}. Connect outcomes of one kind, or show them as a Chart."
    )


# ---------------------------------------------------------------------------
# Layers and tables
# ---------------------------------------------------------------------------

def _is_number(series) -> bool:
    import pandas as pd

    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _join_key(reference: dict, comparison: dict, key, geometry) -> str:
    ref_columns = list(reference["frame"].columns)
    cmp_columns = list(comparison["frame"].columns)
    common = [column for column in ref_columns if column in cmp_columns and column != geometry]
    shared = ", ".join(str(column) for column in common[:8])
    pick = f"Pick a key both have: {shared}." if common else "They share no column to join on."
    if key not in (None, ""):
        for side in (reference, comparison):
            if key not in side["frame"].columns:
                raise ValueError(f"Compare Scenarios: {side['label']} has no column {key} to join on. {pick}")
        return key
    for candidate in STABLE_IDS:
        if candidate in ref_columns and candidate in cmp_columns:
            return candidate
    raise ValueError(
        f"Compare Scenarios cannot match the rows of {reference['label']} and {comparison['label']}: "
        f"they do not both have {' or '.join(STABLE_IDS)}. {pick}"
    )


def _ids(side: dict, key: str) -> list:
    values = side["frame"][key]
    missing = int(values.isna().sum())
    if missing:
        raise ValueError(
            f"Compare Scenarios: {side['label']} has {missing} row{'s' if missing != 1 else ''} with no {key}, "
            "so they cannot be matched. Give every row one in the node that feeds it, or pick another key."
        )
    repeated = values[values.duplicated(keep=False)]
    if not repeated.empty:
        first = repeated.iloc[0]
        count = int((values == first).sum())
        raise ValueError(
            f"Compare Scenarios: {side['label']} has {count} rows with {key} {first}, and a key names one row "
            f"on each side. Pick another key, or keep one row per {key} in the node that feeds it."
        )
    return values.tolist()


def _no_value(value) -> bool:
    """Whether a cell holds nothing: None, or an empty number."""
    import pandas as pd

    if value is None:
        return True
    try:
        return pd.api.types.is_scalar(value) and bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _is_nested(*columns) -> bool:
    """Whether every cell of *columns* that holds something holds a dict."""
    held = [value for column in columns for value in column if not _no_value(value)]
    return bool(held) and all(isinstance(value, dict) for value in held)


def _is_number_value(value) -> bool:
    import numpy as np

    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def _without_numbers(value):
    """*value* with each number in it, at any depth, made empty: what a row on
    one side only holds in a nested column, as its number columns are empty."""
    if isinstance(value, dict):
        return {key: _without_numbers(inner) for key, inner in value.items()}
    return None if _is_number_value(value) else value


def _nested_difference(before, after):
    """``(cell, changed)`` for one row of a nested column: *after* with each
    number that *before* holds at the same place replaced by after minus
    before, and whether any value differs. A value one side alone holds is kept
    from that side, as a column one side alone has is."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        if _no_value(before) and _no_value(after):
            return None, False
        held = before if _no_value(after) else after
        return _without_numbers(held), True
    out = {}
    changed = False
    for key in [*after, *(key for key in before if key not in after)]:
        if key not in before or key not in after:
            out[key] = after[key] if key in after else before[key]
            changed = True
            continue
        old, new = before[key], after[key]
        if isinstance(old, dict) and isinstance(new, dict):
            out[key], differs = _nested_difference(old, new)
        elif _is_number_value(old) and _is_number_value(new):
            old_empty, new_empty = _no_value(old), _no_value(new)
            out[key] = None if old_empty or new_empty else float(new) - float(old)
            differs = old_empty != new_empty or (not old_empty and not new_empty and float(new) != float(old))
        else:
            out[key] = new
            differs = not (_no_value(old) and _no_value(new)) and bool(_differs_once(old, new))
        changed = changed or differs
    return out, changed


def _differs_once(left, right) -> bool:
    try:
        return bool(left != right)
    except (TypeError, ValueError):
        return str(left) != str(right)


def _differs(left, right):
    """Where two columns of one length hold different values; two empty cells
    are the same."""
    import pandas as pd

    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    both_empty = left.isna() & right.isna()
    try:
        equal = pd.Series(left == right).fillna(False).astype(bool)
    except (TypeError, ValueError):
        equal = left.astype(str) == right.astype(str)
    return (~(equal | both_empty)).to_numpy()


def _join(reference: dict, comparison: dict, key):
    import numpy as np
    import pandas as pd

    geo = reference["kind"] == _GEO
    ref = reference["frame"].reset_index(drop=True)
    cmp = comparison["frame"].reset_index(drop=True)
    for side in (reference, comparison):
        if CHANGE_COLUMN in side["frame"].columns:
            raise ValueError(
                f"Compare Scenarios: {side['label']} already has a column named {CHANGE_COLUMN}. "
                "Rename it in the node that feeds it: the difference adds its own."
            )

    geometry = None
    crs = None
    if geo:
        geometry = ref.geometry.name
        named = [(side["label"], _crs_name(frame.crs)) for side, frame in ((reference, ref), (comparison, cmp))]
        if all(text is not None for _, text in named) and named[0][1] != named[1][1]:
            described = ", ".join(f"{label} is in {text}" for label, text in named)
            raise ValueError(
                f"Compare Scenarios: the inputs use different coordinate systems: {described}. "
                "Reproject them to one in the nodes that feed it."
            )
        crs = ref.crs if ref.crs is not None else cmp.crs
        if cmp.geometry.name != geometry:
            cmp = cmp.rename_geometry(geometry)
        if crs is not None and ref.crs is None:
            print(f"Compare Scenarios: {reference['label']} names no coordinate system; its rows are read as {_crs_name(crs)}.")
            ref = ref.set_crs(crs)
        if crs is not None and cmp.crs is None:
            print(f"Compare Scenarios: {comparison['label']} names no coordinate system; its rows are read as {_crs_name(crs)}.")
            cmp = cmp.set_crs(crs)

    key = _join_key(reference, comparison, key, geometry)
    ref_ids = _ids({**reference, "frame": ref}, key)
    cmp_ids = _ids({**comparison, "frame": cmp}, key)

    columns = [c for c in ref.columns if c != key] + [c for c in cmp.columns if c != key and c not in ref.columns]
    common = [c for c in columns if c in ref.columns and c in cmp.columns and c != geometry]
    numbers = [c for c in common if _is_number(ref[c]) and _is_number(cmp[c])]
    nested = [c for c in common if c not in numbers and _is_nested(ref[c], cmp[c])]
    others = [c for c in common if c not in numbers and c not in nested]
    reference_only = [c for c in columns if c not in cmp.columns]

    cmp_at = {value: row for row, value in enumerate(cmp_ids)}
    ref_at = {value: row for row, value in enumerate(ref_ids)}
    both_ref = [row for row, value in enumerate(ref_ids) if value in cmp_at]
    both_cmp = [cmp_at[ref_ids[row]] for row in both_ref]
    removed = [row for row, value in enumerate(ref_ids) if value not in cmp_at]
    added = [row for row, value in enumerate(cmp_ids) if value not in ref_at]

    def rows_of(frame, rows):
        return pd.DataFrame(frame.iloc[rows]).reset_index(drop=True).reindex(columns=[key, *columns])

    on_both = rows_of(cmp, both_cmp)
    ref_both = pd.DataFrame(ref.iloc[both_ref]).reset_index(drop=True)
    for column in reference_only:
        on_both[column] = ref_both[column].to_numpy()
    changed = np.zeros(len(both_ref), dtype=bool)
    for column in numbers:
        before = pd.to_numeric(ref_both[column], errors="coerce").to_numpy(dtype="float64")
        after = pd.to_numeric(on_both[column], errors="coerce").to_numpy(dtype="float64")
        on_both[column] = after - before
        before_empty, after_empty = np.isnan(before), np.isnan(after)
        changed |= (before_empty != after_empty) | (~before_empty & ~after_empty & (after != before))
    for column in nested:
        pairs = [_nested_difference(old, new) for old, new in zip(ref_both[column], on_both[column])]
        on_both[column] = pd.Series([cell for cell, _ in pairs], index=on_both.index, dtype=object)
        changed |= np.asarray([flag for _, flag in pairs], dtype=bool)
    for column in others:
        changed |= _differs(ref_both[column], on_both[column])
    on_both.insert(1, CHANGE_COLUMN, np.where(changed, CHANGED, UNCHANGED))

    # The reference's rows in its order, each matched or removed, then the
    # rows only the comparison has, in its order.
    parts = [on_both]
    places = [np.asarray(both_ref, dtype="int64")]
    for frame, rows, change, place in (
        (ref, removed, REMOVED, removed),
        (cmp, added, ADDED, [len(ref) + row for row in added]),
    ):
        part = rows_of(frame, rows)
        for column in numbers:
            part[column] = np.nan
        for column in nested:
            part[column] = pd.Series([_without_numbers(v) for v in part[column]], index=part.index, dtype=object)
        part.insert(1, CHANGE_COLUMN, change)
        parts.append(part)
        places.append(np.asarray(place, dtype="int64"))

    kept = [index for index, part in enumerate(parts) if len(part)] or [0]
    out = pd.concat([parts[index] for index in kept], ignore_index=True, sort=False)
    order = np.argsort(np.concatenate([places[index] for index in kept]), kind="stable")
    out = out.iloc[order].reset_index(drop=True)
    for column in numbers:
        out[column] = out[column].astype("float64")
    if geo:
        import geopandas as gpd

        out = gpd.GeoDataFrame(out, geometry=geometry, crs=crs)
    return out


# ---------------------------------------------------------------------------
# Rasters
# ---------------------------------------------------------------------------

def _oversize(label: str, width: int, height: int) -> str:
    """``oversizeSentence`` in ``utils/raster/rasterLoad.ts``, in its words."""
    return (
        f"{label} is {width} by {height} cells, more than an Autark map loads at its own size "
        f"({MAX_CELLS} cells, {MAX_SIDE} on a side). Crop it in the node that makes it, "
        "for example with a rasterio window read, and run that node again."
    )


def _raster_request(reference: dict, comparison: dict) -> dict:
    from utk_curio.sandbox.util.rasters import geotiff_bytes, raster_meta

    request = {"dataType": RASTER_DIFFERENCE}
    for role, side in (("reference", reference), ("comparison", comparison)):
        dataset = side["value"]
        meta = raster_meta(dataset)
        width, height = meta["width"], meta["height"]
        if width * height > MAX_CELLS or max(width, height) > MAX_SIDE:
            raise ValueError(f"Compare Scenarios: {_oversize(side['label'], width, height)}")
        request[role] = {
            "scenario": side["scenario"],
            "name": side["name"],
            "label": side["label"],
            "meta": meta,
            "geotiff": base64.b64encode(geotiff_bytes(dataset)).decode("ascii"),
        }
    return request


def is_raster_request(value) -> bool:
    """Whether *value* is what the difference step returns for two rasters."""
    return (
        isinstance(value, dict)
        and value.get("dataType") == RASTER_DIFFERENCE
        and isinstance(value.get("reference"), dict)
        and isinstance(value.get("comparison"), dict)
    )


def program_text() -> str:
    """The raster program, importing the frontend's raster modules by file URL."""
    return _PROGRAM.read_text(encoding="utf-8").replace("__CURIO_RASTER_MODULES__", _RASTER_MODULES.as_uri())


def subtract_in_autark(request: dict, *, cwd=None, node_type="curio.builtin/compare-scenarios") -> dict:
    """Run the raster program on *request* in the sandbox's Node process, as a
    JavaScript node runs: the envelope of comparison minus reference, or
    :class:`RasterDifferenceFailed` with what refused it."""
    import json
    import subprocess
    import time

    from utk_curio.sandbox.app.worker import run_js_script

    try:
        result_json, _logs, stderr_lines = run_js_script(
            program_text(), request, cwd=cwd or os.getcwd(), node_type=node_type,
            t0=time.perf_counter(), node_flags=_NODE_FLAGS,
        )
    except FileNotFoundError as exc:
        raise RasterDifferenceFailed(
            "Compare Scenarios needs Node.js to subtract two rasters, and this sandbox has none."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RasterDifferenceFailed("Compare Scenarios: subtracting the two rasters timed out.") from exc
    if result_json is None:
        detail = "\n".join(stderr_lines).strip() or "Node.js exited without a result."
        raise RasterDifferenceFailed(f"Compare Scenarios could not subtract the two rasters: {detail}")
    try:
        outcome = json.loads(result_json)
    except ValueError as exc:
        raise RasterDifferenceFailed("Compare Scenarios: the raster program returned malformed JSON.") from exc
    if not outcome.get("success"):
        # The program throws the refusal itself; the line after it is its stack.
        message = str(outcome.get("error") or "the raster program failed").split("\n")[0].strip()
        raise RasterDifferenceFailed(f"Compare Scenarios: {message}")
    return outcome.get("value")


def complete_raster_difference(result, *, node_type, session_id=None, launch_dir=None):
    """A node's response, with a raster request its code returned replaced by
    the difference: run once the code has returned, in process or isolated
    alike, since only this process may start Node. Any other response is
    returned as it came."""
    output = result.get("output") if isinstance(result, dict) else None
    if not isinstance(output, dict) or output.get("dataType") != "dict" or not output.get("path"):
        return result

    from utk_curio.sandbox.util.parsers import load_artifact, save_to_duckdb

    try:
        value = load_artifact(output["path"], session_id=session_id)
    except Exception:  # noqa: BLE001 - not a request then; the node's output stands
        return result
    if not is_raster_request(value):
        return result
    try:
        envelope = subtract_in_autark(value, cwd=launch_dir, node_type=node_type)
    except RasterDifferenceFailed as failure:
        stderr = str(result.get("stderr") or "")
        return {
            **result,
            "stderr": f"{stderr}\n{failure}" if stderr.strip() else str(failure),
            "output": {"path": "", "dataType": "str"},
        }
    art_id = save_to_duckdb(envelope, node_id=node_type, session_id=session_id)
    return {**result, "output": {"path": art_id, "dataType": "dict"}}
