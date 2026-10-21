"""Every input's rows stacked under its scenario (#662).

A Vega-Lite chart whose spec names the dataset ``inputs`` reads its inputs
stacked: one table of every input's rows, in circle order, each row under
``__input__``, its circle, and under the two columns its scenario box names it
by, ``scenario`` (the id) and ``scenario_name``, so a chart can color by
scenario. ``stack_inputs`` writes those rows in an exported notebook, and
``input_rows`` each input's own; ``src/utils/scenarios/stackedInputs.ts`` is
their twin in the browser, and ``stackedInputs.cases.json`` beside it pins
both. A chart's rows carry no geometry: it draws a map from the input's own
dataset, so a GeoDataFrame is read as the table of its other columns, beside a
plain table and whatever its coordinate system.

What an input may be:

- a table: a DataFrame, a GeoDataFrame, a list of records, a dict of columns,
  or a dict of values, which is one row;
- a value: a number, a text, a true or false, or a list of them, each one row
  under ``value``;
- the one layer an Autark node hands on.

Inputs of one kind are stacked, and a column one input lacks is empty in its
rows, which the run says. Anything else is refused with a message naming the
input, so a wiring mistake is told rather than drawn as an odd chart: a table
beside a value, an input with no value, one that carries several tables or an
Autark node's several layers, and a raster.
"""
from __future__ import annotations

SCENARIO_COLUMN = "scenario"
NAME_COLUMN = "scenario_name"
VALUE_COLUMN = "value"
#: The circle a row of a chart's ``inputs`` came in on.
INPUT_COLUMN = "__input__"

#: What the messages name the stacking by.
_INPUTS = 'The dataset "inputs"'

_TABLE = "table"
_GEO = "geo"
_VALUE = "value"
_EMPTY = "empty"

#: How each kind is named in a refusal.
_KIND_WORDS = {_TABLE: "a table", _VALUE: "a value"}


def _label(position: int, name: object) -> str:
    return f"input_{position} ({name})" if name not in (None, "") else f"input_{position}"


def _named_layers(value):
    """``[(name, envelope)]`` for the layers an Autark node hands on together
    (its ``outputs`` envelope, each layer under its ``layerName``), else None."""
    if not (isinstance(value, dict) and value.get("dataType") == "outputs" and isinstance(value.get("data"), list)):
        return None
    items = value["data"]
    if not items or not all(isinstance(item, dict) and isinstance(item.get("layerName"), str) and item["layerName"] for item in items):
        return None
    return [(item["layerName"], item) for item in items]


def _one_layer(label: str, value):
    """The one layer an Autark node hands on, when *value* is its several."""
    layers = _named_layers(value)
    if layers is None:
        return value
    if len(layers) == 1:
        return layers[0][1]
    names = ", ".join(name for name, _ in layers)
    raise ValueError(f"{_INPUTS}: {label} carries {len(layers)} layers ({names}). Connect a node that hands on one layer.")


def _declared_crs(envelope):
    """The CRS a layer's FeatureCollection names (``crs.properties.name``, as
    Autark writes ``urn:ogc:def:crs:EPSG::3395``), or None."""
    data = envelope.get("data")
    crs = data.get("crs") if isinstance(data, dict) else None
    properties = crs.get("properties") if isinstance(crs, dict) else None
    name = properties.get("name") if isinstance(properties, dict) else None
    return name if isinstance(name, str) and name else None


def _unwrap(value):
    """A layer an Autark node handed on reaches Python as Curio's
    ``{dataType, data}`` envelope: read it as the value it holds, in the
    coordinate system its FeatureCollection names."""
    if isinstance(value, dict) and "dataType" in value and "data" in value:
        from utk_curio.sandbox.util.parsers import parseInput

        parsed = parseInput(value)
        if parsed is not None:
            declared = _declared_crs(value)
            if declared and _is_geo(parsed) and parsed.crs is None:
                try:
                    parsed = parsed.set_crs(declared)
                except Exception:  # noqa: BLE001  (an unknown CRS name: the rows are read without one)
                    pass
            return parsed
    return value


def _is_frame(value) -> bool:
    import pandas as pd

    return isinstance(value, pd.DataFrame)


def _is_geo(value) -> bool:
    import geopandas as gpd

    return isinstance(value, gpd.GeoDataFrame)


def _is_raster(value) -> bool:
    return hasattr(value, "read") and hasattr(value, "transform") and hasattr(value, "crs")


def _is_scalar(value) -> bool:
    import pandas as pd

    return value is not None and not isinstance(value, (dict, list, tuple)) and pd.api.types.is_scalar(value)


def _plain(value):
    """A numpy scalar as the Python value it holds."""
    import numpy as np

    return value.item() if isinstance(value, np.generic) else value


def _is_column(value) -> bool:
    import numpy as np
    import pandas as pd

    return isinstance(value, (list, tuple, np.ndarray, pd.Series))


def _rows_of(label: str, value):
    """``(kind, frame)``: the rows *value* adds to the stacked table."""
    import pandas as pd

    value = _unwrap(_one_layer(label, value))
    if value is None:
        raise ValueError(
            f"{_INPUTS}: {label} has no value. Run the node that feeds it, "
            "and check that its code returns its result."
        )
    if isinstance(value, tuple) or (isinstance(value, list) and value and all(_is_frame(v) for v in value)):
        raise ValueError(
            f"{_INPUTS}: {label} carries {len(value)} tables. Connect a node that returns one "
            "table, or pick the table to compare in a node between them."
        )
    if _is_geo(value):
        return _GEO, value.copy()
    if _is_frame(value):
        return _TABLE, value.copy()
    if isinstance(value, pd.Series):
        return _TABLE, value.to_frame(name=value.name if value.name is not None else VALUE_COLUMN)
    if isinstance(value, dict):
        if not value:
            return _EMPTY, pd.DataFrame()
        if all(_is_scalar(v) or v is None for v in value.values()):
            return _TABLE, pd.DataFrame([{k: _plain(v) for k, v in value.items()}])
        if all(_is_column(v) for v in value.values()) and len({len(v) for v in value.values()}) == 1:
            return _TABLE, pd.DataFrame({k: list(v) for k, v in value.items()})
        raise ValueError(
            f"{_INPUTS}: {label} is a dict it cannot read as rows. Return one value per key "
            "(one row), or lists of one length per key (one column each)."
        )
    if isinstance(value, list):
        if not value:
            return _EMPTY, pd.DataFrame()
        if all(isinstance(v, dict) for v in value):
            return _TABLE, pd.DataFrame(value)
        if all(_is_scalar(v) for v in value):
            return _VALUE, pd.DataFrame({VALUE_COLUMN: [_plain(v) for v in value]})
        raise ValueError(
            f"{_INPUTS}: {label} is a list that mixes records and values. Return records "
            "(one dict per row) or values."
        )
    if _is_raster(value):
        raise ValueError(
            f"{_INPUTS}: {label} is a raster. A chart compares tables and values; "
            "compute the numbers to compare from the raster in a node before this one."
        )
    if _is_scalar(value):
        return _VALUE, pd.DataFrame({VALUE_COLUMN: [_plain(value)]})
    raise ValueError(
        f"{_INPUTS}: {label} is a {type(value).__name__}, which it cannot stack. "
        "Connect a table, a value, or a list of them."
    )


def stack_inputs(entries):
    """The rows of a Vega-Lite chart's ``inputs`` dataset: every input's rows,
    in circle order, each with its circle under ``__input__``, its scenario's
    id under ``scenario`` and that scenario's name under ``scenario_name``.

    *entries* lists ``(scenario_id, scenario_name, value)`` per input, in circle
    order: a ``scenario_id`` of ``None`` is an input whose node is in no
    scenario, named by its node. The rows are records ready for JSON: a cell
    an input lacks, or that holds no number, is ``None``. A GeoDataFrame's rows
    leave its geometry out, so it stacks beside a plain table and whatever its
    coordinate system. No inputs make no rows.
    """
    entries = list(entries or [])
    if not entries:
        return []
    stacked = _stacked(entries)
    return [{column: _json_cell(cell) for column, cell in row.items()} for row in stacked.to_dict("records")]


def input_rows(value):
    """The rows one input adds under the rules ``stack_inputs`` stacks by,
    before a scenario names them: the input as a chart reading ``inputs`` reads
    it by itself, as ``input_<k>``. Records ready for JSON, a cell a row lacks
    ``None``, a GeoDataFrame's geometry left out; none when the input cannot be
    read as rows, which ``stack_inputs`` then says."""
    try:
        kind, frame = _rows_of("input_0", value)
    except (TypeError, ValueError):
        return []
    if kind == _GEO:
        frame = _without_geometry(frame)
    return [{column: _json_cell(cell) for column, cell in row.items()} for row in frame.to_dict("records")]


def _without_geometry(frame):
    """A GeoDataFrame's rows as a plain table's: every column but its active
    geometry, whose name is read as ``codec.active_geometry_name`` reads it,
    never raising for a frame that has none."""
    import pandas as pd

    geometry = getattr(frame, "_geometry_column_name", None)
    return pd.DataFrame(frame.drop(columns=[geometry] if geometry in frame.columns else []))


def _json_cell(value):
    """*value* as JSON holds it: a numpy scalar as its Python value, and a
    missing number (NaN, NA, NaT) as ``None``."""
    import numpy as np
    import pandas as pd

    value = _plain(value)
    if isinstance(value, (list, tuple, dict, np.ndarray)):
        return value
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _stacked(entries):
    """The table *entries* stack into, under the rules this module states, each
    row holding the circle it came in on, under ``__input__``."""
    import pandas as pd

    parts = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            raise TypeError(f"{_INPUTS}: entry {position} is not (scenario, name, input).")
        scenario, name, value = entry
        name = "" if name is None else str(name)
        label = _label(position, name)
        kind, frame = _rows_of(label, value)
        if kind == _GEO:
            kind, frame = _TABLE, _without_geometry(frame)
        for column in (SCENARIO_COLUMN, NAME_COLUMN):
            if column in frame.columns:
                raise ValueError(
                    f"{_INPUTS}: {label} already has a column named {column}. "
                    "Rename it in the node that feeds it: the stacked table adds its own."
                )
        if INPUT_COLUMN in frame.columns:
            # The circle is the stacking's own: an input's column of that name gives way.
            frame = frame.drop(columns=[INPUT_COLUMN])
        parts.append({
            "position": position, "label": label, "kind": kind, "frame": frame, "scenario": scenario, "name": name,
        })

    kinds = {part["kind"] for part in parts if part["kind"] != _EMPTY}
    if len(kinds) > 1:
        described = ", ".join(
            f"{part['label']} is {_KIND_WORDS[part['kind']]}" for part in parts if part["kind"] != _EMPTY
        )
        raise ValueError(
            f"{_INPUTS} stacks inputs of one kind, and these differ: {described}. "
            "Connect outcomes of the same kind."
        )

    columns: list = []
    for part in parts:
        for column in part["frame"].columns:
            if column not in columns:
                columns.append(column)

    frames = []
    for part in parts:
        frame = part["frame"]
        if part["kind"] == _EMPTY:
            continue
        missing = [str(c) for c in columns if c not in frame.columns]
        if missing:
            print(f"{_INPUTS}: {part['label']} has no {', '.join(missing)}; those cells are empty in its rows.")
        frame = frame.reset_index(drop=True)
        frame.insert(0, NAME_COLUMN, part["name"])
        frame.insert(0, SCENARIO_COLUMN, part["scenario"])
        frame.insert(0, INPUT_COLUMN, part["position"])
        frames.append(frame)

    if not frames:
        return pd.DataFrame({SCENARIO_COLUMN: [], NAME_COLUMN: []})
    return pd.concat(frames, ignore_index=True, sort=False)
