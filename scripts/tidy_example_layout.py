#!/usr/bin/env python3
"""Lay the curated example dataflows out so no two nodes overlap.

WHY
---
``docs/examples/*.json`` is seeded into every account (``projects/seed.py``), so
these eleven files are the first dataflows anyone sees. Node coordinates in them
are whatever the canvas happened to hold when the author hit "Save dataflow as",
and nothing downstream corrects them: ``useCode.loadTrill`` copies ``x``/``y``
straight into a React Flow position, and ``_extract_graph_preview`` feeds the
same numbers to the gallery thumbnail.

Measured before this script existed: seven pairs of node boxes overlapped
outright (three in ``04``, two in ``06``, one each in ``05`` and ``10``) and
twenty-two more sat under a 60px gutter. A gallery example that draws boxes on
top of each other is not a small blemish -- it is the product's first impression.

A script rather than a one-time hand edit, because the layout rots the moment
anyone adds a node to an example. ``--check`` is the standing guard; ``--write``
is the fix. Both resolve node sizes the same four-deep way the app does, so the
geometry it reasons about is the geometry that renders.

The standing promise: **the only bytes this tool ever changes are the ``x`` and
``y`` values on ``dataflow.nodes[]``.** Every file is round-tripped through the
exact ``json.dumps`` settings that reproduce it byte-for-byte before anything is
mutated, and a file that cannot be reproduced that way is refused rather than
reformatted as a side effect (exit 2).

Layout is plain stdlib, deliberately not the frontend's ``dagre``: these
coordinates are a committed artifact that gates dozens of PNG baselines, and a
dagre version bump must not be able to move them with no source diff to point
at. The vocabulary is dagre's though -- ``H_GUTTER`` is its ``ranksep``,
``V_GUTTER`` its ``nodesep`` (compare ``src/utils/provenanceLayout.ts``).

HOW
---
    python scripts/tidy_example_layout.py --all                # check, exit 1 on drift
    python scripts/tidy_example_layout.py --all --write        # apply
    python scripts/tidy_example_layout.py --all --report       # geometry table
    python scripts/tidy_example_layout.py docs/examples/04-vega-lite-multi-flow-dashboard.json --write

Exit code is 0 when every file is already tidy (check) or was written and passed
its post-write self-check (write), 1 on drift or a failed self-check, and 2 on a
usage problem such as an unreadable path or a file that cannot be rewritten
without reformatting it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utk_curio.backend.app.packages.spec_packages import (  # noqa: E402
    unversioned_node_type,
)

# Node geometry, mirroring the renderer. 525x350 is NodeContainer's fallback
# (frontend/urban-workflows/src/components/styles.tsx); a template may override
# it through `containerStyle.nodeWidth/nodeHeight`, and a node may override that
# again with its own `width`/`height`.
DEFAULT_NODE_WIDTH = 525
DEFAULT_NODE_HEIGHT = 350

# Layout constants. H_GUTTER is deliberately NOT NotebookConvertor's
# COLUMN_STRIDE (700): that is a centre-to-centre stride for uniform 525-wide
# boxes, which works out to a ~175px gap. We pack real widths, so the gap itself
# is the constant.
H_GUTTER = 120
V_GUTTER = 80

# A rank taller than this wraps into sub-columns. Mirrors
# NotebookConvertor.MAX_ROWS_PER_LEVEL and its reason: without it, 05's nine
# parallel chart sinks make a portrait canvas that fitView shrinks harder than
# the layout it replaced.
MAX_ROWS_PER_COLUMN = 6

BARYCENTER_SWEEPS = 4
ALIGN_PASSES = 8

# An Interaction edge duplicates a data edge's direction but means "these two
# talk to each other", so it pulls its endpoints together at half strength
# rather than defining a rank.
INTERACTION_WEIGHT = 0.5

# The invariant the post-layout self-check enforces. Slack under the 80px the
# layout actually produces, so integer rounding cannot trip it.
MIN_GUTTER = 60

# NOTE: mirrors scripts/validate_trill.py::_NOT_TRILL.
_NOT_TRILL = {
    "manifest.json",
    "integrity.json",
    "default-packages.json",
    ".seed-state.json",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
}


# ---------------------------------------------------------------------------
# Corpus and node sizes
# ---------------------------------------------------------------------------

def _curated_examples() -> list[Path]:
    """The numbered gallery examples, and nothing else.

    Deliberately narrower than ``validate_trill.py --all``:
    ``docs/examples/dataflows/`` holds hand-tuned single-feature fixtures with
    their own screenshot baselines (measured clean), and ``.curio/`` is the
    user's own work, which this tool has no business rearranging.
    """
    return sorted((REPO_ROOT / "docs" / "examples").glob("[0-9][0-9]-*.json"))


# NOTE: mirrors scripts/validate_trill.py::_template_index.
def _template_index() -> dict[str, dict]:
    """Map ``<packageId>/<templateId>`` to its template, from ``packages/``."""
    index: dict[str, dict] = {}
    for manifest_path in sorted((REPO_ROOT / "packages").glob("*/manifest.json")):
        try:
            with manifest_path.open(encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        package_id = manifest.get("id")
        if not isinstance(package_id, str):
            continue
        for template in manifest.get("templates") or []:
            if isinstance(template, dict) and isinstance(template.get("id"), str):
                index[f"{package_id}/{template['id']}"] = template
    return index


# NOTE: mirrors scripts/validate_trill.py::_looks_like_trill / _files_under / _rel.
def _looks_like_trill(path: Path) -> bool:
    if path.name in _NOT_TRILL:
        return False
    if path.name.endswith(".trill.json"):
        return True
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(doc, dict) and "dataflow" in doc


def _files_under(target: Path) -> list[Path]:
    if not target.is_dir():
        return [target]
    return sorted(
        p
        for p in target.rglob("*.json")
        if p.parent.name != "data" and _looks_like_trill(p)
    )


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _number(value):
    """``typeof value === "number"`` semantics, not truthiness.

    A width of ``0`` is a number and must win over the fallback; ``True`` is an
    ``int`` in Python and must not.
    """
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _first_number(*candidates):
    for candidate in candidates:
        number = _number(candidate)
        if number is not None:
            return number
    return None


def resolve_size(node: dict, templates: dict[str, dict]) -> tuple[float, float]:
    """The node's rendered box, mirroring the app's four-deep precedence.

    ``useCode.ts`` reads ``width | nodeWidth | metadata.width |
    metadata.nodeWidth`` into ``data.nodeWidth``; ``UniversalNode.tsx`` then does
    ``data.nodeWidth ?? adapter.container.nodeWidth``; ``styles.tsx`` falls back
    to 525x350. Today only ``curio.builtin/spatial-join`` (280x170) and
    ``curio.builtin/merge-flow`` (50x180) set a template size.
    """
    meta = node.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    template = templates.get(unversioned_node_type(node.get("type") or "")) or {}
    style = template.get("containerStyle")
    style = style if isinstance(style, dict) else {}

    width = _first_number(
        node.get("width"), node.get("nodeWidth"),
        meta.get("width"), meta.get("nodeWidth"),
        style.get("nodeWidth"),
    )
    height = _first_number(
        node.get("height"), node.get("nodeHeight"),
        meta.get("height"), meta.get("nodeHeight"),
        style.get("nodeHeight"),
    )
    return (
        DEFAULT_NODE_WIDTH if width is None else width,
        DEFAULT_NODE_HEIGHT if height is None else height,
    )


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _partition_edges(edges, known: set[str]):
    """Split into ranking edges and Interaction edges, both deduped.

    Interaction edges are excluded from ranking: with them removed every shipped
    example is a DAG, and each one duplicates a data edge with the same
    ``(source, target)`` anyway, so nothing structural is lost. They still pull
    their endpoints together during ordering.
    """
    ranking: list[tuple[str, str]] = []
    interaction: list[tuple[str, str]] = []
    seen_rank: set[tuple[str, str]] = set()
    seen_inter: set[tuple[str, str]] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source"), edge.get("target")
        if source not in known or target not in known or source == target:
            continue
        pair = (source, target)
        if edge.get("type") == "Interaction":
            if pair not in seen_inter:
                seen_inter.add(pair)
                interaction.append(pair)
        elif pair not in seen_rank:
            seen_rank.add(pair)
            ranking.append(pair)
    return ranking, interaction


def _break_cycles(pairs, order: list[str]) -> list[tuple[str, str]]:
    """Drop back edges so ranking terminates.

    Never fires on the shipped examples -- it is what makes the tool safe to
    point at an arbitrary hand-edited spec instead of hanging on it. Iterative
    DFS in stable node order; a dropped edge is dropped from *ranking* only and
    still participates in the barycenter, so a cyclic region stays together.
    """
    out = defaultdict(list)
    for source, target in pairs:
        out[source].append(target)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = {node: WHITE for node in order}
    dropped: set[tuple[str, str]] = set()

    for root in order:
        if colour[root] != WHITE:
            continue
        colour[root] = GREY
        stack = [(root, iter(out[root]))]
        while stack:
            node, children = stack[-1]
            advanced = False
            for child in children:
                if colour[child] == GREY:
                    dropped.add((node, child))  # back edge
                elif colour[child] == WHITE:
                    colour[child] = GREY
                    stack.append((child, iter(out[child])))
                    advanced = True
                    break
            if not advanced:
                colour[node] = BLACK
                stack.pop()
    return [pair for pair in pairs if pair not in dropped]


def _longest_path_ranks(pairs, order: list[str]) -> dict[str, int]:
    """rank[v] = longest path from any source. Every loader lands in column 0."""
    out = defaultdict(list)
    indegree = {node: 0 for node in order}
    for source, target in pairs:
        out[source].append(target)
        indegree[target] += 1

    rank = {node: 0 for node in order}
    queue = [node for node in order if indegree[node] == 0]
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        for child in out[node]:
            rank[child] = max(rank[child], rank[node] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    return rank


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _order_within_ranks(columns, rank, ranking, interaction, size, file_index):
    """Barycenter sweeps, seeded from the order nodes appear in the file.

    Deliberately NOT seeded from the authored ``y``, tempting though that is as
    a way to preserve the author's vertical intent. The seed would then be a
    value this tool overwrites, so ``tidy(tidy(spec)) != tidy(spec)`` and
    ``--check`` would be meaningless. It is not hypothetical: 04 has a rank of
    eight that wraps into two sub-columns, both starting near y=0, so a second
    pass read them back interleaved and produced a different layout.

    Seeding from file order instead makes the layout a pure function of the
    graph, the node order, and the sizes -- none of which writing ``x``/``y``
    can change. File order is also close to creation order, so parallel branches
    still come out in the order the author built them.

    The sweeps do the real work from there, and they un-cross edges any seed
    would have crossed: example 01's tall chart is authored topmost but fed by
    the *lower* branch.
    """
    neighbours_up = defaultdict(list)    # node -> [(pred, weight)]
    neighbours_down = defaultdict(list)  # node -> [(succ, weight)]
    for source, target in ranking:
        neighbours_up[target].append((source, 1.0))
        neighbours_down[source].append((target, 1.0))
    for source, target in interaction:
        # Orient by the ranks the data edges established, so an interacting view
        # stays level with the pool it reads.
        low, high = (source, target) if rank[source] <= rank[target] else (target, source)
        if rank[low] != rank[high]:
            neighbours_up[high].append((low, INTERACTION_WEIGHT))
            neighbours_down[low].append((high, INTERACTION_WEIGHT))

    position = {}
    for nodes in columns.values():
        for slot, node in enumerate(nodes):
            position[node] = slot

    def sweep(ranks_in_order, neighbours, is_relevant):
        for r in ranks_in_order:
            nodes = columns[r]
            if len(nodes) < 2:
                continue
            keys = {}
            for node in nodes:
                related = [
                    (position[other], weight)
                    for other, weight in neighbours[node]
                    if is_relevant(rank[other], r)
                ]
                if related:
                    total = sum(weight for _, weight in related)
                    keys[node] = sum(p * w for p, w in related) / total
                else:
                    keys[node] = float(position[node])
            # Ties: taller last (keeps a 1613px chart from stranding at the top
            # of its column), then previous position, then file order. Every
            # term is total, so the sweep is idempotent.
            nodes.sort(key=lambda n: (keys[n], size[n][1], position[n], file_index[n]))
            for slot, node in enumerate(nodes):
                position[node] = slot

    ranks_ascending = sorted(columns)
    for _ in range(BARYCENTER_SWEEPS):
        sweep(ranks_ascending[1:], neighbours_up, lambda other, here: other < here)
        sweep(ranks_ascending[-2::-1], neighbours_down, lambda other, here: other > here)


def _wrap(nodes: list[str], max_rows: int) -> list[list[str]]:
    """Split an over-full rank into equal, order-preserving sub-columns."""
    if max_rows <= 0 or len(nodes) <= max_rows:
        return [nodes]
    chunks = -(-len(nodes) // max_rows)  # ceil
    per = -(-len(nodes) // chunks)
    return [nodes[i:i + per] for i in range(0, len(nodes), per)]


def _align_columns(slots, slot_of, ranking, size, x, y):
    """Shift whole sub-columns so each node sits level with its neighbours.

    MEDIAN of the per-node deltas, not the mean: example 01's 1613px-tall chart
    has an 806px half-height that would otherwise drag its entire column off the
    flow axis.
    """
    preds = defaultdict(list)
    succs = defaultdict(list)
    for source, target in ranking:
        preds[target].append(source)
        succs[source].append(target)

    def centre(node):
        return y[node] + size[node][1] / 2

    def shift(index, neighbours, is_relevant):
        deltas = []
        for node in slots[index]:
            related = [n for n in neighbours[node] if is_relevant(slot_of[n], index)]
            if related:
                deltas.append(sum(centre(n) for n in related) / len(related) - centre(node))
        if not deltas:
            return
        delta = median(deltas)
        for node in slots[index]:
            y[node] += delta

    for _ in range(ALIGN_PASSES):
        for index in range(1, len(slots)):
            shift(index, preds, lambda other, here: other < here)
        for index in range(len(slots) - 2, -1, -1):
            shift(index, succs, lambda other, here: other > here)


def tidy_layout(dataflow: dict, templates: dict[str, dict], *,
                h_gutter: int = H_GUTTER, v_gutter: int = V_GUTTER,
                max_rows: int = MAX_ROWS_PER_COLUMN):
    """Compute ``{node_id: (x, y)}`` plus a geometry report for one dataflow."""
    nodes = [
        n for n in (dataflow.get("nodes") or [])
        if isinstance(n, dict) and isinstance(n.get("id"), str)
    ]
    if not nodes:
        return {}, {"nodes": 0, "slots": 0, "columns": [], "extent": (0, 0),
                    "min_gutter": float("inf"), "overlaps": 0}

    order = [n["id"] for n in nodes]
    file_index = {node_id: i for i, node_id in enumerate(order)}
    size = {n["id"]: resolve_size(n, templates) for n in nodes}
    known = set(order)

    ranking, interaction = _partition_edges(dataflow.get("edges") or [], known)
    acyclic = _break_cycles(ranking, order)
    rank = _longest_path_ranks(acyclic, order)

    # Columns are seeded in file order -- see _order_within_ranks on why the
    # authored y deliberately plays no part.
    columns: dict[int, list[str]] = defaultdict(list)
    for node_id in order:
        columns[rank[node_id]].append(node_id)

    _order_within_ranks(columns, rank, acyclic, interaction, size, file_index)

    slots: list[list[str]] = []
    for r in sorted(columns):
        slots.extend(_wrap(columns[r], max_rows))
    slot_of = {node: index for index, slot in enumerate(slots) for node in slot}

    x: dict[str, float] = {}
    y: dict[str, float] = {}
    cursor = 0.0
    for slot in slots:
        slot_width = max(size[node][0] for node in slot)
        top = 0.0
        for node in slot:
            # Centre a narrow node in its slot rather than left-aligning it: a
            # 50px merge-flow sharing a rank with 525px charts would otherwise
            # strand its output handle 475px from the lane edge.
            x[node] = cursor + (slot_width - size[node][0]) / 2
            y[node] = top
            top += size[node][1] + v_gutter
        cursor += slot_width + h_gutter

    _align_columns(slots, slot_of, acyclic, size, x, y)

    min_x = min(x.values())
    min_y = min(y.values())
    layout = {node: (round(x[node] - min_x), round(y[node] - min_y)) for node in order}

    boxes = [(layout[n][0], layout[n][1], size[n][0], size[n][1]) for n in order]
    report = {
        "nodes": len(order),
        "slots": len(slots),
        "columns": [len(slot) for slot in slots],
        "extent": (
            round(max(b[0] + b[2] for b in boxes)),
            round(max(b[1] + b[3] for b in boxes)),
        ),
        "min_gutter": _min_gutter(boxes),
        "overlaps": _overlaps(boxes),
    }
    return layout, report


def _separation(a, b) -> float:
    """How far apart two boxes are; negative means they overlap on both axes."""
    gap_x = max(a[0] - (b[0] + b[2]), b[0] - (a[0] + a[2]))
    gap_y = max(a[1] - (b[1] + b[3]), b[1] - (a[1] + a[3]))
    return max(gap_x, gap_y)


def _min_gutter(boxes) -> float:
    if len(boxes) < 2:
        return float("inf")
    return min(
        _separation(boxes[i], boxes[j])
        for i in range(len(boxes))
        for j in range(i + 1, len(boxes))
    )


def _overlaps(boxes) -> int:
    return sum(
        1
        for i in range(len(boxes))
        for j in range(i + 1, len(boxes))
        if _separation(boxes[i], boxes[j]) < 0
    )


def measure(dataflow: dict, templates: dict[str, dict]) -> dict:
    """Overlap/gutter stats for a dataflow exactly as it stands on disk."""
    boxes = []
    for node in dataflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        width, height = resolve_size(node, templates)
        x = _number(node.get("x"))
        y = _number(node.get("y"))
        boxes.append((0.0 if x is None else x, 0.0 if y is None else y, width, height))
    return {"overlaps": _overlaps(boxes), "min_gutter": _min_gutter(boxes)}


# ---------------------------------------------------------------------------
# Byte-faithful rewriting
# ---------------------------------------------------------------------------

def _dump_settings(raw: str, doc):
    """Find the ``json.dumps`` settings that reproduce ``raw`` exactly.

    Returns ``(ensure_ascii, trailing_newline)``, or ``None`` when no setting
    reproduces the file -- in which case we refuse to touch it rather than
    reformat someone's file as a side effect of moving nodes. The shipped corpus
    splits both ways: 08 and 10 carry non-ASCII prose, and only 06, 08 and 10
    end with a newline.
    """
    for ensure_ascii in (True, False):
        candidate = json.dumps(doc, indent=2, ensure_ascii=ensure_ascii)
        if raw == candidate:
            return ensure_ascii, False
        if raw == candidate + "\n":
            return ensure_ascii, True
    return None


def _write(path: Path, doc, ensure_ascii: bool, trailing_newline: bool) -> None:
    text = json.dumps(doc, indent=2, ensure_ascii=ensure_ascii)
    if trailing_newline:
        text += "\n"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Per-file driver
# ---------------------------------------------------------------------------

def process(path: Path, templates: dict[str, dict], args) -> int:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Cannot read {_rel(path)}: {exc}", file=sys.stderr)
        return 2
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Not valid JSON: {_rel(path)}: {exc}", file=sys.stderr)
        return 2

    dataflow = doc.get("dataflow") if isinstance(doc, dict) else None
    if not isinstance(dataflow, dict) or not isinstance(dataflow.get("nodes"), list):
        print(f"No dataflow.nodes in {_rel(path)}", file=sys.stderr)
        return 2

    before = measure(dataflow, templates)
    layout, report = tidy_layout(
        dataflow, templates,
        h_gutter=args.gutter_x, v_gutter=args.gutter_y, max_rows=args.max_rows,
    )

    if report["overlaps"] or report["min_gutter"] < MIN_GUTTER:
        print(
            f"  FAIL {_rel(path)}: computed layout is not clean "
            f"({report['overlaps']} overlaps, min gutter {report['min_gutter']:.0f})",
            file=sys.stderr,
        )
        return 1

    placed = [
        node for node in dataflow["nodes"]
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    ]
    moved = [
        node["id"] for node in placed
        if node.get("x") != layout[node["id"]][0] or node.get("y") != layout[node["id"]][1]
    ]
    displacement = max(
        (
            max(
                abs((_number(node.get("x")) or 0.0) - layout[node["id"]][0]),
                abs((_number(node.get("y")) or 0.0) - layout[node["id"]][1]),
            )
            for node in placed
        ),
        default=0.0,
    )

    if args.report and not args.quiet:
        gutter_before = (
            "inf" if before["min_gutter"] == float("inf")
            else f"{before['min_gutter']:.0f}"
        )
        gutter_after = (
            "inf" if report["min_gutter"] == float("inf")
            else f"{report['min_gutter']:.0f}"
        )
        print(
            f"  {_rel(path)}\n"
            f"      nodes {report['nodes']:3d}  slots {report['slots']:2d} "
            f"{report['columns']}\n"
            f"      before: {before['overlaps']} overlaps, min gutter {gutter_before}\n"
            f"      after:  {report['overlaps']} overlaps, min gutter {gutter_after}, "
            f"extent {report['extent'][0]}x{report['extent'][1]}\n"
            f"      moved {len(moved)}/{report['nodes']} nodes, "
            f"max displacement {displacement:.0f}px"
        )

    if not moved:
        return 0

    if not args.write:
        if not args.quiet:
            print(
                f"  DRIFT {_rel(path)}: {len(moved)} of {report['nodes']} nodes "
                f"would move (max {displacement:.0f}px). Run with --write to apply.",
                file=sys.stderr,
            )
        return 1

    settings = _dump_settings(raw, doc)
    if settings is None:
        print(
            f"Refusing to rewrite {_rel(path)}: it does not round-trip through "
            f"json.dumps(indent=2), so writing it would reformat the whole file.",
            file=sys.stderr,
        )
        return 2
    ensure_ascii, trailing_newline = settings

    for node in placed:
        node["x"], node["y"] = layout[node["id"]]

    _write(path, doc, ensure_ascii, trailing_newline)

    # Post-write self-check: re-read what actually landed on disk.
    written = json.loads(path.read_text(encoding="utf-8"))
    check = measure(written["dataflow"], templates)
    if check["overlaps"] or check["min_gutter"] < MIN_GUTTER:
        print(
            f"  FAIL {_rel(path)}: wrote a layout that is not clean "
            f"({check['overlaps']} overlaps, min gutter {check['min_gutter']:.0f})",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print(f"  wrote {_rel(path)} ({len(moved)} nodes moved)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lay out example dataflows so no two nodes overlap.",
    )
    parser.add_argument(
        "paths", nargs="*", metavar="PATH",
        help="A .json file, or a directory to search recursively.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="The curated gallery examples, docs/examples/[0-9][0-9]-*.json.",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Apply the layout. Without it, check only.",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Print a per-file geometry table.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Print nothing; communicate through the exit code alone.",
    )
    # The committed layout uses the defaults. Overriding a gutter produces a
    # layout that still passes the self-check but that --check will not
    # reproduce, so these are for experimenting, not for committing.
    parser.add_argument(
        "--gutter-x", type=int, default=H_GUTTER, metavar="N",
        help=f"Gap between columns (default {H_GUTTER}).",
    )
    parser.add_argument(
        "--gutter-y", type=int, default=V_GUTTER, metavar="N",
        help=f"Gap between stacked nodes (default {V_GUTTER}).",
    )
    parser.add_argument(
        "--max-rows", type=int, default=MAX_ROWS_PER_COLUMN, metavar="N",
        help=f"Wrap a rank taller than this; 0 disables (default {MAX_ROWS_PER_COLUMN}).",
    )
    args = parser.parse_args(argv)

    if args.all and args.paths:
        parser.error("pass either --all or explicit paths, not both")
    if not args.all and not args.paths:
        parser.error("pass one or more paths, or --all")

    templates = _template_index()
    if not templates:
        print(f"No package manifests found under {REPO_ROOT / 'packages'}", file=sys.stderr)
        return 2

    if args.all:
        files = _curated_examples()
    else:
        files = []
        for raw in args.paths:
            target = Path(raw)
            if not target.exists():
                print(f"No such path: {raw}", file=sys.stderr)
                return 2
            files += _files_under(target)
    if not files:
        print("No dataflow files to lay out.", file=sys.stderr)
        return 2

    status = 0
    for path in files:
        result = process(path, templates, args)
        if result == 2:
            return 2
        status = max(status, result)

    if not args.quiet and status == 0:
        verb = "written" if args.write else "already tidy"
        print(f"{len(files)} file(s) {verb}.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
