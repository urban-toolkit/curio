"""Turning a node's references into code (#662): ``[!! season !!]`` names a
widget, ``[!! input_1 !!]`` an input (by circle, counted from 0),
``[!! input_1.height !!]`` a column of that input, ``[!! input_1:roads !!]``
(or ``[!! input_1:roads.height !!]``) a layer an input carries, and
``[!! selection picked !!]`` one of the node's selection tags: the ids of the
rows a view's selection picks, which the node holds at
``metadata.selections``.

In a Vega-Lite or Autark spec, the scenario chips write the scenarios of the
node's inputs, from the label each input's rows carry (an input's
``scenario``: the box its feeding node is in, else that node's name):
``[!! scenario colors !!]`` the scale ``{"domain": [names], "range":
[colors]}``, each box once in the order the dataflow lists the boxes, in its
color, then each input from no box, in a grey of its own
(:data:`NO_SCENARIO_GREYS`); ``[!! scenario text_colors !!]`` the same scale in
the shades a text mark reads in (:func:`table_text_color`);
``[!! scenario order !!]`` the names alone; ``[!! scenario input_1 !!]`` the
color of input_1 in that scale. With no input from a box, the two scales are
the names alone, ``{"domain": [names]}``, which the grammar's own palette
colors. ``[!! inputs !!]`` names the dataset ``inputs``, which stacks a
Vega-Lite chart's inputs: a spec writes its name, as an Autark spec does too;
it is refused in code, and on a node with no input, which has nothing to
stack. ``[!! inputs.sunlight !!]`` names a field of that dataset. A widget's
name has no space and no dot, and an input's chip starts ``input_``, so
neither form can name a widget, an input or a column; and no widget takes the
name ``inputs`` (:data:`INPUT_NAME_ONLY_RE`), so beside one saved under it
``[!! inputs !!]`` names the dataset.

The headless twin of ``src/utils/references/codeReferences.ts``, which the
browser runs before posting a node's code. Both write the same code: one table
of cases, ``codeReferences.cases.json`` beside the TypeScript module, is read by
Jest and by ``tests/test_execution/test_code_references.py``.

A widget or selection reference standing on its own becomes a literal of the
language (a selection's ids are a list); inside a string literal it
becomes the value's text, escaped for that string;
inside a comment, the plain text. A column reference is written like a text
value: its name. In a Vega-Lite chart's spec, a reference where Vega-Lite reads
a field name (:func:`_vega_field_places`) writes each name it holds escaped for
Vega-Lite (:func:`vega_field_name`), since Vega-Lite reads a ``.`` or a ``[``
in a field as a path into the row: ``"field": [!! input_0.rain.mm !!]`` reads
``"field": "rain\\\\.mm"``. Anywhere else in it, a title, a sort or an
expression, the name is written as it is. In Python and JavaScript an input reference becomes the name
the code reads that circle's input by, ``input_<circle>`` (the sandbox binds one
variable per wired circle, ``util/input_names.py``), and a layer reference the
call that picks the layer out of it, ``curio_layer(input_1, "roads", 1)`` (the
sandbox's ``util/input_layers.py``, and ``js_wrapper.mjs``); in a Vega-Lite or Autark spec
an input reference is the name the input is read by, ``input_<i>``, and a layer
reference the layer's name, written like a text value. An input of one frame
with no layer name is that layer, whatever the reference names, in a spec as in
code: there its layer reference is ``input_<i>`` too. One frame whose value
names its layer is found by that name.
Numbers are written the way JavaScript's ``String()`` writes them, so a value
prints the same in both.

A chip spelled the old way, ``[!! input 1 !!]``, is refused with a message
naming its new spelling.
"""

from __future__ import annotations

import json
import math
import re
from typing import Iterable

#: A reference as written. Kept in sync with ``REFERENCE_PATTERN``.
REFERENCE_RE = re.compile(r"\[!!\s*(.*?)\s*!!\]")

#: What stands inside an input, layer or column reference: ``input_1``,
#: ``input_1.height``, ``input_1:roads``, ``input_1:roads.height``, or
#: ``input_?`` once its edge was deleted. Kept in sync with
#: ``INPUT_REFERENCE_PATTERN`` in ``codeReferences.ts``.
INPUT_REFERENCE_RE = re.compile(r"^input_(\d+|\?)(?::([^.]+))?(?:\.(.+))?$")

#: What stood inside an input reference before, ``input 1`` with a space,
#: refused naming its new spelling. Kept in sync with
#: ``LEGACY_INPUT_REFERENCE_PATTERN`` in ``codeReferences.ts`` and the
#: sandbox's ``util/input_names.py``.
LEGACY_INPUT_REFERENCE_RE = re.compile(r"^input\s+(\d+|\?)((?:[:.].*)?)$")

#: The dataset a Vega-Lite spec reads every input's rows stacked in, which
#: ``[!! inputs !!]`` names. Kept in sync with ``INPUTS_DATASET`` in
#: ``utils/vegaDatasets.ts`` and in ``agents/domain/document_validation.py``.
STACKED_DATASET = "inputs"

#: The names of a node's inputs and nothing else, which no widget takes
#: (:func:`widget_name_problem`): an input's, ``input_<k>``, and the stacked
#: inputs', :data:`STACKED_DATASET`. Kept in sync with
#: ``INPUT_NAME_ONLY_PATTERN`` in ``widgetModel.ts`` and with the widget
#: name's ``not`` in ``docs/schemas/node-package.v4.json``.
INPUT_NAME_ONLY_RE = re.compile(r"^(?:input_\d+|inputs)$")

#: What stands inside a selection reference, ``selection picked``. Kept in sync
#: with ``SELECTION_REFERENCE_PATTERN`` in ``codeReferences.ts``.
SELECTION_REFERENCE_RE = re.compile(r"^selection\s+(.+)$")

#: What stands inside a scenario chip: ``scenario colors``, ``scenario
#: text_colors``, ``scenario order``, or ``scenario input_1`` (``scenario
#: input_?`` once its edge was deleted). Kept in sync with
#: ``SCENARIO_REFERENCE_PATTERN`` in ``codeReferences.ts``.
SCENARIO_REFERENCE_RE = re.compile(r"^scenario\s+(.+)$")

#: The scenario chips that list every input's scenario: the scale of their
#: colors, the same scale in text shades, and their names in order. Kept in
#: sync with ``SCENARIO_LISTS`` in ``codeReferences.ts``.
SCENARIO_LISTS = ("colors", "text_colors", "order")

_SCENARIO_INPUT_RE = re.compile(r"^input_(\d+|\?)$")

#: What stands inside a chip of a field of the dataset ``inputs``:
#: ``inputs.sunlight``. Kept in sync with ``STACKED_REFERENCE_PATTERN`` in
#: ``codeReferences.ts``.
STACKED_REFERENCE_RE = re.compile(r"^inputs\.(.+)$")

#: The fields the stacking adds to every row of ``inputs``, before the inputs'
#: own columns (``scenario_stack.py``). Kept in sync with ``STACKED_FIELDS`` in
#: ``codeReferences.ts``.
STACKED_FIELDS = ("scenario_name", "scenario", "__input__")

#: The data types of a frame the stacking reads as a table. Kept in sync with
#: ``TABLE_TYPES`` in ``codeReferences.ts``.
TABLE_TYPES = ("dataframe", "geodataframe")

#: The color of an input whose node is in no scenario box. Kept in sync with
#: ``NO_SCENARIO_COLOR`` in ``utils/scenarios/scenarioColors.ts``.
NO_SCENARIO_COLOR = "#8a8f98"

#: The greys the scenario chips draw the inputs from no box in, one per name
#: in circle order, the first :data:`NO_SCENARIO_COLOR`: apart from each other,
#: and from the boxes, since a grey a box among the same inputs uses is passed
#: over. Kept in sync with ``NO_SCENARIO_GREYS`` in
#: ``utils/scenarios/scenarioColors.ts``.
NO_SCENARIO_GREYS = ("#8a8f98", "#5b6068", "#b6bac1", "#40444a", "#d2d5da", "#74797f")

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

#: The data types of an input that is one frame: a table, as ``curio_layer``
#: counts one. Kept in sync with ``ONE_FRAME_TYPES`` in ``codeReferences.ts``.
ONE_FRAME_TYPES = ("dataframe", "geodataframe")

#: The grammar of a Vega-Lite chart's spec, as a template names it
#: (``grammarId``): a JSON document of it writes a name where Vega-Lite reads a
#: field escaped. Kept in sync with ``VEGA_LITE`` in ``codeReferences.ts``.
VEGA_LITE = "vega-lite"

_VEGA_FIELD_SPECIALS_RE = re.compile(r"[.\[\]]")


def vega_field_name(name: str) -> str:
    """*name* as a Vega-Lite field that names that column: each ``.``, ``[``
    and ``]`` behind a backslash, which Vega-Lite would otherwise read as a
    path into the row. A name that already holds a backslash is taken as
    escaped by hand and kept as it is: Vega-Lite reads no column whose name
    holds one anyway. Kept in sync with ``vegaFieldName`` in
    ``utils/vegaFieldNames.ts``."""
    if "\\" in name:
        return name
    return _VEGA_FIELD_SPECIALS_RE.sub(lambda m: "\\" + m.group(0), name)


#: A widget name. Kept in sync with ``WIDGET_NAME_PATTERN`` in ``widgetModel.ts``
#: and with the widget name's ``pattern`` in ``docs/schemas/node-package.v4.json``
#: and ``docs/schemas/trill.v1.json``.
WIDGET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

LANGUAGES = ("python", "javascript", "json")

#: The widget kinds. Kept in sync with ``WIDGET_KINDS`` in ``widgetModel.ts``
#: and with the widget's ``type`` enum in ``docs/schemas/node-package.v4.json``
#: and ``docs/schemas/trill.v1.json``. A package manifest's template widgets
#: are checked against it too (:func:`widget_name_or_type_problem`).
WIDGET_KINDS = (
    "number",
    "slider",
    "text",
    "choice",
    "checkbox",
    "checkbox-group",
    "multi-select",
    "datetime",
    "date",
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


def _parse_scenario_chip(rest: str) -> dict:
    """What follows ``scenario `` in a scenario chip, as the chip it names;
    ``parseScenarioChip`` in ``codeReferences.ts``."""
    if rest in SCENARIO_LISTS:
        return {"kind": "scenario", "chip": rest}
    found = _SCENARIO_INPUT_RE.match(rest)
    if found:
        return {"kind": "scenario", "chip": "input", "slot": None if found.group(1) == "?" else int(found.group(1))}
    return {"kind": "scenario", "chip": None}


def parse_reference(inner: str) -> dict:
    """``{"kind": "widget", "name"}``, ``{"kind": "selection", "name"}``,
    ``{"kind": "input", "slot", "layer"?, "column"?}``,
    ``{"kind": "scenario", "chip", "slot"?}``,
    ``{"kind": "dataset"}`` (``[!! inputs !!]``) or ``{"kind": "stacked",
    "column"}``; ``slot`` is None for ``input_?`` (or ``scenario input_?``),
    the input whose edge was deleted, and a scenario ``chip`` None for a word
    no scenario chip is."""
    m = INPUT_REFERENCE_RE.match(inner)
    if not m:
        selection = SELECTION_REFERENCE_RE.match(inner)
        if selection:
            return {"kind": "selection", "name": selection.group(1)}
        scenario = SCENARIO_REFERENCE_RE.match(inner)
        if scenario:
            return _parse_scenario_chip(scenario.group(1))
        stacked = STACKED_REFERENCE_RE.match(inner)
        if stacked:
            return {"kind": "stacked", "column": stacked.group(1)}
        if inner == STACKED_DATASET:
            return {"kind": "dataset"}
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


def selection_names_in(code: object) -> list[str]:
    """The names of the selection tags *code* references, each once, in order.
    Kept in sync with ``selectionNamesIn`` in ``codeReferences.ts``."""
    return _names_of_kind_in(code, "selection")


def reference_text(inner: str) -> str:
    """The text of a reference to *inner*; ``referenceText`` in ``codeReferences.ts``."""
    return f"[!! {inner} !!]"


def references_as_names(code: object) -> str:
    """*code* with each reference written as the plain name ``input_0``, so
    code that reads its inputs, widgets or tags through references parses as
    Python. For a reader of what the code imports or defines, not of what its
    references hold: the package builder's import scan (#707)."""
    return REFERENCE_RE.sub("input_0", code if isinstance(code, str) else "")


def input_reference_inner(slot: int | None, column: str | None = None, layer: str | None = None) -> str:
    """What stands inside a reference to input *slot*, to one of its layers, or
    to a column of either; ``inputReferenceInner`` in ``codeReferences.ts``."""
    return (
        f"input_{'?' if slot is None else slot}"
        + (f":{layer}" if layer is not None else "")
        + (f".{column}" if column is not None else "")
    )


def selection_reference_inner(name: str) -> str:
    """What stands inside a reference to the selection tag *name*;
    ``selectionReferenceInner`` in ``codeReferences.ts``."""
    return f"selection {name}"


def stacked_reference_inner(column: str) -> str:
    """What stands inside a chip of the field *column* of the dataset
    ``inputs``; ``stackedReferenceInner`` in ``codeReferences.ts``."""
    return f"{STACKED_DATASET}.{column}"


def legacy_reference_message(reference: str, inner: str) -> str | None:
    """Why *reference* is refused when it names an input the old way,
    ``input 1`` with a space, naming its new spelling; else None. The
    sandbox's ``util/input_names.py`` and ``legacyReferenceMessage`` in
    ``codeReferences.ts`` say the same."""
    m = LEGACY_INPUT_REFERENCE_RE.match(inner)
    if not m:
        return None
    new = reference_text(f"input_{m.group(1)}{m.group(2)}")
    return (
        f"{reference} names an input the old way, which Curio no longer reads. "
        f"Write {new}: each input circle is its own variable, input_0, input_1, and so on."
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
    return f"{reference}: input_{slot} has no layer {layer}. {has}"


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


#: The transforms whose own key holds the field they read.
_TRANSFORM_FIELD_KEYS = frozenset({"pivot", "lookup", "impute", "stack", "density", "loess", "regression", "quantile"})
#: The lists of fields a transform reads.
_TRANSFORM_FIELD_LISTS = frozenset({"groupby", "fold", "flatten"})


def _is_vega_field(holder: dict, kind, key: str, item: bool) -> bool:
    """Whether Vega-Lite reads a text at *key* of *holder*, an object that is
    *kind* (``"transform"``, ``"lookup"``, ``"param"``, ``"select"``,
    ``"aggregate"``, ``"repeat"`` or None), as a field name; *item* for a text
    that is an item of a list there. Kept in sync with ``isVegaField`` in
    ``codeReferences.ts``, which says which keys and why."""
    if item:
        if kind == "transform":
            return key in _TRANSFORM_FIELD_LISTS
        if kind in ("lookup", "select"):
            return key == "fields"
        if kind == "repeat":
            return key in ("row", "column", "layer")
        return key == "repeat"
    if key == "field":
        return True
    if kind == "transform":
        if key in _TRANSFORM_FIELD_KEYS:
            return True
        if key == "extent":
            return "param" in holder
        if key == "value":
            return "pivot" in holder
        if key == "key":
            return "impute" in holder
        if key == "on":
            return "loess" in holder or "regression" in holder
        return False
    if kind == "lookup":
        return key == "key"
    if kind == "aggregate":
        return key in ("argmax", "argmin")
    return False


def _field_holder_at(holder: dict, kind, key: str, item: bool):
    """What the object at *key* of *holder*, an object that is *kind*, is;
    *item* for an object that is an item of a list there. Kept in sync with
    ``fieldHolderAt`` in ``codeReferences.ts``."""
    if item:
        if key == "transform":
            return "transform"
        if key == "params":
            return "param"
        return None
    if key == "from" and kind == "transform" and "lookup" in holder:
        return "lookup"
    if key == "select" and kind == "param":
        return "select"
    if key == "aggregate":
        return "aggregate"
    if key == "repeat":
        return "repeat"
    return None


#: The keys whose values hold rows or the author's own notes, never a field:
#: a ``field`` there is a value. Kept in sync with ``NOT_SPEC_KEYS`` in
#: ``codeReferences.ts``.
_NOT_SPEC_KEYS = frozenset({"data", "datasets", "usermeta"})

#: How deep a Vega-Lite spec's objects and lists may nest, its rows and notes
#: included, for its places to be read; a deeper spec writes its names as they
#: are. Kept in sync with ``MAX_SPEC_DEPTH`` in ``codeReferences.ts``.
_MAX_SPEC_DEPTH = 100

#: The first and last code points of Unicode's private use area.
_PRIVATE_USE_FIRST, _PRIVATE_USE_LAST = 0xE000, 0xF8FF


def _spec_depth(spec, limit: int) -> int:
    """How many objects and lists *spec* nests, itself counted as one,
    measured without recursion and no further than past *limit*. Kept in sync
    with ``specDepth`` in ``codeReferences.ts``."""
    deepest = 0
    stack = [(spec, 1)]
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, (dict, list)):
            continue
        deepest = max(deepest, depth)
        if deepest > limit:
            break
        for child in node if isinstance(node, list) else node.values():
            if isinstance(child, (dict, list)):
                stack.append((child, depth + 1))
    return deepest


def _place_marks(code: str) -> tuple[str, str] | None:
    """Two characters of Unicode's private use area that *code* holds neither
    as they are nor as a JSON escape, to stand around a reference's number
    while the spec is read for its places; None when it holds every pair. Kept
    in sync with ``placeMarks`` in ``codeReferences.ts``."""
    lower = code.lower()
    escape = chr(92) + "u"

    def free(point: int) -> bool:
        return chr(point) not in code and f"{escape}{point:04x}" not in lower

    for point in range(_PRIVATE_USE_FIRST, _PRIVATE_USE_LAST, 2):
        if free(point) and free(point + 1):
            return chr(point), chr(point + 1)
    return None


def _not_json(name: str):
    """What ``JSON.parse`` refuses and ``json.loads`` would read: ``NaN`` and
    the infinities."""
    raise ValueError(f"{name} is not JSON")


def _vega_field_places(code: str, refs: list, contexts: list) -> list:
    """Where each of *refs* (in *contexts*) stands in the Vega-Lite spec
    *code*: ``{"text": <whether Vega-Lite reads a text there as a field
    name>, "items": <whether, for a reference that is a whole value, it reads
    each text of a list there as one>}``. The spec is read as JSON, as
    ``JSON.parse`` reads it, with each reference replaced by a mark, its number
    between two characters the spec's text does not hold
    (:func:`_place_marks`), and each mark is found where the spec holds it,
    outside the rows and notes of :data:`_NOT_SPEC_KEYS`. A spec that does not
    read as JSON, or nests deeper than :data:`_MAX_SPEC_DEPTH`, holds no
    field. Kept in sync with ``vegaFieldPlaces`` in ``codeReferences.ts``."""

    def unplaced() -> list:
        return [{"text": False, "items": False} for _ in refs]

    marks = _place_marks(code)
    if marks is None:
        return unplaced()
    open_mark, close_mark = marks
    mark_re = re.compile(re.escape(open_mark) + "([0-9]+)" + re.escape(close_mark))
    marked: list = []
    last = 0
    for index, (ref, context) in enumerate(zip(refs, contexts)):
        mark = f"{open_mark}{index}{close_mark}"
        marked.append(code[last:ref.start()])
        marked.append(f'"{mark}"' if context[0] == "code" else mark)
        last = ref.end()
    marked.append(code[last:])
    try:
        spec = json.loads("".join(marked), parse_constant=_not_json)
    except (ValueError, RecursionError):
        return unplaced()
    if _spec_depth(spec, _MAX_SPEC_DEPTH) > _MAX_SPEC_DEPTH:
        return unplaced()
    places = unplaced()

    def place(text: str, field: bool, items: bool) -> None:
        for match in mark_re.finditer(text):
            index = int(match.group(1))
            if index >= len(places):
                continue
            places[index]["text"] = field
            # Only a reference that is the whole value can hold a list.
            places[index]["items"] = match.group(0) == text and items

    # The spec nests no deeper than _MAX_SPEC_DEPTH, so neither does this walk.
    def visit(node, kind) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, None)
            return
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key in _NOT_SPEC_KEYS:
                continue
            if isinstance(value, str):
                place(value, _is_vega_field(node, kind, key, False), _is_vega_field(node, kind, key, True))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        place(item, _is_vega_field(node, kind, key, True), False)
                    elif not isinstance(item, list):
                        visit(item, _field_holder_at(node, kind, key, True))
                    else:
                        visit(item, None)
            else:
                visit(value, _field_holder_at(node, kind, key, False))

    visit(spec, None)
    return places


def _field_value(value, place: dict):
    """*value*, a reference's value standing on its own at *place*, as it is
    written there: a text Vega-Lite reads as a field escaped, and each text of
    a list whose texts it reads as fields. ``fieldValue`` in
    ``codeReferences.ts``."""
    if isinstance(value, str):
        return vega_field_name(value) if place["text"] else value
    if isinstance(value, list) and place["items"]:
        return [vega_field_name(item) if isinstance(item, str) else item for item in value]
    return value


def _is_one_frame_input(found: dict) -> bool:
    """Whether the input *found* is one frame that lists no layers, which a
    layer reference reads whatever it names (#761). In code ``curio_layer``
    looks at the value when the node runs. A spec is written before the run,
    so the input's data type decides, which the input carries before any of
    its columns is read. Kept in sync with ``isOneFrameInput`` in
    ``codeReferences.ts``."""
    return not isinstance(found.get("layers"), list) and found.get("dataType") in ONE_FRAME_TYPES


def _known_layers(found: dict):
    """The layers the input *found* is known to carry, by name: the ones it
    lists, or the one frame its value names (``layerName``), with the input's
    columns; None when it names none. A layer reference must name one of them,
    as ``curio_layer`` requires. Kept in sync with ``knownLayers`` in
    ``codeReferences.ts``."""
    if isinstance(found.get("layers"), list):
        return found["layers"]
    name = found.get("layerName")
    if isinstance(name, str) and name:
        return [{"name": name, "columns": found.get("columns")}]
    return None


def _over_cap(tag: dict) -> bool:
    ids = tag.get("ids")
    return not isinstance(ids, list) or len(ids) > SELECTION_ID_CAP


def _selection_size(tag: dict) -> int:
    ids = tag.get("ids")
    return len(ids) if isinstance(ids, list) else int(tag.get("count") or 0)


def _stacked_columns_of(found: dict) -> list:
    """The input *found*'s columns as the rows of ``inputs`` carry them: a
    GeoDataFrame's geometry left out, as the stacking leaves it out."""
    dtypes = found.get("dtypes") if isinstance(found.get("dtypes"), dict) else {}
    return [c for c in found.get("columns") or [] if dtypes.get(c) != "geometry"]


def _known_stacked_fields(inputs: list):
    """Every field of the dataset ``inputs``, when every input is a table whose
    columns are known: the three the stacking adds, then each input's columns,
    once each, in circle order. None otherwise, and a field chip is not
    checked. Kept in sync with ``knownStackedFields`` in ``codeReferences.ts``."""
    known = all(
        i.get("dataType") in TABLE_TYPES and isinstance(i.get("columns"), list) and not isinstance(i.get("layers"), list)
        for i in inputs
    )
    if not known:
        return None
    fields = list(STACKED_FIELDS)
    for found in inputs:
        for column in _stacked_columns_of(found):
            if column not in fields:
                fields.append(column)
    return fields


def _contrast_on_white(channels: list) -> float:
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    return 1.05 / (0.2126 * r + 0.7152 * g + 0.0722 * b + 0.05)


def table_text_color(color: str) -> str:
    """*color* as a table's text draws it: itself when it reads on white, at
    WCAG's 3:1 for large text, else its lightest shade that does, taking one
    percent toward black at a time. The ``[!! scenario text_colors !!]`` chip
    writes these. Kept in sync with ``tableTextColor`` in
    ``utils/scenarios/scenarioColors.ts``, whose ``Math.round`` rounds a half
    up."""
    from utk_curio.backend.app.projects.scenarios import COLOR_RE

    if not isinstance(color, str) or not COLOR_RE.match(color):
        return color
    channels = [int(color[at:at + 2], 16) for at in (1, 3, 5)]
    for left in range(100, 0, -1):
        shade = [math.floor(c * left / 100 + 0.5) for c in channels]
        if _contrast_on_white(shade) < 3:
            continue
        return color if left == 100 else "#" + "".join(f"{c:02x}" for c in shade)
    return "#000000"


def scale_labels(labels: list) -> list:
    """The labels the scenario chips list, from *labels*, each wired input's in
    circle order: each box once, in the order the dataflow lists the boxes (its
    ``rank``), then each input from no box, in circle order. Kept in sync with
    ``scaleLabels`` in ``utils/scenarios/scenarioColors.ts``."""
    def rank(label: dict) -> float:
        value = label.get("rank")
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else float("inf")

    boxes: dict = {}
    for label in labels:
        if label.get("scenario") is not None and label["scenario"] not in boxes:
            boxes[label["scenario"]] = label
    return sorted(boxes.values(), key=rank) + [label for label in labels if label.get("scenario") is None]


def scenario_scale(labels: list) -> tuple[list, list]:
    """The scenarios' names and colors, each name once, in the order of
    *labels* (:func:`scale_labels`): a box's name in its box's color, and each
    input from no box in a grey of its own, in that order
    (:data:`NO_SCENARIO_GREYS`, past any a box here uses). Kept in sync with
    ``scenarioScale`` in ``utils/scenarios/scenarioColors.ts``."""
    box_colors = {str(label.get("color", "")).lower() for label in labels if label.get("scenario") is not None}
    greys = [grey for grey in NO_SCENARIO_GREYS if grey not in box_colors] or [NO_SCENARIO_COLOR]
    domain: list = []
    colors: list = []
    given = 0
    for label in labels:
        if label["name"] in domain:
            continue
        domain.append(label["name"])
        if label.get("scenario") is not None:
            colors.append(label["color"])
        else:
            colors.append(greys[given % len(greys)])
            given += 1
    return domain, colors


def _scenario_value(parsed: dict, inputs: list):
    """What the scenario chip *parsed* (one that resolves) writes over
    *inputs*: an input's color (its box's, else its grey in the scale), the
    names in order, or a scale. With no input from a box the scale is the names
    alone, so the grammar's own palette colors them. Kept in sync with
    ``scenarioValue`` in ``codeReferences.ts``."""
    labels = [i["scenario"] for i in inputs]
    domain, colors = scenario_scale(scale_labels(labels))
    if parsed["chip"] == "input":
        label = next(i for i in inputs if i.get("slot") == parsed["slot"])["scenario"]
        return label["color"] if label.get("scenario") is not None else colors[domain.index(label["name"])]
    if parsed["chip"] == "order":
        return domain
    if not any(label.get("scenario") is not None for label in labels):
        return {"domain": domain}
    return {"domain": domain, "range": [table_text_color(c) for c in colors] if parsed["chip"] == "text_colors" else colors}


def _scenario_problem(reference: str, parsed: dict, inputs: list, context: tuple, language: str) -> str | None:
    """Why the scenario chip *reference* (*parsed*) cannot be written over
    *inputs*, standing in *context*, or None. Kept in sync with
    ``scenarioProblem`` in ``codeReferences.ts``."""
    if language != "json":
        return f"{reference} is for a Vega-Lite or Autark spec, not for code."
    chip = parsed["chip"]
    if chip is None:
        return (
            f"{reference} names no scenario chip. The scenario chips are scenario colors, scenario text_colors, "
            "scenario order and scenario input_<k>."
        )
    if chip == "input":
        slot = parsed["slot"]
        if slot is None:
            return f"{reference}: the edge for this input was deleted. Write scenario input_<k> for a circle that has one."
        found = next((i for i in inputs if i.get("slot") == slot), None)
        if found is None:
            return (
                f"{reference}: input_{slot} has no edge. Connect one to that circle, "
                "or write scenario input_<k> for a circle that has one."
            )
        if not isinstance(found.get("scenario"), dict):
            return f"{reference}: the scenario box input_{slot} comes from is not known here."
        return None
    if context[0] != "code":
        what = "a list of names" if chip == "order" else "a scale"
        return f"{reference} is {what}, not text. Use it outside quotes."
    unknown = next((i for i in inputs if not isinstance(i.get("scenario"), dict)), None)
    if unknown is not None:
        return f"{reference}: the scenario box input_{unknown.get('slot')} comes from is not known here."
    return None


def _dataset_problem(reference: str, inputs: list, language: str) -> str | None:
    """Why the chip of the dataset ``inputs``, *reference*, cannot be written
    over *inputs*, or None: it is for a spec, never for code, and a node with
    no input has nothing to stack. Kept in sync with ``datasetProblem`` in
    ``codeReferences.ts``."""
    if language != "json":
        return f"{reference} is for a Vega-Lite spec, not for code."
    if not inputs:
        return f"{reference}: this node has no input to stack. Connect one to an input circle."
    return None


def reference_problem(
    reference: str,
    inner: str,
    widgets: list,
    inputs: list,
    context: tuple,
    language: str,
    selections: list = (),
) -> str | None:
    """Why *reference* cannot be resolved against *widgets*, *inputs* and the
    node's *selections*, standing in *context*, or None."""
    legacy = legacy_reference_message(reference, inner)
    if legacy:
        return legacy
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
    if parsed["kind"] == "scenario":
        return _scenario_problem(reference, parsed, inputs, context, language)
    if parsed["kind"] == "dataset":
        return _dataset_problem(reference, inputs, language)
    if parsed["kind"] == "stacked":
        if language != "json":
            return f"{reference} is for a Vega-Lite spec, not for code."
        fields = _known_stacked_fields(inputs)
        if fields is not None and parsed["column"] not in fields:
            return f"{reference}: the dataset inputs has no field {parsed['column']}."
        return None
    if parsed["kind"] == "input":
        slot = parsed["slot"]
        if slot is None:
            return f"{reference}: the edge for this input was deleted. Drag one of this node's input chips here."
        found = next((i for i in inputs if i.get("slot") == slot), None)
        if found is None:
            return (
                f"{reference}: input_{slot} has no edge. Connect one to that circle, "
                "or drag one of this node's input chips here."
            )
        if "layer" in parsed:
            layers = _known_layers(found)
            layer = next((l for l in layers or [] if l.get("name") == parsed["layer"]), None)
            if layers is not None and layer is None:
                return missing_layer_message(reference, slot, parsed["layer"], (str(l.get("name")) for l in layers))
            # An input of one frame (no list of layers) is that layer: its
            # columns are the frame's.
            columns = layer.get("columns") if layer else found.get("columns") if layers is None else None
            if "column" in parsed and isinstance(columns, list) and parsed["column"] not in columns:
                return f"{reference}: layer {parsed['layer']} of input_{slot} has no column {parsed['column']}."
            if "column" not in parsed and language != "json" and context[0] != "code":
                return f"{reference} is an input, not text. Use it outside quotes and comments."
            return None
        if "column" not in parsed:
            if language == "json":
                layers = found.get("layers")
                if isinstance(layers, list) and len(layers) > 1:
                    names = ", ".join(str(l.get("name")) for l in layers)
                    return (
                        f"{reference}: input_{slot} carries several layers ({names}). "
                        "Drag one of its layer chips here."
                    )
                return None
            if context[0] != "code":
                return f"{reference} is an input, not text. Use it outside quotes and comments."
            return None
        columns = found.get("columns")
        if isinstance(columns, list) and parsed["column"] not in columns:
            return f"{reference}: input_{slot} has no column {parsed['column']}."
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
#: A date widget's value when its widget gives none. Kept in sync with
#: ``DATE_FALLBACK`` in ``widgetModel.ts``.
DATE_FALLBACK = "1970-01-01"


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def _choices(options: dict) -> list:
    """A widget's choices as the canvas reads them (``normalizeOptions`` in
    ``widgetModel.ts``): the texts of a list."""
    choices = options.get("choices")
    return [c for c in choices if isinstance(c, str)] if isinstance(choices, list) else []


def _number_option(options: dict, key: str):
    """A widget's ``min``, ``max`` or ``step`` as the canvas reads it
    (``normalizeOptions``): a finite number, else None."""
    value = options.get(key)
    return value if _finite(value) else None


def default_value_for(kind, options) -> object:
    """A kind's value when a widget gives no default, as ``defaultValueFor`` in
    ``widgetModel.ts`` writes it."""
    options = options if isinstance(options, dict) else {}
    if kind in ("number", "slider"):
        low = _number_option(options, "min")
        return 0 if low is None else low
    if kind == "checkbox":
        return False
    if kind == "choice":
        choices = _choices(options)
        return choices[0] if choices else ""
    if kind in ("checkbox-group", "multi-select", "number-list", "text-list"):
        return []
    if kind == "range":
        return [0, 1]
    if kind == "datetime":
        return DATETIME_FALLBACK
    if kind == "date":
        return DATE_FALLBACK
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


_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def normalize_date(text: str) -> str | None:
    """*text* as a date widget's value, ``YYYY-MM-DD``, or None when it is not
    a real date; ``normalizeDate`` in ``widgetModel.ts``, whose ``Date.UTC``
    reads a year below 100 as 19xx."""
    import datetime as _dt

    m = _DATE_RE.fullmatch(text) if isinstance(text, str) else None
    if not m:
        return None
    y, mo, d = (int(v) for v in m.groups())
    if y < 100:
        return None
    try:
        _dt.date(y, mo, d)
    except ValueError:
        return None
    return text


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
    if kind == "date":
        return None if isinstance(value, str) and normalize_date(value) == value else "Enter a date."
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


def widget_name_problem(name: object) -> str | None:
    """Why a widget may not be named *name*, or None. A name has the shape of
    :data:`WIDGET_NAME_RE`, matched whole: the browser and the schemas read the
    pattern as ECMA-262 does, where ``$`` ends the text, while Python's
    ``re.match`` lets a final line break through. And ``input_<k>`` names one
    of the node's inputs, in its code as in its chips, and ``inputs`` the
    dataset they are stacked in (:data:`STACKED_DATASET`). The Widgets tab
    refuses such a name (:func:`check_widget_def`), and so does a package
    manifest for a template's widgets (``packages/repositories/manifests.py``)."""
    if not isinstance(name, str) or not WIDGET_NAME_RE.fullmatch(name):
        return "A name is letters, digits and underscores, and does not start with a digit."
    if name == STACKED_DATASET:
        return f"{name} names the node's stacked inputs. Pick another name."
    if INPUT_NAME_ONLY_RE.match(name):
        return f"{name} names one of the node's inputs. Pick another name."
    return None


def widget_name_or_type_problem(definition: dict, others=()) -> str | None:
    """What the Widgets tab refuses in a widget before it reads its options
    and its default, or None: a name :func:`widget_name_problem` refuses, a
    name one of *others* has, or a type outside :data:`WIDGET_KINDS`. The
    canvas drops such a widget (``normalizeWidgets``), unless it only has a
    name of the node's inputs, ``input_<k>`` or ``inputs``, which it keeps so
    it can be deleted. :func:`check_widget_def` checks these first."""
    name = definition.get("name")
    if problem := widget_name_problem(name):
        return problem
    if any(isinstance(w, dict) and w.get("name") == name for w in others):
        return f"This node already has a widget named {name}."
    if definition.get("type") not in WIDGET_KINDS:
        return "Pick a widget type."
    return None


def check_widget_def(definition: dict, others=()) -> str | None:
    """What is wrong with a widget being added, or None: ``checkWidgetDef`` in
    ``widgetModel.ts``, what the Widgets tab checks a widget with. *others*
    are the node's other widgets, whose names it must not reuse. Its
    options are read as the canvas reads them before the tab checks them
    (:func:`_choices`, :func:`_number_option`), so a malformed option counts
    as missing. A package manifest's template widgets are checked here too,
    each with its kind's default when it gives none
    (:func:`widget_with_default`, ``packages/repositories/manifests.py``)."""
    if problem := widget_name_or_type_problem(definition, others):
        return problem
    kind = definition.get("type")
    options = definition.get("options") if isinstance(definition.get("options"), dict) else {}
    if kind in CHOICE_KINDS:
        choices = _choices(options)
        if not choices:
            return "Give at least one choice."
        if len(set(choices)) != len(choices):
            return "Each choice can appear only once."
    if kind in NUMERIC_KINDS:
        low, high, step = (_number_option(options, key) for key in ("min", "max", "step"))
        if kind == "slider" and (low is None or high is None):
            return "A slider needs a minimum and a maximum."
        if low is not None and high is not None and not low < high:
            return "The minimum must be below the maximum."
        if step is not None and not step > 0:
            return "The step must be above 0."
    return check_widget_value(definition, definition.get("default"))


def widget_with_default(widget: dict) -> dict:
    """*widget* with its kind's default (:func:`default_value_for`) when it
    gives none, or ``null``, as ``normalizeWidgets`` in ``widgetModel.ts``
    gives it one. A dataflow's widgets (:func:`normalize_widgets`), an
    agent's (``agents/domain/widget_grammar.py``) and a package template's
    (``packages/repositories/manifests.py``) get theirs here."""
    if widget.get("default") is None:
        return {**widget, "default": default_value_for(widget.get("type"), widget.get("options"))}
    return widget


def normalize_widgets(raw) -> list:
    """The well-formed widgets in *raw* (a spec's ``metadata.widgets``), as
    ``normalizeWidgets`` in ``widgetModel.ts`` keeps them: each name once, of
    the :data:`WIDGET_NAME_RE` shape matched whole, as the browser matches it.
    A widget without a default gets its kind's (:func:`widget_with_default`)."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not WIDGET_NAME_RE.fullmatch(name) or name in seen:
            continue
        if entry.get("type") not in WIDGET_KINDS:
            continue
        seen.add(name)
        out.append(widget_with_default(entry))
    return out


def normalize_selections(raw) -> list:
    """The well-formed selection tags in *raw* (a spec's
    ``metadata.selections``), one per name, of the :data:`WIDGET_NAME_RE`
    shape matched whole, as the browser matches it: ``{name, node, column,
    ids}``, or ``count`` in place of ``ids``. Kept in sync with
    ``normalizeSelections`` in ``selectionTags.ts``."""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not WIDGET_NAME_RE.fullmatch(name) or name in seen:
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
    selections_by_name: dict,
    place: dict | None = None,
) -> str:
    def named(name: str) -> str:
        return vega_field_name(name) if place and place["text"] else name

    parsed = parse_reference(inner)
    if parsed["kind"] == "stacked":
        # A field of inputs is written as a column is: its name.
        return _write_text(named(parsed["column"]), context, language)
    if parsed["kind"] == "dataset":
        # The dataset itself is its name too, which no place reads as a field.
        return _write_text(STACKED_DATASET, context, language)
    if parsed["kind"] in ("selection", "scenario"):
        if parsed["kind"] == "selection":
            value = selections_by_name[parsed["name"]]["ids"]
        else:
            value = _scenario_value(parsed, inputs)
        if context[0] == "code":
            return widget_literal(_field_value(value, place) if place else value, language)
        return _escape_for(named(_text_of(value, language)), context, language)
    if parsed["kind"] == "input":
        if "column" in parsed:
            return _write_text(named(parsed["column"]), context, language)
        index = next(i for i, entry in enumerate(inputs) if entry.get("slot") == parsed["slot"])
        if language == "json":
            # A spec reads a layer by its name, and an input, or the one frame
            # it carries, by the name the input is read by.
            layer = None if _is_one_frame_input(inputs[index]) else parsed.get("layer")
            return _write_text(
                named(layer if layer is not None else f"{INPUT_TABLE_PREFIX}{index}"), context, language
            )
        value = f"input_{parsed['slot']}"
        if "layer" in parsed:
            return f"{LAYER_HELPER}({value}, {widget_literal(parsed['layer'], language)}, {parsed['slot']})"
        return value
    value = effective_value(by_name[inner])
    if context[0] == "code":
        return widget_literal(_field_value(value, place) if place else value, language)
    return _escape_for(named(_text_of(value, language)), context, language)


def with_chip_placeholders(code: str) -> str:
    """*code*, a JSON document, with each chip that stands outside a string
    held by a string of its own text, so a reader that wants only the
    document's shape (what an Autark document declares,
    ``execution/autk_spec_kind.py``, ``projects/dashboard_payload.py``) can
    parse it before its chips are resolved: ``"color": [!! scenario input_1 !!]``
    or ``"scale": [!! scenario colors !!]`` is no JSON until then. A chip inside
    a string is JSON already and is left as written. Kept in sync with
    ``withChipPlaceholders`` in ``codeReferences.ts``."""
    if not isinstance(code, str):
        return code
    refs = list(REFERENCE_RE.finditer(code))
    if not refs:
        return code
    out: list = []
    last = 0
    for ref, context in zip(refs, _contexts(code, refs, "json")):
        if context[0] == "string":
            continue
        out.append(code[last:ref.start()])
        out.append(json.dumps(ref.group(0), ensure_ascii=False))
        last = ref.end()
    out.append(code[last:])
    return "".join(out)


#: The chips :func:`with_stand_in_chips` writes as a value of their shape.
_STAND_IN_KINDS = ("scenario", "dataset", "stacked")


def with_stand_in_chips(code: str) -> tuple[str, list]:
    """*code*, a JSON document, with each scenario chip, the dataset
    ``inputs`` and each field of it written as a value of its shape, for a
    check that has no dataflow to say what they write: every input a chip
    names comes from no box, named ``input_<k>``, the dataset stacks at least
    one input (``input_0`` when no chip names one), and the dataset and a
    field are their names; and the refusal of each such chip that cannot stand
    there, in its own words (a scale inside quotes, a chip no scenario chip is
    called). Every other reference is kept as written. The agents' document
    check reads a document through it (``agents/domain/document_validation.py``):
    it reports a refusal as it is, rather than the schema's reading of the chip
    left as text, and checks the rest of the document."""
    refs = list(REFERENCE_RE.finditer(code if isinstance(code, str) else ""))
    parsed = [parse_reference(ref.group(1)) for ref in refs]
    if not any(p["kind"] in _STAND_IN_KINDS for p in parsed):
        return code, []
    slots = sorted({p["slot"] for p in parsed if p["kind"] in ("scenario", "input") and isinstance(p.get("slot"), int)})
    if not slots and any(p["kind"] == "dataset" for p in parsed):
        slots = [0]
    inputs = [{"slot": slot, "scenario": {"name": f"input_{slot}", "color": NO_SCENARIO_COLOR}} for slot in slots]
    out: list = []
    refusals: list = []
    last = 0
    for ref, kind, context in zip(refs, parsed, _contexts(code, refs, "json")):
        out.append(code[last:ref.start()])
        written = ref.group(0)
        problem = (
            reference_problem(written, ref.group(1), [], inputs, context, "json")
            if kind["kind"] in _STAND_IN_KINDS else None
        )
        if problem is not None:
            refusals.append(problem)
        stands_in = kind["kind"] in _STAND_IN_KINDS and problem is None
        out.append(_resolved_text(ref.group(1), {}, inputs, context, "json", {}) if stands_in else written)
        last = ref.end()
    out.append(code[last:])
    return "".join(out), refusals


def resolve_references(
    code: str,
    widgets: Iterable = (),
    language: str = "python",
    inputs: Iterable = (),
    selections: Iterable = (),
    grammar: str | None = None,
) -> tuple[str, list]:
    """*code* with every reference replaced, and the problems found.

    *inputs* are the node's wired inputs, ``{"slot": <circle>, "dataType"?,
    "layerName"?, "columns"?: [...], "dtypes"?: {...}, "layers"?: [{"name",
    "columns"?}, ...], "scenario"?: {"scenario"?, "name", "color", "rank"?}}``
    each, ``scenario`` the label its rows carry, which the scenario chips write
    (``WorkflowSpec.input_scenarios``). *selections* are the node's selection
    tags (``metadata.selections``).
    *grammar* is the grammar of a JSON document: in a Vega-Lite spec
    (:data:`VEGA_LITE`), a reference where Vega-Lite reads a field name writes
    each name escaped (:func:`vega_field_name`).
    A reference with a problem is left as written; each problem is
    ``{"reference": <as written>, "message": <why>}``.
    """
    if language not in LANGUAGES:
        raise ValueError(f"unknown code language {language!r}")
    widgets = normalize_widgets(list(widgets or []))
    selections = normalize_selections(list(selections or []))
    inputs = sorted((dict(i) for i in inputs or ()), key=lambda i: i.get("slot", 0))
    refs = list(REFERENCE_RE.finditer(code))
    if not refs:
        return code, []
    contexts = _contexts(code, refs, language)
    places = _vega_field_places(code, refs, contexts) if language == "json" and grammar == VEGA_LITE else None
    by_name = {w["name"]: w for w in widgets}
    selections_by_name = {t["name"]: t for t in selections}
    problems: list = []
    out: list = []
    last = 0
    for index, (ref, context) in enumerate(zip(refs, contexts)):
        out.append(code[last:ref.start()])
        written = ref.group(0)
        problem = reference_problem(
            written, ref.group(1), widgets, inputs, context, language, selections=selections,
        )
        if problem is not None:
            problems.append({"reference": written, "message": problem})
            out.append(written)
        else:
            out.append(_resolved_text(
                ref.group(1), by_name, inputs, context, language, selections_by_name,
                places[index] if places is not None else None,
            ))
        last = ref.end()
    out.append(code[last:])
    return "".join(out), problems
