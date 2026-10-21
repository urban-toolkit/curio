"""The Map Edits node's step (its type is still ``curio.builtin/edit-features``).

The node's code is its only state: one call of ``curio_map_edits`` with the
node's input, which the node writes from its map and reads back
(``utils/mapEdits/mapEdits.ts``)::

    return curio_map_edits(
        input_0,
        key="building_id",
        remove=[8, 10],
        change={34: {"height": 60}},
    )

- ``key`` is the column that identifies a feature;
- ``layer``, for an input that carries several layers, is the one the edits
  apply to;
- ``remove`` lists the ids of the features taken out;
- ``change`` maps an id to the values written into its features' properties,
  or into its rows' columns for a table: a column the table lacks is made, a
  column of floats stays one, and None is written as a missing value. Neither
  the key nor the geometry can be written.

Features are matched by the value of ``key``, never by their position. Every
feature that holds an id is edited: Autark's buildings repeat ``building_id``
on every part of a building, so an edit by ``building_id`` edits the whole
building. An id no feature holds is reported, and the run goes on. With no
edits, the input is handed on as it came. The output is a new artifact; the
input is never changed.

What the input may be, and what the step hands on:

- the layers an Autark node hands on (its ``outputs`` envelope of
  ``{dataType, data, layerName, layerType}`` layers, one such layer, or the
  ``[{name, type, geojson}]`` records its data section loads): the features
  are edited as GeoJSON, every other feature, property and layer is handed on
  as it came, and the result is the envelope ``persistLayersToBackend`` stores
  for an Autark node (``adapters/node/autkLayerMaterialize.ts``);
- a table (a DataFrame or a GeoDataFrame): the edited table, with its
  ``metadata``;
- several tables, each named by its ``metadata`` as Curio names a layer: the
  same envelope, one layer per table.
"""
from __future__ import annotations

import math

#: Columns a view adds to its own rows, which identify nothing upstream. A row's
#: position is not an id either: it changes when rows are removed upstream.
#: Kept in sync with ``VIEW_COLUMNS`` in ``utils/references/selectionTags.ts``.
_VIEW_COLUMNS = frozenset({"__row_index__", "__input__", "_vgsid_", "interacted", "linked"})

#: The property a feature's geometry would clash with once it is a table's row.
_GEOMETRY = "geometry"

_NAME = "Map Edits"


class _Layer:
    """One layer of the input: its name and type, and its GeoJSON or its table."""

    def __init__(self, name=None, layer_type=None, fc=None, frame=None, envelope=None):
        self.name = name
        self.layer_type = layer_type
        self.fc = fc
        self.frame = frame
        #: The envelope it came in, handed on as it is when it is not edited.
        self.envelope = envelope

    @property
    def label(self) -> str:
        return f"layer {self.name}" if self.name else "the input"


def _is_frame(value) -> bool:
    import pandas as pd

    return isinstance(value, pd.DataFrame)


def _is_fc(value) -> bool:
    return isinstance(value, dict) and value.get("type") == "FeatureCollection" and isinstance(value.get("features"), list)


def _frame_name(frame):
    meta = getattr(frame, "metadata", None)
    if isinstance(meta, dict):
        return meta.get("name"), meta.get("layerType")
    return None, None


def _layer_of_envelope(item):
    """The layer an Autark envelope holds, or None for one this step cannot edit."""
    if not isinstance(item, dict) or item.get("dataType") != "geodataframe" or not _is_fc(item.get("data")):
        return None
    name = item.get("layerName") if isinstance(item.get("layerName"), str) and item.get("layerName") else None
    return _Layer(name=name, layer_type=item.get("layerType"), fc=item["data"], envelope=item)


def _layers_of(value):
    """``(layers, single_table)``: the layers of *value*, and whether it is one
    table, which is handed on as a table."""
    if _is_frame(value):
        name, layer_type = _frame_name(value)
        return [_Layer(name=name, layer_type=layer_type, frame=value)], True
    if isinstance(value, dict) and value.get("dataType") == "outputs" and isinstance(value.get("data"), list):
        return [_layer_of_envelope(item) or _Layer(envelope=item) for item in value["data"]], False
    if isinstance(value, dict) and value.get("dataType") == "geodataframe":
        layer = _layer_of_envelope(value)
        if layer is not None:
            return [layer], False
    if isinstance(value, (list, tuple)) and value:
        if all(isinstance(item, dict) and _is_fc(item.get("geojson")) for item in value):
            return [
                _Layer(name=item.get("name") or None, layer_type=item.get("type"), fc=item["geojson"])
                for item in value
            ], False
        if all(_is_frame(item) for item in value):
            layers = []
            for item in value:
                name, layer_type = _frame_name(item)
                layers.append(_Layer(name=name, layer_type=layer_type, frame=item))
            return layers, False
        if all(isinstance(item, dict) and item.get("dataType") for item in value):
            return [_layer_of_envelope(item) or _Layer(envelope=item) for item in value], False
    raise ValueError(
        f"{_NAME} edits a layer or a table, and its input is a {type(value).__name__}. "
        "Connect a node that hands on layers or a table."
    )


def _editable(layer: _Layer) -> bool:
    return layer.fc is not None or layer.frame is not None


def _pick_layer(layers, layer_name):
    """The layer the edits apply to: *layer_name*, or the only one there is."""
    editable = [layer for layer in layers if _editable(layer)]
    named = [layer.name for layer in editable if layer.name]
    if layer_name not in (None, ""):
        for layer in editable:
            if layer.name == layer_name:
                return layer
        if len(editable) == 1 and not editable[0].name:
            # One layer that lost its name on the way (a table saved without
            # it): the one the node's map showed.
            return editable[0]
        listed = ", ".join(named) if named else "none with a name"
        raise ValueError(f"{_NAME}: the input has no layer {layer_name}. Its layers are {listed}.")
    if len(editable) == 1:
        return editable[0]
    if not editable:
        raise ValueError(f"{_NAME}: the input carries no layer it can edit.")
    if len(named) < len(editable):
        raise ValueError(
            f"{_NAME}: the input carries {len(editable)} layers, and not all of them have a name. "
            "Connect the node that loads them, or a node that hands on one layer."
        )
    raise ValueError(
        f"{_NAME}: the input carries {len(editable)} layers ({', '.join(named)}). "
        "Pick the one to edit in the node's Layer menu."
    )


def _id_key(value):
    """What an id is compared as: a number by its value (12 and 12.0 are one
    id), a text as it is. None for a missing value."""
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:  # pragma: no cover  (numpy ships with the sandbox)
        pass
    if value is None:
        return None
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, int):
        return ("n", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return ("n", int(value)) if value.is_integer() else ("n", value)
    if isinstance(value, str):
        return ("s", value)
    return ("s", str(value))


def _is_id(value) -> bool:
    """Whether *value* can name a feature: a text, or a finite number."""
    if isinstance(value, str):
        return True
    key = _id_key(value)
    return key is not None and key[0] == "n"


def _shown(ids) -> str:
    return ", ".join(str(i) for i in ids)


def _checked_key(key):
    if key in (None, ""):
        raise ValueError(
            f"{_NAME} names no column that identifies a feature. Pick one in the node, such as osm_id or building_id."
        )
    if not isinstance(key, str):
        raise ValueError(f"{_NAME}: key names a column, such as osm_id or building_id, and it is {key!r}.")
    if key in _VIEW_COLUMNS:
        raise ValueError(
            f"{_NAME}: {key} is a row's place in a view, which changes when rows change. "
            "Pick a column that identifies a feature, such as osm_id or building_id."
        )
    return key


def _checked_remove(remove):
    """The ids *remove* lists. The node writes it from its map; code edited by
    hand is checked as well."""
    if remove is None:
        return []
    if not isinstance(remove, (list, tuple, set, frozenset)):
        raise ValueError(f"{_NAME}: remove lists the ids to take out, such as [8, 10], and it is a {type(remove).__name__}.")
    for value in remove:
        if not _is_id(value):
            raise ValueError(f"{_NAME}: remove holds {value!r}, which is not an id. An id is a number or a text.")
    return list(remove)


def _checked_change(change):
    """``[(id, values)]``: what *change* writes, one entry per id that writes
    something."""
    if change is None:
        return []
    if not isinstance(change, dict):
        raise ValueError(
            f"{_NAME}: change maps each id to the values it writes, such as {{34: {{\"height\": 60}}}}, "
            f"and it is a {type(change).__name__}."
        )
    checked = []
    for value, values in change.items():
        if not _is_id(value):
            raise ValueError(f"{_NAME}: change names {value!r}, which is not an id. An id is a number or a text.")
        if not isinstance(values, dict):
            raise ValueError(
                f"{_NAME}: change gives {value!r} {values!r}, which is not the values to write, such as {{\"height\": 60}}."
            )
        for column in values:
            if not isinstance(column, str) or column == "":
                raise ValueError(f"{_NAME}: change writes {column!r} on {value!r}, which is not a column's name.")
        if values:
            checked.append((value, values))
    return checked


def _report_unknown(label, key, ids, known, verb) -> None:
    unknown = [i for i in ids if _id_key(i) not in known]
    if unknown:
        print(f"{_NAME}: {label} has no feature with {key} {_shown(unknown)} to {verb}; the run goes on.")


def _properties(feature) -> dict:
    return (feature.get("properties") or {}) if isinstance(feature, dict) else {}


def _refuse_geometry(column, layer: _Layer) -> None:
    raise ValueError(f"{_NAME}: {column} is the geometry of {layer.label}; a value cannot be set on it.")


def _edit_fc(layer: _Layer, key, remove, change):
    """The layer's FeatureCollection with the edits applied, and what changed."""
    features = layer.fc["features"]
    ids = [_id_key(_properties(feature).get(key)) for feature in features]
    known = {i for i in ids if i is not None}
    if not known and features:
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Pick a column its features have.")
    gone = {_id_key(i) for i in remove}
    written = {}
    for value, values in change:
        if _GEOMETRY in values:
            _refuse_geometry(_GEOMETRY, layer)
        written.setdefault(_id_key(value), {}).update(values)
    _report_unknown(layer.label, key, remove, known, "remove")
    _report_unknown(layer.label, key, [value for value, _values in change], known, "change")
    kept, removed, changed = [], 0, 0
    for feature, feature_id in zip(features, ids):
        if feature_id in gone:
            removed += 1
        elif feature_id in written:
            kept.append({**feature, "properties": {**_properties(feature), **written[feature_id]}})
            changed += 1
        else:
            kept.append(feature)
    return {**layer.fc, "features": kept}, {"removed": removed, "changed": changed}


def _write_column(out, column, positions, values):
    """*values* written into *column* of *out* at the row *positions*; the
    column is made when *out* lacks it. A column of floats stays one."""
    import pandas as pd

    present = column in out.columns
    if present and pd.api.types.is_float_dtype(out[column]):
        values = [float(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in values]
    current = out[column].tolist() if present else [None] * len(out)
    for position, value in zip(positions, values):
        current[position] = value
    out[column] = pd.Series(current, index=out.index)


def _edit_frame(layer: _Layer, key, remove, change):
    """The layer's table with the edits applied, and what changed."""
    import numpy as np

    frame = layer.frame
    if key not in frame.columns:
        listed = ", ".join(str(c) for c in list(frame.columns)[:8])
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Its columns are {listed}.")
    from utk_curio.sandbox.util.codec import active_geometry_name, is_geospatial_frame

    geometry = active_geometry_name(frame) if is_geospatial_frame(frame) else None
    for _value, values in change:
        if geometry is not None and geometry in values:
            _refuse_geometry(geometry, layer)
    ids = [_id_key(value) for value in frame[key].tolist()]
    known = {i for i in ids if i is not None}
    _report_unknown(layer.label, key, remove, known, "remove")
    _report_unknown(layer.label, key, [value for value, _values in change], known, "change")
    gone = {_id_key(i) for i in remove}
    kept = np.array([feature_id not in gone for feature_id in ids], dtype=bool)
    rows = {}
    for position, feature_id in enumerate(ids):
        if kept[position] and feature_id is not None:
            rows.setdefault(feature_id, []).append(position)
    writes, changed = {}, set()
    for value, values in change:
        for position in rows.get(_id_key(value), []):
            changed.add(position)
            for column, written in values.items():
                positions, column_values = writes.setdefault(column, ([], []))
                positions.append(position)
                column_values.append(written)
    out = frame.copy()
    for column, (positions, column_values) in writes.items():
        _write_column(out, column, positions, column_values)
    result = out[kept]
    meta = getattr(frame, "metadata", None)
    if isinstance(meta, dict):
        result.__dict__["metadata"] = dict(meta)
    return result, {"removed": int((~kept).sum()), "changed": len(changed)}


def _summary(layer: _Layer, key, counts) -> str:
    parts = []
    if counts["removed"]:
        parts.append(f"{counts['removed']} removed")
    if counts["changed"]:
        parts.append(f"{counts['changed']} changed")
    what = ", ".join(parts) if parts else "none changed"
    return f"{_NAME}: {layer.label}, features matched on {key}: {what}."


def _envelope(layer: _Layer, edited: bool):
    """A layer as the envelope an Autark node hands it on in: the one it came
    in when it was not edited."""
    if not edited and layer.envelope is not None:
        return layer.envelope
    if layer.fc is not None:
        if layer.envelope is not None:
            return {**layer.envelope, "data": layer.fc}
        out = {"dataType": "geodataframe", "data": layer.fc}
        if layer.name:
            out["layerName"] = layer.name
        if layer.layer_type:
            out["layerType"] = layer.layer_type
        return out
    if layer.frame is not None:
        from utk_curio.sandbox.util.parsers import parseOutput

        out = parseOutput(layer.frame)
        out.pop("schema", None)
        if layer.name:
            out["layerName"] = layer.name
        if layer.layer_type:
            out["layerType"] = layer.layer_type
        return out
    return layer.envelope


def map_edits(value, key=None, remove=(), change=None, layer=None):
    """The input with the features whose *key* is one of *remove* taken out of
    *layer*, and the values *change* gives an id written into its features.
    See the module's docstring."""
    if value is None:
        raise ValueError(
            f"{_NAME} has no input. Run the node that feeds it, and check that its code returns its result."
        )
    remove = _checked_remove(remove)
    change = _checked_change(change)
    if not remove and not change:
        print(f"{_NAME}: no edits yet; the input is handed on as it came.")
        return value
    key = _checked_key(key)
    for value_id, values in change:
        if key in values:
            raise ValueError(f"{_NAME}: change writes {key} on {value_id!r}, and {key} identifies the features; it cannot change.")
    layers, single_table = _layers_of(value)
    target = _pick_layer(layers, layer)
    if target.fc is not None:
        target.fc, counts = _edit_fc(target, key, remove, change)
    else:
        target.frame, counts = _edit_frame(target, key, remove, change)
    print(_summary(target, key, counts))
    if single_table:
        return target.frame
    envelopes = [_envelope(item, item is target) for item in layers]
    if len(envelopes) == 1:
        return envelopes[0]
    return {"dataType": "outputs", "data": envelopes}
