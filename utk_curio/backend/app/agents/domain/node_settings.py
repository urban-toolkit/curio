"""The settings an agent sets on a node a plan or a node.create places.

Three nodes keep a choice their body offers at ``metadata.<key>``: a Spatial
Join its operation and output (``spatial_join_settings``), a Data Pool its
conflict modes (``data_pool_settings``) and a Simple View its image column
(``simple_vis_settings``). Each module parses its setting by its node's own
rule, says why a template keeps none (only one whose ``behavior`` is the
node's does), words it as the node does for the review card, and reads what a
saved node's setting makes it do. This module walks the three, so a plan's
grammar and mint, a node.create, the card, both applies and ``dataflow.read``
treat each one the same way.
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
