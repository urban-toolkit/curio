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
- :func:`stacked_rows`, its stacked table, each input's rows under its
  scenario's id and name, read without their geometry.
"""
from __future__ import annotations


def _is_number(series) -> bool:
    import pandas as pd

    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


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
