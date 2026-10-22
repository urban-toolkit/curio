"""The scenarios part of a Dataflow Builder plan (#662).

A scenario is a named selection of a dataflow's nodes (``dataflow.scenarios``).
A plan's ``scenarios`` list holds two kinds of entry:

* a **selection**, ``{"name", "nodes"}``: its nodes are refs of this plan or
  ids of nodes already in the dataflow;
* a **duplicate**, ``{"name", "duplicateOf", "copies", "values"?}``: a copy of
  a scenario earlier in the list, made the way the canvas's Duplicate as
  scenario makes one (``scenario_catalog.domain.duplicate``). Each node of
  that scenario is copied as a plan node of its own, under the ref ``copies``
  names for it; the edges between those nodes are copied, and every edge
  entering them is wired into the copy too, so both scenarios read the same
  context. ``values`` sets a copy's widget values, keyed by the copy's ref.
  A duplicate copies the nodes this plan adds; a node already on the canvas
  is duplicated on the canvas.

Either kind may carry a ``color`` and a ``description``. A node belongs to one
scenario at most. Parsing expands each duplicate into the plan, so the review
card names every node and connection it adds, and each copy carries
``copyOf``, the ref it was copied from, which the apply records at
``metadata.copiedFrom``.
"""
from __future__ import annotations

import re
from collections import deque
from itertools import count
from typing import Callable

from utk_curio.backend.app.agents.domain.widget_grammar import value_problem, with_values
from utk_curio.backend.app.agents.domain import agent_text

SCENARIOS_MAX = 16
NAME_MAX_CHARS = 60
DESCRIPTION_MAX_CHARS = 300
#: A member is a plan ref or an existing node's id.
_MEMBER_MAX_CHARS = 64
_MEMBERS_MAX = 200
#: The keys an entry may carry.
SCENARIO_KEYS = ("name", "nodes", "duplicateOf", "copies", "values", "description", "color")
#: A scenario's color. ``COLOR_RE`` in ``projects/scenarios.py`` (a test keeps
#: them equal; that package is not imported here, which would pull in Flask).
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

FieldError = Callable[[str, object, int], "str | None"]


def _members(entry: dict, where: str, removed: set, owner: dict,
             field_error: FieldError) -> tuple[list[str], list[str]]:
    """A selection's members, or the errors that stop it."""
    raw = entry.get("nodes")
    if not isinstance(raw, list) or not raw:
        return [], [agent_text.message("scenario.nodes-missing", where=where)]
    if len(raw) > _MEMBERS_MAX:
        return [], [agent_text.message("scenario.too-many-nodes", where=where, count=len(raw), members_max=_MEMBERS_MAX)]
    errors: list[str] = []
    members: list[str] = []
    for index, value in enumerate(raw):
        here = f"{where}.nodes[{index}]"
        err = field_error(here, value, _MEMBER_MAX_CHARS)
        if err:
            errors.append(err)
            continue
        member = str(value).strip()
        if member in removed:
            errors.append(agent_text.message("scenario.member-removed", here=here, member=repr(member)))
        elif member in owner:
            errors.append(agent_text.message(
                "scenario.member-taken", here=here, member=repr(member), owner=repr(owner[member]),
            ))
        elif member not in members:
            members.append(member)
    return members, errors


def _copy_refs(entry: dict, where: str, source: dict, refs: set,
               field_error: FieldError, ref_max: int) -> tuple[dict, list[str]]:
    """Each node of the duplicated scenario to its copy's ref, or the errors."""
    copies = entry.get("copies")
    if not isinstance(copies, dict):
        skeleton = "{" + ", ".join(f'"{m}": "<new ref>"' for m in source["nodes"]) + "}"
        return {}, [agent_text.message(
            "scenario.copies-missing", where=where, name=repr(source['name']), skeleton=skeleton,
        )]
    errors = []
    missing = [m for m in source["nodes"] if m not in copies]
    extra = [k for k in copies if k not in source["nodes"]]
    if missing:
        errors.append(agent_text.message(
            "scenario.copies-incomplete", where=where, missing=', '.join(repr(m) for m in missing),
        ))
    if extra:
        errors.append(agent_text.message(
            "scenario.copies-extra", where=where, extra=', '.join(repr(k) for k in extra), name=repr(source['name']),
        ))
    taken: set[str] = set()
    out: dict[str, str] = {}
    for original in source["nodes"]:
        if original not in copies:
            continue
        here = f"{where}.copies.{original}"
        err = field_error(here, copies[original], ref_max)
        if err:
            errors.append(err)
            continue
        ref = str(copies[original]).strip()
        if ref in refs or ref in taken:
            errors.append(agent_text.message("scenario.copy-ref-taken", here=here, ref=repr(ref)))
            continue
        taken.add(ref)
        out[original] = ref
    return out, errors


def _value_errors(entry: dict, where: str, copies: dict, nodes_by_ref: dict) -> list[str]:
    """Why ``values`` cannot be set on the copies, or nothing."""
    values = entry.get("values")
    if values is None:
        return []
    if not isinstance(values, dict):
        return [agent_text.message("scenario.values-not-map", where=where)]
    original_of = {copy: original for original, copy in copies.items()}
    errors = []
    for ref, chosen in values.items():
        here = f"{where}.values.{ref}"
        if ref not in original_of:
            errors.append(agent_text.message(
                "scenario.values-not-a-copy", here=here, ref=repr(ref),
                original_of=', '.join(repr(c) for c in original_of) or 'none',
            ))
            continue
        if not isinstance(chosen, dict) or not chosen:
            errors.append(agent_text.message("scenario.values-not-widget-map", here=here))
            continue
        widgets = {w["name"]: w for w in nodes_by_ref[original_of[ref]].get("widgets") or []}
        for name, value in chosen.items():
            if name not in widgets:
                errors.append(agent_text.message(
                    "scenario.values-unknown-widget", here=here, name=name, widget=repr(name),
                    widgets_it_has=" " + agent_text.message(
                        "scenario.values-widgets-it-has", widgets=', '.join(widgets),
                    ) if widgets else "",
                ))
                continue
            problem = value_problem(widgets[name], value, f"{here}.{name}")
            if problem:
                errors.append(problem)
    return errors


def _expand(plan: dict, copies: dict, values: dict) -> None:
    """Add the copies (*copies*: each node to its copy's ref) and their edges
    to *plan*, by the canvas's own rule."""
    from utk_curio.backend.app.scenario_catalog.domain.duplicate import duplicate_selection

    nodes_by_ref = {n["ref"]: n for n in plan["nodes"]}
    order = [n["ref"] for n in plan["nodes"] if n["ref"] in copies]
    pending = deque(copies[ref] for ref in order)
    edge_number = count(1)

    def new_id() -> str:
        # Asked for the copied nodes first, in dataflow order, then per edge.
        return pending.popleft() if pending else f"copied-edge-{next(edge_number)}"

    spec_edges = []
    for index, edge in enumerate(plan["edges"]):
        spec_edge = {"id": f"plan-edge-{index}", "planEdge": index, "source": edge["from"], "target": edge["to"]}
        if edge.get("kind") == "interaction":
            spec_edge["type"] = "Interaction"
        spec_edges.append(spec_edge)
    duplicate = duplicate_selection(
        [{"id": ref} for ref in nodes_by_ref], spec_edges, order, new_id=new_id,
    )
    for ref in order:
        twin = {**nodes_by_ref[ref], "ref": copies[ref], "copyOf": ref}
        if twin.get("widgets"):
            twin["widgets"] = with_values(twin["widgets"], values.get(copies[ref]) or {})
        plan["nodes"].append(twin)
    present = {(e["from"], e["to"], e.get("kind", "data")) for e in plan["edges"]}
    for spec_edge in duplicate["edges"]:
        original = plan["edges"][spec_edge["planEdge"]]
        edge = {"from": spec_edge["source"], "to": spec_edge["target"]}
        if original.get("toHandle"):
            edge["toHandle"] = original["toHandle"]
        if original.get("kind"):
            edge["kind"] = original["kind"]
        key = (edge["from"], edge["to"], edge.get("kind", "data"))
        if key not in present:
            # An edge the plan already names into a copy is not added twice.
            present.add(key)
            plan["edges"].append(edge)


def _duplicate(entry: dict, where: str, plan: dict, by_name: dict, field_error: FieldError,
               ref_max: int) -> tuple[list[str], dict, list[str]]:
    """A duplicate's members (the copies' refs), the scenario it copies and
    the values it sets, or the errors that stop it; the copies join *plan*."""
    err = field_error(f"{where}.duplicateOf", entry.get("duplicateOf"), NAME_MAX_CHARS)
    if err:
        return [], {}, [err]
    source_name = str(entry["duplicateOf"]).strip()
    source = by_name.get(source_name)
    if source is None:
        return [], {}, [agent_text.message("scenario.duplicate-unknown", where=where, source_name=repr(source_name))]
    refs = {n["ref"] for n in plan["nodes"]}
    outside = [m for m in source["nodes"] if m not in refs]
    if outside:
        return [], {}, [agent_text.message(
            "scenario.duplicate-outside-plan", where=where, source_name=repr(source_name), outside=repr(outside[0]),
        )]
    copies, errors = _copy_refs(entry, where, source, refs, field_error, ref_max)
    if errors:
        return [], {}, errors
    errors = _value_errors(entry, where, copies, {n["ref"]: n for n in plan["nodes"]})
    if errors:
        return [], {}, errors
    values = dict(entry.get("values") or {})
    _expand(plan, copies, values)
    return [copies[m] for m in source["nodes"]], values, []


def parse_scenarios(raw: object, plan: dict, removed: set, field_error: FieldError,
                    ref_max: int) -> list[str]:
    """Read *raw*, a plan's ``scenarios``, into ``plan["scenarios"]`` (absent
    when there are none), expanding each duplicate into *plan*'s nodes and
    edges. Returns the errors; on any, *plan* is not to be used."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [agent_text.message("scenario.not-list")]
    if len(raw) > SCENARIOS_MAX:
        return [agent_text.message("scenario.too-many", count=len(raw), scenarios_max=SCENARIOS_MAX)]
    errors: list[str] = []
    kept: list[dict] = []
    by_name: dict[str, dict] = {}
    owner: dict[str, str] = {}
    for index, entry in enumerate(raw):
        where = f"scenarios[{index}]"
        if not isinstance(entry, dict):
            errors.append(agent_text.message("scenario.not-object", where=where))
            continue
        unknown = sorted(set(entry) - set(SCENARIO_KEYS))
        if unknown:
            errors.append(agent_text.message(
                "scenario.unknown-keys", where=where, unknown=', '.join(unknown),
                scenario_keys=', '.join(SCENARIO_KEYS),
            ))
            continue
        err = field_error(f"{where}.name", entry.get("name"), NAME_MAX_CHARS)
        if err:
            errors.append(err)
            continue
        name = str(entry["name"]).strip()
        if name in by_name:
            errors.append(agent_text.message("scenario.name-taken", where=where, name=repr(name)))
            continue
        if (entry.get("nodes") is None) == (entry.get("duplicateOf") is None):
            errors.append(agent_text.message("scenario.selection-or-duplicate", where=where))
            continue
        stored: dict = {"name": name}
        if entry.get("color") is not None:
            if not isinstance(entry["color"], str) or not COLOR_RE.match(entry["color"]):
                errors.append(agent_text.message("scenario.color-format", where=where, color=repr(entry['color'])))
                continue
            stored["color"] = entry["color"]
        if entry.get("description") is not None:
            err = field_error(f"{where}.description", entry["description"], DESCRIPTION_MAX_CHARS)
            if err:
                errors.append(err)
                continue
            stored["description"] = str(entry["description"]).strip()
        if entry.get("nodes") is not None:
            members, found = _members(entry, where, removed, owner, field_error)
        elif entry.get("copies") is None and entry.get("values") is not None:
            members, found = [], [agent_text.message("scenario.values-need-copies", where=where)]
        else:
            members, values, found = _duplicate(entry, where, plan, by_name, field_error, ref_max)
            if not found:
                stored["duplicateOf"] = str(entry["duplicateOf"]).strip()
                if values:
                    stored["values"] = values
        if found:
            errors.extend(found)
            continue
        for member in members:
            owner[member] = name
        stored["nodes"] = members
        kept.append(stored)
        by_name[name] = stored
    if errors:
        return errors
    if kept:
        plan["scenarios"] = kept
    return []
