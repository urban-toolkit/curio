"""OpenStreetMap tags that hold a number, written as numbers.

OpenStreetMap keeps every tag as text: a building's ``height`` is ``"12"``, a
road's ``maxspeed`` is ``"45 mph"``. The keys below hold one number in a unit
OpenStreetMap documents, metres for a length and kilometres per hour for a
speed when no unit is written. ``with_numbers`` writes each as that number, in
that unit, and a value that is not one number, such as ``maxspeed=none`` or
``building:levels=3;4``, as null. Every other tag stays text.

A value comes out as an int when it is whole and as a float rounded to two
decimals otherwise: ``"40 ft"`` is 12.19, ``"45 mph"`` is 72.42.
"""

from __future__ import annotations

import math
import re
from typing import Any

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
_METRES = {"m": 1.0, "km": 1000.0, "mi": 1609.344, "nmi": 1852.0, "ft": 0.3048}
#: Kilometres per hour in one of each speed unit.
_KMH = {"km/h": 1.0, "mph": 1.609344, "knots": 1.852}
_FOOT = 0.3048
_INCH = 0.0254

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_WITH_UNIT = re.compile(rf"({_NUMBER})\s*([a-z/]*)", re.IGNORECASE)
#: Feet and inches: ``12'6"``, ``12'``, ``6"``, with spaces allowed between.
_FEET_INCHES = re.compile(r"(?:(\d+(?:\.\d+)?)\s*')?\s*(?:(\d+(?:\.\d+)?)\s*\")?")


def number(key: str, raw: Any) -> int | float | None:
    """The value of tag *key*, one of ``NUMERIC_KEYS``, as a number in its unit, or None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return _tidy(float(raw))
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if key in LENGTH_KEYS:
        return _tidy(_length(text))
    if key in SPEED_KEYS:
        return _tidy(_with_unit(text, _KMH, default="km/h"))
    if key in COUNT_KEYS:
        return _tidy(_with_unit(text, {}, default=None))
    raise KeyError(f"{key!r} is not a numeric OpenStreetMap tag")


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


def _length(text: str) -> float | None:
    feet_inches = _FEET_INCHES.fullmatch(text)
    if feet_inches and (feet_inches.group(1) or feet_inches.group(2)):
        feet, inches = feet_inches.group(1), feet_inches.group(2)
        return float(feet or 0) * _FOOT + float(inches or 0) * _INCH
    return _with_unit(text, _METRES, default="m")


def _with_unit(text: str, units: dict[str, float], *, default: str | None) -> float | None:
    """A number followed by one of *units*, or by nothing (the *default* unit)."""
    match = _WITH_UNIT.fullmatch(text)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    if not unit:
        return value
    if unit == default or unit in units:
        return value * units.get(unit, 1.0)
    return None


def _tidy(value: float | None) -> int | float | None:
    """Whole numbers as ints, others rounded to two decimals; never NaN or infinity."""
    if value is None or not math.isfinite(value):
        return None
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded
