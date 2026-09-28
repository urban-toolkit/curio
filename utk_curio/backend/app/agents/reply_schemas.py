"""Reply schemas: the document a model writes, constrained by its provider.

A content generation run for an Autark node can ask a provider that takes a
reply schema to hold the reply to it: ``output_config.format`` on Anthropic, a
strict ``json_schema`` ``response_format`` on OpenAI. Only the Autark grammar
gets one. Vega-Lite's schema is too large to send, and code has none.

Both providers take a subset of JSON Schema, so what is sent is a projection of
the vendored schema (``contracts.AUTK_SCHEMA_PATH``), built from it when first
asked for:

- every object with properties is closed to them;
- a map (an object whose keys the schema leaves open and whose values it types)
  is a list of ``{key, value}`` entries;
- an object the schema leaves open, and a reference into a recursive
  definition (a GeoJSON geometry), is a JSON string;
- an untyped value is a scalar;
- a conditional union (``allOf`` of ``if``/``then``, keyed on a constant) is the
  ``anyOf`` of its members, and every other conditional is dropped;
- descriptions, types, enums (a constant is a one-value enum), ``required`` and
  ``$ref`` (into ``$defs``) are kept, and every other keyword is dropped;
- in OpenAI's strict mode (:data:`FLAVOR_STRICT`) every key is required and the
  optional ones may be null. Anthropic's flavor (:data:`FLAVOR_CLOSED`) keeps
  optional keys optional.

A reply is decoded back into a document (:meth:`ReplySchema.decode`): entries
into maps, JSON strings into what they encode, and the null an optional key was
given removed. The projection only shapes what the model writes: the vendored
schema and ``document_validation`` still decide whether the document is valid,
including what the projection drops (the conditionals, ``minItems``).
"""

from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote

GRAMMAR_AUTK = "autk-grammar"

#: OpenAI's strict mode: closed objects, every key required, optional ones nullable.
FLAVOR_STRICT = "strict"
#: Anthropic's: closed objects, optional keys optional.
FLAVOR_CLOSED = "closed"

#: The flavor each API type takes. Gemini is absent: its SDK's schema has no
#: ``$ref`` and no ``anyOf``, so an Autark document cannot be expressed in it.
_FLAVORS = {"anthropic": FLAVOR_CLOSED, "openai_compatible": FLAVOR_STRICT, "testing": FLAVOR_STRICT}

#: The prompt a definition declares for a document it writes under the Autark
#: schema. A delegate without it is never constrained: the schema and the
#: instruction written for it arrive together.
AUTK_PROMPT_KEY = "autk-grammar"

#: Decode marks: kept beside the schema, removed from what is sent.
_MARK = "x-curio"
_OPTIONAL = "x-curio-optional"
_MARK_MAP = "map"
_MARK_JSON = "json"

_SCALARS = ("string", "number", "integer", "boolean", "null")


class ReplySchemaError(ValueError):
    """The vendored schema uses a form the projection does not know."""


def _any_scalar(description: str = "") -> dict:
    schema: dict = {"anyOf": [{"type": "string"}, {"type": "number"},
                              {"type": "boolean"}, {"type": "null"}]}
    if description:
        schema["description"] = description
    return schema


def _joined(*parts: str) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())


def _def_name(ref: str) -> str:
    return unquote(ref.rsplit("/", 1)[-1])


def _cycles(definitions: dict) -> set[str]:
    """The definitions that can reach themselves through ``$ref``."""
    edges: dict[str, set[str]] = {}

    def _refs(node, into: set[str]) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                into.add(_def_name(ref))
            for value in node.values():
                _refs(value, into)
        elif isinstance(node, list):
            for value in node:
                _refs(value, into)

    for name, node in definitions.items():
        edges[name] = set()
        _refs(node, edges[name])

    def _reaches(start: str, target: str) -> bool:
        seen, stack = set(), list(edges.get(start, ()))
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(edges.get(current, ()))
        return False

    return {name for name in definitions if _reaches(name, name)}


class _Projector:
    def __init__(self, source: dict, flavor: str):
        self.flavor = flavor
        self.source_defs = source.get("definitions") or source.get("$defs") or {}
        self.recursive = _cycles(self.source_defs)
        self.names: dict[str, str] = {}
        self.defs: dict[str, dict] = {}

    def _name(self, name: str) -> str:
        if name not in self.names:
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "Definition"
            taken = set(self.names.values())
            candidate, n = safe, 2
            while candidate in taken:
                candidate, n = f"{safe}_{n}", n + 1
            self.names[name] = candidate
        return self.names[name]

    def _ensure(self, name: str) -> str:
        safe = self._name(name)
        if safe not in self.defs:
            self.defs[safe] = {}  # a placeholder, so a reference back finds it
            self.defs[safe] = self.project(self.source_defs[name])
        return safe

    def _opaque(self, node: dict) -> dict:
        return {"type": "string", _MARK: _MARK_JSON,
                "description": _joined(node.get("description", ""), "Write it as JSON, in a string.")}

    def project(self, node) -> dict:
        if not isinstance(node, dict) or not node:
            return _any_scalar()
        description = node.get("description", "")
        if "$ref" in node:
            name = _def_name(node["$ref"])
            if name not in self.source_defs:
                raise ReplySchemaError(f"a reference to an unknown definition: {node['$ref']}")
            if name in self.recursive:
                return self._opaque({"description": _joined(
                    description, self.source_defs[name].get("description", ""))})
            out = {"$ref": f"#/$defs/{self._ensure(name)}"}
            return {**out, "description": description} if description else out
        if "allOf" in node:
            members = node["allOf"]
            if not all(isinstance(m, dict) and "then" in m and set(m) <= {"if", "then"} for m in members):
                raise ReplySchemaError(f"an allOf the projection does not know: {json.dumps(node)[:160]}")
            union = {"anyOf": [self.project(m["then"]) for m in members]}
            return {**union, "description": description} if description else union
        if "anyOf" in node:
            union = {"anyOf": [self.project(m) for m in node["anyOf"]]}
            return {**union, "description": description} if description else union
        kind = node.get("type")
        if isinstance(kind, list):
            union = {"anyOf": [self.project({**node, "type": k}) for k in kind]}
            return {**union, "description": description} if description else union
        if "const" in node:
            value = node["const"]
            out = {"type": kind or _type_of(value), "enum": [value]}
            return {**out, "description": description} if description else out
        if kind == "object" or "properties" in node or "additionalProperties" in node:
            return self._object(node)
        if kind == "array":
            out = {"type": "array", "items": self.project(node.get("items", {}))}
            return {**out, "description": description} if description else out
        if kind in _SCALARS:
            out: dict = {"type": kind}
            if isinstance(node.get("enum"), list):
                out["enum"] = list(node["enum"])
            return {**out, "description": description} if description else out
        if isinstance(node.get("enum"), list):
            kinds = {_type_of(v) for v in node["enum"]}
            out = {"type": kinds.pop() if len(kinds) == 1 else "string", "enum": list(node["enum"])}
            return {**out, "description": description} if description else out
        return _any_scalar(description)

    def _object(self, node: dict) -> dict:
        description = node.get("description", "")
        properties = node.get("properties") or {}
        extra = node.get("additionalProperties")
        if not properties:
            if isinstance(extra, dict) and extra:
                return {
                    "type": "array", _MARK: _MARK_MAP,
                    "description": _joined(description, "Each entry is one key of the map and its value."),
                    "items": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}, "value": self.project(extra)},
                        "required": ["key", "value"],
                        "additionalProperties": False,
                    },
                }
            return self._opaque(node)
        required = [k for k in node.get("required") or () if k in properties]
        out_properties: dict = {}
        optional: list[str] = []
        for key, value in properties.items():
            projected = self.project(value)
            if self.flavor == FLAVOR_STRICT and key not in required:
                # Strict mode requires every key: an optional one may be null.
                if "anyOf" in projected:
                    projected = {**projected, "anyOf": [*projected["anyOf"], {"type": "null"}]}
                else:
                    projected = {"anyOf": [projected, {"type": "null"}]}
                optional.append(key)
            out_properties[key] = projected
        out = {
            "type": "object",
            "properties": out_properties,
            "required": list(out_properties) if self.flavor == FLAVOR_STRICT else required,
            "additionalProperties": False,
        }
        if description:
            out["description"] = description
        if optional:
            out[_OPTIONAL] = optional
        return out


def _type_of(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "string"


def _stripped(node):
    """*node* without the decode marks: what a provider receives."""
    if isinstance(node, dict):
        return {k: _stripped(v) for k, v in node.items() if k not in (_MARK, _OPTIONAL)}
    if isinstance(node, list):
        return [_stripped(v) for v in node]
    return node


@dataclass(frozen=True)
class ReplySchema:
    """One grammar's schema in one provider's flavor."""

    name: str
    grammar: str
    flavor: str
    #: What a provider receives.
    schema: dict = field(compare=False, repr=False)
    #: The same schema with its decode marks.
    annotated: dict = field(compare=False, repr=False)

    def request(self) -> dict:
        """``{name, schema}``, as ``providers.run_chat_turn`` takes it."""
        return {"name": self.name, "schema": copy.deepcopy(self.schema)}

    def decode(self, text: str) -> str:
        """A reply as the document it encodes, or the reply itself when it is
        not one (the validator then says what is wrong with it)."""
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return text
        if not isinstance(value, dict):
            return text
        document = _Codec(self).decode(value, self.annotated)
        return json.dumps(document, indent=2, ensure_ascii=False)

    def encode(self, document: dict) -> tuple[object, list[str]]:
        """*document* as a constrained reply would write it, and the paths of
        what the projection has no room for (keys the schema does not name)."""
        codec = _Codec(self)
        return codec.encode(document, self.annotated, "$"), codec.dropped


class _Codec:
    def __init__(self, reply: ReplySchema):
        self.defs = reply.annotated.get("$defs") or {}
        self.wire_defs = reply.schema.get("$defs") or {}
        self.dropped: list[str] = []

    def _resolve(self, schema: dict) -> dict:
        while isinstance(schema, dict) and "$ref" in schema:
            schema = self.defs.get(_def_name(schema["$ref"]), {})
        return schema

    def _matches(self, value, member: dict) -> bool:
        import jsonschema

        schema = {**_stripped(member), "$defs": self.wire_defs}
        return jsonschema.Draft202012Validator(schema).is_valid(value)

    def decode(self, value, schema: dict):
        schema = self._resolve(schema)
        mark = schema.get(_MARK)
        if mark == _MARK_JSON:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except ValueError:
                    return value  # left for the validator to refuse
            return value
        if mark == _MARK_MAP and isinstance(value, list):
            item = schema["items"]["properties"]["value"]
            return {str(entry.get("key")): self.decode(entry.get("value"), item)
                    for entry in value if isinstance(entry, dict)}
        if "anyOf" in schema:
            for member in schema["anyOf"]:
                if self._matches(value, member):
                    return self.decode(value, member)
            return value
        if schema.get("type") == "object" and isinstance(value, dict):
            properties = schema.get("properties") or {}
            optional = set(schema.get(_OPTIONAL) or ())
            out = {}
            for key, item in value.items():
                if item is None and key in optional:
                    continue
                out[key] = self.decode(item, properties[key]) if key in properties else item
            return out
        if schema.get("type") == "array" and isinstance(value, list):
            return [self.decode(item, schema.get("items") or {}) for item in value]
        return value

    def encode(self, value, schema: dict, where: str):
        schema = self._resolve(schema)
        mark = schema.get(_MARK)
        if mark == _MARK_JSON:
            return json.dumps(value, ensure_ascii=False)
        if mark == _MARK_MAP and isinstance(value, dict):
            item = schema["items"]["properties"]["value"]
            return [{"key": key, "value": self.encode(v, item, f"{where}.{key}")} for key, v in value.items()]
        if "anyOf" in schema:
            for member in schema["anyOf"]:
                attempt = _Codec.__new__(_Codec)
                attempt.defs, attempt.wire_defs, attempt.dropped = self.defs, self.wire_defs, []
                encoded = attempt.encode(value, member, where)
                if self._matches(encoded, member):
                    self.dropped.extend(attempt.dropped)
                    return encoded
            return value
        if schema.get("type") == "object" and isinstance(value, dict):
            properties = schema.get("properties") or {}
            out = {}
            for key, sub in properties.items():
                if key in value:
                    out[key] = self.encode(value[key], sub, f"{where}.{key}")
                elif key in set(schema.get(_OPTIONAL) or ()):
                    out[key] = None
            self.dropped.extend(f"{where}.{key}" for key in value if key not in properties)
            return out
        if schema.get("type") == "array" and isinstance(value, list):
            return [self.encode(item, schema.get("items") or {}, f"{where}[{i}]")
                    for i, item in enumerate(value)]
        return value


@lru_cache(maxsize=None)
def autk_reply_schema(flavor: str) -> ReplySchema:
    """The Autark document's reply schema in *flavor*, projected from the
    vendored schema once per process."""
    from utk_curio.backend.app.agents import contracts

    source = contracts.load_autk_schema()
    projector = _Projector(source, flavor)
    root = projector.project(projector.source_defs[_def_name(source.get("$ref", "UrbanSpec"))])
    if root.get("type") != "object":
        raise ReplySchemaError("the Autark document's root is not an object")
    annotated = {**root, "$defs": projector.defs}
    return ReplySchema(
        name="autk_grammar_document", grammar=GRAMMAR_AUTK, flavor=flavor,
        schema=_stripped(annotated), annotated=annotated,
    )


#: Endpoints and models that refused a reply schema in this process: the next
#: run on them asks without one. ``(api_type, base_url, model)``.
_refused: set[tuple[str, str, str]] = set()
_refused_lock = threading.Lock()


def note_refused(config) -> None:
    """*config*'s endpoint answered a request carrying a reply schema with a
    400 or 422; later runs on it in this process send none."""
    with _refused_lock:
        _refused.add((config.api_type, config.base_url or "", config.model))


def for_run(config, user_key: str, grammar: str | None) -> ReplySchema | None:
    """The reply schema a content generation run for a *grammar* document
    sends on *config*, or None: the grammar has none, the provider takes none
    for it, or this endpoint refused one before."""
    if grammar != GRAMMAR_AUTK:
        return None
    flavor = _FLAVORS.get(config.api_type)
    if flavor is None:
        return None
    with _refused_lock:
        if (config.api_type, config.base_url or "", config.model) in _refused:
            return None
    from utk_curio.backend.app.agents import chat_capabilities

    try:
        if not chat_capabilities.chat_capabilities(config, user_key).structured_output:
            return None
    except Exception:  # noqa: BLE001 - the question never fails a run
        return None
    return autk_reply_schema(flavor)
