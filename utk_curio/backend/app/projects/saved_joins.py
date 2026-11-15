"""A Spatial Join saved before its join was code reads as one made now.

The Spatial Join node once held no code: its body picked the operation and
the output, which a save wrote at ``metadata.spatialJoin`` (``predicate``,
``output``). Its code now calls the built-in package's ``spatial_join``, and
its two widgets, Operation and Output, hold those settings. A join saved the
old way, with no code and no widgets, reads with the template's code and
widgets, each widget holding the setting saved for it when that setting is one
of its choices, and without ``metadata.spatialJoin``
(``src/contracts/savedSpatialJoin.json``). A join with code or widgets is left
as it is, so a node is converted once.

A saved dataflow reaches the server's readers from two places, and each read
of them converts it. Its spec file: every reader of a dataflow no tab opened
reads it (``storage.read_spec_in``), and an open dataflow's doc is built from it
(``storage.read_spec_file``). Its doc's log, which keeps a doc between opens:
a doc it kept from before is built anew from its dataflow converted when it
opens (``dataflow_docs._load``), so the doc the tabs edit holds the code; a
read of another process's doc (``dataflow_docs._read_with``) and a version
(``history.dataflow_at``, which putting one back writes) convert what they
read. The canvas's twin is ``src/contracts/savedSpatialJoin.ts``, through which
``hook/codeNodes.ts`` reads each node of a load and of the doc; both run
``src/contracts/savedSpatialJoin.cases.json``.
"""

from __future__ import annotations

import copy
from typing import Any

from utk_curio.common import shared_constants

_SAVED = shared_constants.read("savedSpatialJoin")


def _unversioned(node_type: Any) -> Any:
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


def is_saved_join(node: Any) -> bool:
    """Whether *node*, a dataflow's node, is a Spatial Join saved before its
    code: of the join's type, with no code and no widgets."""
    if not isinstance(node, dict) or _unversioned(node.get("type")) != _SAVED["nodeType"]:
        return False
    content = node.get("content")
    if content is not None and not (isinstance(content, str) and not content.strip()):
        return False
    metadata = node.get("metadata")
    return not (isinstance(metadata, dict) and isinstance(metadata.get("widgets"), list))


def converted_node(node: Any) -> Any:
    """*node* as a join made now reads it, or *node* itself when it is no
    saved join (:func:`is_saved_join`)."""
    if not is_saved_join(node):
        return node
    metadata = dict(node["metadata"]) if isinstance(node.get("metadata"), dict) else {}
    saved = metadata.pop(_SAVED["setting"], None)
    saved = saved if isinstance(saved, dict) else {}
    setting_of = {widget: setting for setting, widget in _SAVED["widgetOf"].items()}
    widgets = []
    for template_widget in _SAVED["widgets"]:
        widget = copy.deepcopy(template_widget)
        value = saved.get(setting_of.get(widget["name"]))
        if isinstance(value, str) and value in widget["options"]["choices"]:
            widget["value"] = value
        widgets.append(widget)
    metadata["widgets"] = widgets
    return {**node, "content": _SAVED["code"], "metadata": metadata}


def converted_dataflow(dataflow: Any) -> Any:
    """*dataflow* with each saved join converted (:func:`converted_node`), or
    *dataflow* itself when it holds none."""
    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    if not isinstance(nodes, list) or not any(is_saved_join(node) for node in nodes):
        return dataflow
    return {**dataflow, "nodes": [converted_node(node) for node in nodes]}


def converted_spec(spec: Any) -> Any:
    """A saved dataflow's whole document with its saved joins converted, or
    *spec* itself when it holds none."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    converted = converted_dataflow(dataflow)
    return spec if converted is dataflow else {**spec, "dataflow": converted}
