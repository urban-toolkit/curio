"""The widgets and scenarios of a Dataflow Builder plan (#662), from mint to apply.

The grammar (``domain/widget_grammar.py``, ``domain/plan_scenarios.py``) checks
what a plan says on its own and expands its duplicates into copies. This is
what needs the saved dataflow:

* at mint: a node that holds widgets is one whose code or spec places them, or
  a Parameter node, whose name no other Parameter node has; an existing node a
  selection names is in the dataflow and in no other scenario; a scenario
  takes a name none of the dataflow's has, since scenario chips color and
  order scenarios by name; each scenario takes its color, as a scenario made
  on the canvas does;
* on the review card: each scenario with its nodes by name, and each node in
  one labelled with it, so a copy and its original read apart;
* at apply: a created node carries its widgets, its settings (a Spatial
  Join's operation and output, a Data Pool's modes, a Simple View's image
  column, ``node_settings``), and, for a copy, where it came from
  (``metadata.copiedFrom``); a scenario is saved once all its nodes exist,
  by the whole-plan apply and the per-node one alike, and checked against the
  dataflow's scenarios, their nodes and their names, again then, since the
  plan's shape digest covers ids only.
"""
from __future__ import annotations

import uuid

from utk_curio.backend.app.agents.domain import node_settings
from utk_curio.backend.app.execution.code_references import check_widget_def, normalize_widgets
from utk_curio.backend.app.execution.workflow_spec import PARAMETER_TYPE
from utk_curio.backend.app.projects.scenarios import next_scenario_color, normalize_scenarios
from utk_curio.backend.app.scenario_catalog.domain.duplicate import lineage_of
from utk_curio.backend.app.agents.domain import agent_text

#: What a node's content is, for the templates whose code or spec places a
#: widget's reference (the roster's ``contentKind``).
_PLACES_WIDGETS = ("code", "grammar")


def _type(node: dict) -> str:
    return str(node.get("type") or node.get("nodeType") or "").split("@", 1)[0]


def _parameter_widgets(nodes, removed: set) -> list[dict]:
    """The widgets the dataflow's Parameter nodes hold, the removed ones left out."""
    return [
        widget
        for node in nodes
        if _type(node) == PARAMETER_TYPE and node.get("id") not in removed
        for widget in normalize_widgets((node.get("metadata") or {}).get("widgets"))
    ]


def existing_scenarios(spec: dict) -> list[dict]:
    """The dataflow's scenarios, as a save keeps them."""
    dataflow = spec.get("dataflow") or {}
    node_ids = [n.get("id") for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    return normalize_scenarios(dataflow.get("scenarios"), node_ids)


def mint_errors(plan: dict, available: dict, existing_nodes: dict, scenarios: list, removed: set) -> list[str]:
    """What the saved dataflow refuses in the plan's widgets and scenarios."""
    errors: list[str] = []
    for node in plan["nodes"]:
        if not node.get("widgets") or node["nodeType"] == PARAMETER_TYPE:
            continue
        entry = available.get(node["nodeType"]) or {}
        if entry.get("contentKind") not in _PLACES_WIDGETS:
            errors.append(
                agent_text.message(
                    "plan.widgets-not-placeable", ref=repr(node['ref']), label=entry.get('label') or node['nodeType'],
                )
            )
    # A shared tag's name is the Parameter node's: the Widgets tab's own rule.
    taken = _parameter_widgets(existing_nodes.values(), removed)
    for node in plan["nodes"]:
        if node["nodeType"] != PARAMETER_TYPE:
            continue
        message = check_widget_def(node["widgets"][0], taken, parameter=True)
        if message:
            errors.append(agent_text.message("plan.node-problem", ref=repr(node['ref']), problem=message))
        taken.append(node["widgets"][0])
    owner = {member: s["name"] for s in scenarios for member in s["nodes"]}
    taken = {s["name"] for s in scenarios}
    refs = {n["ref"] for n in plan["nodes"]}
    for index, scenario in enumerate(plan.get("scenarios") or []):
        if scenario["name"] in taken:
            errors.append(agent_text.message("plan.scenario-name-taken", index=index, name=repr(scenario['name'])))
        for member in scenario["nodes"]:
            if member in refs:
                continue
            if member not in existing_nodes:
                errors.append(agent_text.message(
                    "plan.scenario-member-unknown", index=index, name=repr(scenario['name']), member=repr(member),
                ))
            elif member in owner:
                errors.append(agent_text.message(
                    "plan.scenario-member-taken", index=index, name=repr(scenario['name']), member=repr(member),
                    owner=repr(owner[member]),
                ))
    return errors


def assign_colors(plan: dict, scenarios: list) -> None:
    """Give each plan scenario without a color the next one, after the
    dataflow's own and the plan's earlier ones."""
    worn = [s["color"] for s in scenarios]
    for scenario in plan.get("scenarios") or []:
        scenario.setdefault("color", next_scenario_color(worn))
        worn.append(scenario["color"])


def scenario_names(plan: dict) -> dict[str, str]:
    """Each plan ref in a scenario to that scenario's name."""
    return {m: s["name"] for s in plan.get("scenarios") or [] for m in s["nodes"]}


def node_display(node: dict, names: dict) -> dict:
    """What the review card shows of a node beside its title: its widgets, its
    settings (a Spatial Join's operation and output, a Data Pool's modes, a
    Simple View's image column), the scenario it is in, and the node it
    copies."""
    shown: dict = {}
    if node.get("widgets"):
        shown["widgets"] = [
            {key: w[key] for key in ("name", "type", "label", "default", "value") if key in w}
            for w in node["widgets"]
        ]
    shown.update(node_settings.of(node))
    if node["ref"] in names:
        shown["scenario"] = names[node["ref"]]
    if node.get("copyOf"):
        shown["copyOf"] = node["copyOf"]
    return shown


def display_scenarios(plan: dict, existing_nodes: dict) -> list[dict]:
    """The plan's scenarios for the review card: each with its nodes by name."""
    titles = {n["ref"]: n["title"] for n in plan["nodes"]}
    rows = []
    for scenario in plan.get("scenarios") or []:
        row = {
            "name": scenario["name"],
            "color": scenario["color"],
            "nodes": [
                {"ref": m, "label": (titles.get(m) or str((existing_nodes.get(m) or {}).get("goal") or m))[:60]}
                for m in scenario["nodes"]
            ],
        }
        for key in ("description", "duplicateOf", "values"):
            if scenario.get(key):
                row[key] = scenario[key]
        rows.append(row)
    return rows


def preview_lines(plan: dict) -> list[str]:
    """One preview line per scenario, its nodes by title."""
    titles = {n["ref"]: n["title"] for n in plan["nodes"]}
    lines = []
    for scenario in plan.get("scenarios") or []:
        nodes = ", ".join(titles.get(m, m) for m in scenario["nodes"])
        copied = f" (a copy of {scenario['duplicateOf']})" if scenario.get("duplicateOf") else ""
        lines.append(f"Scenario {scenario['name']}{copied}: {nodes}")
    return lines


def copy_blocker(plan: dict, plan_node: dict, created_ids: dict) -> str | None:
    """Why a copy cannot be created yet: the node it copies must exist first,
    so the copy can name it."""
    origin = plan_node.get("copyOf")
    if not origin or created_ids.get(origin):
        return None
    title = next((n["title"] for n in plan["nodes"] if n["ref"] == origin), origin)
    return f"create {title!r} first: a copy records the node it was copied from"


def created_node_metadata(plan_node: dict, created_ids: dict, nodes: list, starter: dict | None = None) -> dict:
    """The ``metadata`` a planned node is created with: its widgets, its
    settings (a Spatial Join's operation and output, a Data Pool's modes, a
    Simple View's image column, each at its own key), and for a copy the ids
    it descends from, the original's own lineage then the original (as
    Duplicate selection writes it). Empty when it has none of them.

    A node that starts with its template's starter (*starter*, from the
    packages' ``content_starters``) holds the template's widgets, which the
    starter places, each one the plan declares set over the one of its name,
    then the plan's others."""
    metadata: dict = {}
    planned = [dict(w) for w in plan_node.get("widgets") or []]
    widgets = _set_over(starter["widgets"], planned) if starter else planned
    if widgets:
        metadata["widgets"] = widgets
    metadata.update(node_settings.of(plan_node))
    origin_id = created_ids.get(plan_node.get("copyOf") or "")
    if origin_id:
        original = next((n for n in nodes if isinstance(n, dict) and n.get("id") == origin_id), {})
        metadata["copiedFrom"] = [*lineage_of(original), origin_id]
    return metadata


def _set_over(template_widgets: list, planned: list) -> list[dict]:
    """*template_widgets* in their order, each with the keys of the *planned*
    widget of its name set over its own, then the planned widgets of other
    names."""
    by_name = {w["name"]: w for w in planned}
    names = {w["name"] for w in template_widgets}
    merged = [{**w, **by_name.get(w["name"], {})} for w in template_widgets]
    return normalize_widgets(merged + [w for w in planned if w["name"] not in names])


def apply_scenarios(spec: dict, proposal: dict, ref_to_id: dict, *, final: bool) -> list[dict]:
    """Save each plan scenario whose nodes all exist now and that is not saved
    yet, and answer the ones saved. A scenario that would take a node another
    scenario holds, or a name another scenario has, is refused, and so, when
    *final* (the whole-plan apply), is one whose nodes are not all there."""
    plan = proposal.get("plan") or {}
    planned = plan.get("scenarios") or []
    if not planned:
        return []
    states = proposal.setdefault("scenarioStates", {})
    saved_ids = proposal.setdefault("appliedScenarioIds", {})
    dataflow = spec.setdefault("dataflow", {})
    node_ids = {n.get("id") for n in dataflow.get("nodes") or [] if isinstance(n, dict)}
    current = existing_scenarios(spec)
    owner = {m: s["name"] for s in current for m in s["nodes"]}
    names = {s["name"] for s in current}
    created: list[dict] = []
    for index, scenario in enumerate(planned):
        key = str(index)
        if states.get(key) in ("applied", "refused"):
            continue
        members = [ref_to_id.get(m, m) for m in scenario["nodes"]]
        if not all(m in node_ids for m in members):
            if final:
                states[key] = "refused"
            continue
        if any(m in owner for m in members) or scenario["name"] in names:
            states[key] = "refused"
            continue
        entry = {"id": str(uuid.uuid4()), "name": scenario["name"], "color": scenario["color"]}
        if scenario.get("description"):
            entry["description"] = scenario["description"]
        entry["nodes"] = members
        current.append(entry)
        owner.update({m: entry["name"] for m in members})
        names.add(entry["name"])
        states[key] = "applied"
        saved_ids[key] = entry["id"]
        created.append(entry)
    if created:
        dataflow["scenarios"] = current
    return created


def all_saved(proposal: dict) -> bool:
    """Whether every scenario of the plan is saved."""
    states = proposal.get("scenarioStates") or {}
    planned = (proposal.get("plan") or {}).get("scenarios") or []
    return all(states.get(str(i)) == "applied" for i in range(len(planned)))
