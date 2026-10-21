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
