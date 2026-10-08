"""A layer chip in Python code (#662): ``[!! input_0:table_osm_roads !!]``
reads one layer of the several an input carries, an Autark node's tables.

The browser and the headless runner write the chip as a call to this helper,
``curio_layer(input_0, "table_osm_roads", 0)`` (``input_1`` for circle 1; the
last argument is the input's circle). The node's code
calls it by name, in process and under isolation. The JavaScript twin is
``curio_layer`` in ``js_wrapper.mjs``.

A layer is found by its name, as an Autark spec finds it: the table name
exactly (``table_osm_roads``, not ``roads``). What an input may carry:

- the layer array an Autark node with a data section hands on: a list of
  ``{name, type, geojson}``, its features in the coordinate system the
  FeatureCollection names; the layer comes back as a GeoDataFrame in it;
- the layers an Autark compute step hands on together, an ``outputs``
  envelope of ``{dataType, data, layerName}`` layers, or one such layer;
- frames that carry their name in ``metadata`` (``gdf.metadata = {"name":
  "roads"}``), on their own or in a list or tuple.

The layer keeps its name and type in ``metadata``. An input that carries
exactly one frame with no layer name (a GeoDataFrame a Python node returns, or
one Data Loading reads) is that layer, whatever name the chip gives. Otherwise
a name the input does not have fails the node with a message naming the input
and the layers it has.
"""
from __future__ import annotations

#: What a layer chip in Python or JavaScript code calls. Kept in sync with
#: ``LAYER_HELPER`` in ``execution/code_references.py`` and ``codeReferences.ts``.
LAYER_HELPER = "curio_layer"


def missing_layer_message(slot, layer: str, names) -> str:
    """Why input *slot* has no layer *layer*, naming the layers it has.
    Kept in sync with ``missing_layer_message`` in
    ``execution/code_references.py`` and ``missingLayerMessage`` in
    ``codeReferences.ts`` and ``js_wrapper.mjs``."""
    names = list(names)
    has = f"Its layers are {', '.join(names)}." if names else "It carries no named layers."
    return f"[!! input_{slot}:{layer} !!]: input_{slot} has no layer {layer}. {has}"


def _items(value) -> list:
    if isinstance(value, dict) and value.get("dataType") == "outputs" and isinstance(value.get("data"), list):
        return list(value["data"])
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _is_record(item) -> bool:
    return isinstance(item, dict) and isinstance(item.get("geojson"), dict) and "dataType" not in item


def _name_of(item):
    """The layer name *item* carries, or None."""
    if isinstance(item, dict):
        name = item.get("name") if _is_record(item) else item.get("layerName") if "dataType" in item else None
    else:
        # A frame keeps it in ``metadata``. Read from ``__dict__``: a pandas
        # attribute lookup would give a column named ``metadata`` instead.
        meta = getattr(item, "__dict__", {}).get("metadata")
        name = meta.get("name") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and name else None


def _crs_named_by(fc):
    """The CRS a FeatureCollection names (``crs.properties.name``, as Autark
    writes ``urn:ogc:def:crs:EPSG::3395``), or None."""
    crs = fc.get("crs") if isinstance(fc, dict) else None
    properties = crs.get("properties") if isinstance(crs, dict) else None
    name = properties.get("name") if isinstance(properties, dict) else None
    return name if isinstance(name, str) and name else None


def _frame_of_record(record):
    import geopandas as gpd

    fc = record["geojson"]
    features = fc.get("features") if isinstance(fc.get("features"), list) else []
    frame = gpd.GeoDataFrame.from_features(features)
    declared = _crs_named_by(fc)
    if declared and "geometry" in frame.columns:
        try:
            frame = frame.set_crs(declared)
        except Exception:  # noqa: BLE001  (an unknown CRS name: the rows are read without one)
            pass
    return frame


def _read(item, name: str):
    """The layer *item* holds, as node code reads it, keeping its name."""
    if _is_record(item):
        frame = _frame_of_record(item)
        layer_type = item.get("type")
    elif isinstance(item, dict):
        from utk_curio.sandbox.util.scenario_stack import _unwrap

        frame = _unwrap(item)
        layer_type = item.get("layerType")
    else:
        return item
    if hasattr(frame, "__dict__"):
        meta = {"name": name}
        if isinstance(layer_type, str) and layer_type:
            meta["layerType"] = layer_type
        frame.__dict__["metadata"] = meta
    return frame


def _is_frame(item) -> bool:
    """Whether *item* is one frame: a table, a layer record or envelope."""
    import pandas as pd

    if isinstance(item, pd.DataFrame):
        return True
    return isinstance(item, dict) and (
        _is_record(item) or item.get("dataType") in ("geodataframe", "dataframe")
    )


def _read_unnamed(item):
    """The frame *item* holds, which carries no layer name."""
    if _is_record(item):
        return _frame_of_record(item)
    if isinstance(item, dict):
        from utk_curio.sandbox.util.scenario_stack import _unwrap

        return _unwrap(item)
    return item


def curio_layer(value, layer: str, slot=0):
    """The layer named *layer* of *value*, input *slot*'s value; or the one
    frame *value* carries, when that frame has no layer name."""
    items = _items(value)
    named = [(name, item) for item in items for name in [_name_of(item)] if name is not None]
    for name, item in named:
        if name == layer:
            return _read(item, name)
    if len(items) == 1 and not named and _is_frame(items[0]):
        return _read_unnamed(items[0])
    raise LookupError(missing_layer_message(slot, layer, [name for name, _ in named]))
