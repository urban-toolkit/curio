"""A dataflow's scenarios (#662), at ``dataflow.scenarios``.

A scenario is a named selection of the dataflow's nodes. Each one is
``{id, name, color, description?, nodes, collapsed?, box?, source?}``, and a
node belongs to at most one.

* :func:`scenario_conflicts` is what a writer may not send: a node in two
  scenarios, or two scenarios with one id. A save that sends either is refused.
* :func:`scenario_problems` adds a member that is not a node of the dataflow.
  A save drops those (a deleted node leaves its scenario); a committed spec may
  not have them.
* :func:`normalize_scenarios` is what a spec keeps, and the twin of
  ``normalizeScenarios`` in ``src/utils/scenarios/scenarioModel.ts``. Both read
  ``scenarios.cases.json`` beside it.

A scenario whose last node was deleted keeps its name and color, with no
members, until it is deleted itself.
"""
from __future__ import annotations

import re
from typing import Iterable

#: A scenario's color: a CSS hex color. Kept in sync with
#: ``$defs.scenario.properties.color`` in ``docs/schemas/trill.v1.json``.
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

#: The colors new scenarios take in turn. Kept in sync with ``SCENARIO_COLORS``
#: in ``src/utils/scenarios/scenarioEdits.ts``, which a test reads.
SCENARIO_COLORS = (
    "#3567c7",
    "#e86a3c",
    "#2f8f4a",
    "#7a4bd1",
    "#c0392b",
    "#2e6874",
    "#996300",
    "#a3417a",
)


def next_scenario_color(colors: Iterable[str]) -> str:
    """The first of ``SCENARIO_COLORS`` none of *colors* is, or the next one
    round; ``nextScenarioColor`` in ``scenarioEdits.ts``."""
    worn = [str(c) for c in colors]
    taken = {c.lower() for c in worn}
    for color in SCENARIO_COLORS:
        if color not in taken:
            return color
    return SCENARIO_COLORS[len(worn) % len(SCENARIO_COLORS)]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _well_formed(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), str) and bool(entry["id"])
        and isinstance(entry.get("name"), str) and bool(entry["name"].strip())
        and isinstance(entry.get("color"), str) and bool(COLOR_RE.match(entry["color"]))
    )


def _members(entry: dict) -> list[str]:
    raw = entry.get("nodes")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for node_id in raw:
        if isinstance(node_id, str) and node_id and node_id not in out:
            out.append(node_id)
    return out


def _node_ids(spec: object) -> set[str]:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    nodes = dataflow.get("nodes") if isinstance(dataflow, dict) else None
    return {n["id"] for n in nodes or [] if isinstance(n, dict) and isinstance(n.get("id"), str)}


def _raw_scenarios(spec: object) -> list:
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    raw = dataflow.get("scenarios") if isinstance(dataflow, dict) else None
    return raw if isinstance(raw, list) else []


def scenario_conflicts(spec: object) -> list[str]:
    """What no writer may send in ``dataflow.scenarios``: a node in two
    scenarios, or two scenarios with one id. One message each."""
    problems: list[str] = []
    owner: dict[str, str] = {}
    seen_ids: set[str] = set()
    for entry in _raw_scenarios(spec):
        if not _well_formed(entry):
            continue
        if entry["id"] in seen_ids:
            problems.append(f"Two scenarios have the id {entry['id']}.")
            continue
        seen_ids.add(entry["id"])
        for node_id in _members(entry):
            if node_id in owner:
                problems.append(
                    f"Node {node_id} is in two scenarios, {owner[node_id]} and {entry['name']}. "
                    "A node belongs to at most one scenario."
                )
            else:
                owner[node_id] = entry["name"]
    return problems


def scenario_problems(spec: object) -> list[str]:
    """:func:`scenario_conflicts`, and each member that is not a node of the
    dataflow."""
    problems = scenario_conflicts(spec)
    nodes = _node_ids(spec)
    for entry in _raw_scenarios(spec):
        if not _well_formed(entry):
            continue
        for node_id in _members(entry):
            if node_id not in nodes:
                problems.append(f"Scenario {entry['name']} names node {node_id}, which the dataflow does not have.")
    return problems


def normalize_scenarios(raw: object, node_ids: Iterable[str]) -> list[dict]:
    """The scenarios in *raw* as a spec keeps them.

    An entry without an id, a name or a color is dropped, and so is a second
    entry with the same id. Members are kept once each, only when *node_ids*
    has them, and only in the first scenario that names them. Optional fields
    are kept when well formed.
    """
    nodes = set(node_ids)
    out: list[dict] = []
    seen_ids: set[str] = set()
    claimed: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not _well_formed(entry) or entry["id"] in seen_ids:
            continue
        seen_ids.add(entry["id"])
        members = [n for n in _members(entry) if n in nodes and n not in claimed]
        claimed.update(members)
        scenario: dict = {"id": entry["id"], "name": entry["name"], "color": entry["color"]}
        if isinstance(entry.get("description"), str) and entry["description"]:
            scenario["description"] = entry["description"]
        scenario["nodes"] = members
        if isinstance(entry.get("collapsed"), bool):
            scenario["collapsed"] = entry["collapsed"]
        box = entry.get("box")
        if isinstance(box, dict) and _is_number(box.get("x")) and _is_number(box.get("y")):
            scenario["box"] = {"x": box["x"], "y": box["y"]}
        source = entry.get("source")
        if (
            isinstance(source, dict)
            and isinstance(source.get("project"), str) and source["project"]
            and isinstance(source.get("scenario"), str) and source["scenario"]
        ):
            scenario["source"] = {"project": source["project"], "scenario": source["scenario"]}
        out.append(scenario)
    return out


def normalize_spec_scenarios(spec: object) -> None:
    """Clean ``dataflow.scenarios`` in place, against the spec's own nodes; an
    empty list is dropped, so a dataflow without scenarios has no key."""
    dataflow = spec.get("dataflow") if isinstance(spec, dict) else None
    if not isinstance(dataflow, dict) or "scenarios" not in dataflow:
        return
    kept = normalize_scenarios(dataflow["scenarios"], _node_ids(spec))
    if kept:
        dataflow["scenarios"] = kept
    else:
        del dataflow["scenarios"]


def carry_scenarios(new_spec: object, old_spec: object) -> None:
    """A spec written without ``dataflow.scenarios`` keeps the on-disk ones,
    as hand categories are kept: only the canvas writes the key, and an empty
    list from it clears them."""
    new_df = new_spec.get("dataflow") if isinstance(new_spec, dict) else None
    old_df = old_spec.get("dataflow") if isinstance(old_spec, dict) else None
    if not isinstance(new_df, dict) or not isinstance(old_df, dict):
        return
    if "scenarios" not in new_df and "scenarios" in old_df:
        new_df["scenarios"] = old_df["scenarios"]


def scenario_summaries(spec: object) -> list[dict]:
    """The scenarios a project summary lists: each one's id, name, color,
    description and members."""
    keep = ("id", "name", "color", "description", "nodes")
    return [
        {k: s[k] for k in keep if k in s}
        for s in normalize_scenarios(_raw_scenarios(spec), _node_ids(spec))
    ]
