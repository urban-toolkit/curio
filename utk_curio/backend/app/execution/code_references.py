"""Turning a node's references into code (#662): ``[!! season !!]`` names a
widget, ``[!! input 1 !!]`` an input (by circle, counted from 0),
``[!! input 1.height !!]`` a column of that input, ``[!! input 1:roads !!]``
(or ``[!! input 1:roads.height !!]``) a layer an input carries, and
``[!! @season !!]`` a shared tag: the widget of the Parameter node named
``season``.

The headless twin of ``src/utils/references/codeReferences.ts``, which the
browser runs before posting a node's code. Both write the same code: one table
of cases, ``codeReferences.cases.json`` beside the TypeScript module, is read by
Jest and by ``tests/test_execution/test_code_references.py``.

A widget or shared reference standing on its own becomes a literal of the language;
inside a string literal it becomes the value's text, escaped for that string;
inside a comment, the plain text. A column or layer reference is written like a
text value: its name. In Python and JavaScript an input reference becomes
``arg`` when the node has one input and ``arg[i]`` when it has several, ``i``
being its place in circle order; in a Vega-Lite or Autark spec it is the name
the input is read by, ``input_<i>``, written like a text value.
Numbers are written the way JavaScript's ``String()`` writes them, so a value
prints the same in both.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

#: A reference as written. Kept in sync with ``REFERENCE_PATTERN``.
REFERENCE_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")

#: What stands inside an input, layer or column reference. Kept in sync with
#: ``INPUT_REFERENCE_PATTERN`` in ``codeReferences.ts``.
INPUT_REFERENCE_RE = re.compile(r"^input\s+(\d+|\?)(?::([^.]+))?(?:\.(.+))?$")

#: What a shared reference starts with. Kept in sync with ``SHARED_PREFIX`` in
#: ``codeReferences.ts``.
SHARED_PREFIX = "@"

#: What a Vega-Lite or Autark node calls its inputs. Kept in sync with
#: ``INPUT_TABLE_PREFIX`` in ``agents/domain/contracts.py``.
INPUT_TABLE_PREFIX = "input_"

#: A widget name. Kept in sync with ``WIDGET_NAME_PATTERN`` in ``widgetModel.ts``.
WIDGET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

LANGUAGES = ("python", "javascript", "json")

#: The widget kinds. Kept in sync with ``WIDGET_KINDS`` in ``widgetModel.ts``.
WIDGET_KINDS = (
    "number",
    "slider",
    "text",
    "choice",
    "checkbox",
    "checkbox-group",
    "multi-select",
    "datetime",
    "location",
    "number-list",
    "text-list",
    "range",
    "file",
)


class CodeReferenceError(ValueError):
    """A node's code holds references it cannot resolve."""


def effective_value(widget: dict):
    return widget["value"] if "value" in widget else widget.get("default")


def js_number(x) -> str:
    """*x* as JavaScript's ``String(x)`` writes it."""
    if isinstance(x, int):
        if abs(x) < 10 ** 21:
            return str(x)
        x = float(x)
    if x == 0:
        return "0"
    # Through repr for every float, integral ones too: repr has JavaScript's
    # shortest round-trip digits, where str(int(x)) would print 1.2345678901234568e20
    # as 123456789012345677824 instead of 123456789012345680000.
    sign = "-" if x < 0 else ""
    text = repr(abs(x))
    mantissa, _, exponent = text.partition("e")
    exp = int(exponent) if exponent else 0
    int_part, _, frac = mantissa.partition(".")
    all_digits = int_part + frac
    lead = len(all_digits) - len(all_digits.lstrip("0"))
    digits = all_digits.lstrip("0").rstrip("0") or "0"
    k = len(digits)
    n = (len(int_part) - lead) + exp
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    head = digits[0] + ("." + digits[1:] if k > 1 else "")
    return sign + head + "e" + ("+" if e >= 0 else "-") + str(abs(e))


def widget_literal(value, language: str) -> str:
    """*value* as a literal of *language*."""
    if value is None:
        return "None" if language == "python" else "null"
    if isinstance(value, bool):
        if language == "python":
            return "True" if value else "False"
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return "None" if language == "python" else "null"
        return js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(widget_literal(v, language) for v in value) + "]"
    if isinstance(value, dict):
        # A location's {"lat": ..., "lon": ...}: a dict in Python, an object in
        # JavaScript and JSON.
        return "{" + ", ".join(
            json.dumps(str(k), ensure_ascii=False) + ": " + widget_literal(v, language) for k, v in value.items()
        ) + "}"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_reference(inner: str) -> dict:
    """``{"kind": "widget", "name"}``, ``{"kind": "shared", "name"}`` or
    ``{"kind": "input", "slot", "layer"?, "column"?}``; ``slot`` is None for
    ``input ?``, the input whose edge was deleted."""
    m = INPUT_REFERENCE_RE.match(inner)
    if not m:
        if inner.startswith(SHARED_PREFIX):
            return {"kind": "shared", "name": inner[len(SHARED_PREFIX):]}
        return {"kind": "widget", "name": inner}
    parsed = {"kind": "input", "slot": None if m.group(1) == "?" else int(m.group(1))}
    if m.group(2) is not None:
        parsed["layer"] = m.group(2)
    if m.group(3) is not None:
        parsed["column"] = m.group(3)
    return parsed


def reference_text(inner: str) -> str:
    """The text of a reference to *inner*; ``referenceText`` in ``codeReferences.ts``."""
    return f"[!! {inner} !!]"


def input_reference_inner(slot: int | None, column: str | None = None, layer: str | None = None) -> str:
    """What stands inside a reference to input *slot*, to one of its layers, or
    to a column of either; ``inputReferenceInner`` in ``codeReferences.ts``."""
    return (
        f"input {'?' if slot is None else slot}"
        + (f":{layer}" if layer is not None else "")
        + (f".{column}" if column is not None else "")
    )


def _text_of(value, language: str) -> str:
    return value if isinstance(value, str) else widget_literal(value, language)


def _escape_for(text: str, context: tuple, language: str) -> str:
    kind = context[0]
    if kind == "comment":
        return text.replace("\r\n", " ").replace("\n", " ")
    if kind == "code":
        return text
    if language == "json":
        return json.dumps(text, ensure_ascii=False)[1:-1]
    quote = context[1]
    out = text.replace("\\", "\\\\")
    if quote == "`":
        return out.replace("`", "\\`").replace("${", "\\${")
    if len(quote) == 3:
        return out.replace(quote[0], "\\" + quote[0])
    out = out.replace(quote, "\\" + quote)
    return out.replace("\n", "\\n").replace("\r", "\\r")


def _contexts(code: str, refs: list, language: str) -> list:
    """Where each reference sits: ``("code",)``, ``("comment",)`` or ``("string", quote)``."""
    contexts: list = []
    state = "code"
    quote = ""
    i = 0
    r = 0

    def current():
        if state == "string":
            return ("string", quote)
        return ("code",) if state == "code" else ("comment",)

    while i < len(code) or r < len(refs):
        if r < len(refs) and i >= refs[r].start():
            contexts.append(current())
            i = max(i, refs[r].end())
            r += 1
            continue
        if i >= len(code):
            break
        ch = code[i]
        if state == "code":
            if language == "python" and ch == "#":
                state = "comment"
            elif language == "javascript" and code.startswith("//", i):
                state = "comment"
                i += 2
                continue
            elif language == "javascript" and code.startswith("/*", i):
                state = "block"
                i += 2
                continue
            elif ch == '"' or (language != "json" and (ch == "'" or (language == "javascript" and ch == "`"))):
                if language == "python" and code.startswith(ch * 3, i):
                    quote = ch * 3
                    state = "string"
                    i += 3
                    continue
                quote = ch
                state = "string"
        elif state == "comment":
            if ch == "\n":
                state = "code"
        elif state == "block":
            if code.startswith("*/", i):
                state = "code"
                i += 2
                continue
        else:
            if ch == "\\":
                i += 2
                continue
            if len(quote) == 3:
                if code.startswith(quote, i):
                    state = "code"
                    i += 3
                    continue
            elif ch == quote:
                state = "code"
            elif ch == "\n" and quote != "`":
                # An unterminated one-line string ends with its line.
                state = "code"
        i += 1
    return contexts


def _write_text(text: str, context: tuple, language: str) -> str:
    return widget_literal(text, language) if context[0] == "code" else _escape_for(text, context, language)


def reference_problem(
    reference: str, inner: str, widgets: list, inputs: list, context: tuple, language: str, shared: list = ()
) -> str | None:
    """Why *reference* cannot be resolved against *widgets*, *inputs* and the
    *shared* tags, standing in *context*, or None."""
    parsed = parse_reference(inner)
    if parsed["kind"] == "shared":
        name = parsed["name"]
        if not WIDGET_NAME_RE.match(name):
            return (
                f"{reference} does not name a Parameter node. "
                "Parameter names are letters, digits and underscores."
            )
        named = sum(1 for w in shared if w.get("name") == name)
        if named == 0:
            return f"{reference}: no Parameter node is named {name}. Add one, or drag a tag from Shared."
        if named > 1:
            return f"{reference}: {named} Parameter nodes are named {name}. Rename all but one."
        return None
    if parsed["kind"] == "input":
        slot = parsed["slot"]
        if slot is None:
            return f"{reference}: the edge for this input was deleted. Drag one of this node's input chips here."
        found = next((i for i in inputs if i.get("slot") == slot), None)
        if found is None:
            return (
                f"{reference}: input {slot} has no edge. Connect one to that circle, "
                "or drag one of this node's input chips here."
            )
        if "layer" in parsed:
            if language != "json":
                return f"{reference}: a layer chip works in Vega-Lite and Autark specs."
            layers = found.get("layers") if isinstance(found.get("layers"), list) else None
            layer = next((l for l in layers or [] if l.get("name") == parsed["layer"]), None)
            if layers is not None and layer is None:
                return f"{reference}: input {slot} has no layer {parsed['layer']}."
            columns = layer.get("columns") if layer else None
            if "column" in parsed and isinstance(columns, list) and parsed["column"] not in columns:
                return f"{reference}: layer {parsed['layer']} of input {slot} has no column {parsed['column']}."
            return None
        if "column" not in parsed:
            if language == "json":
                layers = found.get("layers")
                if isinstance(layers, list) and len(layers) > 1:
                    names = ", ".join(str(l.get("name")) for l in layers)
                    return (
                        f"{reference}: input {slot} carries several layers ({names}). "
                        "Drag one of its layer chips here."
                    )
                return None
            if context[0] != "code":
                return f"{reference} is an input, not text. Use it outside quotes and comments."
            return None
        columns = found.get("columns")
        if isinstance(columns, list) and parsed["column"] not in columns:
            return f"{reference}: input {slot} has no column {parsed['column']}."
        return None
    if "$" in inner:
        return (
            f"{reference} is an old widget marker. Add the widget in the node's "
            "Widgets tab and drag its tag into the code."
        )
    if not WIDGET_NAME_RE.match(inner):
        return f"{reference} does not name a widget. Widget names are letters, digits and underscores."
    if not any(w.get("name") == inner for w in widgets):
        return f"{reference}: this node has no widget named {inner}. Add it in the Widgets tab."
    return None


#: A date-time widget's value when its widget gives none. Kept in sync with
#: ``DATETIME_FALLBACK`` in ``widgetModel.ts``.
DATETIME_FALLBACK = "1970-01-01T00:00:00"


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def default_value_for(kind, options) -> object:
    """A kind's value when a widget gives no default, as ``defaultValueFor`` in
    ``widgetModel.ts`` writes it."""
    options = options if isinstance(options, dict) else {}
    if kind in ("number", "slider"):
        return options["min"] if _finite(options.get("min")) else 0
    if kind == "checkbox":
        return False
    if kind == "choice":
        choices = [c for c in options.get("choices") or [] if isinstance(c, str)]
        return choices[0] if choices else ""
    if kind in ("checkbox-group", "multi-select", "number-list", "text-list"):
        return []
    if kind == "range":
        return [0, 1]
    if kind == "datetime":
        return DATETIME_FALLBACK
    if kind == "location":
        return {"lat": 0, "lon": 0}
    return ""


def normalize_widgets(raw) -> list:
    """The well-formed widgets in *raw* (a spec's ``metadata.widgets``). A
    widget without a default gets its kind's, as the browser gives it."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not WIDGET_NAME_RE.match(name) or name in seen:
            continue
        if entry.get("type") not in WIDGET_KINDS:
            continue
        seen.add(name)
        if entry.get("default") is None:
            entry = {**entry, "default": default_value_for(entry.get("type"), entry.get("options"))}
        out.append(entry)
    return out


def normalize_shared(raw) -> list:
    """The well-formed widgets in *raw*, one per Parameter node, as
    :func:`normalize_widgets` reads each. Unlike a node's own widgets, two with
    one name are both kept, so a reference to that name can say so."""
    out: list = []
    for entry in raw if isinstance(raw, (list, tuple)) else []:
        out.extend(normalize_widgets([entry]))
    return out


def _resolved_text(
    inner: str, by_name: dict, inputs: list, context: tuple, language: str, shared_by_name: dict
) -> str:
    parsed = parse_reference(inner)
    if parsed["kind"] == "shared":
        value = effective_value(shared_by_name[parsed["name"]])
        if context[0] == "code":
            return widget_literal(value, language)
        return _escape_for(_text_of(value, language), context, language)
    if parsed["kind"] == "input":
        if "column" in parsed:
            return _write_text(parsed["column"], context, language)
        if "layer" in parsed:
            return _write_text(parsed["layer"], context, language)
        index = next(i for i, entry in enumerate(inputs) if entry.get("slot") == parsed["slot"])
        if language == "json":
            return _write_text(f"{INPUT_TABLE_PREFIX}{index}", context, language)
        if len(inputs) == 1:
            return "arg"
        return f"arg[{index}]"
    value = effective_value(by_name[inner])
    if context[0] == "code":
        return widget_literal(value, language)
    return _escape_for(_text_of(value, language), context, language)


def resolve_references(
    code: str, widgets: Iterable = (), language: str = "python", inputs: Iterable = (), shared: Iterable = ()
) -> tuple[str, list]:
    """*code* with every reference replaced, and the problems found.

    *inputs* are the node's wired inputs, ``{"slot": <circle>, "columns"?: [...]}``
    each. *shared* are the widgets of the dataflow's Parameter nodes, one per
    node. A reference with a problem is left as written; each problem is
    ``{"reference": <as written>, "message": <why>}``.
    """
    if language not in LANGUAGES:
        raise ValueError(f"unknown code language {language!r}")
    widgets = normalize_widgets(list(widgets or []))
    shared = normalize_shared(list(shared or []))
    inputs = sorted((dict(i) for i in inputs or ()), key=lambda i: i.get("slot", 0))
    refs = list(REFERENCE_RE.finditer(code))
    if not refs:
        return code, []
    contexts = _contexts(code, refs, language)
    by_name = {w["name"]: w for w in widgets}
    shared_by_name = {w["name"]: w for w in shared}
    problems: list = []
    out: list = []
    last = 0
    for ref, context in zip(refs, contexts):
        out.append(code[last:ref.start()])
        written = ref.group(0)
        problem = reference_problem(written, ref.group(1), widgets, inputs, context, language, shared)
        if problem is not None:
            problems.append({"reference": written, "message": problem})
            out.append(written)
        else:
            out.append(_resolved_text(ref.group(1), by_name, inputs, context, language, shared_by_name))
        last = ref.end()
    out.append(code[last:])
    return "".join(out), problems
