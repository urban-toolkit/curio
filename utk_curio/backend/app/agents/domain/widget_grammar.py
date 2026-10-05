"""The widgets an agent declares on a node (#662).

A node's widgets are named values the user sets in its Widgets tab; its code
places each one as a ``[!! name !!]`` reference, which a run replaces with the
value. They are stored at ``metadata.widgets``. An agent declares them on a
planned node (``dataflow.plan.write``) or a created one (``node.create``), and
each declaration is checked here, so a wrong one comes back to the model as an
error it can fix. A run would only drop it (``normalize_widgets``), and the
code's reference would then fail as naming no widget.

The shape is ``$defs.widget`` in ``docs/schemas/trill.v1.json`` (a test pins
these keys to it), and the rules are the Widgets tab's own: ``check_widget_def``
and ``check_widget_value``, the twins of ``checkWidgetDef`` and
``checkWidgetValue`` in ``widgetModel.ts``.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.execution.code_references import (
    check_widget_def,
    check_widget_value,
    default_value_for,
    normalize_widgets,
)

#: The keys a widget has, in the order a node stores them.
WIDGET_KEYS = ("name", "type", "label", "default", "value", "options")
#: The keys of a widget's options.
OPTION_KEYS = ("choices", "display", "min", "max", "step", "units")
#: How a choice widget is drawn.
CHOICE_DISPLAYS = ("dropdown", "radio")

#: Bounds on what one declaration may carry: abuse backstops, not product rules.
MAX_WIDGETS = 16
_TEXT_MAX_CHARS = 80
_VALUE_MAX_CHARS = 2000
_CHOICES_MAX = 50
_UNITS_MAX_CHARS = 16


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _size_problem(value: object, where: str) -> str | None:
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return f"{where} is not a JSON value"
    if len(text) > _VALUE_MAX_CHARS:
        return f"{where} is {len(text)} chars as JSON (max {_VALUE_MAX_CHARS})"
    return None


def _options_problems(options: object, where: str) -> list[str]:
    if not isinstance(options, dict):
        return [f"{where} must be an object"]
    problems = []
    unknown = sorted(set(options) - set(OPTION_KEYS))
    if unknown:
        problems.append(f"{where} has keys a widget's options do not: {', '.join(unknown)} "
                        f"(they are {', '.join(OPTION_KEYS)})")
    choices = options.get("choices")
    if choices is not None and (
        not isinstance(choices, list) or len(choices) > _CHOICES_MAX
        or not all(isinstance(c, str) and len(c) <= _TEXT_MAX_CHARS for c in choices)
    ):
        problems.append(f"{where}.choices must be a list of up to {_CHOICES_MAX} texts")
    if options.get("display") is not None and options["display"] not in CHOICE_DISPLAYS:
        problems.append(f"{where}.display must be one of {', '.join(CHOICE_DISPLAYS)}")
    for key in ("min", "max", "step"):
        if options.get(key) is not None and not _number(options[key]):
            problems.append(f"{where}.{key} must be a number")
    units = options.get("units")
    if units is not None and (not isinstance(units, str) or len(units) > _UNITS_MAX_CHARS):
        problems.append(f"{where}.units must be a text of up to {_UNITS_MAX_CHARS} chars")
    return problems


def _shape_problems(entry: object, where: str) -> list[str]:
    """What keeps *entry* from being read as a widget at all."""
    if not isinstance(entry, dict):
        return [f"{where} must be an object"]
    problems = []
    unknown = sorted(set(entry) - set(WIDGET_KEYS))
    if unknown:
        problems.append(f"{where} has keys a widget does not: {', '.join(unknown)} "
                        f"(a widget has {', '.join(WIDGET_KEYS)})")
    for key in ("name", "type"):
        if not isinstance(entry.get(key), str):
            problems.append(f"{where}.{key} must be a text")
    label = entry.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > _TEXT_MAX_CHARS):
        problems.append(f"{where}.label must be a text of up to {_TEXT_MAX_CHARS} chars")
    if entry.get("options") is not None:
        problems.extend(_options_problems(entry["options"], f"{where}.options"))
    for key in ("default", "value"):
        if key in entry:
            problem = _size_problem(entry[key], f"{where}.{key}")
            if problem:
                problems.append(problem)
    return problems


def value_problem(widget: dict, value: object, where: str) -> str | None:
    """Why *value* cannot be *widget*'s value, or None: as the Widgets tab
    judges a value the user sets."""
    problem = _size_problem(value, where)
    if problem:
        return problem
    message = check_widget_value(widget, value)
    return f"{where}: {message}" if message else None


def parse_widgets(raw: object, where: str) -> tuple[list[dict], list[str]]:
    """The widgets *raw* declares, as a node stores them (each with its kind's
    default when it gives none), and an error for each one the Widgets tab
    would not take. Absent means none."""
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{where} must be a list of widgets"]
    if len(raw) > MAX_WIDGETS:
        return [], [f"{where} has {len(raw)} widgets (max {MAX_WIDGETS})"]
    problems: list[str] = []
    kept: list[dict] = []
    for index, entry in enumerate(raw):
        here = f"{where}[{index}]"
        shape = _shape_problems(entry, here)
        if shape:
            problems.extend(shape)
            continue
        widget = {key: entry[key] for key in WIDGET_KEYS if entry.get(key) is not None}
        if "default" not in widget:
            widget["default"] = default_value_for(widget["type"], widget.get("options"))
        message = check_widget_def(widget, kept)
        if message is None and "value" in widget:
            message = check_widget_value(widget, widget["value"])
        if message:
            problems.append(f"{here} ({widget['name']!r}): {message}")
            continue
        kept.append(widget)
    if problems:
        return [], problems
    return normalize_widgets(kept), []


def with_values(widgets: list[dict], values: dict) -> list[dict]:
    """*widgets* with ``value`` set from *values* (name to value), as the
    Widgets tab sets a value; the others as they are."""
    return [{**w, "value": values[w["name"]]} if w["name"] in values else dict(w) for w in widgets]
