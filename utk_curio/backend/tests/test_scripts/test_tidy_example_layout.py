"""Does ``scripts/tidy_example_layout.py`` stay safe to point at a spec?

Two properties matter, and they pull against each other.

The first is that the committed gallery stays tidy: ``--check`` over
``docs/examples/`` must exit 0 forever. Seven pairs of node boxes overlapped
outright before this script ran, and a gallery example that draws boxes on top
of each other is the first thing a new user sees. ``test_the_committed_examples_
are_already_tidy`` is the standing guard; when it fails, someone moved a node and
the fix is ``--write``.

The second is that the script never touches anything but coordinates. It rewrites
files that gate dozens of screenshot baselines, so a stray reformat would bury
the real diff. ``test_write_touches_only_coordinates`` pins that line by line,
and ``test_a_file_that_does_not_round_trip_is_refused`` pins the refusal that
makes it true rather than hopeful.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from utk_curio.backend.app.projects.seed import _repo_root

REPO_ROOT = str(_repo_root())
SCRIPT = os.path.join(REPO_ROOT, "scripts", "tidy_example_layout.py")
EXAMPLES = os.path.join(REPO_ROOT, "docs", "examples")


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _spec(nodes, edges) -> dict:
    return {
        "dataflow": {
            "nodes": nodes,
            "edges": edges,
            "name": "Fixture",
            "task": "",
            "timestamp": 1748990000000,
            "provenance_id": "Fixture",
        }
    }


def _node(node_id, x, y, node_type="curio.builtin/data-loading", **extra) -> dict:
    node = {
        "id": node_id,
        "type": node_type,
        "x": x,
        "y": y,
        "in": "DEFAULT",
        "out": "DEFAULT",
        "goal": "",
        "content": "print(1)",
        "metadata": {"keywords": []},
    }
    node.update(extra)
    return node


def _edge(source, target, **extra) -> dict:
    edge = {"id": f"e-{source}-{target}", "source": source, "target": target}
    edge.update(extra)
    return edge


def _write_spec(path, spec) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(spec, indent=2))


def _boxes(dataflow, default=(525, 350)):
    return [
        (n["x"], n["y"], n.get("width", default[0]), n.get("height", default[1]))
        for n in dataflow["nodes"]
    ]


def _separation(a, b) -> float:
    gap_x = max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))
    gap_y = max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))
    return max(gap_x, gap_y)


def _min_separation(boxes) -> float:
    return min(
        _separation(boxes[i], boxes[j])
        for i in range(len(boxes))
        for j in range(i + 1, len(boxes))
    )


# ---------------------------------------------------------------------------
# CLI contract
# ---------------------------------------------------------------------------

def test_help_exits_zero():
    assert _run("--help").returncode == 0


def test_all_and_explicit_paths_together_is_a_usage_error():
    result = _run("--all", os.path.join(EXAMPLES, "11-autark-pbf-loading.json"))
    assert result.returncode == 2
    assert "not both" in result.stderr


def test_no_arguments_is_a_usage_error():
    assert _run().returncode == 2


def test_a_missing_path_exits_two():
    result = _run(os.path.join(EXAMPLES, "does-not-exist.json"))
    assert result.returncode == 2
    assert "No such path" in result.stderr


# ---------------------------------------------------------------------------
# The standing guard
# ---------------------------------------------------------------------------

def test_the_committed_examples_are_already_tidy():
    """The whole point: the shipped gallery has no overlapping nodes.

    When this fails, someone moved a node in ``docs/examples/`` by hand. Run
    ``python scripts/tidy_example_layout.py --all --write`` and review the diff.
    """
    result = _run("--all")
    assert result.returncode == 0, result.stderr


def test_every_committed_example_clears_the_gutter():
    """Independent of the script's own arithmetic: re-measure the files.

    Sizes here use only the two template overrides that exist today, so this
    check cannot pass by sharing a bug with ``resolve_size``.
    """
    overrides = {
        "curio.builtin/spatial-join": (280, 170),
        "curio.builtin/merge-flow": (50, 180),
    }
    import glob

    for path in sorted(glob.glob(os.path.join(EXAMPLES, "[0-9][0-9]-*.json"))):
        with open(path, encoding="utf-8") as fh:
            dataflow = json.load(fh)["dataflow"]
        boxes = []
        for node in dataflow["nodes"]:
            base = overrides.get(node["type"].split("@")[0], (525, 350))
            boxes.append(
                (
                    node["x"],
                    node["y"],
                    node.get("width", base[0]),
                    node.get("height", base[1]),
                )
            )
        if len(boxes) < 2:
            continue
        assert _min_separation(boxes) >= 60, f"{os.path.basename(path)} crowds"


# ---------------------------------------------------------------------------
# Check vs write
# ---------------------------------------------------------------------------

def test_a_jittered_example_is_reported_as_drift(tmp_path):
    source = os.path.join(EXAMPLES, "11-autark-pbf-loading.json")
    target = tmp_path / "11-autark-pbf-loading.json"
    shutil.copyfile(source, target)
    with open(target, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["dataflow"]["nodes"][0]["x"] += 37
    _write_spec(target, doc)

    result = _run(str(target))
    assert result.returncode == 1
    assert "DRIFT" in result.stderr
    assert "11-autark-pbf-loading.json" in result.stderr


def test_check_mode_never_writes(tmp_path):
    target = tmp_path / "crowded.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 10, 10)],
        [_edge("a", "b")],
    ))
    before = target.read_bytes()

    assert _run(str(target)).returncode == 1
    assert target.read_bytes() == before


def test_write_separates_overlapping_nodes(tmp_path):
    target = tmp_path / "crowded.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 10, 10), _node("c", 20, 20)],
        [_edge("a", "b"), _edge("b", "c")],
    ))

    assert _run(str(target), "--write").returncode == 0
    with open(target, encoding="utf-8") as fh:
        dataflow = json.load(fh)["dataflow"]
    assert _min_separation(_boxes(dataflow)) >= 60


def test_write_is_idempotent(tmp_path):
    target = tmp_path / "crowded.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 10, 10), _node("c", 20, 20)],
        [_edge("a", "b"), _edge("a", "c")],
    ))

    assert _run(str(target), "--write").returncode == 0
    once = target.read_bytes()
    assert _run(str(target), "--write").returncode == 0
    assert target.read_bytes() == once
    assert _run(str(target)).returncode == 0


def test_a_wrapped_rank_is_idempotent(tmp_path):
    """The bug that made the first draft of this script useless.

    A rank wider than MAX_ROWS_PER_COLUMN wraps into sub-columns that both start
    near y=0. The layout used to seed each rank's order from the authored ``y``,
    so a second pass read the two sub-columns back interleaved and produced a
    different -- still valid, but different -- layout. ``--check`` can only mean
    something if the layout is a fixed point, so the order is seeded from file
    order and the authored coordinates are not an input at all.
    """
    fan = [_node("src", 0, 0)] + [_node(f"leaf{i}", 0, 0) for i in range(8)]
    target = tmp_path / "fan.json"
    _write_spec(target, _spec(fan, [_edge("src", f"leaf{i}") for i in range(8)]))

    assert _run(str(target), "--write").returncode == 0
    first = target.read_bytes()
    assert _run(str(target), "--write").returncode == 0
    assert target.read_bytes() == first
    assert _run(str(target)).returncode == 0

    with open(target, encoding="utf-8") as fh:
        dataflow = json.load(fh)["dataflow"]
    # The fan really did wrap: the leaves occupy more than one column.
    leaf_columns = {n["x"] for n in dataflow["nodes"] if n["id"].startswith("leaf")}
    assert len(leaf_columns) > 1
    assert _min_separation(_boxes(dataflow)) >= 60


def test_write_touches_only_coordinates(tmp_path):
    """The standing promise, pinned line by line."""
    source = os.path.join(EXAMPLES, "04-vega-lite-multi-flow-dashboard.json")
    target = tmp_path / "04.json"
    shutil.copyfile(source, target)
    with open(target, encoding="utf-8") as fh:
        doc = json.load(fh)
    for node in doc["dataflow"]["nodes"]:
        node["x"] += 13
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=2, ensure_ascii=True))
    before = target.read_text(encoding="utf-8").splitlines()

    assert _run(str(target), "--write").returncode == 0
    after = target.read_text(encoding="utf-8").splitlines()

    assert len(before) == len(after)
    for old, new in zip(before, after):
        if old != new:
            assert old.lstrip().startswith(('"x":', '"y":')), old
            assert new.lstrip().startswith(('"x":', '"y":')), new


def test_a_file_that_does_not_round_trip_is_refused(tmp_path):
    """Four-space indent is someone else's formatting. Refuse, do not reflow."""
    target = tmp_path / "four-space.json"
    spec = _spec([_node("a", 0, 0), _node("b", 10, 10)], [_edge("a", "b")])
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(spec, indent=4))
    before = target.read_bytes()

    result = _run(str(target), "--write")
    assert result.returncode == 2
    assert "would reformat the whole file" in result.stderr
    assert target.read_bytes() == before


# ---------------------------------------------------------------------------
# Graph shapes that must not hang or mislay
# ---------------------------------------------------------------------------

def test_an_interaction_cycle_lays_out(tmp_path):
    """07/08/09 all carry an Interaction edge doubling back over a data edge."""
    target = tmp_path / "interaction.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 10, 10)],
        [_edge("a", "b"), _edge("b", "a", type="Interaction")],
    ))

    result = _run(str(target), "--write")
    assert result.returncode == 0, result.stderr
    with open(target, encoding="utf-8") as fh:
        dataflow = json.load(fh)["dataflow"]
    # The data edge still decides the reading order.
    by_id = {n["id"]: n for n in dataflow["nodes"]}
    assert by_id["a"]["x"] < by_id["b"]["x"]


def test_a_genuine_data_cycle_lays_out(tmp_path):
    """The cycle-breaker: a hand-edited spec must not hang the tool."""
    target = tmp_path / "cycle.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 10, 10), _node("c", 20, 20)],
        [_edge("a", "b"), _edge("b", "c"), _edge("c", "a")],
    ))

    result = _run(str(target), "--write")
    assert result.returncode == 0, result.stderr
    with open(target, encoding="utf-8") as fh:
        dataflow = json.load(fh)["dataflow"]
    assert _min_separation(_boxes(dataflow)) >= 60


def test_a_disconnected_node_is_still_placed(tmp_path):
    target = tmp_path / "island.json"
    _write_spec(target, _spec(
        [_node("a", 0, 0), _node("b", 0, 0), _node("island", 0, 0)],
        [_edge("a", "b")],
    ))

    assert _run(str(target), "--write").returncode == 0
    with open(target, encoding="utf-8") as fh:
        dataflow = json.load(fh)["dataflow"]
    assert _min_separation(_boxes(dataflow)) >= 60


# ---------------------------------------------------------------------------
# Size resolution
# ---------------------------------------------------------------------------

def test_a_metadata_height_is_packed_on(tmp_path):
    """The precedence level nothing else exercises.

    ``useCode.ts`` accepts ``metadata.nodeHeight`` as the third fallback. Packing
    a 1200px node as if it were 350 would put the next node straight through it.
    """
    target = tmp_path / "metadata-size.json"
    tall = _node("tall", 0, 0)
    tall["metadata"] = {"keywords": [], "nodeHeight": 1200}
    _write_spec(target, _spec(
        [tall, _node("under", 0, 0)],
        [],
    ))

    assert _run(str(target), "--write").returncode == 0
    with open(target, encoding="utf-8") as fh:
        nodes = {n["id"]: n for n in json.load(fh)["dataflow"]["nodes"]}
    boxes = [
        (nodes["tall"]["x"], nodes["tall"]["y"], 525, 1200),
        (nodes["under"]["x"], nodes["under"]["y"], 525, 350),
    ]
    assert _separation(boxes[0], boxes[1]) >= 60


def test_a_merge_flow_sliver_keeps_its_real_footprint(tmp_path):
    """``merge-flow`` is 50x180, not 525x350. Packing it as the default would
    leave a 475px hole in every column it appears in."""
    target = tmp_path / "sliver.json"
    _write_spec(target, _spec(
        [
            _node("a", 0, 0),
            _node("m", 0, 0, node_type="curio.builtin/merge-flow"),
            _node("b", 0, 0),
        ],
        [_edge("a", "m"), _edge("m", "b")],
    ))

    assert _run(str(target), "--write").returncode == 0
    with open(target, encoding="utf-8") as fh:
        nodes = {n["id"]: n for n in json.load(fh)["dataflow"]["nodes"]}
    # 525 + 120 gutter, plus the merge node centred in its own 50px slot.
    assert nodes["m"]["x"] - (nodes["a"]["x"] + 525) == 120
    assert nodes["b"]["x"] - (nodes["m"]["x"] + 50) == 120
