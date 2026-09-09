"""The oracle: what a perfect answer would have to look like (memo dev/121).

Turns a fixture's expected graph into the replies a model would have to produce
for the production path to rebuild that dataflow -- one ``dataflowPlan`` tail,
and one code reply per executable node for Solve.

It exists to prove REACHABILITY. If the oracle's replies drive the real mint,
the real apply and the real Solve to a graph that scores 1.0, then the harness
measures the model rather than its own plumbing, and a failing fixture is a
finding about the model. And where the oracle CANNOT express the expected graph
it says so by raising :class:`Unrepresentable` -- naming the capability the
contract lacks instead of quietly emitting something smaller. On this branch
that is the interaction edge: the plan grammar carries ``from``, ``to`` and
``toHandle`` only (dev/112's ``edges[].kind`` is not here), so no reply exists
that would produce a bidirectional link.

The oracle is not a model and never stands in for one: it scripts the
deterministic suite. A live evaluation never calls it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Mapping

#: The fence the plan grammar recognises (``content.py``); fence-agnostic
#: recovery exists, but the oracle emits the canonical spelling.
_FENCE = "curio.v1"

#: Edge kinds the plan grammar can carry on this branch.
EXPRESSIBLE_EDGE_KINDS = ("data",)

_ROLE_TITLES = {
    "loader": "Load",
    "transform": "Transform",
    "analysis": "Analyse",
    "visualization": "Visualise",
    "grammar": "Render",
    "pool": "Fan out",
    "merge": "Combine",
    "export": "Export",
    "endpoint": "Process",
    "presentation": "Note",
}


class Unrepresentable(Exception):
    """The expected graph needs something the agent contract cannot express.

    ``need`` is the fixture ``capability.needs`` entry that names it, so a
    driver can check the fixture DECLARED this gap rather than discovering an
    undeclared one -- an undeclared gap is a finding about the fixture.
    """

    def __init__(self, need: str, detail: str = ""):
        super().__init__(f"{need}: {detail}" if detail else need)
        self.need = need
        self.detail = detail


@dataclass(frozen=True)
class OraclePlan:
    goal: str
    nodes: tuple
    edges: tuple

    def as_reply(self, preamble: str = "Here is the plan.") -> str:
        payload = {
            "dataflowPlan": {
                "goal": self.goal,
                "nodes": [dict(n) for n in self.nodes],
                "edges": [dict(e) for e in self.edges],
            }
        }
        return f"{preamble}\n```{_FENCE}\n{json.dumps(payload)}\n```"


def _intent_for(
    ref: str,
    role: str,
    intents: Mapping,
    sources: Iterable = (),
    synthetic: bool = False,
) -> str:
    """The node's one-line intent.

    Where the fixture asserts words for this node, the intent contains them:
    that is the point of the reachability proof -- the pipeline must carry the
    meaning from the plan through apply to the persisted node, and an intent
    the fixture cannot find later is a defect in the plumbing, not in the
    model.
    """
    intent = intents.get(ref) or {}
    mentions = [str(m) for m in (intent.get("mustMention") or [])]
    verb = _ROLE_TITLES.get(role, "Step")
    # The ref rides in the intent because the intent becomes the node's goal at
    # apply, and the goal is what a per-node content request carries: it is how
    # a scripted responder knows WHICH node it is being asked to fill.
    hints = [str(h) for h in sources]
    tail = f" — reads {', '.join(hints)}" if hints else ""
    if synthetic and not hints:
        # DEC-072: inline data in a data-loading node is grounded only when
        # synthetic data was ASKED for, and Solve reads the node's goal rather
        # than the chat -- so the word has to be here or the node cannot be
        # filled. ``source_grounding.SYNTHETIC_MARKERS`` owns the vocabulary.
        tail = " — builds sample data inline (synthetic)"
    if mentions:
        return f"{verb} for {ref} — covers {', '.join(mentions)}{tail}"
    return f"{verb} step for {ref}{tail}"


def plan_for(
    expected: Mapping,
    *,
    goal: str = "rebuild the requested dataflow",
    intents: Iterable = (),
    source_hints: Mapping | None = None,
    synthetic_refs: Iterable = (),
) -> OraclePlan:
    """The plan reply for a fixture's ``expected`` block.

    ``source_hints`` (``{ref: [path, ...]}``) names the file a node will read
    inside that node's intent. This is not a hint to the model -- it is what a
    competent planner does with a path the user typed, and it is *required* for
    the file to be usable later: a background Solve builds its grounding
    evidence from the dataflow's task and its target nodes' GOALS
    (``_solve_grounding_base``), never from the chat session, so a path
    mentioned only in conversation is not evidence when the node is filled.
    Harness finding, recorded as a follow-up in memo dev/121.

    Raises :class:`Unrepresentable` for an edge kind the grammar cannot carry.
    """
    by_ref = {str(i.get("ref")): dict(i) for i in intents}
    hints = {str(k): list(v) for k, v in (source_hints or {}).items()}
    synthetic_refs = {str(r) for r in synthetic_refs}
    nodes = []
    roles = {}
    for node in expected.get("nodes") or []:
        ref = str(node.get("ref"))
        role = str(node.get("role") or "analysis")
        roles[ref] = role
        nodes.append(
            {
                "ref": ref,
                "nodeType": str(node.get("type")),
                "title": f"{_ROLE_TITLES.get(role, 'Step')} {ref}",
                "intent": _intent_for(
                    ref, role, by_ref, hints.get(ref, ()), ref in synthetic_refs
                ),
            }
        )
    edges = []
    for edge in expected.get("edges") or []:
        kind = str(edge.get("kind") or "data")
        if kind not in EXPRESSIBLE_EDGE_KINDS:
            raise Unrepresentable(
                f"{kind}-edge",
                f"the plan grammar carries no edge kind, so {edge.get('from')} -> "
                f"{edge.get('to')} cannot be proposed as a {kind} link",
            )
        entry = {"from": str(edge.get("from")), "to": str(edge.get("to"))}
        slot = edge.get("slot")
        if slot is not None:
            entry["toHandle"] = f"in_{int(slot)}"
        edges.append(entry)
    return OraclePlan(goal=goal, nodes=tuple(nodes), edges=tuple(edges))


def content_replies(
    expected: Mapping,
    *,
    example: Mapping,
    origins: Iterable,
    only_executable: bool = True,
) -> dict:
    """``{ref: code}`` for Solve, taken from the example's own nodes.

    In the deterministic suite there is no model to leak to: the point is that
    the code the example ships, generated for the matching node, survives
    grounding, execution and the per-wave persist. ``origins`` is the canonical
    graph's mapping back to the example's node order.
    """
    inner = example.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else example
    raw_nodes = list(dataflow.get("nodes") or [])
    order = list(origins)
    replies: dict = {}
    for index, node in enumerate(expected.get("nodes") or []):
        if only_executable and not node.get("executable"):
            continue
        if index >= len(order):
            continue
        original = raw_nodes[order[index]] if order[index] < len(raw_nodes) else {}
        content = original.get("content")
        if isinstance(content, str) and content.strip():
            replies[str(node.get("ref"))] = content
    return replies


def source_hints_for(
    expected: Mapping,
    *,
    example: Mapping,
    origins: Iterable,
    paths: Iterable,
) -> dict:
    """``{ref: [path, ...]}`` for the required paths each example node reads.

    Computed from the example's own code with the production scanner, so the
    hint names a real read rather than a guess.
    """
    from utk_curio.backend.app.agents import source_grounding

    inner = example.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else example
    raw_nodes = list(dataflow.get("nodes") or [])
    wanted = {str(p) for p in paths}
    order = list(origins)
    hints: dict = {}
    for index, node in enumerate(expected.get("nodes") or []):
        if index >= len(order) or order[index] >= len(raw_nodes):
            continue
        content = raw_nodes[order[index]].get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        found = [
            ref.literal
            for ref in source_grounding.scan_sources(content, "python")
            if ref.kind == "path" and ref.literal in wanted
        ]
        if found:
            hints[str(node.get("ref"))] = sorted(set(found))
    return hints


def synthetic_refs_for(expected: Mapping, *, example: Mapping, origins: Iterable) -> tuple:
    """Refs whose example node is a loader that builds its data INLINE.

    Half the legacy structural dataflows do exactly that (``pd.DataFrame({...})``,
    synthetic polygons around the Loop). Under ``DEC-072`` such a node is
    grounded only when synthetic data was asked for, so the plan's intent has
    to say so -- see :func:`plan_for`.
    """
    from utk_curio.backend.app.agents import source_grounding

    inner = example.get("dataflow")
    dataflow = inner if isinstance(inner, Mapping) else example
    raw_nodes = list(dataflow.get("nodes") or [])
    order = list(origins)
    refs: list = []
    for index, node in enumerate(expected.get("nodes") or []):
        if str(node.get("role")) != "loader" or index >= len(order):
            continue
        if order[index] >= len(raw_nodes):
            continue
        content = raw_nodes[order[index]].get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if not source_grounding.scan_sources(content, "python"):
            refs.append(str(node.get("ref")))
    return tuple(refs)
