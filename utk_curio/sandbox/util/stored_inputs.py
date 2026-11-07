"""What a node's input reads as, from the value its output is stored as.

One rule, which both runners follow: in process (``worker.execute_code`` and
``execute_js_code``), and in an isolated child, whose parent stages the value
(``util/staging.py``) and whose ``child.rebuild_input`` reads it here.

- A stored value that is one envelope of a frame, ``{dataType:
  'geodataframe' | 'dataframe', data}``, as an Autark node hands on one layer
  (``persistLayersToBackend`` in ``adapters/node/autkLayerMaterialize.ts``),
  reads as that frame, whatever data type the request names.
- One that is an ``outputs`` wrapper, ``{dataType: 'outputs', data: [...]}``,
  as an Autark node hands on several layers, reads as the list of what it
  holds, whatever data type the request names.
- Anything else reads as it is stored: an Autark data node's layer array
  (``[{name, type, geojson}]``), a dict a node returned.

A frame read from an envelope keeps the envelope's ``layerName`` and
``layerType`` in its ``metadata`` (:func:`keep_layer_identity`), beside the
label of the bundle part it was read from, and is in the
coordinate system its FeatureCollection names. A JavaScript node gets it as
the FeatureCollection ``worker._to_js_value`` writes, under its layer name.

A wrapper's elements are read one by one: an inline envelope as the value it
holds, and a reference to another output (``{path}``, or a bare artifact id)
as that output reads. A wrapper reads the outputs it names only when it is the
node's one input, whose names the backend checks before the run
(``node_exec.wrapped_input_names``); on one of several circles, or named by
another wrapper, a wrapper that names outputs reads as it is stored.
"""
from __future__ import annotations


def is_frame_envelope(value) -> bool:
    """Whether *value* is one envelope of a frame: a geodataframe's ``data``
    a FeatureCollection, a dataframe's its columns or its rows."""
    if not isinstance(value, dict) or "data" not in value:
        return False
    data = value["data"]
    if value.get("dataType") == "geodataframe":
        return isinstance(data, dict) and isinstance(data.get("features"), list)
    if value.get("dataType") == "dataframe":
        return isinstance(data, (dict, list))
    return False


def is_outputs_wrapper(value) -> bool:
    """Whether *value* is an ``outputs`` wrapper: several values in one."""
    return isinstance(value, dict) and value.get("dataType") == "outputs" and isinstance(value.get("data"), list)


def is_ref(item) -> bool:
    """Whether *item*, an element of a wrapper, names another output: a
    ``{path}`` dict or a bare artifact id."""
    return isinstance(item, str) or (isinstance(item, dict) and "path" in item)


def ref_name(item):
    """The output the reference *item* names."""
    return item["path"] if isinstance(item, dict) else item


def names_outputs(value) -> bool:
    """Whether *value* is a wrapper that names other outputs."""
    return is_outputs_wrapper(value) and any(is_ref(item) for item in value["data"])


def keep_layer_identity(value, envelope):
    """A layer an Autark node handed on keeps its name and its layer type.

    Its envelope names them (``layerName``, ``layerType``); the frame keeps them
    where Curio keeps a frame's own (``metadata``, which ``parseOutput`` hands
    on), so a node can tell an Autark node's layers apart, as the Map Editor
    node does to edit one of them (#662). A frame that already has a name keeps
    it, and one read from a bundle keeps its part's label.
    """
    from utk_curio.sandbox.util.codec import is_geospatial_frame, part_label_only

    name = envelope.get("layerName")
    if not isinstance(name, str) or not name or not is_geospatial_frame(value):
        return value
    meta = getattr(value, "metadata", None)
    if isinstance(meta, dict) and meta.get("name"):
        return value
    kept = {"name": name}
    if isinstance(envelope.get("layerType"), str) and envelope["layerType"]:
        kept["layerType"] = envelope["layerType"]
    value.__dict__["metadata"] = {**kept, **(part_label_only(meta) or {})}
    return value


def _in_declared_crs(value, envelope):
    """*value*, a frame read from *envelope*, in the coordinate system its
    FeatureCollection names, when it has none of its own. Set in place, so the
    frame keeps its ``metadata``; an unknown name leaves the rows without one."""
    from utk_curio.sandbox.util.codec import is_geospatial_frame
    from utk_curio.sandbox.util.input_layers import _crs_named_by

    declared = _crs_named_by(envelope.get("data"))
    if declared and is_geospatial_frame(value) and value.crs is None:
        try:
            value.set_crs(declared, inplace=True)
        except Exception:  # noqa: BLE001  (an unknown CRS name: the rows are read without one)
            pass
    return value


def read_element(item):
    """An inline element of a wrapper as the value it holds: an envelope
    ``{dataType, data}`` as ``parseInput`` reads it, a frame keeping its
    layer's name, type and coordinate system; anything else as it is."""
    if isinstance(item, dict) and "dataType" in item and "data" in item:
        from utk_curio.sandbox.util.parsers import parseInput

        return keep_layer_identity(_in_declared_crs(parseInput(item), item), item)
    return item


def read_stored(value, read_ref=None):
    """What an input whose output is stored as *value* reads as (see the
    module's docstring). *read_ref*, given for a node's one input, reads the
    output an element of its wrapper names: ``read_ref(index, element)``."""
    if is_frame_envelope(value):
        return read_element(value)
    if not is_outputs_wrapper(value):
        return value
    if read_ref is None and names_outputs(value):
        return value
    return [
        read_ref(index, item) if is_ref(item) else read_element(item)
        for index, item in enumerate(value["data"])
    ]
