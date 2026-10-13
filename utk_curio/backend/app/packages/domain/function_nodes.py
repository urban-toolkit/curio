"""New node from a Python function (SCOUT's Compute Catalog, the Curio way). Pure.

A package's modules (``python_modules.py``) are read from their source with
``ast``, never imported or run: each public top-level function, with its
parameters' names, kinds, defaults and annotations. Each parameter then gets
one use: a widget, a fixed value, one of the node's inputs, or its own
default. :func:`template_code` writes the template's code, which imports the
function and returns its call, with ``[!! name !!]`` for a widget and
``[!! input k !!]`` for an input, the references a node's code holds (#662).
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass

POSITIONAL_ONLY = "positional-only"
POSITIONAL = "positional-or-keyword"
KEYWORD_ONLY = "keyword-only"

#: What a parameter can be given.
WIDGET = "widget"
FIXED = "fixed"
INPUT = "input"
DEFAULT = "default"
USES = (WIDGET, FIXED, INPUT, DEFAULT)

#: A widget's name, as ``WIDGET_NAME_RE`` in ``execution/code_references.py``.
WIDGET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: At most this much of a docstring becomes the template's description.
MAX_DESCRIPTION = 600

#: What a suggested widget starts at when the parameter's default does not
#: fit it: the kind's own value (``default_value_for``).
_FALLBACK = {
    "checkbox": False, "number": 0, "text": "", "number-list": [], "text-list": [],
    "datetime": "1970-01-01T00:00:00",
}
_TYPING_PREFIXES = ("typing.", "typing_extensions.", "t.")
_SCALAR_KINDS = {
    "bool": ("checkbox", {}),
    "int": ("number", {"step": 1}),
    "float": ("number", {}),
    "str": ("text", {}),
    "datetime": ("datetime", {}),
    "datetime.datetime": ("datetime", {}),
}
_SEQUENCES = {"list", "List", "Sequence", "tuple", "Tuple", "Iterable", "Collection"}
_LIST_KINDS = {"text": "text-list", "number": "number-list"}


class FunctionSourceError(ValueError):
    """A module that does not parse, a function it does not define, one a node
    cannot call, or a parameter given nothing it can be called with."""


def _jsonable(value: object) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: str
    annotation: str | None = None
    has_default: bool = False
    #: The default as written in the source.
    default_text: str | None = None
    #: Its value, when it is a literal (``ast.literal_eval``).
    default: object = None
    literal_default: bool = False

    def to_json(self) -> dict:
        out: dict = {"name": self.name, "kind": self.kind, "annotation": self.annotation,
                     "hasDefault": self.has_default}
        if self.has_default:
            out["defaultText"] = self.default_text
            if self.literal_default and _jsonable(self.default):
                out["default"] = self.default
        return out


@dataclass(frozen=True)
class FunctionSignature:
    name: str
    parameters: tuple[Parameter, ...]
    doc: str = ""
    #: Why a node cannot call it, or None.
    problem: str | None = None

    def to_json(self) -> dict:
        return {"name": self.name, "doc": self.doc, "problem": self.problem,
                "parameters": [p.to_json() for p in self.parameters]}


def _parameter(arg: ast.arg, kind: str, default: ast.expr | None) -> Parameter:
    annotation = ast.unparse(arg.annotation) if arg.annotation is not None else None
    if default is None:
        return Parameter(arg.arg, kind, annotation)
    try:
        value, literal = ast.literal_eval(default), True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        value, literal = None, False
    return Parameter(arg.arg, kind, annotation, True, ast.unparse(default), value, literal)


def _doc(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""
    first = doc.strip().split("\n\n", 1)[0]
    return " ".join(first.split())[:MAX_DESCRIPTION]


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FunctionSignature:
    args = node.args
    problem = None
    if isinstance(node, ast.AsyncFunctionDef):
        problem = f"{node.name} is an async function; a node calls a plain function."
    elif args.vararg is not None:
        problem = (f"{node.name} takes *{args.vararg.arg}, any number of values; a node calls "
                   "a function whose parameters each have a name.")
    elif args.kwarg is not None:
        problem = (f"{node.name} takes **{args.kwarg.arg}, any named values; a node calls "
                   "a function whose parameters each have a name.")
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    params = [
        _parameter(arg, POSITIONAL_ONLY if i < len(args.posonlyargs) else POSITIONAL, default)
        for i, (arg, default) in enumerate(zip(positional, defaults))
    ]
    params += [_parameter(arg, KEYWORD_ONLY, d) for arg, d in zip(args.kwonlyargs, args.kw_defaults)]
    return FunctionSignature(node.name, tuple(params), _doc(node), problem)


def read_functions(source: str, module: str) -> list[FunctionSignature]:
    """The public top-level functions *source*, the module *module*, defines,
    in source order. Raises :class:`FunctionSourceError` when it does not parse."""
    try:
        tree = ast.parse(source, filename=f"{module}.py")
    except SyntaxError as exc:
        raise FunctionSourceError(f"{module} does not parse: line {exc.lineno}: {exc.msg}") from None
    except ValueError as exc:
        raise FunctionSourceError(f"{module} does not parse: {exc}") from None
    found: dict[str, FunctionSignature] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            found.pop(node.name, None)
            found[node.name] = _signature(node)  # a later definition replaces an earlier one
    return list(found.values())


def read_function(source: str, module: str, name: str) -> FunctionSignature:
    """The function *name* in *source*, one a node can call."""
    for signature in read_functions(source, module):
        if signature.name == name:
            if signature.problem:
                raise FunctionSourceError(signature.problem)
            return signature
    raise FunctionSourceError(f"{module} defines no public function named {name!r}.")


# ---------------------------------------------------------------------------
# The widget a parameter suggests
# ---------------------------------------------------------------------------

def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return f"{head}.{node.attr}" if head else None
    return None


def _typing_name(node: ast.expr) -> str | None:
    dotted = _dotted(node)
    if dotted is None:
        return None
    for prefix in _TYPING_PREFIXES:
        if dotted.startswith(prefix):
            return dotted[len(prefix):]
    return dotted


def _is_none(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value is None) or _dotted(node) == "None"


def _union(members: list[ast.expr]) -> tuple[str, dict] | None:
    kinds = [_kind_of(m) for m in members if not _is_none(m)]
    if len(kinds) == 1:
        return kinds[0]
    if kinds and all(k is not None and k[0] == "number" for k in kinds):
        return ("number", {})
    return None


def _union_members(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_members(node.left) + _union_members(node.right)
    return [node]


def _kind_of(node: ast.expr | None) -> tuple[str, dict] | None:
    """The widget kind and options an annotation asks for, or None."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):  # a forward reference
        try:
            return _kind_of(ast.parse(node.value, mode="eval").body)
        except SyntaxError:
            return None
    if isinstance(node, ast.BinOp):
        return _union(_union_members(node))
    if isinstance(node, ast.Subscript):
        base = _typing_name(node.value)
        args = list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if base == "Optional":
            return _union(args)
        if base == "Union":
            return _union(args)
        if base == "Literal":
            try:
                choices = [ast.literal_eval(a) for a in args]
            except ValueError:
                return None
            if choices and all(isinstance(c, str) for c in choices) and len(set(choices)) == len(choices):
                return ("choice", {"choices": choices})
            return None
        if base in _SEQUENCES and args:
            inner = _kind_of(args[0])
            list_kind = _LIST_KINDS.get(inner[0]) if inner else None
            return (list_kind, {}) if list_kind else None
        return None
    found = _SCALAR_KINDS.get(_typing_name(node) or "")
    return (found[0], dict(found[1])) if found else None


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _kind_of_value(value: object) -> tuple[str, dict] | None:
    """The widget kind and options a literal default asks for, or None."""
    if isinstance(value, bool):
        return ("checkbox", {})
    if isinstance(value, int):
        return ("number", {"step": 1})
    if isinstance(value, float):
        return ("number", {})
    if isinstance(value, str):
        return ("text", {})
    if isinstance(value, (list, tuple)) and value:
        if all(isinstance(v, str) for v in value):
            return ("text-list", {})
        if all(_number(v) for v in value):
            return ("number-list", {})
    return None


def _fitting_default(kind: str, options: dict, param: Parameter) -> object:
    value = param.default if param.literal_default else None
    if kind == "checkbox" and isinstance(value, bool):
        return value
    if kind == "number" and _number(value) and (options.get("step") != 1 or float(value).is_integer()):
        return value
    if kind == "text" and isinstance(value, str):
        return value
    if kind == "choice":
        return value if value in options["choices"] else options["choices"][0]
    if kind == "text-list" and isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return list(value)
    if kind == "number-list" and isinstance(value, (list, tuple)) and all(_number(v) for v in value):
        return list(value)
    return _FALLBACK[kind]


def widget_label(name: str) -> str:
    """``max_height`` reads ``Max height``."""
    words = name.strip("_").replace("_", " ").split()
    text = " ".join(words) or name
    return text[:1].upper() + text[1:]


def suggest_widget(param: Parameter) -> dict | None:
    """The widget *param* suggests, in a node's ``metadata.widgets`` shape, or
    None when nothing fits: an annotation names its kind (``bool``, ``int``,
    ``float``, ``str``, ``Literal[...]``, a list of texts or numbers,
    ``datetime``, each also inside ``Optional``), else an unannotated
    parameter's literal default does. Its default is the parameter's, when it
    fits."""
    if not WIDGET_NAME_RE.match(param.name):
        return None
    if param.annotation is not None:
        try:
            found = _kind_of(ast.parse(param.annotation, mode="eval").body)
        except SyntaxError:
            found = None
    else:
        found = _kind_of_value(param.default) if param.literal_default else None
    if found is None:
        return None
    kind, options = found
    widget = {"name": param.name, "type": kind, "label": widget_label(param.name),
              "default": _fitting_default(kind, options, param)}
    if options:
        widget["options"] = options
    return widget


def suggested_use(param: Parameter) -> str:
    """What the dialog starts a parameter at: its widget, else its default,
    else an input."""
    if suggest_widget(param) is not None:
        return WIDGET
    return DEFAULT if param.has_default else INPUT


# ---------------------------------------------------------------------------
# The template's code
# ---------------------------------------------------------------------------

def fixed_value_text(text: object, name: str) -> str:
    """A fixed value as Python writes it: *text* must be a literal."""
    if not isinstance(text, str) or not text.strip():
        raise FunctionSourceError(f"Give {name} a value, written as Python writes it (2, 'winter', [1, 2]).")
    try:
        value = ast.literal_eval(text.strip())
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        raise FunctionSourceError(
            f"The value of {name}, {text.strip()!r}, is not a Python literal (a number, a text "
            "in quotes, True, False, None, or a list, tuple or dict of those)."
        ) from None
    return repr(value)


def template_code(module: str, function: FunctionSignature, uses: dict[str, dict]) -> str:
    """The code of a template that calls *function* from *module*.

    *uses* maps each parameter's name to what it is given: ``{"use":
    "widget"}`` (a widget of the same name), ``{"use": "fixed", "value":
    <literal text>}``, ``{"use": "input", "slot": k}`` or ``{"use":
    "default"}``. Positional-only parameters are passed by position, the
    others by name.
    """
    # The node's code is the body of a function whose parameters are its
    # inputs, input_0, input_1, ...: a function of such a name would be hidden.
    callee = function.name if not re.match(r"^input_\d+$", function.name) else f"{function.name}_function"
    imported = function.name if callee == function.name else f"{function.name} as {callee}"
    arguments: list[str] = []
    skipped: list[Parameter] = []
    for param in function.parameters:
        use = uses.get(param.name) or {}
        how = use.get("use")
        if how == DEFAULT:
            if not param.has_default:
                raise FunctionSourceError(f"{param.name} has no default: give it a widget, a value or an input.")
            if param.kind == POSITIONAL_ONLY:
                skipped.append(param)
            continue
        if how == WIDGET:
            text = f"[!! {param.name} !!]"
        elif how == FIXED:
            text = fixed_value_text(use.get("value"), param.name)
        elif how == INPUT:
            text = f"[!! input_{int(use.get('slot', 0))} !!]"
        else:
            raise FunctionSourceError(f"Choose what {param.name} is given: a widget, a value, an input or its default.")
        if param.kind == POSITIONAL_ONLY:
            for earlier in skipped:
                if not earlier.literal_default:
                    raise FunctionSourceError(
                        f"{earlier.name} comes before {param.name}, which is passed by position: "
                        f"give {earlier.name} a value."
                    )
                arguments.append(earlier.default_text or "None")
            skipped = []
            arguments.append(text)
        else:
            arguments.append(f"{param.name}={text}")
    if len(arguments) <= 1:
        call = f"{callee}({''.join(arguments)})"
    else:
        call = f"{callee}(\n" + "".join(f"    {a},\n" for a in arguments) + ")"
    return f"from {module} import {imported}\n\nreturn {call}\n"


def template_description(module: str, function: FunctionSignature) -> str:
    """The template's description: the function's docstring, and where it comes from."""
    where = f"Calls {function.name} from {module}."
    return f"{function.doc} {where}" if function.doc else where
