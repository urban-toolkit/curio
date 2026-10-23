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
behavior ``packages.template_behavior`` reads, which the caller passes in. An
agent changes a join already on the canvas (``node.settings.write``) by the
same rule, each key it gives picked as the join's select picks it
(``parse_change``, ``after``).
"""
from __future__ import annotations

from utk_curio.backend.app.common import spatial
from utk_curio.backend.app.agents.domain import agent_text

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
        return None, [agent_text.message("spatial-join.not-object", where=where)]
    unknown = sorted(str(key) for key in set(raw) - set(SETTING_KEYS))
    if unknown:
        return None, [agent_text.message(
            "spatial-join.unknown-keys", where=where, unknown=', '.join(unknown), setting_keys=', '.join(SETTING_KEYS),
        )]
    problem = spatial.settings_problem(
        raw.get("predicate", spatial.DEFAULT_PREDICATE), raw.get("output", spatial.DEFAULT_OUTPUT),
    )
    if problem:
        return None, [f"{where}: {problem}"]
    setting = {key: raw[key] for key in SETTING_KEYS if key in raw}
    return (setting or None), []


#: What the join does with nothing saved, by key.
_DEFAULTS = {"predicate": spatial.DEFAULT_PREDICATE, "output": spatial.DEFAULT_OUTPUT}


def parse_change(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The change *raw* (``node.settings.write``'s) makes to a join on the
    canvas: each key it gives, as the join's select picks it, and both at the
    join's defaults (intersects, pairs) when it gives none; or the errors that
    say what the join would not take, as ``parse`` says them. Absent changes
    nothing. The join judges each key on its own, so a key the change leaves
    out cannot make one it gives wrong."""
    if raw is None:
        return None, []
    _setting, errors = parse(raw, where)
    if errors:
        return None, errors
    return {key: raw.get(key, _DEFAULTS[key]) for key in SETTING_KEYS if key in raw or not raw}, []


def after(current: object, change: dict) -> dict | None:
    """What a join whose ``metadata.spatialJoin`` is *current* stores once
    *change* is picked: its operation and output with each one *change*
    gives, its defaults left out as the join writes them (``saved``)."""
    return saved({**(saved(current) or {}), **change})


def template_problem(behavior: object, label: object, where: str) -> str | None:
    """Why a node whose template names *behavior* keeps no setting, or None."""
    if behavior == BEHAVIOR:
        return None
    return agent_text.message("spatial-join.not-a-join", where=where, label=label or 'this', key=KEY)


def describe(setting: dict | None) -> str:
    """The setting as a review card reads it: ``operation within, output counts``."""
    words = {"predicate": "operation", "output": "output"}
    return ", ".join(f"{words[key]} {setting[key]}" for key in SETTING_KEYS if key in (setting or {}))


def saved(raw: object) -> dict | None:
    """What a saved node's ``metadata.spatialJoin`` makes the join do, its
    defaults (intersects, pairs) left out, or None: ``resolvePredicate`` and
    ``resolveOutputMode`` in ``spatialJoinBehavior.tsx`` read anything else as
    those defaults."""
    if not isinstance(raw, dict):
        return None
    setting = {}
    predicate, output = raw.get("predicate"), raw.get("output")
    if isinstance(predicate, str) and predicate in spatial.PREDICATES and predicate != spatial.DEFAULT_PREDICATE:
        setting["predicate"] = predicate
    if isinstance(output, str) and output in spatial.OUTPUTS and output != spatial.DEFAULT_OUTPUT:
        setting["output"] = output
    return setting or None
