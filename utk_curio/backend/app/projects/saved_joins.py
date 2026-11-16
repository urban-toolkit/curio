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

An agent's change to a join, kept on its attachment from before, undoes by
the same rule (``agents/application/proposals/changes.py``): a join it created
is compared as it reads now, and a change of its setting puts back the values
the rule gives its widgets (:func:`widget_values`).
"""

from __future__ import annotations

import copy
from typing import Any

from utk_curio.common import shared_constants

_SAVED = shared_constants.read("savedSpatialJoin")
#: Where a join saved before its code kept its settings, in its ``metadata``.
SETTING = _SAVED["setting"]


def _unversioned(node_type: Any) -> Any:
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


def _held_values(saved: Any) -> dict[str, str]:
    """The values *saved*, a join's saved setting, gives its widgets, by
    widget name: each setting saved for a widget (``widgetOf``) that is one
    of the widget's choices."""
    saved = saved if isinstance(saved, dict) else {}
    setting_of = {widget: setting for setting, widget in _SAVED["widgetOf"].items()}
    held = {}
    for widget in _SAVED["widgets"]:
        value = saved.get(setting_of.get(widget["name"]))
        if isinstance(value, str) and value in widget["options"]["choices"]:
            held[widget["name"]] = value
    return held


def widget_values(setting: Any) -> dict[str, str]:
    """The value each widget of a join holds once *setting*, a saved
    ``metadata.spatialJoin``, is converted (:func:`converted_node`), by
    widget name: the setting saved for it when that is one of its choices,
    else its default."""
    held = _held_values(setting)
    return {widget["name"]: held.get(widget["name"], widget["default"]) for widget in _SAVED["widgets"]}


def widgets_of(setting: Any) -> list[str]:
    """The widgets the keys of *setting*, a join's saved setting or a change
    of it, are saved for (``widgetOf``), in the template's order."""
    keys = set(setting) if isinstance(setting, dict) else set()
    named = {name for key, name in _SAVED["widgetOf"].items() if key in keys}
    return [widget["name"] for widget in _SAVED["widgets"] if widget["name"] in named]


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
    held = _held_values(metadata.pop(SETTING, None))
    widgets = []
    for template_widget in _SAVED["widgets"]:
        widget = copy.deepcopy(template_widget)
        if widget["name"] in held:
            widget["value"] = held[widget["name"]]
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
