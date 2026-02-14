import os
import re
import pytest
import json
from dataclasses import dataclass
from collections import deque
from .fixtures import load_workflow_files_from_folder

"""
This test file is to test the loading of workflow files in the frontend.
To watch the browser (see the menu open): run with --headed, e.g.
"""


def test_load_workflow_files(workflow_files):
    """
    This test is to check that the workflow files can be loaded from the /tests folder,
    Test if they have the expected structure (nodes and edges).
    The test will fail if the workflow file has no nodes or edges
    """
    assert len(workflow_files) > 0, f"No workflow files found in folder: {workflow_files}"
    #  assert filenames are unique
    assert len(workflow_files) == len(set(workflow_files)), "Workflow files have duplicate filenames"

    # For each workflow file print the Nodes and Edges count
    for workflow_file in workflow_files:
        with open(workflow_file, "r") as f:
            workflow_data = f.read()
            workflow_data = json.loads(workflow_data)
            print(f"Processing workflow file: {workflow_file}")
            nodes_count = len(workflow_data['dataflow']['nodes'])
            edges_count = len(workflow_data['dataflow']['edges'])

            print(f"{os.path.basename(workflow_file)}: {nodes_count} nodes, {edges_count} edges")
            # add assertion to check that the workflow file has at least 1 node and 1 edge
            assert nodes_count > 0, f"Workflow file {workflow_file} has no nodes"
            assert edges_count > 0, f"Workflow file {workflow_file} has no edges"


# ---------------------------------------------------------------------------
# Data model: parse workflow JSON into structured specs
# ---------------------------------------------------------------------------

GRAMMAR_TYPES = {"VIS_VEGA", "VIS_UTK"}
CODE_TYPES = {
    "DATA_LOADING", "DATA_CLEANING", "DATA_TRANSFORMATION",
    "DATA_EXPORT", "COMPUTATION_ANALYSIS", "CONSTANTS",
    "FLOW_SWITCH", "VIS_TEXT",
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
        """Count only regular (non-Interaction) edges.

        Workflow JSON files contain two kinds of edges:

        1. **Regular edges** – standard data-flow connections between an
           ``out`` handle and an ``in`` handle (``type`` is ``None`` or
           absent).  The frontend renders each of these as a
           ``.react-flow__edge`` DOM element.

        2. **Interaction edges** – ``type == 'Interaction'``.  These link
           ``in/out`` handles and represent a bidirectional interaction
           channel (e.g. brushing / highlighting) between visualisation
           nodes.  The frontend renders them through a separate interaction
           layer and they do **not** produce ``.react-flow__edge`` DOM
           elements.

        This property returns the count of regular edges only, so it can
        be compared directly against
        ``page.locator('.react-flow__edge').count()``.
        """
        return sum(1 for e in self.edges if e.get("type") != "Interaction")

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

    def topo_sorted_nodes(self) -> list:
        """Return nodes in topological (dependency) order using Kahn's algorithm.

        Source / root nodes come first so upstream boxes execute before
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



# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("loaded_workflow", load_workflow_files_from_folder(), indirect=True)
class TestWorkflowCanvas:
    """End-to-end checks for each workflow loaded into the ReactFlow canvas.

    The class-scoped ``loaded_workflow`` fixture uploads the workflow once.
    All five test methods share the same browser page and parsed spec
    via ``self.page`` and ``self.spec``.
    """

    # -- helpers -----------------------------------------------------------

    def _node_locator(self, node: NodeSpec):
        """Return a Playwright ``Locator`` for a ReactFlow node element."""
        return self.page.locator(f'.react-flow__node[data-id="{node.id}"]')

    def _execute_all_playable_nodes(self):
        """Click *play* on every node that has a play button (topological order)
        and wait for each to finish."""
        for node in self.spec.topo_sorted_nodes():
            if not node.has_play_button:
                continue
            node_el = self._node_locator(node)
            node_el.scroll_into_view_if_needed()

            play_btn = node_el.locator("svg.fa-circle-play")
            if play_btn.count() == 0:
                continue
            play_btn.click(force=True)

            # Wait for "Done" or "Error" to appear (up to 30 s per node)
            outcome = node_el.locator("span").filter(
                has_text=re.compile(r"^(Done|Error)$")
            ).first
            outcome.wait_for(state="visible", timeout=30000)

    # -- 1. Node & edge counts --------------------------------------------

    def test_node_and_edge_count(self, loaded_workflow):
        """The canvas must contain the exact number of nodes and edges
        declared in the workflow JSON."""
        node_els = self.page.locator(".react-flow__node")
        edge_els = self.page.locator(".react-flow__edge")

        wf_name = os.path.basename(self.spec.filepath)
        assert node_els.count() == self.spec.nodes_count, (
            f"[{wf_name}] Expected {self.spec.nodes_count} nodes, "
            f"found {node_els.count()}"
        )
        assert edge_els.count() == self.spec.edges_count, (
            f"[{wf_name}] Expected {self.spec.edges_count} edges, "
            f"found {edge_els.count()}"
        )
