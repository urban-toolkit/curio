"""The Interaction node's step (#662; it was the Edit Features node).

The node keeps a list of edits, each made on features picked on its map, and
writes its code from that list: one call of ``curio_edit_features`` with the
node's input, the edits in the order they were made, the column that
identifies a feature (``key``) and, for an input that carries several layers,
the layer they apply to. The output is a new artifact; the input is never
changed.

An edit is a dict with an ``op``, the features it applies to, and, for some
ops, a ``column`` and a ``value``:

- ``remove`` drops the features;
- ``restore`` puts them back as the input has them, undoing the edits before;
- ``set`` writes ``value`` into ``column``;
- ``scale`` multiplies the number in ``column`` by ``value``;
- ``offset`` adds ``value`` to the number in ``column``;
- ``expr`` writes into ``column`` what the expression ``value`` makes of the
  feature, e.g. ``levels * 3.2`` (``edit_expr``).

The features are those whose ``key`` is one of ``ids``, or, in place of
``ids``, those a ``where`` condition holds for, as the edits before have left
them (``height > 100 and levels >= 30``; a restore reads the input's). An
edit with ``"enabled": False`` is kept in the list and skipped; ``label`` names
it for people. A number edit skips a feature whose ``column`` holds no number.

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
                f"{_NAME}: edit {position} is not one of {', '.join(OPS)}. "
                "The node writes its code from its edit list; edit the list in the node."
            )
        if edit.get("enabled") is False:
            continue
        ids, where = edit.get("ids"), edit.get("where")
        has_ids = isinstance(ids, list) and len(ids) > 0
        has_where = isinstance(where, str) and where.strip() != ""
        if has_ids == has_where:
            raise ValueError(f"{_NAME}: edit {position} needs either the features' ids or a where condition, not both.")
        op = edit["op"]
        if op in WRITES and (not isinstance(edit.get("column"), str) or not edit["column"]):
            raise ValueError(f"{_NAME}: edit {position} writes a value but names no column.")
        if op in (SCALE, OFFSET) and edit_expr._number(edit.get("value")) is None:
            raise ValueError(f"{_NAME}: edit {position} {op}s {edit['column']} by {edit.get('value')!r}, which is not a number.")
        parsed = dict(edit)
        try:
            if has_where:
                parsed["_where"] = edit_expr.parse(where)
            if op == EXPR:
                parsed["_expr"] = edit_expr.parse(str(edit.get("value") or ""))
        except edit_expr.ExprError as exc:
            raise ValueError(f"{_NAME}: edit {position}: {exc}.") from None
        checked.append(parsed)
    return checked


def _report_unknown(label, key, op, ids, known):
    unknown = [i for i in ids if _id_key(i) not in known]
    if unknown:
        noun = "feature" if len(unknown) == 1 else "features"
        print(f"{_NAME}: {label} has no feature with {key} {_shown(unknown)}; the {op} skips {'it' if len(unknown) == 1 else 'them'}.")
        return len(unknown), noun
    return 0, None


def _apply(rows, ids, edits, key, label):
    """*edits* over the property dicts *rows* (one per feature, the input's):
    the rows after them (None for a removed feature, the input's own dict for
    an untouched one), what changed, and the columns written."""
    known = {i for i in ids if i is not None}
    state = list(rows)
    counts = {REMOVE: set(), SET: set(), RESTORE: set()}
    written = []
    for edit in edits:
        op = edit["op"]
        if "_where" in edit:
            source = rows if op == RESTORE else state
            targets = [
                i for i, row in enumerate(source)
                if row is not None and edit_expr.truthy(edit_expr.evaluate(edit["_where"], row))
            ]
        else:
            wanted = {_id_key(i) for i in edit["ids"]}
            _report_unknown(label, key, op, edit["ids"], known)
            targets = [i for i, feature_id in enumerate(ids) if feature_id in wanted]
        for index in targets:
            if op == REMOVE:
                if state[index] is not None:
                    state[index] = None
                    counts[REMOVE].add(index)
                continue
            if op == RESTORE:
                if state[index] is not rows[index]:
                    state[index] = rows[index]
                    counts[RESTORE].add(index)
                    counts[REMOVE].discard(index)
                    counts[SET].discard(index)
                continue
            current = state[index]
            if current is None:
                continue
            column = edit["column"]
            if op == SET:
                value = edit.get("value")
            elif op == EXPR:
                value = edit_expr.evaluate(edit["_expr"], current)
            else:
                number = edit_expr._number(current.get(column))
                if number is None:
                    continue
                by = edit_expr._number(edit["value"])
                value = edit_expr._out(number * by if op == SCALE else number + by)
            updated = dict(current)
            updated[column] = value
            state[index] = updated
            counts[SET].add(index)
            if column not in written:
                written.append(column)
    return state, {op: len(found) for op, found in counts.items()}, written


def _edit_fc(layer: _Layer, edits, key):
    """The layer's FeatureCollection with *edits* applied, and what changed."""
    features = layer.fc["features"]
    rows = [dict((feature or {}).get("properties") or {}) if isinstance(feature, dict) else {} for feature in features]
    ids = [_id_key(row.get(key)) for row in rows]
    if not any(i is not None for i in ids) and features:
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Pick a column its features have.")
    state, counts, _ = _apply(rows, ids, edits, key, layer.label)
    out = []
    for feature, original, row in zip(features, rows, state):
        if row is None:
            continue
        out.append(feature if row is original else {**feature, "properties": row})
    return {**layer.fc, "features": out}, counts


def _edit_frame(layer: _Layer, edits, key):
    """The layer's table with *edits* applied, and what changed."""
    import pandas as pd

    frame = layer.frame
    if key not in frame.columns:
        listed = ", ".join(str(c) for c in list(frame.columns)[:8])
        raise ValueError(f"{_NAME}: {layer.label} has no column {key}. Its columns are {listed}.")
    from utk_curio.sandbox.util.codec import active_geometry_name, is_geospatial_frame

    geometry = active_geometry_name(frame) if is_geospatial_frame(frame) else None
    for edit in edits:
        if edit.get("column") is not None and edit.get("column") == geometry and edit["op"] in WRITES:
            raise ValueError(f"{_NAME}: {geometry} is the geometry of {layer.label}; a value cannot be set on it.")
    plain = frame.drop(columns=[geometry]) if geometry else frame
    rows = [{k: edit_expr._plain(v) for k, v in row.items()} for row in plain.to_dict("records")]
    ids = [_id_key(row.get(key)) for row in rows]
    state, counts, written = _apply(rows, ids, edits, key, layer.label)
    kept = pd.Series([row is not None for row in state], index=frame.index)
    out = frame.copy()
    for column in written:
        values = [row.get(column) if row is not None else None for row in state]
        out[column] = pd.Series(values, index=frame.index, dtype=object)
        if column in frame.columns and pd.api.types.is_numeric_dtype(frame[column]):
            converted = pd.to_numeric(out[column], errors="coerce")
            if converted.notna().sum() == out[column].notna().sum():
                # A float column stays one, though 50.0 was written as 50.
                if pd.api.types.is_float_dtype(frame[column]):
                    converted = converted.astype(frame[column].dtype)
                out[column] = converted
    result = out[kept]
    # A table numbered 0, 1, 2, ... stays so: a step after this one that reads
    # rows by position (as SCOUT's rasterizer does) must not meet the gaps the
    # removed rows leave.
    if isinstance(frame.index, pd.RangeIndex) and frame.index.start == 0 and frame.index.step == 1:
        result = result.reset_index(drop=True)
    meta = getattr(frame, "metadata", None)
    if isinstance(meta, dict):
        result.__dict__["metadata"] = dict(meta)
    return result, counts


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
    """The input with *edits* applied to the features of *layer* whose *key*
    is one of each edit's ids. See the module's docstring."""
    if value is None:
        raise ValueError(
            f"{_NAME} has no input. Run the node that feeds it, and check that its code returns its result."
        )
    if not edits:
        print(f"{_NAME}: no edits yet; the input is handed on as it came.")
        return value
    edits = _checked_edits(edits, key)
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
