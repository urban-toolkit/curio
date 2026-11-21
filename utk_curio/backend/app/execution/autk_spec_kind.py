"""What kind of step an Autark document describes, decided as the canvas
decides it.

The twin of ``classifyAutkSpec`` and ``classifyAutkSpecString`` in
``utils/autkSpecKind.ts``; ``utils/autkSpecKind.cases.json`` beside it holds
the cases both run. ``render`` draws a map or a plot, ``compute`` runs WGSL
over layers, ``data`` only loads sources, and anything else is ``unknown``.

Also which tables of the node's input a document's data section reads
(:func:`section_input_tables`), the twin of ``sectionInputTables`` in
``adapters/node/autkDataCompile.ts``, with the cases both run in
``autkSectionInputs.cases.json`` beside it: a data node that reads some
runs on its input on the server too.
"""
from __future__ import annotations

import json

from utk_curio.common import shared_constants

#: autk-db's default workspace: a source that names none, or names it, is in it.
DEFAULT_WORKSPACE: str = shared_constants.read("autkGrammar")["defaultWorkspace"]

#: The step each top-level family describes (``FAMILY_KIND``). A family of
#: None describes none of its own: a layout arranges views, links join them
#: and workspaces set where the sources load, so a document with one is the
#: step its other families describe.
FAMILY_KIND = {
    "map": "render", "plot": "render", "layout": None, "links": None, "workspaces": None,
    "compute": "compute", "data": "data",
}

#: Drawing wins over computing, and computing over loading.
KIND_ORDER = ("render", "compute", "data")

AUTK_GRAMMAR = "AUTK_GRAMMAR"


def classify_autk_spec(spec) -> str:
    """``render``, ``compute``, ``data`` or ``unknown`` for a parsed document.
    A map or a plot counts as soon as it is named; a step list only when it
    holds a step."""
    if not isinstance(spec, dict):
        return "unknown"

    def names(family: str) -> bool:
        if FAMILY_KIND[family] == "render":
            return spec.get(family) is not None
        value = spec.get(family)
        return isinstance(value, list) and len(value) > 0

    for kind in KIND_ORDER:
        if any(FAMILY_KIND[family] == kind and names(family) for family in FAMILY_KIND):
            return kind
    return "unknown"


def _not_json(constant: str):
    raise ValueError(f"{constant} is not JSON")


def classify_autk_spec_string(spec_text) -> str:
    """:func:`classify_autk_spec` for a document as text, read as
    ``JSON.parse`` reads it, before its chips are resolved: a chip standing on
    its own, ``"color": [!! scenario input_1 !!]``, holds its place
    (``code_references.with_chip_placeholders``), so the document is read for
    what it declares rather than taken for no document."""
    from utk_curio.backend.app.execution.code_references import with_chip_placeholders

    if not isinstance(spec_text, str) or not spec_text.strip():
        return "unknown"
    try:
        return classify_autk_spec(json.loads(with_chip_placeholders(spec_text), parse_constant=_not_json))
    except ValueError:
        return "unknown"


def is_autk_data_node(node: dict) -> bool:
    """An Autark node of a saved dataflow whose document only loads data."""
    from utk_curio.backend.app.execution.workflow_spec import normalize_type

    node_type = (node or {}).get("type")
    return (
        isinstance(node_type, str)
        and normalize_type(node_type) == AUTK_GRAMMAR
        and classify_autk_spec_string(node.get("content")) == "data"
    )


def _workspace_of(entry) -> str | None:
    """The workspace *entry* names, or None for the default one, named or not."""
    workspace = entry.get("workspace") if isinstance(entry, dict) else None
    return workspace if isinstance(workspace, str) and workspace and workspace != DEFAULT_WORKSPACE else None


def _table_key(workspace: str | None, name: str) -> str:
    """A table's key: its name in the default workspace, ``<workspace>/<name>``
    in another (``autkTableKey``)."""
    return name if workspace is None else f"{workspace}/{name}"


def _loaded_tables(sources: list) -> set[str]:
    """The keys of a data section's own tables: those its sources load and
    make, as ``requestedLayerTables`` names them (an OSM load's layers
    ``<outputTableName>_<layer>`` and tag sets ``<outputTableName>_<name>_<type>``),
    and every name a source gives its table (``outputTableName``, an OSM load's
    and a SQL source's included). A join, an update and a drop make none."""
    keys: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        kind, out, workspace = source.get("type"), source.get("outputTableName"), _workspace_of(source)
        if kind == "osm" and isinstance(out, str) and out:
            auto = source.get("autoLoadLayers")
            layers = auto.get("layers") if isinstance(auto, dict) else None
            if isinstance(layers, list):
                keys.update(_table_key(workspace, f"{out}_{layer}") for layer in layers)
            tag_sets = source.get("tagSets")
            for tag_set in tag_sets if isinstance(tag_sets, list) else []:
                if isinstance(tag_set, dict) and tag_set.get("name") and tag_set.get("type"):
                    keys.add(_table_key(workspace, f"{out}_{tag_set['name']}_{tag_set['type']}"))
        if isinstance(out, str) and out:
            keys.add(_table_key(workspace, out))
    return keys


#: The tables each kind of source reads by name: a heatmap bins one, a join
#: joins two, and an update or a drop changes one.
_READS = {"heatmap": ("joinDataRef",), "join": ("dataRef", "joinDataRef"), "update": ("dataRef",), "drop": ("dataRef",)}


def _in_phase_order(sources: list) -> list:
    """*sources* in the order autk-grammar runs them when no pass runs between
    them: those without ``after``, then those with it (``after: 'compute'``),
    each in the order of ``data``. ``inPhaseOrder`` is the node's twin."""
    return ([source for source in sources if not isinstance(source, dict) or "after" not in source]
            + [source for source in sources if isinstance(source, dict) and "after" in source])


def section_input_tables(spec) -> list[str]:
    """The keys of the tables a document's data section reads from the node's
    input, in the order it first reads them: each table a heatmap bins
    (``joinDataRef``), a join reads (``dataRef``, ``joinDataRef``) or an update
    or a drop changes (``dataRef``), in the entry's workspace, that none of the
    section's own sources loads. The section is read in the order autk-grammar
    runs it (``_in_phase_order``)."""
    sources = spec.get("data") if isinstance(spec, dict) else None
    if not isinstance(sources, list):
        return []
    loaded = _loaded_tables(sources)
    keys: list[str] = []
    for source in _in_phase_order(sources):
        if not isinstance(source, dict) or source.get("type") not in _READS:
            continue
        read = [source.get(field) for field in _READS[source["type"]]]
        for table in read:
            if not isinstance(table, str) or not table:
                continue
            key = _table_key(_workspace_of(source), table)
            if key not in loaded and key not in keys:
                keys.append(key)
    return keys


def reads_input_tables(node: dict) -> bool:
    """Whether the document of an Autark node of a saved dataflow reads tables
    of the node's input in its data section (:func:`section_input_tables`),
    read before its chips are resolved, a chip standing on its own holding its
    place: a chip in a document always names something the input carries."""
    from utk_curio.backend.app.execution.code_references import with_chip_placeholders

    content = (node or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        spec = json.loads(with_chip_placeholders(content), parse_constant=_not_json)
    except ValueError:
        return False
    return bool(section_input_tables(spec))
