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
    ("04-vega-lite-multi-flow-dashboard.json", 21, 23,
     {"curio.builtin/computation-analysis": 3, "curio.builtin/vis-vega": 2}, False),
    ("05-vega-lite-multi-view-drilldown.json", 27, 22,
     {"curio.builtin/data-loading": 5, "curio.builtin/vis-vega": 2}, False),
    ("06-autark-what-if-shadow-study.json", 11, 13,
     {"curio.builtin/autk-grammar": 7, "curio.builtin/data-pool": 1,
      "curio.builtin/compare-scenarios": 2, "curio.builtin/edit-features": 1}, False),
    ("07-autark-gpu-shader.json", 5, 6,
     {"curio.builtin/autk-grammar": 4, "curio.builtin/data-pool": 1}, True),
    ("08-autark-spatial-join-regression.json", 7, 8,
     {"curio.builtin/autk-grammar": 4, "curio.builtin/js-computation": 1,
      "curio.builtin/data-pool": 1}, True),
    ("09-heterogeneous-data-linked-views.json", 11, 13,
     {"curio.builtin/autk-grammar": 1, "curio.builtin/vis-vega": 2}, True),
    ("10-street-vision-cv-analysis.json", 12, 12,
     {
         "curio.builtin/data-loading": 2,
         "curio.streetvision/image-segmentation": 2,
         "curio.builtin/vis-simple": 2,
         "curio.builtin/spatial-join": 2,
         "curio.builtin/vis-vega": 3,
     }, False),
    ("11-autark-pbf-loading.json", 2, 1,
     {"curio.builtin/autk-grammar": 2}, False),
    ("12-vega-lite-geodataframe-maps.json", 5, 4,
     {"curio.builtin/data-loading": 1, "curio.builtin/data-transformation": 1,
      "curio.builtin/vis-vega": 3}, False),
    ("13-vega-lite-geometry-columns.json", 14, 13,
     {"curio.builtin/data-loading": 1, "curio.builtin/data-transformation": 6,
      "curio.builtin/vis-vega": 7}, False),
    ("14-vega-lite-crs-and-geometry-types.json", 15, 14,
     {"curio.builtin/data-loading": 1, "curio.builtin/data-transformation": 7,
      "curio.builtin/vis-vega": 7}, False),
    ("15-vega-lite-spec-forms-and-catalogs.json", 12, 10,
     {"curio.builtin/data-loading": 3, "curio.builtin/spatial-join": 1,
      "curio.builtin/vis-vega": 8}, False),
    ("16-simple-view-tables-and-images.json", 4, 2,
     {"curio.builtin/data-loading": 2, "curio.builtin/vis-simple": 2}, False),
    ("17-autark-geodataframe-maps.json", 15, 15,
     {"curio.builtin/data-loading": 1, "curio.builtin/data-transformation": 4,
      "curio.builtin/autk-grammar": 5, "curio.builtin/vis-vega": 5}, True),
    ("18-storage-orthorectified-imagery.json", 6, 5,
     {"curio.builtin/data-loading": 1, "curio.media/mosaic-rasters": 1,
      "curio.builtin/vis-vega": 1, "curio.builtin/vis-simple": 1}, False),
    ("19-storage-video-frames.json", 3, 2,
     {"curio.builtin/data-loading": 1, "curio.builtin/vis-simple": 1,
      "curio.builtin/vis-vega": 1}, False),
    ("20-storage-folder-of-csv-files.json", 5, 4,
     {"curio.builtin/data-loading": 2, "curio.builtin/computation-analysis": 1,
      "curio.builtin/vis-vega": 2}, False),
    ("21-storage-photos-and-videos.json", 5, 4,
     {"curio.builtin/data-loading": 1, "curio.media/video-frames": 1,
      "curio.builtin/vis-simple": 2, "curio.builtin/vis-vega": 1}, False),
    ("22-storage-audio-recordings.json", 4, 3,
     {"curio.builtin/data-loading": 1, "curio.media/split-audio": 1,
      "curio.builtin/vis-simple": 1, "curio.builtin/vis-vega": 1}, False),
    ("23-storage-folder-of-different-files.json", 4, 3,
     {"curio.builtin/data-loading": 2, "curio.builtin/computation-analysis": 1,
      "curio.builtin/vis-vega": 1}, False),
    ("24-scout-building-rasters.json", 7, 7,
     {"curio.builtin/data-loading": 1, "scout.raster-conversion/rasterize-buildings": 1,
      "scout.shadow/accumulated-shadow": 1, "curio.builtin/raster-statistics": 1,
      "curio.builtin/autk-grammar": 3}, False),
    ("25-several-inputs.json", 10, 14,
     {"curio.builtin/data-loading": 3, "curio.builtin/computation-analysis": 2,
      "curio.builtin/data-transformation": 1, "curio.builtin/js-computation": 1,
      "curio.builtin/vis-vega": 1, "curio.builtin/autk-grammar": 1,
      "curio.builtin/data-pool": 1}, False),
]


#: Examples whose flows meet in one node, and how many nodes take several data
#: inputs. Each such node reads its inputs in circle order (``in``, ``in_1``,
#: ...), so its edges must name every circle from the first, once each: a gap or
#: a repeat changes which input the node's ``[!! input N !!]`` chips read.
FAN_IN_NODES = {
    "04-vega-lite-multi-flow-dashboard.json": 3,
    "06-autark-what-if-shadow-study.json": 2,
    "08-autark-spatial-join-regression.json": 1,
    "09-heterogeneous-data-linked-views.json": 2,
    "20-storage-folder-of-csv-files.json": 1,
    "23-storage-folder-of-different-files.json": 1,
    "24-scout-building-rasters.json": 1,
    # Every kind of node that takes several inputs: Python (three), Data
    # Transformation, JS Computation, Vega-Lite, Autark and Data Pool.
    "25-several-inputs.json": 6,
}


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
    presence of marquee node types like AUTK_GRAMMAR, DATA_POOL, VIS_VEGA).
    Where flows meet in one node, ``test_example_flows_meet_on_input_circles``
    checks the circles they arrive on."""
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


def _circle_index(handle) -> int:
    if handle == "in":
        return 0
    match = re.fullmatch(r"in_(\d+)", str(handle))
    return int(match.group(1)) if match else -1


@pytest.mark.parametrize("basename,expected_fan_in", FAN_IN_NODES.items(), ids=list(FAN_IN_NODES))
def test_example_flows_meet_on_input_circles(basename, expected_fan_in):
    """Each node that takes several data edges takes them on its circles
    ``in``, ``in_1``, ... ``in_<k-1>``, one edge per circle, with no gap: the
    same order the canvas draws and the chips ``[!! input N !!]`` read."""
    with open(os.path.join(EXAMPLES_DIR, basename), "r", encoding="utf-8") as f:
        wf = json.load(f)
    types = {n["id"]: n["type"] for n in wf["dataflow"]["nodes"]}
    handles: dict[str, list] = {}
    for e in wf["dataflow"]["edges"]:
        if e.get("type") == "Interaction":
            continue
        handles.setdefault(e["target"], []).append(e.get("targetHandle"))
    fan_in = {target: hs for target, hs in handles.items() if len(hs) > 1}

    assert len(fan_in) == expected_fan_in, (
        f"{basename}: expected {expected_fan_in} node(s) taking several inputs, "
        f"got {len(fan_in)}: { {t: (types.get(t), hs) for t, hs in fan_in.items()} }"
    )
    for target, hs in fan_in.items():
        circles = ["in"] + [f"in_{k}" for k in range(1, len(hs))]
        assert sorted(hs, key=_circle_index) == circles, (
            f"{basename}: node {target} ({types.get(target)}) takes its inputs on "
            f"{hs}, not once each on {circles}"
        )


def test_example_06_is_three_scenarios_over_one_context():
    """Example 06 is a scenario study (#662). Baseline, Twice as tall and Two
    towers removed share the loader and the pool as fixed context. Each node of
    Twice as tall is a copy that names its Baseline twin and holds the same
    code, and the one value that differs is the shadow step's ``height_factor``
    widget, 1 against 2, which its spec reads as a uniform. Two towers removed
    is an Edit Features node that removes two towers, 200 Clarendon and
    Raffles, by their ``building_id``, before copies of Baseline's two nodes
    with factor 1."""
    path = os.path.join(EXAMPLES_DIR, "06-autark-what-if-shadow-study.json")
    with open(path, "r", encoding="utf-8") as f:
        flow = json.load(f)["dataflow"]
    nodes = {n["id"]: n for n in flow["nodes"]}
    baseline, twice, towers = flow["scenarios"]
    assert (baseline["name"], twice["name"], towers["name"]) == ("Baseline", "Twice as tall", "Two towers removed")
    assert not any(s.get("collapsed") for s in (baseline, twice, towers)), (
        "the shipped scenarios open expanded, so every node shows on the canvas"
    )
    outside = set(nodes) - set(baseline["nodes"]) - set(twice["nodes"]) - set(towers["nodes"])
    assert outside == {"whatif-data", "whatif-pool", "whatif-compare-chart", "whatif-compare-difference"}
    assert len(baseline["nodes"]) == len(twice["nodes"]) == 2
    for original, copy in zip(baseline["nodes"], twice["nodes"]):
        assert nodes[copy]["metadata"].get("copiedFrom") == [original], copy
        assert nodes[copy]["content"] == nodes[original]["content"], (
            f"{copy} holds other code than its twin {original}"
        )
    # Two towers removed: its Edit Features node, then copies of Baseline's two.
    edit, *copies = towers["nodes"]
    assert copies == ["whatif-towers-compute", "whatif-towers-map"]
    for original, copy in zip(baseline["nodes"], copies):
        assert nodes[copy]["metadata"].get("copiedFrom") == [original], copy
        assert nodes[copy]["content"] == nodes[original]["content"], (
            f"{copy} holds other code than its twin {original}"
        )
    assert nodes[edit]["type"] == "curio.builtin/edit-features"
    assert nodes[edit]["metadata"]["editFeatures"] == {
        "key": "building_id",
        "layer": "table_osm_buildings",
        "edits": [{"op": "remove", "ids": [119, 136]}],
    }
    assert '{"op": "remove", "ids": [119, 136]},' in nodes[edit]["content"]
    assert '], key="building_id", layer="table_osm_buildings")' in nodes[edit]["content"]
    feeds = sorted((edge["source"], edge["target"]) for edge in flow["edges"] if edit in (edge["source"], edge["target"]))
    assert feeds == [("whatif-pool", edit), (edit, "whatif-towers-compute")], (
        "Two towers removed reads the pool, the context the others read, through its Edit Features node"
    )

    def factor(node_id):
        [widget] = nodes[node_id]["metadata"]["widgets"]
        assert widget["name"] == "height_factor"
        return widget.get("value", widget["default"])

    assert (
        factor("whatif-baseline-compute"), factor("whatif-modified-compute"), factor("whatif-towers-compute"),
    ) == (1, 2, 1)
    # Both comparisons read the roads layer of what each scenario's map draws,
    # and Difference matches the roads by their shapes (they carry no id). The
    # chart compares the three scenarios; Difference, Twice as tall's change.
    expected_sources = {
        "whatif-compare-chart": ["whatif-baseline-map", "whatif-modified-map", "whatif-towers-map"],
        "whatif-compare-difference": ["whatif-baseline-map", "whatif-modified-map"],
    }
    for compare, expected in expected_sources.items():
        settings = nodes[compare]["metadata"]["compareScenarios"]
        assert settings["layer"] == "table_osm_roads", compare
        assert 'layer="table_osm_roads")' in nodes[compare]["content"], compare
        sources = sorted(edge["source"] for edge in flow["edges"] if edge["target"] == compare)
        assert sources == expected, compare
    chart = nodes["whatif-compare-chart"]
    assert [(label["scenario"], label["name"], label["color"]) for label in chart["metadata"]["compareScenarios"]["inputs"]] == [
        (s["id"], s["name"], s["color"]) for s in (baseline, twice, towers)
    ]
    assert '("s-towers", "Two towers removed", [!! input 2 !!]),' in chart["content"]
    third = [e for e in flow["edges"] if e["target"] == "whatif-compare-chart" and e["source"] == "whatif-towers-map"]
    assert [e.get("targetHandle") for e in third] == ["in_2"]
    assert "key" not in nodes["whatif-compare-difference"]["metadata"]["compareScenarios"].get("difference", {})
    shader = nodes["whatif-baseline-compute"]["content"]
    assert '"height_factor": [!! height_factor !!]' in shader
    assert "let height = height_factor * bld_height[bi];" in shader


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
            f'curio_data_path("<id>") against the Data Catalog '
            f"(datasets/), or add the file to _DATA_DIR_ALLOWLIST with a reason "
            f"if it genuinely cannot move."
        )


def test_examples_that_load_catalog_data_declare_it_in_the_spec():
    """A ``curio_load_data``, ``curio_data_path`` or ``curio_load_collection``
    call and a ``dataflow.datasets`` ref go together.

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
                    r"""curio_(?:load_data|data_path|load_collection)\(\s*["']([^"']+)["']\s*\)""",
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


#: URL prefixes an example node may legitimately reference. Vega-Lite specs
#: carry their ``$schema`` URL, which the renderer never fetches.
_EXTERNAL_URL_ALLOWLIST = (
    "https://vega.github.io/schema/",
    # The credit in the SCOUT packages' template docstrings, which example 24's
    # package nodes carry unchanged; nothing is fetched from it.
    "https://github.com/urban-toolkit/scout",
)

_EXTERNAL_URL = re.compile(r"""https?://[^\s"'\)\]]+""")


def test_example_nodes_do_not_fetch_external_urls():
    """No example node reads its data from a live third-party URL (#276).

    Example 10 fetched Chicago's neighborhood boundaries from a Socrata id that
    the portal later retired, so a curated example failed on its first node with
    a 404 on a fresh install. Open-data portals rename and retire resources; a
    layer an example depends on belongs in ``datasets/`` as a catalog entry,
    loaded with ``curio_data_path``. Anything else here needs an allowlist
    entry with a reason.
    """
    for path in _example_json_paths():
        spec = json.load(open(path, encoding="utf-8"))
        for node in spec["dataflow"]["nodes"]:
            urls = sorted({
                url
                for url in _EXTERNAL_URL.findall(node.get("content") or "")
                if not url.startswith(_EXTERNAL_URL_ALLOWLIST)
            })
            assert not urls, (
                f"{os.path.basename(path)} node {node.get('id')} fetches "
                f"{urls}. Vendor the data under datasets/ and load it with "
                f'curio_data_path("<id>"), or allowlist the prefix with a '
                f"reason in _EXTERNAL_URL_ALLOWLIST."
            )


def test_examples_declared_datasets_exist_in_the_catalog():
    """Every ``dataflow.datasets`` ref points at a shipped catalog directory.

    The parity test above proves the ref matches the node; this proves the ref
    matches the repository. A ref to a directory that is not committed passes
    every structural check and then fails at run time, when the seeder has
    nothing to provision and ``curio_data_path`` cannot resolve.
    """
    datasets_dir = os.path.join(REPO_ROOT, "datasets")
    for path in _example_json_paths():
        spec = json.load(open(path, encoding="utf-8"))
        for ref in spec["dataflow"].get("datasets") or []:
            root = os.path.join(datasets_dir, ref["dirName"])
            manifest_path = os.path.join(root, "manifest.json")
            assert os.path.isfile(manifest_path), (
                f"{os.path.basename(path)} declares {ref['dirName']} but "
                f"{manifest_path} does not exist"
            )
            manifest = json.load(open(manifest_path, encoding="utf-8"))
            assert manifest["id"] == ref["datasetId"], (
                f"{ref['dirName']}/manifest.json id {manifest['id']!r} != "
                f"ref datasetId {ref['datasetId']!r}"
            )
            data_file = os.path.join(root, manifest["dataFile"])
            assert os.path.isfile(data_file), (
                f"{ref['dirName']} manifest names {manifest['dataFile']} but "
                f"the file is missing"
            )
