"""The single source for contracts both the model and the code must agree on.

A contract is something the code enforces: change it and the model, or the
other half of the code, is wrong about what the system accepts. Each one is
defined here exactly once. Python imports it from this module; every other
consumer receives a GENERATED copy, rendered by the functions below and
written by ``scripts/generate_contracts.py``.

``GENERATED_OUTPUTS`` is the one registry of committed outputs. The CLI writes
each entry and ``test_generated_contracts`` re-renders each entry and fails on
any difference, so a hand edit to an output, or a change here that was never
regenerated, turns the suite red.

Pure and importable from an installed wheel: no I/O at import time, nothing
beyond the standard library.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

#: Where this module lives, relative to the repository root. Named in every
#: generated header so a reader of an output knows what to edit instead.
SOURCE_MODULE = "utk_curio/backend/app/agents/contracts.py"
#: The CLI that writes the outputs, named in the same header.
GENERATOR = "scripts/generate_contracts.py"


# --- Render outcome vocabulary ---------------------------------------------
#
# A renderer Curio owns (frontend ``renderOutcome``) counts what it drew and,
# when it drew nothing, reports a journal record whose ``kind`` is
# ``empty-render:<cause>``. The cause decides who is at fault, and therefore
# whether the harness asks for a corrected document or waits on the upstream.

#: The kind a renderer stamps on an empty render, with its cause appended.
EMPTY_RENDER_KIND = "empty-render"


@dataclass(frozen=True)
class RenderCause:
    """One reason a render drew nothing."""

    name: str
    #: Whether rewriting THIS node's document is the repair. False only when
    #: nothing arrived from upstream, so no document could have drawn a thing.
    document_at_fault: bool
    description: str


CAUSE_NO_LAYERS = "no-layers"
CAUSE_NO_INPUT_ROWS = "no-input-rows"
CAUSE_NOTHING_DRAWN = "nothing-drawn"
CAUSE_EMPTY_SOURCE = "empty-source"

#: Every cause a renderer can report. The order is the vocabulary's own and new
#: causes are appended; which cause wins when several apply is decided by the
#: rule order in ``renderOutcome``.
RENDER_CAUSES: tuple[RenderCause, ...] = (
    RenderCause(
        CAUSE_NO_LAYERS, True,
        "Every layer the document asks for names data the dataflow does not produce.",
    ),
    RenderCause(
        CAUSE_NO_INPUT_ROWS, False,
        "Zero rows arrived from upstream, so the upstream node is what must change.",
    ),
    RenderCause(
        CAUSE_NOTHING_DRAWN, True,
        "Rows arrived and the document drew none of them.",
    ),
    RenderCause(
        CAUSE_EMPTY_SOURCE, True,
        "The node's own data sources loaded zero rows.",
    ),
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


# --- Autark grammar ---------------------------------------------------------
#
# The grammar is defined upstream: autk-grammar generates a JSON Schema from its
# TypeScript types, and ``schemas/autk-grammar.v1.json`` is a byte-for-byte copy
# of the released file (``scripts/sync_autk_schema.py``). The renderers below
# read that file. The one Curio fact they add is how a node names its input.

#: The vendored schema, beside this module so an installed wheel carries it.
AUTK_SCHEMA_PATH = Path(__file__).parent / "schemas" / "autk-grammar.v1.json"
#: The template whose content is an Autark document.
AUTK_TEMPLATE = "curio.builtin/autk-grammar"
#: The layer an Autark node makes of its own input when that input is a single
#: frame. An upstream Autark node's layers keep their table names instead.
AUTK_UPSTREAM_LAYER = "upstream"


def load_autk_schema(path: Path = AUTK_SCHEMA_PATH) -> dict:
    """The vendored Autark schema, parsed."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _definition(schema: dict, ref: str) -> dict:
    """A definition by ``$ref`` (escaped or not) or by bare name."""
    return schema.get("definitions", {}).get(unquote(ref.rsplit("/", 1)[-1]), {})


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
    layers, layer_required = map_layers(schema)
    common, either = _compute_required(schema)
    source_types = _definition(schema, "DataSourceSpec").get("properties", {}).get("type", {}).get("enum", [])
    example_layer = ", ".join(f'"{field}": "{AUTK_UPSTREAM_LAYER}"' for field in layer_required)
    return (
        f'an Autark grammar JSON document, such as the map {{"map": {{"{layers}": [{{{example_layer}}}]}}}}, '
        f'where "{AUTK_UPSTREAM_LAYER}" is this node\'s own input. A document names at least one of '
        f"{_either(autk_families(schema))}; a plot needs {_every(_plot_required(schema))}; "
        f"a compute pass needs {_every(common)}, plus {_either(either)}; "
        f'a loader is {{"data": [{{"type": "{source_types[0] if source_types else ""}", ...}}]}}'
    )


def render_autk_region(schema: dict, legacy_name: str) -> str:
    """The preamble's section on Autark documents, from the schema."""
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

    lines = [
        f"{legacy_name} nodes ({AUTK_TEMPLATE}) are controlled through grammar: their content "
        f"is one JSON document that follows the Autark grammar's JSON Schema ({schema.get('$id')}). "
        f"Keys the schema does not name are allowed. A document names at least one of "
        f"{_either(autk_families(schema))}.",
        f'In the document, the node\'s own input is the layer named "{AUTK_UPSTREAM_LAYER}"; the '
        f'layers an upstream {legacy_name} node produces keep their table names, such as '
        f'"table_osm_buildings".',
        "",
        f'- "data": {props.get("data", {}).get("description", "")} Each entry\'s "type" selects its fields:',
    ]
    for values, definition in _variants(schema, "DataSourceSpec", "type"):
        required = [f for f in definition.get("required", []) if f != "type"]
        lines.append(
            f"  - {_either(values)}: {definition.get('description', '')}"
            + (f" Requires {_every(required)}." if required else "")
        )
    lines += [
        f'- "compute": {props.get("compute", {}).get("description", "")} '
        f"{compute.get('description', '')} Every pass also requires {_every(common)}.",
    ]
    for field in common:
        description = compute_fields.get(field, {}).get("description")
        if description:
            lines.append(f'  - "{field}": {description}')
    lines += [
        f"  - A uniform is written inline or as {{\"fromFeature\": {{...}}}}. {directive.get('description', '')} "
        f"Its \"iterate\": {iterate.get('description', '')}".rstrip(),
        f'- "map": {props.get("map", {}).get("description", "")} Requires {_every(_definition(schema, "MapSpec").get("required", []))}, '
        f'and each entry of "{layers}" requires {_every(layer_required)}. '
        f'"colorMapInterpolator" is one of {_either(interpolators)}.',
        f'- "plot": {props.get("plot", {}).get("description", "")} Every plot requires '
        f'{_every(_plot_required(schema))}; "mark" selects the rest:',
    ]
    for values, definition in _variants(schema, "PlotSpec", "mark"):
        lines.append(f"  - {_either(values)}: {definition.get('description', '')}")
    return "\n".join(lines)


# --- Built-in templates in the preamble -----------------------------------
#
# The preamble still names nodes by their legacy ids (``VIS_VEGA``), and those
# lists are hand-written except where a row is generated from the built-in
# manifest below. A template's row reads its description, editor, ports and
# interaction support from ``packages/curio.builtin@1/manifest.json``.

#: Where the prompt files live, relative to the repository root.
PROMPTS_DIR = "utk_curio/llm-prompts"
#: The built-in node manifest the generated rows read.
BUILTIN_MANIFEST = "packages/curio.builtin@1/manifest.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _builtin_template(manifest: dict, coord: str) -> dict:
    """A built-in template by its namespaced id, such as ``curio.builtin/autk-grammar``."""
    for template in manifest.get("templates", []):
        if f"{manifest.get('id', '').split('@')[0]}/{template.get('id')}" == coord:
            return template
    raise KeyError(coord)


def _control(template: dict) -> str:
    editor = template.get("editor")
    if editor == "grammar":
        return "controllable through grammar."
    if editor == "code":
        return "controllable through JavaScript code." if template.get("engine") == "js" else "controllable through python code."
    return "uncontrollable."


def _types(port_list: list) -> str:
    types = [t for port in port_list for t in port.get("types", [])]
    return ", ".join(dict.fromkeys(types)) if types else "none"


def _cardinality(port_list: list) -> str:
    return ", ".join(port.get("cardinality", "") for port in port_list) or "0"


def preamble_fields(manifest: dict, schema: dict) -> dict:
    """The generated values ``default_preamble.template.txt`` names."""
    from utk_curio.backend.app.execution.workflow_spec import NAMESPACED_TO_LEGACY

    legacy = NAMESPACED_TO_LEGACY[AUTK_TEMPLATE]
    template = _builtin_template(manifest, AUTK_TEMPLATE)
    return {
        "autk.node": f"- {legacy}: {template.get('description', '')}",
        "autk.control": f"- {legacy}: {_control(template)}",
        "autk.inputs": f"- {legacy}: {_types(template.get('inputPorts', []))}",
        "autk.outputs": f"- {legacy}: {_types(template.get('outputPorts', []))}",
        "autk.input_count": f"- {legacy}: {_cardinality(template.get('inputPorts', []))}",
        "autk.output_count": f"- {legacy}: {_cardinality(template.get('outputPorts', []))}",
        "autk.interaction": f"- {legacy}" if template.get("bidirectional") else "",
        "autk.grammar": render_autk_region(schema, legacy),
    }


def render_default_preamble() -> str:
    """``default_preamble.txt``: its template with every ``{{field}}`` filled."""
    root = _repo_root()
    text = (root / PROMPTS_DIR / "default_preamble.template.txt").read_text(encoding="utf-8")
    manifest = json.loads((root / BUILTIN_MANIFEST).read_text(encoding="utf-8"))
    for key, value in preamble_fields(manifest, load_autk_schema()).items():
        marker = "{{" + key + "}}"
        if marker not in text:
            raise KeyError(f"default_preamble.template.txt has no {marker}")
        text = text.replace(marker, value)
    return text


def render_autk_grammar_ts() -> str:
    """``src/generated/autkGrammar.ts``: the grammar's families and the input layer name."""
    names = [_ts_string(f) for f in autk_families(load_autk_schema())]
    families = f"export const AUTK_FAMILIES = [{', '.join(names)}] as const;\n"
    if len(families) > 81:  # prettier's 80 columns: one name per line instead
        families = "export const AUTK_FAMILIES = [\n" + "".join(f"  {n},\n" for n in names) + "] as const;\n"
    return (
        _ts_header()
        + "\n"
        + "/** The top-level keys an Autark document can name, from the vendored schema. */\n"
        + families
        + "\n"
        + "export type AutkFamily = (typeof AUTK_FAMILIES)[number];\n"
        + "\n"
        + "/** The layer an Autark node makes of its own input when that input is a single frame. */\n"
        + f"export const AUTK_UPSTREAM_LAYER = {_ts_string(AUTK_UPSTREAM_LAYER)};\n"
    )


# --- Renderers -------------------------------------------------------------


def _ts_header() -> str:
    return (
        f"// Generated by {GENERATOR} from\n"
        f"// {SOURCE_MODULE}. Do not edit by hand: change the\n"
        f"// source module and run `python {GENERATOR}`.\n"
    )


def _ts_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_render_causes_ts() -> str:
    """``src/generated/renderCauses.ts``: the render outcome vocabulary."""
    causes = "".join(
        f"  /** {cause.description} */\n  {_ts_string(cause.name)},\n"
        for cause in RENDER_CAUSES
    )
    at_fault = "".join(
        f"  {_ts_string(cause.name)}: {'true' if cause.document_at_fault else 'false'},\n"
        for cause in RENDER_CAUSES
    )
    return (
        _ts_header()
        + "\n"
        + "/** The kind prefix of an empty render: `empty-render:<cause>`. */\n"
        + f"export const EMPTY_RENDER_KIND = {_ts_string(EMPTY_RENDER_KIND)};\n"
        + "\n"
        + "/** Every reason a render can draw nothing. */\n"
        + "export const RENDER_CAUSES = [\n"
        + causes
        + "] as const;\n"
        + "\n"
        + "export type RenderCause = (typeof RENDER_CAUSES)[number];\n"
        + "\n"
        + "/** Whether rewriting the node's document is the repair for each cause. */\n"
        + "export const DOCUMENT_AT_FAULT: Readonly<Record<RenderCause, boolean>> = {\n"
        + at_fault
        + "};\n"
    )


#: Every committed output: repo-relative path -> the function that renders it.
GENERATED_OUTPUTS: dict[str, Callable[[], str]] = {
    "utk_curio/frontend/urban-workflows/src/generated/renderCauses.ts": render_render_causes_ts,
    "utk_curio/frontend/urban-workflows/src/generated/autkGrammar.ts": render_autk_grammar_ts,
    f"{PROMPTS_DIR}/default_preamble.txt": render_default_preamble,
}


def stale_outputs(repo_root: Path) -> list[str]:
    """The registered outputs whose file on disk differs from a fresh render."""
    stale = []
    for relative, render in GENERATED_OUTPUTS.items():
        path = Path(repo_root) / relative
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != render():
            stale.append(relative)
    return stale
