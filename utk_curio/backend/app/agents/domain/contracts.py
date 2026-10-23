"""The single source for contracts both the model and the code must agree on.

A contract is something the code enforces: change it and the model, or the
other half of the code, is wrong about what the system accepts. Each one is
defined once. A contract the frontend shares is a JSON file in the frontend's
``src/contracts/``, which the frontend imports and this module reads at import
(``utk_curio/common/shared_constants.py``); the rest are defined here. Nothing
is generated.

The agents read these facts too. A page or prompt in ``agents/`` that states
something the code owns holds a marker for it, and each marker is a field
that ``PROMPT_FIELDS`` renders from the code that owns it (see Prompt fields
below). The backend renders every page and prompt when it starts
(``agent_text``); nothing of them is generated or committed.

Importable from an installed wheel: at import the module reads only the shared
files, and imports only the standard library and their reader. A renderer
reads the files it projects when it is called, and a prompt field imports the
module that owns its fact inside its own function (the built-in agents, the
packages layer, the egress policy), so importing this module never pulls
those in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from utk_curio.common import shared_constants

#: The prompt slot an Autark content run reads (``manifest.prompts``): the key the built-in
#: manifests declare and the reply-schema run looks up — one spelling, agreed here.
AUTK_PROMPT_KEY = "autk-grammar"


# --- Render outcome vocabulary ---------------------------------------------
#
# A renderer Curio owns (frontend ``renderOutcome``) counts what it drew and,
# when it drew nothing, reports a journal record whose ``kind`` is
# ``empty-render:<cause>``. The cause decides who is at fault, and therefore
# whether the harness asks for a corrected document or waits on the upstream.
# ``renderCauses.json`` holds the kind and the causes for both sides.

_RENDER_CAUSES = shared_constants.read("renderCauses")

#: The kind a renderer stamps on an empty render, with its cause appended.
EMPTY_RENDER_KIND: str = _RENDER_CAUSES["emptyRenderKind"]


@dataclass(frozen=True)
class RenderCause:
    """One reason a render drew nothing."""

    name: str
    #: Whether rewriting THIS node's document is the repair. False only when
    #: nothing arrived from upstream, so no document could have drawn a thing.
    document_at_fault: bool
    description: str


#: Every cause a renderer can report. The order is the vocabulary's own and new
#: causes are appended; which cause wins when several apply is decided by the
#: rule order in ``renderOutcome``.
RENDER_CAUSES: tuple[RenderCause, ...] = tuple(
    RenderCause(name, cause["documentAtFault"], cause["description"])
    for name, cause in _RENDER_CAUSES["causes"].items()
)

#: The cause names alone, in table order.
EMPTY_RENDER_CAUSES: tuple[str, ...] = tuple(cause.name for cause in RENDER_CAUSES)

_AT_FAULT = {cause.name: cause.document_at_fault for cause in RENDER_CAUSES}


def is_document_at_fault(cause: object) -> bool:
    """Whether an empty render with this cause is the DOCUMENT's problem.

    Read from ``RENDER_CAUSES``. A cause this build does not know is treated as
    the document's fault, so a correction is still asked for: only a cause the
    table marks as not at fault spares the document.
    """
    return _AT_FAULT.get(str(cause or ""), True)


# --- Solve stop reasons ------------------------------------------------------
#
# A node's repair loop (``solve/verified_loop.py``) reports why it stopped as
# ``stoppedBy``. The failure sentences, the loop's trace, the attempts card and
# the per-node Solve row all say it with the phrase ``solveStopReasons.json``
# gives it; ARCHITECTURE's "The Solve loop" says when each reason happens.


@dataclass(frozen=True)
class StopReason:
    """One reason a node's repair loop stopped, and how it reads."""

    key: str
    #: A clause that continues a sentence: it follows "3 attempts · " on the
    #: card and sits in the parentheses of "not fixed after 3 attempts (...)".
    phrase: str


#: Every reason a repair loop can stop. New reasons are appended.
SOLVE_STOP_REASONS: tuple[StopReason, ...] = tuple(
    StopReason(key, phrase) for key, phrase in shared_constants.read("solveStopReasons")["phrases"].items()
)


def one_phrase_per_reason(reasons: tuple[StopReason, ...]) -> dict[str, str]:
    """``{key: phrase}`` for *reasons*. A key given twice raises, where a
    dict literal would keep the last phrase and say nothing."""
    phrases: dict[str, str] = {}
    for reason in reasons:
        if reason.key in phrases:
            raise ValueError(f"the stop reason {reason.key!r} is given twice")
        phrases[reason.key] = reason.phrase
    return phrases


#: ``stoppedBy`` -> the words every surface shows for it.
STOPPED_BY_PHRASES: dict[str, str] = one_phrase_per_reason(SOLVE_STOP_REASONS)


# --- Autark grammar ---------------------------------------------------------
#
# The grammar is defined upstream: autk-grammar generates a JSON Schema from its
# TypeScript types, and ``schemas/autk-grammar.v1.json`` is a byte-for-byte copy
# of the released file (``scripts/sync_autk_schema.py``). The renderers below
# read that file. The Curio facts they add, how a node names its input and that
# a node draws one view, are in ``autkGrammar.json`` with the top-level families
# the node routes, which a test holds to the schema's.

_AUTK_GRAMMAR = shared_constants.read("autkGrammar")

#: The vendored schema, beside this module so an installed wheel carries it.
# domain/contracts.py -> agents/schemas/ (one level up since the module moved into domain/, memo dev/142 B1)
AUTK_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "autk-grammar.v1.json"
#: The template whose content is an Autark document.
AUTK_TEMPLATE = "curio.builtin/autk-grammar"
#: The Map Edits node's template (its id is still Edit Features'): it edits
#: on an Autark map it feeds, linked to it by an interaction edge.
EDIT_FEATURES_TEMPLATE = "curio.builtin/edit-features"
#: What a Vega-Lite or Autark node calls its inputs: ``input_0``, ``input_1``,
#: ... in circle order. An upstream Autark node's layers keep their table names.
INPUT_TABLE_PREFIX: str = _AUTK_GRAMMAR["inputTablePrefix"]


def input_table_name(position: int) -> str:
    """The name a grammar node's input at *position* is read by.
    ``inputTableName`` in the frontend's ``contracts/autkGrammar.ts`` is the
    node's twin; ``autkGrammar.cases.json`` beside it holds the cases both run."""
    return f"{INPUT_TABLE_PREFIX}{position}"


#: What a document with more than one view is told: a map and a plot, or a list
#: of more than one map or more than one plot. An Autark node draws one view, a
#: map on the one canvas or a plot in the one pane it hands autk-grammar, which
#: puts every map of a list on that canvas and draws a plot only into a pane.
#: The node's error (``autkOneViewProblem`` in ``contracts/autkGrammar.ts``),
#: the agents' document check (``document_validation``) and the preamble say
#: these words.
AUTK_ONE_VIEW: str = _AUTK_GRAMMAR["oneView"]


def autk_one_view_problem(document: object) -> str | None:
    """``AUTK_ONE_VIEW`` when *document* has a map and a plot, or lists more
    than one map or more than one plot, else None. A list of one map or one
    plot is that view. ``autkOneViewProblem`` is the node's twin, held to this
    function by the cases in ``autkGrammar.cases.json``."""
    if not isinstance(document, dict):
        return None
    views = [document.get("map"), document.get("plot")]
    both = all(view is not None for view in views)
    several = any(isinstance(view, list) and len(view) > 1 for view in views)
    return AUTK_ONE_VIEW if both or several else None


def load_autk_schema(path: Path = AUTK_SCHEMA_PATH) -> dict:
    """The vendored Autark schema, parsed."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _definition(schema: dict, ref: str) -> dict:
    """A definition by ``$ref`` (escaped or not) or by bare name, from a
    draft-07 ``definitions`` or a 2020-12 ``$defs``."""
    definitions = schema.get("definitions") or schema.get("$defs") or {}
    return definitions.get(unquote(ref.rsplit("/", 1)[-1]), {})


def autk_families(schema: dict) -> tuple[str, ...]:
    """The top-level keys a document can name, in schema order."""
    root = _definition(schema, schema.get("$ref", "UrbanSpec"))
    return tuple(key for key in root.get("properties", {}) if not key.startswith("$"))


def _variants(schema: dict, union: str, key: str) -> list[tuple[list[str], dict]]:
    """A discriminated union's members: each one's ``key`` values and definition."""
    members = []
    for clause in _definition(schema, union).get("allOf", []):
        condition = clause.get("if", {}).get("properties", {}).get(key, {})
        values = [condition["const"]] if "const" in condition else list(condition.get("enum", []))
        target = clause.get("then", {}).get("$ref")
        if values and target:
            members.append((values, _definition(schema, target)))
    return members


def _either(values) -> str:
    """``a, b, c`` quoted and joined with "or"."""
    quoted = [f'"{v}"' for v in values]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " or " + quoted[-1]


def _every(values) -> str:
    """``a, b, c`` quoted and joined with "and"."""
    quoted = [f'"{v}"' for v in values]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


def _compute_required(schema: dict) -> tuple[list[str], list[str]]:
    """The fields every compute pass needs, and the fields it needs one of."""
    branches = [
        set(branch.get("required", []))
        for branch in _definition(schema, "ComputeSpec").get("anyOf", [])
    ] or [set()]
    common = set.intersection(*branches)
    return sorted(common), sorted(set.union(*branches) - common)


def _plot_required(schema: dict) -> list[str]:
    """The fields every plot needs, whatever its mark."""
    sets = [set(d.get("required", [])) for _, d in _variants(schema, "PlotSpec", "mark")] or [set()]
    return sorted(set.intersection(*sets))


def map_layers(schema: dict) -> tuple[str, list[str]]:
    """The map key that lists its layers, and what each layer requires."""
    spec = _definition(schema, "MapSpec")
    for key, prop in spec.get("properties", {}).items():
        ref = prop.get("items", {}).get("$ref", "")
        if ref:
            return key, _definition(schema, ref).get("required", [])
    return "", []


def render_autk_shape(schema: dict) -> str:
    """One line naming what an Autark document is, for a refusal's text. The
    map example leads, so it survives the attempt trail's shorter cut."""
    from utk_curio.backend.app.agents.domain import agent_text

    layers, layer_required = map_layers(schema)
    common, either = _compute_required(schema)
    source_types = _definition(schema, "DataSourceSpec").get("properties", {}).get("type", {}).get("enum", [])
    first = input_table_name(0)
    example_layer = "{" + ", ".join(f'"{field}": "{first}"' for field in layer_required) + "}"
    return agent_text.message(
        "document.autk-shape", layers=layers, example_layer=example_layer, first=first,
        families=_either(autk_families(schema)), plot_fields=_every(_plot_required(schema)),
        compute_fields=_every(common), compute_one_of=_either(either),
        source_type=source_types[0] if source_types else "",
    )


#: The page of the base entry that holds the words of the preamble's section
#: on Autark documents, one section per line (``render_autk_region``).
AUTK_GRAMMAR_PAGE = "autark-grammar.md"


def _autk_words(name: str, **values: str) -> str:
    """The section *name* of ``AUTK_GRAMMAR_PAGE``, its places filled."""
    from utk_curio.backend.app.agents.domain import agent_text

    where = f"{agent_text.PAGE_PREFIX}{AUTK_GRAMMAR_PAGE}, section {name}"
    return agent_text.fill(agent_text.section(AUTK_GRAMMAR_PAGE, name), values, where)


def render_autk_region(schema: dict, label: str) -> str:
    """The preamble's section on Autark documents: the words of the base
    entry's ``autark-grammar.md``, filled from the schema, with the lines of
    the schema's own choices between them."""
    root = _definition(schema, schema.get("$ref", "UrbanSpec"))
    props = root.get("properties", {})
    layers, layer_required = map_layers(schema)
    common, either = _compute_required(schema)
    compute = _definition(schema, "ComputeSpec")
    compute_fields = compute.get("anyOf", [{}])[0].get("properties", {})
    directive = _definition(schema, "FromFeatureDirective")
    iterate = directive.get("properties", {}).get("fromFeature", {}).get("properties", {}).get("iterate", {})
    layer_spec = _definition(schema, "MapLayerSpec")
    interpolators = _definition(
        schema, layer_spec.get("properties", {}).get("colorMapInterpolator", {}).get("$ref", "")
    ).get("enum", [])
    # What "title" does in a map; the grammar's note on which adapters read it is left out.
    layer_title = layer_spec.get("properties", {}).get("title", {}).get("description", "")
    layer_title = layer_title.split(" Read by the ", 1)[0]

    lines = [
        _autk_words(
            "intro", label=label, template=AUTK_TEMPLATE, schema_id=str(schema.get("$id")),
            families=_either(autk_families(schema)),
        ),
        _autk_words("inputs", first=input_table_name(0), second=input_table_name(1), label=label),
        "",
        "- " + _autk_words("data", description=props.get("data", {}).get("description", "")),
    ]
    for values, definition in _variants(schema, "DataSourceSpec", "type"):
        required = [f for f in definition.get("required", []) if f != "type"]
        lines.append(
            f"  - {_either(values)}: {definition.get('description', '')}"
            + (" " + _autk_words("requires", fields=_every(required)) if required else "")
        )
    lines += [
        "- " + _autk_words(
            "compute", description=props.get("compute", {}).get("description", ""),
            pass_description=compute.get("description", ""), fields=_every(common),
        ),
    ]
    for field in common:
        description = compute_fields.get(field, {}).get("description")
        if description:
            lines.append(f'  - "{field}": {description}')
    lines += [
        ("  - " + _autk_words(
            "uniform", directive=directive.get("description", ""), iterate=iterate.get("description", ""),
        )).rstrip(),
        # The schema's own descriptions of "map" and "plot" allow several, and a
        # document may name both; a node draws one view.
        ("- " + _autk_words(
            "map", one_view=AUTK_ONE_VIEW, map_fields=_every(_definition(schema, "MapSpec").get("required", [])),
            layers=layers, layer_fields=_every(layer_required), interpolators=_either(interpolators),
            layer_title=layer_title,
        )).rstrip(),
        "- " + _autk_words("plot", one_view=AUTK_ONE_VIEW, plot_fields=_every(_plot_required(schema))),
    ]
    for values, definition in _variants(schema, "PlotSpec", "mark"):
        lines.append(f"  - {_either(values)}: {definition.get('description', '')}")
    return "\n".join(lines)


# --- Starter specs and image columns ----------------------------------------
#
# Two things a visualization node does with its input by itself, which the
# shared preamble describes so a model writes what the node would. A Vega-Lite
# or Autark node whose editor is empty fills it with a starter chosen by a
# ladder of rules over the input's column roles (frontend ``vegaDefaultSpec``,
# ``autkDefaultSpec``, ``starterSpec``), and a Simple View node draws the
# columns that hold images as cards (``imageColumns``). ``visDefaults.json``
# holds the tables for both sides: the frontend keeps each rule's builder, keyed
# by the rule's id, and the matching logic.

_VIS_DEFAULTS = shared_constants.read("visDefaults")

#: The ``$schema`` of a Vega-Lite spec Curio writes.
VEGA_SCHEMA_URL: str = _VIS_DEFAULTS["vegaSchemaUrl"]

#: The roles a column can have, in the order a ladder groups them.
COLUMN_ROLES: tuple[str, ...] = tuple(_VIS_DEFAULTS["columnRoles"])


@dataclass(frozen=True)
class DtypeRole:
    """The pandas dtypes that give a column one role: those named whole and
    those that start with one of the prefixes. Matched in lower case."""

    role: str
    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()


#: A dtype's role is the first entry's that matches it, in this order, and a
#: dtype no entry matches gives its column no role. ``str`` is pandas 3's
#: string dtype; pandas 2 said ``object``.
DTYPE_ROLES: tuple[DtypeRole, ...] = tuple(
    DtypeRole(entry["role"], names=tuple(entry["names"]), prefixes=tuple(entry["prefixes"]))
    for entry in _VIS_DEFAULTS["dtypeRoles"]
)


@dataclass(frozen=True)
class CountRange:
    """At least ``least``, and at most ``most`` when it is set."""

    least: int
    most: int | None = None


def _count(entry: dict) -> CountRange:
    """A ``{"least", "most"}`` count of the file as a :class:`CountRange`."""
    return CountRange(entry["least"], entry.get("most"))


@dataclass(frozen=True)
class StarterRule:
    """One rule of a starter ladder. The ladder is tried in order and the first
    rule whose condition holds writes the starter."""

    #: Stable id: the frontend keys the rule's builder by it.
    id: str
    #: The mark a Vega-Lite rule's spec draws, or the family an Autark rule's
    #: document names.
    produces: str
    #: What the starter holds, in one line.
    description: str
    #: How many columns of each role the rule needs; for an Autark rule, in
    #: every layer of the input.
    columns: tuple[tuple[str, CountRange], ...] = ()
    #: For an Autark rule, how many layers with geometry the input has.
    layers: CountRange | None = None


def _starter_ladder(rules: list[dict]) -> tuple[StarterRule, ...]:
    """A ladder of the file, rule by rule, in its order."""
    return tuple(
        StarterRule(
            rule["id"], rule["produces"], rule["description"],
            columns=tuple((role, _count(count)) for role, count in rule["columns"].items()),
            layers=_count(rule["layers"]) if "layers" in rule else None,
        )
        for rule in rules
    )


#: The Vega-Lite starter ladder.
VEGA_STARTER_LADDER: tuple[StarterRule, ...] = _starter_ladder(_VIS_DEFAULTS["vegaStarterLadder"])

#: The Autark starter ladder, over the input's layers that have geometry.
AUTK_STARTER_LADDER: tuple[StarterRule, ...] = _starter_ladder(_VIS_DEFAULTS["autkStarterLadder"])

#: The column names Simple View checks for images first, in this order.
IMAGE_COLUMNS: tuple[str, ...] = tuple(_VIS_DEFAULTS["imageColumns"])
#: The extensions an image URL has in a column not named above.
IMAGE_EXTENSIONS: tuple[str, ...] = tuple(_VIS_DEFAULTS["imageExtensions"])
#: The share of a column's non-empty values that must be images for it to
#: count as an image column.
IMAGE_MATCH_THRESHOLD: float = _VIS_DEFAULTS["imageMatchThreshold"]


# --- The preamble's node vocabulary ----------------------------------------
#
# The shared preamble describes Trill and the built-in templates. Both halves
# are rendered: the Trill block is a projection of ``docs/schemas/trill.v1.json``
# and every list of templates reads ``packages/curio.builtin@1/manifest.json``
# (description, editor, ports, interaction support). Templates are named by
# their labels. A node's ``type`` is a template id, and the per-run roster of
# available templates is the authority on ids, so the preamble lists none.

#: The built-in node manifest the rendered lists read.
BUILTIN_MANIFEST = "packages/curio.builtin@1/manifest.json"
#: Its package id, which a built-in template's namespaced id starts with.
BUILTIN_PACKAGE = BUILTIN_MANIFEST.split("/")[1].split("@", 1)[0]
#: The Trill schema the preamble's Trill block projects, by its repository
#: path (``utk_curio/shipped.py`` finds it).
TRILL_SCHEMA = "docs/schemas/trill.v1.json"
#: The Trill fields the preamble shows, per definition: what an agent reads in
#: a dataflow or writes into one. The rest of the schema is bookkeeping.
TRILL_PROMPT_FIELDS: dict[str, tuple[str, ...]] = {
    "dataflowBase": ("nodes", "edges", "name", "task", "scenarios"),
    "node": ("id", "type", "content", "goal", "title", "x", "y", "in", "out", "metadata"),
    # #662: a node's widgets are what an agent declares for its code to read,
    # and a copy's lineage is how two scenarios' levers pair. A Spatial Join's
    # operation and output, a Data Pool's conflict modes and a Simple View's
    # image column are what an agent sets on one.
    "nodeMetadata": ("keywords", "widgets", "copiedFrom", "spatialJoin", "dataPool", "simpleVis"),
    "edge": ("id", "source", "target", "type", "sourceHandle", "targetHandle", "metadata"),
    # Where a scenario sits on the canvas and where it came from are the
    # canvas's own bookkeeping, and its description is for people.
    "scenario": ("id", "name", "color", "nodes"),
}
#: The JSON Schema keywords a projection keeps.
_PROJECTED_KEYWORDS = ("type", "enum", "pattern", "items", "properties", "required")


def _builtin_template(manifest: dict, coord: str) -> dict:
    """A built-in template by its namespaced id, such as ``curio.builtin/autk-grammar``."""
    for template in manifest.get("templates", []):
        if f"{manifest.get('id', '').split('@')[0]}/{template.get('id')}" == coord:
            return template
    raise KeyError(coord)


def _resolve(schema: dict, node: dict, fields: tuple[str, ...] | None) -> tuple[dict, tuple[str, ...] | None]:
    """*node* with its ``$ref`` and ``allOf`` followed into one object, and the
    field list of the first definition on the way that ``TRILL_PROMPT_FIELDS``
    names."""
    while True:
        if "$ref" in node:
            rest = {k: v for k, v in node.items() if k != "$ref"}
            fields = fields or TRILL_PROMPT_FIELDS.get(node["$ref"].rsplit("/", 1)[-1])
            node = {**_definition(schema, node["$ref"]), **rest}
        elif "allOf" in node:
            merged = {k: v for k, v in node.items() if k != "allOf"}
            for part in node["allOf"]:
                part, part_fields = _resolve(schema, part, None)
                fields = fields or part_fields
                properties = {**part.get("properties", {}), **merged.get("properties", {})}
                merged = {**part, **merged, **({"properties": properties} if properties else {})}
            node = merged
        else:
            return node, fields


def _project(schema: dict, node: dict) -> dict:
    """*node* resolved, keeping only the projected keywords and, where
    ``TRILL_PROMPT_FIELDS`` names its definition, only those fields."""
    node, fields = _resolve(schema, node, None)
    out: dict = {}
    for keyword in _PROJECTED_KEYWORDS:
        if keyword not in node:
            continue
        value = node[keyword]
        if keyword == "properties":
            value = {n: _project(schema, value[n]) for n in (fields or value) if n in value}
        elif keyword == "required":
            value = [n for n in value if not fields or n in fields]
            if not value:
                continue
        elif keyword == "items":
            value = _project(schema, value)
        out[keyword] = value
    return out


def render_trill_block(schema: dict) -> str:
    """The preamble's Trill block: the schema's shape for the fields an agent uses."""
    dataflow = schema["properties"]["dataflow"]
    block = {
        "$schema": schema.get("$schema"),
        "type": "object",
        "properties": {"dataflow": _project(schema, dataflow)},
        "required": [f for f in schema.get("required", []) if f == "dataflow"],
    }
    return _compact_json(block)


def _compact_json(value, depth: int = 0) -> str:
    """JSON indented two spaces, with a list of plain values on one line."""
    pad = "  " * depth
    if isinstance(value, dict) and value:
        items = [f"{pad}  {json.dumps(k)}: {_compact_json(v, depth + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list) and any(isinstance(v, (dict, list)) for v in value):
        items = [f"{pad}  {_compact_json(v, depth + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v) for v in value) + "]"
    return json.dumps(value)


def _is_python_code(template: dict) -> bool:
    """Whether a node made from *template* is controlled through Python code."""
    return template.get("editor") == "code" and template.get("engine") != "javascript"


def _control(template: dict) -> str:
    editor = template.get("editor")
    if editor == "grammar":
        return "controllable through grammar."
    if _is_python_code(template):
        return "controllable through python code."
    if editor == "code":
        return "controllable through JavaScript code."
    return "uncontrollable."


def _types(port_list: list) -> str:
    types = [t for port in port_list for t in port.get("types", [])]
    return ", ".join(dict.fromkeys(types))


def _cardinality(port_list: list) -> str:
    return ", ".join(port.get("cardinality", "") for port in port_list)


def builtin_lists(manifest: dict) -> dict[str, str]:
    """The preamble's lists of built-in templates, one line per template in
    manifest order, keyed by the ``{{builtin.<list>}}`` field each fills. An
    input count is the connections a node accepts (``maxIncomingEdges``):
    one port's declared maximum, or one per port when there are several."""
    from utk_curio.backend.app.packages.application.templates import input_capacity

    rows: dict[str, list[str]] = {
        "nodes": [], "control": [], "inputs": [], "outputs": [],
        "input_count": [], "output_count": [], "interaction": [],
    }
    for template in manifest.get("templates", []):
        label = template.get("label") or template.get("id")
        inputs, outputs = template.get("inputPorts", []), template.get("outputPorts", [])
        rows["nodes"].append(f"- {label}: {template.get('description', '')}")
        rows["control"].append(f"- {label}: {_control(template)}")
        rows["inputs"].append(f"- {label}: {_types(inputs) or 'no input supported'}")
        rows["outputs"].append(f"- {label}: {_types(outputs) or 'no output supported'}")
        if inputs:
            single = inputs[0].get("cardinality") if len(inputs) == 1 else None
            capacity = input_capacity(len(inputs), single)
            rows["input_count"].append(f"- {label}: {'any number' if capacity is None else capacity}")
        if outputs:
            rows["output_count"].append(f"- {label}: {_cardinality(outputs)}")
        if template.get("bidirectional"):
            rows["interaction"].append(f"- {label}")
    return {f"builtin.{key}": "\n".join(lines) for key, lines in rows.items()}


# --- Tool bounds --------------------------------------------------------------
#
# What a read tool returns at most, which its description tells the model and
# its executor (``application/tools.py``) holds it to.

#: models.search: the most rows a call returns, and the most labels per row.
#: A Transformers checkpoint may name hundreds of classes.
MODELS_SEARCH_MAX_ROWS = 40
MODEL_LABELS_MAX = 40

#: How many notes one request carries: a package.install's ``notes``, and
#: the rows a mint keeps of any notes list
#: (``turns/delegates._notes_from_delegate_inputs``).
MAX_NOTES = 16


# --- Prompt fields ------------------------------------------------------------
#
# A page or prompt in ``agents/`` that states something the code owns holds a
# marker for it, ``{{field}}`` or ``{{field:argument}}``, which
# ``render_template`` fills from ``PROMPT_FIELDS`` when the backend renders the
# file (``agent_text``). Each field is one small function that reads its
# source when the file is rendered, so a change there reaches the agents with
# no edit to the text. ``{{include:<path>}}`` puts another page of the base
# entry there whole.

#: A marker: a field name, then the argument after a colon when it takes one.
_MARKER_RE = re.compile(r"\{\{([a-z][a-z0-9_.]*)(?::([^{}]+))?\}\}")


class PromptTemplateError(ValueError):
    """A page or prompt names a field the registry does not define, gives a
    field the wrong argument, includes a page that cannot be read or that
    includes it, or renders to text that still holds a marker."""


class _Sources:
    """The files the fields read, each loaded at most once per render, and
    the pages being rendered around the marker, outermost first."""

    def __init__(self, including: tuple[str, ...] = ()) -> None:
        self.including = including

    @cached_property
    def manifest(self) -> dict:
        from utk_curio import shipped

        return json.loads(shipped.path(BUILTIN_MANIFEST).read_text(encoding="utf-8"))

    @cached_property
    def trill(self) -> dict:
        from utk_curio import shipped

        return json.loads(shipped.path(TRILL_SCHEMA).read_text(encoding="utf-8"))

    @cached_property
    def autk(self) -> dict:
        return load_autk_schema()

    @cached_property
    def lists(self) -> dict[str, str]:
        return builtin_lists(self.manifest)

    def package(self, package_id: str) -> dict:
        """The manifest of the package Curio ships as *package_id*
        (``packages/<id>@<major>``, its highest major). KeyError when Curio
        ships none."""
        read = self.__dict__.setdefault("_packages", {})
        if package_id not in read:
            from utk_curio import shipped

            folders = [
                (int(folder.name.rsplit("@", 1)[1]), folder)
                for folder in shipped.path("packages").glob(f"{package_id}@*")
                if folder.name.rsplit("@", 1)[1].isdigit() and (folder / "manifest.json").is_file()
            ]
            if not folders:
                raise KeyError(package_id)
            read[package_id] = json.loads((max(folders)[1] / "manifest.json").read_text(encoding="utf-8"))
        return read[package_id]


@dataclass(frozen=True)
class PromptField:
    """One fact a prompt states from code. ``render`` takes the sources, and
    the marker's argument as well when the field ``takes_arg``."""

    render: Callable[..., str]
    takes_arg: bool = False


def _builtin_list(key: str) -> PromptField:
    """One of ``builtin_lists``: every built-in template, one line each."""
    return PromptField(lambda src: src.lists[key])


def _agent_name(_src: _Sources, agent_id: str) -> str:
    """The display name of an agent Curio ships, by its id, from its manifest
    (``builtin.list_builtin_manifests``)."""
    from utk_curio.backend.app.agents.domain import builtin

    for manifest in builtin.list_builtin_manifests():
        if manifest.agent_id == agent_id:
            return manifest.name
    raise PromptTemplateError(f"no built-in agent has the id {agent_id!r}")


def _template_label(src: _Sources, coord: str) -> str:
    """A template's label, by ``<package id>/<template id>``: a built-in
    one's, or one's of a package Curio ships, such as Scout's charts
    (``packages/curio.scout@1``)."""
    package_id = coord.rpartition("/")[0]
    where = BUILTIN_MANIFEST if package_id == BUILTIN_PACKAGE else f"packages/{package_id}"
    try:
        manifest = src.manifest if package_id == BUILTIN_PACKAGE else src.package(package_id)
        return _builtin_template(manifest, coord)["label"]
    except KeyError:
        raise PromptTemplateError(f"{where} has no labelled template {coord!r}") from None


def _input_handles(_src: _Sources) -> str:
    """The handles of a node's input circles, first ones then an ellipsis
    (``slot_handle_id``)."""
    from utk_curio.backend.app.execution.workflow_spec import slot_handle_id

    return ", ".join(f'"{slot_handle_id(k)}"' for k in range(3)) + ", ..."


def _input_chip(_src: _Sources, text: str) -> str:
    """The chip node code reads an input by: ``0`` is input_0, ``0.height``
    a column of it, ``0:roads`` the layer of it named roads and
    ``0:roads.height`` a column of that layer (``reference_text``)."""
    from utk_curio.backend.app.execution.code_references import (
        input_reference_inner,
        reference_text,
    )

    head, _, column = text.partition(".")
    slot, colon, layer = head.partition(":")
    if not slot.strip().isdigit() or (colon and not layer):
        raise PromptTemplateError(
            f"an input chip names a circle number, then a layer after a colon and a column after a dot "
            f"if it reads one, not {text!r}"
        )
    return reference_text(input_reference_inner(int(slot), column or None, layer or None))


def _stacked_column_chip(_src: _Sources, column: str) -> str:
    """The chip a Vega-Lite spec names a column of every input's rows stacked
    by, ``[!! inputs.<column> !!]`` (``stacked_reference_inner``)."""
    from utk_curio.backend.app.execution.code_references import reference_text, stacked_reference_inner

    return reference_text(stacked_reference_inner(column))


def _selection_chip(_src: _Sources, name: str) -> str:
    """The reference a node's code places its selection tag *name* by
    (``selection_reference_inner``)."""
    from utk_curio.backend.app.execution.code_references import reference_text, selection_reference_inner

    return reference_text(selection_reference_inner(_widget_name(name)))


def _selection_id_cap(_src: _Sources) -> str:
    """The most ids one selection tag holds (``SELECTION_ID_CAP``), as ``10,000``."""
    from utk_curio.backend.app.execution.code_references import SELECTION_ID_CAP

    return f"{SELECTION_ID_CAP:,}"


def _stacked_dataset_chip(_src: _Sources) -> str:
    """The chip a Vega-Lite spec names every input's rows stacked by,
    ``[!! inputs !!]`` (``STACKED_DATASET``, ``reference_text``)."""
    from utk_curio.backend.app.execution.code_references import STACKED_DATASET, reference_text

    return reference_text(STACKED_DATASET)


def _scenario_chip(_src: _Sources, what: str) -> str:
    """A chip a Vega-Lite or Autark spec writes its scenarios with: ``colors``,
    ``text_colors`` or ``order`` for the scale or the names of every input's
    box, ``input.1`` for the color of input_1's box (``reference_text``)."""
    from utk_curio.backend.app.execution.code_references import SCENARIO_LISTS, reference_text

    if what in SCENARIO_LISTS:
        return reference_text(f"scenario {what}")
    prefix, _, slot = what.partition(".")
    if prefix != "input" or not slot.isdigit():
        raise PromptTemplateError(f"a scenario chip is {', '.join(SCENARIO_LISTS)} or input.<k>, not {what!r}")
    return reference_text(f"scenario input_{int(slot)}")


def _widget_kinds(_src: _Sources) -> str:
    """The kinds a widget can be (``WIDGET_KINDS``), as ``a, b ... or z``."""
    from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

    return _join(list(WIDGET_KINDS), "or")


def _widget_name(name: str) -> str:
    """*name*, of the ``WIDGET_NAME_RE`` shape matched whole, as the Widgets
    tab matches it."""
    from utk_curio.backend.app.execution.code_references import WIDGET_NAME_RE

    if not WIDGET_NAME_RE.fullmatch(name):
        raise PromptTemplateError(f"{name!r} is not a widget name")
    return name


def _widget_reference(_src: _Sources, name: str) -> str:
    """The reference code places a node's widget *name* by (``reference_text``)."""
    from utk_curio.backend.app.execution.code_references import reference_text

    return reference_text(_widget_name(name))


def _shared_reference(_src: _Sources, name: str) -> str:
    """The reference any node's code places the Parameter node *name* by:
    its shared tag (``SHARED_PREFIX``)."""
    from utk_curio.backend.app.execution.code_references import SHARED_PREFIX, reference_text

    return reference_text(SHARED_PREFIX + _widget_name(name))


def _not_code(src: _Sources) -> str:
    """The built-in templates whose nodes hold no Python or JavaScript code
    (``_control`` calls them uncontrollable or grammar), one ``- <label>`` line
    each: there is no code for the coherence check to judge."""
    return "\n".join(
        f"- {template.get('label') or template.get('id')}"
        for template in src.manifest.get("templates", [])
        if template.get("editor") != "code"
    )


def _note_palette(_src: _Sources) -> str:
    """The colour names a node's appearance accepts (``NOTE_PALETTE``)."""
    from utk_curio.backend.app.packages.application.note_palette import NOTE_PALETTE

    return ", ".join(NOTE_PALETTE.colors)


def _web_calls_per_run(_src: _Sources) -> str:
    """How many web calls one run may make (``MAX_CALLS_PER_RUN``)."""
    from utk_curio.backend.app.common.egress_policy import MAX_CALLS_PER_RUN

    return str(MAX_CALLS_PER_RUN)


def _rows_per_lane(_src: _Sources) -> str:
    """How many rows each lane of a candidates card holds."""
    from utk_curio.backend.app.agents.domain.content import _CANDIDATES_MAX_ROWS_PER_LANE

    return str(_CANDIDATES_MAX_ROWS_PER_LANE)


def _runtime_block_keys(_src: _Sources) -> str:
    """The keys of a node row's ``runtime`` block, as ``{a, b, ...}``."""
    from utk_curio.backend.app.agents.domain.node_context import RUNTIME_BLOCK_KEYS

    return "{" + ", ".join(RUNTIME_BLOCK_KEYS) + "}"


def _input_kind_several(_src: _Sources) -> str:
    """The ``inputContract`` kind of several circles, one value each, quoted."""
    from utk_curio.backend.app.agents.domain.input_contract import KIND_SEVERAL

    return json.dumps(KIND_SEVERAL)


def _input_kind_gathered(_src: _Sources) -> str:
    """The ``inputContract`` kind of one circle holding several edges' values, quoted."""
    from utk_curio.backend.app.agents.domain.input_contract import KIND_GATHERED

    return json.dumps(KIND_GATHERED)


def _input_kind_single(_src: _Sources) -> str:
    """The ``inputContract`` kind of one circle that is one value, quoted."""
    from utk_curio.backend.app.agents.domain.input_contract import KIND_SINGLE

    return json.dumps(KIND_SINGLE)


def _vega_runtime_field(_src: _Sources, name: str) -> str:
    """A field Curio adds to the rows a Vega-Lite node reads, quoted; the
    argument must be one of ``RUNTIME_FIELDS``."""
    from utk_curio.backend.app.agents.domain.document_validation import RUNTIME_FIELDS

    if name not in RUNTIME_FIELDS:
        raise PromptTemplateError(f"{name!r} is not one of RUNTIME_FIELDS {RUNTIME_FIELDS}")
    return json.dumps(name)


def _handler_pattern(_src: _Sources) -> str:
    """The pattern a package backend handler's name must match."""
    from utk_curio.backend.app.packages.domain.backend_contract import HANDLER_NAME_RE

    return HANDLER_NAME_RE.pattern


def _timeout_classes(_src: _Sources) -> str:
    """The timeout classes a handler may declare, quoted, as ``"a"|"b"``."""
    from utk_curio.backend.app.packages.domain.backend_contract import TIMEOUT_CLASSES

    return "|".join(json.dumps(name) for name in TIMEOUT_CLASSES)


def _server_code_permission(_src: _Sources) -> str:
    """The permission a package with backend code declares."""
    from utk_curio.backend.app.packages.domain.backend_contract import PERMISSION_SERVER_CODE

    return PERMISSION_SERVER_CODE


def _server_network_permission(_src: _Sources) -> str:
    """The permission a package whose backend code reaches the network declares."""
    from utk_curio.backend.app.packages.domain.backend_contract import PERMISSION_SERVER_NETWORK

    return PERMISSION_SERVER_NETWORK


def _data_dir_env(_src: _Sources) -> str:
    """The environment variable that names a handler's persistent directory."""
    from utk_curio.backend.app.packages.domain.backend_contract import DATA_DIR_ENV

    return DATA_DIR_ENV


def _timeout_class_choices(_src: _Sources) -> str:
    """The timeout classes a handler may declare, as ``a | b``, where a
    JSON string lists them."""
    from utk_curio.backend.app.packages.domain.backend_contract import TIMEOUT_CLASSES

    return " | ".join(TIMEOUT_CLASSES)


def _note_palette_choices(_src: _Sources) -> str:
    """The colour names a node's appearance accepts (``NOTE_PALETTE``), as
    ``a|b|c``, where a JSON string lists them."""
    from utk_curio.backend.app.packages.application.note_palette import NOTE_PALETTE

    return "|".join(NOTE_PALETTE.colors)


def _suggested_prompt_chars(_src: _Sources) -> str:
    """How many characters a suggested prompt may hold."""
    from utk_curio.backend.app.agents.domain.content import _PROMPT_MAX_CHARS

    return str(_PROMPT_MAX_CHARS)


def _suggested_prompt_alternatives(_src: _Sources) -> str:
    """How many alternatives a suggested prompts block may hold."""
    from utk_curio.backend.app.agents.domain.content import _MAX_ALTERNATIVES

    return str(_MAX_ALTERNATIVES)


def _candidate_source_types(_src: _Sources) -> str:
    """The source types a candidate row may name, as ``a|b|c``."""
    from utk_curio.backend.app.agents.domain.content import _CANDIDATE_SOURCE_TYPES

    return "|".join(_CANDIDATE_SOURCE_TYPES)


def _candidate_name_chars(_src: _Sources) -> str:
    """How many characters a candidate row's name may hold."""
    from utk_curio.backend.app.agents.domain.content import _CANDIDATE_NAME_MAX_CHARS

    return str(_CANDIDATE_NAME_MAX_CHARS)


def _candidate_text_chars(_src: _Sources) -> str:
    """How many characters each other text field of a candidate row may hold."""
    from utk_curio.backend.app.agents.domain.content import _CANDIDATE_TEXT_MAX_CHARS

    return str(_CANDIDATE_TEXT_MAX_CHARS)


def _wire_name(_src: _Sources, tool_id: str) -> str:
    """The name a run on native tools calls the tool *tool_id* by
    (``tool_names.wire_name``)."""
    from utk_curio.backend.app.agents.domain.tool_names import tool_id_of, wire_name

    if tool_id_of(wire_name(tool_id)) != tool_id:
        raise PromptTemplateError(f"{tool_id!r} is not a tool id")
    return wire_name(tool_id)


def _delegate_tool(_src: _Sources) -> str:
    """The native name of delegation (``tool_names.DELEGATE_TOOL``)."""
    from utk_curio.backend.app.agents.domain.tool_names import DELEGATE_TOOL

    return DELEGATE_TOOL


def _include(src: _Sources, page: str) -> str:
    """Another page of the base entry, by its path there, rendered, to include
    whole without its final line breaks (``agent_text.include``)."""
    from utk_curio.backend.app.agents.domain import agent_text

    return agent_text.include(page, src.including)


_NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _number(n: int) -> str:
    return _NUMBER_WORDS[n] if 0 <= n < len(_NUMBER_WORDS) else str(n)


def _join(words: list[str], last: str) -> str:
    """``a, b and c``, with *last* as the final joiner."""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" {last} " + words[-1]


def _role_phrase(role: str, count: CountRange) -> str:
    """A role a starter rule needs: the role alone for at least one column."""
    if count.most is None:
        return role if count.least == 1 else f"{_number(count.least)} or more {role}"
    if count.most == count.least:
        return f"exactly {_number(count.least)} {role}"
    return f"{_number(count.least)} to {_number(count.most)} {role}"


def _layer_phrase(count: CountRange) -> str:
    """The layers an Autark starter rule needs, such as ``two or more layers``."""
    noun = "layer" if count.most == 1 else "layers"
    if count.most is None:
        return f"{_number(count.least)} or more {noun}"
    if count.most == count.least:
        return f"{_number(count.least)} {noun}"
    return f"{_number(count.least)} to {_number(count.most)} {noun}"


def render_starter_ladder(rules: tuple[StarterRule, ...]) -> str:
    """A starter ladder, one ``- <condition> -> <produces>: <description>`` line
    per rule in ladder order. The condition joins the layers and the column
    roles the rule needs with ``+``."""
    lines = []
    for rule in rules:
        terms = [_layer_phrase(rule.layers)] if rule.layers else []
        terms += [_role_phrase(role, count) for role, count in rule.columns]
        lines.append(f"- {' + '.join(terms) or 'any input'} -> {rule.produces}: {rule.description}")
    return "\n".join(lines)


def _dtype_roles(_src: _Sources) -> str:
    """Which pandas dtypes give which column role, in ``DTYPE_ROLES`` order."""
    parts = []
    for entry in DTYPE_ROLES:
        subjects = []
        if entry.names:
            subjects.append(_join([f"`{name}`" for name in entry.names], "and"))
        if entry.prefixes:
            subjects.append("a dtype that starts with " + _join([f"`{p}`" for p in entry.prefixes], "or"))
        plural = len(entry.names) > 1 or len(subjects) > 1
        parts.append(f"{' and '.join(subjects)} {'are' if plural else 'is'} {entry.role}")
    return "; ".join(parts)


def _image_column(_src: _Sources, name: str) -> str:
    """One of ``IMAGE_COLUMNS``, quoted; the argument must be one of them."""
    if name not in IMAGE_COLUMNS:
        raise PromptTemplateError(f"{name!r} is not one of IMAGE_COLUMNS {IMAGE_COLUMNS}")
    return json.dumps(name)


def _image_extensions(_src: _Sources) -> str:
    """``IMAGE_EXTENSIONS`` as ``.png, .jpg ... or .avif``."""
    return _join([f".{extension}" for extension in IMAGE_EXTENSIONS], "or")


def _image_threshold(_src: _Sources) -> str:
    """``IMAGE_MATCH_THRESHOLD`` as a percentage."""
    return f"{IMAGE_MATCH_THRESHOLD:.0%}"


#: Every field a page or prompt may name, by the name its marker uses.
PROMPT_FIELDS: dict[str, PromptField] = {
    "trill.schema": PromptField(lambda src: render_trill_block(src.trill)),
    **{key: _builtin_list(key) for key in (
        "builtin.nodes", "builtin.control", "builtin.inputs", "builtin.outputs",
        "builtin.input_count", "builtin.output_count", "builtin.interaction",
    )},
    "inputs.handles": PromptField(_input_handles),
    "inputs.chip": PromptField(_input_chip, takes_arg=True),
    "inputs.stacked": PromptField(_stacked_dataset_chip),
    "inputs.stacked_column": PromptField(_stacked_column_chip, takes_arg=True),
    "selections.reference": PromptField(_selection_chip, takes_arg=True),
    "selections.id_cap": PromptField(_selection_id_cap),
    "scenarios.chip": PromptField(_scenario_chip, takes_arg=True),
    "widgets.kinds": PromptField(_widget_kinds),
    "widgets.reference": PromptField(_widget_reference, takes_arg=True),
    "widgets.shared": PromptField(_shared_reference, takes_arg=True),
    "builtin.not_code": PromptField(_not_code),
    "autk.grammar": PromptField(
        lambda src: render_autk_region(src.autk, _template_label(src, AUTK_TEMPLATE))
    ),
    "agent.name": PromptField(_agent_name, takes_arg=True),
    "template.label": PromptField(_template_label, takes_arg=True),
    "note.palette": PromptField(_note_palette),
    "egress.calls_per_run": PromptField(_web_calls_per_run),
    "candidates.rows_per_lane": PromptField(_rows_per_lane),
    "node_context.runtime_keys": PromptField(_runtime_block_keys),
    "input_contract.several": PromptField(_input_kind_several),
    "input_contract.gathered": PromptField(_input_kind_gathered),
    "input_contract.single": PromptField(_input_kind_single),
    "vega.runtime_field": PromptField(_vega_runtime_field, takes_arg=True),
    "backend.handler_pattern": PromptField(_handler_pattern),
    "backend.timeout_classes": PromptField(_timeout_classes),
    "backend.server_code_permission": PromptField(_server_code_permission),
    "backend.server_network_permission": PromptField(_server_network_permission),
    "backend.data_dir_env": PromptField(_data_dir_env),
    "backend.timeout_class_choices": PromptField(_timeout_class_choices),
    "note.palette_choices": PromptField(_note_palette_choices),
    "suggested_prompts.max_chars": PromptField(_suggested_prompt_chars),
    "suggested_prompts.alternatives": PromptField(_suggested_prompt_alternatives),
    "candidates.source_types": PromptField(_candidate_source_types),
    "candidates.name_chars": PromptField(_candidate_name_chars),
    "candidates.text_chars": PromptField(_candidate_text_chars),
    "models.search_max_rows": PromptField(lambda _src: str(MODELS_SEARCH_MAX_ROWS)),
    "models.max_labels": PromptField(lambda _src: str(MODEL_LABELS_MAX)),
    "notes.max": PromptField(lambda _src: str(MAX_NOTES)),
    "tools.wire_name": PromptField(_wire_name, takes_arg=True),
    "tools.delegate": PromptField(_delegate_tool),
    "include": PromptField(_include, takes_arg=True),
    "vega.schema_url": PromptField(lambda _src: VEGA_SCHEMA_URL),
    "vega.starter_ladder": PromptField(lambda _src: render_starter_ladder(VEGA_STARTER_LADDER)),
    "autk.starter_ladder": PromptField(lambda _src: render_starter_ladder(AUTK_STARTER_LADDER)),
    "starter.dtype_roles": PromptField(_dtype_roles),
    "image.columns": PromptField(lambda _src: _either(IMAGE_COLUMNS)),
    "image.column": PromptField(_image_column, takes_arg=True),
    "image.extensions": PromptField(_image_extensions),
    "image.threshold": PromptField(_image_threshold),
}


def render_template(text: str, name: str = "the template", *, including: tuple[str, ...] = ()) -> str:
    """*text* with every marker filled from ``PROMPT_FIELDS``. *including*
    holds the pages of the base entry being rendered around it, outermost
    first, for ``{{include:<path>}}`` to refuse a page that includes itself.

    Raises ``PromptTemplateError`` on a field the registry does not define, on
    a marker whose argument does not fit its field, and on any ``{{`` left in
    the result."""
    sources = _Sources(including)

    def fill(match: re.Match) -> str:
        key, argument = match.group(1), match.group(2)
        field = PROMPT_FIELDS.get(key)
        if field is None:
            raise PromptTemplateError(f"{name} names {match.group(0)}, which no prompt field defines")
        if field.takes_arg != (argument is not None):
            needs = "an argument after a colon" if field.takes_arg else "no argument"
            raise PromptTemplateError(f"{name} names {match.group(0)}, but {key} takes {needs}")
        return field.render(sources, argument) if field.takes_arg else field.render(sources)

    text = _MARKER_RE.sub(fill, text)
    if "{{" in text:
        at = text.index("{{")
        raise PromptTemplateError(f"{name} still holds {text[at:at + 40]!r} once rendered")
    return text


# --- System turn composition -------------------------------------------------
#
# Every system turn, for an attached run or a delegated run, is composed here
# from fixed slots in a fixed order. A slot holds one
# kind of text with one owner:
#
#   preamble       the built-ins' shared preamble, or a definition's own; optional
#   instruction    exactly one: the agent's, the invoked mode's, or an edited intent
#   configuration  the catalog settings the run reads, framed as data
#   tool-protocol  how to request a tool, and which tools are granted
#   runtime        blocks composed per run: template rosters, the delegation paragraph
#
# A run selects its instruction; it never appends to one. Everything a user
# wrote (an edited intent, a setting) comes before every runtime-owned slot, so
# none of it can strip or pose as one.


@dataclass(frozen=True)
class SystemSlot:
    kind: str
    text: str


def compose_system(
    *,
    instruction: str,
    preamble: str | None = None,
    configuration: str | None = None,
    tool_protocol: str | None = None,
    runtime: tuple[str | None, ...] | list[str | None] = (),
) -> tuple[SystemSlot, ...]:
    """The system turn's slots in order, each runtime block its own slot.
    Empty pieces are left out."""
    pieces = [
        ("preamble", preamble),
        ("instruction", instruction),
        ("configuration", configuration),
        ("tool-protocol", tool_protocol),
        *(("runtime", block) for block in runtime),
    ]
    return tuple(SystemSlot(kind, text) for kind, text in pieces if text)


def join_system(slots: tuple[SystemSlot, ...]) -> str:
    """The slots as one system message."""
    return "\n\n".join(slot.text for slot in slots)


def system_message(slots: tuple[SystemSlot, ...]) -> dict:
    """The system turn as a message: its joined text as ``content``, and the
    slots themselves, which a provider that takes several system blocks
    receives one by one (``providers``)."""
    return {
        "role": "system",
        "content": join_system(slots),
        "slots": [{"kind": slot.kind, "text": slot.text} for slot in slots],
    }


# --- Catalog settings --------------------------------------------------------
#
# A catalog setting is a value the user owns: a domain decision that changes
# with their work, such as the types a keyword can take. Each key is defined
# here once, with the JSON Schema its value must satisfy and how a run
# receives it; the value Curio ships is a page of the base entry. A definition
# declares the keys a run reads, per capability
# (``capabilities[].requiredConfig``) or for every run
# (``inputs.requiredConfig``); those keys fill the run's configuration slot.
# Values are stored per account and edited in the Agent Catalog.


@dataclass(frozen=True)
class CatalogSetting:
    key: str
    label: str
    description: str
    #: JSON Schema of the value.
    schema: dict
    #: The page of the base entry that holds the value Curio ships, as its one
    #: block fenced as json.
    default_page: str
    #: The value as lines of the configuration slot.
    render: Callable[[object], str]
    #: The entry field that must be unique, for a list of objects.
    unique_by: str | None = None

    @property
    def default(self) -> object:
        """The value Curio ships: its page's json block, read as an agent
        reads the page (``agent_text``), a fresh value on every read."""
        from utk_curio.backend.app.agents.domain import agent_text

        page = self.default_page
        return agent_text.json_block(agent_text.page_text(page), agent_text.PAGE_PREFIX + page)


def _one_line(max_length: int) -> dict:
    return {"type": "string", "minLength": 1, "maxLength": max_length, "pattern": "^[^\\r\\n]*$"}


def _render_keyword_types(value) -> str:
    lines = []
    for entry in value:
        line = f"- {entry['name']}: {entry['description']}"
        examples = entry.get("examples") or []
        if examples:
            line += " Examples: " + ", ".join(json.dumps(e, ensure_ascii=False) for e in examples) + "."
        lines.append(line)
    return "\n".join(lines)


#: The page of the base entry that holds the keyword types Curio ships.
KEYWORD_TYPES_PAGE = "keyword-types.md"

KEYWORD_TYPES = CatalogSetting(
    key="keywordTypes",
    label="Keyword types",
    description=(
        "The types a keyword in a dataflow's description can take. Keywords are "
        "extracted with these types and bound to the nodes and edges they describe."
    ),
    schema={
        "type": "array",
        "minItems": 1,
        "maxItems": 30,
        "items": {
            "type": "object",
            "required": ["name", "description"],
            "additionalProperties": False,
            "properties": {
                "name": _one_line(40),
                "description": _one_line(400),
                "examples": {"type": "array", "maxItems": 12, "items": _one_line(80)},
            },
        },
    },
    default_page=KEYWORD_TYPES_PAGE,
    render=_render_keyword_types,
    unique_by="name",
)

#: Every catalog setting, by key, in the order the configuration slot lists them.
CATALOG_SETTINGS: dict[str, CatalogSetting] = {s.key: s for s in (KEYWORD_TYPES,)}

def configuration_frame() -> str:
    """The configuration slot's first line, which frames the values as data:
    the section ``configuration`` of the base entry's ``frames.md``."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin

    return agent_text.section(builtin.FRAMES_FILE, "configuration")


def render_configuration(values: dict) -> str | None:
    """The configuration slot for *values* (key to value), in registry order;
    ``None`` when no registered key is among them."""
    sections = [
        f"{setting.label}:\n{setting.render(values[key])}"
        for key, setting in CATALOG_SETTINGS.items()
        if key in values
    ]
    if not sections:
        return None
    return "\n\n".join([configuration_frame(), *sections])
