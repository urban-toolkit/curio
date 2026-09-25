"""Validating the content the sandbox cannot run.

Memo dev/129, from the owner's instruction: *"it should never put failing code
inside a node."*

``DEC-075`` (dev/118) made Solve honest about node kinds the sandbox cannot
execute — a Vega-Lite chart, an AUTK map grammar — by writing their content and
saying plainly that it was not executed. Honest, and too permissive: those
kinds carry a **document**, and "cannot be run" is not "cannot be checked". The
field proof is dataflow ``00708324``, where the Vega spec Solve wrote and
called *solved* is invalid — ``altair`` (already a dependency, its Vega-Lite
schema bundled) reports ``additional property 'else' is not allowed`` inside
``encoding.color.condition`` — and the node renders red while the chat says
solved.

So a document is validated before it is written, and the answer is one of three
things, never a guess:

- ``valid``    — write it, and say it was validated as a document, not executed;
- ``invalid``  — a failed ROUND: the validator's message is the correction, and
                 the loop's existing budget and trail carry it;
- ``unchecked``— nothing here can check this kind: write NOTHING and say so.

Kind routing is by the template's own ``grammarId`` (``DEC-076``'s rule: the
roster, not a name list), with the template id suffix as the offline fallback.
Pure: no I/O, no network, no spec.

dev/134 corrects two things this module could not do, both proven by the owner's
``e72c7080``:

- a reply that is not a document AT ALL — prose, a decline, the
  ``not controllable`` marker — is a **refusal** for a kind that has a validator
  (the field log wrote the sentence "not controllable" into an ``autk-grammar``
  node as its grammar), so the loop asks again with the shape named and writes
  nothing until it gets one. ``unchecked`` keeps its narrow meaning: *nothing
  here can check this kind*;
- a Vega document's **field references** are checked against the columns its
  input actually has (dev/129 **F3**): the same spec encoded
  ``y.field: "neighborhood"`` over a frame whose name column is ``community``,
  which the schema cannot know and a reader of the columns can.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNCHECKED = "unchecked"

#: The marker a passive node's content carries — nothing was authored, so there
#: is nothing to validate and nothing to write.
NOT_CONTROLLABLE = "not controllable"

_DETAIL_CHARS = 600
#: Placeholder data for validation only: Curio supplies a Vega node's data at
#: render time from its input, so a spec without ``data`` is CORRECT here and
#: the schema's "data is required" must not be reported as the author's error.
_DATA_STUB = {"values": [{}]}


def _detail(text: object) -> str:
    return str(text or "").strip()[:_DETAIL_CHARS]


def _parse_json(content: str) -> tuple[object | None, str | None]:
    try:
        return json.loads(content), None
    except ValueError as exc:
        return None, f"the document is not valid JSON: {exc}"


def validate_vega_lite(content: str, *, columns: list | None = None) -> dict:
    """A Vega-Lite document, against the schema ``altair`` bundles offline —
    and (dev/134) against the columns its input actually has."""
    payload, error = _parse_json(content)
    if error:
        return {"status": STATUS_INVALID, "detail": _detail(error)}
    if not isinstance(payload, dict):
        return {"status": STATUS_INVALID,
                "detail": "a Vega-Lite document must be a JSON object"}
    try:
        import altair as alt
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"altair is unavailable, so the Vega-Lite schema "
                               f"could not be read: {exc}")}
    spec = dict(payload)
    if "data" not in spec:
        # Never overwrite an author's own data block; only stand in for the one
        # the runtime injects.
        spec["data"] = _DATA_STUB
    try:
        alt.Chart.from_dict(spec, validate=True)
    except Exception as exc:  # noqa: BLE001  (altair raises SchemaValidationError)
        return {"status": STATUS_INVALID, "detail": _vega_message(exc)}
    fields = check_vega_fields(payload, columns)
    if fields is not None:
        return fields
    return {"status": STATUS_VALID}


#: dev/134: names Curio's own runtime adds to every row it hands Vega, so an
#: encoding may use them even though no upstream column is called that.
#: ``interacted`` is set by the Data Pool / ``useTableData``; ``__row_index__``
#: by ``useVega.parseInputData``.
RUNTIME_FIELDS = ("interacted", "__row_index__")

#: Transforms whose output column names cannot be known from the document
#: alone. A spec that uses one is schema-checked and its FIELDS are left alone —
#: refusing a field this module cannot enumerate would be a guess.
_OPAQUE_TRANSFORMS = ("pivot", "fold", "flatten", "sample", "lookup", "density", "loess")

#: Keys under which a Vega-Lite spec nests another spec.
_SPEC_CONTAINERS = ("layer", "hconcat", "vconcat", "concat", "spec", "facet", "repeat")


def _transform_outputs(spec: dict) -> tuple[set, bool]:
    """``(names a transform creates, whether any transform is opaque)``."""
    produced: set = set()
    opaque = False
    for entry in spec.get("transform") or []:
        if not isinstance(entry, dict):
            continue
        if any(key in entry for key in _OPAQUE_TRANSFORMS):
            opaque = True
        for key in ("as",):
            value = entry.get(key)
            if isinstance(value, str):
                produced.add(value)
            elif isinstance(value, list):
                produced.update(v for v in value if isinstance(v, str))
        for key in ("aggregate", "joinaggregate", "window"):
            for item in entry.get(key) or []:
                if isinstance(item, dict) and isinstance(item.get("as"), str):
                    produced.add(item["as"])
        if isinstance(entry.get("calculate"), str) and isinstance(entry.get("as"), str):
            produced.add(entry["as"])
    for key in _SPEC_CONTAINERS:
        child = spec.get(key)
        for sub in (child if isinstance(child, list) else [child]):
            if isinstance(sub, dict):
                names, sub_opaque = _transform_outputs(sub)
                produced |= names
                opaque = opaque or sub_opaque
    return produced, opaque


def _field_refs(spec: dict, path: str = "") -> list[tuple[str, str]]:
    """Every ``(json path, field name)`` an encoding or a transform reads.

    Only string fields: ``{"repeat": "column"}`` and a bare ``count`` aggregate
    name no column, and inventing one would produce a false refusal.
    """
    refs: list[tuple[str, str]] = []

    def _walk(node: object, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "field" and isinstance(value, str):
                    refs.append((f"{where}.field", value))
                elif key == "groupby" and isinstance(value, list):
                    for i, name in enumerate(value):
                        if isinstance(name, str):
                            refs.append((f"{where}.groupby[{i}]", name))
                else:
                    _walk(value, f"{where}.{key}" if where else key)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{where}[{index}]")

    _walk(spec, path)
    return refs


def check_vega_fields(payload: dict, columns: list | None) -> dict | None:
    """dev/134 (closes dev/129 **F3**): does this document read columns that
    exist?

    The field proof is the owner's `e72c7080`: a schema-valid bar chart encoding
    ``y.field: "neighborhood"`` against a frame whose name column is
    ``community`` — a chart that renders axes and no bars. The columns come from
    the SAME bounded artifact preview the generation request was handed
    (``DEC-063``: never refuse a model for ignoring something it was not told),
    so when they are unknown this check does not run at all.
    """
    if not columns:
        return None
    known = {str(c) for c in columns} | set(RUNTIME_FIELDS)
    produced, opaque = _transform_outputs(payload)
    if opaque:
        return None  # a transform creates names this module cannot enumerate
    known |= produced
    for where, field in _field_refs(payload):
        if field in known:
            continue
        available = ", ".join(sorted(str(c) for c in columns)[:20])
        return {
            "status": STATUS_INVALID,
            "detail": _detail(
                f"{where} reads {field!r}, which is not a column of this node's "
                f"input — available columns: {available}"
                + (f" (plus {', '.join(RUNTIME_FIELDS)}, added by Curio)")
            ),
        }
    return None


def _vega_message(exc: Exception) -> str:
    """The offending property and where it sits, from a schema error.

    ``altair``'s message is a full schema dump; the first line carries the
    complaint and the ``$.…`` path line carries the location. Both are worth
    keeping, nothing after them is.
    """
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return _detail(f"{type(exc).__name__}: the document does not match the Vega-Lite schema")
    head = lines[0]
    # A JSON path (``$.encoding.color.condition``) is the useful location when
    # altair emits one; the bare "On instance:" label and the schema dump that
    # follows are not, so they are dropped rather than truncated into noise.
    path = next((line for line in lines if line.startswith("$.")), "")
    rule = next(
        (line for line in lines if line.startswith("Failed validating")), ""
    )
    parts = [head]
    if path:
        parts.append(f"at {path}")
    elif rule:
        parts.append(rule.rstrip(":"))
    return _detail(" — ".join(parts))


#: At most this many schema errors are reported, in the order the schema meets
#: them, so the refusal stays inside ``_DETAIL_CHARS``.
_MAX_SCHEMA_ERRORS = 5


def validate_autk_grammar(content: str, *, columns: list | None = None) -> dict:
    """An Autark document, against the grammar's own JSON Schema.

    The schema is the vendored copy of what autk-grammar publishes
    (``contracts.AUTK_SCHEMA_PATH``). One rule sits on top, because no schema
    form says it: the document must load, compute or draw something, and a map
    must list a layer (``_draws_nothing``).
    """
    from utk_curio.backend.app.agents import contracts

    payload, error = _parse_json(content)
    if error:
        return {"status": STATUS_INVALID, "detail": _detail(error)}
    if not isinstance(payload, dict):
        return {"status": STATUS_INVALID,
                "detail": "an Autark grammar document must be a JSON object"}
    try:
        import jsonschema
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"jsonschema is unavailable, so the Autark schema could not be applied: {exc}")}
    try:
        schema = contracts.load_autk_schema()
        validator_class = jsonschema.validators.validator_for(schema, default=jsonschema.Draft7Validator)
        validator_class.check_schema(schema)
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"the Autark schema could not be read: {exc}")}
    messages: list[str] = []
    for err in validator_class(schema).iter_errors(payload):
        for message in _messages(err, jsonschema):
            if message not in messages:
                messages.append(message)
    if messages:
        return {"status": STATUS_INVALID, "detail": _detail("; ".join(messages[:_MAX_SCHEMA_ERRORS]))}
    empty = _draws_nothing(payload, schema)
    if empty:
        return {"status": STATUS_INVALID, "detail": _detail(empty)}
    return {"status": STATUS_VALID}


#: JSON type names, for a value that fits none of a field's forms.
_JSON_TYPES = {dict: "object", list: "array", str: "string", bool: "boolean",
               int: "number", float: "number", type(None): "null"}


def _messages(error, jsonschema) -> list[str]:
    """What *error* says. An ``anyOf`` failure (``map`` and ``plot`` are one
    object or a list of them) is explained by the branch that fits the value."""
    if error.validator not in ("anyOf", "oneOf") or not error.context:
        return [_schema_message(error)]
    branches: dict = {}
    for sub in error.context:
        if sub.validator == "type" and not sub.relative_path:
            continue  # that branch is for another kind of value
        branches.setdefault(sub.relative_schema_path[0], []).append(sub)
    if not branches:
        types = [t for sub in error.context
                 for t in ([sub.validator_value] if isinstance(sub.validator_value, str) else sub.validator_value)]
        given = _JSON_TYPES.get(type(error.instance), "value")
        return [f"{_where(error)}: expected {_or(dict.fromkeys(types))}, not {given}"]
    lacking = [_lacking(subs) for subs in branches.values()]
    if len(lacking) > 1 and all(lacking):
        # Every branch that fits only lacks fields: what all of them need, then the choice.
        common = [f for f in lacking[0] if all(f in fields for fields in lacking)]
        choice = [f for fields in lacking for f in fields if f not in common]
        needs = ([_and([f'"{f}"' for f in common])] if common else []) + (
            [f"one of {_or(dict.fromkeys(choice))}"] if choice else [])
        return [f"{_where(error)}: missing " + ", and ".join(needs)]
    best = jsonschema.exceptions.best_match([sub for subs in branches.values() for sub in subs])
    return [m for sub in branches[best.relative_schema_path[0]] for m in _messages(sub, jsonschema)]


def _lacking(errors) -> list[str]:
    """The fields a branch is missing, if missing fields are all that is wrong with it."""
    if not all(e.validator == "required" and not e.relative_path for e in errors):
        return []
    return list(dict.fromkeys(name for e in errors for name in e.validator_value
                              if name not in (e.instance or {})))


def _where(error) -> str:
    """``map.layerRefs[0]``, or "the document" at the root."""
    path = ""
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else (f".{part}" if path else str(part))
    return path or "the document"


def _and(items) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _or(values) -> str:
    quoted = [f'"{v}"' for v in values]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " or " + quoted[-1]


def _schema_message(error) -> str:
    """``map.layerRefs[0]: missing "dataRef"``, with the field's own description."""
    where = _where(error)
    if error.validator == "required":
        properties = error.schema.get("properties", {}) if isinstance(error.schema, dict) else {}
        missing = [name for name in error.validator_value if name not in (error.instance or {})]
        if not missing:
            return f"{where}: {error.message}"
        named = []
        for name in missing:
            described = properties.get(name, {}).get("description")
            named.append(f'"{name}"' + (f" ({described})" if described else ""))
        return f"{where}: missing " + _and(named)
    described = error.schema.get("description") if isinstance(error.schema, dict) else None
    return f"{where}: {error.message}" + (f" ({described})" if described else "")


def _draws_nothing(payload: dict, schema: dict) -> str | None:
    """Why a schema-valid document would still run nothing, or None."""
    from utk_curio.backend.app.agents import contracts

    if not any(payload.get(f) not in (None, [], {}) for f in contracts.autk_families(schema)):
        return (
            "the document has nothing for Autark to run; it must be "
            + contracts.render_autk_shape(schema)
        )
    layers, _ = contracts.map_layers(schema)
    maps = payload.get("map")
    for index, grammar in enumerate(maps if isinstance(maps, list) else [maps] if maps else []):
        if isinstance(grammar, dict) and not grammar.get(layers):
            where = f"map[{index}]" if isinstance(maps, list) else "map"
            return f'"{where}.{layers}" is empty, and a map with no layers renders nothing'
    return None


#: GRAMMAR ID → validator (dev/134: the manifest's own ``grammarId``, so a
#: package that ships its own Vega node validates through the same entry). Read
#: by ``validate`` only, so a new grammar is one entry rather than a branch.
_VALIDATORS = {
    "vega-lite": validate_vega_lite,
    "autk-grammar": validate_autk_grammar,
}

#: The offline fallback: a template id suffix → the grammar it carries, for a
#: caller with no roster snapshot (dev/119's pattern).
_SUFFIX_GRAMMARS = {
    "vis-vega": "vega-lite",
    "autk-grammar": "autk-grammar",
}

#: What each grammar's document IS, for the refusal a non-document reply gets.
_GRAMMAR_SHAPES = {
    "vega-lite": (
        'a Vega-Lite JSON document — {"$schema": "https://vega.github.io/schema/'
        'vega-lite/v6.json", "mark": …, "encoding": …}. Do NOT include a "data" '
        "block: Curio injects this node's input as the data at render time"
    ),
}


def grammar_shape(grammar: str | None) -> str:
    """What a document in *grammar* is, for the refusal a non-document reply gets."""
    if grammar == "autk-grammar":
        from utk_curio.backend.app.agents import contracts

        try:
            return contracts.render_autk_shape(contracts.load_autk_schema())
        except Exception:  # noqa: BLE001
            return "an Autark grammar JSON document"
    return _GRAMMAR_SHAPES.get(grammar or "", "a JSON document")


#: Kinds whose content is never authored (the preamble's "uncontrollable"
#: boxes): nothing to validate, and nothing to write.
_PASSIVE = ("merge-flow", "data-pool", "vis-simple", "spatial-join")


def canonical_suffix(node_type: object) -> str:
    """``"curio.builtin/vis-vega@2"`` → ``"vis-vega"`` (versioned and legacy
    enum spellings tolerated, as everywhere else)."""
    return str(node_type or "").rsplit("/", 1)[-1].split("@", 1)[0].lower().replace("_", "-")


def grammar_of(node_type: object, grammar_id: object = None) -> str | None:
    """Which grammar this node's document is written in (dev/134).

    The roster's ``grammarId`` when the caller has one; otherwise the template
    id suffix, the offline fallback.
    """
    if isinstance(grammar_id, str) and grammar_id.strip():
        return grammar_id.strip()
    return _SUFFIX_GRAMMARS.get(canonical_suffix(node_type))


def validate(
    node_type: object,
    content: object,
    *,
    grammar_id: object = None,
    columns: list | None = None,
) -> dict:
    """Validate a non-executable node's content. See the module docstring.

    dev/134: the kind is routed by its GRAMMAR (the roster's ``grammarId``), and
    a reply that is not a document at all — prose, a decline, the
    ``not controllable`` marker — is a REFUSAL for a kind that has a validator,
    not an "unchecked". The owner's `e72c7080` wrote the sentence
    "not controllable" into an ``autk-grammar`` node as its grammar; the loop
    must ask again with the shape named, and write nothing until it gets one.
    """
    text = content if isinstance(content, str) else ""
    suffix = canonical_suffix(node_type)
    grammar = grammar_of(node_type, grammar_id)
    validator = _VALIDATORS.get(grammar or "")
    stripped = text.strip()
    if not stripped or stripped.lower() == NOT_CONTROLLABLE:
        if validator is not None:
            return {
                "status": STATUS_INVALID,
                "detail": _detail(
                    "there is no document here at all"
                    + (f" (the reply was {stripped!r})" if stripped else "")
                    + f"; this node's content must be {grammar_shape(grammar)}"
                ),
            }
        # A wired box's marker, or nothing at all: there is no document.
        return {"status": STATUS_UNCHECKED,
                "why": "there is no authored document to validate",
                "passive": suffix in _PASSIVE}
    if validator is None:
        return {"status": STATUS_UNCHECKED,
                "why": f"no document validator exists for {grammar or suffix or 'this kind'}",
                "passive": suffix in _PASSIVE}
    if not stripped.startswith(("{", "[")):
        # Prose where a document belongs: say what was expected rather than
        # letting a JSON parse error stand in for the real problem.
        return {
            "status": STATUS_INVALID,
            "detail": _detail(
                f"the reply is prose, not a document ({stripped[:120]!r}…); this "
                f"node's content must be {grammar_shape(grammar)}"
            ),
        }
    try:
        return validator(text, columns=columns)
    except Exception as exc:  # noqa: BLE001
        log.warning("Document validation failed for %s", grammar or suffix, exc_info=True)
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"the validator for {grammar or suffix} could not run: {exc}")}


def refusal_text(node_type: object, verdict: dict, *, grammar_id: object = None) -> str:
    """What the model is told, and what a human reads in the trail."""
    grammar = grammar_of(node_type, grammar_id)
    what = "Vega-Lite" if grammar == "vega-lite" else (
        "Autark grammar" if grammar == "autk-grammar" else
        grammar or canonical_suffix(node_type) or "document"
    )
    return (
        f"document refused — this node's content is a {what} document and it does not "
        f"validate: {_detail(verdict.get('detail'))}. Fix exactly that and return the "
        "whole document; nothing is written to the node until it validates."
    )
