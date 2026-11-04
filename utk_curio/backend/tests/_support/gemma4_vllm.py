"""What a vLLM server hands Curio for a native call Gemma 4 makes.

Gemma 4 writes a call in its own syntax, not JSON: a string between ``<|"|>``
delimiters, and a number, ``true``, ``false`` or ``null`` bare. vLLM's parser
for it (``vllm/parser/gemma4.py``, ``_parse_gemma4_fields`` and
``_parse_gemma4_array``) keeps a bare value as its text, so ``2`` and
``<|"|>2<|"|>`` both arrive as ``"2"``, and objects and lists as objects and
lists. Its parser engine then types the values by the schema of the tool the
request offered (``vllm/parser/engine/parser_engine.py``, ``_fix_arg_types``,
``_coerce_dict`` and ``_coerce_value``, with ``coerce_to_schema_type`` and
``extract_types_from_schema`` from ``vllm/tool_parsers/utils.py``):

- a key the schema's ``properties`` do not name is left as it is;
- an object whose schema has no ``properties`` is left as it is, whatever its
  values (``additionalProperties`` is not read);
- each item of a list is typed by the list's ``items``;
- a text is typed by the schema's types (its ``type``, else its enum's, else
  ``anyOf``/``oneOf``/``allOf``'s, else ``string``), tried in the order null,
  integer, number, boolean, object, array, string, then read as JSON.

So a value whose type the offered schema does not give reaches Curio as text.
:func:`delivered` is that transport for a call whose arguments the model meant
as *arguments*, on a tool offered *schema*.
"""
from __future__ import annotations

import json
import math

#: The order vLLM tries a text's types in (``coerce_to_schema_type``).
_ORDER = ("null", "integer", "number", "boolean", "object", "array", "string")


def delivered(arguments: dict, schema: dict) -> dict:
    """The arguments vLLM hands over for a Gemma 4 call meant as *arguments*."""
    return _typed(_as_written(arguments), schema)


def _as_written(value):
    """What ``_parse_gemma4_fields`` makes of a value: a bare one is its text."""
    if isinstance(value, dict):
        return {key: _as_written(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_written(item) for item in value]
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _types(schema: dict) -> set[str]:
    """``extract_types_from_schema``."""
    found: set[str] = set()
    kind = schema.get("type")
    if isinstance(kind, str):
        found.add(kind)
    elif isinstance(kind, list):
        found.update(k for k in kind if isinstance(k, str))
    for value in schema.get("enum") or []:
        found.add("null" if value is None else "boolean" if isinstance(value, bool)
                  else "integer" if isinstance(value, int) else "number" if isinstance(value, float)
                  else "string" if isinstance(value, str) else "array" if isinstance(value, list) else "object")
    for key in ("anyOf", "oneOf", "allOf"):
        for choice in schema.get(key) or []:
            if isinstance(choice, dict):
                found |= _types(choice)
    return found or {"string"}


def _finite(value) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    if isinstance(value, dict):
        return all(_finite(item) for item in value.values())
    return True


def _as_types(text: str, types: set[str]):
    """``coerce_to_schema_type``."""
    for kind in (k for k in _ORDER if k in types):
        if kind == "null" and text.lower() == "null":
            return None
        if kind == "integer":
            try:
                return int(text)
            except ValueError:
                continue
        if kind == "number":
            try:
                return int(text)
            except ValueError:
                pass
            try:
                number = float(text)
            except ValueError:
                continue
            if math.isfinite(number):
                return int(number) if number == int(number) else number
        if kind == "boolean":
            if text.lower().strip() in ("true", "1"):
                return True
            if text.lower().strip() in ("false", "0"):
                return False
        if kind in ("object", "array"):
            try:
                parsed = json.loads(text)
            except ValueError:
                continue
            if _finite(parsed):
                return parsed
        if kind == "string":
            return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    return parsed if _finite(parsed) else text


def _typed(value, schema):
    """``_coerce_value``: *value* typed where *schema* gives the type."""
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict):
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return value
        return {key: _typed(item, properties[key]) if isinstance(properties.get(key), dict) else item
                for key, item in value.items()}
    if isinstance(value, list):
        items = schema.get("items")
        return [_typed(item, items) for item in value] if isinstance(items, dict) else value
    if isinstance(value, str):
        return _as_types(value, _types(schema))
    return value
