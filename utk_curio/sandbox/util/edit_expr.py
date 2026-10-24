"""The Map Editor node's expressions: the conditions its edits pick features
by (``where``) and the formulas an ``expr`` edit computes, over one feature's
properties.

A small language read by its own parser, never by Python's ``eval``. Its twin
is ``utils/editFeatures/editExpr.ts`` in the frontend, and both read the cases
in ``utils/editFeatures/editExpr.cases.json``, so the node's table in the
browser and a run agree on every value. A text that is not an expression is
refused in the twin's words, values written as JavaScript writes them
(``js_values``), so the node and the sandbox's reader of its code
(``feature_edits_code.py``) give one reason.

- A column: a name (``height``, ``building:levels``), or any text in
  backticks (`` `Mean Acc shadow` ``).
- A number (``3``, ``0.5``, ``1e3``), a text in single or double quotes (a
  backslash keeps the next character as it is), ``true``, ``false``, ``null``.
- ``+ - * / %``, a leading ``-``, one comparison ``== != < <= > >=``,
  ``and``, ``or``, ``not``, and parentheses.
- The functions ``abs(x)``, ``round(x)``, ``round(x, digits)``,
  ``min(a, ...)`` and ``max(a, ...)``.

What a value is:

- A column a feature lacks, or one holding something other than a number, a
  text, true or false, is null.
- Arithmetic takes numbers, and ``+`` also joins two texts; anything else,
  and a division by zero, is null. A result keeps 15 significant digits, and
  ``round`` rounds half away from zero.
- A comparison with null is false. Two numbers compare by value and two texts
  in text order; a number and a text are never equal.
- ``and``, ``or`` and ``not`` give true or false. Null, false, 0 and the
  empty text count as false, anything else as true.
"""
from __future__ import annotations

import math
import re
from decimal import ROUND_HALF_UP, Decimal

from utk_curio.sandbox.util import js_values

#: Deeper than this, an expression is refused, so a run never meets Python's
#: own recursion limit where the browser would meet another.
MAX_DEPTH = 50

#: Whitespace, spelled out: ``\s`` and ``\d`` mean more characters in Python
#: than in JavaScript.
_SPACE = re.compile(r"[ \t\r\n]*")
_TOKEN = re.compile(
    r"(?P<num>[0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?|\.[0-9]+(?:[eE][+-]?[0-9]+)?)"
    r"|(?P<str>'(?:[^'\\]|\\[\s\S])*'|\"(?:[^\"\\]|\\[\s\S])*\")"
    r"|(?P<tick>`[^`]+`)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_:.]*)"
    r"|(?P<op>==|!=|<=|>=|[-+*/%<>(),])"
)
_ESCAPE = re.compile(r"\\([\s\S])")
_KEYWORDS = frozenset({"and", "or", "not", "true", "false", "null"})
#: Each function and how many arguments it takes, at least and at most.
_FUNCTIONS = {"abs": (1, 1), "round": (1, 2), "min": (1, None), "max": (1, None)}
_COMPARISONS = ("==", "!=", "<=", ">=", "<", ">")
#: Powers of ten written out, so a scale is the same number in both languages.
_TENS = [10 ** k for k in range(16)]


class ExprError(ValueError):
    """The text is not an expression, or a function was given the wrong number
    of arguments."""


def _tokens(text: str):
    out = []
    pos = 0
    while True:
        pos = _SPACE.match(text, pos).end()
        if pos >= len(text):
            return out
        match = _TOKEN.match(text, pos)
        if not match:
            raise ExprError(f"cannot read '{text[pos:pos + 20]}' in '{text}'")
        kind = match.lastgroup
        value = match.group(kind)
        pos = match.end()
        if kind == "num":
            literal = float(value)
            if not math.isfinite(literal):
                raise ExprError(f"{value} is too large a number")
            out.append(("lit", _whole(literal)))
        elif kind == "str":
            out.append(("lit", _ESCAPE.sub(lambda m: m.group(1), value[1:-1])))
        elif kind == "tick":
            out.append(("col", value[1:-1]))
        elif kind == "name":
            out.append(("kw", value) if value in _KEYWORDS else ("name", value))
        else:
            out.append(("op", value))


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokens(text)
        self.at = 0
        self.depth = 0

    def _peek(self, kind=None, value=None):
        if self.at >= len(self.tokens):
            return None
        token = self.tokens[self.at]
        if (kind is not None and token[0] != kind) or (value is not None and token[1] != value):
            return None
        return token

    def _take(self, kind=None, value=None):
        token = self._peek(kind, value)
        if token is None:
            raise ExprError(f"expected {value or kind or 'more'} in '{self.text}'")
        self.at += 1
        return token

    def _deeper(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError(f"the expression nests deeper than {MAX_DEPTH} levels")

    def parse(self):
        if not self.tokens:
            raise ExprError("the expression is empty")
        node = self._or()
        if self.at != len(self.tokens):
            raise ExprError(f"unexpected '{js_values.string(self.tokens[self.at][1])}' in '{self.text}'")
        return node

    def _or(self):
        node = self._and()
        while self._peek("kw", "or"):
            self._take()
            node = ("or", node, self._and())
        return node

    def _and(self):
        node = self._not()
        while self._peek("kw", "and"):
            self._take()
            node = ("and", node, self._not())
        return node

    def _not(self):
        if self._peek("kw", "not"):
            self._take()
            self._deeper()
            node = ("not", self._not())
            self.depth -= 1
            return node
        return self._compare()

    def _compare(self):
        node = self._sum()
        for op in _COMPARISONS:
            if self._peek("op", op):
                self._take()
                return ("cmp", op, node, self._sum())
        return node

    def _sum(self):
        node = self._product()
        while self._peek("op", "+") or self._peek("op", "-"):
            op = self._take()[1]
            node = ("bin", op, node, self._product())
        return node

    def _product(self):
        node = self._unary()
        while self._peek("op", "*") or self._peek("op", "/") or self._peek("op", "%"):
            op = self._take()[1]
            node = ("bin", op, node, self._unary())
        return node

    def _unary(self):
        if self._peek("op", "-"):
            self._take()
            self._deeper()
            node = ("neg", self._unary())
            self.depth -= 1
            return node
        return self._atom()

    def _atom(self):
        token = self._peek()
        if token is None:
            raise ExprError(f"the expression '{self.text}' ends too soon")
        kind, value = token
        if kind in ("lit", "col"):
            self._take()
            return token
        if kind == "kw" and value in ("true", "false", "null"):
            self._take()
            return ("lit", {"true": True, "false": False, "null": None}[value])
        if kind == "name":
            self._take()
            if not self._peek("op", "("):
                return ("col", value)
            if value not in _FUNCTIONS:
                raise ExprError(f"{value} is not a function: use abs, round, min or max")
            self._take()
            self._deeper()
            args = [self._or()]
            while self._peek("op", ","):
                self._take()
                args.append(self._or())
            self._take("op", ")")
            self.depth -= 1
            least, most = _FUNCTIONS[value]
            if len(args) < least or (most is not None and len(args) > most):
                raise ExprError(f"{value} takes {_arity(value)}, not {len(args)}")
            return ("call", value, args)
        if kind == "op" and value == "(":
            self._take()
            self._deeper()
            node = self._or()
            self._take("op", ")")
            self.depth -= 1
            return node
        raise ExprError(f"unexpected '{js_values.string(value)}' in '{self.text}'")


def _arity(name: str) -> str:
    least, most = _FUNCTIONS[name]
    if most == least:
        return "one argument"
    if most is None:
        return "one argument or more"
    return f"{least} or {most} arguments"


def parse(text: str):
    """The expression *text*, parsed. ExprError when it is not one."""
    if not isinstance(text, str):
        raise ExprError("an expression is a text")
    return _Parser(text).parse()


def _scalar(value):
    """A value as the language sees it: a number, a text, true, false or null.
    numpy's numbers are numbers; a value that is not finite, a list, a date or
    anything else is null."""
    try:
        import numpy as np

        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:  # pragma: no cover  (numpy ships with the sandbox)
        pass
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return None


def number(value):
    """*value* as a finite float, or None when it is not a number (true and
    false are not numbers)."""
    value = _scalar(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except OverflowError:
        return None
    return out if math.isfinite(out) else None


def tidy(value: float) -> float:
    """A finite *value* to 15 significant digits, half away from zero, as
    JavaScript's ``toPrecision(15)`` gives it, so a run writes what the
    browser shows. Zero has no sign."""
    if value == 0:
        return 0.0
    exact = Decimal(value)
    rounded = exact.quantize(Decimal(1).scaleb(exact.adjusted() - 14), rounding=ROUND_HALF_UP)
    return float(rounded)


def _whole(value: float):
    """A whole number as an int, as JSON writes it, while a float holds it exactly."""
    return int(value) if value.is_integer() and abs(value) < 2 ** 53 else value


def result(value: float):
    """A number an expression makes: null when it is not finite, else kept to
    15 significant digits, a whole one as an int."""
    if not math.isfinite(value):
        return None
    return _whole(tidy(value))


def truthy(value) -> bool:
    """Whether a value counts as true: anything but null, false, 0 and ''."""
    if value is None or value is False or value == "":
        return False
    amount = number(value)
    return amount is None or amount != 0


def _round_half_away(value: float, digits: float) -> float:
    places = max(-15, min(15, int(digits)))
    if places >= 0:
        scaled = abs(value) * _TENS[places] + 0.5
    else:
        scaled = abs(value) / _TENS[-places] + 0.5
    if not math.isfinite(scaled):
        return value
    # In floats throughout, as JavaScript computes it.
    floor = float(math.floor(scaled))
    rounded = floor / _TENS[places] if places >= 0 else floor * _TENS[-places]
    return -rounded if value < 0 else rounded


def evaluate(node, row):
    """What the parsed expression *node* makes of one feature's properties *row*."""
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "col":
        return _scalar(row.get(node[1])) if isinstance(row, dict) else None
    if kind == "not":
        return not truthy(evaluate(node[1], row))
    if kind == "and":
        return truthy(evaluate(node[1], row)) and truthy(evaluate(node[2], row))
    if kind == "or":
        return truthy(evaluate(node[1], row)) or truthy(evaluate(node[2], row))
    if kind == "neg":
        value = number(evaluate(node[1], row))
        return None if value is None else result(-value)
    if kind == "bin":
        return _arithmetic(node[1], evaluate(node[2], row), evaluate(node[3], row))
    if kind == "cmp":
        return _compare(node[1], evaluate(node[2], row), evaluate(node[3], row))
    if kind == "call":
        return _call(node[1], [evaluate(arg, row) for arg in node[2]])
    raise ExprError(f"cannot evaluate {kind}")  # pragma: no cover


def _arithmetic(op, a, b):
    x, y = number(a), number(b)
    if x is None or y is None:
        if op == "+" and isinstance(a, str) and isinstance(b, str):
            return a + b
        return None
    if op == "+":
        return result(x + y)
    if op == "-":
        return result(x - y)
    if op == "*":
        return result(x * y)
    if y == 0:
        return None
    return result(x / y) if op == "/" else result(math.fmod(x, y))


def _compare(op, a, b):
    a, b = _scalar(a), _scalar(b)
    if a is None or b is None:
        return False
    x, y = number(a), number(b)
    if x is not None and y is not None:
        a, b = x, y
    elif isinstance(a, bool) and isinstance(b, bool):
        a, b = int(a), int(b)
    elif not (isinstance(a, str) and isinstance(b, str)):
        return op == "!="
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if isinstance(a, str):
        # Text order by UTF-16 code units, as JavaScript compares texts.
        a, b = a.encode("utf-16-be", "surrogatepass"), b.encode("utf-16-be", "surrogatepass")
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    return a >= b


def _call(name, args):
    numbers = [number(arg) for arg in args]
    if any(n is None for n in numbers):
        return None
    if name == "abs":
        return result(abs(numbers[0]))
    if name == "round":
        return result(_round_half_away(numbers[0], numbers[1] if len(numbers) > 1 else 0))
    if name == "min":
        return result(min(numbers))
    return result(max(numbers))
