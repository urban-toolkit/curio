"""Plan topology validation (memo dev/112, DEC-070).

The ONE place that answers two questions about a ``dataflowPlan`` against the
saved spec, so the mint, both apply paths, and the applied summary agree:

1. Is the NET data graph — saved nodes minus ``removeNodes`` plus plan refs,
   saved edges minus ``removeEdges`` minus the removal cascade plus plan
   edges — acyclic?  Only DATA edges count: interaction edges are the Trill's
   feedback channel and are excluded exactly as the canvas's ``hasCycle`` and
   the execution runner exclude them, by the one rule both read
   (``is_interaction_edge``, ``execution/run_plan.py``): typed
   ``Interaction``, of the plan kind ``interaction``, or an interaction handle
   at both ends, a node's own ``in/out`` or a view's ``in/out@<id>``.
2. Are the plan's interaction edges legal?  An interaction edge carries
   selections, never data, so one of its ends must show what it receives: it
   links two visualizations of which one highlights, a visualization and a
   pool, or two pools, all read from the roster's ``bidirectional`` templates.
   The canvas refuses the same edges (``src/registry/interactionRoles.ts``).

Before this module, plan mint validated endpoints and fan-in only; the bulk
bridge inserts edges without the canvas's connect-time cycle check; and the
only enforcement was the execution runner's refusal — which the agent never
saw.  The owner's 2026-08-25 session shows the result: five rounds of a
correct diagnosis, each applying a plan that recreated the cycle.

Pure module: no I/O, no imports from the service layer.

Ported to ``imp/agentcatalog`` by memo dev/125 (dev/121 F2): dev/112 shipped on
``feat/agentscatalog``, which is never merged back, so this branch carried the
same defect — and the harness reported it as ``capability-gap:interaction-edge``
on eight example fixtures rather than as a wrong score.
"""
from __future__ import annotations

import json

from utk_curio.backend.app.agents.domain import agent_text
from utk_curio.backend.app.agents.domain.contracts import AUTK_TEMPLATE
from utk_curio.backend.app.execution import code_references, run_plan

#: The type a saved dataflow gives an interaction edge, as the rule names it.
INTERACTION_EDGE_TYPE = run_plan.INTERACTION_EDGE_TYPE
#: Whether an edge, of a saved dataflow or of a plan, is an interaction edge:
#: the one rule, ``run_plan.is_interaction_edge``.
is_interaction_edge = run_plan.is_interaction_edge
#: The behavior a Map Editor template names: its node is linked by an
#: interaction edge to a map it feeds on a data edge, and to no other node
#: (``interaction_edge_errors``). Read off each template's roster row, never
#: off its id, as ``map_edits`` reads it.
EDITOR_BEHAVIOR = "edit-features"
#: The behavior an Autark map's template names.
MAP_BEHAVIOR = "autk-grammar"


def template_behavior(templates: dict, template_id: str) -> str:
    """The behavior the roster row of *template_id* names, ``""`` for none."""
    row = templates.get(template_id)
    return str(row.get("behavior") or "") if isinstance(row, dict) else ""


def interaction_roles(templates: dict) -> tuple[frozenset[str], frozenset[str]]:
    """``(pools, visualizations)``: the template ids an interaction edge may
    join, read from the roster. A template that declares ``bidirectional`` has
    the interaction handle; it is a visualization when its category is one
    (``vis_*``) and a pool otherwise. A Map Editor template has the handle too,
    and is neither: it links to its map alone."""
    capable = {
        tid for tid, row in templates.items()
        if isinstance(row, dict) and row.get("bidirectional") and template_behavior(templates, tid) != EDITOR_BEHAVIOR
    }
    visualizations = frozenset(
        tid for tid in capable if str(templates[tid].get("category") or "").startswith("vis")
    )
    return frozenset(capable - visualizations), visualizations


def interaction_highlighters(templates: dict) -> frozenset[str]:
    """The visualizations that highlight the rows another visualization, linked
    to them directly by an interaction edge with no pool between, selects: the
    roster's grammar charts (category ``vis_grammar``). A selection crosses a
    direct edge both ways, so one such end is enough."""
    _, visualizations = interaction_roles(templates)
    return frozenset(
        tid for tid in visualizations if templates[tid].get("category") == "vis_grammar"
    )


def strip_type_version(node_type: object) -> str:
    """``curio.builtin/data-pool@1`` → ``curio.builtin/data-pool``."""
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else ""


def template_suffix(node_type: object) -> str:
    """``curio.builtin/vis-vega@1`` → ``vis-vega``."""
    return strip_type_version(node_type).rsplit("/", 1)[-1]


def removal_cascade(existing_edges: list, remove_node_set: set, remove_edge_set: set) -> set[str]:
    """Edge ids that die with the plan: listed victims plus every edge
    incident to a removed node (dev/59)."""
    dead = set(str(e) for e in remove_edge_set)
    for e in existing_edges:
        if not isinstance(e, dict):
            continue
        if e.get("source") in remove_node_set or e.get("target") in remove_node_set:
            dead.add(str(e.get("id")))
    return dead


def net_data_edges(
    existing_edges: list,
    plan: dict,
    remove_node_set: set,
    remove_edge_set: set,
    ref_to_id: dict | None = None,
) -> list[tuple[str, str]]:
    """The (source, target) pairs of every DATA edge the graph will hold after
    the plan applies.  Plan refs stay refs unless ``ref_to_id`` maps them (the
    apply paths pass the real ids they minted)."""
    dead = removal_cascade(existing_edges, remove_node_set, remove_edge_set)
    pairs: list[tuple[str, str]] = []
    for e in existing_edges:
        if not isinstance(e, dict) or str(e.get("id")) in dead or is_interaction_edge(e):
            continue
        pairs.append((str(e.get("source")), str(e.get("target"))))
    mapping = ref_to_id or {}
    for e in plan.get("edges", []) or []:
        if is_interaction_edge(e):
            continue
        pairs.append((mapping.get(e["from"], e["from"]), mapping.get(e["to"], e["to"])))
    return pairs


def find_data_cycle(pairs: list[tuple[str, str]]) -> list[str] | None:
    """One cycle as an ordered node path (``[a, b, c, a]``) or ``None``.
    Iterative DFS with colours — deterministic (edge order) and stack-safe."""
    adjacency: dict[str, list[str]] = {}
    for src, dst in pairs:
        adjacency.setdefault(src, []).append(dst)
        adjacency.setdefault(dst, [])
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {n: WHITE for n in adjacency}
    parent: dict[str, str | None] = {}
    for start in adjacency:
        if colour[start] != WHITE:
            continue
        parent[start] = None
        stack: list[tuple[str, int]] = [(start, 0)]
        colour[start] = GREY
        while stack:
            node, idx = stack[-1]
            nexts = adjacency[node]
            if idx < len(nexts):
                stack[-1] = (node, idx + 1)
                nxt = nexts[idx]
                if colour[nxt] == WHITE:
                    colour[nxt] = GREY
                    parent[nxt] = node
                    stack.append((nxt, 0))
                elif colour[nxt] == GREY:
                    path = [nxt]
                    cur = node
                    while cur is not None and cur != nxt:
                        path.append(cur)
                        cur = parent.get(cur)
                    path.append(nxt)
                    path.reverse()
                    return path
            else:
                colour[node] = BLACK
                stack.pop()
    return None


def closing_plan_edges(
    net_pairs: list[tuple[str, str]], plan: dict, ref_to_id: dict | None = None
) -> list[tuple[str, str, list[str]]]:
    """Every plan DATA edge (u → v) that closes a cycle in the NET graph —
    i.e. v already reaches u — with the closed path ``[u, v, …, u]``.

    This is the refusal predicate: a plan is blamed only for cycles IT closes.
    A cycle the user drew and the plan leaves alone is reported (applied
    summary), never refused — the plan did not create it."""
    adjacency: dict[str, list[str]] = {}
    for src, dst in net_pairs:
        adjacency.setdefault(src, []).append(dst)
    mapping = ref_to_id or {}
    closing: list[tuple[str, str, list[str]]] = []
    for e in plan.get("edges", []) or []:
        if is_interaction_edge(e):
            continue
        u, v = mapping.get(e["from"], e["from"]), mapping.get(e["to"], e["to"])
        path = _shortest_path(adjacency, v, u)
        if path is not None:
            closing.append((u, v, [u] + path))
    return closing


def _shortest_path(adjacency: dict[str, list[str]], start: str, goal: str) -> list[str] | None:
    """BFS path ``[start, …, goal]`` or ``None``."""
    if start == goal:
        return [start]
    parent: dict[str, str | None] = {start: None}
    frontier = [start]
    while frontier:
        nxt: list[str] = []
        for node in frontier:
            for succ in adjacency.get(node, []):
                if succ in parent:
                    continue
                parent[succ] = node
                if succ == goal:
                    path = [succ]
                    cur: str | None = node
                    while cur is not None:
                        path.append(cur)
                        cur = parent[cur]
                    path.reverse()
                    return path
                nxt.append(succ)
        frontier = nxt
    return None


def format_cycle(path: list[str], label_of) -> str:
    """``A → B → C → A`` with caller-supplied labels (plan titles / spec goals)."""
    return " → ".join(str(label_of(n)) for n in path)


def interaction_edge_errors(plan: dict, type_of_endpoint, templates: dict, data_pairs=None) -> list[str]:
    """Corrective errors for plan edges of kind ``interaction`` that do not link
    two visualizations of which one highlights (``interaction_highlighters``),
    a visualization and a pool, or two pools (``interaction_roles``, from the
    *templates* roster), or the Map Editor node and an Autark map it feeds.
    ``type_of_endpoint(endpoint) -> str | None`` returns the (possibly
    versioned) template id of a plan ref or existing node id; an unknown
    template fails open: no fabricated refusal.  *data_pairs* are the
    (source, target) data edges the graph holds once the plan applies
    (``net_data_edges``); without them, the plan's own data edges."""
    pools, visualizations = interaction_roles(templates)
    highlighters = interaction_highlighters(templates)
    pool_names = " or ".join(sorted(template_suffix(t) for t in pools)) or "pool"
    map_names = " or ".join(
        sorted(template_suffix(t) for t in templates if template_behavior(templates, t) == MAP_BEHAVIOR)
    ) or MAP_BEHAVIOR
    if data_pairs is None:
        data_pairs = [(e["from"], e["to"]) for e in plan.get("edges", []) or [] if not is_interaction_edge(e)]
    fed = {(str(source), str(target)) for source, target in data_pairs}
    errors: list[str] = []
    for i, edge in enumerate(plan.get("edges", []) or []):
        if not is_interaction_edge(edge):
            continue
        src, dst = (strip_type_version(type_of_endpoint(edge[end])) for end in ("from", "to"))
        if src not in templates or dst not in templates:
            continue
        src_edits = template_behavior(templates, src) == EDITOR_BEHAVIOR
        if src_edits or template_behavior(templates, dst) == EDITOR_BEHAVIOR:
            editor, other = (edge["from"], edge["to"]) if src_edits else (edge["to"], edge["from"])
            editor_type, other_type = (src, dst) if src_edits else (dst, src)
            if template_behavior(templates, other_type) != MAP_BEHAVIOR:
                errors.append(
                    agent_text.message(
                        "topology.edit-features-other-node", i=i, editor_type=template_suffix(editor_type),
                        map_type=map_names, other=repr(other),
                        other_type=template_suffix(other_type) or 'untyped',
                    )
                )
            elif (str(editor), str(other)) not in fed:
                errors.append(
                    agent_text.message(
                        "topology.edit-features-not-fed", i=i, editor_type=template_suffix(editor_type),
                        map_type=template_suffix(other_type), editor=repr(editor), other=repr(other),
                    )
                )
            continue
        if (src in pools and dst in (pools | visualizations)) or (dst in pools and src in visualizations):
            continue
        if src in visualizations and dst in visualizations and {src, dst} & highlighters:
            continue
        offender = edge["to"] if dst not in pools | visualizations else edge["from"]
        offender_sfx = template_suffix(dst if offender == edge["to"] else src)
        errors.append(
            agent_text.message(
                "topology.interaction-edge-refused", i=i,
                highlighters=', '.join(sorted(template_suffix(t) for t in highlighters)),
                views=', '.join(sorted(template_suffix(t) for t in visualizations)), pool_names=pool_names,
                offender=repr(offender), offender_type=offender_sfx or 'untyped',
            )
        )
    return errors


def document_views(content: object) -> list[dict] | None:
    """The views an Autark document declares, its maps then its plots, the
    order its panes take: each with its ``id`` when it has one. A chip in the
    document holds its place (``code_references.with_chip_placeholders``).
    None when it does not read as a document. The twin of the canvas's
    ``utils/autkDocumentViews.ts``."""
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        spec = json.loads(code_references.with_chip_placeholders(content))
    except (ValueError, TypeError):
        return None
    if not isinstance(spec, dict):
        return None

    def listed(value) -> list:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    views = []
    for kind in ("map", "plot"):
        for entry in listed(spec.get(kind)):
            view_id = entry.get("id") if isinstance(entry, dict) else None
            views.append({"kind": kind, **({"id": view_id} if isinstance(view_id, str) and view_id else {})})
    return views


def interaction_view_errors(plan: dict, type_of_endpoint, document_of_endpoint) -> list[str]:
    """Corrective errors for the views the plan's interaction edges name
    (``fromView`` at the ``from`` node, ``toView`` at the ``to`` node): each
    must be, by its ``id``, a map or a plot of the Autark node at that end, a
    node of several views, whose dot the edge then joins (``in/out@<id>``). A
    node the plan adds has no document yet: a view named on one is what the
    plan asks of it, so its intent names that id. ``type_of_endpoint(endpoint)``
    gives a plan ref's or an existing node's (possibly versioned) template id,
    ``document_of_endpoint(endpoint)`` an existing node's document."""
    errors: list[str] = []
    for i, edge in enumerate(plan.get("edges", []) or []):
        if not is_interaction_edge(edge):
            continue
        for field, end in (("fromView", "from"), ("toView", "to")):
            view = edge.get(field)
            if not isinstance(view, str) or not view:
                continue
            endpoint = edge[end]
            node_type = strip_type_version(type_of_endpoint(endpoint))
            if node_type != AUTK_TEMPLATE:
                errors.append(agent_text.message(
                    "topology.view-not-on-views", i=i, field=field, view=repr(view), endpoint=repr(endpoint),
                    node_type=template_suffix(node_type) or "untyped",
                ))
                continue
            views = document_views(document_of_endpoint(endpoint))
            if views is None:
                # A node the plan adds, or one whose document does not read: no refusal made up.
                continue
            ids = [entry["id"] for entry in views if "id" in entry]
            if len(views) < 2:
                errors.append(agent_text.message(
                    "topology.view-on-one-view", i=i, field=field, view=repr(view), endpoint=repr(endpoint),
                ))
            elif view not in ids:
                errors.append(agent_text.message(
                    "topology.view-unknown", i=i, field=field, view=repr(view), endpoint=repr(endpoint),
                    views=", ".join(repr(each) for each in dict.fromkeys(ids)),
                ) if ids else agent_text.message(
                    "topology.view-no-ids", i=i, field=field, view=repr(view), endpoint=repr(endpoint),
                ))
    return errors
