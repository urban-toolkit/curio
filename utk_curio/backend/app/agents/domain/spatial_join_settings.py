"""The operation and output an agent sets on a Spatial Join node.

A Spatial Join keeps how input_0's shape must meet input_1's (its operation)
and what it emits (one row per pair, or input_1's rows with a count of their
pairs) at ``metadata.spatialJoin``. An agent sets them on a planned node
(``dataflow.plan.write``) or a created one (``node.create``), and each setting
is checked here, so a wrong one comes back to the model as an error it can
fix. The node itself would draw ``intersects`` and ``pairs`` in its place.

The shape is ``$defs.nodeMetadata.properties.spatialJoin`` in
``docs/schemas/trill.v1.json`` (a test pins these keys to it), and the rule is
the join's own, the one its route answers with (``common/spatial.settings_problem``).
Only a template whose ``behavior`` is the Spatial Join's keeps a setting: the
behavior ``packages.template_behavior`` reads, which the caller passes in.
"""
from __future__ import annotations

from utk_curio.backend.app.common import spatial

#: The behavior a Spatial Join template names.
BEHAVIOR = "spatial-join"
#: Where a node keeps the setting, in its ``metadata``, and the key a planned
#: node or a node.create gives it under.
KEY = "spatialJoin"
#: The keys the setting has, in the order a node stores them.
SETTING_KEYS = ("predicate", "output")


def parse(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The setting *raw* gives, as a node stores it, or the errors that say
    what the join would not take. Absent, or empty, sets nothing."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, [f'{where} must be an object, such as {{"predicate": "within", "output": "counts"}}']
    unknown = sorted(str(key) for key in set(raw) - set(SETTING_KEYS))
    if unknown:
        return None, [f"{where} has keys a Spatial Join does not: {', '.join(unknown)} "
                      f"(it has {', '.join(SETTING_KEYS)})"]
    problem = spatial.settings_problem(
        raw.get("predicate", spatial.DEFAULT_PREDICATE), raw.get("output", spatial.DEFAULT_OUTPUT),
    )
    if problem:
        return None, [f"{where}: {problem}"]
    setting = {key: raw[key] for key in SETTING_KEYS if key in raw}
    return (setting or None), []


def template_problem(behavior: object, label: object, where: str) -> str | None:
    """Why a node whose template names *behavior* keeps no setting, or None."""
    if behavior == BEHAVIOR:
        return None
    return f"{where}: a {label or 'this'} node has no operation or output; only a Spatial Join node takes {KEY}"


def plan_problems(nodes: list, entries: list, behavior_of) -> list[str]:
    """For each planned node that sets one, why its template keeps no setting:
    *entries* are the roster rows the mint resolved, in the nodes' order, and
    *behavior_of* gives a node type's behavior."""
    problems = []
    for node, entry in zip(nodes, entries):
        if not node.get(KEY):
            continue
        label = (entry or {}).get("label") or node["nodeType"]
        problem = template_problem(behavior_of(node["nodeType"]), label, f"plan node {node['ref']!r}")
        if problem:
            problems.append(problem)
    return problems


def describe(setting: dict | None) -> str:
    """The setting as a review card reads it: ``operation within, output counts``."""
    words = {"predicate": "operation", "output": "output"}
    return ", ".join(f"{words[key]} {setting[key]}" for key in SETTING_KEYS if key in (setting or {}))
