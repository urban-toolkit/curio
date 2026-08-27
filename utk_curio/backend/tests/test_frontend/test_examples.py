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
    return sorted(glob.glob(os.path.join(EXAMPLES_DIR, "[0-9][0-9]-*.json")))


# (basename, expected_nodes, expected_edges, min_type_counts, requires_interaction_edge)
EXAMPLE_INVARIANTS = [
    ("01-vega-lite-chained-transforms.json", 6, 5,
     {"curio.builtin/data-loading": 1, "curio.builtin/data-transformation": 3, "curio.builtin/vis-vega": 2}, False),
    ("02-vega-lite-spatial-density.json", 8, 6,
     {"curio.builtin/data-pool": 1, "curio.builtin/vis-vega": 2}, False),
    ("03-vega-lite-linked-temporal-charts.json", 4, 3,
     {"curio.builtin/vis-vega": 2}, False),
    ("04-vega-lite-multi-flow-dashboard.json", 24, 26,
     {"curio.builtin/merge-flow": 1, "curio.builtin/vis-vega": 2}, False),
    ("05-vega-lite-multi-view-drilldown.json", 27, 22,
     {"curio.builtin/data-loading": 5, "curio.builtin/vis-vega": 2}, False),
    ("06-autark-what-if-shadow-study.json", 6, 5,
     {"curio.builtin/autk-grammar": 5, "curio.builtin/data-pool": 1}, False),
    ("07-autark-gpu-shader.json", 5, 6,
     {"curio.builtin/autk-grammar": 4, "curio.builtin/data-pool": 1}, True),
    ("08-autark-spatial-join-regression.json", 8, 9,
     {"curio.builtin/autk-grammar": 4, "curio.builtin/js-computation": 1,
      "curio.builtin/merge-flow": 1, "curio.builtin/data-pool": 1}, True),
    ("09-heterogeneous-data-linked-views.json", 13, 15,
     {"curio.builtin/autk-grammar": 1, "curio.builtin/vis-vega": 2}, True),
    ("10-street-vision-cv-analysis.json", 8, 7,
     {
         "curio.streetvision/street-view-fetcher": 1,
         "curio.streetvision/hf-cv-inference": 1,
         "curio.streetvision/cv-gallery": 1,
         "curio.builtin/spatial-join": 1,
         "curio.builtin/vis-vega": 2,
     }, False),
    ("11-autark-pbf-loading.json", 2, 1,
     {"curio.builtin/autk-grammar": 2}, False),
]


def test_examples_present():
    """Every NN-*.json under docs/examples/ is sequentially numbered with no gaps."""
    paths = _example_json_paths()
    basenames = [os.path.basename(p) for p in paths]
    assert len(paths) >= 9, (
        f"Expected at least 9 example JSONs, found {len(paths)}: {basenames}"
    )
    prefixes = sorted(int(b[:2]) for b in basenames)
    assert prefixes == list(range(1, len(prefixes) + 1)), (
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
    """Every example parses into a WorkflowSpec with >0 nodes and unique IDs.

    Edges are not required: single-node autk-grammar examples (06-08, 11)
    are self-contained and have zero edges by design.
    """
    for json_path in _example_json_paths():
        spec = parse_workflow(json_path)
        basename = os.path.basename(json_path)
        assert spec.nodes_count > 0, f"{basename} has zero nodes"
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
    """Example 07's headline functionality is a WGSL shader run via the
    autk-grammar's ``compute`` block.  Assert the grammar spec contains
    a ``wglsFunction`` so we catch accidental removals of the GPU step."""
    path = os.path.join(EXAMPLES_DIR, "07-autark-gpu-shader.json")
    with open(path, "r", encoding="utf-8") as f:
        wf = json.load(f)
    matches = [
        n for n in wf["dataflow"]["nodes"]
        if n["type"] == "curio.builtin/autk-grammar"
        and "wglsFunction" in n.get("content", "")
    ]
    assert matches, (
        "07-autark-gpu-shader.json no longer has a curio.builtin/autk-grammar "
        "node with a wglsFunction — the example's GPU compute step is gone."
    )


#: The only ``docs/examples/data`` files that legitimately stay put. The four OSM
#: extracts are consumed by autk-grammar ``pbfFileUrl`` specs, which take a URL
#: the *browser* fetches from the unauthenticated ``/file/`` route, not a Python
#: path a loader can resolve by dataset id -- and ``.pbf`` is not even a catalog
#: format. The Niteroi raster belongs to the same Autark example. ImageTest/ is a
#: directory the image fixture globs, and the remaining entries serve only the
#: legacy ``docs/examples/dataflows`` fixtures.
_DATA_DIR_ALLOWLIST = (
    "back_bay.osm.pbf",
    "chicago_loop.osm.pbf",
    "lower_mnt.osm.pbf",
    "niteroi.osm.pbf",
    "niteroi_lst_verao_2001_2024.tif",
    "ImageTest",
    "access_score.geojson",
    "nyc_zip.geojson",
    "test.data",
    "<your-polygons>.geojson",
)

_DATA_DIR_REF = re.compile(r"docs/examples/data/([A-Za-z0-9_.<>/-]*)")


@pytest.mark.parametrize("basename", [inv[0] for inv in EXAMPLE_INVARIANTS])
def test_examples_read_their_data_from_the_catalog(basename):
    """Every tabular/raster/vector input resolves by dataset id, not by path.

    A literal ``docs/examples/data/x.csv`` in an example node works on a repo
    checkout and nowhere else: ``MANIFEST.in`` does not ship ``docs/``, so a pip
    install has no such tree, and an isolated sandbox cannot reach one. That
    portability is the whole point of moving these into the Data Catalog, and a
    single un-migrated node is enough to make an example machine-specific again.

    The ``.md`` is checked alongside the ``.json`` because a stale prose
    reference is invisible to ``test_example_docs_parity`` -- that only compares
    fenced code blocks, so a walkthrough can happily document a path its node no
    longer uses.
    """
    for path in (
        os.path.join(EXAMPLES_DIR, basename),
        os.path.join(EXAMPLES_DIR, basename[:-5] + ".md"),
    ):
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        stragglers = sorted({
            match.group(1)
            for match in _DATA_DIR_REF.finditer(text)
            if match.group(1) and not match.group(1).startswith(_DATA_DIR_ALLOWLIST)
        })
        assert not stragglers, (
            f"{os.path.basename(path)} still reads {stragglers} by path. Use "
            f'curio_dataset_path("<id>") against the Data Catalog '
            f"(datasets/), or add the file to _DATA_DIR_ALLOWLIST with a reason "
            f"if it genuinely cannot move."
        )


def test_examples_that_load_catalog_data_declare_it_in_the_spec():
    """A ``curio_dataset_path`` call and a ``dataflow.datasets`` ref go together.

    The call alone is enough to *execute* -- ``resolve_execution_paths`` hardcodes
    ``include_hub=True`` -- so an example missing its ref runs fine and simply
    shows an empty Data palette with nothing marked as in-dataflow. The ref is
    also what ``datasets/seed.py`` reads to decide what to provision, so without
    it the dataset is never copied into the user's store either.
    """
    for path in _example_json_paths():
        spec = json.load(open(path, encoding="utf-8"))
        dataflow = spec["dataflow"]
        used = set()
        for node in dataflow["nodes"]:
            used.update(
                re.findall(
                    r"""curio_dataset_path\(\s*["']([^"']+)["']\s*\)""",
                    node.get("content") or "",
                )
            )
        declared = {
            ref.get("datasetId")
            for ref in (dataflow.get("datasets") or [])
        }
        missing = sorted(used - declared)
        assert not missing, (
            f"{os.path.basename(path)} loads {missing} but does not declare "
            f"them in dataflow.datasets; add a ref so the dataset is actually "
            f"added to the dataflow and gets provisioned into the user store"
        )
        # The reverse direction too: a ref nothing reads is dead weight that the
        # seeder would still copy on every boot.
        unused = sorted(declared - used)
        assert not unused, (
            f"{os.path.basename(path)} declares {unused} in dataflow.datasets "
            f"but no node reads them"
        )


def test_declared_dataset_refs_have_the_shape_the_backend_writes():
    """Hand-written refs must match ``mutations.py::_ref_from_item``.

    These are authored by hand rather than produced by an install, so nothing
    else stops them drifting from the six-key folder-ref form the UI writes.
    ``origin`` is ``imported`` because a project install *is* a user-store copy
    rather than a hub row, and ``consumerNodeIds`` stays empty because
    ``base_item`` documents that it must not be used as a count.
    """
    expected_keys = {
        "datasetId",
        "dirName",
        "origin",
        "producerNodeId",
        "consumerNodeIds",
        "installedAt",
    }
    for path in _example_json_paths():
        spec = json.load(open(path, encoding="utf-8"))
        for ref in spec["dataflow"].get("datasets") or []:
            name = os.path.basename(path)
            assert set(ref) == expected_keys, f"{name}: {sorted(ref)}"
            assert ref["dirName"] == f"{ref['datasetId']}@1", f"{name}: {ref}"
            assert ref["origin"] == "imported", f"{name}: {ref['origin']}"
            assert ref["consumerNodeIds"] == [], f"{name}: {ref}"
            assert ref["producerNodeId"] is None, f"{name}: {ref}"
            assert ref["installedAt"], f"{name}: missing installedAt"
