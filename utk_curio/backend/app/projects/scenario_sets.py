"""A dataflow's scenario sets, at ``dataflow.scenarioSets``.

A set groups the scenarios that answer one question: they are compared on the
same shared context and outcomes, and scenarios of different sets never mix.
Each set is ``{id, name, description?}``; a scenario names its set in ``set``.

A scenario also keeps its finalized ``context``, the nodes upstream of it it
uses, and ``outcomes``, the nodes downstream of it it feeds. Both are nodes
outside every scenario's box; a node in them can belong to some of a set's
scenarios and not others. :func:`infer_context_outcomes` is what Curio
proposes for them, which the person then edits.

* :func:`infer_context_outcomes` walks the edges up and down from a
  scenario's nodes, never into another scenario's box and never along an
  Interaction link.
* :func:`group_into_sets` puts scenarios that share a context or outcome
  node in one set.
* :func:`normalize_scenario_sets` is what a spec keeps: every scenario with a
  set, a context and outcomes. A scenario written without them (a spec from
  before sets) gets the inferred lists and a set grouped as above.

The twin of ``src/utils/scenarios/scenarioSets.ts``; both read
``scenarioSets.cases.json`` beside it.
"""
from __future__ import annotations

from typing import Iterable, Optional


def _is_interaction(edge: dict) -> bool:
    """A two-way link between views, which a run does not follow."""
    return edge.get("type") == "Interaction" or (
        edge.get("sourceHandle") == "in/out" and edge.get("targetHandle") == "in/out"
    )


def _walk(start: Iterable[str], step: dict[str, list[str]], boxed: set[str]) -> set[str]:
    seen: set[str] = set()
    frontier = list(start)
    while frontier:
        node_id = frontier.pop()
        for nxt in step.get(node_id, []):
            if nxt in boxed or nxt in seen:
                continue
            seen.add(nxt)
            frontier.append(nxt)
    return seen


def infer_context_outcomes(
    members: Iterable[str], node_ids: list[str], edges: list[dict], boxed: Iterable[str],
) -> dict:
    """``{"context", "outcomes"}`` for a scenario of *members*, in the order of
    *node_ids*: every node upstream of a member, and every node downstream of
    one, the walk stopping at any node in *boxed* (the nodes of every
    scenario's box, *members* among them)."""
    known = set(node_ids)
    inside = [m for m in members if m in known]
    boxed_set = set(boxed) | set(inside)
    up: dict[str, list[str]] = {}
    down: dict[str, list[str]] = {}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if _is_interaction(edge) or source not in known or target not in known:
            continue
        up.setdefault(target, []).append(source)
        down.setdefault(source, []).append(target)
    context = _walk(inside, up, boxed_set)
    outcomes = _walk(inside, down, boxed_set)
    return {
        "context": [n for n in node_ids if n in context],
        "outcomes": [n for n in node_ids if n in outcomes],
    }


def group_into_sets(scenarios: list[dict]) -> list[list[str]]:
    """The ids of *scenarios* in groups, each scenario with every other that
    shares a context or outcome node with it, directly or through others.
    Groups and their members keep the scenarios' order."""
    parent = {s["id"]: s["id"] for s in scenarios}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first_with: dict[str, str] = {}
    for s in scenarios:
        for node_id in list(s.get("context") or []) + list(s.get("outcomes") or []):
            if node_id in first_with:
                a, b = find(first_with[node_id]), find(s["id"])
                if a != b:
                    parent[b] = a
            else:
                first_with[node_id] = s["id"]
    groups: dict[str, list[str]] = {}
    for s in scenarios:
        groups.setdefault(find(s["id"]), []).append(s["id"])
    return list(groups.values())


def _sets(raw: object) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        set_id, name = entry.get("id"), entry.get("name")
        if not (isinstance(set_id, str) and set_id and isinstance(name, str) and name.strip()) or set_id in seen:
            continue
        seen.add(set_id)
        kept = {"id": set_id, "name": name}
        if isinstance(entry.get("description"), str) and entry["description"]:
            kept["description"] = entry["description"]
        shared = _shared(entry.get("shared"))
        if shared:
            kept["shared"] = shared
        out.append(kept)
    return out


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _shared(raw: object) -> dict:
    """How the set's shared context and outcomes are drawn: collapsed or not,
    and where the collapsed box sits. Only what is set and well formed."""
    out: dict = {}
    for kind in ("context", "outcomes"):
        entry = raw.get(kind) if isinstance(raw, dict) else None
        if not isinstance(entry, dict):
            continue
        kept: dict = {}
        if entry.get("collapsed") is True:
            kept["collapsed"] = True
        box = entry.get("box")
        if isinstance(box, dict) and _number(box.get("x")) and _number(box.get("y")):
            kept["box"] = {"x": box["x"], "y": box["y"]}
        if kept:
            out[kind] = kept
    return out


def _free_id(base: str, taken: set[str]) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    taken.add(candidate)
    return candidate


def normalize_scenario_sets(
    scenarios: list[dict], raw_sets: object, node_ids: list[str], edges: list[dict],
    dataflow_name: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """``(scenarios, sets)`` as a spec keeps them.

    *scenarios* are already normalized (``normalize_scenarios``). A scenario
    without a ``context`` or ``outcomes`` list gets the inferred one; the
    lists it has keep only nodes of the dataflow outside every box, in the
    dataflow's order. A scenario whose ``set`` is not one of *raw_sets* is
    grouped with the others like it (:func:`group_into_sets`) into a new set,
    named after the dataflow when it is the only one. A set no scenario names
    is dropped.
    """
    boxed = {n for s in scenarios for n in s.get("nodes") or []}
    known = set(node_ids)
    filled: list[dict] = []
    for s in scenarios:
        inferred = None
        out = dict(s)
        for key in ("context", "outcomes"):
            given = s.get(key)
            if isinstance(given, list):
                keep = {n for n in given if isinstance(n, str)}
                out[key] = [n for n in node_ids if n in keep and n not in boxed and n in known]
            else:
                if inferred is None:
                    inferred = infer_context_outcomes(s.get("nodes") or [], node_ids, edges, boxed)
                out[key] = inferred[key]
        filled.append(out)

    sets = _sets(raw_sets)
    set_ids = {x["id"] for x in sets}
    loose = [s for s in filled if s.get("set") not in set_ids]
    groups = group_into_sets(loose)
    taken = set(set_ids)
    names = {s["id"]: s["name"] for s in filled}
    only = len(groups) == 1 and not sets
    for group in groups:
        new_id = _free_id(f"set-{group[0]}", taken)
        if only and isinstance(dataflow_name, str) and dataflow_name.strip():
            name = dataflow_name.strip()
        else:
            name = " vs ".join(names[i] for i in group)
        sets.append({"id": new_id, "name": name})
        for s in filled:
            if s["id"] in group:
                s["set"] = new_id

    used = {s["set"] for s in filled}
    sets = [x for x in sets if x["id"] in used]
    ordered: list[dict] = []
    for s in filled:
        entry = {k: v for k, v in s.items() if k not in ("set", "context", "outcomes", "collapsed", "box", "source")}
        entry["set"] = s["set"]
        entry["context"] = s["context"]
        entry["outcomes"] = s["outcomes"]
        for k in ("collapsed", "box", "source"):
            if k in s:
                entry[k] = s[k]
        ordered.append(entry)
    return ordered, sets


def set_membership(scenarios: list[dict], set_id: str) -> dict:
    """For one set: ``{"scenarios": [ids], "context": {node: [ids]},
    "outcomes": {node: [ids]}}``, the scenario ids of a node in the set's
    order."""
    members = [s for s in scenarios if s.get("set") == set_id]
    out: dict = {"scenarios": [s["id"] for s in members], "context": {}, "outcomes": {}}
    for key in ("context", "outcomes"):
        for s in members:
            for node_id in s.get(key) or []:
                out[key].setdefault(node_id, []).append(s["id"])
    return out
