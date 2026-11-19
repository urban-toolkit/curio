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
them.

A new node starts with the widgets its template declares, and an agent sets
one by its name. What the agent wrote is kept as written (:func:`read_widgets`)
until the template is known, then set over the template's widget
(:func:`set_over`): the keys it gives over the template's, and the template's
for the rest, its default among them. The template's widget keeps its type and
the options that bound its value, a choice's choices and a number's or a
slider's minimum, maximum and step, and the value is judged against them
(:func:`template_problems`).
"""
from __future__ import annotations

import json
import math

from utk_curio.backend.app.execution.code_references import (
    CHOICE_KINDS,
    NUMERIC_KINDS,
    check_widget_def,
    check_widget_value,
    effective_value,
    js_number,
    normalize_widgets,
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


#: The options that bound a kind's value, which a template's widget keeps.
_BOUNDING = {
    **{kind: ("choices",) for kind in CHOICE_KINDS},
    **{kind: ("min", "max", "step") for kind in NUMERIC_KINDS},
}


def _options_of(widget: dict) -> dict:
    return widget["options"] if isinstance(widget.get("options"), dict) else {}


def _choices_of(widget: dict) -> list:
    """*widget*'s choices as the canvas reads them (``normalizeOptions`` in
    ``widgetModel.ts``): the texts of its options' list."""
    choices = _options_of(widget).get("choices")
    return [c for c in choices if isinstance(c, str)] if isinstance(choices, list) else []


def sets_by_name(entry: dict) -> bool:
    """Whether *entry*, a widget an agent declares on a new node, cannot stand
    as a widget of its own: a choice kind that gives no choices, or a slider
    that gives no minimum or no maximum. It sets the widget of its name that
    the node's template declares, whose options it keeps, which only the
    template knows (:func:`template_problems`)."""
    options = _options_of(entry)
    if entry.get("type") in CHOICE_KINDS:
        return "choices" not in options
    return entry.get("type") == "slider" and not ("min" in options and "max" in options)


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


def read_widgets(raw: object, where: str) -> tuple[list[dict], list[str]]:
    """The widgets *raw* declares, each as written (the keys a widget has,
    none filled in), and an error for each one the Widgets tab would not
    take. Absent means none. One that stands on its own is judged as the tab
    judges it, with its kind's default when it gives none; one that sets a
    template's widget by name (:func:`sets_by_name`) by its name and type, for
    :func:`template_problems` to judge against the template's widget."""
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
            problem = _declaration_problem(widget_with_default(given), kept, here)
        if problem:
            problems.append(problem)
            continue
        kept.append(given)
    if problems:
        return [], problems
    return kept, []


def parse_widgets(raw: object, where: str, declared: list[dict] = ()) -> tuple[list[dict], list[str]]:
    """The widgets a new node holds when *raw* declares its widgets and its
    template declares *declared*, as the node stores them (:func:`set_over`),
    and an error for each one the Widgets tab would not take
    (:func:`read_widgets`, :func:`template_problems`). Absent means none."""
    written, problems = read_widgets(raw, where)
    problems = problems or template_problems(written, declared, where)
    return ([], problems) if problems else (set_over(declared, written), [])


def _merged(template: dict, written: dict) -> dict:
    """*template* with the keys of *written* set over its own, its options'
    keys too."""
    merged = {**template, **written}
    options = {**_options_of(template), **_options_of(written)}
    if options:
        merged["options"] = options
    return merged


def set_over(declared: list[dict], written: list[dict]) -> list[dict]:
    """The widgets of a new node whose template declares *declared* and whose
    agent wrote *written* (:func:`read_widgets`): each of *declared* in its
    order, with the widget written by its name set over it (:func:`_merged`),
    then the written widgets of other names, each with its kind's default
    when it has none (``normalize_widgets``)."""
    names = {w["name"] for w in declared}
    by_name = {w["name"]: w for w in written}
    merged = [_merged(w, by_name[w["name"]]) if w["name"] in by_name else dict(w) for w in declared]
    return normalize_widgets(merged + [dict(w) for w in written if w["name"] not in names])


def _keeps_problem(written: dict, template: dict, here: str) -> str | None:
    """Why *written* would change what the node keeps of *template*, the
    template's widget of its name: its type and the options that bound its
    value (:data:`_BOUNDING`), each written only as the template gives it."""
    kind = template.get("type")
    mine, theirs = _options_of(written), _options_of(template)
    bounding = _BOUNDING.get(kind, ())
    if written.get("type") == kind and all(key not in mine or mine[key] == theirs.get(key) for key in bounding):
        return None
    if kind in CHOICE_KINDS:
        return agent_text.message(
            "widget.template-choices", where=here, widget=written["name"], kind=kind,
            choices=", ".join(_choices_of(template)),
        )
    if kind in NUMERIC_KINDS:
        bounds = ", ".join(f"{key} {js_number(theirs[key])}" for key in bounding if theirs.get(key) is not None)
        return agent_text.message(
            "widget.template-bounds", where=here, widget=written["name"], kind=kind, bounds=bounds or "none",
        )
    return agent_text.message("widget.template-type", where=here, widget=written["name"], kind=kind)


def template_problems(written: list[dict], declared: list[dict], where: str) -> list[str]:
    """Why *written*, the widgets an agent wrote on a new node
    (:func:`read_widgets`, at *where*), cannot be set over *declared*, the
    widgets its template declares, which the node starts with
    (:func:`set_over`). One of a name the template declares keeps the
    template's type and the options that bound its value
    (:func:`_keeps_problem`), and is judged as the node will hold it, the
    template's with the keys it gives set over it, so its value and its
    default must fit them. One that sets a template's widget by name
    (:func:`sets_by_name`) and names none is refused as the Widgets tab
    refuses it."""
    held = {w.get("name"): w for w in declared if isinstance(w, dict)}
    problems: list[str] = []
    for index, entry in enumerate(written):
        here = f"{where}[{index}]"
        template = held.get(entry["name"])
        if template is None:
            message = check_widget_def(widget_with_default(entry)) if sets_by_name(entry) else None
            if message:
                problems.append(f"{here} ({entry['name']!r}): {message}")
            continue
        problem = _keeps_problem(entry, template, here) or _declaration_problem(
            widget_with_default(_merged(template, entry)), [], here,
        )
        if problem:
            problems.append(problem)
    return problems


def with_values(widgets: list[dict], values: dict) -> list[dict]:
    """*widgets* with ``value`` set from *values* (name to value), as the
    Widgets tab sets a value; the others as they are."""
    return [{**w, "value": values[w["name"]]} if w["name"] in values else dict(w) for w in widgets]


def values_over(widgets: list[dict], values: dict) -> list[dict]:
    """*widgets*, a planned node's, with ``value`` set from *values*
    (:func:`with_values`), then ``{"name", "value"}`` for each name of
    *values* none of them has: a widget the node's template may declare, which
    the mint judges against it and :func:`set_over` sets over it."""
    names = {w["name"] for w in widgets}
    return with_values(widgets, values) + [{"name": n, "value": v} for n, v in values.items() if n not in names]


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
