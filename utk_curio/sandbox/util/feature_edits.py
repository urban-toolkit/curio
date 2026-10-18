"""The Interaction node's step (#662; its type is still
``curio.builtin/edit-features``).

The node keeps a log of edits, each made on features picked on its map or by
a condition, and writes its code from that log: one call of
``curio_edit_features`` with the node's input, the edits in the order they
were made, the column that identifies a feature (``key``) and, for an input
that carries several layers, the layer they apply to. The output is a new
artifact; the input is never changed.

An edit is a dict with an ``op``, the features it applies to and, for the ops
that write, a ``column`` and a ``value``:

- ``remove`` drops the features;
- ``restore`` puts them back as the input has them, undoing the edits before
  it;
- ``set`` writes ``value`` into ``column``;
- ``scale`` multiplies the number in ``column`` by ``value``, and ``offset``
  adds ``value`` to it; a feature whose ``column`` holds no number is left as
  it is;
- ``expr`` writes into ``column`` what the expression ``value`` makes of the
  feature, such as ``levels * 3.2`` (``edit_expr``).

The features are those whose ``key`` is one of ``ids`` or, in place of
``ids``, those the expression ``where`` holds for, read as the edits before
have left them (``height > 100 and levels >= 30``); a restore reads them as
the input has them. An edit with ``"enabled": False`` stays in the log and is
skipped; ``label`` names an edit for people and changes nothing.

Features are matched by the value of ``key``, never by their position. Every
feature that holds an id is edited: Autark's buildings repeat ``building_id``
on every part of a building, so an edit by ``building_id`` edits the whole
building. An id no feature holds is reported, and the run goes on. With no
edits, the input is handed on as it came.

What the input may be, and what the step hands on:

- the layers an Autark node hands on (its ``outputs`` envelope of
  ``{dataType, data, layerName, layerType}`` layers, one such layer, or the
  ``[{name, type, geojson}]`` records its data section loads): the features
  are edited as GeoJSON, every other feature, property and layer is handed on
  as it came, and the result is the envelope ``persistLayersToBackend`` stores
  for an Autark node (``adapters/node/autkLayerMaterialize.ts``);
- a table (a DataFrame or a GeoDataFrame): the edited table;
- several tables, each named by its ``metadata`` as Curio names a layer: the
  same envelope, one layer per table.
"""
from __future__ import annotations

import math

from utk_curio.sandbox.util import edit_expr

REMOVE = "remove"
SET = "set"
RESTORE = "restore"
SCALE = "scale"
OFFSET = "offset"
EXPR = "expr"
#: In the order of the op enum in ``docs/schemas/trill.v1.json``.
OPS = (REMOVE, SET, RESTORE, SCALE, OFFSET, EXPR)
#: The ops that write a column.
WRITES = (SET, SCALE, OFFSET, EXPR)

#: Columns a view adds to its own rows, which identify nothing upstream. A row's
#: position is not an id either: it changes when rows are removed upstream.
#: Kept in sync with ``VIEW_COLUMNS`` in ``utils/references/selectionTags.ts``.
_VIEW_COLUMNS = frozenset({"__row_index__", "__input__", "_vgsid_", "interacted", "linked"})

_NAME = "Interaction"


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
    if value is None:
        raise ValueError(
            f"{_NAME} has no input. Run the node that feeds it, and check that its code returns its result."
        )
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


def _shown(ids) -> str:
    return ", ".join(str(i) for i in ids)


def _checked_edits(edits, key):
    if key in (None, ""):
        raise ValueError(
            f"{_NAME} names no column that identifies a feature. Pick one in the node, such as osm_id or building_id."
        )
    if key in _VIEW_COLUMNS:
        raise ValueError(
            f"{_NAME}: {key} is a row's place in a view, which changes when rows change. "
            "Pick a column that identifies a feature, such as osm_id or building_id."
        )
    checked = []
    for position, edit in enumerate(edits or []):
        if not isinstance(edit, dict) or edit.get("op") not in OPS:
            raise ValueError(
                f"{_NAME}: edit {position} is not a remove, set, restore, scale, offset or expr. "
                "The node writes its code from its edit log; edit the log in the node."
            )
        if edit.get("enabled") is False:
            continue
        op = edit["op"]
        ids, where = edit.get("ids"), edit.get("where")
        by_ids = isinstance(ids, list) and len(ids) > 0
        by_where = isinstance(where, str) and where.strip() != ""
        if by_ids and by_where:
            raise ValueError(f"{_NAME}: edit {position} names its features both by ids and by a condition; it takes one.")
        if not (by_ids or by_where):
            raise ValueError(f"{_NAME}: edit {position} names no features: it needs their ids or a where condition.")
        if op in WRITES and (not isinstance(edit.get("column"), str) or not edit["column"]):
            raise ValueError(f"{_NAME}: edit {position} writes a value but names no column.")
        if op in (SCALE, OFFSET) and edit_expr.number(edit.get("value")) is None:
            verb = "scales" if op == SCALE else "offsets"
            raise ValueError(
                f"{_NAME}: edit {position} {verb} {edit['column']} by {edit.get('value')!r}, which is not a number."
            )
        if op == EXPR and not isinstance(edit.get("value"), str):
            raise ValueError(
                f"{_NAME}: edit {position} computes {edit['column']} from {edit.get('value')!r}, which is not an expression."
            )
        parsed = dict(edit)
        try:
            if by_where:
                parsed["_where"] = edit_expr.parse(where)
            if op == EXPR:
                parsed["_expr"] = edit_expr.parse(edit["value"])
        except edit_expr.ExprError as exc:
            what = f"the condition {where!r}" if by_where and "_where" not in parsed else f"the expression {edit['value']!r}"
            raise ValueError(f"{_NAME}: edit {position}: {what} is not one: {exc}.") from None
        checked.append(parsed)
    return checked


def _written(edit, properties):
    """``(True, value)``: what a writing *edit* puts into its column of a
    feature whose properties are *properties*, or ``(False, None)`` when it
    leaves the feature alone (a number edit on a column with no number)."""
    op = edit["op"]
    if op == SET:
        return True, edit.get("value")
    if op == EXPR:
        return True, edit_expr.evaluate(edit["_expr"], properties)
    current = edit_expr.number(properties.get(edit["column"]))
    if current is None:
        return False, None
    by = edit_expr.number(edit["value"])
    return True, edit_expr.result(current * by if op == SCALE else current + by)


def _where_holds(edit, properties) -> bool:
    return edit_expr.truthy(edit_expr.evaluate(edit["_where"], properties))


def _report_unknown(label, key, op, ids, known):
    unknown = [i for i in ids if _id_key(i) not in known]
    if unknown:
        noun = "feature" if len(unknown) == 1 else "features"
        print(f"{_NAME}: {label} has no feature with {key} {_shown(unknown)}; the {op} skips {'it' if len(unknown) == 1 else 'them'}.")
        return len(unknown), noun
    return 0, None


def _properties(feature) -> dict:
    return (feature.get("properties") or {}) if isinstance(feature, dict) else {}


def _edit_fc(layer: _Layer, edits, key):
    """The layer's FeatureCollection with *edits* applied, and what changed."""
    features = layer.fc["features"]
    ids = [_id_key((feature or {}).get("properties", {}).get(key) if isinstance(feature, dict) else None) for feature in features]
    known = {i for i in ids if i is not None}
    if not known and features:
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Pick a column its features have.")
    state = list(features)
    counts = {REMOVE: set(), SET: set(), RESTORE: set()}
    for edit in edits:
        op = edit["op"]
        if "_where" in edit:
            # A condition reads the features as the edits before left them; a
            # restore reads them as the input has them, removed ones included.
            source = features if op == RESTORE else state
            targets = [i for i, feature in enumerate(source) if feature is not None and _where_holds(edit, _properties(feature))]
        else:
            wanted = {_id_key(i) for i in edit["ids"]}
            _report_unknown(layer.label, key, op, edit["ids"], known)
            targets = [i for i, feature_id in enumerate(ids) if feature_id in wanted]
        for index in targets:
            if op == REMOVE:
                if state[index] is not None:
                    state[index] = None
                    counts[REMOVE].add(index)
            elif op == RESTORE:
                if state[index] is not features[index]:
                    state[index] = features[index]
                    counts[RESTORE].add(index)
                    counts[REMOVE].discard(index)
                    counts[SET].discard(index)
            else:
                current = state[index]
                if current is None:
                    continue
                writes, value = _written(edit, _properties(current))
                if not writes:
                    continue
                properties = dict(current.get("properties") or {})
                properties[edit["column"]] = value
                state[index] = {**current, "properties": properties}
                counts[SET].add(index)
    fc = {**layer.fc, "features": [feature for feature in state if feature is not None]}
    return fc, {op: len(rows) for op, rows in counts.items()}


def _records(table, geometry):
    """One dict per row of *table*, every column but its geometry, for a
    condition or an expression to read."""
    columns = [column for column in table.columns if column != geometry]
    return table[columns].to_dict("records")


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


def _edit_frame(layer: _Layer, edits, key):
    """The layer's table with *edits* applied, and what changed."""
    import pandas as pd

    frame = layer.frame
    if key not in frame.columns:
        listed = ", ".join(str(c) for c in list(frame.columns)[:8])
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Its columns are {listed}.")
    from utk_curio.sandbox.util.codec import active_geometry_name, is_geospatial_frame

    geometry = active_geometry_name(frame) if is_geospatial_frame(frame) else None
    ids = frame[key].map(_id_key)
    known = {i for i in ids if i is not None}
    out = frame.copy()
    kept = pd.Series(True, index=frame.index)
    changed = pd.Series(False, index=frame.index)
    removed = pd.Series(False, index=frame.index)
    restored = pd.Series(False, index=frame.index)
    for edit in edits:
        op = edit["op"]
        if "_where" in edit:
            # Read as the edits before left the rows; a restore reads the input's.
            rows = _records(frame if op == RESTORE else out, geometry)
            holds = [_where_holds(edit, row) for row in rows]
            mask = pd.Series(holds, index=frame.index, dtype=bool)
            if op != RESTORE:
                mask &= kept
        else:
            wanted = {_id_key(i) for i in edit["ids"]}
            _report_unknown(layer.label, key, op, edit["ids"], known)
            mask = ids.isin(wanted)
        if op in WRITES and edit["column"] == geometry:
            raise ValueError(f"{_NAME}: {geometry} is the geometry of {layer.label}; a value cannot be set on it.")
        if op == REMOVE:
            removed |= mask & kept
            kept &= ~mask
        elif op == SET:
            column = edit["column"]
            target = mask & kept
            if column not in out.columns:
                out[column] = pd.Series([None] * len(out), index=out.index, dtype=object)
            out[column] = out[column].where(~target, edit.get("value"))
            changed |= target
        elif op in (SCALE, OFFSET, EXPR):
            target = (mask & kept).to_numpy()
            rows = _records(out, geometry)
            positions, values = [], []
            for position in target.nonzero()[0]:
                writes, value = _written(edit, rows[position])
                if writes:
                    positions.append(int(position))
                    values.append(value)
            if positions:
                _write_column(out, edit["column"], positions, values)
                wrote = pd.Series(False, index=frame.index)
                wrote.iloc[positions] = True
                changed |= wrote
        else:
            back = mask & (~kept | changed)
            for column in out.columns:
                if column == geometry:
                    continue
                source = frame[column] if column in frame.columns else pd.Series([None] * len(frame), index=frame.index, dtype=object)
                out[column] = out[column].where(~mask, source)
            restored |= back
            removed &= ~mask
            changed &= ~mask
            kept |= mask
    result = out[kept]
    meta = getattr(frame, "metadata", None)
    if isinstance(meta, dict):
        result.__dict__["metadata"] = dict(meta)
    return result, {REMOVE: int(removed.sum()), SET: int(changed.sum()), RESTORE: int(restored.sum())}


def _summary(layer: _Layer, key, counts) -> str:
    parts = []
    if counts[REMOVE]:
        parts.append(f"{counts[REMOVE]} removed")
    if counts[SET]:
        parts.append(f"{counts[SET]} changed")
    if counts[RESTORE]:
        parts.append(f"{counts[RESTORE]} restored")
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


def edit_features(value, edits, key=None, layer=None):
    """The input with *edits* applied to the features of *layer* each edit
    names, by *key* or by a condition. See the module's docstring."""
    if value is None:
        raise ValueError(
            f"{_NAME} has no input. Run the node that feeds it, and check that its code returns its result."
        )
    if not edits:
        print(f"{_NAME}: no edits yet; the input is handed on as it came.")
        return value
    edits = _checked_edits(edits, key)
    if not edits:
        print(f"{_NAME}: every edit is switched off; the input is handed on as it came.")
        return value
    layers, single_table = _layers_of(value)
    target = _pick_layer(layers, layer)
    if target.fc is not None:
        target.fc, counts = _edit_fc(target, edits, key)
    else:
        target.frame, counts = _edit_frame(target, edits, key)
    print(_summary(target, key, counts))
    if single_table:
        return target.frame
    envelopes = [_envelope(item, item is target) for item in layers]
    if len(envelopes) == 1:
        return envelopes[0]
    return {"dataType": "outputs", "data": envelopes}
