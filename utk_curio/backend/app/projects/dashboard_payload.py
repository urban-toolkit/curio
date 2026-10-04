"""Everything a standalone dashboard page needs, in one dict.

A dashboard served at ``/dashboard/<id>`` is meant to be a finished HTML
document: it renders its tiles without calling the backend, the sandbox, or
anything else. That is only possible if the rows the tiles draw travel with the
page, so this module assembles them.

Two separate things go into the page and they come from different places:

``spec``
    The Trill spec. It carries which nodes are pinned, each tile's geometry, and
    the grammar each tile compiles. It is read from disk, not rebuilt.

``outputs``
    A map from a saved output's filename to the wire envelope
    ``{dataType, data, schema}`` that the sandbox ``/get`` already returns for
    that filename. Deliberately the same shape rather than a new one: it is what
    Python emits (``sandbox/util/parsers.py``), what ``/get`` serves, and what
    the tile behaviours already accept, so the page reads its embedded rows
    through the same code path that reads a fetched artifact. The key is the
    manifest ``filename`` because that is the key the tiles look up.

Only the outputs a tile actually needs are embedded. A dataflow saved under
``--save-node-outputs`` has an output for every node, and a dashboard has no
business shipping rows from nodes it does not show: that is somebody's data
riding along in a page they hand out by link.

The size limit is a refusal, not a fallback. A dashboard over budget fails to
build and names the tiles responsible, because the alternative is a page that
looks standalone and silently is not, or one so large a browser cannot open it.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

# Node kinds that re-derive their own content from whatever reaches them, so a
# walk upward from a pinned tile passes through them looking for the node that
# actually produced rows. Mirrors ``isPassThroughNode`` in
# ``frontend/urban-workflows/src/utils/dashboardLayout.ts``; the parity is
# pinned by ``test_dashboard_payload.py``.
_PASS_THROUGH_KINDS = frozenset(
    {
        "vis-vega",
        "vis-simple",
        "data-pool",
    }
)

_AUTK_GRAMMAR_KIND = "autk-grammar"

#: How much embedded data a single dashboard may carry, measured as the UTF-8
#: length of the serialised envelopes. Chosen to stay well inside what a browser
#: will parse from one document without the page feeling broken; a raster layer
#: or an unaggregated geodataframe blows past it, which is the case the refusal
#: exists for.
DEFAULT_PAYLOAD_LIMIT_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class TileWeight:
    """How much one embedded output contributes to the page."""

    node_id: str
    filename: str
    data_type: Optional[str]
    bytes: int


class DashboardTooLargeError(Exception):
    """Raised when the embedded rows would exceed the page budget.

    Carries the per-output breakdown so the caller can tell the owner which
    tile to aggregate rather than just quoting a number at them.
    """

    def __init__(self, total_bytes: int, limit_bytes: int, weights: Sequence[TileWeight]):
        self.total_bytes = total_bytes
        self.limit_bytes = limit_bytes
        # Heaviest first: the first line of the message is the thing to fix.
        self.weights = sorted(weights, key=lambda w: w.bytes, reverse=True)
        super().__init__(self.describe())

    def describe(self) -> str:
        lines = [
            f"This dashboard needs {_mb(self.total_bytes)} of data embedded in the page, "
            f"over the {_mb(self.limit_bytes)} limit.",
            "",
            "Heaviest outputs:",
        ]
        for weight in self.weights[:5]:
            kind = weight.data_type or "unknown"
            lines.append(f"  {weight.node_id}  {_mb(weight.bytes)}  {kind}")
        lines.append("")
        lines.append(
            "Aggregate or filter upstream of these nodes, or unpin the tiles that use them."
        )
        return "\n".join(lines)


def _mb(num_bytes: int) -> str:
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _unversioned(node_type: object) -> str:
    """``curio.builtin/vis-vega@1`` -> ``vis-vega``.

    Node types are written three ways in a saved spec depending on how the node
    got there (palette drag, package install, a builtin), so the comparison has
    to be made on the bare kind.
    """
    text = str(node_type or "")
    if "@" in text:
        text = text.split("@", 1)[0]
    if "/" in text:
        text = text.rsplit("/", 1)[1]
    return text


def _classify_autk_spec(spec_text: object) -> str:
    """``render`` when the grammar draws something, else ``data``/``compute``.

    Matches ``classifyAutkSpec`` on the frontend: a spec counts as render
    whenever it declares a map or a plot, whatever else it also declares.
    """
    if not isinstance(spec_text, str) or not spec_text.strip():
        return "unknown"
    try:
        parsed = json.loads(spec_text)
    except (ValueError, TypeError):
        return "unknown"
    if not isinstance(parsed, dict):
        return "unknown"
    if parsed.get("map") is not None or parsed.get("plot") is not None:
        return "render"
    if parsed.get("compute") is not None:
        return "compute"
    if parsed.get("data") is not None:
        return "data"
    return "unknown"


class DashboardCannotBeStandaloneError(Exception):
    """Raised when a pinned tile would still have to reach a server to draw.

    Same channel as the size refusal, and for the same reason: a page that looks
    standalone and is not is worse than one that refuses to be built. The owner
    finds out here, where they can change the dataflow, rather than from a
    viewer who opened the link somewhere the server cannot be reached.
    """

    def __init__(self, offenders: Sequence[str]):
        self.offenders = list(offenders)
        super().__init__(self.describe())

    def describe(self) -> str:
        names = ", ".join(self.offenders)
        return (
            f"These tiles load their own data when they draw: {names}.\n\n"
            "A dashboard carries the rows saved with it, so a tile that fetches "
            "its own cannot be published. Move the data section into its own "
            "node upstream of the tile, so its output is saved and travels with "
            "the page."
        )


def _node_kind(node: dict) -> str:
    """A saved node's bare kind. ``TrillGenerator`` writes the template id as
    the node's ``type``, its code as ``content``, and ``dashboardPinned`` on the
    node itself; a saved node has no ``data`` block."""
    return _unversioned(node.get("type"))


def _is_pinned(node: dict) -> bool:
    return bool(node.get("dashboardPinned"))


def _autark_spec_has_data_sources(node: dict) -> bool:
    """True when an Autark tile would run its own data section to draw.

    A spec counts as render whenever it declares a map or a plot, whatever else
    it declares, so a render tile can still carry `data` sources. Those are
    compiled and executed when it draws, which on a published page means a call
    to a server that is not supposed to be needed.
    """
    text = node.get("content")
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(parsed, dict):
        return False
    sources = parsed.get("data")
    return isinstance(sources, list) and len(sources) > 0


def _is_pass_through(node: dict) -> bool:
    kind = _node_kind(node)
    if kind in _PASS_THROUGH_KINDS:
        return True
    if kind == _AUTK_GRAMMAR_KIND:
        return _classify_autk_spec(node.get("content")) == "render"
    return False


def dashboard_source_node_ids(spec: dict) -> Set[str]:
    """Node ids whose saved output a pinned tile needs in order to draw.

    Walks upward from every pinned node through the pass-through kinds and stops
    at the first node on each path that actually produces rows. Breadth-first
    with a visited set, so a cycle or a diamond terminates.
    """
    dataflow = (spec or {}).get("dataflow") or {}
    nodes = dataflow.get("nodes") or []
    edges = dataflow.get("edges") or []

    by_id = {node.get("id"): node for node in nodes if node.get("id")}
    pinned = [node["id"] for node in nodes if node.get("id") and _is_pinned(node)]
    sources: Set[str] = set()
    if not pinned:
        return sources

    incoming: Dict[str, List[str]] = {}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        incoming.setdefault(target, []).append(source)

    queue = deque(pinned)
    visited: Set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for source_id in incoming.get(node_id, []):
            node = by_id.get(source_id)
            if node is None:
                continue
            if _is_pass_through(node):
                queue.append(source_id)
            else:
                sources.add(source_id)
    return sources


def _refuse_tiles_that_fetch_their_own_data(spec: dict) -> None:
    """Refuse a dashboard whose pinned tiles would still call out to draw."""
    dataflow = (spec or {}).get("dataflow") or {}
    offenders: List[str] = []
    for node in dataflow.get("nodes") or []:
        if not _is_pinned(node):
            continue
        if _node_kind(node) != _AUTK_GRAMMAR_KIND:
            continue
        if _autark_spec_has_data_sources(node):
            offenders.append(str(node.get("id") or "a tile"))
    if offenders:
        raise DashboardCannotBeStandaloneError(offenders)


@dataclass
class DashboardPayload:
    """What gets inlined into the page."""

    spec: dict
    outputs: Dict[str, dict]
    meta: dict
    weights: List[TileWeight] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(weight.bytes for weight in self.weights)

    def to_dict(self) -> dict:
        return {
            "meta": self.meta,
            "spec": self.spec,
            "outputs": self.outputs,
            # The same refs the project load hands the page, narrowed to what
            # actually travelled. The page restores a node's output by node id,
            # and the map above is keyed by filename because that is how a tile
            # looks its rows up; carrying both beats making the page re-derive
            # one from the other against the spec.
            "outputRefs": [
                {
                    "node_id": weight.node_id,
                    "filename": weight.filename,
                    "data_type": weight.data_type,
                }
                for weight in self.weights
            ],
        }


def build_dashboard_payload(
    *,
    spec: dict,
    output_refs: Iterable,
    fetch_envelope: Callable[[str], dict],
    meta: Optional[dict] = None,
    limit_bytes: int = DEFAULT_PAYLOAD_LIMIT_BYTES,
) -> DashboardPayload:
    """Assemble the standalone payload for one dashboard.

    *output_refs* are the project's saved outputs, each carrying ``node_id``,
    ``filename`` and ``data_type`` (the manifest shape; either objects with
    those attributes or plain dicts).

    *fetch_envelope* is handed a filename and returns that artifact's
    ``{dataType, data, schema}`` envelope. Injected rather than called directly
    so the assembly can be tested without a sandbox, and so the caller decides
    whether it reads over HTTP or off the disk.

    An output whose envelope cannot be read is skipped rather than fatal: the
    tile it feeds shows its own empty state, which is the same thing that
    happens today when an artifact has gone. A dashboard over *limit_bytes*
    raises :class:`DashboardTooLargeError`.
    """
    _refuse_tiles_that_fetch_their_own_data(spec)

    needed = dashboard_source_node_ids(spec)

    outputs: Dict[str, dict] = {}
    weights: List[TileWeight] = []
    for ref in output_refs:
        node_id = _ref_field(ref, "node_id")
        filename = _ref_field(ref, "filename")
        data_type = _ref_field(ref, "data_type")
        if not node_id or not filename:
            continue
        if node_id not in needed:
            # Saved for some other reason (the per-node toggle, or
            # --save-node-outputs). No tile reads it, so it does not travel.
            continue
        if filename in outputs:
            continue
        try:
            envelope = fetch_envelope(filename)
        except Exception:
            continue
        if envelope is None:
            continue
        outputs[filename] = envelope
        weights.append(
            TileWeight(
                node_id=node_id,
                filename=filename,
                data_type=data_type,
                bytes=len(json.dumps(envelope, default=str).encode("utf-8")),
            )
        )

    total = sum(weight.bytes for weight in weights)
    if total > limit_bytes:
        raise DashboardTooLargeError(total, limit_bytes, weights)

    return DashboardPayload(
        spec=spec,
        outputs=outputs,
        meta=dict(meta or {}),
        weights=weights,
    )


def _ref_field(ref: object, name: str):
    if isinstance(ref, dict):
        return ref.get(name)
    return getattr(ref, name, None)
