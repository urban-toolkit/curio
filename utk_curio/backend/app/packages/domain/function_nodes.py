"""New node from a Python function (SCOUT's Compute Catalog, the Curio way). Pure.

A package's modules (``python_modules.py``) are read from their source with
``ast``, never imported or run: the functions each one offers, with their
parameters' names, kinds, defaults and annotations. A module offers the names
its ``__all__`` lists, when it has one (a function it defines, or one it
imports from another module of its package); else every public top-level
function (:func:`read_functions`). Each parameter then gets one use: a widget,
a fixed value, one of the node's inputs, or its own default.
:func:`template_code` writes the template's code, which imports the function
and returns its call, with ``[!! name !!]`` for a widget and ``[!! input_k
!!]`` for an input, the references a node's code holds (#662).
"""

from __future__ import annotations

import ast
import json
import math
import re
from dataclasses import dataclass, replace
from typing import Callable

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

#: How many imports a name ``__all__`` lists is followed through to the
#: function it names: ``deep_umbra/__init__.py``'s ``from .node_outputs import
#: accumulated_shadow`` is one.
MAX_REEXPORTS = 8

#: How a reader reaches another module of the same package, to follow an
#: import a name of ``__all__`` comes from: a dotted module name in, ``(its
#: source, whether it is a package's __init__.py)`` out, or None for a module
#: the package does not ship.
ModuleLookup = Callable[[str], "tuple[str, bool] | None"]

#: What a suggested widget starts at when the parameter's default does not
#: fit it: the kind's own value (``default_value_for``).
_FALLBACK = {
    "checkbox": False, "number": 0, "text": "", "number-list": [], "text-list": [],
    "datetime": "1970-01-01T00:00:00", "date": "1970-01-01",
}
_TYPING_PREFIXES = ("typing.", "typing_extensions.", "t.")
_SCALAR_KINDS = {
    "bool": ("checkbox", {}),
    "int": ("number", {"step": 1}),
    "float": ("number", {}),
    "str": ("text", {}),
    "datetime": ("datetime", {}),
    "datetime.datetime": ("datetime", {}),
    "date": ("date", {}),
    "datetime.date": ("date", {}),
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

    @property
    def call(self) -> str:
        """Its signature as Python writes one, without annotations:
        ``raster_calculate(operation, rasters, codes=None, absolute=False)``,
        with ``/`` after the positional-only parameters and ``*`` before the
        keyword-only ones."""
        parts: list[str] = []
        for index, param in enumerate(self.parameters):
            if param.kind == KEYWORD_ONLY and (index == 0 or self.parameters[index - 1].kind != KEYWORD_ONLY):
                parts.append("*")
            parts.append(f"{param.name}={param.default_text}" if param.has_default else param.name)
            following = self.parameters[index + 1].kind if index + 1 < len(self.parameters) else None
            if param.kind == POSITIONAL_ONLY and following != POSITIONAL_ONLY:
                parts.append("/")
        return f"{self.name}({', '.join(parts)})"

    @property
    def required_call(self) -> str:
        """A call node code can start from: its name and the parameters a call
        must give, each by its own name, a keyword-only one as ``name=name``:
        ``raster_calculate(operation, rasters)``."""
        parts = [
            f"{param.name}={param.name}" if param.kind == KEYWORD_ONLY else param.name
            for param in self.parameters
            if not param.has_default
        ]
        return f"{self.name}({', '.join(parts)})"


def _parameter(node_arg: ast.arg, kind: str, default: ast.expr | None) -> Parameter:
    annotation = ast.unparse(node_arg.annotation) if node_arg.annotation is not None else None
    if default is None:
        return Parameter(node_arg.arg, kind, annotation)
    try:
        value, literal = ast.literal_eval(default), True
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        value, literal = None, False
    return Parameter(node_arg.arg, kind, annotation, True, ast.unparse(default), value, literal)


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
        _parameter(node_arg, POSITIONAL_ONLY if i < len(args.posonlyargs) else POSITIONAL, default)
        for i, (node_arg, default) in enumerate(zip(positional, defaults))
    ]
    params += [_parameter(node_arg, KEYWORD_ONLY, d) for node_arg, d in zip(args.kwonlyargs, args.kw_defaults)]
    return FunctionSignature(node.name, tuple(params), _doc(node), problem)


def _parse(source: str, module: str) -> ast.Module:
    try:
        return ast.parse(source, filename=f"{module}.py")
    except SyntaxError as exc:
        raise FunctionSourceError(f"{module} does not parse: line {exc.lineno}: {exc.msg}") from None
    except ValueError as exc:
        raise FunctionSourceError(f"{module} does not parse: {exc}") from None


def _public_definitions(tree: ast.Module) -> list[FunctionSignature]:
    found: dict[str, FunctionSignature] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            found.pop(node.name, None)
            found[node.name] = _signature(node)  # a later definition replaces an earlier one
    return list(found.values())


def defined_functions(source: str, module: str) -> list[FunctionSignature]:
    """Every public top-level function *source*, the module *module*, defines,
    in source order, whatever its ``__all__`` says. Raises
    :class:`FunctionSourceError` when it does not parse."""
    return _public_definitions(_parse(source, module))


def _texts(node: ast.expr | None) -> list[str] | None:
    """The texts of a literal list or tuple of texts, else None."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    if not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
        return None
    return [item.value for item in node.elts]


def offered_names(tree: ast.Module) -> list[str] | None:
    """The names the module's ``__all__`` lists, in its order, each once: a
    literal list or tuple of texts assigned at its top level, and extended
    there with ``+=``. None when it has no ``__all__``, or one that only
    running the module could tell."""
    names: list[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            names = _texts(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            names = _texts(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            more = _texts(node.value) if isinstance(node.op, ast.Add) else None
            names = None if names is None or more is None else names + more
        else:
            continue
        if names is None:
            return None
    return None if names is None else list(dict.fromkeys(names))


def _bindings(tree: ast.Module) -> dict[str, object]:
    """What each name of the module's top level is bound to last, as the module
    runs: a function's definition, ``(the ImportFrom, the name it imports)``,
    or None for anything else (a class, a value, a module). Only statements at
    the top level count, not those inside an ``if`` or a ``try``."""
    bound: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound[node.name] = node
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    bound[alias.asname or alias.name] = (node, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound[alias.asname or alias.name.split(".", 1)[0]] = None
        elif isinstance(node, ast.ClassDef):
            bound[node.name] = None
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        bound[name.id] = None
    return bound


def _imported_module(module: str, package: bool, node: ast.ImportFrom) -> str | None:
    """The dotted name of the module *node* imports from, in the module
    *module*, a package's ``__init__.py`` when *package*: a relative import
    starts at the module's own package. None for one that climbs past it."""
    if not node.level:
        return node.module
    parts = module.split(".") if package else module.split(".")[:-1]
    climb = node.level - 1
    if climb >= len(parts):
        return None
    base = parts[: len(parts) - climb] + (node.module.split(".") if node.module else [])
    return ".".join(base)


def _resolved(
    name: str, bound: dict[str, object], module: str, package: bool,
    lookup: ModuleLookup | None, read: dict, depth: int = 0,
) -> FunctionSignature | None:
    """The function *name* is bound to in the module *module*: its own
    definition, or, through an import from another module of its package
    (*lookup*), that module's, at most MAX_REEXPORTS imports away. None for
    anything else. *read* keeps each module's bindings for the reader."""
    binding = bound.get(name)
    if isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _signature(binding)
    if not isinstance(binding, tuple) or lookup is None or depth >= MAX_REEXPORTS:
        return None
    node, imported = binding
    target = _imported_module(module, package, node)
    if target is None:
        return None
    if target not in read:
        found = lookup(target)
        try:
            read[target] = None if found is None else (_bindings(_parse(found[0], target)), bool(found[1]))
        except FunctionSourceError:
            read[target] = None
    if read[target] is None:
        return None
    target_bound, target_package = read[target]
    return _resolved(imported, target_bound, target, target_package, lookup, read, depth + 1)


def read_functions(
    source: str, module: str, *, package: bool = False, lookup: ModuleLookup | None = None,
) -> list[FunctionSignature]:
    """The functions *source*, the module *module*, offers, in order.

    With an ``__all__`` (:func:`offered_names`), the names it lists, in its
    order, that are functions: one the module defines, or one it imports from
    another module of its package, which *lookup* reads (*package* says the
    module is a package's ``__init__.py``, which a relative import starts
    from). A name it lists that is not a function, or that comes from a module
    the package does not ship, is left out. Without one, every public
    top-level function, in source order (:func:`defined_functions`).

    Raises :class:`FunctionSourceError` when *source* does not parse."""
    tree = _parse(source, module)
    names = offered_names(tree)
    if names is None:
        return _public_definitions(tree)
    bound = _bindings(tree)
    read: dict = {}
    found: list[FunctionSignature] = []
    for name in names:
        signature = _resolved(name, bound, module, package, lookup, read)
        if signature is not None:
            found.append(signature if signature.name == name else replace(signature, name=name))
    return found


def read_function(
    source: str, module: str, name: str, *, package: bool = False, lookup: ModuleLookup | None = None,
) -> FunctionSignature:
    """The function *name* the module offers (:func:`read_functions`), one a
    node can call."""
    for signature in read_functions(source, module, package=package, lookup=lookup):
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
    ``datetime``, ``date``, each also inside ``Optional``), else an unannotated
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


def suggested_use(param: Parameter, takes_widget: bool = True) -> str:
    """What the dialog starts a parameter at: its widget, else its default,
    else an input. *takes_widget* is False for a parameter named as no widget
    may be, such as one of the node's inputs, which gets no widget."""
    if takes_widget and suggest_widget(param) is not None:
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


def template_description(module: str, name: str, doc: str) -> str:
    """The template's description: what the function *name* does, *doc* in
    plain words, and where it comes from."""
    where = f"Calls {name} from {module}."
    return f"{doc} {where}" if doc else where
