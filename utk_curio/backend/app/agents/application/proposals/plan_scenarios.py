"""The widgets and scenarios of a Dataflow Builder plan (#662), from mint to apply.

The grammar (``domain/widget_grammar.py``, ``domain/plan_scenarios.py``) checks
what a plan says on its own and expands its duplicates into copies. This is
what needs the saved dataflow:

* at mint: a node that holds widgets is one whose code or spec places them,
  and each widget its template declares is judged as the node will hold it,
  keeping the template's type, choices and bounds
  (``widget_grammar.template_problems``); a duplicate's values are judged
  against the widgets the node it copies will hold, its template's among
  them; an existing node a selection names is in the dataflow and in no other
  scenario; a scenario
  takes a name none of the dataflow's has, since scenario chips color and
  order scenarios by name; each scenario takes its color, as a scenario made
  on the canvas does;
* on the plan's card: each scenario with its nodes by name, and each node in
  one labelled with it, so a copy and its original read apart;
* at apply: a created node carries its widgets, its settings (a Data Pool's
  modes, a Simple View's image column, ``node_settings``), and, for a copy,
  where it came from
  (``metadata.copiedFrom``); a scenario is saved once all its nodes exist,
  by the whole-plan apply and the per-node one alike, and checked against the
  dataflow's scenarios, their nodes and their names, again then, since the
  plan's shape digest covers ids only.
"""
from __future__ import annotations

import uuid

from utk_curio.backend.app.agents.domain import node_settings, widget_grammar
from utk_curio.backend.app.execution.code_references import widget_with_default
from utk_curio.backend.app.projects.scenarios import next_scenario_color, normalize_scenarios
from utk_curio.backend.app.scenario_catalog.domain.duplicate import lineage_of
from utk_curio.backend.app.agents.domain import agent_text

#: What a node's content is, for the templates whose code or spec places a
#: widget's reference (the roster's ``contentKind``).
_PLACES_WIDGETS = ("code", "grammar")


def existing_scenarios(spec: dict) -> list[dict]:
    """The dataflow's scenarios, as a save keeps them."""
    dataflow = spec.get("dataflow") or {}
    node_ids = [n.get("id") for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    return normalize_scenarios(dataflow.get("scenarios"), node_ids)


def mint_errors(plan: dict, available: dict, existing_nodes: dict, scenarios: list, *,
                starters: dict | None = None, declared: dict | None = None) -> list[str]:
    """What the saved dataflow refuses in the plan's widgets and scenarios.
    *starters* and *declared* are the refs' templates' starters and declared
    widgets (``plans._content_starters``, ``plans._declared_widgets``), which
    a node of each starts with (:func:`created_node_metadata`)."""
    errors: list[str] = []

    def template_of(ref: str) -> list:
        return _template_widgets((starters or {}).get(ref), (declared or {}).get(ref))

    for index, node in enumerate(plan["nodes"]):
        if not node.get("widgets"):
            continue
        entry = available.get(node["nodeType"]) or {}
        if entry.get("contentKind") not in _PLACES_WIDGETS:
            errors.append(
                agent_text.message(
                    "plan.widgets-not-placeable", ref=repr(node['ref']), label=entry.get('label') or node['nodeType'],
                )
            )
        elif not node.get("copyOf"):
            # A copy holds its original's widgets, judged here once, and the
            # values its duplicate sets, judged below.
            errors.extend(widget_grammar.template_problems(
                node["widgets"], template_of(node["ref"]), f"nodes[{index}].widgets",
            ))
    errors.extend(_duplicate_value_errors(plan, template_of))
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


def _duplicate_value_errors(plan: dict, template_of) -> list[str]:
    """Why a duplicate's values cannot be set on its copies: each judged
    against the widget of its name the node the copy copies will hold
    (``widget_grammar.set_over``), a widget its template declares among them,
    as the Widgets tab judges a value."""
    nodes = {n["ref"]: n for n in plan["nodes"]}
    errors: list[str] = []
    for index, scenario in enumerate(plan.get("scenarios") or []):
        for ref, chosen in (scenario.get("values") or {}).items():
            original = nodes.get((nodes.get(ref) or {}).get("copyOf")) or {}
            held = {w["name"]: w for w in widget_grammar.set_over(
                template_of(original.get("ref")), original.get("widgets") or [])}
            here = f"scenarios[{index}].values.{ref}"
            for name, value in chosen.items():
                if name not in held:
                    errors.append(agent_text.message(
                        "scenario.values-unknown-widget", here=here, name=name, widget=repr(name),
                        widgets_it_has=" " + agent_text.message(
                            "scenario.values-widgets-it-has", widgets=", ".join(held),
                        ) if held else "",
                    ))
                    continue
                problem = widget_grammar.value_problem(held[name], value, f"{here}.{name}")
                if problem:
                    errors.append(problem)
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
    """What the plan's card shows of a node beside its title: its widgets, its
    settings (a Data Pool's modes, a Simple View's image column), the scenario
    it is in, and the node it copies."""
    shown: dict = {}
    # Each widget the plan writes on the node, as it stands on its own; a
    # duplicate's value for its template's widget is on the scenario's row.
    rows = [
        {key: widget[key] for key in ("name", "type", "label", "default", "value") if key in widget}
        for widget in (w if widget_grammar.sets_by_name(w) else widget_with_default(w)
                       for w in node.get("widgets") or [] if w.get("type"))
    ]
    if rows:
        shown["widgets"] = rows
    shown.update(node_settings.of(node))
    if node["ref"] in names:
        shown["scenario"] = names[node["ref"]]
    if node.get("copyOf"):
        shown["copyOf"] = node["copyOf"]
    return shown


def display_scenarios(plan: dict, existing_nodes: dict) -> list[dict]:
    """The plan's scenarios for the plan's card: each with its nodes by name."""
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


def created_node_metadata(
    plan_node: dict,
    created_ids: dict,
    nodes: list,
    starter: dict | None = None,
    declared: list | None = None,
) -> dict:
    """The ``metadata`` a planned node is created with: its widgets, its
    settings (a Data Pool's modes, a Simple View's image column, each at its
    own key), and for a copy the ids it descends from, the original's own
    lineage then the original (as Duplicate selection writes it). Empty when
    it has none of them.

    A node holds the widgets its template declares (*declared*, from the
    packages' ``declared_widgets``; for a node that starts with its
    template's starter, *starter*'s, which the starter places), each one the
    plan declares set over the one of its name, then the plan's others
    (``widget_grammar.set_over``)."""
    metadata: dict = {}
    planned = [dict(w) for w in plan_node.get("widgets") or []]
    widgets = widget_grammar.set_over(_template_widgets(starter, declared), planned)
    if widgets:
        metadata["widgets"] = widgets
    metadata.update(node_settings.of(plan_node))
    origin_id = created_ids.get(plan_node.get("copyOf") or "")
    if origin_id:
        original = next((n for n in nodes if isinstance(n, dict) and n.get("id") == origin_id), {})
        metadata["copiedFrom"] = [*lineage_of(original), origin_id]
    return metadata


def _template_widgets(starter: dict | None, declared: list | None) -> list:
    """The widgets a planned node starts with before the plan's own: its
    template's starter's, which the starter places, else the ones its
    template declares."""
    return starter["widgets"] if starter else (declared or [])


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
        # Each goes in a set, with its context and outcomes, as the plan's
        # write lands (``dataflow_docs._write``).
        dataflow["scenarios"] = current
    return created


def all_saved(proposal: dict) -> bool:
    """Whether every scenario of the plan is saved."""
    states = proposal.get("scenarioStates") or {}
    planned = (proposal.get("plan") or {}).get("scenarios") or []
    return all(states.get(str(i)) == "applied" for i in range(len(planned)))
