"""Plan topology validation (memo dev/112, DEC-070).

The ONE place that answers two questions about a ``dataflowPlan`` against the
saved spec, so the mint, both apply paths, and the applied summary agree:

1. Is the NET data graph — saved nodes minus ``removeNodes`` plus plan refs,
   saved edges minus ``removeEdges`` minus the removal cascade plus plan
   edges — acyclic?  Only DATA edges count: interaction edges are the Trill's
   feedback channel (``type: "Interaction"``, ``in/out`` handles) and are
   excluded exactly as the canvas's ``hasCycle`` and the execution runner
   exclude them.
2. Are the plan's interaction edges legal?  The default preamble teaches the
   rule ("Visualizations can be connected to a Data Pool with an edge of type
   Interaction"), and here it is executable: one endpoint is a pool, the other a
   visualization, both read from the roster's ``bidirectional`` templates.

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

INTERACTION_EDGE_TYPE = "Interaction"



def interaction_roles(templates: dict) -> tuple[frozenset[str], frozenset[str]]:
    """``(pools, visualizations)``: the template ids an interaction edge may
    join, read from the roster. A template that declares ``bidirectional`` has
    the interaction handle; it is a visualization when its category is one
    (``vis_*``) and a pool otherwise."""
    capable = {tid for tid, row in templates.items() if isinstance(row, dict) and row.get("bidirectional")}
    visualizations = frozenset(
        tid for tid in capable if str(templates[tid].get("category") or "").startswith("vis")
    )
    return frozenset(capable - visualizations), visualizations


def strip_type_version(node_type: object) -> str:
    """``curio.builtin/merge-flow@1`` → ``curio.builtin/merge-flow``."""
    return node_type.split("@", 1)[0] if isinstance(node_type, str) else ""


def template_suffix(node_type: object) -> str:
    """``curio.builtin/vis-vega@1`` → ``vis-vega``."""
    return strip_type_version(node_type).rsplit("/", 1)[-1]


def is_interaction_edge(edge: dict) -> bool:
    """Spec edge (``type: "Interaction"``) or plan edge (``kind: "interaction"``)."""
    return (
        str(edge.get("type") or "") == INTERACTION_EDGE_TYPE
        or str(edge.get("kind") or "") == "interaction"
    )


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


def interaction_edge_errors(plan: dict, type_of_endpoint, templates: dict) -> list[str]:
    """Corrective errors for plan edges of kind ``interaction`` that do not join
    a visualization to a pool (``interaction_roles``, from the *templates*
    roster).  ``type_of_endpoint(endpoint) -> str | None`` returns the (possibly
    versioned) template id of a plan ref or existing node id; an unknown
    template fails open: no fabricated refusal."""
    pools, visualizations = interaction_roles(templates)
    pool_names = " or ".join(sorted(template_suffix(t) for t in pools)) or "pool"
    errors: list[str] = []
    for i, edge in enumerate(plan.get("edges", []) or []):
        if not is_interaction_edge(edge):
            continue
        src, dst = (strip_type_version(type_of_endpoint(edge[end])) for end in ("from", "to"))
        if src not in templates or dst not in templates:
            continue
        if (src in pools and dst in visualizations) or (dst in pools and src in visualizations):
            continue
        offender = edge["to"] if dst not in pools | visualizations else edge["from"]
        offender_sfx = template_suffix(dst if offender == edge["to"] else src)
        errors.append(
            f"edges[{i}]: an interaction edge connects a visualization "
            f"({', '.join(sorted(template_suffix(t) for t in visualizations))}) to a "
            f"{pool_names} node; {offender!r} is {offender_sfx or 'untyped'}; use a data "
            f"edge, or target the {pool_names}"
        )
    return errors
