"""The Compare Scenarios node's stacking step (#662).

The node writes its own code from its inputs: one entry per input circle, in
circle order, holding the scenario's id, its name and the input's value. This
stacks them into one table under two leading columns, ``scenario`` (the id) and
``scenario_name``, so a chart can color by scenario and a later node can group
by it. The node's code calls it as ``curio_stack_scenarios``.

What an input may be:

- a table: a DataFrame, a GeoDataFrame, a list of records, a dict of columns,
  or a dict of values, which is one row;
- a value: a number, a text, a true or false, or a list of them, each one row
  under ``value``;
- one layer of an Autark node's several (a compute step hands on every layer
  of its workspace), the one the node's Layer menu names (``layer``).

Inputs of one kind are stacked, and a column one input lacks is empty in its
rows, which the run says. Anything else is refused with a message naming the
input, so a wiring mistake is told rather than drawn as an odd chart: a table
beside a value, a GeoDataFrame beside a plain table, two coordinate systems, an
input with no value, one that carries several tables, and a raster.
"""
from __future__ import annotations

SCENARIO_COLUMN = "scenario"
NAME_COLUMN = "scenario_name"
VALUE_COLUMN = "value"

_TABLE = "table"
_GEO = "geo"
_VALUE = "value"
_EMPTY = "empty"

#: How each kind is named in a refusal.
_KIND_WORDS = {_TABLE: "a table", _GEO: "a GeoDataFrame", _VALUE: "a value"}


def _label(position: int, name: object) -> str:
    return f"input {position} ({name})" if name not in (None, "") else f"input {position}"


def _named_layers(value):
    """``[(name, envelope)]`` for the layers an Autark node hands on together
    (its ``outputs`` envelope, each layer under its ``layerName``), else None."""
    if not (isinstance(value, dict) and value.get("dataType") == "outputs" and isinstance(value.get("data"), list)):
        return None
    items = value["data"]
    if not items or not all(isinstance(item, dict) and isinstance(item.get("layerName"), str) and item["layerName"] for item in items):
        return None
    return [(item["layerName"], item) for item in items]


def _pick_layer(label: str, value, layer):
    """The one layer of an Autark node's several that the node compares,
    *layer*, named in its Layer menu."""
    layers = _named_layers(value)
    if layers is None:
        return value
    names = ", ".join(name for name, _ in layers)
    if layer not in (None, ""):
        for name, item in layers:
            if name == layer:
                return item
        raise ValueError(f"Compare Scenarios: {label} has no layer {layer}. Its layers are {names}.")
    if len(layers) == 1:
        return layers[0][1]
    raise ValueError(
        f"Compare Scenarios: {label} carries {len(layers)} layers ({names}). "
        "Pick the one to compare in the node's Layer menu."
    )


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


def _rows_of(label: str, value, layer=None):
    """``(kind, frame)``: the rows *value* adds to the stacked table, from its
    layer *layer* when it is an Autark node's several layers."""
    import pandas as pd

    value = _unwrap(_pick_layer(label, value, layer))
    if value is None:
        raise ValueError(
            f"Compare Scenarios: {label} has no value. Run the node that feeds it, "
            "and check that its code returns its result."
        )
    if isinstance(value, tuple) or (isinstance(value, list) and value and all(_is_frame(v) for v in value)):
        raise ValueError(
            f"Compare Scenarios: {label} carries {len(value)} tables. Connect a node that returns one "
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
            f"Compare Scenarios: {label} is a dict it cannot read as rows. Return one value per key "
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
            f"Compare Scenarios: {label} is a list that mixes records and values. Return records "
            "(one dict per row) or values."
        )
    if _is_raster(value):
        raise ValueError(
            f"Compare Scenarios: {label} is a raster. A chart compares tables and values; "
            "compute the numbers to compare from the raster in a node before this one."
        )
    if _is_scalar(value):
        return _VALUE, pd.DataFrame({VALUE_COLUMN: [_plain(value)]})
    raise ValueError(
        f"Compare Scenarios: {label} is a {type(value).__name__}, which it cannot stack. "
        "Connect a table, a value, or a list of them."
    )


def _crs_name(crs) -> str | None:
    if crs is None:
        return None
    try:
        return crs.to_string()
    except Exception:  # noqa: BLE001  (an exotic CRS still has a str)
        return str(crs)


def stack_scenarios(entries, layer=None):
    """One table of every input's rows, each under its scenario.

    *entries* lists ``(scenario_id, scenario_name, value)`` per input, in circle
    order. A ``scenario_id`` of ``None`` is an input whose node is in no
    scenario, named by its node. *layer* names the layer to read from an input
    that is an Autark node's several layers.
    """
    import pandas as pd

    entries = list(entries or [])
    if not entries:
        raise ValueError(
            "Compare Scenarios has no inputs. Connect each scenario's outcome to one of its input circles."
        )

    parts = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, (tuple, list)) or len(entry) != 3:
            raise TypeError(
                f"Compare Scenarios: entry {position} is not (scenario, name, input). "
                "Its code is written for it; connect the inputs again to write it anew."
            )
        scenario, name, value = entry
        name = "" if name is None else str(name)
        label = _label(position, name)
        kind, frame = _rows_of(label, value, layer)
        for column in (SCENARIO_COLUMN, NAME_COLUMN):
            if column in frame.columns:
                raise ValueError(
                    f"Compare Scenarios: {label} already has a column named {column}. "
                    "Rename it in the node that feeds it: the stacked table adds its own."
                )
        parts.append({"label": label, "kind": kind, "frame": frame, "scenario": scenario, "name": name})

    kinds = {part["kind"] for part in parts if part["kind"] != _EMPTY}
    if len(kinds) > 1:
        described = ", ".join(
            f"{part['label']} is {_KIND_WORDS[part['kind']]}" for part in parts if part["kind"] != _EMPTY
        )
        raise ValueError(
            f"Compare Scenarios stacks inputs of one kind, and these differ: {described}. "
            "Connect outcomes of the same kind."
        )

    geo = kinds == {_GEO}
    crs = None
    geometry = None
    if geo:
        geo_parts = [part for part in parts if part["kind"] == _GEO]
        known = [(part["label"], _crs_name(part["frame"].crs)) for part in geo_parts]
        named = [(label, text) for label, text in known if text is not None]
        if len({text for _, text in named}) > 1:
            described = ", ".join(f"{label} is in {text}" for label, text in named)
            raise ValueError(
                f"Compare Scenarios: the inputs use different coordinate systems: {described}. "
                "Reproject them to one in the nodes that feed it."
            )
        geometry = geo_parts[0]["frame"].geometry.name
        crs = next((part["frame"].crs for part in geo_parts if part["frame"].crs is not None), None)
        for label, text in known:
            if text is None and crs is not None:
                print(f"Compare Scenarios: {label} names no coordinate system; its rows are read as {_crs_name(crs)}.")

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
            print(f"Compare Scenarios: {part['label']} has no {', '.join(missing)}; those cells are empty in its rows.")
        if part["kind"] == _GEO and frame.geometry.name != geometry:
            frame = frame.rename_geometry(geometry)
        if part["kind"] == _GEO and frame.crs is None and crs is not None:
            frame = frame.set_crs(crs)
        frame = frame.reset_index(drop=True)
        frame.insert(0, NAME_COLUMN, part["name"])
        frame.insert(0, SCENARIO_COLUMN, part["scenario"])
        frames.append(frame)

    if not frames:
        return pd.DataFrame({SCENARIO_COLUMN: [], NAME_COLUMN: []})
    stacked = pd.concat(frames, ignore_index=True, sort=False)
    if geo:
        import geopandas as gpd

        stacked = gpd.GeoDataFrame(stacked, geometry=geometry, crs=crs)
    return stacked
