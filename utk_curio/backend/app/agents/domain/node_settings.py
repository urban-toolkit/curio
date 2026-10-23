"""The settings an agent sets on a node a plan or a node.create places, or
changes on a node already on the canvas (``node.settings.write``).

Three nodes keep a choice their body offers at ``metadata.<key>``: a Spatial
Join its operation and output (``spatial_join_settings``), a Data Pool its
conflict modes (``data_pool_settings``) and a Simple View its image column
(``simple_vis_settings``). Each module parses its setting by its node's own
rule, says why a template keeps none (only one whose ``behavior`` is the
node's does), words it as the node does for the review card, and reads what a
saved node's setting makes it do. A change of a node on the canvas is parsed
by the same rule, each key it gives picked as the node's select picks it and
each key it leaves out kept (``parse_change``, ``after``). This module walks
the three, so a plan's grammar and mint, a node.create, a settings change, the
card, the applies and ``dataflow.read`` treat each one the same way.
"""
from __future__ import annotations

from collections.abc import Callable

from utk_curio.backend.app.agents.domain import data_pool_settings, simple_vis_settings, spatial_join_settings

#: Each setting's module, in the order a node's card names them.
SETTINGS = (spatial_join_settings, data_pool_settings, simple_vis_settings)
#: The keys they go by: on a planned node, in node.create's params, on a
#: proposal and in a node's ``metadata``.
KEYS = tuple(module.KEY for module in SETTINGS)


def parse(raw: dict, prefix: str) -> tuple[dict, list[str]]:
    """The settings *raw* (a planned node, or node.create's params) gives, by
    key, each as its node stores it, or the errors; *prefix* is where they
    are, such as ``nodes[2]`` or ``params``."""
    found: dict = {}
    problems: list[str] = []
    for module in SETTINGS:
        setting, errors = module.parse(raw.get(module.KEY), f"{prefix}.{module.KEY}")
        problems.extend(errors)
        if setting:
            found[module.KEY] = setting
    return found, problems


def parse_change(raw: dict, prefix: str) -> tuple[dict, list[str]]:
    """The settings *raw* (``node.settings.write``'s params) changes on a node
    on the canvas, by key, each as its node's select picks it
    (``module.parse_change``), or the errors; *prefix* is where they are."""
    found: dict = {}
    problems: list[str] = []
    for module in SETTINGS:
        change, errors = module.parse_change(raw.get(module.KEY), f"{prefix}.{module.KEY}")
        problems.extend(errors)
        if change is not None:
            found[module.KEY] = change
    return found, problems


def write(metadata: dict, changes: dict) -> None:
    """Write *changes* into a saved node's *metadata*: each setting as its
    node stores it once the change is picked (``module.after``), and none at
    all where that is the node's default."""
    for module in SETTINGS:
        if module.KEY not in changes:
            continue
        setting = module.after(metadata.get(module.KEY), changes[module.KEY])
        if setting:
            metadata[module.KEY] = setting
        else:
            metadata.pop(module.KEY, None)


def changes_anything(metadata: object, changes: dict) -> bool:
    """Whether *changes* changes what a saved node with *metadata* does."""
    held = metadata if isinstance(metadata, dict) else {}
    return any(
        module.after(held.get(module.KEY), changes[module.KEY]) != module.saved(held.get(module.KEY))
        for module in SETTINGS if module.KEY in changes
    )


def describe_change(changes: dict) -> list[str]:
    """Each setting *changes* picks, as the review card words it: each key it
    gives, one put back to its default among them, and a Simple View's every
    image column in the view's own word."""
    return [module.describe(changes[module.KEY]) for module in SETTINGS if module.KEY in changes]


def template_problems(settings: dict, behavior: object, label: object, where_of: Callable[[str], str]) -> list[str]:
    """For each of *settings* whose node is not the one a template naming
    *behavior* makes, why it keeps none; *where_of* says where each key is."""
    problems: list[str] = []
    for module in SETTINGS:
        if module.KEY not in settings:
            continue
        problem = module.template_problem(behavior, label, where_of(module.KEY))
        if problem:
            problems.append(problem)
    return problems


def plan_problems(nodes: list, entries: list, behavior_of: Callable[[str], object]) -> list[str]:
    """For each planned node that sets one, why its template keeps no such
    setting: *entries* are the roster rows the mint resolved, in the nodes'
    order, and *behavior_of* gives a node type's behavior."""
    problems: list[str] = []
    for node, entry in zip(nodes, entries):
        settings = of(node)
        if not settings:
            continue
        label = (entry or {}).get("label") or node["nodeType"]
        where = f"plan node {node['ref']!r}"
        problems.extend(template_problems(settings, behavior_of(node["nodeType"]), label, lambda _key: where))
    return problems


def of(holder: dict) -> dict:
    """The settings *holder* (a planned node, a proposal) carries, by key,
    each a copy."""
    return {module.KEY: dict(holder[module.KEY]) for module in SETTINGS if holder.get(module.KEY)}


def describe(holder: dict) -> list[str]:
    """Each setting *holder* carries, as the review card words it."""
    return [module.describe(holder[module.KEY]) for module in SETTINGS if holder.get(module.KEY)]


def saved(metadata: object) -> dict:
    """What a saved node's settings make it do, by key, its defaults left out:
    what ``dataflow.read`` shows of the node."""
    if not isinstance(metadata, dict):
        return {}
    found = {}
    for module in SETTINGS:
        setting = module.saved(metadata.get(module.KEY))
        if setting:
            found[module.KEY] = setting
    return found
