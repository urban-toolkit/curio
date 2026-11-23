"""OpenStreetMap tags that hold a number, written as numbers.

OpenStreetMap keeps every tag as text: a building's ``height`` is ``"12"``, a
road's ``maxspeed`` is ``"45 mph"``. ``with_numbers`` writes each value of the
keys below as a number, and a value that holds no number that can be read, such
as ``maxspeed=none`` or ``building:levels=3;4``, as null. Every other tag stays
text.

- Lengths, in metres (``LENGTH_KEYS``): a number followed by its unit is
  converted: ``m``, ``metre``, ``metres``, ``meter``, ``meters``, ``km``,
  ``mi``, ``nmi`` and ``ft``, in any case, and feet and inches (``12'``,
  ``12'6"``, ``6"``).
- Speeds, in kilometres per hour (``SPEED_KEYS``): ``km/h``, ``mph`` and
  ``knots`` are converted.
- Counts (``COUNT_KEYS``): a plain number alone.

A plain number is written as Curio's expression language writes one, signed,
with nothing around it once JavaScript's spaces are trimmed off
(``js_values.trim``), and it stays the number it writes, as does one written in
its key's own unit (``"86 metres"``, ``"50 km/h"``). A value converted from
another unit is rounded to two decimals as JavaScript's ``Math.round`` rounds:
``"40 ft"`` is 12.19, ``"45 mph"`` is 72.42. A value that is a number stays
that number. A whole number comes out as an int.

Curio's Autark loaders hand an OpenStreetMap table on by the same rule
(``withOsmNumbers`` in the frontend's ``src/adapters/node/autkDataCompile.ts``),
and both run one set of cases (``autkOsmNumbers.cases.json`` beside it), so
OpenStreetMap's data reads the same however it was loaded.
"""

from __future__ import annotations

import math
import re
from typing import Any

from utk_curio.sandbox.util.js_values import SPACES, trim

#: Lengths, in metres.
LENGTH_KEYS = frozenset({
    "height", "min_height", "roof:height", "building:height",
    "width", "est_width", "maxheight", "maxwidth", "maxlength",
    "ele", "depth",
})
#: Speeds, in kilometres per hour.
SPEED_KEYS = frozenset({"maxspeed", "maxspeed:forward", "maxspeed:backward", "minspeed"})
#: Counts, with no unit.
COUNT_KEYS = frozenset({
    "building:levels", "building:min_level", "building:levels:underground",
    "roof:levels", "levels", "min_level",
    "lanes", "lanes:forward", "lanes:backward", "lanes:both_ways",
    "layer",
    "capacity", "seats", "beds", "rooms", "building:flats",
})
NUMERIC_KEYS = LENGTH_KEYS | SPEED_KEYS | COUNT_KEYS

#: Metres in one of each length unit OpenStreetMap writes after a number.
_METRES = {
    "m": 1.0, "metre": 1.0, "metres": 1.0, "meter": 1.0, "meters": 1.0,
    "km": 1000.0, "mi": 1609.344, "nmi": 1852.0, "ft": 0.3048,
}
#: Kilometres per hour in one of each speed unit.
_KMH = {"km/h": 1.0, "mph": 1.609344, "knots": 1.852}
_FOOT = 0.3048
_INCH = 0.0254

#: A number as the expression language writes it (``NUMBER_TEXT`` in the
#: frontend's ``utils/editFeatures/applyEdits.ts``).
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
#: JavaScript's ``\s``: the spaces its ``trim`` takes off.
_SPACE = "[" + re.escape(SPACES) + "]*"
_PLAIN = re.compile(_NUMBER)
_LENGTH = re.compile(rf"({_NUMBER}){_SPACE}(m|metres?|meters?|km|mi|nmi|ft)", re.ASCII | re.IGNORECASE)
_SPEED = re.compile(rf"({_NUMBER}){_SPACE}(km/h|mph|knots)", re.ASCII | re.IGNORECASE)
#: Feet and inches: ``12'6"``, ``12'``, ``6"``, with spaces allowed between.
_FEET_INCHES = re.compile(rf"(?:([0-9]+(?:\.[0-9]+)?){_SPACE}')?{_SPACE}(?:([0-9]+(?:\.[0-9]+)?){_SPACE}\")?")


def number(key: str, raw: Any) -> int | float | None:
    """The value of tag *key*, one of ``NUMERIC_KEYS``, as a number in its unit, or None."""
    if key not in NUMERIC_KEYS:
        raise KeyError(f"{key!r} is not a numeric OpenStreetMap tag")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return _as_number(float(raw))
    if not isinstance(raw, str):
        return None
    text = trim(raw)
    if _PLAIN.fullmatch(text):
        return _as_number(float(text))
    if key in LENGTH_KEYS:
        return _length(text)
    if key in SPEED_KEYS:
        return _with_unit(_SPEED, _KMH, text)
    return None


def with_numbers(collection: dict[str, Any]) -> dict[str, Any]:
    """*collection* with each feature's ``NUMERIC_KEYS`` tags written as numbers."""
    features = []
    for feature in collection.get("features") or []:
        properties = feature.get("properties")
        if properties:
            properties = {
                key: number(key, value) if key in NUMERIC_KEYS else value
                for key, value in properties.items()
            }
        features.append({**feature, "properties": properties})
    return {**collection, "features": features}


def _length(text: str) -> int | float | None:
    written = _with_unit(_LENGTH, _METRES, text)
    if written is not None:
        return written
    feet_inches = _FEET_INCHES.fullmatch(text)
    if feet_inches and (feet_inches.group(1) is not None or feet_inches.group(2) is not None):
        return _converted(float(feet_inches.group(1) or 0) * _FOOT + float(feet_inches.group(2) or 0) * _INCH)
    return None


def _with_unit(pattern: re.Pattern, units: dict[str, float], text: str) -> int | float | None:
    """A number followed by one of *units*: as written in the unit worth 1,
    else converted."""
    match = pattern.fullmatch(text)
    if not match:
        return None
    value, factor = float(match.group(1)), units[match.group(2).lower()]
    return _as_number(value) if factor == 1.0 else _converted(value * factor)


def _converted(value: float) -> int | float | None:
    """*value* rounded to two decimals as JavaScript's ``Math.round(value * 100) / 100``
    rounds it: to the nearest hundredth, a half up, never to the even one."""
    scaled = value * 100
    if not math.isfinite(scaled):
        return None
    whole = math.floor(scaled)
    return _as_number((whole + (1 if scaled - whole >= 0.5 else 0)) / 100)


def _as_number(value: float) -> int | float | None:
    """*value* as a whole number an int; never NaN or infinity."""
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value
