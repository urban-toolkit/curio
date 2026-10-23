"""The widgets an agent declares on a node (#662).

A node's widgets are named values the user sets in its Widgets tab; its code
places each one as a ``[!! name !!]`` reference, which a run replaces with the
value. They are stored at ``metadata.widgets``. An agent declares them on a
planned node (``dataflow.plan.write``) or a created one (``node.create``), and
each declaration is checked here, so a wrong one comes back to the model as an
error it can fix. It changes the values of a node already on the canvas
(``node.settings.write``) by name, each checked as the Widgets tab checks a
value the user sets (:func:`parse_values`). A run would only drop it (``normalize_widgets``), and the
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
    effective_value,
    normalize_widgets,
    widget_with_default,
)
from utk_curio.backend.app.agents.domain import agent_text

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
        return agent_text.message("widget.value-not-json", where=where)
    if len(text) > _VALUE_MAX_CHARS:
        return agent_text.message(
            "widget.value-too-long", where=where, count=len(text), value_max_chars=_VALUE_MAX_CHARS,
        )
    return None


def _options_problems(options: object, where: str) -> list[str]:
    if not isinstance(options, dict):
        return [agent_text.message("widget.options-not-object", where=where)]
    problems = []
    unknown = sorted(set(options) - set(OPTION_KEYS))
    if unknown:
        problems.append(agent_text.message(
            "widget.options-unknown-keys", where=where, unknown=', '.join(unknown), option_keys=', '.join(OPTION_KEYS),
        ))
    choices = options.get("choices")
    if choices is not None and (
        not isinstance(choices, list) or len(choices) > _CHOICES_MAX
        or not all(isinstance(c, str) and len(c) <= _TEXT_MAX_CHARS for c in choices)
    ):
        problems.append(agent_text.message("widget.choices-shape", where=where, choices_max=_CHOICES_MAX))
    if options.get("display") is not None and options["display"] not in CHOICE_DISPLAYS:
        problems.append(agent_text.message(
            "widget.display-choice", where=where, choice_displays=', '.join(CHOICE_DISPLAYS),
        ))
    for key in ("min", "max", "step"):
        if options.get(key) is not None and not _number(options[key]):
            problems.append(agent_text.message("widget.option-not-number", where=where, key=key))
    units = options.get("units")
    if units is not None and (not isinstance(units, str) or len(units) > _UNITS_MAX_CHARS):
        problems.append(agent_text.message("widget.units-shape", where=where, units_max_chars=_UNITS_MAX_CHARS))
    return problems


def _shape_problems(entry: object, where: str) -> list[str]:
    """What keeps *entry* from being read as a widget at all."""
    if not isinstance(entry, dict):
        return [agent_text.message("widget.not-object", where=where)]
    problems = []
    unknown = sorted(set(entry) - set(WIDGET_KEYS))
    if unknown:
        problems.append(agent_text.message(
            "widget.unknown-keys", where=where, unknown=', '.join(unknown), widget_keys=', '.join(WIDGET_KEYS),
        ))
    for key in ("name", "type"):
        if not isinstance(entry.get(key), str):
            problems.append(agent_text.message("widget.field-not-text", where=where, key=key))
    label = entry.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > _TEXT_MAX_CHARS):
        problems.append(agent_text.message("widget.label-shape", where=where, text_max_chars=_TEXT_MAX_CHARS))
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
        return [], [agent_text.message("widget.not-list", where=where)]
    if len(raw) > MAX_WIDGETS:
        return [], [agent_text.message("widget.too-many", where=where, count=len(raw), max_widgets=MAX_WIDGETS)]
    problems: list[str] = []
    kept: list[dict] = []
    for index, entry in enumerate(raw):
        here = f"{where}[{index}]"
        shape = _shape_problems(entry, here)
        if shape:
            problems.extend(shape)
            continue
        widget = widget_with_default({key: entry[key] for key in WIDGET_KEYS if entry.get(key) is not None})
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


def parse_values(raw: object, widgets: list[dict], where: str, label: object) -> tuple[dict | None, list[str]]:
    """The new values *raw* (``node.settings.write``'s ``widgets``, a widget's
    name to its value) gives a node on the canvas whose widgets are *widgets*
    (its ``metadata.widgets``, as ``normalize_widgets`` reads them), or an
    error for each name the node has no widget by and each value its widget
    would not take, in the Widgets tab's words (:func:`value_problem`);
    *label* names the node. Absent changes nothing."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict) or not raw:
        return None, [agent_text.message("node-settings.widgets-not-map", where=where)]
    held = {widget["name"]: widget for widget in widgets}
    problems: list[str] = []
    for name, value in raw.items():
        here = f"{where}.{name}"
        if name not in held:
            problems.append(agent_text.message(
                "node-settings.unknown-widget", where=here, label=label, widget=repr(name),
                widgets=", ".join(held) or "none",
            ))
            continue
        problem = value_problem(held[name], value, here)
        if problem:
            problems.append(problem)
    return (None, problems) if problems else (dict(raw), [])


def changes_anything(widgets: list[dict], values: dict) -> bool:
    """Whether *values* gives any of *widgets* a value it does not hold now
    (its ``value``, else its ``default``)."""
    held = {widget["name"]: widget for widget in widgets}
    return any(name in held and effective_value(held[name]) != value for name, value in values.items())


def describe_value(widget: dict, value: object) -> str:
    """*value* as a review card reads it, beside the words the widget's row
    in its Widgets tab shows, its label or else its name: ``Combine: max``. A
    text reads as it is, any other value as JSON."""
    shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"{widget.get('label') or widget['name']}: {shown}"
