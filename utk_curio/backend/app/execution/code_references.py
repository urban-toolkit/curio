"""Turning a node's references into code (#662): ``[!! season !!]`` names a
widget, ``[!! input 1 !!]`` an input (by circle, counted from 0),
``[!! input 1.height !!]`` a column of that input, ``[!! input 1:roads !!]``
(or ``[!! input 1:roads.height !!]``) a layer an input carries,
``[!! @season !!]`` a shared tag: the widget of the Parameter node named
``season``, and ``[!! selection picked !!]`` one of the node's selection tags:
the ids of the rows a view's selection picks, which the node holds at
``metadata.selections``.

The headless twin of ``src/utils/references/codeReferences.ts``, which the
browser runs before posting a node's code. Both write the same code: one table
of cases, ``codeReferences.cases.json`` beside the TypeScript module, is read by
Jest and by ``tests/test_execution/test_code_references.py``.

A widget, shared or selection reference standing on its own becomes a literal
of the language (a selection's ids are a list); inside a string literal it
becomes the value's text, escaped for that string;
inside a comment, the plain text. A column reference is written like a text
value: its name. In Python and JavaScript an input reference becomes ``arg``
when the node has one input and ``arg[i]`` when it has several, ``i`` being its
place in circle order, and a layer reference the call that picks the layer out
of it, ``curio_layer(arg[i], "roads", 1)`` (the sandbox's
``util/input_layers.py``, and ``js_wrapper.mjs``); in a Vega-Lite or Autark spec
an input reference is the name the input is read by, ``input_<i>``, and a layer
reference the layer's name, written like a text value.
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

#: What stands inside a selection reference, ``selection picked``. Kept in sync
#: with ``SELECTION_REFERENCE_PATTERN`` in ``codeReferences.ts``.
SELECTION_REFERENCE_RE = re.compile(r"^selection\s+(.+)$")

#: The most ids one selection tag holds. Kept in sync with ``SELECTION_ID_CAP``
#: in ``selectionTags.ts`` and ``maxItems`` in ``docs/schemas/trill.v1.json``.
SELECTION_ID_CAP = 10000

#: What a Vega-Lite or Autark node calls its inputs. Kept in sync with
#: ``INPUT_TABLE_PREFIX`` in ``agents/domain/contracts.py``.
INPUT_TABLE_PREFIX = "input_"

#: What a layer reference in Python or JavaScript calls. Kept in sync with
#: ``LAYER_HELPER`` in ``codeReferences.ts`` and the sandbox's
#: ``util/input_layers.py``.
LAYER_HELPER = "curio_layer"

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
    """``{"kind": "widget", "name"}``, ``{"kind": "shared", "name"}``,
    ``{"kind": "selection", "name"}`` or ``{"kind": "input", "slot",
    "layer"?, "column"?}``; ``slot`` is None for ``input ?``, the input whose
    edge was deleted."""
    m = INPUT_REFERENCE_RE.match(inner)
    if not m:
        selection = SELECTION_REFERENCE_RE.match(inner)
        if selection:
            return {"kind": "selection", "name": selection.group(1)}
        if inner.startswith(SHARED_PREFIX):
            return {"kind": "shared", "name": inner[len(SHARED_PREFIX):]}
        return {"kind": "widget", "name": inner}
    parsed = {"kind": "input", "slot": None if m.group(1) == "?" else int(m.group(1))}
    if m.group(2) is not None:
        parsed["layer"] = m.group(2)
    if m.group(3) is not None:
        parsed["column"] = m.group(3)
    return parsed


def _names_of_kind_in(code: object, kind: str) -> list[str]:
    names: list[str] = []
    for ref in REFERENCE_RE.finditer(code if isinstance(code, str) else ""):
        parsed = parse_reference(ref.group(1))
        if parsed["kind"] == kind and parsed["name"] not in names:
            names.append(parsed["name"])
    return names


def shared_names_in(code: object) -> list[str]:
    """The names of the shared tags *code* references, each once, in order.
    Kept in sync with ``sharedNamesIn`` in ``codeReferences.ts``."""
    return _names_of_kind_in(code, "shared")


def selection_names_in(code: object) -> list[str]:
    """The names of the selection tags *code* references, each once, in order.
    Kept in sync with ``selectionNamesIn`` in ``codeReferences.ts``."""
    return _names_of_kind_in(code, "selection")


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


def missing_layer_message(reference: str, slot, layer: str, names) -> str:
    """Why *reference* fails: input *slot* has no layer *layer*. It names the
    layers the input has. The resolver says it when the layers are known, and
    the sandbox's ``curio_layer`` says the same of a layer reference when the
    node runs. Kept in sync with ``missingLayerMessage`` in
    ``codeReferences.ts`` and with the sandbox's ``util/input_layers.py`` and
    ``js_wrapper.mjs``."""
    names = list(names)
    has = f"Its layers are {', '.join(names)}." if names else "It carries no named layers."
    return f"{reference}: input {slot} has no layer {layer}. {has}"


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


def _over_cap(tag: dict) -> bool:
    ids = tag.get("ids")
    return not isinstance(ids, list) or len(ids) > SELECTION_ID_CAP


def _selection_size(tag: dict) -> int:
    ids = tag.get("ids")
    return len(ids) if isinstance(ids, list) else int(tag.get("count") or 0)


def reference_problem(
    reference: str,
    inner: str,
    widgets: list,
    inputs: list,
    context: tuple,
    language: str,
    shared: list = (),
    selections: list = (),
) -> str | None:
    """Why *reference* cannot be resolved against *widgets*, *inputs*, the
    *shared* tags and the node's *selections*, standing in *context*, or None."""
    parsed = parse_reference(inner)
    if parsed["kind"] == "selection":
        name = parsed["name"]
        if not WIDGET_NAME_RE.match(name):
            return (
                f"{reference} does not name a selection tag. "
                "Selection tag names are letters, digits and underscores."
            )
        tag = next((t for t in selections if t.get("name") == name), None)
        if tag is None:
            return f"{reference}: this node has no selection tag named {name}. Add it in the Widgets tab."
        if _over_cap(tag):
            return (
                f"{reference}: the selection holds {_selection_size(tag)} ids, more than the "
                f"{SELECTION_ID_CAP} a selection tag takes. Select fewer rows in its view."
            )
        return None
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
            layers = found.get("layers") if isinstance(found.get("layers"), list) else None
            layer = next((l for l in layers or [] if l.get("name") == parsed["layer"]), None)
            if layers is not None and layer is None:
                return missing_layer_message(reference, slot, parsed["layer"], (str(l.get("name")) for l in layers))
            # An input of one frame (no list of layers) is that layer: its
            # columns are the frame's.
            columns = layer.get("columns") if layer else found.get("columns") if layers is None else None
            if "column" in parsed and isinstance(columns, list) and parsed["column"] not in columns:
                return f"{reference}: layer {parsed['layer']} of input {slot} has no column {parsed['column']}."
            if "column" not in parsed and language != "json" and context[0] != "code":
                return f"{reference} is an input, not text. Use it outside quotes and comments."
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


#: Kept in sync with ``CHOICE_KINDS``, ``NUMERIC_KINDS`` and
#: ``FILE_WIDGET_MAX_CHARS`` in ``widgetModel.ts``.
CHOICE_KINDS = ("choice", "checkbox-group", "multi-select")
NUMERIC_KINDS = ("number", "slider")
FILE_WIDGET_MAX_CHARS = 1_000_000

_DATETIME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?")


def normalize_datetime(text: str) -> str | None:
    """*text* as a date-time widget's value, ``YYYY-MM-DDTHH:mm:ss``, or None
    when it is not a real date and time; ``normalizeDateTime`` in
    ``widgetModel.ts``, whose ``Date.UTC`` reads a year below 100 as 19xx."""
    import datetime as _dt

    m = _DATETIME_RE.fullmatch(text) if isinstance(text, str) else None
    if not m:
        return None
    seconds = m.group(6) or "00"
    y, mo, d, h, mi, s = (int(v) for v in (m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), seconds))
    if y < 100:
        return None
    try:
        _dt.datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{seconds}"


def _bounds_problem(value, options: dict) -> str | None:
    low = options.get("min") if _finite(options.get("min")) else None
    high = options.get("max") if _finite(options.get("max")) else None
    if low is not None and high is not None and (value < low or value > high):
        return f"Enter a number from {js_number(low)} to {js_number(high)}."
    if low is not None and value < low:
        return f"Enter a number of at least {js_number(low)}."
    if high is not None and value > high:
        return f"Enter a number of at most {js_number(high)}."
    return None


def check_widget_value(widget: dict, value) -> str | None:
    """What is wrong with *value* for *widget*, or None when it is fine:
    ``checkWidgetValue`` in ``widgetModel.ts``, what the Widgets tab checks a
    value with. Both read ``widgetChecks.cases.json`` beside it."""
    kind = widget.get("type")
    options = widget.get("options") if isinstance(widget.get("options"), dict) else {}
    choices = options.get("choices") if isinstance(options.get("choices"), list) else []
    if kind in NUMERIC_KINDS:
        return _bounds_problem(value, options) if _finite(value) else "Enter a number."
    if kind == "text":
        return None if isinstance(value, str) else "Enter a text."
    if kind == "file":
        if not isinstance(value, str):
            return "Choose a text file."
        if len(value) > FILE_WIDGET_MAX_CHARS:
            return (f"The file is longer than {FILE_WIDGET_MAX_CHARS:,} characters. "
                    "Add it to the Data Catalog instead.")
        return None
    if kind == "checkbox":
        return None if isinstance(value, bool) else "Choose true or false."
    if kind == "choice":
        return None if isinstance(value, str) and value in choices else "Pick one of the choices."
    if kind in ("checkbox-group", "multi-select"):
        fine = (
            isinstance(value, list)
            and all(isinstance(v, str) and v in choices for v in value)
            and len(set(value)) == len(value)
        )
        return None if fine else "Pick among the choices, each at most once."
    if kind == "datetime":
        return None if isinstance(value, str) and normalize_datetime(value) == value else "Enter a date and time."
    if kind == "location":
        fine = (
            isinstance(value, dict) and len(value) == 2
            and _finite(value.get("lat")) and _finite(value.get("lon"))
            and abs(value["lat"]) <= 90 and abs(value["lon"]) <= 180
        )
        return None if fine else "Enter a latitude from -90 to 90 and a longitude from -180 to 180."
    if kind == "number-list":
        fine = isinstance(value, list) and all(_finite(v) for v in value)
        return None if fine else "Enter a list of numbers, such as [1, 2.5]."
    if kind == "text-list":
        fine = isinstance(value, list) and all(isinstance(v, str) for v in value)
        return None if fine else 'Enter a list of texts, such as ["a", "b"].'
    if kind == "range":
        fine = (
            isinstance(value, list) and len(value) == 2
            and _finite(value[0]) and _finite(value[1]) and value[0] <= value[1]
        )
        return None if fine else "Enter two numbers, the first not larger than the second."
    return "Unknown widget type."


def check_widget_def(definition: dict, others=(), parameter: bool = False) -> str | None:
    """What is wrong with a widget being added, or None: ``checkWidgetDef`` in
    ``widgetModel.ts``, what the Widgets tab checks a widget with. *others*
    are the node's other widgets, whose names it must not reuse; for a
    Parameter node's widget (*parameter*), the other Parameter nodes'."""
    name = definition.get("name")
    if not isinstance(name, str) or not WIDGET_NAME_RE.match(name):
        return "A name is letters, digits and underscores, and does not start with a digit."
    if any(isinstance(w, dict) and w.get("name") == name for w in others):
        return f"Another Parameter node is named {name}." if parameter else f"This node already has a widget named {name}."
    kind = definition.get("type")
    if kind not in WIDGET_KINDS:
        return "Pick a widget type."
    options = definition.get("options") if isinstance(definition.get("options"), dict) else {}
    if kind in CHOICE_KINDS:
        choices = options.get("choices") if isinstance(options.get("choices"), list) else []
        if not choices:
            return "Give at least one choice."
        if len(set(choices)) != len(choices):
            return "Each choice can appear only once."
    if kind in NUMERIC_KINDS:
        low, high, step = options.get("min"), options.get("max"), options.get("step")
        if kind == "slider" and (low is None or high is None):
            return "A slider needs a minimum and a maximum."
        if low is not None and high is not None and not low < high:
            return "The minimum must be below the maximum."
        if step is not None and not step > 0:
            return "The step must be above 0."
    return check_widget_value(definition, definition.get("default"))


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


def normalize_selections(raw) -> list:
    """The well-formed selection tags in *raw* (a spec's
    ``metadata.selections``), one per name: ``{name, node, column, ids}``, or
    ``count`` in place of ``ids``. Kept in sync with ``normalizeSelections`` in
    ``selectionTags.ts``."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not WIDGET_NAME_RE.match(name) or name in seen:
            continue
        if not isinstance(entry.get("node"), str) or not entry["node"]:
            continue
        if not isinstance(entry.get("column"), str) or not entry["column"]:
            continue
        tag = {"name": name, "node": entry["node"], "column": entry["column"]}
        count = entry.get("count")
        if isinstance(entry.get("ids"), list):
            tag["ids"] = list(entry["ids"])
        elif _finite(count) and count >= 0 and count == int(count):
            # A whole number, as JavaScript's Number.isInteger takes it.
            tag["count"] = int(count)
        else:
            continue
        seen.add(name)
        out.append(tag)
    return out


def _resolved_text(
    inner: str,
    by_name: dict,
    inputs: list,
    context: tuple,
    language: str,
    shared_by_name: dict,
    selections_by_name: dict,
) -> str:
    parsed = parse_reference(inner)
    if parsed["kind"] in ("shared", "selection"):
        if parsed["kind"] == "shared":
            value = effective_value(shared_by_name[parsed["name"]])
        else:
            value = selections_by_name[parsed["name"]]["ids"]
        if context[0] == "code":
            return widget_literal(value, language)
        return _escape_for(_text_of(value, language), context, language)
    if parsed["kind"] == "input":
        if "column" in parsed:
            return _write_text(parsed["column"], context, language)
        if "layer" in parsed and language == "json":
            return _write_text(parsed["layer"], context, language)
        index = next(i for i, entry in enumerate(inputs) if entry.get("slot") == parsed["slot"])
        if language == "json":
            return _write_text(f"{INPUT_TABLE_PREFIX}{index}", context, language)
        value = "arg" if len(inputs) == 1 else f"arg[{index}]"
        if "layer" in parsed:
            return f"{LAYER_HELPER}({value}, {widget_literal(parsed['layer'], language)}, {parsed['slot']})"
        return value
    value = effective_value(by_name[inner])
    if context[0] == "code":
        return widget_literal(value, language)
    return _escape_for(_text_of(value, language), context, language)


def resolve_references(
    code: str,
    widgets: Iterable = (),
    language: str = "python",
    inputs: Iterable = (),
    shared: Iterable = (),
    selections: Iterable = (),
) -> tuple[str, list]:
    """*code* with every reference replaced, and the problems found.

    *inputs* are the node's wired inputs, ``{"slot": <circle>, "columns"?: [...],
    "layers"?: [{"name", "columns"?}, ...]}`` each. *shared* are the widgets of the dataflow's Parameter nodes, one per
    node. *selections* are the node's selection tags (``metadata.selections``).
    A reference with a problem is left as written; each problem is
    ``{"reference": <as written>, "message": <why>}``.
    """
    if language not in LANGUAGES:
        raise ValueError(f"unknown code language {language!r}")
    widgets = normalize_widgets(list(widgets or []))
    shared = normalize_shared(list(shared or []))
    selections = normalize_selections(list(selections or []))
    inputs = sorted((dict(i) for i in inputs or ()), key=lambda i: i.get("slot", 0))
    refs = list(REFERENCE_RE.finditer(code))
    if not refs:
        return code, []
    contexts = _contexts(code, refs, language)
    by_name = {w["name"]: w for w in widgets}
    shared_by_name = {w["name"]: w for w in shared}
    selections_by_name = {t["name"]: t for t in selections}
    problems: list = []
    out: list = []
    last = 0
    for ref, context in zip(refs, contexts):
        out.append(code[last:ref.start()])
        written = ref.group(0)
        problem = reference_problem(
            written, ref.group(1), widgets, inputs, context, language, shared, selections
        )
        if problem is not None:
            problems.append({"reference": written, "message": problem})
            out.append(written)
        else:
            out.append(_resolved_text(
                ref.group(1), by_name, inputs, context, language, shared_by_name, selections_by_name
            ))
        last = ref.end()
    out.append(code[last:])
    return "".join(out), problems
