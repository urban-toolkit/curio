import json
import os
import re
from dataclasses import dataclass
from collections import deque


def _merge_edge_handle_index(edge_id: str) -> int | None:
    """Parse ``in_N`` from a React Flow edge id (matches frontend ``useCode.ts``).

    MERGE_FLOW inputs are ordered by handle slot ``in_0``, ``in_1``, … — not by
    the order edges appear in the JSON file.
    """
    # e.g. ``…78504in_0`` (no hyphen before ``in_``)
    m = re.search(r"in_(\d+)$", edge_id or "")
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Data model: parse workflow JSON into structured specs
# ---------------------------------------------------------------------------

GRAMMAR_TYPES = {"VIS_VEGA", "VIS_UTK"}
CODE_TYPES = {
    "DATA_LOADING", "DATA_CLEANING", "DATA_TRANSFORMATION",
    "DATA_EXPORT", "COMPUTATION_ANALYSIS", "CONSTANTS",
    "FLOW_SWITCH", "VIS_TEXT",
}

# Subset of CODE_TYPES whose frontend component passes ``code={true}``
# to ``NodeEditor``, meaning they render a "code" tab with a Monaco editor.
# The remaining CODE_TYPES (DATA_EXPORT, CONSTANTS, VIS_TEXT) use
# ``code={false}`` and have no code tab.
CODE_EDITOR_TYPES = {
    "DATA_LOADING", "DATA_CLEANING", "DATA_TRANSFORMATION",
    "COMPUTATION_ANALYSIS", "FLOW_SWITCH",
}


def classify_node(node_type: str) -> str:
    """Classify a workflow node type string into a test category.

    Categories:
        "code"     – has a Monaco code editor and a play button
        "grammar"  – has a JSON / grammar editor and a play button
        "datapool" – has ``#data-tabs`` but NO play button
        "passive"  – no standard editor and no play button (e.g. MERGE_FLOW, VIS_IMAGE)
    """
    if node_type in GRAMMAR_TYPES:
        return "grammar"
    if node_type == "DATA_POOL":
        return "datapool"
    if node_type in CODE_TYPES:
        return "code"
    # MERGE_FLOW, VIS_IMAGE, COMMENTS, or any unknown type
    return "passive"


@dataclass
class NodeSpec:
    """Expected properties of a single node parsed from the workflow JSON."""
    id: str
    type: str            # e.g. "DATA_LOADING", "VIS_VEGA"
    x: float
    y: float
    content: str         # raw content string (may be empty for DataPool)
    in_type: str         # "DEFAULT", "DATAFRAME", etc.
    out_type: str
    category: str        # "code" | "grammar" | "datapool" | "passive"

    @property
    def has_play_button(self) -> bool:
        """Only code and grammar nodes expose a play button."""
        return self.category in ("code", "grammar")


@dataclass
class WorkflowSpec:
    """Expected structure of a complete workflow parsed from JSON."""
    filepath: str
    name: str
    nodes: list          # list[NodeSpec]
    edges: list          # list[dict]  –  each: {id, source, target, type?}

    @property
    def nodes_count(self) -> int:
        return len(self.nodes)

    @property
    def edges_count(self) -> int:
        """Count all edges, including Interaction-type edges.

        Workflow JSON files contain two kinds of edges:

        1. **Regular edges** – standard data-flow connections between an
           ``out`` handle and an ``in`` handle (``type`` is ``None`` or
           absent).

        2. **Interaction edges** – ``type == 'Interaction'``.  These link
           ``in/out`` handles and represent a bidirectional interaction
           channel (e.g. brushing / highlighting) between visualisation
           nodes.

        Both kinds are rendered as ``.react-flow__edge`` DOM elements by
        the frontend, so the total count must match what the canvas shows.
        """
        return len(self.edges)

    @property
    def interaction_edges_count(self) -> int:
        """Count Interaction-type edges.

        Interaction edges (``type == 'Interaction'``) use ``in/out``
        handles on both source and target nodes (visible in their edge
        IDs, e.g. ``…in/out-…in/out``).  They represent a bidirectional
        interaction channel – for instance, brushing a bar in a Vega
        chart highlights the corresponding geometry on a UTK map, and
        vice-versa.

        The frontend does **not** render these as ``.react-flow__edge``
        elements; instead they are managed by a dedicated interaction
        layer.  Use this count when you need to verify interaction
        wiring separately from the standard data-flow edge count.
        """
        return sum(1 for e in self.edges if e.get("type") == "Interaction")

    def upstream_nodes(self, node_id: str) -> list[str]:
        """Return source node IDs feeding into *node_id* (data-flow edges only).

        Interaction edges are excluded because they carry selection state,
        not data.

        For ``MERGE_FLOW`` targets, sources are ordered by ``in_0``, ``in_1``,
        … as encoded in each edge's ``id`` (same as the canvas / sandbox).
        """
        node_map = {n.id: n for n in self.nodes}
        target = node_map.get(node_id)
        edges_to = [
            e for e in self.edges
            if e["target"] == node_id and e.get("type") != "Interaction"
        ]
        if target and target.type == "MERGE_FLOW" and len(edges_to) > 1:

            def sort_key(e: dict) -> tuple:
                idx = _merge_edge_handle_index(e.get("id", ""))
                return (idx if idx is not None else 10**9, e.get("id", ""))

            edges_to = sorted(edges_to, key=sort_key)
        return [e["source"] for e in edges_to]

    def topo_sorted_nodes(self) -> list:
        """Return nodes in topological (dependency) order using Kahn's algorithm.

        Source / root nodes come first so upstream nodes execute before
        downstream ones.  If cycles exist the remaining nodes are appended
        at the end.
        """
        node_map = {n.id: n for n in self.nodes}
        in_degree = {n.id: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}

        for edge in self.edges:
            src, tgt = edge["source"], edge["target"]
            if src in adj and tgt in in_degree:
                adj[src].append(tgt)
                in_degree[tgt] += 1

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        ordered: list[NodeSpec] = []

        while queue:
            nid = queue.popleft()
            ordered.append(node_map[nid])
            for neighbour in adj[nid]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        # Append any remaining nodes (cycles or disconnected)
        visited = {n.id for n in ordered}
        for n in self.nodes:
            if n.id not in visited:
                ordered.append(n)

        return ordered


def parse_workflow(filepath: str) -> WorkflowSpec:
    """Read a workflow JSON file and return a ``WorkflowSpec``."""
    with open(filepath, "r") as f:
        data = json.loads(f.read())

    dataflow = data["dataflow"]

    nodes = [
        NodeSpec(
            id=n["id"],
            type=n["type"],
            x=float(n.get("x", 0)),
            y=float(n.get("y", 0)),
            content=n.get("content", ""),
            in_type=n.get("in", "DEFAULT"),
            out_type=n.get("out", "DEFAULT"),
            category=classify_node(n["type"]),
        )
        for n in dataflow["nodes"]
    ]

    edges = [
        {
            "id": e["id"],
            "source": e["source"],
            "target": e["target"],
            "type": e.get("type"),
        }
        for e in dataflow["edges"]
    ]

    return WorkflowSpec(
        filepath=filepath,
        name=data.get("name", os.path.basename(filepath)),
        nodes=nodes,
        edges=edges,
    )

