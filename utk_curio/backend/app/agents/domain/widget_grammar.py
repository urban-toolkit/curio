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
``checkWidgetValue`` in ``widgetModel.ts``. A value a choice widget does not
offer, wherever an agent writes one, is refused naming the widget and its
choices (:func:`choice_problem`), which the model cannot see as the tab shows
them. A widget the node's template declares is judged as the node will hold
it, the template's with the agent's keys set over it, and a choice keeps the
template's choices (:func:`template_problems`).
"""
from __future__ import annotations

import json
import math

from utk_curio.backend.app.execution.code_references import (
    CHOICE_KINDS,
    check_widget_def,
    check_widget_value,
    effective_value,
    widget_name_or_type_problem,
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
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and not (isinstance(value, float) and math.isnan(value))
    )


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


def _choices_of(widget: dict) -> list:
    """*widget*'s choices as the canvas reads them (``normalizeOptions`` in
    ``widgetModel.ts``): the texts of its options' list."""
    options = widget.get("options") if isinstance(widget.get("options"), dict) else {}
    choices = options.get("choices")
    return [c for c in choices if isinstance(c, str)] if isinstance(choices, list) else []


def sets_by_name(entry: dict) -> bool:
    """Whether *entry*, a widget an agent declares on a new node, is of a
    choice kind and gives no choices: it sets the widget of its name that the
    node's template declares, whose choices it keeps, which only the template
    knows (:func:`template_problems`)."""
    options = entry.get("options")
    return entry.get("type") in CHOICE_KINDS and not (isinstance(options, dict) and "choices" in options)


def choice_problem(widget: dict, value: object, where: str) -> str | None:
    """Why *value*, written at *where*, is not the value of *widget*, a choice
    that offers choices, naming the widget and its choices; None when it is one
    of them or *widget* is no such choice."""
    choices = _choices_of(widget)
    if widget.get("type") != "choice" or not choices or (isinstance(value, str) and value in choices):
        return None
    return agent_text.message(
        "widget.not-a-choice", where=where, widget=widget.get("name"), choices=", ".join(choices),
        value=json.dumps(value, ensure_ascii=False, default=str),
    )


def value_problem(widget: dict, value: object, where: str) -> str | None:
    """Why *value* cannot be *widget*'s value, or None: as the Widgets tab
    judges a value the user sets, a choice's naming its choices."""
    problem = _size_problem(value, where) or choice_problem(widget, value, where)
    if problem:
        return problem
    message = check_widget_value(widget, value)
    return f"{where}: {message}" if message else None


def _declaration_problem(widget: dict, others: list[dict], here: str) -> str | None:
    """What the Widgets tab refuses in *widget*, a whole declaration at *here*
    beside the node's *others*, its value among it: a choice's default or value
    outside its choices named with them (:func:`choice_problem`), anything else
    in the tab's words."""
    message = check_widget_def(widget, others)
    if message is None and "value" in widget:
        message = check_widget_value(widget, widget["value"])
    if message is None:
        return None
    for key in ("default", "value"):
        if key in widget and message == check_widget_value(widget, widget[key]):
            named = choice_problem(widget, widget[key], f"{here}.{key}")
            if named:
                return named
    return f"{here} ({widget['name']!r}): {message}"


def parse_widgets(raw: object, where: str) -> tuple[list[dict], list[str]]:
    """The widgets *raw* declares, as a node stores them (each with its kind's
    default when it gives none), and an error for each one the Widgets tab
    would not take. Absent means none. A choice that gives no choices
    (:func:`sets_by_name`) is kept as written, for :func:`template_problems`
    to judge against the template's widget of its name."""
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
        given = {key: entry[key] for key in WIDGET_KEYS if entry.get(key) is not None}
        if sets_by_name(given):
            message = widget_name_or_type_problem(given, kept)
            problem = f"{here} ({given['name']!r}): {message}" if message else None
        else:
            given = widget_with_default(given)
            problem = _declaration_problem(given, kept, here)
        if problem:
            problems.append(problem)
            continue
        kept.append(given)
    if problems:
        return [], problems
    return kept, []


def template_problems(widgets: list[dict], declared: list[dict], where: str) -> list[str]:
    """Why *widgets*, the widgets an agent declares on a new node
    (:func:`parse_widgets`, at *where*), cannot be set over *declared*, the
    widgets its template declares, which the node starts with
    (``plan_scenarios._set_over``). The template's choice keeps its type and
    its choices: one of its name is judged as the node will hold it, the
    template's with the keys it gives set over it, so its value and its
    default must be among those choices. A choice that gives no choices is
    judged so over any other widget of its name, and refused as the Widgets
    tab refuses it when the template declares none."""
    held = {w.get("name"): w for w in declared if isinstance(w, dict)}
    problems: list[str] = []
    for index, entry in enumerate(widgets):
        here = f"{where}[{index}]"
        template = held.get(entry["name"])
        if template is None:
            message = check_widget_def(widget_with_default(entry)) if sets_by_name(entry) else None
            if message:
                problems.append(f"{here} ({entry['name']!r}): {message}")
            continue
        if template.get("type") in CHOICE_KINDS and (
            entry["type"] != template["type"]
            or (not sets_by_name(entry) and _choices_of(entry) != _choices_of(template))
        ):
            problems.append(agent_text.message(
                "widget.template-choices", where=here, widget=entry["name"], kind=template["type"],
                choices=", ".join(_choices_of(template)),
            ))
            continue
        if template.get("type") not in CHOICE_KINDS and not sets_by_name(entry):
            # A whole declaration over any other widget: parse_widgets judged it.
            continue
        problem = _declaration_problem(widget_with_default({**template, **entry}), [], here)
        if problem:
            problems.append(problem)
    return problems


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
    """*value* as a change card reads it, beside the words the widget's row
    in its Widgets tab shows, its label or else its name: ``Combine: max``. A
    text reads as it is, any other value as JSON."""
    shown = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return f"{widget.get('label') or widget['name']}: {shown}"
