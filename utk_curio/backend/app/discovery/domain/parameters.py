"""What a person fills in before adding a resource: a source's declared parameters.

A query service has nothing to browse. Its manifest declares the questions a
person answers before a download, the way a storage manifest declares how its
files are organized: an area, a date range, a choice, a number. The page
renders one form from the declarations, and the server checks every answer
against the same declarations before anything is fetched.

Declared at the source (shared by every resource) or on a resource; a
resource's entry replaces the source's entry with the same ``id``.

An ``area`` has two forms, and a declaration says which it accepts:

- ``box``: ``{"box": [west, south, east, north], "label": "..."}`` in WGS84;
- ``names``: ``{"names": {"geocodeArea": "Chicago", "areas": ["Loop"]}}``,
  named OpenStreetMap areas, the form Autark's OSM loader takes.

``normalize`` gives equal requests equal values, so ``values_hash`` can key
the held lookup: the same area, dates and choices are the same dataset.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

PARAMETER_TYPES = ("area", "dateRange", "choice", "number", "integer", "boolean", "text", "url")
AREA_FORMS = ("box", "names")

MAX_PARAMETERS = 16
MAX_OPTIONS = 64
MAX_TEXT_LENGTH = 500
MAX_URL_LENGTH = 2048
MAX_AREA_NAMES = 10
MAX_NAME_LENGTH = 120
#: Boxes are compared to five decimals, about a metre.
BOX_DECIMALS = 5

_ID_RE = re.compile(r"^[a-z][A-Za-z0-9]{0,31}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: A named area goes into an Overpass query as ``area["name"="..."]``, so a
#: quote, a bracket or a backslash in it would change the query.
_NAME_FORBIDDEN = re.compile(r'["\[\]\\\n\r\t]')
_EARTH_RADIUS_KM = 6371.0088


class ManifestParameterError(ValueError):
    """A manifest declares a parameter badly. Raised while reading the manifest."""


class ParameterError(DiscoveryError):
    """A request's answer does not fit what the source declares. 400."""

    status = 400


@dataclass(frozen=True)
class ChoiceOption:
    value: str
    label: str


@dataclass(frozen=True)
class ParameterSpec:
    id: str
    type: str
    label: str
    description: str = ""
    required: bool = False
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None
    options: tuple[ChoiceOption, ...] = ()
    multiple: bool = False
    pattern: str | None = None
    accepts: tuple[str, ...] = ("box",)
    max_area_km2: float | None = None
    min_date: str | None = None
    max_date: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── reading a manifest ────────────────────────────────────────────────────


def parse_parameters(raw: object, *, where: str) -> tuple[ParameterSpec, ...]:
    """The ``parameters`` list of a source or of one resource."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ManifestParameterError(f"{where} must be an array")
    if len(raw) > MAX_PARAMETERS:
        raise ManifestParameterError(f"{where} is limited to {MAX_PARAMETERS} entries")
    seen: set[str] = set()
    out = []
    for index, entry in enumerate(raw):
        spec = _parse_one(entry, where=f"{where}[{index}]")
        if spec.id in seen:
            raise ManifestParameterError(f"{where}[{index}].id {spec.id!r} is used twice")
        seen.add(spec.id)
        out.append(spec)
    return tuple(out)


def merge(source: tuple[ParameterSpec, ...], resource: tuple[ParameterSpec, ...]) -> tuple[ParameterSpec, ...]:
    """The source's parameters, with a resource's entries replacing same-id ones."""
    by_id = {spec.id: spec for spec in source}
    for spec in resource:
        by_id[spec.id] = spec
    order = [spec.id for spec in source] + [s.id for s in resource if s.id not in {x.id for x in source}]
    return tuple(by_id[i] for i in order)


def _number(raw: object, where: str) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ManifestParameterError(f"{where} must be a number")
    return float(raw)


def _parse_one(raw: object, *, where: str) -> ParameterSpec:
    if not isinstance(raw, dict):
        raise ManifestParameterError(f"{where} must be an object")
    pid = raw.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        raise ManifestParameterError(f"{where}.id must be a short camelCase name, got {pid!r}")
    kind = raw.get("type")
    if kind not in PARAMETER_TYPES:
        raise ManifestParameterError(f"{where}.type must be one of {list(PARAMETER_TYPES)}")
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ManifestParameterError(f"{where}.label must be a non-empty string")
    description = raw.get("description") or ""
    if not isinstance(description, str):
        raise ManifestParameterError(f"{where}.description must be a string")
    required = raw.get("required", False)
    if not isinstance(required, bool):
        raise ManifestParameterError(f"{where}.required must be a boolean")

    minimum = _number(raw.get("min"), f"{where}.min")
    maximum = _number(raw.get("max"), f"{where}.max")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ManifestParameterError(f"{where}.min is greater than max")
    if kind not in ("number", "integer") and (minimum is not None or maximum is not None):
        raise ManifestParameterError(f"{where}.min and max apply to numbers only")
    step = _number(raw.get("step"), f"{where}.step")
    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or len(unit) > 16):
        raise ManifestParameterError(f"{where}.unit must be a short string")

    options: tuple[ChoiceOption, ...] = ()
    multiple = bool(raw.get("multiple", False))
    if kind == "choice":
        raw_options = raw.get("options")
        if not isinstance(raw_options, list) or not raw_options or len(raw_options) > MAX_OPTIONS:
            raise ManifestParameterError(f"{where}.options must list 1 to {MAX_OPTIONS} choices")
        parsed = []
        for o_index, option in enumerate(raw_options):
            if not isinstance(option, dict) or not isinstance(option.get("value"), str) or not option["value"]:
                raise ManifestParameterError(f"{where}.options[{o_index}].value must be a string")
            parsed.append(ChoiceOption(option["value"], str(option.get("label") or option["value"])))
        if len({o.value for o in parsed}) != len(parsed):
            raise ManifestParameterError(f"{where}.options repeats a value")
        options = tuple(parsed)
    elif "options" in raw or "multiple" in raw:
        raise ManifestParameterError(f"{where}.options and multiple apply to a choice only")

    pattern = raw.get("pattern")
    if pattern is not None:
        if kind != "text" or not isinstance(pattern, str):
            raise ManifestParameterError(f"{where}.pattern applies to text only")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ManifestParameterError(f"{where}.pattern is not a regular expression: {exc}") from exc

    accepts: tuple[str, ...] = ("box",)
    max_area = None
    if kind == "area":
        raw_accepts = raw.get("accepts", ["box"])
        if not isinstance(raw_accepts, list) or not raw_accepts or any(a not in AREA_FORMS for a in raw_accepts):
            raise ManifestParameterError(f"{where}.accepts must list forms from {list(AREA_FORMS)}")
        accepts = tuple(dict.fromkeys(raw_accepts))
        max_area = _number(raw.get("maxAreaKm2"), f"{where}.maxAreaKm2")
        if max_area is not None and max_area <= 0:
            raise ManifestParameterError(f"{where}.maxAreaKm2 must be positive")
    elif "accepts" in raw or "maxAreaKm2" in raw:
        raise ManifestParameterError(f"{where}.accepts and maxAreaKm2 apply to an area only")

    min_date = raw.get("minDate")
    max_date = raw.get("maxDate")
    if kind == "dateRange":
        for name, value in (("minDate", min_date), ("maxDate", max_date)):
            if value is not None and not _is_date(value):
                raise ManifestParameterError(f"{where}.{name} must be a date like 2024-01-31")
    elif min_date is not None or max_date is not None:
        raise ManifestParameterError(f"{where}.minDate and maxDate apply to a date range only")

    spec = ParameterSpec(
        id=pid, type=kind, label=label.strip(), description=description, required=required,
        minimum=minimum, maximum=maximum, step=step, unit=unit, options=options,
        multiple=multiple, pattern=pattern, accepts=accepts, max_area_km2=max_area,
        min_date=min_date, max_date=max_date,
    )
    default = raw.get("default")
    if default is not None:
        try:
            spec = replace(spec, default=_check(spec, default))
        except ParameterError as exc:
            raise ManifestParameterError(f"{where}.default: {exc}") from exc
    return spec


def _is_date(value: object) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


# ── checking a request ────────────────────────────────────────────────────


def validate_values(declared: tuple[ParameterSpec, ...], raw: object) -> dict[str, Any]:
    """The request's answers, checked and normalized, defaults filled in.

    Refuses an answer to a question the source does not ask, so a client cannot
    smuggle a value a provider might read.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ParameterError("parameters must be an object")
    known = {spec.id for spec in declared}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ParameterError(f"this resource takes no parameter named {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for spec in declared:
        value = raw.get(spec.id)
        if value is None or value == "" or value == []:
            if spec.default is not None:
                out[spec.id] = spec.default
            elif spec.required:
                raise ParameterError(f"{spec.label} is required")
            continue
        out[spec.id] = _check(spec, value)
    return out


def _check(spec: ParameterSpec, value: object) -> Any:
    kind = spec.type
    if kind == "area":
        return _check_area(spec, value)
    if kind == "dateRange":
        return _check_dates(spec, value)
    if kind == "choice":
        allowed = {o.value for o in spec.options}
        if spec.multiple:
            if not isinstance(value, list) or not value:
                raise ParameterError(f"{spec.label} takes one or more of the listed choices")
            picked = sorted(dict.fromkeys(str(v) for v in value))
            bad = [v for v in picked if v not in allowed]
            if bad:
                raise ParameterError(f"{spec.label} does not offer {', '.join(bad)}")
            return picked
        if not isinstance(value, str) or value not in allowed:
            raise ParameterError(f"{spec.label} does not offer {value!r}")
        return value
    if kind in ("number", "integer"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ParameterError(f"{spec.label} takes a number")
        if kind == "integer":
            if float(value) != int(value):
                raise ParameterError(f"{spec.label} takes a whole number")
            value = int(value)
        if spec.minimum is not None and value < spec.minimum:
            raise ParameterError(f"{spec.label} is at least {_fmt(spec.minimum)}")
        if spec.maximum is not None and value > spec.maximum:
            raise ParameterError(f"{spec.label} is at most {_fmt(spec.maximum)}")
        return value if kind == "integer" else float(value)
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ParameterError(f"{spec.label} is yes or no")
        return value
    if kind == "text":
        if not isinstance(value, str):
            raise ParameterError(f"{spec.label} takes text")
        text = value.strip()
        if len(text) > MAX_TEXT_LENGTH:
            raise ParameterError(f"{spec.label} is at most {MAX_TEXT_LENGTH} characters")
        if spec.pattern and not re.fullmatch(spec.pattern, text):
            raise ParameterError(f"{spec.label} is not in the form this source accepts")
        return text
    if kind == "url":
        if not isinstance(value, str) or not value.strip().startswith("https://"):
            raise ParameterError(f"{spec.label} must be an https link")
        link = value.strip()
        if len(link) > MAX_URL_LENGTH or any(c.isspace() for c in link):
            raise ParameterError(f"{spec.label} is not a link")
        return link
    raise ParameterError(f"{spec.label} has an unknown type")  # pragma: no cover


def _fmt(number: float) -> str:
    return str(int(number)) if float(number).is_integer() else f"{number:g}"


def _check_area(spec: ParameterSpec, value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ParameterError(f"{spec.label} must be a box or named areas")
    if "box" in value and "names" in value:
        raise ParameterError(f"{spec.label} is a box or named areas, not both")
    if "box" in value:
        if "box" not in spec.accepts:
            raise ParameterError(f"{spec.label} is given by name for this source")
        box = value["box"]
        if (
            not isinstance(box, list) or len(box) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
        ):
            raise ParameterError(f"{spec.label} must be [west, south, east, north]")
        west, south, east, north = (round(float(v), BOX_DECIMALS) for v in box)
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ParameterError(f"{spec.label} is not a box on the map: west must be left of east and south below north")
        km2 = box_area_km2([west, south, east, north])
        if spec.max_area_km2 is not None and km2 > spec.max_area_km2:
            raise ParameterError(
                f"{spec.label} covers {km2:,.1f} km2; this source takes at most {_fmt(spec.max_area_km2)} km2"
            )
        label = value.get("label")
        out: dict[str, Any] = {"box": [west, south, east, north]}
        if isinstance(label, str) and label.strip():
            out["label"] = label.strip()[:MAX_NAME_LENGTH]
        return out
    if "names" in value:
        if "names" not in spec.accepts:
            raise ParameterError(f"{spec.label} is given as a box for this source")
        names = value["names"]
        if not isinstance(names, dict):
            raise ParameterError(f"{spec.label} names a place and the areas inside it")
        scope = _clean_name(names.get("geocodeArea"), spec, "place")
        areas = names.get("areas")
        if not isinstance(areas, list) or not areas or len(areas) > MAX_AREA_NAMES:
            raise ParameterError(f"{spec.label} lists 1 to {MAX_AREA_NAMES} areas")
        cleaned = sorted(dict.fromkeys(_clean_name(a, spec, "area") for a in areas))
        return {"names": {"geocodeArea": scope, "areas": cleaned}}
    raise ParameterError(f"{spec.label} must be a box or named areas")


def _clean_name(value: object, spec: ParameterSpec, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParameterError(f"{spec.label} needs a {what} name")
    name = value.strip()
    if len(name) > MAX_NAME_LENGTH or _NAME_FORBIDDEN.search(name):
        raise ParameterError(f"{spec.label}: {name[:40]!r} is not a {what} name OpenStreetMap uses")
    return name


def _check_dates(spec: ParameterSpec, value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ParameterError(f"{spec.label} takes a start and an end date")
    start, end = value.get("start"), value.get("end")
    out: dict[str, str] = {}
    for name, day in (("start", start), ("end", end)):
        if day in (None, ""):
            continue
        if not _is_date(day):
            raise ParameterError(f"{spec.label} takes dates like 2024-05-01")
        if spec.min_date and day < spec.min_date:
            raise ParameterError(f"{spec.label} starts no earlier than {spec.min_date}")
        if spec.max_date and day > spec.max_date:
            raise ParameterError(f"{spec.label} ends no later than {spec.max_date}")
        out[name] = day
    if not out:
        raise ParameterError(f"{spec.label} needs a start or an end date")
    if "start" in out and "end" in out and out["start"] > out["end"]:
        raise ParameterError(f"{spec.label} starts after it ends")
    return out


# ── geometry and identity ─────────────────────────────────────────────────


def box_area_km2(box: list[float]) -> float:
    """The area of a WGS84 box on a sphere, in square kilometres."""
    west, south, east, north = box
    lam = math.radians(east - west)
    return (_EARTH_RADIUS_KM ** 2) * lam * abs(math.sin(math.radians(north)) - math.sin(math.radians(south)))


def values_hash(values: dict[str, Any]) -> str:
    """A short, stable key for a set of answers, ignoring display-only labels."""
    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in sorted(value.items()) if k != "label"}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    canonical = json.dumps(strip(values), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def parameter_row(spec: ParameterSpec) -> dict[str, Any]:
    """What a client is told about one parameter: enough to draw its field."""
    row: dict[str, Any] = {
        "id": spec.id, "type": spec.type, "label": spec.label,
        "description": spec.description, "required": spec.required,
    }
    if spec.default is not None:
        row["default"] = spec.default
    for key, value in (("min", spec.minimum), ("max", spec.maximum), ("step", spec.step), ("unit", spec.unit),
                       ("minDate", spec.min_date), ("maxDate", spec.max_date)):
        if value is not None:
            row[key] = value
    if spec.type == "choice":
        row["options"] = [{"value": o.value, "label": o.label} for o in spec.options]
        row["multiple"] = spec.multiple
    if spec.type == "area":
        row["accepts"] = list(spec.accepts)
        if spec.max_area_km2 is not None:
            row["maxAreaKm2"] = spec.max_area_km2
    return row


def declaration_dict(spec: ParameterSpec) -> dict[str, Any]:
    """The declaration as a manifest writes it: the client's row plus ``pattern``."""
    out = parameter_row(spec)
    if spec.pattern:
        out["pattern"] = spec.pattern
    return out
