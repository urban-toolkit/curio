"""Dataflow plans: minting, fan-in validation, landing whole and its Undo, node-agent attachment, and layout.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import copy
import logging
import hashlib
import re as _re
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application import delegation
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import dashboards
from utk_curio.backend.app.agents.domain import node_settings
from utk_curio.backend.app.agents.domain import plan_topology
from utk_curio.backend.app.agents.domain.counts import count_label
from utk_curio.backend.app.agents.repositories import project_agents
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.execution.workflow_spec import slot_handle_id
from utk_curio.backend.app.agents.application.proposals import changes as agents_changes
from utk_curio.backend.app.agents.application.proposals import plan_scenarios
from utk_curio.backend.app.collaboration import dataflow_docs
from utk_curio.backend.app.collaboration import doc_mapping
from utk_curio.backend.app.collaboration import history
from utk_curio.backend.app.agents.domain import agent_text

log = logging.getLogger(__name__)


# A growing node's input circles: ``in`` first, then ``in_1``, ``in_2``, ...
_CIRCLE_HANDLE_RE = _re.compile(r"^in(?:_[1-9][0-9]*)?$")


def _grows_circles(entry: dict | None) -> bool:
    """A template whose one input port takes more than one edge: each edge
    lands on a circle of its own, as the canvas draws them (``inputSlots``)."""
    if not entry:
        return False
    return len(entry.get("inputs") or []) == 1 and entry.get("maxIncomingEdges") not in (0, 1)


def _takes_circles(entry: dict | None) -> bool:
    """A template whose every edge takes a circle of its own: a growing port,
    or several input ports, one edge each (the Spatial Join's ``in`` and
    ``in_1``, #576). An edge that names no circle takes the first free one."""
    if not entry:
        return False
    return _grows_circles(entry) or len(entry.get("inputs") or []) > 1


def _free_circle(taken: set, wanted) -> str:
    """The circle a new edge takes: a named free circle wins, else the first
    free one."""
    if isinstance(wanted, str) and _CIRCLE_HANDLE_RE.match(wanted) and wanted not in taken:
        return wanted
    slot = 0
    while slot_handle_id(slot) in taken:
        slot += 1
    return slot_handle_id(slot)


def _circle_index(handle: str) -> int:
    """The circle a handle names (``in`` is 0, ``in_k`` is k), or -1."""
    if not _CIRCLE_HANDLE_RE.match(handle):
        return -1
    return 0 if handle == "in" else int(handle[3:])


def _circle_names(max_in: int | None) -> str:
    """A growing node's circles as the handles an edge may name."""
    shown = range(3) if max_in is None else range(max_in)
    names = ", ".join(f'"{slot_handle_id(k)}"' for k in shown)
    return names + (", ..." if max_in is None else "")


def _strip_type_version(node_type: str) -> str:
    """``curio.builtin/data-pool@1`` → ``curio.builtin/data-pool``: spec
    node types may carry the versioned form; the template registry is
    unversioned-canonical."""
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


def _content_starters(user_key: str, project_id: str, plan_nodes: list) -> dict[str, dict]:
    """What each planned node whose template's starter is a node's whole
    content (``starterIsContent``) starts with, by plan ref: the template's
    starter and widgets (the packages' ``content_starters``). A planned node
    of any other template starts empty, for Solve to write."""
    from utk_curio.backend.app.packages import service as packages_services

    by_template = packages_services.content_starters(
        user_key, project_id, [n["nodeType"] for n in plan_nodes]
    )
    canonical = packages_services.canonical_template_id
    return {
        n["ref"]: by_template[canonical(n["nodeType"])]
        for n in plan_nodes
        if canonical(n["nodeType"]) in by_template
    }


def _declared_widgets(user_key: str, project_id: str, plan_nodes: list) -> dict[str, list]:
    """The widgets each planned node's template declares, by plan ref (the
    packages' ``declared_widgets``): the ones the roster names for it, which
    a node of it starts with on the canvas too. A ref whose template declares
    none is left out."""
    from utk_curio.backend.app.packages import service as packages_services

    by_template = packages_services.declared_widgets(
        user_key, project_id, [n["nodeType"] for n in plan_nodes]
    )
    canonical = packages_services.canonical_template_id
    return {
        n["ref"]: by_template[canonical(n["nodeType"])]
        for n in plan_nodes
        if canonical(n["nodeType"]) in by_template
    }


def _awaits_solve(node: dict) -> bool:
    """Whether Solve writes a created node's content: a planned node starts
    empty unless its template's starter is its whole content."""
    return not (node.get("content") or "").strip()


def _created_state(ref: str, starters: dict) -> str:
    """A created ref's Simulation Mode state. One that starts with its
    template's starter is approved: its content is the template's, which
    nothing validates or writes again."""
    return "approved" if ref in starters else "created"


def _validate_plan_fanin(
    plan: dict,
    available: dict,
    existing_nodes: dict,
    existing_edges: list,
    remove_node_set: set,
    remove_edge_set: set,
) -> list[str]:
    """dev/67-3 (DEC-051): every edge target must accept its NET incoming
    degree — plan edges plus the SURVIVING existing edges (dev/59 victims
    excluded), against the template registry's capacity. Refusals say how
    to rewire so the corrective round can replan; unknown or out-of-scope
    templates fail open (no arity metadata → no refusal)."""
    errors: list[str] = []
    plan_nodes = {n["ref"]: n for n in plan.get("nodes", [])}
    surviving_in: dict[str, int] = {}
    for edge in existing_edges:
        if str(edge.get("id")) in remove_edge_set:
            continue
        if edge.get("source") in remove_node_set or edge.get("target") in remove_node_set:
            continue
        if plan_topology.is_interaction_edge(edge):
            continue  # dev/112: feedback edges take no input port (parity with _plan_edge_context)
        target = edge.get("target")
        surviving_in[target] = surviving_in.get(target, 0) + 1
    incoming: dict[str, list[str]] = {}
    for edge in plan.get("edges", []):
        if plan_topology.is_interaction_edge(edge):
            continue  # dev/112
        incoming.setdefault(edge["to"], []).append(edge["from"])
    for target, sources in incoming.items():
        if target in plan_nodes:
            node_type = plan_nodes[target]["nodeType"]
            label = plan_nodes[target]["title"]
            existing_count = 0
        else:
            node = existing_nodes.get(target) or {}
            node_type = _strip_type_version(str(node.get("type") or ""))
            label = (node.get("goal") or target)[:60]
            existing_count = surviving_in.get(target, 0)
        entry = available.get(node_type)
        if entry is None:
            continue  # out-of-scope/custom template: fail open
        max_in = entry.get("maxIncomingEdges")
        total = len(sources) + existing_count
        if max_in is None or total <= max_in:
            continue
        src_list = ", ".join(repr(s) for s in sources[:4])
        existing_note = (
            " " + agent_text.message(
                "plan.fanin-existing-note", existing_count=existing_count, s='s' if existing_count != 1 else '',
            )
            if existing_count
            else ""
        )
        if max_in == 0:
            errors.append(
                agent_text.message("plan.fanin-no-inputs", label=repr(label), node_type=node_type, src_list=src_list)
            )
        elif max_in == 1:
            errors.append(
                agent_text.message(
                    "plan.fanin-single-input", label=repr(label), node_type=node_type, total=total,
                    existing_note=existing_note, src_list=src_list,
                )
            )
        else:
            errors.append(
                agent_text.message(
                    "plan.fanin-too-many-inputs", label=repr(label), node_type=node_type, max_inputs=max_in,
                    total=total, existing_note=existing_note,
                )
            )
    for i, edge in enumerate(plan.get("edges", [])):
        handle = edge.get("toHandle")
        if not handle:
            continue
        target = edge["to"]
        if target in plan_nodes:
            node_type = plan_nodes[target]["nodeType"]
        else:
            node_type = _strip_type_version(
                str((existing_nodes.get(target) or {}).get("type") or "")
            )
        entry = available.get(node_type)
        if not _takes_circles(entry):
            continue
        max_in = entry.get("maxIncomingEdges")
        index = _circle_index(handle)
        if index < 0 or (max_in is not None and index >= max_in):
            errors.append(
                agent_text.message("plan.handle-invalid", i=i, handle=repr(handle), circles=_circle_names(max_in))
            )
    return errors


def _interaction_spec_edge(source: str, target: str) -> dict:
    """dev/112: the spec shape of a Trill Interaction edge — what
    ``TrillGenerator`` writes and ``loadTrill`` reads (``in/out`` both ends,
    bidirectional on the canvas)."""
    return {
        "id": str(uuid.uuid4()),
        "source": source,
        "target": target,
        "sourceHandle": "in/out",
        "targetHandle": "in/out",
        "type": plan_topology.INTERACTION_EDGE_TYPE,
    }


def _topology_clause(spec: dict) -> str:
    """dev/112 (G5): the applied turn's verdict on the saved graph — what the
    agent reads to confirm a repair instead of asserting one. A cycle the plan
    could not have created (the user drew it) is reported here, never refused."""
    dataflow = spec.get("dataflow") or {}
    nodes = {n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)}
    pairs = plan_topology.net_data_edges(dataflow.get("edges") or [], {"edges": []}, set(), set())
    path = plan_topology.find_data_cycle(pairs)
    if path is None:
        return "Topology: acyclic."
    return "Topology: cycle through " + plan_topology.format_cycle(
        path, lambda x: (nodes.get(x) or {}).get("goal") or x
    ) + "."


def _removal_phrase(n_nodes: int, n_edges: int, *, prefix: str = "removed ") -> str:
    """dev/112: ``, removed 1 node and 2 connections`` — truthful for edges
    (the old copy counted nodes only, so an edge-only removal read "removed 0
    nodes"). Empty when nothing was removed."""
    parts = []
    if n_nodes:
        parts.append(count_label(n_nodes, "node"))
    if n_edges:
        parts.append(count_label(n_edges, "connection"))
    return f", {prefix}" + " and ".join(parts) if parts else ""


def _mint_dataflow_plan(
    user_key: str, project_id: str, loop_ctx: dict, plan: dict
) -> tuple[str, str, dict | None]:
    """Mint the dev/52 plan proposal from a validated ``dataflowPlan`` part.

    Reuse-first exactly as dev/48: every nodeType must be an available
    template (authorable when the plan carries content for it). Pins the
    whole-graph shape digest; the apply endpoint re-checks it. Returns
    ``(status, user_facing_error, proposal_part | None)``."""
    from utk_curio.backend.app.packages import service as packages_services

    session_id = loop_ctx.get("session_id")
    if not isinstance(session_id, str):
        return "refused", agent_text.message("plan.no-conversation"), None
    # dev/67-5: plans describe intent — generated code never rides a plan.
    # There is no "trivial code" shortcut (67-0): every node's content is
    # produced and validated per node after creation. Supersedes dev/52's
    # plan-carried-content allowance at its recorded revisit point.
    content_refs = [n["ref"] for n in plan["nodes"] if n.get("content")]
    if content_refs:
        return (
            "refused",
            agent_text.message("plan.nodes-carry-content", content_refs=', '.join(repr(r) for r in content_refs)),
            None,
        )
    try:
        available = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        return "refused", agent_text.message("mint.template-registry-unavailable", exc=exc), None
    # dev/93 D3: the ONE availability gate, shared with node.create — a plan
    # may name any available template (a plan places a typed PLACEHOLDER whose
    # content arrives later from Solve), hence require_authorable=False. The
    # nodeType is already canonical here (canonicalised at the parse boundary),
    # so this used to be an exact-match dict lookup that refused the versioned
    # spelling the model was handed by its own run context.
    #
    # dev/99 R1.2: resolved as a BATCH — one store snapshot for the whole plan
    # instead of one per node. Resolving per node re-walked the store (and,
    # once readers hold the seed lock, re-acquired it) once per plan node, so
    # the cost scaled with plan size; it also judged each node against a
    # different instant.
    outcomes = packages_services.resolve_templates(
        user_key, project_id,
        [node["nodeType"] for node in plan["nodes"]],
        require_authorable=False,
    )
    for node, (entry, err) in zip(plan["nodes"], outcomes):
        if entry is None:
            return "refused", agent_text.message("plan.node-problem", ref=repr(node['ref']), problem=err), None
    setting_errors = node_settings.plan_problems(
        plan["nodes"], [entry for entry, _err in outcomes],
        lambda node_type: packages_services.template_behavior(user_key, project_id, node_type),
    )
    if setting_errors:
        return "refused", "\n- ".join([agent_text.message("plan.node-settings-invalid")] + setting_errors), None
    spec = dataflow_docs.live(user_key, project_id)
    if spec is None:
        return "refused", agent_text.message("mint.no-saved-spec"), None
    # Revision validation against the saved spec (dev/59): removal targets and
    # existing-id edge endpoints must be real; the grammar could only check
    # shape. Errors feed the same correction rounds as every plan failure.

    dataflow = spec.get("dataflow") or {}
    existing_nodes = {
        n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)
    }
    existing_edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    revision_errors = _plan_revision_errors(plan, existing_nodes, existing_edges)
    if revision_errors:
        return "refused", "\n- ".join([agent_text.message("plan.revision-targets-invalid")] + revision_errors), None
    remove_node_set = set(remove_nodes)
    # #662: widgets and scenarios against the saved dataflow; each scenario
    # takes its color here, so the review card shows it.
    scenarios = plan_scenarios.existing_scenarios(spec)
    scenario_errors = plan_scenarios.mint_errors(plan, available, existing_nodes, scenarios)
    if scenario_errors:
        return "refused", "\n- ".join([agent_text.message("plan.widgets-scenarios-invalid")] + scenario_errors), None
    plan_scenarios.assign_colors(plan, scenarios)
    # dev/67-3 (DEC-051): fan-in validates BEFORE anything materializes — an
    # invalid multi-input topology is unmintable, and the corrective error
    # says how to rewire it.
    fanin_errors = _validate_plan_fanin(
        plan, available, existing_nodes, existing_edges,
        remove_node_set, set(remove_edges),
    )
    if fanin_errors:
        return "refused", "\n- ".join([agent_text.message("plan.fanin-invalid")] + fanin_errors), None
    refusal = _plan_topology_refusal(plan, existing_nodes, existing_edges, available, remove_node_set, remove_edges)
    if refusal:
        return "refused", refusal, None
    cascade_edge_ids = _plan_cascade_edge_ids(existing_edges, remove_node_set, remove_edges)
    positions = _plan_positions(plan, existing_nodes)
    _digest, pins = _plan_pins(spec, plan, existing_nodes)
    plan_id = uuid.uuid4().hex
    summary = _plan_summary(plan)
    part = _plan_review_part(plan_id, plan, existing_nodes, existing_edges, pins, summary, cascade_edge_ids)
    landing = {
        "proposalId": plan_id,
        "tool": "dataflow.plan.write",
        "plan": plan,
        # The mint-time layout of the plan's nodes.
        "positions": positions,
        # DEC-049.1: each node it removes, held to the code the mint read.
        **({"removeContentSha256": pins["removeContentSha256"]} if "removeContentSha256" in pins else {}),
        "summary": summary,
    }
    return agents_changes.land(user_key, project_id, loop_ctx, spec, landing, part)


def _victims_changed(user_key: str, project_id: str, plan: dict, landing: dict) -> str | None:
    """Why the plan cannot land when a node it removes holds other code than
    the mint read (DEC-049.1), as after waiting for a person in it; None when
    each holds what it did."""
    if not plan.get("removeNodes"):
        return None
    pins = landing.get("removeContentSha256") or {}
    fresh = dataflow_docs.live(user_key, project_id) or {}
    nodes = {n.get("id"): n for n in (fresh.get("dataflow") or {}).get("nodes") or [] if isinstance(n, dict)}
    for node_id in plan["removeNodes"]:
        victim = nodes.get(node_id)
        digest = hashlib.sha256(((victim or {}).get("content") or "").encode("utf-8")).hexdigest()
        if victim is None or digest != pins.get(node_id):
            label = ((victim or {}).get("goal") or node_id)[:60]
            return agent_text.message("change.plan-victim-changed", label=label)
    return None


def _closes_a_cycle_now(user_key: str, project_id: str, plan: dict) -> str | None:
    """Why the plan cannot land when one of its data edges would now close a
    cycle through a connection drawn after the mint read the dataflow, as
    while it waited for a person in a node it removes (dev/112, DEC-070);
    None when none would."""
    fresh = dataflow_docs.live(user_key, project_id) or {}
    dataflow = fresh.get("dataflow") or {}
    edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    closing = plan_topology.closing_plan_edges(
        plan_topology.net_data_edges(
            edges, plan, set(plan.get("removeNodes", [])), set(plan.get("removeEdges", [])),
        ),
        plan,
    )
    if not closing:
        return None
    _u, _v, path = closing[0]
    labels = {n.get("id"): (n.get("goal") or n.get("id")) for n in dataflow.get("nodes") or [] if isinstance(n, dict)}
    titles = {n["ref"]: n["title"] for n in plan.get("nodes", [])}
    cycle = plan_topology.format_cycle(path, lambda x: titles.get(x) or labels.get(x) or x)
    return agent_text.message("change.plan-closes-a-cycle", cycle=cycle)


def _scenarios_taken_now(user_key: str, project_id: str, plan: dict) -> str | None:
    """Why the plan cannot land when a scenario it saves would take a name,
    or a node, that a scenario saved after the mint read the dataflow has, as
    while it waited for a person in a node it removes (#662); None when none
    would."""
    planned = plan.get("scenarios") or []
    if not planned:
        return None
    current = plan_scenarios.existing_scenarios(dataflow_docs.live(user_key, project_id) or {})
    owner = {m for s in current for m in s["nodes"]}
    names = {s["name"] for s in current}
    for scenario in planned:
        if scenario["name"] in names or any(m in owner for m in scenario.get("nodes") or []):
            return agent_text.message("change.plan-scenario-taken", name=scenario["name"])
    return None


def _land_dataflow_plan(user_key: str, project_id: str, loop_ctx: dict, spec: dict, landing: dict, part: dict):
    """A dataflow plan, landed whole and at once (dev/52, dev/59), as the
    agent's change: its removals and the connections they cascade to, its
    nodes (at the mint-time layout, each with its template's starter or no
    code, and its agents, dev/126), its connections and its scenarios, in ONE
    write, so one transaction of the doc. Unlisted nodes keep their ids,
    places and code by construction. The planner's session then holds the
    plan, whose nodes Build & validate and Solve fill."""
    attachment_id = loop_ctx.get("attachment_id")
    plan = landing["plan"]
    plan_id = landing["proposalId"]
    refusal = (
        _victims_changed(user_key, project_id, plan, landing)
        or _closes_a_cycle_now(user_key, project_id, plan)
        or _scenarios_taken_now(user_key, project_id, plan)
    )
    if refusal:
        return "refused", refusal, None
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    edges = dataflow.setdefault("edges", [])
    spec_nodes_by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    remove_node_set = set(plan.get("removeNodes", []))
    planner = attachments.get_attachment(spec, attachment_id) or {}
    # What the planner held before: the Undo of this plan puts both back.
    session_before = copy.deepcopy(planner.get("builderSession") or {})
    plan_before = copy.deepcopy(planner.get("planProposal"))
    removed_edge_ids, pruned = _remove_plan_victims(spec, nodes, edges, remove_node_set, plan.get("removeEdges", []))
    starters = _content_starters(user_key, project_id, plan.get("nodes", []))
    declared = _declared_widgets(user_key, project_id, plan.get("nodes", []))
    plan_agents = _plan_node_agents(user_key, spec, agents_spec_reads._definition(user_key, planner.get("coord", "")))
    created_nodes, attached_results, ref_to_id = _create_plan_nodes(
        user_key, spec, nodes, plan, landing, starters,
        agents=plan_agents, templates=_roster_templates(user_key, project_id), declared=declared,
    )
    created_edges = _create_plan_edges(
        user_key, project_id, plan_id, spec, landing, loop_ctx.get("session_id"), plan, nodes, edges, ref_to_id,
        spec_nodes_by_id,
    )
    created_scenarios = plan_scenarios.apply_scenarios(spec, landing, ref_to_id, final=True)
    record, node_runs = _plan_apply_session(
        spec, attachment_id, plan_id, created_nodes, remove_node_set, ref_to_id, starters,
    )
    if record is not None:
        # Build & validate and the rows' Solve and Run work on this plan.
        record["builderSession"]["planProposalId"] = plan_id
        record["planProposal"] = {**landing, "status": "applied", "appliedNodeIds": dict(ref_to_id)}
    change = agents_changes.new_change(
        "dataflow.plan.write", landing["summary"], planId=plan_id,
        nodeIds=[n["id"] for n in created_nodes], edgeIds=[str(e["id"]) for e in created_edges],
        removedNodeIds=sorted(remove_node_set), removedEdgeIds=sorted(removed_edge_ids),
        scenarioIds=[s.get("id") for s in created_scenarios if isinstance(s, dict) and s.get("id")],
        session=session_before,
        **({"planBefore": plan_before} if isinstance(plan_before, dict) else {}),
    )
    agents_changes.keep(spec, attachment_id, change)
    dataflow_docs.write(user_key, project_id, spec, agents_changes.actor(user_key, spec, loop_ctx, "plan"),
                        point={"kind": history.AGENT, "what": "", "change": change["changeId"]})
    sessions.delete_sessions_of(user_key, project_id, pruned)
    agents_changes.landed(loop_ctx, change, {
        "kind": "graph-created", "planId": plan_id, "nodes": created_nodes, "edges": created_edges,
        "removedNodeIds": sorted(remove_node_set), "removedEdgeIds": sorted(removed_edge_ids),
        **({"scenarios": created_scenarios} if created_scenarios else {}),
    })
    text, lines = _plan_landed_lines(spec, created_nodes, created_edges, remove_node_set, removed_edge_ids,
                                     node_runs, attached_results, created_scenarios)
    return (agents_changes.LANDED, agent_text.message("change.plan-landed", result=text),
            agents_changes.card(part, change, lines))


def _normal(value):
    """*value*, each number a float: two reads of one dataflow are compared
    whatever form each gives a number."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        return {key: _normal(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normal(item) for item in value]
    return value


def _outside_the_plan(dataflow: dict, change: dict) -> dict:
    """What the doc holds of *dataflow* but the plan's own: its nodes, the
    connections it drew or that touch its nodes, its scenarios."""
    own = set(change.get("nodeIds") or [])
    own_edges = set(change.get("edgeIds") or [])
    own_scenarios = set(change.get("scenarioIds") or [])
    flow = doc_mapping.owned(dataflow)
    out = {key: value for key, value in flow.items() if key not in ("nodes", "edges", "scenarios")}
    out["nodes"] = {n.get("id"): n for n in flow.get("nodes") or [] if isinstance(n, dict) and n.get("id") not in own}
    out["edges"] = {
        str(e.get("id")): e for e in flow.get("edges") or []
        if isinstance(e, dict) and str(e.get("id")) not in own_edges
        and e.get("source") not in own and e.get("target") not in own
    }
    out["scenarios"] = [s for s in flow.get("scenarios") or [] if not (isinstance(s, dict) and s.get("id") in own_scenarios)]
    return _normal(out)


def _undo_plan(user_key: str, project_id: str, attachment_id: str, change: dict, by: dict) -> list[dict]:
    """Undo a plan an agent landed: put back the version the dataflow had
    before it (``history.put_back``), for every tab, so what it removed comes
    back with its connections and what it added goes. Refused, with nothing
    changed, unless the dataflow outside the plan's own nodes is still what
    the plan left: a put-back would erase what a person did after. The
    planner's session goes back to what it was."""
    from utk_curio.backend.app.projects import storage as projects_storage

    with projects_storage.spec_write_lock(user_key, project_id):
        points = history.points(user_key, project_id)
        index = next((i for i, p in enumerate(points) if p.get("change") == change["changeId"]), None)
        if index is None or not points[index].get("parent"):
            raise AgentServiceError("This plan is not in the dataflow's history; nothing was undone.", 409)
        then = history.dataflow_at(user_key, project_id, points[index]["id"])
        before = history.dataflow_at(user_key, project_id, points[index]["parent"])
        now = dataflow_docs.live(user_key, project_id)
        if then is None or before is None or now is None:
            raise AgentServiceError("This plan's version can no longer be rebuilt; nothing was undone.", 409)
        if _outside_the_plan(then, change) != _outside_the_plan(now.get("dataflow") or {}, change):
            later = next((p.get("by") for p in points[index + 1:] if (p.get("by") or {}).get("name")), None)
            name = (later or {}).get("name") or "Someone"
            raise AgentServiceError(f"{name} changed this dataflow after; nothing was undone.", 409)
        try:
            history.put_back(user_key, project_id, points[index]["parent"], by)
        except history.HistoryError as exc:
            raise AgentServiceError(str(exc), exc.status) from exc
    spec = agents_spec_reads._live_spec_or_404(user_key, project_id)
    record = attachments.get_attachment(spec, attachment_id)
    if record is not None:
        record["builderSession"] = copy.deepcopy(change.get("session") or {})
        if (record.get("planProposal") or {}).get("proposalId") == change.get("planId"):
            # The plan before it, when there was one, is the planner's again.
            if isinstance(change.get("planBefore"), dict):
                record["planProposal"] = copy.deepcopy(change["planBefore"])
            else:
                record.pop("planProposal", None)
    pruned = attachments.prune_orphaned_attachments(spec)
    dataflow_docs.write(user_key, project_id, spec, agents_spec_reads._person(user_key, "undo"))
    sessions.delete_sessions_of(user_key, project_id, pruned)
    removed = set(change.get("removedNodeIds") or [])
    removed_edges = set(change.get("removedEdgeIds") or [])
    return [{
        "kind": "graph-created", "planId": f"undo:{change['changeId']}",
        "nodes": [n for n in before.get("nodes") or [] if isinstance(n, dict) and n.get("id") in removed],
        "edges": [e for e in before.get("edges") or [] if isinstance(e, dict) and str(e.get("id")) in removed_edges],
        "removedNodeIds": list(change.get("nodeIds") or []),
        "removedEdgeIds": list(change.get("edgeIds") or []),
    }]


def _plan_revision_errors(plan: dict, existing_nodes: dict, existing_edges: list) -> list[str]:
    """Revision validation against the saved spec (dev/59): removal targets and existing-id edge
    endpoints must be real; the grammar could only check shape. Errors feed the same correction
    rounds as every plan failure."""
    existing_edge_ids = {str(e.get("id")) for e in existing_edges}
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    revision_errors: list[str] = []
    for node_id in remove_nodes:
        if node_id not in existing_nodes:
            revision_errors.append(
                agent_text.message("plan.remove-node-unknown", node_id=repr(node_id))
            )
    for edge_id in remove_edges:
        if edge_id not in existing_edge_ids:
            revision_errors.append(
                agent_text.message("plan.remove-edge-unknown", edge_id=repr(edge_id))
            )
    plan_refs = {n["ref"] for n in plan["nodes"]}
    for i, edge in enumerate(plan["edges"]):
        for label in ("from", "to"):
            endpoint = edge[label]
            if endpoint not in plan_refs and endpoint not in existing_nodes:
                revision_errors.append(
                    agent_text.message("plan.edge-endpoint-unknown", i=i, label=label, endpoint=repr(endpoint))
                )
    return revision_errors


def _plan_topology_refusal(plan: dict, existing_nodes: dict, existing_edges: list, available: dict,
                           remove_node_set: set, remove_edges: list) -> str | None:
    """dev/112 (DEC-070): the topology refusal, or None: an interaction edge must reach a node that
    shows the selection it carries, and no plan DATA edge may close a cycle in the NET graph;
    validated BEFORE anything materializes."""
    # dev/112 (DEC-070): topology validated BEFORE anything materializes, like
    # fan-in. (1) An interaction edge must reach a node that shows the
    # selection it carries (plan_topology.interaction_edge_errors): an
    # executable rule, not prose the model must infer. (2) No
    # plan DATA edge may close a cycle in the NET graph. Before this, an
    # agent asked to "make it an interaction edge" had its kind dropped by
    # the grammar and re-applied the same data edge — the same cycle — on
    # every round; the only enforcement was the execution runner's refusal,
    # which the agent never saw.
    plan_types = {n["ref"]: n["nodeType"] for n in plan["nodes"]}

    def _type_of_endpoint(endpoint: str):
        if endpoint in plan_types:
            return plan_types[endpoint]
        node = existing_nodes.get(endpoint)
        return node.get("type") if node else None

    net_pairs = plan_topology.net_data_edges(
        existing_edges, plan, remove_node_set, set(remove_edges)
    )
    # A Map Editor node's link is to a map it feeds once the plan applies.
    kind_errors = plan_topology.interaction_edge_errors(plan, _type_of_endpoint, available, net_pairs)
    if kind_errors:
        return "\n- ".join([agent_text.message("plan.interaction-edges-invalid")] + kind_errors)
    closing = plan_topology.closing_plan_edges(net_pairs, plan)
    if closing:
        def _label(node_id: str) -> str:
            return _plan_endpoint_label(node_id, plan, existing_nodes)
        cycle_errors = [
            agent_text.message(
                "plan.edge-closes-cycle", source=repr(_label(u)), target=repr(_label(v)),
                cycle=plan_topology.format_cycle(path, _label),
            )
            for u, v, path in closing[:5]
        ]
        return "\n- ".join(
                [agent_text.message("plan.creates-cycle")]
                + cycle_errors
                + [
                    agent_text.message("plan.cycle-remedy")
                ]
        )
    return None


def _plan_cascade_edge_ids(existing_edges: list, remove_node_set: set, remove_edges: list) -> list[str]:
    """The cascade: edges incident to removed nodes die with them (dev/59) — computed here for the
    review card, recomputed at apply as the truth."""
    return [
        str(e.get("id"))
        for e in existing_edges
        if (e.get("source") in remove_node_set or e.get("target") in remove_node_set)
        and str(e.get("id")) not in set(remove_edges)
    ]


def _plan_positions(plan: dict, existing_nodes: dict) -> dict[str, dict]:
    """dev/67-5: positions computed ONCE at mint, so per-node applies land exactly where the whole-plan
    apply would have put them (both read the same map). Extent from the pre-removal spec — victims
    may inflate it slightly; a stable layout beats a perfectly tight one."""
    right = _right_edge(existing_nodes.values())
    ys = [n.get("y") for n in existing_nodes.values() if isinstance(n.get("y"), (int, float))]
    layout_base_x = (right + _NODE_H_GUTTER) if right is not None else 80.0
    layout_base_y = min(ys) if ys else 80.0
    layout_depths = _plan_depths(plan["nodes"], plan["edges"])
    layout_rows: dict[int, int] = {}
    positions: dict[str, dict] = {}
    for node in plan["nodes"]:
        depth = layout_depths.get(node["ref"], 0)
        row = layout_rows.get(depth, 0)
        layout_rows[depth] = row + 1
        positions[node["ref"]] = {
            "x": float(layout_base_x + depth * _PLAN_COLUMN_OFFSET),
            "y": float(layout_base_y + row * _PLAN_ROW_OFFSET),
        }
    return positions


def _plan_pins(spec: dict, plan: dict, existing_nodes: dict) -> tuple[str, dict]:
    """The shape digest the apply re-checks and, for removals, every victim pinned by its content at
    mint (DEC-049.1) — editing a doomed node between mint and apply makes the apply 409 + stale."""
    remove_nodes = plan.get("removeNodes", [])
    digest = agents_spec_reads._graph_shape_digest(spec)
    pins: dict = {"baseGraphDigest": digest}
    if remove_nodes:
        # DEC-049.1: every victim pinned by its content at mint — editing a
        # doomed node between mint and apply makes the apply 409 + stale.
        pins["removeContentSha256"] = {
            node_id: hashlib.sha256(
                (existing_nodes[node_id].get("content") or "").encode("utf-8")
            ).hexdigest()
            for node_id in remove_nodes
        }
    return digest, pins


def _plan_summary(plan: dict) -> str:
    """The plan card's one-line summary: counts, and removals named (dev/112)."""
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    n_nodes, n_edges = len(plan["nodes"]), len(plan["edges"])
    summary = f"Plan · {count_label(n_nodes, 'node')}, {count_label(n_edges, 'edge')}"
    if plan.get("scenarios"):
        summary += f", {count_label(len(plan['scenarios']), 'scenario')}"
    if remove_nodes or remove_edges:
        # dev/112: removed connections counted too — the user approved edge
        # removals five times without seeing them named.
        summary += _removal_phrase(len(remove_nodes), len(remove_edges), prefix="removes ")
    return summary


def _plan_review_part(proposal_id: str, plan: dict, existing_nodes: dict, existing_edges: list,
                      pins: dict, summary: str, cascade_edge_ids: list) -> dict:
    """The proposal part the review card renders: the preview, the display copy of the plan (edges by
    NAME, dev/67-8), and the removals reviewed by name (DEC-049.2; edges too, dev/112)."""
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    n_edges = len(plan["edges"])
    in_scenario = plan_scenarios.scenario_names(plan)
    preview_lines = [
        f"{node['title']} · {node['nodeType']} — {node['intent']}" for node in plan["nodes"]
    ]
    # A node's settings, each in its node's words, on its own line's end: a
    # Spatial Join's operation and output, a Data Pool's modes, a Simple
    # View's image column.
    for index, node in enumerate(plan["nodes"]):
        for words in node_settings.describe(node):
            preview_lines[index] += f" · {words}"
    preview_lines += plan_scenarios.preview_lines(plan)
    for node_id in remove_nodes:
        victim = existing_nodes[node_id]
        label = (victim.get("goal") or node_id)[:80]
        # A pinned victim is a dashboard tile, which its removal takes off the dashboard.
        tile = " · a dashboard tile, which leaves the dashboard" if dashboards.is_pinned(victim) else ""
        preview_lines.append(f"− Remove: {label} · {victim.get('type') or 'untyped'}{tile}")
    part = content.make_proposal_part(
        proposal_id=proposal_id,
        tool="dataflow.plan.write",
        summary=summary,
        preview="\n".join(preview_lines),
        pins=pins,
    )
    # The display copy for the review card (bounded upstream by the grammar).
    part["plan"] = {
        "goal": plan["goal"],
        **({"templateId": plan["templateId"]} if plan.get("templateId") else {}),
        "nodes": [
            {
                "ref": n["ref"], "nodeType": n["nodeType"], "title": n["title"],
                "intent": n["intent"],
                **({"expects": n["expects"]} if n.get("expects") else {}),
                # #662: its widgets, its scenario, and the node a copy copies.
                **plan_scenarios.node_display(n, in_scenario),
            }
            for n in plan["nodes"]
        ],
        "edgeCount": n_edges,
        # dev/67-8: the connection stage reviews edges BY NAME — labels from
        # plan titles (refs) or spec goals (existing ids), index-stable.
        "edges": [
            {
                "from": e["from"],
                "to": e["to"],
                **({"toHandle": e["toHandle"]} if e.get("toHandle") else {}),
                **({"kind": e["kind"]} if e.get("kind") else {}),  # dev/112
                "fromLabel": _plan_endpoint_label(e["from"], plan, existing_nodes),
                "toLabel": _plan_endpoint_label(e["to"], plan, existing_nodes),
            }
            for e in plan["edges"]
        ],
    }
    if plan.get("scenarios"):
        # #662: the scenarios the plan saves, each with its nodes by name.
        part["plan"]["scenarios"] = plan_scenarios.display_scenarios(plan, existing_nodes)
    if remove_nodes or remove_edges:
        # DEC-049.2: removals reviewed by NAME — every victim listed with a
        # content flag; the cascade counted.
        part["plan"]["removals"] = [
            {
                "id": node_id,
                "label": (existing_nodes[node_id].get("goal") or node_id)[:80],
                "nodeType": existing_nodes[node_id].get("type"),
                "contentChars": len(existing_nodes[node_id].get("content") or ""),
                # Only on a dashboard tile, which leaves the dashboard.
                **({"pinned": True} if dashboards.is_pinned(existing_nodes[node_id]) else {}),
            }
            for node_id in remove_nodes
        ]
        part["plan"]["removedEdgeCount"] = len(remove_edges)
        part["plan"]["cascadeCount"] = len(cascade_edge_ids)
        # dev/112: removed connections reviewed by NAME too (DEC-049.2 applied
        # to edges) — endpoint labels from the saved spec, kind preserved.
        edges_by_id = {str(e.get("id")): e for e in existing_edges}
        part["plan"]["removedEdges"] = [
            {
                "id": edge_id,
                "fromLabel": _plan_endpoint_label(str(edges_by_id[edge_id].get("source")), plan, existing_nodes),
                "toLabel": _plan_endpoint_label(str(edges_by_id[edge_id].get("target")), plan, existing_nodes),
                **(
                    {"kind": "interaction"}
                    if plan_topology.is_interaction_edge(edges_by_id[edge_id])
                    else {}
                ),
            }
            for edge_id in remove_edges
            if edge_id in edges_by_id
        ]
    return part


def _attach_node_agent(
    user_key: str | None, spec: dict, agent_id: str, node_id: str, node_type: object,
    *, templates: dict | None = None,
) -> dict:
    """Attach ONE agent to a node, idempotently, reporting what happened.

    dev/126: the shared body of dev/71's plan-node attachment. Whether the
    agent lives on that node is its manifest's node target
    (``attachments.node_target_matches``, read against the project's roster
    snapshot *templates*). Returns ``{"agentId", "name", "attachmentId" |
    None, "status": "attached" | "existing" | "skipped", "reason"?}``. Never
    raises and never writes the spec: the caller's own single write persists
    it, and a node is never blocked over its agent."""
    coord = agents_spec_reads._installed_project_coord(spec, agent_id)
    manifest = agents_spec_reads._definition(user_key, coord) if coord else None
    name = getattr(manifest, "name", None) or agent_id
    existing = agents_spec_reads._node_attachment_of(spec, agent_id, node_id)
    if existing is not None:
        return {
            "agentId": agent_id,
            "name": name,
            "attachmentId": existing.get("attachmentId"),
            "status": "existing",
        }
    if coord is None:
        return {"agentId": agent_id, "name": name, "attachmentId": None, "status": "skipped",
                "reason": "not installed in this dataflow"}
    if manifest is not None and not attachments.node_target_matches(manifest, node_type, templates):
        return {"agentId": agent_id, "name": name, "attachmentId": None, "status": "skipped",
                "reason": f"does not attach to {attachments.canonical_node_suffix(node_type)} nodes"}
    try:
        record = attachments.attach(
            spec, coord, {"kind": "node", "targetId": node_id},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not attach %s to node %s: %s", agent_id, node_id, exc)
        return {"agentId": agent_id, "name": name, "attachmentId": None, "status": "skipped",
                "reason": str(exc)[:120]}
    return {"agentId": agent_id, "name": name, "attachmentId": record.get("attachmentId"),
            "status": "attached"}


def _roster_templates(user_key: str, project_id: str) -> dict | None:
    """The project's template roster snapshot, or None when it is unreadable
    (``packages.roster_templates``): what a node target's template flags are
    read against."""
    from utk_curio.backend.app.packages import service as packages_services

    return packages_services.roster_templates(user_key, project_id)


def _plan_node_agents(user_key: str | None, spec: dict, parent=None) -> list[dict]:
    """dev/126: the agents a plan-created node carries, one per capability
    Solve asks for (``content.SOLVE_CAPABILITIES``), in that order: the agent
    that writes the node's content, then the one that finds its datasets.

    Each is the agent *parent*, the agent whose plan it is, delegates that
    capability to among the dataflow's installed agents
    (``delegation.resolve_among``); with no parent, the first installed agent
    that declares it. Which of them lives on a given node is its manifest's
    node target, read when it is attached. Returns ``{"capability", "agentId",
    "name", "installed"}`` per capability that some agent does; an agent that
    is not installed is the visible one that would do it."""
    installed = set(project_agents.project_agents(spec))
    agents: list[dict] = []
    for capability in content.SOLVE_CAPABILITIES:
        coord, manifest, is_installed = None, None, False
        if parent is not None and user_key:
            found = delegation.resolve_among(user_key, installed, parent, capability)
            coord, manifest, is_installed = found.coord, found.manifest, found.outcome == "ok"
        else:
            coord = agents_spec_reads._installed_coord_declaring(spec, capability, user_key=user_key)
            if coord is not None:
                manifest, is_installed = agents_spec_reads._definition(user_key, coord), True
            else:
                manifest = next((
                    m for m in builtin.list_builtin_manifests()
                    if capability in m.capability_ids and not builtin.is_internal(m.dir_name)
                ), None)
                coord = getattr(manifest, "dir_name", None)
        # An internal agent runs only as a delegate: it is never attached.
        if not coord or builtin.is_internal(coord):
            continue
        agents.append({
            "capability": capability,
            "agentId": coord.split("@", 1)[0],
            "name": getattr(manifest, "name", None) or coord.split("@", 1)[0],
            "installed": is_installed,
        })
    return agents


def _attach_plan_node_agents(
    user_key: str | None, spec: dict, node_id: str, node_type: object,
    *, parent=None, templates: dict | None = None, agents: list[dict] | None = None,
) -> dict:
    """dev/126: every plan-created node gets its agents (``_plan_node_agents``,
    or *agents* when the caller resolved them once for the whole apply): the
    content agent always, the dataset agent when the node's template loads a
    dataset. On BOTH apply paths, idempotently, in the caller's own spec write.

    Returns ``{"attached": [row], "skipped": [row], "byAgent": {agentId: id},
    "byCapability": {capability: id}}`` so the apply can SAY what it attached
    instead of silently dropping it."""
    rows: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for agent in agents if agents is not None else _plan_node_agents(user_key, spec, parent):
        if agent["agentId"] in seen:
            continue  # one agent that does both is attached once
        seen.add(agent["agentId"])
        if agent["installed"]:
            row = _attach_node_agent(
                user_key, spec, agent["agentId"], node_id, node_type, templates=templates,
            )
        else:
            row = {"agentId": agent["agentId"], "name": agent["name"], "attachmentId": None,
                   "status": "skipped", "reason": "not installed in this dataflow"}
        rows.append((agent["capability"], row))
    return {
        "attached": [
            {"nodeId": node_id, **r} for _, r in rows if r["status"] in ("attached", "existing")
        ],
        "skipped": [{"nodeId": node_id, **r} for _, r in rows if r["status"] == "skipped"],
        "byAgent": {
            r["agentId"]: r["attachmentId"] for _, r in rows if r.get("attachmentId")
        },
        "byCapability": {
            capability: r["attachmentId"] for capability, r in rows if r.get("attachmentId")
        },
    }


def _attached_agent_lines(*results: dict) -> list[str]:
    """The applied card's truthful account of the agents an apply attached
    (dev/126): one line naming each agent, as its manifest names it, and how
    many nodes carry it, plus a line for anything that could not be
    attached, with its reason."""
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for result in results:
        for row in result.get("attached") or []:
            counts[row["agentId"]] = counts.get(row["agentId"], 0) + 1
            names.setdefault(row["agentId"], row.get("name") or row["agentId"])
        for row in result.get("skipped") or []:
            skipped.setdefault(row["agentId"], row.get("reason") or "skipped")
            names.setdefault(row["agentId"], row.get("name") or row["agentId"])
    lines: list[str] = []
    if counts:
        lines.append("agents attached: " + " · ".join(
            f"{names[a]} ×{n}" if n > 1 else names[a]
            for a, n in sorted(counts.items())
        ))
    for agent_id, reason in sorted(skipped.items()):
        lines.append(f"no {names[agent_id]}: {reason}")
    return lines


def _attach_node_builder(spec: dict, node_id: str, *, user_key: str | None = None,
                         node_type: object = None, templates: dict | None = None) -> str | None:
    """dev/71: best-effort attachment of the node's content agent, the
    installed agent that declares ``node.content.generate``. Skips (returning
    None) when none is installed or it cannot live on the node; node creation
    NEVER fails over this. An attachment it already has is returned."""
    coord = agents_spec_reads._installed_coord_declaring(
        spec, "node.content.generate", user_key=user_key,
    )
    if coord is None:
        return None
    row = _attach_node_agent(
        user_key, spec, coord.split("@", 1)[0], node_id, node_type, templates=templates,
    )
    return row.get("attachmentId")


def _plan_endpoint_label(endpoint: str, plan: dict, existing_nodes: dict) -> str:
    """A human label for one plan-edge endpoint: the plan node's title, or the
    existing node's goal (id as the last resort). #662: a planned node in a
    scenario is labelled with it too, so a copy and its original read apart."""
    for node in plan.get("nodes", []):
        if node["ref"] == endpoint:
            scenario = plan_scenarios.scenario_names(plan).get(endpoint)
            return node["title"][:60] + (f" ({scenario})" if scenario else "")
    existing = existing_nodes.get(endpoint) or {}
    return str(existing.get("goal") or endpoint)[:60]


def _existing_plan_edge(edges: list, plan_edges: list, index: int, source: str, target: str,
                        doomed: frozenset | set = frozenset()) -> dict | None:
    """The dataflow's connection that plan edge *index*, from *source* to
    *target*, already is, or None: one a row drew, or the user. It is one of
    the same two ends, kind and input circle. An edge that names its circle
    (``toHandle``) is on that circle; one that names none is on a circle no
    other plan edge between the same two ends names, so a node fed twice by
    one node (a Spatial Join of a layer with itself) keeps both feeds. An edge
    the plan removes (*doomed*) does not count. A plan that lands creates none
    for such an edge."""
    plan_edge = plan_edges[index]
    interaction = plan_topology.is_interaction_edge(plan_edge)
    named = plan_edge.get("toHandle")
    taken = {
        other.get("toHandle") for i, other in enumerate(plan_edges)
        if i != index and other.get("toHandle")
        and other["from"] == plan_edge["from"] and other["to"] == plan_edge["to"]
        and not plan_topology.is_interaction_edge(other)
    }
    for e in edges:
        if not isinstance(e, dict) or str(e.get("id")) in doomed:
            continue
        if e.get("source") != source or e.get("target") != target:
            continue
        if plan_topology.is_interaction_edge(e) != interaction:
            continue
        circle = e.get("targetHandle") or "in"
        if interaction or (circle == named if named else circle not in taken):
            return e
    return None


# A node's box as the canvas draws it when the node sets no size of its own
# (DEFAULT_NODE_WIDTH/HEIGHT, frontend src/constants.ts), and the gutters the
# shipped examples are laid out with (scripts/tidy_example_layout.py). Steps
# smaller than the box put every placed node on top of its neighbour (#499,
# #410).
_NODE_WIDTH = 525
_NODE_HEIGHT = 350
_NODE_H_GUTTER = 120
_NODE_V_GUTTER = 80


def _right_edge(nodes) -> float | None:
    """The rightmost edge of the placed nodes, each at its own width, or None."""
    edges = [
        float(n["x"]) + float(n["width"] if isinstance(n.get("width"), (int, float)) else _NODE_WIDTH)
        for n in nodes
        if isinstance(n, dict) and isinstance(n.get("x"), (int, float))
    ]
    return max(edges) if edges else None


# Plan layout (dev/52): topological columns right of the existing extent.
_PLAN_COLUMN_OFFSET = _NODE_WIDTH + _NODE_H_GUTTER
_PLAN_ROW_OFFSET = _NODE_HEIGHT + _NODE_V_GUTTER


def _plan_depths(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Longest-path depth per plan ref (plans are small DAGs; a cycle — which
    the grammar allows structurally — degrades to BFS-capped depths, never an
    infinite loop)."""
    refs = [n["ref"] for n in nodes]
    incoming: dict[str, list[str]] = {r: [] for r in refs}
    for e in edges:
        # dev/59: endpoints may name EXISTING nodes — only plan-local wiring
        # contributes to layout depth (existing nodes keep their positions).
        if e["to"] in incoming and e["from"] in incoming:
            incoming[e["to"]].append(e["from"])
    depths: dict[str, int] = {}

    def depth_of(ref: str, seen: frozenset) -> int:
        if ref in depths:
            return depths[ref]
        if ref in seen:
            return 0  # cycle guard
        parents = incoming.get(ref, [])
        d = 0 if not parents else 1 + max(depth_of(p, seen | {ref}) for p in parents)
        depths[ref] = d
        return d

    for r in refs:
        depth_of(r, frozenset())
    return depths


def _remove_plan_victims(spec: dict, nodes: list, edges: list, remove_node_set: set,
                         remove_edges: list) -> tuple[set, list]:
    """Removals first (dev/59): listed edges + the recomputed cascade of edges incident to removed
    nodes, then the victims themselves, in place, so unlisted elements are untouched by construction.
    Answers the removed edge ids and the attachments removed with their nodes, whose transcripts the
    caller deletes once its write lands (``sessions.delete_sessions_of``)."""
    removed_edge_ids = set(remove_edges)
    for e in edges:
        if isinstance(e, dict) and (
            e.get("source") in remove_node_set or e.get("target") in remove_node_set
        ):
            removed_edge_ids.add(str(e.get("id")))
    if removed_edge_ids:
        edges[:] = [e for e in edges if str(e.get("id")) not in removed_edge_ids]
    pruned: list = []
    if remove_node_set:
        nodes[:] = [n for n in nodes if n.get("id") not in remove_node_set]
        # Agent attachments on removed nodes die with them, exactly as manual
        # canvas deletion (dev/32), and so do their transcripts.
        pruned = attachments.prune_orphaned_attachments(spec)
    return removed_edge_ids, pruned


def _create_plan_nodes(user_key, spec: dict, nodes: list, plan: dict, proposal: dict,
                       starters: dict, *, agents: list[dict] | None = None,
                       templates: dict | None = None,
                       declared: dict | None = None) -> tuple[list, list, dict]:
    """The plan's new nodes at the mint-time layout (+ review-stage overlays). A ref a row applied
    is a node of the dataflow already: it is not created again, and its id seeds the edge
    resolution, as a connection already there is not drawn again (``_create_plan_edges``). Each
    created node gets its agents (*agents*, ``_plan_node_agents``) in THIS apply's single spec
    write (dev/126). A ref in *starters* starts with its template's starter and widgets
    (``_content_starters``); every other ref with its template's declared widgets (*declared*,
    ``_declared_widgets``)."""
    right = _right_edge(nodes)
    ys = [n.get("y") for n in nodes if isinstance(n, dict) and isinstance(n.get("y"), (int, float))]
    base_x = (right + _NODE_H_GUTTER) if right is not None else 80.0
    base_y = min(ys) if ys else 80.0
    depths = _plan_depths(plan.get("nodes", []), plan.get("edges", []))
    rows: dict[int, int] = {}
    # dev/67-5: the mint-time layout + review-stage overlays; the refs rows
    # applied are REAL nodes, skipped here, whose ids seed the edge
    # resolution so mixed per-node/whole-plan flows wire correctly.
    positions = proposal.get("positions") or {}
    edited_goals = proposal.get("editedGoals") or {}
    ref_to_id: dict[str, str] = dict(proposal.get("appliedNodeIds") or {})
    in_dataflow = {n.get("id") for n in nodes if isinstance(n, dict) and n.get("id")}
    created_nodes: list[dict] = []
    attached_results: list[dict] = []
    for plan_node in plan.get("nodes", []):
        depth = depths.get(plan_node["ref"], 0)
        row = rows.get(depth, 0)
        rows[depth] = row + 1
        if ref_to_id.get(plan_node["ref"]) in in_dataflow:
            continue
        node_id = str(uuid.uuid4())
        ref_to_id[plan_node["ref"]] = node_id
        pos = positions.get(plan_node["ref"]) or {}
        starter = starters.get(plan_node["ref"])
        created = {
            "id": node_id,
            "type": plan_node["nodeType"],
            "content": starter["content"] if starter else plan_node.get("content", ""),
            "goal": edited_goals.get(plan_node["ref"])
            or f"{plan_node['title']} — {plan_node['intent']}",
            "x": float(pos.get("x", base_x + depth * _PLAN_COLUMN_OFFSET)),
            "y": float(pos.get("y", base_y + row * _PLAN_ROW_OFFSET)),
        }
        # #662: its widgets, and for a copy its lineage; a copy follows the
        # node it copies in the plan, so that node is already created.
        metadata = plan_scenarios.created_node_metadata(
            plan_node, ref_to_id, nodes, starter, (declared or {}).get(plan_node["ref"]),
        )
        if metadata:
            created["metadata"] = metadata
        nodes.append(created)
        created_nodes.append(created)
        # dev/126: the whole-plan apply gives every created node its agents,
        # in THIS apply's single spec write — the per-node path has done so
        # since dev/71 and the two must not disagree.
        attached_results.append(
            _attach_plan_node_agents(
                user_key, spec, node_id, plan_node["nodeType"], agents=agents, templates=templates,
            )
        )
    return created_nodes, attached_results, ref_to_id


def _create_plan_edges(user_key, project_id, proposal_id, spec: dict, proposal: dict, session_id, plan: dict,
                       nodes: list, edges: list, ref_to_id: dict, spec_nodes_by_id: dict) -> list:
    """The plan's edges: endpoints resolve through the ref map ∪ existing ids (dev/59); handles are
    explicit end-to-end (DEC-051): an edge into a node with several inputs gets a deterministic
    free circle; an interaction edge (dev/112) takes no port and no circle. An edge a row applied,
    or one already in the dataflow on its circle (``_existing_plan_edge``), is not drawn again."""
    # dev/67-3 (DEC-051): handles are explicit end-to-end. An edge into a
    # growing node gets a deterministic free circle (a named free toHandle
    # wins; occupied or unnamed falls to the lowest free); the bridge passes
    # these through instead of hardcoding "in", which left circles unfilled
    # until a reload healed them.
    from utk_curio.backend.app.packages import service as packages_services

    types_by_id = {
        n.get("id"): _strip_type_version(str(n.get("type") or ""))
        for n in nodes
        if isinstance(n, dict)
    }
    try:
        available = {
            t["id"]: t
            for t in packages_services.available_templates(user_key, project_id)
        }
    except Exception:
        available = {}  # arity metadata unavailable: every edge keeps "in"
    circles_taken: dict[str, set[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        if str(e.get("type") or "") != "Interaction" and _takes_circles(available.get(types_by_id.get(e.get("target")))):
            circles_taken.setdefault(e.get("target"), set()).add(e.get("targetHandle") or "in")
    created_edges: list[dict] = []
    # A connection a row applied, or one the dataflow held before this apply
    # (a row drew it, or the user did), is not drawn again: no node is fed
    # twice by one plan edge. What this apply draws never stands in for
    # another plan edge, so a node fed twice by one node keeps both feeds.
    edge_states = proposal.get("edgeStates") or {}
    before = list(edges)
    plan_edges = plan.get("edges", [])
    for index, plan_edge in enumerate(plan_edges):
        # dev/59: endpoints resolve through the ref map ∪ existing ids.
        source = ref_to_id.get(plan_edge["from"], plan_edge["from"])
        target = ref_to_id.get(plan_edge["to"], plan_edge["to"])
        if edge_states.get(str(index)) == "applied" or _existing_plan_edge(
            before, plan_edges, index, source, target,
        ) is not None:
            continue
        if plan_topology.is_interaction_edge(plan_edge):
            # dev/112: the Trill's feedback edge — in/out handles both ends,
            # type Interaction (what loadTrill/TrillGenerator round-trip); no
            # input port, no input circle.
            edge = _interaction_spec_edge(source, target)
            edges.append(edge)
            created_edges.append(edge)
            continue
        target_handle = plan_edge.get("toHandle") or "in"
        if _takes_circles(available.get(types_by_id.get(target))):
            # Each edge into a growing or several-port node takes a circle of its own.
            taken = circles_taken.setdefault(target, set())
            target_handle = _free_circle(taken, plan_edge.get("toHandle"))
            taken.add(target_handle)
        edge = {
            "id": str(uuid.uuid4()),
            "source": source,
            "target": target,
            "sourceHandle": "out",
            "targetHandle": target_handle,
        }
        edges.append(edge)
        created_edges.append(edge)
    return created_edges


def _plan_apply_session(spec: dict, attachment_id: str, proposal_id: str, created_nodes: list,
                        remove_node_set: set, ref_to_id: dict, starters: dict) -> tuple[dict | None, dict]:
    """The builder session (DR-2, merged per dev/59): removed victims leave nodeRuns; surviving prior
    entries persist; new pending nodes join; every ref's ledger row completes (dev/67-5), approved
    for a ref in *starters*."""
    # The builder session (DR-2, merged per dev/59): removed victims leave
    # nodeRuns; surviving prior entries persist; new pending nodes join.
    record = attachments.get_attachment(spec, attachment_id)
    prior_runs = (
        (record.get("builderSession") or {}).get("nodeRuns") or {} if record else {}
    )
    node_runs = {
        node_id: status
        for node_id, status in prior_runs.items()
        if node_id not in remove_node_set
    }
    node_runs.update({n["id"]: "pending" for n in created_nodes if _awaits_solve(n)})
    unresolved = any(s in ("pending", "failed") for s in node_runs.values())
    if record is not None:
        record["builderSession"] = {
            "phase": "applied" if unresolved else "ready",
            "appliedPlanId": proposal_id,
            "nodeRuns": node_runs,
            # dev/67-5: the whole-plan apply completes every ref's ledger row.
            "nodeStates": {ref: _created_state(ref, starters) for ref in ref_to_id},
            "nodeIds": dict(ref_to_id),
        }
    return record, node_runs


def _plan_landed_lines(spec: dict, created_nodes: list, created_edges: list, remove_node_set: set,
                       removed_edge_ids: set, node_runs: dict, attached_results: list,
                       created_scenarios: list = ()) -> tuple[str, list[str]]:
    """What a landed plan did, for the model and for its card: truthful for
    connections (dev/112), the topology verdict the agent needs to confirm a
    fix instead of asserting one, and the scenarios it saved (#662)."""
    removed_summary = _removal_phrase(len(remove_node_set), len(removed_edge_ids))
    topology = _topology_clause(spec)
    scenario_summary = (
        f" It saved {count_label(len(created_scenarios), 'scenario')}: "
        + ", ".join(s["name"] for s in created_scenarios) + "."
        if created_scenarios else ""
    )
    text = (
        f"the plan added {count_label(len(created_nodes), 'node')} and "
        f"{count_label(len(created_edges), 'connection')}{removed_summary}.{scenario_summary} {topology}"
    )
    lines = [
        f"+{count_label(len(created_nodes), 'node')} · +{count_label(len(created_edges), 'connection')}"
        + (f" · +{count_label(len(created_scenarios), 'scenario')}" if created_scenarios else "")
        + (f" · −{count_label(len(remove_node_set), 'node')}" if remove_node_set else "")
        + (f" · −{count_label(len(removed_edge_ids), 'connection')}" if removed_edge_ids else ""),
        f"{sum(1 for s in node_runs.values() if s == 'pending')} pending for Build & validate or Solve",
        *_attached_agent_lines(*attached_results),
        topology,
    ]
    return text, lines

