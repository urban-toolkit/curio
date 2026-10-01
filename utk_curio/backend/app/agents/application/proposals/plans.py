"""Dataflow plans: minting, fan-in validation, goal edits, per-node and per-edge apply, node-agent attachment, and layout.

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import logging
import hashlib
import re as _re
import uuid

from utk_curio.backend.app.agents.application import attachments
from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain import content
from utk_curio.backend.app.agents.domain import plan_topology
from utk_curio.backend.app.agents.domain.counts import count_label
from utk_curio.backend.app.agents.repositories import sessions
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.application import spec_reads as agents_spec_reads
from utk_curio.backend.app.agents.application.proposals import store as agents_store
from utk_curio.backend.app.projects import storage as projects_storage

log = logging.getLogger(__name__)


# Merge slot handles as the canvas renders them (mergeFlowBehavior in_0..in_4).
_MERGE_HANDLE_RE = _re.compile(r"^in_[0-4]$")


_MERGE_NODE_TYPE = "curio.builtin/merge-flow"


def _strip_type_version(node_type: str) -> str:
    """``curio.builtin/merge-flow@1`` → ``curio.builtin/merge-flow`` — spec
    node types may carry the versioned form; the template registry is
    unversioned-canonical."""
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else node_type


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
    excluded) — against the template registry's rendered capacity. Refusals
    name the Merge resolution so the corrective round can replan; unknown or
    out-of-scope templates fail open (no arity metadata → no refusal)."""
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
            f" (plus {existing_count} existing connection"
            f"{'s' if existing_count != 1 else ''})"
            if existing_count
            else ""
        )
        if max_in == 0:
            errors.append(
                f"target {label!r} ({node_type}) accepts no inputs — remove the "
                f"edge(s) from {src_list}"
            )
        elif max_in == 1:
            errors.append(
                f"target {label!r} ({node_type}) accepts 1 input but the plan wires "
                f"{total}{existing_note} — route {src_list} through a "
                f"{_MERGE_NODE_TYPE} node instead (A → Merge, B → Merge, "
                "Merge → target)"
            )
        else:
            errors.append(
                f"target {label!r} ({node_type}) accepts at most {max_in} inputs "
                f"but the plan wires {total}{existing_note} — reduce the fan-in "
                "or stage merges"
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
        if node_type == _MERGE_NODE_TYPE and not _MERGE_HANDLE_RE.match(handle):
            errors.append(
                f"edges[{i}].toHandle {handle!r}: merge inputs are in_0..in_4"
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
        return "refused", "proposals need a persistent conversation", None
    # dev/67-5: plans describe intent — generated code never rides a plan.
    # There is no "trivial code" shortcut (67-0): every node's content is
    # produced and validated per node after creation. Supersedes dev/52's
    # plan-carried-content allowance at its recorded revisit point.
    content_refs = [n["ref"] for n in plan["nodes"] if n.get("content")]
    if content_refs:
        return (
            "refused",
            "plan nodes must not carry content — plans describe intent; node "
            "content is generated and validated per node after creation. "
            f"Remove the content from: {', '.join(repr(r) for r in content_refs)}",
            None,
        )
    try:
        available = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        return "refused", f"the node template registry is unavailable: {exc}", None
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
            return "refused", f"plan node {node['ref']!r}: {err}", None
    spec = projects_storage.read_spec(user_key, project_id)
    if spec is None:
        return "refused", "no saved project spec is available", None
    # Revision validation against the saved spec (dev/59): removal targets and
    # existing-id edge endpoints must be real; the grammar could only check
    # shape. Errors feed the same correction rounds as every plan failure.

    dataflow = spec.get("dataflow") or {}
    existing_nodes = {
        n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)
    }
    existing_edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    existing_edge_ids = {str(e.get("id")) for e in existing_edges}
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    revision_errors = _plan_revision_errors(plan, existing_nodes, existing_edges)
    if revision_errors:
        return "refused", "\n- ".join(["the plan's revision targets are invalid:"] + revision_errors), None
    remove_node_set = set(remove_nodes)
    # dev/67-3 (DEC-051): fan-in validates BEFORE anything materializes — an
    # invalid multi-input topology is unmintable, and the corrective error
    # names the Merge resolution.
    fanin_errors = _validate_plan_fanin(
        plan, available, existing_nodes, existing_edges,
        remove_node_set, set(remove_edges),
    )
    if fanin_errors:
        return "refused", "\n- ".join(["the plan wires invalid fan-in:"] + fanin_errors), None
    refusal = _plan_topology_refusal(plan, existing_nodes, existing_edges, available, remove_node_set, remove_edges)
    if refusal:
        return "refused", refusal, None
    cascade_edge_ids = _plan_cascade_edge_ids(existing_edges, remove_node_set, remove_edges)
    positions = _plan_positions(plan, existing_nodes)
    digest, pins = _plan_pins(spec, plan, existing_nodes)
    proposal_id = uuid.uuid4().hex
    n_edges = len(plan["edges"])
    summary = _plan_summary(plan)
    part = _plan_review_part(proposal_id, plan, existing_nodes, existing_edges, pins, summary, cascade_edge_ids)
    _enter_plan_review(spec, loop_ctx, proposal_id, plan)
    agents_store._store_proposal(
        user_key,
        project_id,
        spec,
        loop_ctx,
        {
            "proposalId": proposal_id,
            "tool": "dataflow.plan.write",
            "plan": plan,
            "baseGraphDigest": digest,
            # dev/67-5: per-node application state + the mint-time layout.
            "positions": positions,
            "editedGoals": {},
            "appliedRefs": [],
            "appliedNodeIds": {},
            # DEC-049.1: the apply re-checks each victim against this mirror.
            **(
                {"removeContentSha256": pins["removeContentSha256"]}
                if "removeContentSha256" in pins
                else {}
            ),
            "summary": summary,
            "status": "pending",
        },
        part,
    )
    return "proposed", "", part


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
                f"removeNodes: {node_id!r} is not a node in the saved dataflow — "
                "use real node ids (dataflow.read shows them)"
            )
    for edge_id in remove_edges:
        if edge_id not in existing_edge_ids:
            revision_errors.append(
                f"removeEdges: {edge_id!r} is not an edge in the saved dataflow"
            )
    plan_refs = {n["ref"] for n in plan["nodes"]}
    for i, edge in enumerate(plan["edges"]):
        for label in ("from", "to"):
            endpoint = edge[label]
            if endpoint not in plan_refs and endpoint not in existing_nodes:
                revision_errors.append(
                    f"edges[{i}].{label} {endpoint!r} is neither a plan ref nor an "
                    "existing node id"
                )
    return revision_errors


def _plan_topology_refusal(plan: dict, existing_nodes: dict, existing_edges: list, available: dict,
                           remove_node_set: set, remove_edges: list) -> str | None:
    """dev/112 (DEC-070): the topology refusal, or None — interaction edges obey the preamble's rule
    and no plan DATA edge may close a cycle in the NET graph; validated BEFORE anything materializes."""
    # dev/112 (DEC-070): topology validated BEFORE anything materializes, like
    # fan-in. (1) Interaction edges obey the preamble's rule (visualization ↔
    # data-pool) — an executable rule, not prose the model must infer. (2) No
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

    kind_errors = plan_topology.interaction_edge_errors(plan, _type_of_endpoint, available)
    if kind_errors:
        return "\n- ".join(["the plan wires invalid interaction edges:"] + kind_errors)
    net_pairs = plan_topology.net_data_edges(
        existing_edges, plan, remove_node_set, set(remove_edges)
    )
    closing = plan_topology.closing_plan_edges(net_pairs, plan)
    if closing:
        def _label(node_id: str) -> str:
            return _plan_endpoint_label(node_id, plan, existing_nodes)
        cycle_errors = [
            f"edge {_label(u)!r} → {_label(v)!r} closes a cycle: "
            + plan_topology.format_cycle(path, _label)
            for u, v, path in closing[:5]
        ]
        return "\n- ".join(
                ["the plan creates a cycle in the dataflow (data edges must form a DAG):"]
                + cycle_errors
                + [
                    "remove one data edge of the loop, or — for a visualization feeding "
                    "back into a data-pool — make that edge \"kind\": \"interaction\""
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
    """The review card's one-line summary: counts, and removals named (dev/112)."""
    remove_nodes = plan.get("removeNodes", [])
    remove_edges = plan.get("removeEdges", [])
    n_nodes, n_edges = len(plan["nodes"]), len(plan["edges"])
    summary = f"Apply plan · {count_label(n_nodes, 'node')}, {count_label(n_edges, 'edge')}"
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
    preview_lines = [
        f"{node['title']} · {node['nodeType']} — {node['intent']}" for node in plan["nodes"]
    ]
    for node_id in remove_nodes:
        victim = existing_nodes[node_id]
        label = (victim.get("goal") or node_id)[:80]
        preview_lines.append(f"− Remove: {label} · {victim.get('type') or 'untyped'}")
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
    if remove_nodes or remove_edges:
        # DEC-049.2: removals reviewed by NAME — every victim listed with a
        # content flag; the cascade counted.
        part["plan"]["removals"] = [
            {
                "id": node_id,
                "label": (existing_nodes[node_id].get("goal") or node_id)[:80],
                "nodeType": existing_nodes[node_id].get("type"),
                "contentChars": len(existing_nodes[node_id].get("content") or ""),
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


def _enter_plan_review(spec: dict, loop_ctx: dict, proposal_id: str, plan: dict) -> None:
    """The builder session (DR-2) transitions on the SAME spec write: the attachment record is rule-9
    share-stripped and save-preserved already."""
    record = attachments.get_attachment(spec, loop_ctx["attachment_id"])
    if record is not None:
        session = record.setdefault("builderSession", {})
        session["phase"] = "plan_review"
        session["planProposalId"] = proposal_id
        # dev/67-5: the per-node Simulation Mode ledger — reset per plan.
        session["nodeStates"] = {n["ref"]: "planned" for n in plan["nodes"]}
        session["nodeIds"] = {}



# dev/67-5: review-stage goal edits are bounded like plan intents.
_PLAN_GOAL_EDIT_MAX_CHARS = 300


def set_plan_goal(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    ref: str,
    goal: str,
) -> dict:
    """dev/67-5: review-stage goal editing — an audited overlay applied at
    creation. The PINNED plan bytes stay immutable (the digest model
    survives); the overlay lives on the proposal and rides the mirror so it
    survives reloads. Pending proposals only."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    agents_spec_reads._record_or_404(spec, attachment_id)
    proposal = agents_store._pending_plan_proposal(spec, attachment_id, proposal_id)
    refs = {n["ref"] for n in (proposal.get("plan") or {}).get("nodes", [])}
    if ref not in refs:
        raise AgentServiceError(f"ref {ref!r} is not a node in this plan", 404)
    if not isinstance(goal, str) or not goal.strip():
        raise AgentServiceError("goal must be a non-empty string", 422)
    goal = goal.strip()
    if len(goal) > _PLAN_GOAL_EDIT_MAX_CHARS:
        raise AgentServiceError(
            f"goal exceeds {_PLAN_GOAL_EDIT_MAX_CHARS} characters", 422
        )
    edited = proposal.setdefault("editedGoals", {})
    edited[ref] = goal
    projects_storage.write_spec(user_key, project_id, spec)
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "ref": ref,
        "goal": goal,
        "editedGoals": dict(edited),
    }


#: dev/126: the agents a plan-created node carries. WHICH of them attaches to
#: a given node is the manifests' own compatibility declaration, read through
#: ``attachments.node_target_matches`` — the Node Builder accepts any node, the
#: Dataset Finder only a ``data-loading`` one (dev/50's ``requires``). No second
#: predicate lives here, so this list can never drift from the manifests.
_PLAN_NODE_AGENTS: tuple[str, ...] = ("agent.node-builder", "agent.dataset-finder")


#: dev/132: which node-attached agent a confirmed source is handed to, in
#: preference order — the Node Builder owns fetch code (`DEC-047`), and the
#: Node Content Builder is the fallback a plain plan node carries.
_NODE_BUILD_AGENTS: tuple[str, ...] = (
    "agent.node-builder", "agent.node-content-builder",
)


def _attach_node_agent(
    user_key: str | None, spec: dict, agent_id: str, node_id: str, node_type: object
) -> dict:
    """Attach ONE agent to a node, idempotently, reporting what happened.

    dev/126: the shared body of dev/71's plan-node attachment. Returns
    ``{"agentId", "attachmentId" | None, "status": "attached" | "existing" |
    "skipped", "reason"?}``. Never raises and never writes the spec — the
    caller's own single write persists it, and a node is never blocked over
    its agent."""
    existing = agents_spec_reads._node_attachment_of(spec, agent_id, node_id)
    if existing is not None:
        return {
            "agentId": agent_id,
            "attachmentId": existing.get("attachmentId"),
            "status": "existing",
        }
    coord = agents_spec_reads._installed_project_coord(spec, agent_id)
    if coord is None:
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": "not installed in this dataflow"}
    manifest = agents_catalog._resolve_definition(user_key, coord) if user_key else None
    if manifest is not None and not attachments.node_target_matches(manifest, node_type):
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": f"does not attach to {attachments.canonical_node_suffix(node_type)} nodes"}
    try:
        record = attachments.attach(
            spec, coord, {"kind": "node", "targetId": node_id},
            attachment_id=uuid.uuid4().hex, session_id=uuid.uuid4().hex,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not attach %s to node %s: %s", agent_id, node_id, exc)
        return {"agentId": agent_id, "attachmentId": None, "status": "skipped",
                "reason": str(exc)[:120]}
    return {"agentId": agent_id, "attachmentId": record.get("attachmentId"),
            "status": "attached"}


def _attach_plan_node_agents(
    user_key: str | None, spec: dict, node_id: str, node_type: object
) -> dict:
    """dev/126: every plan-created node gets its agents — the Node Builder
    always, the Dataset Finder when the node is a data-loading one — on BOTH
    apply paths, idempotently, in the caller's own spec write.

    Returns ``{"attached": [row], "skipped": [row], "byAgent": {agentId: id}}``
    so the apply can SAY what it attached instead of silently dropping it."""
    rows = [
        _attach_node_agent(user_key, spec, agent_id, node_id, node_type)
        for agent_id in _PLAN_NODE_AGENTS
    ]
    return {
        "attached": [
            {"nodeId": node_id, **r} for r in rows if r["status"] in ("attached", "existing")
        ],
        "skipped": [{"nodeId": node_id, **r} for r in rows if r["status"] == "skipped"],
        "byAgent": {
            r["agentId"]: r["attachmentId"] for r in rows if r.get("attachmentId")
        },
    }


def _attached_agent_lines(*results: dict) -> list[str]:
    """The applied card's truthful account of the agents an apply attached
    (dev/126): one line naming each agent and how many nodes carry it, plus a
    line for anything that could not be attached, with its reason."""
    counts: dict[str, int] = {}
    skipped: dict[str, str] = {}
    for result in results:
        for row in result.get("attached") or []:
            counts[row["agentId"]] = counts.get(row["agentId"], 0) + 1
        for row in result.get("skipped") or []:
            skipped.setdefault(row["agentId"], row.get("reason") or "skipped")
    lines: list[str] = []
    if counts:
        lines.append("agents attached: " + " · ".join(
            f"{_agent_label(a)} ×{n}" if n > 1 else _agent_label(a)
            for a, n in sorted(counts.items())
        ))
    for agent_id, reason in sorted(skipped.items()):
        lines.append(f"no {_agent_label(agent_id)}: {reason}")
    return lines


def _agent_label(agent_id: str) -> str:
    """A built-in's display name for a card line, id as the last resort."""
    manifest = builtin.get_builtin_manifest(f"{agent_id}@{builtin.BUILTIN_VERSION}")
    return getattr(manifest, "name", None) or agent_id


def _attach_node_builder(spec: dict, node_id: str, *, user_key: str | None = None,
                         node_type: object = None) -> str | None:
    """dev/71: best-effort Node Builder attachment for a plan-created node.
    Skips (returning None) when the template is not installed or the node
    already carries one — node creation NEVER fails over this. dev/126: one
    call into the shared body above."""
    row = _attach_node_agent(user_key, spec, "agent.node-builder", node_id, node_type)
    return row.get("attachmentId")


def apply_plan_node(
    user_key: str, project_id: str, attachment_id: str, proposal_id: str, ref: str
) -> dict:
    """dev/67-5: apply ONE planned node — the per-node narrowing of the plan
    apply (Simulation Mode: create). Edges are the connection stage's concern
    (67-8); the proposal STAYS pending until every ref is applied or it is
    dismissed. A pure node ADD is drift-safe, so the whole-graph digest is not
    re-checked here — the ref's slice of the apply contract is: proposal
    pending (a stale/dismissed one refuses at the status gate) + the template
    still available. Creation uses the mint-time position and the (possibly
    edited) goal; the created node joins ``nodeRuns`` as ``pending`` so Solve
    and the 67-6/67-7 stages pick it up."""
    from utk_curio.backend.app.packages import service as packages_services

    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    proposal = agents_store._pending_plan_proposal(spec, attachment_id, proposal_id)
    plan = proposal.get("plan") or {}
    plan_node = next((n for n in plan.get("nodes", []) if n["ref"] == ref), None)
    if plan_node is None:
        raise AgentServiceError(f"ref {ref!r} is not a node in this plan", 404)
    applied_refs = proposal.setdefault("appliedRefs", [])
    applied_ids = proposal.setdefault("appliedNodeIds", {})
    session_id = record.get("sessionId")
    if ref in applied_refs:
        # Idempotent: the node exists; say so honestly, change nothing.
        return {
            "attachmentId": attachment_id,
            "proposalId": proposal_id,
            "status": "already-applied",
            "ref": ref,
            "nodeId": applied_ids.get(ref),
            "appliedRefs": list(applied_refs),
            "builderSession": record.get("builderSession"),
        }
    try:
        available = {t["id"] for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node template registry is unavailable: {exc}",
        ) from exc
    # dev/93 D3: canonicalise the COMPARISON, never the stored value — a
    # proposal minted before the parse-boundary change may hold a raw
    # versioned string whose shape digest was computed over exactly that
    # string, so rewriting it here would mark an in-flight proposal stale.
    if packages_services.canonical_template_id(plan_node["nodeType"]) not in available:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"node type {plan_node['nodeType']!r} is no longer available — "
            "ask the agent to replan",
        )
    created = _created_plan_node(proposal, plan_node, ref)
    node_id = created["id"]
    dataflow = spec.setdefault("dataflow", {})
    dataflow.setdefault("nodes", []).append(created)
    applied_refs.append(ref)
    applied_ids[ref] = node_id
    # dev/71: attach the Node Builder to the created node (best-effort,
    # idempotent — creation never fails over it); it operates as the node's
    # creation/content orchestration agent (67-6 modify-existing posture).
    # dev/126: and the Dataset Finder when the node is a data-loading one —
    # the same helper the whole-plan apply uses, so the two paths cannot
    # produce different graphs from the same plan.
    attached = _attach_plan_node_agents(user_key, spec, node_id, plan_node["nodeType"])
    attached_agent_id = attached["byAgent"].get("agent.node-builder")
    # dev/71: PROGRESSIVE CONNECTION — apply every plan edge whose other
    # endpoint already exists (created refs or existing canvas nodes), through
    # the 67-8 per-edge policy. The graph grows connected, not as islands;
    # topology refusals are recorded per edge and never block the node.
    ctx = _plan_edge_context(user_key, project_id, spec, proposal)
    edge_results: dict = {}
    created_edges: list[dict] = []
    for index in range(len(ctx["plan_edges"])):
        if ctx["edge_states"].get(str(index)) == "applied":
            continue
        result_row, created_edge = _apply_one_plan_edge(ctx, index, record_missing=False)
        if result_row is not None:
            edge_results[str(index)] = result_row
        if created_edge is not None:
            created_edges.append(created_edge)
    # Re-pin the shape digest to the spec THIS apply produced: the plan's own
    # per-node progress is legitimate drift for a later whole-plan apply;
    # foreign edits between applies still 409 + stale.
    proposal["baseGraphDigest"] = agents_spec_reads._graph_shape_digest(spec)
    session = record.setdefault("builderSession", {})
    session["phase"] = "simulating"
    session["appliedPlanId"] = proposal_id
    session.setdefault("nodeStates", {})[ref] = "created"
    session.setdefault("nodeIds", {})[ref] = node_id
    session.setdefault("nodeRuns", {})[node_id] = "pending"
    session["edgeStates"] = dict(ctx["edge_states"])
    # The last apply may complete the STRUCTURE (all refs + edges applied) —
    # content keeps its own lifecycle (dev/71).
    _complete_plan_if_done(record, proposal, session)
    projects_storage.write_spec(user_key, project_id, spec)
    if isinstance(session_id, str):
        _log_plan_node_applied(user_key, project_id, session_id, attachment_id, proposal_id,
                               plan, plan_node, node_id, applied_refs, attached)
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": proposal.get("status", "pending"),
        "ref": ref,
        # The bridge's node-created payload shape (dev/48 §3.3).
        "createdNode": dict(created),
        "appliedRefs": list(applied_refs),
        # dev/71: the progressive sweep's outcomes + the bridge payload.
        "createdEdges": created_edges,
        "edgeResults": edge_results,
        "edgeStates": dict(ctx["edge_states"]),
        "attachedAgentId": attached_agent_id,
        # dev/126: every agent this apply gave the node, and anything it could
        # not — the apply SAYS what it attached instead of dropping it.
        "attachedAgents": attached["attached"],
        "skippedAgents": attached["skipped"],
        "builderSession": session,
    }


def _created_plan_node(proposal: dict, plan_node: dict, ref: str) -> dict:
    """The canvas node one plan ref becomes: the mint-time position and the (possibly edited) goal."""
    pos = (proposal.get("positions") or {}).get(ref) or {}
    goal_text = (proposal.get("editedGoals") or {}).get(ref) or (
        f"{plan_node['title']} — {plan_node['intent']}"
    )
    return {
        "id": str(uuid.uuid4()),
        "type": plan_node["nodeType"],
        "content": "",
        "goal": goal_text,
        "x": float(pos.get("x", 80.0)),
        "y": float(pos.get("y", 80.0)),
    }


def _log_plan_node_applied(user_key, project_id, session_id, attachment_id, proposal_id,
                           plan: dict, plan_node: dict, node_id: str, applied_refs: list, attached: dict) -> None:
    """A result card WITHOUT flipping the proposal part: it stays pending for the remaining refs
    (unlike ``_log_applied_turn``'s applied flip)."""
    sessions.append_turns(
        user_key, project_id, session_id, attachment_id,
        [
            sessions.make_turn(
                "agent",
                f"Applied: created node {plan_node['title']!r} from the plan "
                f"({len(applied_refs)} of {len(plan.get('nodes', []))}).",
                content=[{
                    "type": "card",
                    "kind": "result",
                    "title": "Applied: plan node created",
                    "lines": [
                        f"{plan_node['title']} · {plan_node['nodeType']}",
                        f"node {node_id[:8]}",
                        f"{len(applied_refs)} of {len(plan.get('nodes', []))} plan nodes created",
                        *_attached_agent_lines(attached),
                        f"proposal {proposal_id[:8]}",
                    ],
                }],
            )
        ],
    )


def _plan_endpoint_label(endpoint: str, plan: dict, existing_nodes: dict) -> str:
    """A human label for one plan-edge endpoint: the plan node's title, or the
    existing node's goal (id as the last resort)."""
    for node in plan.get("nodes", []):
        if node["ref"] == endpoint:
            return node["title"][:60]
    existing = existing_nodes.get(endpoint) or {}
    return str(existing.get("goal") or endpoint)[:60]


def _plan_edge_context(
    user_key: str, project_id: str, spec: dict, proposal: dict
) -> dict:
    """Shared lookups + mutable state for per-edge application (dev/71 —
    ONE validation policy for the connect stage and the progressive sweep)."""
    from utk_curio.backend.app.packages import service as packages_services

    plan = proposal.get("plan") or {}
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    edges = dataflow.setdefault("edges", [])
    try:
        available = {
            t["id"]: t
            for t in packages_services.available_templates(user_key, project_id)
        }
    except Exception:
        available = {}  # arity metadata unavailable: fan-in fails open
    types_by_id = {
        n.get("id"): _strip_type_version(str(n.get("type") or ""))
        for n in nodes
        if isinstance(n, dict)
    }
    merge_slots_taken: dict[str, set[str]] = {}
    incoming_count: dict[str, int] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        target = e.get("target")
        if str(e.get("type") or "") == "Interaction":
            continue
        incoming_count[target] = incoming_count.get(target, 0) + 1
        if types_by_id.get(target) == _MERGE_NODE_TYPE and isinstance(e.get("targetHandle"), str):
            merge_slots_taken.setdefault(target, set()).add(e["targetHandle"])
    return {
        "plan": plan,
        "plan_edges": plan.get("edges", []),
        "plan_refs": {n["ref"] for n in plan.get("nodes", [])},
        "edge_states": proposal.setdefault("edgeStates", {}),
        "applied_ids": proposal.get("appliedNodeIds") or {},
        "nodes_by_id": {n.get("id"): n for n in nodes if isinstance(n, dict)},
        "edges": edges,
        "available": available,
        "types_by_id": types_by_id,
        "merge_slots_taken": merge_slots_taken,
        "incoming_count": incoming_count,
    }


def _apply_one_plan_edge(ctx: dict, index: int, *, record_missing: bool = True):
    """Apply ONE plan edge against the CURRENT spec (the 67-8 policy: endpoint
    resolution, already-connected no-op, DEC-051 fan-in, merge slots).
    Returns ``(result_row | None, created_edge | None)`` — ``None`` result when
    an endpoint is missing and ``record_missing`` is False (the progressive
    sweep skips not-yet-created endpoints silently; the explicit connect
    stage names them)."""
    plan = ctx["plan"]
    plan_edge = ctx["plan_edges"][index]
    edge_states = ctx["edge_states"]
    nodes_by_id = ctx["nodes_by_id"]
    key = str(index)
    row = {
        "from": plan_edge["from"],
        "to": plan_edge["to"],
        "fromLabel": _plan_endpoint_label(plan_edge["from"], plan, nodes_by_id),
        "toLabel": _plan_endpoint_label(plan_edge["to"], plan, nodes_by_id),
    }
    if edge_states.get(key) == "applied":
        return {**row, "status": "already-applied"}, None

    def _resolve_endpoint(endpoint: str):
        if endpoint in ctx["plan_refs"]:
            node_id = ctx["applied_ids"].get(endpoint)
            if not node_id:
                title = _plan_endpoint_label(endpoint, plan, nodes_by_id)
                return None, f"create {title!r} first"
            if node_id not in nodes_by_id:
                return None, f"node {node_id!r} was deleted from the canvas"
            return node_id, None
        if endpoint in nodes_by_id:
            return endpoint, None
        return None, f"node {endpoint!r} is no longer in the dataflow"

    source, source_err = _resolve_endpoint(plan_edge["from"])
    target, target_err = _resolve_endpoint(plan_edge["to"])
    if source_err or target_err:
        if not record_missing:
            return None, None  # progressive sweep: endpoint not created yet
        reason = source_err or target_err
        edge_states[key] = "refused"
        return {**row, "status": "refused", "reason": reason}, None
    wants_interaction = plan_topology.is_interaction_edge(plan_edge)
    already = next(
        (
            e for e in ctx["edges"]
            if isinstance(e, dict)
            and e.get("source") == source and e.get("target") == target
            and plan_topology.is_interaction_edge(e) == wants_interaction
        ),
        None,
    )
    if already is not None:
        edge_states[key] = "applied"
        return {
            **row, "status": "applied", "edgeId": already.get("id"),
            "note": "already connected",
        }, None
    if wants_interaction:
        # dev/112: feedback edge — no input port, no merge slot, no cycle
        # question (interaction edges never carry data flow).
        edge = _interaction_spec_edge(source, target)
        ctx["edges"].append(edge)
        edge_states[key] = "applied"
        return {**row, "status": "applied", "edgeId": edge["id"], "kind": "interaction"}, edge
    # dev/112: a data edge that would close a cycle in the CURRENT graph is
    # refused per edge, named — the same predicate the mint applies.
    current_pairs = [
        (str(e.get("source")), str(e.get("target")))
        for e in ctx["edges"]
        if isinstance(e, dict) and not plan_topology.is_interaction_edge(e)
    ]
    closing = plan_topology.closing_plan_edges(current_pairs, {"edges": [{"from": source, "to": target}]})
    if closing:
        _, _, path = closing[0]
        labels = {nid: (n.get("goal") or nid) for nid, n in nodes_by_id.items()}
        edge_states[key] = "refused"
        return {
            **row, "status": "refused",
            "reason": "closes a cycle: " + plan_topology.format_cycle(path, lambda x: labels.get(x, x)),
        }, None
    # Fan-in against the CURRENT spec (DEC-051 rendered capacity).
    target_type = ctx["types_by_id"].get(target, "")
    entry = ctx["available"].get(target_type)
    max_in = entry.get("maxIncomingEdges") if entry else None
    incoming = ctx["incoming_count"]
    if max_in is not None and incoming.get(target, 0) + 1 > max_in:
        reason = (
            f"{row['toLabel']!r} accepts "
            + ("no inputs" if max_in == 0 else f"at most {max_in} input{'s' if max_in != 1 else ''}")
            + f" and already has {incoming.get(target, 0)} — "
            f"route through a {_MERGE_NODE_TYPE} node instead"
        )
        edge_states[key] = "refused"
        return {**row, "status": "refused", "reason": reason}, None
    target_handle = plan_edge.get("toHandle") or "in"
    if target_type == _MERGE_NODE_TYPE:
        taken = ctx["merge_slots_taken"].setdefault(target, set())
        wanted_handle = plan_edge.get("toHandle")
        if isinstance(wanted_handle, str) and _MERGE_HANDLE_RE.match(wanted_handle) and wanted_handle not in taken:
            target_handle = wanted_handle
        else:
            target_handle = next(
                (f"in_{i}" for i in range(5) if f"in_{i}" not in taken), None
            )
            if target_handle is None:
                edge_states[key] = "refused"
                return {
                    **row, "status": "refused",
                    "reason": f"merge node {row['toLabel']!r} has no free input slot",
                }, None
        taken.add(target_handle)
    edge = {
        "id": str(uuid.uuid4()),
        "source": source,
        "target": target,
        "sourceHandle": "out",
        "targetHandle": target_handle,
    }
    ctx["edges"].append(edge)
    incoming[target] = incoming.get(target, 0) + 1
    edge_states[key] = "applied"
    return {
        **row, "status": "applied", "edgeId": edge["id"],
        "targetHandle": target_handle,
    }, edge


def _complete_plan_if_done(record: dict, proposal: dict, session: dict) -> bool:
    """The plan proposal completes when every ref AND every edge is applied —
    the reviewed STRUCTURE is fully materialized (content has its own
    lifecycle: nodeStates/nodeRuns keep tracking Solve). dev/71: the parked
    plan is KEPT after completion — the progressive lifecycle (per-row
    Solve/Run, the driver's validate/approve actions) still reads it; a new
    plan mint replaces it."""
    plan = proposal.get("plan") or {}
    plan_refs = {n["ref"] for n in plan.get("nodes", [])}
    edge_states = proposal.get("edgeStates") or {}
    all_refs_applied = plan_refs and plan_refs == set(proposal.get("appliedRefs") or [])
    all_edges_applied = all(
        edge_states.get(str(i)) == "applied"
        for i in range(len(plan.get("edges", [])))
    )
    if not (all_refs_applied and all_edges_applied):
        return False
    proposal["status"] = "applied"
    runs = session.get("nodeRuns") or {}
    unresolved = any(s in ("pending", "failed") for s in runs.values())
    session["phase"] = "applied" if unresolved else "ready"
    session["appliedPlanId"] = proposal.get("proposalId")
    return True


def apply_plan_edges(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    indices: list[int] | None = None,
) -> dict:
    """Apply plan edges — the connection review stage (memo dev/67-8,
    Simulation Mode: connect; per-edge core shared with the dev/71
    progressive sweep).

    All not-yet-applied edges by default, or the given subset (index-stable —
    the pinned plan's order). Each edge validates against the CURRENT spec at
    apply time; refusals are PER EDGE and named — partial success is normal
    and honest. An edge the user already drew manually applies as a no-op.
    When every ref and every edge is applied, the proposal completes."""
    spec = agents_spec_reads._read_spec_or_404(user_key, project_id)
    record = agents_spec_reads._record_or_404(spec, attachment_id)
    proposal = agents_store._pending_plan_proposal(spec, attachment_id, proposal_id)
    plan = proposal.get("plan") or {}
    plan_edges = plan.get("edges", [])
    if indices is not None:
        bad = [i for i in indices if not isinstance(i, int) or not (0 <= i < len(plan_edges))]
        if bad:
            raise AgentServiceError(f"edge indices out of range: {bad}", 422)
    ctx = _plan_edge_context(user_key, project_id, spec, proposal)
    edge_states = ctx["edge_states"]
    wanted = indices if indices is not None else [
        i for i in range(len(plan_edges)) if edge_states.get(str(i)) != "applied"
    ]
    results: dict = {}
    created_edges: list[dict] = []
    for index in wanted:
        result_row, created = _apply_one_plan_edge(ctx, index)
        if result_row is not None:
            results[str(index)] = result_row
        if created is not None:
            created_edges.append(created)
    # dev/67-5 semantics: the plan's own progress re-pins the shape digest.
    proposal["baseGraphDigest"] = agents_spec_reads._graph_shape_digest(spec)
    session = record.setdefault("builderSession", {})
    session["edgeStates"] = dict(edge_states)
    session_id = record.get("sessionId")
    completed = _complete_plan_if_done(record, proposal, session)
    applied_now = sum(1 for r in results.values() if r["status"] == "applied")
    refused_now = sum(1 for r in results.values() if r["status"] == "refused")
    if isinstance(session_id, str) and (applied_now or refused_now):
        if completed:
            agents_store._log_applied_turn(
                user_key, project_id, session_id, attachment_id, proposal_id,
                f"Applied: {applied_now} connection{'s' if applied_now != 1 else ''} — "
                "the plan is fully applied.",
                "Applied: plan connections",
                [
                    f"+{count_label(applied_now, 'connection')}"
                    + (f" · {refused_now} refused" if refused_now else ""),
                    "plan complete",
                    f"proposal {proposal_id[:8]}",
                ],
            )
        else:
            sessions.append_turns(
                user_key, project_id, session_id, attachment_id,
                [sessions.make_turn(
                    "agent",
                    f"Applied {applied_now} connection{'s' if applied_now != 1 else ''}"
                    + (f"; {refused_now} refused — see the card." if refused_now else "."),
                    content=[{
                        "type": "card",
                        "kind": "result",
                        "title": "Applied: plan connections",
                        "lines": [
                            f"{r['fromLabel']} → {r['toLabel']} · {r['status']}"
                            + (f" — {r['reason']}" if r.get("reason") else "")
                            for r in list(results.values())[:10]
                        ],
                    }],
                )],
            )
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": proposal.get("status"),
        "results": results,
        "edgeStates": dict(edge_states),
        # The bridge inserts these into the LIVE canvas (dev/67-8).
        "createdEdges": created_edges,
        "builderSession": session,
    }


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


def _apply_dataflow_plan(
    user_key: str,
    project_id: str,
    attachment_id: str,
    proposal_id: str,
    spec: dict,
    proposal: dict,
    session_id: object,
) -> dict:
    """The dev/52 apply, extended by dev/59 revisions: atomically remove the
    plan's listed victims (+ their edge cascade) and insert the new graph.

    Revision safety both ways: the pinned shape digest (node-id + edge-id
    sets) catches structural drift, and every removal victim is pinned by its
    content at mint (DEC-049.1) — editing a doomed node between mint and
    apply 409s + ``stale`` naming it, so user work never dies to a stale
    review. Templates re-validated; server-minted ids for every new node; the
    apply touches ONLY listed elements — unlisted nodes keep their ids,
    positions, and content by construction."""

    plan = proposal.get("plan") or {}
    spec_nodes_by_id, remove_nodes = _check_plan_apply_preconditions(
        user_key, project_id, proposal_id, spec, proposal, session_id, plan,
    )
    dataflow = spec.setdefault("dataflow", {})
    nodes = dataflow.setdefault("nodes", [])
    edges = dataflow.setdefault("edges", [])
    remove_node_set = set(remove_nodes)
    removed_edge_ids = _remove_plan_victims(spec, nodes, edges, remove_node_set, plan.get("removeEdges", []))
    created_nodes, attached_results, ref_to_id = _create_plan_nodes(user_key, spec, nodes, plan, proposal)
    created_edges = _create_plan_edges(
        user_key, project_id, proposal_id, spec, proposal, session_id, plan, nodes, edges, ref_to_id, spec_nodes_by_id,
    )
    proposal["status"] = "applied"
    record, node_runs = _plan_apply_session(spec, attachment_id, proposal_id, created_nodes, remove_node_set, ref_to_id)
    projects_storage.write_spec(user_key, project_id, spec)
    _log_plan_applied(user_key, project_id, session_id, attachment_id, proposal_id, spec,
                      created_nodes, created_edges, remove_node_set, removed_edge_ids, node_runs, attached_results)
    return {
        "attachmentId": attachment_id,
        "proposalId": proposal_id,
        "status": "applied",
        "mutationApplied": True,
        # Consumed by the frontend bridge (dev/52; removals per dev/59).
        "appliedGraph": {
            "nodes": created_nodes,
            "edges": created_edges,
            "removedNodeIds": sorted(remove_node_set),
            "removedEdgeIds": sorted(removed_edge_ids),
        },
        # dev/126: as the per-node apply — what each created node was given.
        "attachedAgents": [row for r in attached_results for row in r["attached"]],
        "skippedAgents": [row for r in attached_results for row in r["skipped"]],
        "builderSession": record.get("builderSession") if record else None,
    }


def _check_plan_apply_preconditions(user_key, project_id, proposal_id, spec: dict, proposal: dict, session_id,
                                    plan: dict) -> tuple[dict, list]:
    """Everything that must hold BEFORE anything mutates — the pinned shape digest, every removal
    victim's content pin (DEC-049.1), the templates, and the topology against the CURRENT spec
    (dev/112, DEC-070: ``_mark_stale`` persists the spec, so a later raise would persist the
    removals). Answers the spec's nodes by id and the removal list."""
    from utk_curio.backend.app.packages import service as packages_services

    if agents_spec_reads._graph_shape_digest(spec) != proposal.get("baseGraphDigest"):
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the canvas changed since this plan was proposed — ask the agent to replan",
        )
    # DEC-049.1: per-victim content digests.
    remove_nodes = plan.get("removeNodes", [])
    victim_pins = proposal.get("removeContentSha256") or {}
    spec_nodes_by_id = {
        n.get("id"): n
        for n in (spec.get("dataflow") or {}).get("nodes") or []
        if isinstance(n, dict)
    }
    for node_id in remove_nodes:
        victim = spec_nodes_by_id.get(node_id)
        current = hashlib.sha256(
            ((victim or {}).get("content") or "").encode("utf-8")
        ).hexdigest()
        if victim is None or current != victim_pins.get(node_id):
            label = ((victim or {}).get("goal") or node_id)[:60]
            raise agents_store._mark_stale(
                user_key, project_id, proposal_id, spec, proposal, session_id,
                f"the node you were about to remove changed ({label}) — "
                "ask the agent to replan",
            )
    try:
        available = {t["id"] for t in packages_services.available_templates(user_key, project_id)}
    except Exception as exc:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"the node template registry is unavailable: {exc}",
        ) from exc
    # Canonicalised comparison, stored value untouched — see the per-node
    # apply above for why (dev/93 D3, in-flight proposals keep their digest).
    missing = [
        n["nodeType"] for n in plan.get("nodes", [])
        if packages_services.canonical_template_id(n["nodeType"]) not in available
    ]
    if missing:
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            f"plan node type(s) no longer available: {', '.join(sorted(set(missing)))} — "
            "ask the agent to replan",
        )
    nodes = (spec.get("dataflow") or {}).get("nodes") or []
    edges = (spec.get("dataflow") or {}).get("edges") or []
    # dev/112 (DEC-070): topology re-checked against the CURRENT spec BEFORE
    # anything mutates (``_mark_stale`` persists the spec, so a later raise
    # would persist the removals). The shape digest already catches most
    # drift; this names the one case it cannot — a plan minted acyclic whose
    # edges now close a loop through edges the user drew since.
    pre_ref_to_id: dict[str, str] = dict(proposal.get("appliedNodeIds") or {})
    closing = plan_topology.closing_plan_edges(
        plan_topology.net_data_edges(
            edges, plan, set(plan.get("removeNodes", [])),
            set(plan.get("removeEdges", [])), pre_ref_to_id,
        ),
        plan, pre_ref_to_id,
    )
    if closing:
        u, v, path = closing[0]
        labels = {n.get("id"): (n.get("goal") or n.get("id")) for n in nodes if isinstance(n, dict)}
        plan_titles = {n["ref"]: n["title"] for n in plan.get("nodes", [])}
        def _lbl(x):  # noqa: E306
            return plan_titles.get(x) or labels.get(x) or x
        raise agents_store._mark_stale(
            user_key, project_id, proposal_id, spec, proposal, session_id,
            "the canvas changed since this plan was proposed — applying it would now "
            f"close a cycle ({plan_topology.format_cycle(path, _lbl)}) — ask the agent to replan",
        )
    return spec_nodes_by_id, remove_nodes


def _remove_plan_victims(spec: dict, nodes: list, edges: list, remove_node_set: set, remove_edges: list) -> set:
    """Removals first (dev/59): listed edges + the recomputed cascade of edges incident to removed
    nodes, then the victims themselves — in place, so unlisted elements are untouched by construction."""
    removed_edge_ids = set(remove_edges)
    for e in edges:
        if isinstance(e, dict) and (
            e.get("source") in remove_node_set or e.get("target") in remove_node_set
        ):
            removed_edge_ids.add(str(e.get("id")))
    if removed_edge_ids:
        edges[:] = [e for e in edges if str(e.get("id")) not in removed_edge_ids]
    if remove_node_set:
        nodes[:] = [n for n in nodes if n.get("id") not in remove_node_set]
        # Agent attachments on removed nodes die with them, exactly as manual
        # canvas deletion (dev/32).
        attachments.prune_orphaned_attachments(spec)
    return removed_edge_ids


def _create_plan_nodes(user_key, spec: dict, nodes: list, plan: dict, proposal: dict) -> tuple[list, list, dict]:
    """The plan's new nodes at the mint-time layout (+ review-stage overlays); refs already applied
    per-node are REAL nodes — skipped, their ids seed the edge resolution. Each created node gets its
    agents in THIS apply's single spec write (dev/126)."""
    right = _right_edge(nodes)
    ys = [n.get("y") for n in nodes if isinstance(n, dict) and isinstance(n.get("y"), (int, float))]
    base_x = (right + _NODE_H_GUTTER) if right is not None else 80.0
    base_y = min(ys) if ys else 80.0
    depths = _plan_depths(plan.get("nodes", []), plan.get("edges", []))
    rows: dict[int, int] = {}
    # dev/67-5: the mint-time layout + review-stage overlays; refs already
    # applied per-node are REAL nodes — skipped here, their ids seed the edge
    # resolution so mixed per-node/whole-plan flows wire correctly.
    positions = proposal.get("positions") or {}
    edited_goals = proposal.get("editedGoals") or {}
    already_applied = set(proposal.get("appliedRefs") or [])
    ref_to_id: dict[str, str] = dict(proposal.get("appliedNodeIds") or {})
    created_nodes: list[dict] = []
    attached_results: list[dict] = []
    for plan_node in plan.get("nodes", []):
        depth = depths.get(plan_node["ref"], 0)
        row = rows.get(depth, 0)
        rows[depth] = row + 1
        if plan_node["ref"] in already_applied:
            continue
        node_id = str(uuid.uuid4())
        ref_to_id[plan_node["ref"]] = node_id
        pos = positions.get(plan_node["ref"]) or {}
        created = {
            "id": node_id,
            "type": plan_node["nodeType"],
            "content": plan_node.get("content", ""),
            "goal": edited_goals.get(plan_node["ref"])
            or f"{plan_node['title']} — {plan_node['intent']}",
            "x": float(pos.get("x", base_x + depth * _PLAN_COLUMN_OFFSET)),
            "y": float(pos.get("y", base_y + row * _PLAN_ROW_OFFSET)),
        }
        nodes.append(created)
        created_nodes.append(created)
        # dev/126: the whole-plan apply gives every created node its agents,
        # in THIS apply's single spec write — the per-node path has done so
        # since dev/71 and the two must not disagree.
        attached_results.append(
            _attach_plan_node_agents(user_key, spec, node_id, plan_node["nodeType"])
        )
    return created_nodes, attached_results, ref_to_id


def _create_plan_edges(user_key, project_id, proposal_id, spec: dict, proposal: dict, session_id, plan: dict,
                       nodes: list, edges: list, ref_to_id: dict, spec_nodes_by_id: dict) -> list:
    """The plan's edges: endpoints resolve through the ref map ∪ existing ids (dev/59); handles are
    explicit end-to-end (DEC-051) — merge targets get a deterministic free in_N slot; an interaction
    edge (dev/112) takes no port and no slot."""
    # dev/67-3 (DEC-051): handles are explicit end-to-end. Merge targets get a
    # deterministic free in_N slot (a named free toHandle wins; occupied or
    # unnamed falls to the lowest free) — the bridge passes these through
    # instead of hardcoding "in", which left merge slots unfilled until a
    # reload healed them.
    types_by_id = {
        n.get("id"): _strip_type_version(str(n.get("type") or ""))
        for n in nodes
        if isinstance(n, dict)
    }
    merge_slots_taken: dict[str, set[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        if types_by_id.get(e.get("target")) == _MERGE_NODE_TYPE:
            handle = e.get("targetHandle")
            if isinstance(handle, str):
                merge_slots_taken.setdefault(e.get("target"), set()).add(handle)
    created_edges: list[dict] = []
    for plan_edge in plan.get("edges", []):
        # dev/59: endpoints resolve through the ref map ∪ existing ids.
        source = ref_to_id.get(plan_edge["from"], plan_edge["from"])
        target = ref_to_id.get(plan_edge["to"], plan_edge["to"])
        if plan_topology.is_interaction_edge(plan_edge):
            # dev/112: the Trill's feedback edge — in/out handles both ends,
            # type Interaction (what loadTrill/TrillGenerator round-trip); no
            # input port, no merge slot.
            edge = _interaction_spec_edge(source, target)
            edges.append(edge)
            created_edges.append(edge)
            continue
        target_handle = plan_edge.get("toHandle") or "in"
        if types_by_id.get(target) == _MERGE_NODE_TYPE:
            taken = merge_slots_taken.setdefault(target, set())
            wanted = plan_edge.get("toHandle")
            if isinstance(wanted, str) and _MERGE_HANDLE_RE.match(wanted) and wanted not in taken:
                target_handle = wanted
            else:
                target_handle = next(
                    (f"in_{i}" for i in range(5) if f"in_{i}" not in taken), None
                )
                if target_handle is None:
                    label = ((spec_nodes_by_id.get(target) or {}).get("goal") or target)[:60]
                    raise agents_store._mark_stale(
                        user_key, project_id, proposal_id, spec, proposal, session_id,
                        f"merge node {label!r} has no free input slot — "
                        "ask the agent to replan",
                    )
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
                        remove_node_set: set, ref_to_id: dict) -> tuple[dict | None, dict]:
    """The builder session (DR-2, merged per dev/59): removed victims leave nodeRuns; surviving prior
    entries persist; new pending nodes join; every ref's ledger row completes (dev/67-5)."""
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
    node_runs.update(
        {n["id"]: "pending" for n in created_nodes if not (n.get("content") or "").strip()}
    )
    unresolved = any(s in ("pending", "failed") for s in node_runs.values())
    if record is not None:
        record["builderSession"] = {
            "phase": "applied" if unresolved else "ready",
            "appliedPlanId": proposal_id,
            "nodeRuns": node_runs,
            # dev/67-5: the whole-plan apply completes every ref's ledger row.
            "nodeStates": {ref: "created" for ref in ref_to_id},
            "nodeIds": dict(ref_to_id),
        }
    return record, node_runs


def _log_plan_applied(user_key, project_id, session_id, attachment_id, proposal_id, spec: dict,
                      created_nodes: list, created_edges: list, remove_node_set: set, removed_edge_ids: set,
                      node_runs: dict, attached_results: list) -> None:
    """The applied turn: truthful for edges (dev/112) plus the post-apply topology verdict the agent
    needs to confirm a fix instead of asserting one."""
    # dev/112: truthful for edges (the old copy said "removed 0 nodes" after an
    # edge-only removal), plus the post-apply topology verdict the agent needs
    # to confirm a fix instead of asserting one.
    removed_summary = _removal_phrase(len(remove_node_set), len(removed_edge_ids))
    topology = _topology_clause(spec)
    agents_store._log_applied_turn(
        user_key, project_id, session_id, attachment_id, proposal_id,
        f"Applied: plan added {count_label(len(created_nodes), 'node')} and "
        f"{count_label(len(created_edges), 'connection')}{removed_summary}. {topology}",
        "Applied: dataflow plan",
        [
            f"+{count_label(len(created_nodes), 'node')} · +{count_label(len(created_edges), 'connection')}"
            + (f" · −{count_label(len(remove_node_set), 'node')}" if remove_node_set else "")
            + (f" · −{count_label(len(removed_edge_ids), 'connection')}" if removed_edge_ids else ""),
            f"{sum(1 for s in node_runs.values() if s == 'pending')} pending for Solve",
            *_attached_agent_lines(*attached_results),
            topology,
            f"proposal {proposal_id[:8]}",
        ],
    )

