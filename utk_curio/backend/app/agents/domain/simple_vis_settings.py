"""The image column an agent sets on a Simple View node.

A Simple View shows a card per row when its frame carries image columns, every
image column side by side unless the node names one, which its body offers as
its Image column select and keeps at ``metadata.simpleVis`` (#276). An agent
sets it on a planned node (``dataflow.plan.write``) or a created one
(``node.create``), and the setting is checked here, so a wrong one comes back
to the model as an error it can fix.

The rule is the view's own: it reads the name trimmed, and an empty one as
every image column (``resolveImageColumnChoice`` in
``adapters/node/simpleVisBehavior.tsx``). So a name is kept trimmed, and one
that is empty, which the view would read as every column without a word, is
refused. The shape is ``$defs.nodeMetadata.properties.simpleVis`` in
``docs/schemas/trill.v1.json`` (a string of at least one character), and the
words are ``src/contracts/nodeSettings.json``, which the view reads too. An
agent changes a view already on the canvas (``node.settings.write``) by the
same rule, and one that names no column picks every image column, as the
view's All does, which clears the setting. Only a
template whose ``behavior`` is the view's keeps a setting: the behavior
``packages.template_behavior`` reads, which the caller passes in.
"""
from __future__ import annotations

from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.common import shared_constants

_WORDS = shared_constants.read("nodeSettings")["simpleVis"]

#: The behavior a Simple View template names.
BEHAVIOR = "simple-vis"
#: Where a node keeps the setting, in its ``metadata``, and the key a planned
#: node or a node.create gives it under.
KEY = "simpleVis"
#: The keys the setting has.
SETTING_KEYS = tuple(_WORDS["settings"])


def _column(value: object) -> str:
    """The column *value* names, as the view reads it: trimmed, or ``""``."""
    return value.strip() if isinstance(value, str) else ""


def parse(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The setting *raw* gives, as the view reads it (its column trimmed), or
    the errors that say what the view would not take. Absent, or empty, sets
    nothing: the view shows every image column."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, [agent_text.message("simple-vis.not-object", where=where)]
    unknown = sorted(str(key) for key in set(raw) - set(SETTING_KEYS))
    if unknown:
        return None, [agent_text.message(
            "simple-vis.unknown-keys", where=where, unknown=', '.join(unknown), setting_keys=', '.join(SETTING_KEYS),
        )]
    if "imageColumn" not in raw:
        return None, []
    column = _column(raw["imageColumn"])
    if not column:
        return None, [agent_text.message(
            "simple-vis.image-column-empty", where=f"{where}.imageColumn", value=repr(raw["imageColumn"]),
        )]
    return {"imageColumn": column}, []


def parse_change(raw: object, where: str) -> tuple[dict | None, list[str]]:
    """The change *raw* (``node.settings.write``'s) makes to a view on the
    canvas: the column it names, trimmed, or ``{}``, every image column, as
    the view's All picks it, when it names none; or the errors that say what
    the view would not take, as ``parse`` says them. Absent changes nothing."""
    if raw is None:
        return None, []
    setting, errors = parse(raw, where)
    if errors:
        return None, errors
    return (setting or {}), []


def after(current: object, change: dict) -> dict | None:
    """What a view stores once *change* is picked: the column it names, or
    None for every image column, which the view writes as no setting."""
    column = _column(change.get("imageColumn"))
    return {"imageColumn": column} if column else None


def template_problem(behavior: object, label: object, where: str) -> str | None:
    """Why a node whose template names *behavior* keeps no setting, or None."""
    if behavior == BEHAVIOR:
        return None
    return agent_text.message("simple-vis.not-a-view", where=where, label=label or 'this', key=KEY)


def describe(setting: dict | None) -> str:
    """The setting as the view's select names it, as a review card reads it:
    ``Image column: overlay_url``, or the select's own word for every image
    column, ``Image column: all``, when it names none."""
    return f"{_WORDS['settings']['imageColumn']}: {_column((setting or {}).get('imageColumn')) or _WORDS['all']}"


def saved(raw: object) -> dict | None:
    """What a saved node's ``metadata.simpleVis`` makes the view show: the
    column it names, trimmed, or None when it shows every image column."""
    column = _column(raw.get("imageColumn")) if isinstance(raw, dict) else ""
    return {"imageColumn": column} if column else None
