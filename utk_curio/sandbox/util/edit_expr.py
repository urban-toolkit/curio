"""The Interaction node's expressions: the conditions its edits pick features
by (``where``) and the formulas an ``expr`` edit writes, over one feature's
properties.

A small language, never Python's ``eval``, kept in step with
``utils/editFeatures/editExpr.ts`` (both read ``editExpr.cases.json``):

- a column: a name (``height``, ``building:levels``), or any name in
  backticks (`` `Mean Acc shadow` ``);
- a number, a text in single or double quotes, ``true``, ``false``, ``null``;
- ``+ - * / %``, a leading ``-``, comparisons ``== != < <= > >=``, ``and``,
  ``or``, ``not``, and parentheses;
- the functions ``abs``, ``min``, ``max`` and ``round``.

A column a feature lacks is null. Arithmetic with null, or with a text, is
null; a comparison with null is false.
"""
from __future__ import annotations

import math
import re

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|(?P<str>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")"
    r"|(?P<tick>`[^`]*`)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_:.]*)"
    r"|(?P<op>==|!=|<=|>=|[-+*/%<>(),])"
    r")"
)
_KEYWORDS = {"and", "or", "not", "true", "false", "null"}
_FUNCTIONS = {"abs", "min", "max", "round"}


class ExprError(ValueError):
    pass


def _tokens(text: str):
    out, pos = [], 0
    text = text or ""
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise ExprError(f"cannot read {text[pos:].strip()[:20]!r} in {text!r}")
        pos = match.end()
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "num":
            out.append(("num", float(value)))
        elif kind == "str":
            out.append(("str", re.sub(r"\\(.)", r"\1", value[1:-1])))
        elif kind == "tick":
            out.append(("col", value[1:-1]))
        elif kind == "name":
            out.append(("kw", value) if value in _KEYWORDS else ("name", value))
        else:
            out.append(("op", value))
    return out


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokens(text)
        self.at = 0

    def peek(self, kind=None, value=None):
        if self.at >= len(self.tokens):
            return None
        token = self.tokens[self.at]
        if kind is not None and token[0] != kind:
            return None
        if value is not None and token[1] != value:
            return None
        return token

    def take(self, kind=None, value=None):
        token = self.peek(kind, value)
        if token is None:
            want = value or kind or "more"
            raise ExprError(f"expected {want} in {self.text!r}")
        self.at += 1
        return token

    def parse(self):
        if not self.tokens:
            raise ExprError("the expression is empty")
        node = self.or_()
        if self.at != len(self.tokens):
            raise ExprError(f"unexpected {self.tokens[self.at][1]!r} in {self.text!r}")
        return node

    def or_(self):
        node = self.and_()
        while self.peek("kw", "or"):
            self.take()
            node = ("or", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.peek("kw", "and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.peek("kw", "not"):
            self.take()
            return ("not", self.not_())
        return self.compare()

    def compare(self):
        node = self.sum_()
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if self.peek("op", op):
                self.take()
                return ("cmp", op, node, self.sum_())
        return node

    def sum_(self):
        node = self.product()
        while self.peek("op", "+") or self.peek("op", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.product())
        return node

    def product(self):
        node = self.unary()
        while self.peek("op", "*") or self.peek("op", "/") or self.peek("op", "%"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek("op", "-"):
            self.take()
            return ("neg", self.unary())
        return self.atom()

    def atom(self):
        token = self.peek()
        if token is None:
            raise ExprError(f"the expression {self.text!r} ends too soon")
        kind, value = token
        if kind == "num" or kind == "str":
            self.take()
            return ("lit", value)
        if kind == "kw" and value in ("true", "false", "null"):
            self.take()
            return ("lit", {"true": True, "false": False, "null": None}[value])
        if kind == "col":
            self.take()
            return ("col", value)
        if kind == "name":
            self.take()
            if self.peek("op", "("):
                if value not in _FUNCTIONS:
                    raise ExprError(f"{value} is not a function here: use abs, min, max or round")
                self.take()
                args = [self.or_()]
                while self.peek("op", ","):
                    self.take()
                    args.append(self.or_())
                self.take("op", ")")
                return ("call", value, args)
            return ("col", value)
        if kind == "op" and value == "(":
            self.take()
            node = self.or_()
            self.take("op", ")")
            return node
        raise ExprError(f"unexpected {value!r} in {self.text!r}")


def parse(text: str):
    """The expression *text*, parsed; ExprError when it is not one."""
    return _Parser(text).parse()


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return _number(value.item())
    except ImportError:  # pragma: no cover
        pass
    return None


def _plain(value):
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:  # pragma: no cover
        pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _out(value):
    """A number result as JSON would carry it: 15 significant digits (as the
    preview keeps them), whole numbers as ints."""
    if isinstance(value, float) and math.isfinite(value):
        value = float(f"{value:.15g}")
        if value.is_integer():
            return int(value)
    return value


def evaluate(node, row: dict):
    """*node* over one feature's properties *row*."""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "col":
        return _plain(row.get(node[1]))
    if kind == "not":
        return not truthy(evaluate(node[1], row))
    if kind == "and":
        return truthy(evaluate(node[1], row)) and truthy(evaluate(node[2], row))
    if kind == "or":
        return truthy(evaluate(node[1], row)) or truthy(evaluate(node[2], row))
    if kind == "neg":
        value = _number(evaluate(node[1], row))
        return None if value is None else _out(-value)
    if kind == "bin":
        left, right = _number(evaluate(node[2], row)), _number(evaluate(node[3], row))
        if left is None or right is None:
            if node[1] == "+":
                a, b = evaluate(node[2], row), evaluate(node[3], row)
                if isinstance(a, str) and isinstance(b, str):
                    return a + b
            return None
        op = node[1]
        if op == "+":
            return _out(left + right)
        if op == "-":
            return _out(left - right)
        if op == "*":
            return _out(left * right)
        if right == 0:
            return None
        return _out(left / right) if op == "/" else _out(math.fmod(left, right))
    if kind == "cmp":
        op, a, b = node[1], _plain(evaluate(node[2], row)), _plain(evaluate(node[3], row))
        if a is None or b is None:
            return False
        na, nb = _number(a), _number(b)
        if na is not None and nb is not None:
            a, b = na, nb
        elif type(a) is not type(b):
            return op == "!="
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        try:
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        except TypeError:
            return False
    if kind == "call":
        name, args = node[1], [evaluate(arg, row) for arg in node[2]]
        numbers = [_number(arg) for arg in args]
        if any(n is None for n in numbers):
            return None
        if name == "abs" and len(numbers) == 1:
            return _out(abs(numbers[0]))
        if name == "round":
            digits = int(numbers[1]) if len(numbers) > 1 else 0
            return _out(_round_half_away(numbers[0], digits))
        if name == "min" and numbers:
            return _out(min(numbers))
        if name == "max" and numbers:
            return _out(max(numbers))
        raise ExprError(f"{name} takes {'one argument' if name == 'abs' else 'numbers'}")
    raise ExprError(f"cannot evaluate {kind}")  # pragma: no cover


def _round_half_away(value: float, digits: int) -> float:
    """Round half away from zero, as JavaScript's tests expect, not Python's banker's rounding."""
    scale = 10 ** digits
    shifted = abs(value) * scale
    rounded = math.floor(shifted + 0.5) / scale
    return math.copysign(rounded, value)


def truthy(value) -> bool:
    return value is not None and value is not False and value != 0 and value != ""
