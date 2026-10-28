"""A dataflow's Trill and its Yjs doc, each made from the other.

The layout is ``frontend/urban-workflows/src/contracts/dataflowDoc.json``, the
table the canvas's own mapping reads too, so the server and every tab build the
same doc from the same Trill, and the same Trill from the same doc. Each field
``TrillGenerator.generateTrill`` writes has a row in it.

**Keys and values.** A map's keys, and the items of the order arrays
(``nodeOrder``, ``edgeOrder``, ``scenarioOrder``, a node's ``widgetOrder``), are
plain strings: node and edge ids, scenario ids, widget names. Every other value
that is not a shared type is the JSON text of its value, plain strings
included. So a number keeps the form it was written in (``5`` stays an int and
``5.0`` a float, which a Yjs number does not keep), and an object keeps the
order of its keys, which a Yjs map does not keep either.

**Layout 1:**

* ``meta`` (map): the doc's own ``id``, the ``layout`` it was built with, and
  ``scenariosListed`` when the Trill lists its scenarios, even none.
* ``dataflow`` (map): each field of the Trill's ``dataflow`` but its three
  lists and the sections kept outside the doc (``outsideTheDoc``), each under
  its own name.
* ``nodes`` (map by id, each a map) and ``nodeOrder`` (array of ids). A node's
  ``place`` {x, y}, ``size`` {width, height} and ``pin`` {pinned, x, y, width,
  height} are one value each, holding the members the Trill gives; its
  ``content`` is a ``Text``; ``metadata`` is a map with each setting as its own
  key; ``widgets`` (map by name, each a map of ``definition``, the widget but
  its name and value, and ``value``) and ``widgetOrder`` hold
  ``metadata.widgets``; every other field is its own key.
* ``edges`` (map by id, each edge whole as one value) and ``edgeOrder``.
* ``scenarios`` (map by id, each a map with each field as its own key) and
  ``scenarioOrder``.

A list whose entries cannot each be keyed (an entry that is not an object, or a
missing or repeated id or name) is kept whole, as one value under its Trill
name in the map that would hold its entries. A node's ``metadata``, ``widgets``
and ``widgetOrder`` are made with the node, so two tabs never each make one; an
empty ``metadata`` is written as none, as ``generateTrill`` writes none.

Trill comes out in the table's order, then the fields the table does not name,
sorted: a Yjs map has no order of its own, so the same doc always gives the
same text.
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Iterable, Optional

from pycrdt import Array, Doc, Map, Text

from utk_curio.common import shared_constants

logger = logging.getLogger(__name__)

#: The doc's layout, shared with the canvas.
LAYOUT = shared_constants.read("dataflowDoc")
#: The Socket.IO event the doc's messages travel in.
EVENT: str = LAYOUT["event"]
#: The ``dataflow`` sections the server keeps beside the doc, never in it: the
#: dataflow's agents, which a watcher, who receives the doc, does not read.
OUTSIDE_THE_DOC = frozenset(LAYOUT["outsideTheDoc"])

#: The origin of the transaction that builds a doc from Trill.
TRILL_ORIGIN = "trill"

KEY = "@key"
TEXT = "@text"
METADATA = "@metadata"
WIDGETS = "@widgets"
NODES = "@nodes"
EDGES = "@edges"
SCENARIOS = "@scenarios"
WHOLE = "@whole"

#: A node's keys for its widgets.
WIDGETS_KEY = "widgets"
WIDGET_ORDER_KEY = "widgetOrder"
#: A widget's keys.
DEFINITION_KEY = "definition"
VALUE_KEY = "value"

_DATAFLOW: dict = LAYOUT["dataflow"]
_NODE: dict = LAYOUT["node"]
_METADATA: dict = LAYOUT["metadata"]
_WIDGET: dict = LAYOUT["widget"]
_SCENARIO: dict = LAYOUT["scenario"]


def _field_of(table: dict, target: str) -> str:
    """The one field of *table* whose place in the doc is *target*."""
    (name,) = [name for name, place in table.items() if place == target]
    return name


#: The Trill fields that name an entry: a node's and an edge's id, a scenario's
#: id, a widget's name.
_NODE_ID = _field_of(_NODE, KEY)
_EDGE_ID = _field_of(LAYOUT["edge"], KEY)
_SCENARIO_ID = _field_of(_SCENARIO, KEY)
_WIDGET_NAME = _field_of(_WIDGET, KEY)
#: The node fields that hold its code and its settings.
_CONTENT = _field_of(_NODE, TEXT)
_NODE_METADATA = _field_of(_NODE, METADATA)
_METADATA_WIDGETS = _field_of(_METADATA, WIDGETS)
_WIDGET_VALUE = _field_of(_WIDGET, VALUE_KEY)

#: A node's grouped values: group -> {member: Trill field}.
_GROUPS: dict[str, dict[str, str]] = {}
for _name, _place in _NODE.items():
    if "." in _place:
        _group, _member = _place.split(".", 1)
        _GROUPS.setdefault(_group, {})[_member] = _name

#: Every key the layout gives a node's map. A Trill node field the table does
#: not name takes its own key, which must not be one of these.
NODE_DOC_KEYS = frozenset(
    {place for place in _NODE.values() if not place.startswith("@") and "." not in place}
    | set(_GROUPS) | {_CONTENT, _NODE_METADATA, WIDGETS_KEY, WIDGET_ORDER_KEY}
)


class DocMappingError(ValueError):
    """A Trill the layout has no place for."""


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def encode(value: Any) -> str:
    """*value* as the JSON text the doc holds: what ``JSON.stringify`` writes,
    a number that is not finite as ``null``."""
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except ValueError:
        return json.dumps(_finite(value), separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(item) for item in value]
    return value


_warned: set[str] = set()


def _warn_once(kind: str, value: Any) -> None:
    if kind not in _warned:
        _warned.add(kind)
        logger.warning("a dataflow doc holds %s, read as it is: %.120r", kind, value)


def decode(value: Any) -> Any:
    """The value a doc holds as JSON text. Never raises: a text that is not
    JSON is kept as it is, and a value some writer put in the doc without its
    JSON text is read as ``JSON.stringify`` would write it."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            _warn_once("a value that is not JSON text", value)
            return value
    if isinstance(value, Text):
        return str(value)
    if isinstance(value, (Map, Array)):
        value = value.to_py()
    _warn_once("a value without its JSON text", value)
    return _as_written(value)


def _as_written(value: Any) -> Any:
    """*value* with each whole float as an int, as ``JSON.stringify`` writes it."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
        return int(value)
    if isinstance(value, dict):
        return {key: _as_written(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_written(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Trill to doc
# ---------------------------------------------------------------------------

def new_doc() -> Doc:
    """An empty doc that any thread may use, one at a time (each open
    dataflow's lock, ``dataflow_docs.py``)."""
    return Doc(allow_multithreading=True)


def owned(dataflow: dict) -> dict:
    """The part of a Trill ``dataflow`` the doc holds."""
    return {name: value for name, value in dataflow.items() if name not in OUTSIDE_THE_DOC}


def _keyed(entries: Any, key: str) -> Optional[list[tuple[str, dict]]]:
    """*entries* by their *key*, or ``None`` when they cannot each be keyed."""
    if not isinstance(entries, list):
        return None
    keyed: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name = entry.get(key)
        if not isinstance(name, str) or name in seen:
            return None
        seen.add(name)
        keyed.append((name, entry))
    return keyed


def dataflow_to_doc(dataflow: dict, doc: Doc, *, doc_id: str) -> None:
    """Write the Trill *dataflow* (a spec's ``dataflow`` object) into the empty
    *doc*, which is then named *doc_id*. Raises :class:`DocMappingError` for a
    node field the layout has no place for."""
    if not isinstance(dataflow, dict):
        raise DocMappingError("a dataflow is an object")
    with doc.transaction(origin=TRILL_ORIGIN):
        meta = doc.get("meta", type=Map)
        fields = doc.get("dataflow", type=Map)
        meta["id"] = encode(doc_id)
        meta["layout"] = encode(LAYOUT["layout"])
        for name, value in dataflow.items():
            if name in OUTSIDE_THE_DOC:
                continue
            place = _DATAFLOW.get(name)
            if place == NODES:
                keyed = _keyed(value, _NODE_ID)
                if keyed is None:
                    fields[name] = encode(value)
                    continue
                nodes = doc.get("nodes", type=Map)
                for node_id, node in keyed:
                    nodes[node_id] = _node_map(node)
                doc.get("nodeOrder", type=Array).extend([node_id for node_id, _ in keyed])
            elif place == EDGES:
                keyed = _keyed(value, _EDGE_ID)
                if keyed is None:
                    fields[name] = encode(value)
                    continue
                edges = doc.get("edges", type=Map)
                for edge_id, edge in keyed:
                    edges[edge_id] = encode(edge)
                doc.get("edgeOrder", type=Array).extend([edge_id for edge_id, _ in keyed])
            elif place == SCENARIOS:
                keyed = _keyed(value, _SCENARIO_ID)
                if keyed is None:
                    fields[name] = encode(value)
                    continue
                meta["scenariosListed"] = encode(True)
                scenarios = doc.get("scenarios", type=Map)
                for scenario_id, scenario in keyed:
                    scenarios[scenario_id] = Map({
                        field: encode(item) for field, item in scenario.items() if field != _SCENARIO_ID
                    })
                doc.get("scenarioOrder", type=Array).extend([scenario_id for scenario_id, _ in keyed])
            else:
                fields[name] = encode(value)


def _node_map(node: dict) -> Map:
    entries: dict[str, Any] = {}
    groups: dict[str, dict] = {}
    metadata: Any = {}
    for name, value in node.items():
        place = _NODE.get(name)
        if place == KEY:
            continue
        if place is None:
            if name in NODE_DOC_KEYS:
                raise DocMappingError(
                    f"node {node.get(_NODE_ID)!r} has a field {name!r}, which is a key "
                    "the doc's layout gives a node for something else"
                )
            entries[name] = encode(value)
        elif place == TEXT:
            entries[name] = Text(value) if isinstance(value, str) else encode(value)
        elif place == METADATA:
            metadata = value
        elif "." in place:
            group, member = place.split(".", 1)
            groups.setdefault(group, {})[member] = value
        else:
            entries[place] = encode(value)
    for group, members in groups.items():
        entries[group] = encode(members)
    widgets: dict[str, Map] = {}
    order: list[str] = []
    if isinstance(metadata, dict):
        settings: dict[str, Any] = {}
        for name, value in metadata.items():
            if _METADATA.get(name) == WIDGETS:
                keyed = _keyed(value, _WIDGET_NAME)
                if keyed is None:
                    settings[name] = encode(value)
                    continue
                for widget_name, widget in keyed:
                    widgets[widget_name] = _widget_map(widget)
                order = [widget_name for widget_name, _ in keyed]
            else:
                settings[name] = encode(value)
        entries[_NODE_METADATA] = Map(settings)
    else:
        # A metadata that is not an object is kept whole.
        entries[_NODE_METADATA] = encode(metadata)
    entries[WIDGETS_KEY] = Map(widgets)
    entries[WIDGET_ORDER_KEY] = Array(order)
    return Map(entries)


def _widget_map(widget: dict) -> Map:
    entries = {DEFINITION_KEY: encode({
        name: value for name, value in widget.items() if name not in (_WIDGET_NAME, _WIDGET_VALUE)
    })}
    if _WIDGET_VALUE in widget:
        entries[VALUE_KEY] = encode(widget[_WIDGET_VALUE])
    return Map(entries)


# ---------------------------------------------------------------------------
# Doc to Trill
# ---------------------------------------------------------------------------

def _keys(value: Any) -> set[str]:
    return set(value.keys()) if isinstance(value, Map) else set()


def _ordered(order: Any, entries: Map) -> list[str]:
    """The keys of *entries* in the order *order* lists them, each once; any
    it does not list come after, sorted."""
    present = _keys(entries)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in order if isinstance(order, Array) else ():
        if isinstance(item, str) and item in present and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered + sorted(present - seen)


def doc_id(doc: Doc) -> Optional[str]:
    """The id *doc* was built with, if it holds one."""
    meta = doc.get("meta", type=Map)
    if "id" not in _keys(meta):
        return None
    value = decode(meta["id"])
    return value if isinstance(value, str) and value else None


def doc_to_dataflow(doc: Doc) -> dict:
    """The Trill ``dataflow`` object *doc* holds, without the sections kept
    outside the doc."""
    meta = doc.get("meta", type=Map)
    fields = doc.get("dataflow", type=Map)
    present = _keys(fields)
    out: dict[str, Any] = {}
    for name, place in _DATAFLOW.items():
        if name in present:
            out[name] = decode(fields[name])
        elif place == NODES:
            nodes = doc.get("nodes", type=Map)
            out[name] = [
                _node_out(node_id, nodes[node_id])
                for node_id in _ordered(doc.get("nodeOrder", type=Array), nodes)
            ]
        elif place == EDGES:
            edges = doc.get("edges", type=Map)
            out[name] = [
                _edge_out(edge_id, edges[edge_id])
                for edge_id in _ordered(doc.get("edgeOrder", type=Array), edges)
            ]
        elif place == SCENARIOS:
            scenarios = doc.get("scenarios", type=Map)
            listed = [
                _scenario_out(scenario_id, scenarios[scenario_id])
                for scenario_id in _ordered(doc.get("scenarioOrder", type=Array), scenarios)
            ]
            if listed or ("scenariosListed" in _keys(meta) and decode(meta["scenariosListed"]) is True):
                out[name] = listed
    for name in sorted(present - set(_DATAFLOW)):
        out[name] = decode(fields[name])
    return out


def _with_key(field: str, key: str, value: Any) -> Any:
    """An entry kept whole, its *field* the *key* its map names it by."""
    value = decode(value)
    if isinstance(value, dict):
        if field in value:
            value[field] = key
        else:
            value = {field: key, **value}
    return value


def _node_out(node_id: str, node: Any) -> Any:
    if not isinstance(node, Map):
        return _with_key(_NODE_ID, node_id, node)
    keys = _keys(node)
    groups = {group: decode(node[group]) for group in _GROUPS if group in keys}
    out: dict[str, Any] = {}
    for name, place in _NODE.items():
        if place == KEY:
            out[name] = node_id
        elif place == TEXT:
            if name in keys:
                value = node[name]
                out[name] = str(value) if isinstance(value, Text) else decode(value)
        elif place == METADATA:
            metadata = _metadata_out(node, keys)
            if metadata is not None:
                out[name] = metadata
        elif "." in place:
            group, member = place.split(".", 1)
            members = groups.get(group)
            if isinstance(members, dict) and member in members:
                out[name] = members[member]
        elif place in keys:
            out[name] = decode(node[place])
    for name in sorted(keys - NODE_DOC_KEYS):
        out[name] = decode(node[name])
    return out


def _metadata_out(node: Map, keys: set[str]) -> Any:
    """A node's ``metadata``, or ``None`` when it has none to write."""
    settings = node[_NODE_METADATA] if _NODE_METADATA in keys else None
    if settings is not None and not isinstance(settings, Map):
        return decode(settings)
    present = _keys(settings)
    out: dict[str, Any] = {}
    for name, place in _METADATA.items():
        if name in present:
            out[name] = decode(settings[name])
        elif place == WIDGETS:
            widgets = _widgets_out(node, keys)
            if widgets:
                out[name] = widgets
    for name in sorted(present - set(_METADATA)):
        out[name] = decode(settings[name])
    return out or None


def _widgets_out(node: Map, keys: set[str]) -> list:
    widgets = node[WIDGETS_KEY] if WIDGETS_KEY in keys else None
    if not isinstance(widgets, Map):
        return []
    order = node[WIDGET_ORDER_KEY] if WIDGET_ORDER_KEY in keys else None
    return [_widget_out(name, widgets[name]) for name in _ordered(order, widgets)]


def _widget_out(name: str, widget: Any) -> Any:
    if not isinstance(widget, Map):
        return _with_key(_WIDGET_NAME, name, widget)
    keys = _keys(widget)
    out: dict[str, Any] = {_WIDGET_NAME: name}
    definition = decode(widget[DEFINITION_KEY]) if DEFINITION_KEY in keys else {}
    if isinstance(definition, dict):
        out.update({
            field: value for field, value in definition.items()
            if field not in (_WIDGET_NAME, _WIDGET_VALUE)
        })
    if VALUE_KEY in keys:
        out[_WIDGET_VALUE] = decode(widget[VALUE_KEY])
    return out


def _edge_out(edge_id: str, edge: Any) -> Any:
    return _with_key(_EDGE_ID, edge_id, edge)


def _scenario_out(scenario_id: str, scenario: Any) -> Any:
    if not isinstance(scenario, Map):
        return _with_key(_SCENARIO_ID, scenario_id, scenario)
    keys = _keys(scenario)
    out: dict[str, Any] = {}
    for name, place in _SCENARIO.items():
        if place == KEY:
            out[name] = scenario_id
        elif place in keys:
            out[name] = decode(scenario[place])
    for name in sorted(keys - set(_SCENARIO.values())):
        out[name] = decode(scenario[name])
    return out


def node_ids(doc: Doc) -> Iterable[str]:
    """The ids of *doc*'s nodes, in order."""
    return _ordered(doc.get("nodeOrder", type=Array), doc.get("nodes", type=Map))
