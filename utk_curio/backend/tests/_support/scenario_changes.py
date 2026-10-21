"""What the shipped dataflows' scenario comparisons must hand on, stated from
their inputs.

Until step 6.4 of the plan answering komar41's review of the #914 merges, the
tests of the SCOUT examples held each comparison node to the Compare Scenarios
node it replaced, run on the same inputs. With that node gone, they are held
to the rules it wrote its outputs by, stated here once; each rule was checked
against Compare Scenarios' own functions, on inputs shaped like the tests',
before they were deleted:

- :func:`keyed_change`, its Difference of two tables or layers joined on a key
  column, with ``absolute`` for each difference's size;
- :func:`roads_change`, its Difference of two layers with no key column, in
  one order and with the same shapes, numbers nested in a column of dicts
  subtracted too (example 06's roads);
- :func:`stacked_rows`, its stacked table, each input's rows under its
  scenario's id and name, read without their geometry.

The fixtures in ``tests/test_packages/fixtures/compare_scenarios/`` hold what
Compare's own functions wrote on the unit tests' inputs, made by
``make_compare_fixtures.py`` there from main as it held them; the tests hold
the nodes, and these rules, to them.
"""
from __future__ import annotations


def _is_number(series) -> bool:
    import pandas as pd

    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _is_number_value(value) -> bool:
    import numpy as np

    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_))


def _no_value(value) -> bool:
    import pandas as pd

    if value is None:
        return True
    try:
        return pd.api.types.is_scalar(value) and bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _holds_dicts(*columns) -> bool:
    held = [value for column in columns for value in column if not _no_value(value)]
    return bool(held) and all(isinstance(value, dict) for value in held)


def _without_numbers(value):
    if isinstance(value, dict):
        return {key: _without_numbers(inner) for key, inner in value.items()}
    return None if _is_number_value(value) else value


def _cell_change(before, after):
    """``(cell, differs)`` for one row's cell of a column of dicts: *after*'s
    dict, then the keys only *before*'s holds, each number both hold
    *after*'s minus *before*'s."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        if _no_value(before) and _no_value(after):
            return None, False
        return _without_numbers(before if _no_value(after) else after), True
    cell, differs = {}, False
    for key in [*after, *(key for key in before if key not in after)]:
        if key not in before or key not in after:
            cell[key] = after[key] if key in after else before[key]
            differs = True
            continue
        old, new = before[key], after[key]
        if isinstance(old, dict) and isinstance(new, dict):
            cell[key], inner = _cell_change(old, new)
        elif _is_number_value(old) and _is_number_value(new):
            old_empty, new_empty = _no_value(old), _no_value(new)
            cell[key] = None if old_empty or new_empty else float(new) - float(old)
            inner = old_empty != new_empty or (not old_empty and not new_empty and float(new) != float(old))
        else:
            cell[key] = new
            inner = not (_no_value(old) and _no_value(new)) and old != new
        differs = differs or bool(inner)
    return cell, differs


def roads_change(before, after):
    """*after*'s layer minus *before*'s, two layers with no key column in one
    order and with the same shapes, each row matched to the row in its place:
    the geometry first and ``change`` second, then the other columns in their
    order. Each number column, and each number in a column of dicts, is
    *after*'s value minus *before*'s; ``change`` says ``changed`` where any
    value differs, else ``unchanged``; every other value, and the shape, is
    *after*'s."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    assert list(before.columns) == list(after.columns), (list(before.columns), list(after.columns))
    assert before.geometry.to_wkb().tolist() == after.geometry.to_wkb().tolist(), "the rows are not in one order"
    geometry = after.geometry.name
    was, now = before.reset_index(drop=True), after.reset_index(drop=True)
    columns = {}
    differs = np.zeros(len(now), dtype=bool)
    for column in [c for c in was.columns if c != geometry]:
        if _is_number(was[column]) and _is_number(now[column]):
            old, new = was[column].astype("float64"), now[column].astype("float64")
            columns[column] = new - old
            differs |= ((old.isna() != new.isna()) | (old.notna() & new.notna() & (new != old))).to_numpy()
        elif _holds_dicts(was[column], now[column]):
            pairs = [_cell_change(old, new) for old, new in zip(was[column], now[column])]
            columns[column] = pd.Series([cell for cell, _ in pairs], dtype=object)
            differs |= np.asarray([flag for _, flag in pairs], dtype=bool)
        else:
            columns[column] = now[column]
            same = (was[column] == now[column]).fillna(False).astype(bool) | (was[column].isna() & now[column].isna())
            differs |= ~same.to_numpy()
    written = pd.DataFrame({geometry: now[geometry], "change": np.where(differs, "changed", "unchanged"), **columns})
    return gpd.GeoDataFrame(written, geometry=geometry, crs=after.crs if after.crs is not None else before.crs)


def keyed_change(before, after, key: str, *, absolute: bool = False):
    """*after*'s rows minus *before*'s, joined on *key*: *before*'s rows in
    its order, then the rows only *after* has, in its order; *key* first and
    ``change`` second, then the other columns in *before*'s order. In each
    number column, *after*'s value minus *before*'s (its size with
    *absolute*), as float64, empty for a row one side lacks. ``change`` says
    ``changed`` where a number or another value differs, else ``unchanged``,
    ``removed`` for a row only *before* has and ``added`` for one only
    *after* has. The geometry and every other value are *after*'s, *before*'s
    for a removed row. Both hold the same columns."""
    import geopandas as gpd
    import numpy as np
    import pandas as pd

    assert list(before.columns) == list(after.columns), (list(before.columns), list(after.columns))
    geometry = before.geometry.name if isinstance(before, gpd.GeoDataFrame) else None
    numbers = [c for c in before.columns if c not in (key, geometry) and _is_number(before[c]) and _is_number(after[c])]
    others = [c for c in before.columns if c not in (key, geometry, *numbers)]
    was, now = before.set_index(key), after.set_index(key)
    gone = [k for k in was.index if k not in now.index]
    keys = [*was.index, *(k for k in now.index if k not in was.index)]
    out = (pd.concat([now, was.loc[gone]]) if gone else now).reindex(keys)
    a = now[numbers].reindex(keys).astype("float64")
    b = was[numbers].reindex(keys).astype("float64")
    out[numbers] = (a - b).abs() if absolute else a - b
    differs = ((a.isna() != b.isna()) | (a.notna() & b.notna() & (a != b))).any(axis=1)
    for column in others:
        left, right = was[column].reindex(keys), now[column].reindex(keys)
        differs |= ~((left == right).fillna(False).astype(bool) | (left.isna() & right.isna()))
    labels = np.select(
        [out.index.isin(gone), ~out.index.isin(was.index), differs.to_numpy()],
        ["removed", "added", "changed"], "unchanged",
    )
    out = out.reset_index()
    out.insert(1, "change", labels)
    if geometry is not None:
        out = gpd.GeoDataFrame(out, geometry=geometry, crs=before.crs if before.crs is not None else after.crs)
    return out


def _json_value(value):
    """*value* as the fixtures hold it: a number, a text, a bool, a dict of
    them, or None for a cell with no value."""
    import numpy as np

    if isinstance(value, dict):
        return {key: _json_value(inner) for key, inner in value.items()}
    if _no_value(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value)
    if isinstance(value, str):
        return str(value)
    return value


def frame_fixture(frame, values: list | None = None) -> dict:
    """A table or layer as the fixtures hold it: its columns in order, their
    types, each row's values in column order (the outlines left out), and for
    a layer its coordinate system and a digest of its outlines, row by row.
    With *values*, only those columns' values are held, and a digest of the
    other columns' values, row by row (a roads layer's hundred OpenStreetMap
    tags, which a change takes as they are)."""
    import hashlib
    import json

    import geopandas as gpd

    geometry = frame.geometry.name if isinstance(frame, gpd.GeoDataFrame) else None
    held_columns = list(values) if values is not None else [c for c in frame.columns if c != geometry]
    held = {
        "columns": list(frame.columns),
        "dtypes": frame.dtypes.astype(str).tolist(),
        "rows": [[_json_value(row[c]) for c in held_columns] for row in frame[held_columns].to_dict("records")],
    }
    if values is not None:
        held["values"] = held_columns
        rest = [c for c in frame.columns if c != geometry and c not in held_columns]
        rows = [[_json_value(row[c]) for c in rest] for row in frame[rest].to_dict("records")]
        held["rest_sha256"] = hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()
    if geometry is not None:
        held["crs"] = frame.crs.to_string() if frame.crs is not None else None
        held["geometry_sha256"] = hashlib.sha256(b"".join(frame.geometry.to_wkb())).hexdigest()
    return held


def _same(got, held, rel: float) -> bool:
    import math

    if isinstance(held, dict) and isinstance(got, dict):
        return list(got) == list(held) and all(_same(got[k], held[k], rel) for k in held)
    if isinstance(held, list) and isinstance(got, list):
        return len(got) == len(held) and all(_same(a, b, rel) for a, b in zip(got, held))
    if isinstance(held, float) and isinstance(got, (int, float)) and not isinstance(got, bool):
        return math.isclose(got, held, rel_tol=rel, abs_tol=0.0) if rel else float(got) == held
    return got == held and type(got) is type(held)


def assert_frame_matches(frame, held: dict, *, rel: float = 0.0, what: str = "") -> None:
    """*frame* is the table or layer the fixture *held* holds: the same
    columns in the same order and of the same types, the same coordinate
    system and outlines, and every value, a number exactly, or within *rel*
    of it where the fixture's numbers come from sums another machine may add
    in another order."""
    got = frame_fixture(frame, held.get("values"))
    assert got["columns"] == held["columns"], (what, got["columns"], held["columns"])
    assert got["dtypes"] == held["dtypes"], (what, got["dtypes"], held["dtypes"])
    assert got.get("crs") == held.get("crs"), (what, got.get("crs"), held.get("crs"))
    assert got.get("geometry_sha256") == held.get("geometry_sha256"), (what, "the outlines differ")
    assert got.get("rest_sha256") == held.get("rest_sha256"), (what, "the columns the fixture digests differ")
    assert len(got["rows"]) == len(held["rows"]), (what, len(got["rows"]), len(held["rows"]))
    wrong = [(k, row, want) for k, (row, want) in enumerate(zip(got["rows"], held["rows"])) if not _same(row, want, rel)]
    assert not wrong, (what, f"{len(wrong)} rows differ, the first: {wrong[0]}")


def assert_rows_match(rows: list, held: list, *, rel: float = 0.0, what: str = "") -> None:
    """*rows*, records, are the fixture's *held* records: the same keys in the
    same order and every value, a number exactly or within *rel*."""
    got = [{key: _json_value(value) for key, value in row.items()} for row in rows]
    assert len(got) == len(held), (what, len(got), len(held))
    wrong = [(k, row, want) for k, (row, want) in enumerate(zip(got, held)) if not _same(row, want, rel)]
    assert not wrong, (what, f"{len(wrong)} rows differ, the first: {wrong[0]}")


def park_shade_inputs(parks: list) -> dict:
    """Each scenario's Shade per park table on fixed numbers, shaped like the
    node's output in the park shade dataflow: the parks (``park``,
    ``area_m2`` and an outline in EPSG:4326), then ``cells`` and the minutes
    and shares it measures, Existing's the most shadow, Height cap's less and
    Towers removed's the least. Deep Umbra's own shadow moves with
    onnxruntime's thread count, so a fixture of Compare's output on a real
    run would hold one machine's numbers; these hold every machine's."""
    import geopandas as gpd
    from shapely.geometry import box

    taken = {"existing": 0.0, "height-cap": 30.0, "towers-removed": 60.0}
    tables = {}
    for scenario, less in taken.items():
        rows = []
        for k, park in enumerate(parks):
            mean = 250.0 + 7.25 * k - less - (1.25 if scenario == "height-cap" else 2.5) * k * (less > 0)
            sun = 0.1 + 0.01 * (k % 5) + less / 1000.0
            deep = 0.4 - 0.01 * (k % 3) - less / 2000.0
            rows.append({
                "park": park,
                "area_m2": 600.0 + 37.5 * k,
                "geometry": box(-74.015 + 0.001 * k, 40.700, -74.0145 + 0.001 * k, 40.7005),
                "cells": 40 + 3 * k,
                "mean_min": mean,
                "median_min": mean - 4.5,
                "p90_min": mean + 20.0,
                "pct_daylight": mean / 720.0,
                "share_sun": sun,
                "share_partial": 1.0 - sun - deep,
                "share_deep": deep,
            })
        tables[scenario] = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return tables


def stacked_rows(entries) -> list:
    """Each of *entries*' rows, ``(scenario id, scenario name, frame)`` in
    circle order, under ``scenario`` and ``scenario_name``, its geometry left
    out, as records."""
    rows = []
    for scenario, name, frame in entries:
        geometry = getattr(frame, "_geometry_column_name", None)
        table = frame.drop(columns=[geometry] if geometry in frame.columns else [])
        rows += [{"scenario": scenario, "scenario_name": name, **row} for row in table.to_dict("records")]
    return rows
