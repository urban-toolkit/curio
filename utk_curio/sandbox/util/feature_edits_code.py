"""The Map Edits node's code, read as the node reads it.

A Map Edits node (its type is still ``curio.builtin/edit-features``) keeps
its edits in its code, one call of ``curio_edit_features``, which the node
writes from its edit list and reads back (``readEditFeaturesCode`` in
``utils/editFeatures/editFeatures.ts``). Code of any other shape still runs,
and the node says why it cannot read it.

This is that reader, ported line for line, so code an agent writes for the
node is held to what the node reads: ``read_edit_features_code`` and the
pieces it is built of, ``edit_problem``, ``new_layer_problem``, the literal
reader of ``utils/editFeatures/pyLiteral.ts`` (``read_call_args``) and the
normalizers the settings pass through. It reads by the node's rules alone,
never by Python's: Python takes code the node refuses, such as a comment
inside the call or a triple-quoted text. Where a reason shows a value, it
shows it as the browser does (``js_values``), so both say the same words;
``editFeaturesCode.cases.json`` holds the cases Jest and pytest check them
on, word for word. Texts are read by characters, where the browser reads
UTF-16 units: a character outside the Basic Multilingual Plane next to a
refusal's position can make the two differ, and none of the cases has one.
"""
from __future__ import annotations

import math
import re

from utk_curio.sandbox.util import edit_expr
from utk_curio.sandbox.util import js_values
from utk_curio.sandbox.util.feature_edits import _GEOMETRY_TYPES, NEW_LAYER_TYPES, OPS, WRITES

#: What the node's code calls (``EDIT_HELPER``).
EDIT_HELPER = "curio_edit_features"
#: The edits the node makes, in order (``EDIT_OPS``), as the step lists them.
EDIT_OPS = OPS
#: The ops that write a column (``WRITE_OPS``).
WRITE_OPS = WRITES
#: The geometry a new layer's features take (``NEW_LAYER_GEOMETRIES``).
NEW_LAYER_GEOMETRIES = tuple(NEW_LAYER_TYPES)
#: The kinds of value a property takes (``PROPERTY_TYPES``).
PROPERTY_TYPES = ("text", "number", "boolean", "choice", "date")
#: The keywords ``curio_edit_features`` takes after its input and its edits.
KEYWORDS = ("key", "layer", "keys", "new_layers", "crs", "by_input")
#: What each op's dict holds, besides its op, its layer, its label and its switch.
EDIT_FIELDS = {
    "remove": ("ids", "where"),
    "restore": ("ids", "where"),
    "set": ("ids", "where", "column", "value"),
    "scale": ("ids", "where", "column", "value"),
    "offset": ("ids", "where", "column", "value"),
    "expr": ("ids", "where", "column", "value"),
    "geometry": ("ids", "where", "geometry", "crs"),
    "add": ("id", "geometry", "crs", "values"),
    "add_column": ("column", "value"),
}
#: The fields every op's dict may hold.
COMMON_FIELDS = ("op", "layer", "label", "enabled")
#: What a new layer's dict holds, and each of its properties'.
NEW_LAYER_FIELDS = ("name", "geometry", "properties")
PROPERTY_FIELDS = ("name", "type", "required", "choices", "default")

NOT_THE_CALL = (
    f"This node reads one call, return {EDIT_HELPER}(input_0, [...]), and this code holds something else."
)
NOT_A_VALUE = "is not a text, a number, True, False or None"

#: A key a dict does not hold, which the browser calls ``undefined``.
_MISSING = object()

_HEAD = re.compile(r"(?:[ \t\f]*(?:#[^\r\n]*)?(?:\r\n|\r|\n))*")
_LINES = re.compile(r"\r\n|\r|\n")
_OPENING = re.compile(rf"return[ \t\f]+{EDIT_HELPER}[ \t\f]*\(")
_INDENTED_RETURN = re.compile(r"[ \t\f]+return\b", re.ASCII)
#: A ``[!! ... !!]`` reference (``REFERENCE_PATTERN``), as the browser matches it.
_REFERENCE = re.compile(
    rf"\[!![{js_values.SPACES}]*[^{js_values.LINE_TERMINATORS}]*?[{js_values.SPACES}]*!!\]"
)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_OCTAL = re.compile(r"[0-7]{1,3}")
_ESCAPES = {"\\": "\\", "'": "'", '"': '"', "a": "\x07", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


class Unreadable(Exception):
    """Why code cannot be read: its message is what the node says."""


class Literal:
    """A literal as the reader found it: a value (``kind`` "value"), a list of
    literals, a dict's entries (pairs of literals, so its keys keep their
    types) or a bare name."""

    def __init__(self, kind: str, value=None, items=None, entries=None, name=None):
        self.kind = kind
        self.value = value
        self.items = items
        self.entries = entries
        self.name = name


def _is_id(value) -> bool:
    return isinstance(value, str) or (js_values.is_number(value) and math.isfinite(value))


def _is_value(value) -> bool:
    return (
        value is None or isinstance(value, (str, bool))
        or (js_values.is_number(value) and math.isfinite(value))
    )


def _is_geometry(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("type"), str)
        and value["type"] in _GEOMETRY_TYPES
        and isinstance(value.get("coordinates"), list)
    )


def _one_of(value, choices) -> bool:
    """Whether *value* is one of the texts *choices*, as ``includes`` compares."""
    return isinstance(value, str) and value in choices


def _show(value) -> str:
    """A value as a reason shows it, as Python writes it (``show``)."""
    if value is _MISSING:
        return "nothing"
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    return js_values.stringify(value)


def shown(literal: Literal) -> str:
    """*literal* as Python's ``repr`` would show it, in a reason."""
    if literal.kind == "list":
        return "a list"
    if literal.kind == "dict":
        return "a dict"
    if literal.kind == "name":
        return literal.name
    if literal.value is None:
        return "None"
    if isinstance(literal.value, bool):
        return "True" if literal.value else "False"
    if isinstance(literal.value, str):
        return js_values.stringify(literal.value)
    return js_values.number(literal.value)


def with_article(word: str) -> str:
    """*word* after its article: "a point", "an area", "an add"."""
    return f"{'an' if re.match(r'[aeiou]', word, re.IGNORECASE) else 'a'} {word}"


def _unique_ids(raw: list) -> list:
    out = []
    seen = set()
    for value in raw:
        if not _is_id(value):
            continue
        key = ("string", value) if isinstance(value, str) else ("number", js_values.number(value))
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _clean_values(raw) -> dict:
    out = {}
    if not isinstance(raw, dict):
        return out
    for column in js_values.keys(raw):
        value = raw[column]
        if column != "" and _is_value(value):
            out[column] = value
    return out


def normalize_edit(raw):
    """The well-formed edit *raw* holds, or None (``normalizeEdit``)."""
    if not isinstance(raw, dict) or not _one_of(raw.get("op"), EDIT_OPS):
        return None
    op = raw["op"]
    layer = {"layer": raw["layer"]} if isinstance(raw.get("layer"), str) and raw["layer"] != "" else {}

    def tail(out: dict) -> dict:
        if isinstance(raw.get("label"), str) and js_values.trim(raw["label"]) != "":
            out["label"] = js_values.trim(raw["label"])
        if raw.get("enabled", _MISSING) is False:
            out["enabled"] = False
        return out

    drawn_in = raw["crs"] if isinstance(raw.get("crs"), str) and raw["crs"] != "" else None
    if op == "add":
        if not _is_id(raw.get("id", _MISSING)) or not _is_geometry(raw.get("geometry")):
            return None
        values = _clean_values(raw.get("values"))
        out = {"op": op, **layer, "id": raw["id"], "geometry": raw["geometry"]}
        if drawn_in:
            out["crs"] = drawn_in
        if values:
            out["values"] = values
        return tail(out)
    if op == "add_column":
        value = raw.get("value")
        if not isinstance(raw.get("column"), str) or raw["column"] == "" or not _is_value(value):
            return None
        return tail({"op": op, **layer, "column": raw["column"], "value": value})
    ids = _unique_ids(raw["ids"]) if isinstance(raw.get("ids"), list) else []
    where = raw.get("where")
    where = js_values.trim(where) if isinstance(where, str) and js_values.trim(where) != "" else None
    if (len(ids) > 0) == (where is not None):
        return None
    out = {"op": op, **layer, "where": where} if where is not None else {"op": op, **layer, "ids": ids}
    if op == "geometry":
        if not _is_geometry(raw.get("geometry")):
            return None
        out["geometry"] = raw["geometry"]
        if drawn_in:
            out["crs"] = drawn_in
    if op in WRITE_OPS:
        value = raw.get("value", _MISSING)
        if not isinstance(raw.get("column"), str) or raw["column"] == "" or not _is_value(value):
            return None
        if op in ("scale", "offset") and not js_values.is_number(value):
            return None
        if op == "expr" and not isinstance(value, str):
            return None
        out["column"] = raw["column"]
        out["value"] = value
    return tail(out)


def normalize_new_layer(raw):
    """A new layer's well-formed definition, or None (``normalizeNewLayer``)."""
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or js_values.trim(name) == "":
        return None
    if not _one_of(raw.get("geometry"), NEW_LAYER_GEOMETRIES):
        return None
    properties = []
    for item in raw["properties"] if isinstance(raw.get("properties"), list) else []:
        if not isinstance(item, dict):
            continue
        prop_name = item.get("name")
        if not isinstance(prop_name, str) or js_values.trim(prop_name) == "" or not _one_of(item.get("type"), PROPERTY_TYPES):
            continue
        if any(other["name"] == prop_name for other in properties):
            continue
        definition = {"name": js_values.trim(prop_name), "type": item["type"]}
        if item.get("required") is True:
            definition["required"] = True
        if isinstance(item.get("choices"), list):
            choices = [js_values.trim(c) for c in item["choices"] if isinstance(c, str) and js_values.trim(c) != ""]
            if choices:
                definition["choices"] = choices
        default = item.get("default", _MISSING)
        if default is not _MISSING and _is_value(default):
            definition["default"] = default
        properties.append(definition)
    out = {"name": js_values.trim(name), "geometry": raw["geometry"]}
    if properties:
        out["properties"] = properties
    return out


def normalize_edit_features(raw):
    """The well-formed settings in *raw*, or None when it holds none
    (``normalizeEditFeatures``)."""
    if not isinstance(raw, dict):
        return None
    out = {}
    if isinstance(raw.get("key"), str) and raw["key"] != "":
        out["key"] = raw["key"]
    if isinstance(raw.get("layer"), str) and raw["layer"] != "":
        out["layer"] = raw["layer"]
    if isinstance(raw.get("keys"), dict):
        keys = {
            name: column for name, column in raw["keys"].items()
            if name != "" and isinstance(column, str) and column != ""
        }
        if keys:
            out["keys"] = keys
    new_layers = (
        [layer for layer in (normalize_new_layer(item) for item in raw["newLayers"]) if layer is not None]
        if isinstance(raw.get("newLayers"), list) else []
    )
    if new_layers:
        out["newLayers"] = new_layers
    if isinstance(raw.get("crs"), str) and raw["crs"] != "":
        out["crs"] = raw["crs"]
    edits = (
        [edit for edit in (normalize_edit(item) for item in raw["edits"]) if edit is not None]
        if isinstance(raw.get("edits"), list) else []
    )
    if edits:
        out["edits"] = edits
    return out or None


def _expr_problem(text: str):
    """Why *text* is not an expression, or None when it is one (``exprProblem``)."""
    try:
        edit_expr.parse(text)
    except edit_expr.ExprError as error:
        return str(error)
    return None


def edit_problem(raw):
    """Why the dict *raw* is not an edit the node writes, or None when it is
    one: the checks ``normalize_edit`` makes, each with what is wrong, and no
    field the node would not write back (``editProblem``)."""
    if not isinstance(raw, dict):
        return "is not a dict"
    op = raw.get("op", _MISSING)
    if not _one_of(op, EDIT_OPS):
        return f"has the op {_show(op)}, which is none of {', '.join(EDIT_OPS)}"
    allowed = (*COMMON_FIELDS, *EDIT_FIELDS[op])
    extra = next((name for name in js_values.keys(raw) if name not in allowed), None)
    if extra is not None:
        return f"is {with_article(op)}, which takes no {extra}"
    layer = raw.get("layer", _MISSING)
    if layer is not _MISSING and (not isinstance(layer, str) or layer == ""):
        return "has a layer that is not a name"
    label = raw.get("label", _MISSING)
    if label is not _MISSING and not isinstance(label, str):
        return "has a label that is not a text"
    if isinstance(label, str) and js_values.trim(label) == "":
        return "has an empty label"
    enabled = raw.get("enabled", _MISSING)
    if enabled is not _MISSING and not isinstance(enabled, bool):
        return "has an enabled that is not True or False"
    crs = raw.get("crs", _MISSING)
    if crs is not _MISSING and (not isinstance(crs, str) or crs == ""):
        return "has a crs that is not a CRS name"
    if op == "add":
        if not _is_id(raw.get("id", _MISSING)):
            return "adds a feature with no id"
        if not _is_geometry(raw.get("geometry", _MISSING)):
            return "adds a feature with no geometry the node reads"
        values = raw.get("values", _MISSING)
        if values is _MISSING:
            return None
        if not isinstance(values, dict):
            return "adds a feature whose values are not a dict"
        bad = next((column for column in js_values.keys(values) if column == "" or not _is_value(values[column])), None)
        return f"adds a feature whose {bad or 'unnamed value'} {NOT_A_VALUE}" if bad is not None else None
    if op == "add_column":
        column = raw.get("column", _MISSING)
        if not isinstance(column, str) or column == "":
            return "adds a property but names none"
        value = raw.get("value", _MISSING)
        return None if value is _MISSING or _is_value(value) else f"gives {column} a value that {NOT_A_VALUE}"
    by_ids = "ids" in raw
    by_where = "where" in raw
    if by_ids and by_where:
        return "names its features both by ids and by a condition"
    if not by_ids and not by_where:
        return "names no features: it takes ids or a where condition"
    where = raw.get("where")
    if by_where and (not isinstance(where, str) or js_values.trim(where) == ""):
        return "has a where that is not a condition"
    where_problem = _expr_problem(where) if by_where else None
    if where_problem:
        return f"has the condition {_show(where)}, which is not one: {where_problem}"
    ids = raw.get("ids")
    if by_ids and (not isinstance(ids, list) or len(ids) == 0):
        return "has ids that are not a list of ids"
    if by_ids and any(not _is_id(value) for value in ids):
        not_id = next(value for value in ids if not _is_id(value))
        return f"names {_show(not_id)}, which is not an id"
    if op == "geometry" and not _is_geometry(raw.get("geometry", _MISSING)):
        return "redraws features with no geometry the node reads"
    if op not in WRITE_OPS:
        return None
    column = raw.get("column", _MISSING)
    if not isinstance(column, str) or column == "":
        return "writes a value but names no column"
    value = raw.get("value", _MISSING)
    if value is _MISSING:
        return f"writes no value into {column}"
    if not _is_value(value):
        return f"writes a value into {column} that {NOT_A_VALUE}"
    if op in ("scale", "offset") and not js_values.is_number(value):
        return f"{'scales' if op == 'scale' else 'offsets'} {column} by {_show(value)}, which is not a number"
    if op == "expr" and not isinstance(value, str):
        return f"computes {column} from {_show(value)}, which is not an expression"
    formula_problem = _expr_problem(value) if op == "expr" else None
    if formula_problem:
        return f"computes {column} from {_show(value)}, which is not an expression: {formula_problem}"
    return None


def new_layer_problem(raw):
    """Why the dict *raw* is not a layer the node makes, or None when it is
    one (``newLayerProblem``)."""
    if not isinstance(raw, dict):
        return "is not a dict"
    extra = next((name for name in js_values.keys(raw) if name not in NEW_LAYER_FIELDS), None)
    if extra is not None:
        return f"takes no {extra}"
    name = raw.get("name", _MISSING)
    if not isinstance(name, str) or js_values.trim(name) == "" or name != js_values.trim(name):
        return "has no name"
    geometry = raw.get("geometry", _MISSING)
    if not _one_of(geometry, NEW_LAYER_GEOMETRIES):
        return f"has the geometry {_show(geometry)}, which is none of {', '.join(NEW_LAYER_GEOMETRIES)}"
    properties = raw.get("properties", _MISSING)
    if properties is _MISSING:
        return None
    if not isinstance(properties, list):
        return "has properties that are not a list"
    names = set()
    for prop in properties:
        if not isinstance(prop, dict):
            return "has a property that is not a dict"
        prop_name = prop.get("name", _MISSING)
        if not isinstance(prop_name, str) or js_values.trim(prop_name) == "" or prop_name != js_values.trim(prop_name):
            return "has a property with no name"
        more = next((field for field in js_values.keys(prop) if field not in PROPERTY_FIELDS), None)
        if more is not None:
            return f"has a property {prop_name} that takes no {more}"
        if prop_name in names:
            return f"gives the property {prop_name} twice"
        names.add(prop_name)
        prop_type = prop.get("type", _MISSING)
        if not _one_of(prop_type, PROPERTY_TYPES):
            return (
                f"has a property {prop_name} of the type {_show(prop_type)}, "
                f"which is none of {', '.join(PROPERTY_TYPES)}"
            )
        required = prop.get("required", _MISSING)
        if required is not _MISSING and not isinstance(required, bool):
            return f"has a property {prop_name} whose required is not True or False"
        choices = prop.get("choices", _MISSING)
        if choices is not _MISSING and (
            not isinstance(choices, list)
            or any(not isinstance(c, str) or js_values.trim(c) == "" or c != js_values.trim(c) for c in choices)
        ):
            return f"has a property {prop_name} whose choices are not a list of texts"
        default = prop.get("default", _MISSING)
        if default is not _MISSING and not _is_value(default):
            return f"has a property {prop_name} whose default {NOT_A_VALUE}"
    return None


def read_call_args(text: str, start: int, call: str, names) -> tuple[list, dict]:
    """The arguments of the call whose ``(`` ends just before *start* in
    *text*, and nothing after it: its positional literals in order, then its
    keywords (``readCallArgs``). Values are literals; a bare name is read only
    in the positional places *names* takes (the call's input). Whitespace and
    line breaks may stand between any two tokens, a list, a dict or the call
    may end in a comma, and a comment inside the call is refused: it would be
    lost when the node writes its code again."""
    pos = start

    def at(index: int):
        return text[index] if 0 <= index < len(text) else None

    def fail(what: str):
        raise Unreadable(f"Line {len(_LINES.split(text[:pos]))}: {what}.")

    def missing(what: str):
        fail("the call is not closed" if pos >= len(text) else what)

    def skip() -> None:
        nonlocal pos
        while pos < len(text):
            c = text[pos]
            if c == "#":
                raise Unreadable("The call holds a comment, which would be lost when the node writes its code.")
            if c not in " \t\f\n\r":
                return
            pos += 1

    def word():
        nonlocal pos
        found = _WORD.match(text, pos)
        if not found:
            return None
        pos = found.end()
        return found.group(0)

    def hex_digits(digits: int) -> int:
        nonlocal pos
        found = text[pos:pos + digits]
        if not re.fullmatch(f"[0-9a-fA-F]{{{digits}}}", found):
            fail("a text has an escape cut short")
        pos += digits
        return int(found, 16)

    def escape() -> str:
        nonlocal pos
        c = at(pos + 1)
        pos += 2
        if c is not None and c in _ESCAPES:
            return _ESCAPES[c]
        if c == "x":
            return chr(hex_digits(2))
        if c in ("u", "U"):
            code = hex_digits(4 if c == "u" else 8)
            if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                fail("a text escapes a character Unicode has not")
            return chr(code)
        if c is not None and "0" <= c <= "7":
            digits = _OCTAL.match(text, pos - 1).group(0)
            pos += len(digits) - 1
            return chr(int(digits, 8))
        pos -= 2
        fail("a text goes on past its line" if c in ("\n", "\r") else f"\\{c or ''} is not an escape the node reads")

    def string() -> str:
        nonlocal pos
        quote = text[pos]
        if text.startswith(quote * 3, pos):
            fail("the node reads texts in single or double quotes, not in triple quotes")
        pos += 1
        out = []
        while True:
            c = at(pos)
            if c is None or c in ("\n", "\r"):
                fail("a text is not closed on its line")
            if c == quote:
                pos += 1
                return "".join(out)
            if c == "\\":
                out.append(escape())
            else:
                out.append(c)
                pos += 1

    def number():
        nonlocal pos
        sign = -1 if at(pos) == "-" else 1
        if at(pos) in ("-", "+"):
            pos += 1
            skip()
        found = _NUMBER.match(text, pos)
        if not found:
            fail("a sign stands before no number")
        literal = found.group(0)
        pos = found.end()
        after = at(pos)
        if after is not None and re.fullmatch(r"[A-Za-z0-9_.]", after):
            fail(f"{literal}{after} is not a number the node reads")
        whole = re.fullmatch(r"[0-9]+", literal) is not None
        if whole and re.match(r"0+[1-9]", literal):
            fail(f"{literal} starts with a zero, which Python refuses")
        if whole:
            value = sign * int(literal)
            if abs(value) > 2 ** 53 - 1:
                fail(f"{literal} is too large to read exactly")
            return value
        value = sign * float(literal)
        if not math.isfinite(value):
            fail(f"{literal} is too large to read exactly")
        return value

    def value(named: bool) -> Literal:
        nonlocal pos
        skip()
        c = at(pos)
        if c == "[":
            pos += 1
            items = []
            while True:
                skip()
                if at(pos) == "]":
                    break
                items.append(value(named))
                skip()
                if at(pos) == ",":
                    pos += 1
                elif at(pos) != "]":
                    missing("an item of a list has no , or ] after it")
            pos += 1
            return Literal("list", items=items)
        if c == "{":
            pos += 1
            entries = []
            while True:
                skip()
                if at(pos) == "}":
                    break
                key = value(False)
                skip()
                if at(pos) != ":":
                    missing("a key of a dict has no : after it")
                pos += 1
                entries.append((key, value(False)))
                skip()
                if at(pos) == ",":
                    pos += 1
                elif at(pos) != "}":
                    missing("a value of a dict has no , or } after it")
            pos += 1
            return Literal("dict", entries=entries)
        if c in ('"', "'"):
            return Literal("value", value=string())
        if c is not None and c in "-+.0123456789":
            return Literal("value", value=number())
        name = word()
        if name in ("True", "False"):
            return Literal("value", value=name == "True")
        if name == "None":
            return Literal("value", value=None)
        if name is not None and named:
            return Literal("name", name=name)
        if name is not None:
            fail(f"{name} is not a value written out")
        fail("the call is not closed" if c is None else f"{c} does not start a value the node reads")

    positional: list[Literal] = []
    keywords: dict[str, Literal] = {}
    skip()
    while at(pos) != ")":
        if pos >= len(text):
            fail("the call is not closed")
        # A keyword: a name and one =, not ==.
        start_of = pos
        name = word()
        skip()
        if name is not None and at(pos) == "=" and at(pos + 1) != "=":
            if name in keywords:
                raise Unreadable(f"The call gives {name} twice.")
            pos += 1
            keywords[name] = value(False)
        else:
            pos = start_of
            if keywords:
                raise Unreadable("The call gives a value without its name after one with a name.")
            positional.append(value(names(len(positional))))
        skip()
        if at(pos) == ",":
            pos += 1
            skip()
        elif at(pos) != ")":
            missing("an argument has no , or ) after it")
    pos += 1
    if not re.fullmatch(r"[ \t\f\r\n]*", text[pos:]):
        raise Unreadable(f"The code goes on after the {call} call.")
    return positional, keywords


def json_of(literal: Literal, where: str):
    """*literal* as JSON: a dict's keys must be texts, each once; *where*
    names it in a reason (``jsonOf``). A dict keeps its keys in the order the
    browser keeps them (``js_values.keys``)."""
    if literal.kind == "value":
        return literal.value
    if literal.kind == "name":
        raise Unreadable(f"{where} holds {literal.name}, which is not a value written out.")
    if literal.kind == "list":
        return [json_of(item, where) for item in literal.items]
    out = {}
    for key, item in literal.entries:
        if key.kind != "value" or not isinstance(key.value, str):
            raise Unreadable(f"A dict in {where} has the key {shown(key)}, which is not a text.")
        if key.value in out:
            raise Unreadable(f"A dict in {where} gives {key.value} twice.")
        out[key.value] = json_of(item, where)
    return js_values.ordered(out)


def _circles_of(literal) -> int:
    """The circles the call's first argument hands the step: ``input_0``, or
    ``[input_0, input_1, ...]``."""
    if literal is not None and literal.kind == "name" and literal.name == "input_0":
        return 1
    if (
        literal is not None and literal.kind == "list" and len(literal.items) > 1
        and all(item.kind == "name" and item.name == f"input_{k}" for k, item in enumerate(literal.items))
    ):
        return len(literal.items)
    raise Unreadable(
        "The call's first argument is neither input_0 nor a list of the inputs in order, [input_0, input_1, ...]."
    )


def _text_arg(literal, name: str):
    """A keyword that holds a text, or None."""
    if literal is None or (literal.kind == "value" and literal.value is None):
        return None
    if literal.kind == "value" and isinstance(literal.value, str):
        return None if literal.value == "" else literal.value
    raise Unreadable(f"{name} is not a text.")


def _settings_of(positional: list, keywords: dict) -> tuple:
    """The settings the call's arguments hold, and its circles."""
    if len(positional) < 2:
        raise Unreadable(f"The call takes its input and its list of edits, then {', '.join(KEYWORDS)} by name.")
    if len(positional) > 2:
        raise Unreadable(f"After its input and its edits, the call takes {', '.join(KEYWORDS)} by name.")
    other = next((name for name in keywords if name not in KEYWORDS), None)
    if other is not None:
        raise Unreadable(f"{EDIT_HELPER} takes {', '.join(KEYWORDS)}, not {other}.")
    circles = _circles_of(positional[0])
    by_input = keywords.get("by_input")
    several = by_input is not None and by_input.kind == "value" and by_input.value is True
    if by_input is not None and not (by_input.kind == "value" and (isinstance(by_input.value, bool) or by_input.value is None)):
        raise Unreadable("by_input is not True or False.")
    if several != (circles > 1):
        raise Unreadable(
            "A list of inputs takes by_input=True." if circles > 1
            else "by_input=True takes a list of inputs, [input_0, input_1, ...]."
        )
    raw: dict = {}
    key = _text_arg(keywords.get("key"), "key")
    layer = _text_arg(keywords.get("layer"), "layer")
    crs = _text_arg(keywords.get("crs"), "crs")
    if key:
        raw["key"] = key
    if layer:
        raw["layer"] = layer
    if crs:
        raw["crs"] = crs
    keys = keywords.get("keys")
    if keys is not None and not (keys.kind == "value" and keys.value is None):
        value = json_of(keys, "keys")
        if not isinstance(value, dict) or any(
            name == "" or not isinstance(column, str) or column == "" for name, column in value.items()
        ):
            raise Unreadable("keys is not a dict of layer names and the columns that identify their features.")
        raw["keys"] = value
    new_layers = keywords.get("new_layers")
    if new_layers is not None and not (new_layers.kind == "value" and new_layers.value is None):
        value = json_of(new_layers, "new_layers")
        if not isinstance(value, list):
            raise Unreadable("new_layers is not a list of layers.")
        for index, item in enumerate(value):
            problem = new_layer_problem(item)
            if problem:
                raise Unreadable(f"New layer {index + 1} {problem}.")
        raw["newLayers"] = value
    edits = positional[1]
    if edits.kind != "list":
        raise Unreadable(f"The call's second argument is {shown(edits)}, not a list of edits.")
    raw_edits = []
    for index, item in enumerate(edits.items):
        value = json_of(item, "the edits")
        problem = edit_problem(value)
        if problem:
            raise Unreadable(f"Edit {index + 1} {problem}.")
        raw_edits.append(value)
    raw["edits"] = raw_edits
    return normalize_edit_features(raw), circles


def read_edit_features_code(code) -> dict:
    """What the node makes of *code* (``readEditFeaturesCode``):
    ``{"settings", "circles", "comments"}``, the edits, how many circles the
    call hands the step and the comment lines above its call, or
    ``{"problem"}``, why the node cannot read it. Blank code is a new node:
    ``{"settings": None}``. Otherwise the code is comment and blank lines,
    then ``return curio_edit_features(input, [edits], ...)`` from the start of
    its line: its input (``input_0``, or every circle's with ``by_input=True``),
    its edits, each a dict the node writes (``edit_problem``), and the
    keywords ``key``, ``layer``, ``keys``, ``new_layers``, ``crs`` and
    ``by_input`` in any order, each at most once and each a literal. Anything
    else is refused: another statement, a comment inside the call, a
    reference, a field the node would not write back."""
    text = code if isinstance(code, str) else ""
    if js_values.trim(text) == "":
        return {"settings": None}
    head = _HEAD.match(text).group(0)
    comments = _LINES.split(head)[:-1]
    call = text[len(head):]
    opening = _OPENING.match(call)
    if not opening:
        if _INDENTED_RETURN.match(call):
            return {"problem": "The return line starts with spaces; the node writes it from the line's start."}
        return {"problem": NOT_THE_CALL}
    if _REFERENCE.search(call):
        return {"problem": "The call holds a [!! !!] reference, whose value the node cannot know before a run."}
    try:
        positional, keywords = read_call_args(text, len(head) + opening.end(), EDIT_HELPER, lambda position: position == 0)
        settings, circles = _settings_of(positional, keywords)
    except Unreadable as error:
        return {"problem": str(error)}
    return {"settings": settings, "circles": circles, "comments": comments}
