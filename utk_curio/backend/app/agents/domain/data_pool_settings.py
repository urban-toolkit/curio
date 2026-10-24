"""The conflict modes an agent sets on a Data Pool node.

A Data Pool resolves the selections that reach it with two modes, which its
body offers as two selects and keeps at ``metadata.dataPool`` (#581):
``insideChart`` combines the selects of one chart, ``betweenCharts`` the latest
selection of each chart linked to the pool. An agent sets them on a planned
node (``dataflow.plan.write``) or a created one (``node.create``), and each
setting is checked here, so a wrong one comes back to the model as an error it
can fix.

The rule is the pool's own, ``utils/dataPoolSpec.ts``: a value that names no
mode reads as OVERWRITE, and only the modes that are not OVERWRITE are written.
So a value the pool would read as OVERWRITE without a word is refused, and a
setting is stored as the pool writes it. An agent changes a pool already on
the canvas (``node.settings.write``) by the same rule, each mode it gives
picked as the pool's select picks it (``parse_change``, ``after``). ``dataPoolSpec.cases.json`` beside
the TypeScript holds the cases both sides run. The shape is
``$defs.nodeMetadata.properties.dataPool`` in ``docs/schemas/trill.v1.json``,
and the modes and their words are ``src/contracts/nodeSettings.json``, which
the pool's selects read too (tests pin all three to ``ResolutionType``). Only a
template whose ``behavior`` is the pool's keeps a setting: the behavior
``packages.template_behavior`` reads, which the caller passes in.
"""
from __future__ import annotations

from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.common import shared_constants

_WORDS = shared_constants.read("nodeSettings")["dataPool"]

#: The behavior a Data Pool template names.
BEHAVIOR = "data-pool"
#: Where a node keeps the setting, in its ``metadata``, and the key a planned
#: node or a node.create gives it under.
KEY = "dataPool"
#: The keys the setting has, in the order a node stores them.
SETTING_KEYS = tuple(_WORDS["settings"])
#: The modes each key takes: ``ResolutionType``, in its order.
MODES = tuple(_WORDS["modes"])
#: The mode a pool reads anything else as, which it never writes.
DEFAULT = "OVERWRITE"


def parse(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The setting *raw* gives, as the pool writes it (``dataPoolToSpec``:
    the modes that are not OVERWRITE), or the errors that say what the pool
    would not take. Absent, or naming only OVERWRITE, sets nothing."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, [agent_text.message("data-pool.not-object", where=where)]
    unknown = sorted(str(key) for key in set(raw) - set(SETTING_KEYS))
    if unknown:
        return None, [agent_text.message(
            "data-pool.unknown-keys", where=where, unknown=', '.join(unknown), setting_keys=', '.join(SETTING_KEYS),
        )]
    problems = [
        agent_text.message(
            "data-pool.not-a-mode", where=f"{where}.{key}", modes=', '.join(MODES), value=repr(raw[key]),
            default=DEFAULT,
        )
        for key in SETTING_KEYS
        if key in raw and not _names_a_mode(raw[key])
    ]
    if problems:
        return None, problems
    setting = {key: raw[key] for key in SETTING_KEYS if key in raw and raw[key] != DEFAULT}
    return (setting or None), []


def _names_a_mode(value: object) -> bool:
    return isinstance(value, str) and value in MODES


def parse_change(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The change *raw* (``node.settings.write``'s) makes to a pool on the
    canvas: each mode it gives, as the pool's select picks it, OVERWRITE among
    them, and both modes at OVERWRITE when it gives none; or the errors that
    say what the pool would not take, as ``parse`` says them. Absent changes
    nothing."""
    if raw is None:
        return None, []
    _setting, errors = parse(raw, where)
    if errors:
        return None, errors
    return {key: raw.get(key, DEFAULT) for key in SETTING_KEYS if key in raw or not raw}, []


def after(current: object, change: dict) -> dict | None:
    """What a pool whose ``metadata.dataPool`` is *current* stores once
    *change* is picked: its modes with each one *change* gives, as the pool
    writes them (``saved``), or None when both are OVERWRITE."""
    return saved({**(saved(current) or {}), **change})


def template_problem(behavior: object, label: object, where: str) -> str | None:
    """Why a node whose template names *behavior* keeps no setting, or None."""
    if behavior == BEHAVIOR:
        return None
    return agent_text.message("data-pool.not-a-pool", where=where, label=label or 'this', key=KEY)


def describe(setting: dict | None) -> str:
    """The setting as the pool's selects word it, as a review card reads it:
    ``Conflict between visualizations: Merge (AND)``."""
    return "; ".join(
        f"{_WORDS['settings'][key]}: {_WORDS['modes'].get(setting[key], setting[key])}"
        for key in SETTING_KEYS if key in (setting or {})
    )


def saved(raw: object) -> dict | None:
    """What a saved node's ``metadata.dataPool`` makes the pool do, the modes
    other than OVERWRITE (``dataPoolFromSpec`` drops a member that names no
    mode, and the pool reads it as OVERWRITE), or None."""
    if not isinstance(raw, dict):
        return None
    setting = {key: raw[key] for key in SETTING_KEYS if _names_a_mode(raw.get(key)) and raw[key] != DEFAULT}
    return setting or None
