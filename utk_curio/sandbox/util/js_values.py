"""Values as JavaScript writes them, for the texts the browser and the sandbox
both say.

A Map Edits node reads its code in the browser (``utils/editFeatures``), and
the sandbox reads the same code with a port of that reader
(``feature_edits_code.py``), so the two say the same words when they refuse
it. Where a reason shows a value, the browser shows it as JavaScript writes
it: ``String`` and ``JSON.stringify`` spell numbers their own way (``1e-7``
where Python writes ``1e-07``, ``3`` where Python writes ``3.0``), lay out
JSON with no spaces, and list an object's keys that are array indices first.
JavaScript's ``trim`` takes off its own set of spaces. These do the same.
"""
from __future__ import annotations

import json
import math
import re
from decimal import Decimal

#: The characters JavaScript's ``trim``, and its patterns' class of spaces,
#: take as spaces: its white space and its line terminators, by code point.
SPACES = "".join(chr(code) for code in (
    0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0xA0, 0x1680, *range(0x2000, 0x200B),
    0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF,
))
#: The characters JavaScript's ``.`` in a pattern does not match.
LINE_TERMINATORS = "".join(chr(code) for code in (0x0A, 0x0D, 0x2028, 0x2029))
#: A key JavaScript keeps as an array index: listed first, by its number.
_INDEX = re.compile(r"0|[1-9][0-9]*")


def trim(text: str) -> str:
    """*text* without the spaces JavaScript's ``trim`` takes off its ends."""
    return text.strip(SPACES)


def is_number(value) -> bool:
    """Whether *value* is what JavaScript calls a number (True and False are not)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def number(value) -> str:
    """The number *value* as JavaScript's ``String`` writes it."""
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    # The shortest digits that read back as the number, which both languages
    # write; then JavaScript's rules for where the point goes.
    shortest = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(str(d) for d in shortest.digits)
    k = len(digits)
    n = shortest.exponent + k
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        exponent = n - 1
        mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
        text = f"{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"
    return "-" + text if value < 0 else text


def string(value) -> str:
    """*value* as JavaScript's ``String`` writes it: a text, a number, true,
    false or null."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        return number(value)
    return str(value)


def keys(record: dict) -> list:
    """The keys of *record* in the order JavaScript lists an object's: those
    that are array indices first, by their number, then the others in the
    order they were made."""
    indices = [key for key in record if isinstance(key, str) and _INDEX.fullmatch(key) and int(key) < 2 ** 32 - 1]
    others = [key for key in record if key not in indices]
    return sorted(indices, key=int) + others


def ordered(record: dict) -> dict:
    """*record* with its keys in JavaScript's order (``keys``)."""
    return {key: record[key] for key in keys(record)}


def stringify(value) -> str:
    """*value*, a JSON value, as JavaScript's ``JSON.stringify`` writes it."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if is_number(value):
        return number(value) if math.isfinite(value) else "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(stringify(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{stringify(str(key))}:{stringify(value[key])}" for key in keys(value)) + "}"
    raise TypeError(f"{type(value).__name__} is not a JSON value")
