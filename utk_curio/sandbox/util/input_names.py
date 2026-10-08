"""The names a node's code reads its inputs by: ``input_0``, ``input_1``, …

Each input circle of a node is one variable, named after the circle: what the
edge on circle k delivers is ``input_k``. A tuple an upstream node returns is
one value on its circle, so its items are ``input_k[0]``, ``input_k[1]``, …. A
circle with no edge is None.

The in-process worker (``app/worker.py``), the isolated child
(``isolation/child.py``) and the JavaScript wrapper (``js_wrapper.mjs``, through
``worker.run_js_script``) all bind the inputs through here, so the three agree
on every name.

``input`` and ``arg``, the names a node's whole input once had, are gone: code
that still reads them fails with :data:`LEGACY_INPUT_MESSAGE` instead of
silently calling Python's built-in ``input()``.
"""
from __future__ import annotations

import ast
import re

#: ``input_<circle>``, as code names it and as the canvas tags it.
INPUT_NAME_RE = re.compile(r"^input_(\d+)$")

#: The names the whole input once had.
LEGACY_NAMES = ("input", "arg")

LEGACY_INPUT_MESSAGE = (
    "This node's code reads `{name}`, which Curio no longer defines. Each input "
    "circle is its own variable, named after the circle: input_0, input_1, and "
    "so on (a tuple on one circle is input_0[0], input_0[1], ...). Replace "
    "`{name}` with the input it means, e.g. `input_0`."
)

MISSING_INPUT_MESSAGE = (
    "This node's code reads `{name}`, but nothing arrived on input circle {slot}. "
    "Either no edge is wired to that circle, or the node feeding it has not run "
    "yet or failed. Check the nodes feeding this one: fix any that show an "
    "error, run them until each shows 'Done', then run this node again."
)


def input_name(slot: int) -> str:
    return f"input_{slot}"


def _parse(code: str):
    """*code* as the body of a function, or None if it does not parse."""
    try:
        return ast.parse("def userCode():\n" + code)
    except SyntaxError:
        return None


def input_names_read(code: str) -> list[int]:
    """The circles whose ``input_k`` *code* reads (a load, not only a binding)."""
    tree = _parse(code)
    if tree is None:
        found = {int(m.group(1)) for m in re.finditer(r"\binput_(\d+)\b", code)}
        return sorted(found)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            m = INPUT_NAME_RE.match(node.id)
            if m:
                found.add(int(m.group(1)))
    return sorted(found)


def legacy_name_read(code: str) -> str | None:
    """``input`` or ``arg`` when *code* reads one it never binds itself.

    A name the code assigns, imports, takes as a parameter or loops over is the
    code's own (``for arg in args``), so only a read of an unbound one is the
    old input.
    """
    tree = _parse(code)
    if tree is None:
        m = re.search(r"\b(input|arg)\b(?!\s*=[^=])", code)
        return m.group(1) if m else None
    bound: set[str] = set()
    read: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in LEGACY_NAMES:
            if isinstance(node.ctx, ast.Load):
                read.append(node.id)
            else:
                bound.add(node.id)
        elif isinstance(node, ast.arg) and node.arg in LEGACY_NAMES:
            bound.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                if name in LEGACY_NAMES:
                    bound.add(name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in LEGACY_NAMES:
                bound.add(node.name)
    for name in read:
        if name not in bound:
            return name
    return None


def _js_code_only(code: str) -> str:
    """*code* with its comments and string literals blanked."""
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", " ", code, flags=re.S)
    return re.sub(r"`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"", "''", stripped)


def input_names_read_js(code: str) -> list[int]:
    """:func:`input_names_read` for JavaScript, by words outside strings and comments."""
    found = {int(m.group(1)) for m in re.finditer(r"(?<![\w$.])input_(\d+)(?![\w$])", _js_code_only(code))}
    return sorted(found)


def legacy_name_read_js(code: str) -> str | None:
    """:func:`legacy_name_read` for JavaScript, by words outside strings and comments."""
    stripped = _js_code_only(code)
    for name in LEGACY_NAMES:
        declared = re.search(
            rf"\b(?:const|let|var|function)\s+{name}\b|[(,]\s*{name}\s*[,)=]|\bof\s+{name}\b",
            stripped,
        )
        if declared:
            continue
        if re.search(rf"(?<![\w$.]){name}(?![\w$])", stripped):
            return name
    return None


def user_code_header(code: str) -> str:
    """The one line a node's Python code is the body of.

    Every ``input_k`` the code reads is a parameter that defaults to None, so a
    read of an unwired circle is None rather than a ``NameError``; the ``**``
    swallows circles the code never reads.
    One line, so a traceback's line numbers stay the code's own plus one, as
    they always were.
    """
    params = [f"{input_name(k)}=None" for k in input_names_read(code)]
    params.append("**_curio_unread_inputs")
    return f"def userCode({', '.join(params)}):"


def split_inputs(value, slots, data_type="") -> dict[str, object]:
    """``{"input_k": value}`` for each wired circle k.

    *slots* lists the wired circles in circle order, as the canvas and the
    runners know them. With several, *value* is their values in that order (a
    list or a tuple); with one, *value* is that circle's whole value, a Data
    Pool's bundle of layers included. Without *slots* (a caller that predates
    them) the circles are taken to be 0, 1, …: several when *data_type* is
    ``outputs`` and *value* a list or tuple, else one.
    """
    if value is None or (isinstance(value, str) and value == ""):
        return {}
    if not slots:
        if data_type == "outputs" and isinstance(value, (list, tuple)):
            slots = list(range(len(value)))
        else:
            slots = [0]
    slots = [int(s) for s in slots]
    if len(slots) == 1:
        return {input_name(slots[0]): value}
    if not isinstance(value, (list, tuple)):
        return {input_name(slots[0]): value}
    # Several edges on one circle (a port that takes many) are that circle's
    # list, in edge order.
    grouped: dict[int, list] = {}
    for slot, item in zip(slots, value):
        grouped.setdefault(slot, []).append(item)
    return {
        input_name(slot): items[0] if slots.count(slot) == 1 else items
        for slot, items in grouped.items()
    }


def missing_input(code: str, bound: dict, *, javascript: bool = False) -> str | None:
    """The message for code that reads an input when none arrived.

    A circle with no edge is None, so a node can take an optional input (a
    Raster Statistics node's mask on input_1). But code that reads its inputs
    and got none at all would fail on the first ``input_0[...]`` with a
    confusing ``'NoneType' object is not subscriptable``; this names the
    circle instead, so the user looks at what feeds it.
    """
    if any(value is not None for value in bound.values()):
        return None
    read = input_names_read_js(code) if javascript else input_names_read(code)
    if not read:
        return None
    return MISSING_INPUT_MESSAGE.format(name=input_name(read[0]), slot=read[0])


def call_as_node(code: str, namespace: dict, value=None, slots=None, data_type=""):
    """Run *code*, a node's body indented as a function's, as the sandbox does:
    defined under :func:`user_code_header` in *namespace*, then called with
    *value* split over the circles *slots* (:func:`split_inputs`). For tests and
    tools that run a node's code outside a sandbox."""
    exec(f"{user_code_header(code)}\n{code}", namespace)  # noqa: S102 - the sandbox does exactly this
    return namespace["userCode"](**split_inputs(value, slots, data_type))


def legacy_input_message(name: str) -> str:
    return LEGACY_INPUT_MESSAGE.format(name=name)


def parse_slots(raw) -> list[int] | None:
    """A request's ``input_slots``, or None when absent or malformed."""
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    try:
        slots = [int(s) for s in raw]
    except (TypeError, ValueError):
        return None
    if any(s < 0 or s > 255 for s in slots):
        return None
    return slots
