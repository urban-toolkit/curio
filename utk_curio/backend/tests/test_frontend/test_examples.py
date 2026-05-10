"""Pure-Python structural checks for the 9 curated example workflows.

Catches drift in [docs/examples/0X-*.json] without running the browser,
complementing the full Playwright e2e in test_workflows.py.
"""

import json
import os
import re
import glob

import pytest

from .utils import REPO_ROOT
from .workflow_spec import parse_workflow


EXAMPLES_DIR = os.path.join(REPO_ROOT, "docs", "examples")


def _example_json_paths() -> list[str]:
    return sorted(glob.glob(os.path.join(EXAMPLES_DIR, "0[1-9]-*.json")))


# (basename, expected_nodes, expected_edges, min_type_counts, requires_interaction_edge)
EXAMPLE_INVARIANTS = [
    ("01-vega-lite-chained-transforms.json", 6, 5,
     {"DATA_LOADING": 1, "DATA_TRANSFORMATION": 3, "VIS_VEGA": 2}, False),
    ("02-vega-lite-spatial-density.json", 8, 6,
     {"DATA_POOL": 1, "VIS_VEGA": 2}, False),
    ("03-vega-lite-linked-temporal-charts.json", 4, 3,
     {"VIS_VEGA": 2}, False),
    ("04-vega-lite-multi-flow-dashboard.json", 24, 26,
     {"MERGE_FLOW": 1, "VIS_VEGA": 2}, False),
    ("05-vega-lite-multi-view-drilldown.json", 27, 22,
     {"DATA_LOADING": 5, "VIS_VEGA": 2}, False),
    ("06-autark-what-if-picking.json", 8, 8,
     {"AUTK_MAP": 3, "DATA_POOL": 1}, True),
    ("07-autark-gpu-shader.json", 5, 5,
     {"AUTK_COMPUTE": 1, "AUTK_MAP": 1, "AUTK_PLOT": 1}, True),
    ("08-autark-spatial-join-regression.json", 7, 7,
     {"AUTK_DB": 1, "AUTK_COMPUTE": 1}, True),
    ("09-heterogeneous-data-linked-views.json", 13, 15,
     {"AUTK_MAP": 1, "VIS_VEGA": 2}, True),
]


def test_nine_examples_present():
    """Exactly 9 files match docs/examples/0[1-9]-*.json with no gaps."""
    paths = _example_json_paths()
    basenames = [os.path.basename(p) for p in paths]
    assert len(paths) == 9, (
        f"Expected 9 example JSONs, found {len(paths)}: {basenames}"
    )
    prefixes = sorted(b[:2] for b in basenames)
    assert prefixes == [f"0{i}" for i in range(1, 10)], (
        f"Example prefixes have gaps or duplicates: {prefixes}"
    )


def test_each_example_has_markdown_walkthrough():
    """Every XX-slug.json has a sibling XX-slug.md."""
    for json_path in _example_json_paths():
        md_path = json_path[:-5] + ".md"
        assert os.path.isfile(md_path), (
            f"Example {os.path.basename(json_path)} is missing its sibling "
            f"markdown walkthrough: {md_path}"
        )


def test_each_example_referenced_in_readme():
    """Every example's markdown link appears in docs/README.md's table."""
    readme_path = os.path.join(REPO_ROOT, "docs", "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()
    for json_path in _example_json_paths():
        slug = os.path.basename(json_path)[:-5]  # 01-vega-lite-...
        ref = f"examples/{slug}.md"
        assert ref in readme, (
            f"docs/README.md does not reference {ref!r} — the examples table "
            f"is out of sync with the JSONs in docs/examples/"
        )


def test_each_example_has_valid_dataflow_structure():
    """Every example parses into a WorkflowSpec with >0 nodes/edges and unique IDs."""
    for json_path in _example_json_paths():
        spec = parse_workflow(json_path)
        basename = os.path.basename(json_path)
        assert spec.nodes_count > 0, f"{basename} has zero nodes"
        assert spec.edges_count > 0, f"{basename} has zero edges"
        ids = [n.id for n in spec.nodes]
        assert len(ids) == len(set(ids)), (
            f"{basename} has duplicate node IDs: "
            f"{[i for i in ids if ids.count(i) > 1]}"
        )


@pytest.mark.parametrize(
    "basename,expected_nodes,expected_edges,min_type_counts,requires_interaction",
    EXAMPLE_INVARIANTS,
    ids=[inv[0] for inv in EXAMPLE_INVARIANTS],
)
def test_example_documented_invariants(
    basename, expected_nodes, expected_edges, min_type_counts, requires_interaction,
):
    """Each example must keep the structural invariants documented in
    docs/README.md and the per-example walkthrough (node count / edge count /
    presence of marquee node types like MERGE_FLOW, AUTK_DB, AUTK_COMPUTE)."""
    path = os.path.join(EXAMPLES_DIR, basename)
    with open(path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    nodes = wf["dataflow"]["nodes"]
    edges = wf["dataflow"]["edges"]

    assert len(nodes) == expected_nodes, (
        f"{basename}: expected {expected_nodes} nodes, got {len(nodes)}"
    )
    assert len(edges) == expected_edges, (
        f"{basename}: expected {expected_edges} edges, got {len(edges)}"
    )

    counts: dict[str, int] = {}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    for node_type, min_count in min_type_counts.items():
        actual = counts.get(node_type, 0)
        assert actual >= min_count, (
            f"{basename}: expected >={min_count} {node_type} node(s), "
            f"got {actual}. Type histogram: {counts}"
        )

    if requires_interaction:
        interaction_count = sum(
            1 for e in edges if e.get("type") == "Interaction"
        )
        assert interaction_count >= 1, (
            f"{basename}: expected >=1 Interaction edge for cross-view "
            f"brushing, got 0. Edge types: "
            f"{sorted({e.get('type') or 'data' for e in edges})}"
        )


def test_example_07_drives_compute_gpgpu():
    """Example 07's headline functionality is a WGSL shader run via AUTK's
    ``ComputeGpgpu`` primitive. The WGSL itself is wrapped (the literal
    ``@compute`` decorator is added by AUTK at runtime), so we assert on the
    JS API surface instead — an AUTK_COMPUTE node that references both
    ``ComputeGpgpu`` and ``wgslBody``."""
    path = os.path.join(EXAMPLES_DIR, "07-autark-gpu-shader.json")
    with open(path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    matches = [
        n for n in wf["dataflow"]["nodes"]
        if n["type"] == "AUTK_COMPUTE"
        and "ComputeGpgpu" in n.get("content", "")
        and "wgslBody" in n.get("content", "")
    ]
    assert matches, (
        "07-autark-gpu-shader.json no longer has an AUTK_COMPUTE node that "
        "drives ComputeGpgpu with a wgslBody — the example's headline "
        "functionality is gone."
    )
