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

``rasters``
    What ``/raster`` answered for each raster an Autark map on the page asks it
    for: a Python node's raster, whose envelope holds only its file's path, by
    the output's filename and its place in a tuple (``part``). A served raster
    is its GeoTIFF in base64 with the ``X-Curio-Raster`` description; a refused
    one is the status, description and message the editor's map would get. The
    page answers ``fetchRaster`` from these as it answers ``fetchData`` from
    ``outputs``.

Only the outputs a tile actually needs are embedded. A dataflow saved under
``--save-node-outputs`` has an output for every node, and a dashboard has no
business shipping rows from nodes it does not show: that is somebody's data
riding along in a page they hand out by link.

The size limit is a refusal, not a fallback. A dashboard over budget fails to
build and names the tiles responsible, because the alternative is a page that
looks standalone and silently is not, or one so large a browser cannot open it.
So is a saved output a tile needs that cannot be read: a page built without it
would draw the tile empty, as if the dataflow had never run.
"""
from __future__ import annotations

import base64
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, Iterable, List, Optional, Sequence, Set

if TYPE_CHECKING:
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

logger = logging.getLogger(__name__)

# The behaviors (a template's ``behavior``, ``template_grammars``) of the nodes
# that re-derive their own content from whatever reaches them: a Vega-Lite
# chart, a Simple View and a Data Pool, and the built-in nodes of a type no
# template declares a behavior for. A walk upward from a pinned tile passes
# through them looking for the node that actually produced rows. The canvas's
# twin is ``isPassThroughNode`` in
# ``frontend/urban-workflows/src/utils/dashboardLayout.ts``.
_PASS_THROUGH_BEHAVIORS = frozenset({"vega", "simple-vis", "data-pool"})
_PASS_THROUGH_TYPES = frozenset({
    "curio.builtin/vis-vega", "curio.builtin/vis-simple", "curio.builtin/data-pool",
})

#: The Autark node, a pass-through only when its spec draws.
_AUTK_GRAMMAR_BEHAVIORS = frozenset({"autk-grammar"})
_AUTK_GRAMMAR_TYPES = frozenset({"curio.builtin/autk-grammar"})

#: How much embedded data a single dashboard may carry, measured as the UTF-8
#: length of the serialised envelopes. Chosen to stay well inside what a browser
#: will parse from one document without the page feeling broken; a raster layer
#: or an unaggregated geodataframe blows past it, which is the case the refusal
#: exists for.
DEFAULT_PAYLOAD_LIMIT_BYTES = 25 * 1024 * 1024

#: The most an Autark map loads from one raster (``RASTER_MAX_CELLS`` and
#: ``RASTER_MAX_SIDE`` in ``utils/raster/rasterLoad.ts``). The page's rasters
#: are asked of ``/raster`` with these, as the editor's map asks, so a larger
#: one travels as the refusal the editor gets and is never written out whole.
RASTER_MAX_CELLS = 4096 * 4096
RASTER_MAX_SIDE = 8192


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
    tile to aggregate rather than just quoting a number at them, and the
    dataflow's *name*, which the page that shows the refusal is titled with.
    """

    def __init__(
        self,
        total_bytes: int,
        limit_bytes: int,
        weights: Sequence[TileWeight],
        name: Optional[str] = None,
    ):
        self.total_bytes = total_bytes
        self.limit_bytes = limit_bytes
        # Heaviest first: the first line of the message is the thing to fix.
        self.weights = sorted(weights, key=lambda w: w.bytes, reverse=True)
        self.name = name
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


def _classify_autk_spec(spec_text: object) -> str:
    """``render`` when the grammar draws something, else ``data``/``compute``.

    Matches ``classifyAutkSpec`` on the frontend: a spec counts as render
    whenever it declares a map or a plot, whatever else it also declares. A
    chip standing on its own holds its place (``with_chip_placeholders``).
    """
    from utk_curio.backend.app.execution.code_references import with_chip_placeholders

    if not isinstance(spec_text, str) or not spec_text.strip():
        return "unknown"
    try:
        parsed = json.loads(with_chip_placeholders(spec_text))
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
    viewer who opened the link somewhere the server cannot be reached. Carries
    the dataflow's *name* for the page that shows the refusal, as the size
    refusal does.
    """

    def __init__(self, offenders: Sequence[str], name: Optional[str] = None):
        self.offenders = list(offenders)
        self.name = name
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


class DashboardOutputUnreadableError(Exception):
    """Raised when a tile needs a saved output that could not be read.

    Same channel as the other refusals: a page built without the output would
    draw its tile empty, as if the dataflow had never run (#941). Reading it
    again usually works, so the message says to try again. Carries the nodes
    whose outputs could not be read, and the dataflow's *name*, as the other
    refusals do.
    """

    def __init__(self, offenders: Sequence[str], name: Optional[str] = None):
        self.offenders = list(offenders)
        self.name = name
        super().__init__(self.describe())

    def describe(self) -> str:
        names = ", ".join(self.offenders)
        return (
            f"This dashboard could not read the saved output of these nodes: {names}.\n\n"
            "Try again in a moment. If it keeps failing, run the dataflow and save it again."
        )


def _is_autark_node(node: dict, packages: "TemplateGrammars") -> bool:
    """Whether a saved node's template declares the Autark node's behavior.
    ``TrillGenerator`` writes the template id as the node's ``type``, its code
    as ``content``, and ``dashboardPinned`` on the node itself; a saved node
    has no ``data`` block."""
    from utk_curio.backend.app.projects.template_grammars import declares_behavior

    return declares_behavior(node.get("type"), _AUTK_GRAMMAR_BEHAVIORS, _AUTK_GRAMMAR_TYPES, packages)


def is_pinned(node: dict) -> bool:
    """Whether a saved *node* is pinned to its dataflow's dashboard, so a tile
    of the page: ``dashboardPinned`` on the node itself, as ``TrillGenerator``
    writes it."""
    return bool(node.get("dashboardPinned"))


def _autark_spec_has_data_sources(node: dict) -> bool:
    """True when an Autark tile would run its own data section to draw.

    A spec counts as render whenever it declares a map or a plot, whatever else
    it declares, so a render tile can still carry `data` sources. Those are
    compiled and executed when it draws, which on a published page means a call
    to a server that is not supposed to be needed. A chip standing on its own
    holds its place (``with_chip_placeholders``), as it does where the spec is
    classified.
    """
    from utk_curio.backend.app.execution.code_references import with_chip_placeholders

    text = node.get("content")
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        parsed = json.loads(with_chip_placeholders(text))
    except (ValueError, TypeError):
        return False
    if not isinstance(parsed, dict):
        return False
    sources = parsed.get("data")
    return isinstance(sources, list) and len(sources) > 0


def tile_loads_its_own_data(node: dict, packages: "TemplateGrammars") -> bool:
    """Whether a saved *node* is a tile the dashboard refuses to publish: it
    is pinned, its template declares the Autark node's behavior, and its spec,
    the node's ``content``, has data sources of its own, which it would fetch
    when the page draws. *packages* reads what the node's template declares.
    The agents hold a spec they write for a pinned node to this check too."""
    return is_pinned(node) and _is_autark_node(node, packages) and _autark_spec_has_data_sources(node)


def passes_through(node: dict, packages: Optional["TemplateGrammars"] = None) -> bool:
    """Whether a saved *node* shows what reaches it rather than making rows:
    a node whose template declares a Vega-Lite chart's, a Simple View's or a
    Data Pool's behavior, or draws with the Vega-Lite grammar
    (``template_grammars``), or the Autark node when its spec draws, as
    ``isPassThroughNode`` reads it. *packages* reads the manifests
    (``TemplateGrammars.for_account()`` when None)."""
    from utk_curio.backend.app.projects.template_grammars import (
        TemplateGrammars,
        declares_behavior,
        draws_with_vega_lite,
    )

    packages = packages or TemplateGrammars.for_account()
    node_type = node.get("type")
    if (declares_behavior(node_type, _PASS_THROUGH_BEHAVIORS, _PASS_THROUGH_TYPES, packages)
            or draws_with_vega_lite(node_type, packages)):
        return True
    if _is_autark_node(node, packages):
        return _classify_autk_spec(node.get("content")) == "render"
    return False


def dashboard_source_node_ids(spec: dict, packages: Optional["TemplateGrammars"] = None) -> Set[str]:
    """Node ids whose saved output a pinned tile needs in order to draw.

    Walks upward from every pinned node through the nodes that pass what
    reaches them through (:func:`passes_through`) and stops at the first node
    on each path that actually produces rows. Breadth-first with a visited
    set, so a cycle or a diamond terminates. *packages* reads the manifests
    (``TemplateGrammars.for_account()`` when None).
    """
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    packages = packages or TemplateGrammars.for_account()
    dataflow = (spec or {}).get("dataflow") or {}
    nodes = dataflow.get("nodes") or []
    edges = dataflow.get("edges") or []

    by_id = {node.get("id"): node for node in nodes if node.get("id")}
    pinned = [node["id"] for node in nodes if node.get("id") and is_pinned(node)]
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
            if passes_through(node, packages):
                queue.append(source_id)
            else:
                sources.add(source_id)
    return sources


def _refuse_tiles_that_fetch_their_own_data(
    spec: dict, packages: "TemplateGrammars", name: Optional[str] = None,
) -> None:
    """Refuse a dashboard whose pinned Autark tiles would still call out to draw."""
    dataflow = (spec or {}).get("dataflow") or {}
    offenders = [
        str(node.get("id") or "a tile")
        for node in dataflow.get("nodes") or []
        if tile_loads_its_own_data(node, packages)
    ]
    if offenders:
        raise DashboardCannotBeStandaloneError(offenders, name=name)


#: The envelope kinds of a frame, which hold rows rather than other envelopes.
_FRAME_KINDS = frozenset({"dataframe", "geodataframe"})


def _is_envelope(value: object) -> bool:
    return isinstance(value, dict) and isinstance(value.get("dataType"), str) and "data" in value


def _is_raster_by_path(value: object) -> bool:
    """A Python node's raster as ``/get`` answers it: the path of its file."""
    return _is_envelope(value) and value["dataType"] == "raster" and isinstance(value["data"], str)


def _keyed_frames_as_outputs(value: object) -> Optional[dict]:
    """A dict of frames read as a tuple of them (``keyedFramesAsOutputs``)."""
    if not isinstance(value, dict) or not value or _is_envelope(value):
        return None
    items = list(value.values())
    if not all(_is_envelope(item) for item in items):
        return None
    if not any(item["dataType"] in _FRAME_KINDS for item in items):
        return None
    return {"dataType": "outputs", "data": items}


def raster_places(envelope: object, data_type: Optional[str]) -> List[Optional[int]]:
    """The rasters an Autark map asks ``/raster`` for in one saved output.

    An output saved as a raster is asked for whole (``None``), whatever its
    envelope holds, as ``readGrammarInput`` does. Otherwise its envelope is
    read by ``framesFromPayload``'s rules (``utils/grammarInput.ts``): value
    envelopes are peeled, a dict of frames reads as a tuple of them, a raster
    by path is the output itself, and one in a tuple is the part at its place.
    A raster that travels as its collection is in the envelope already.
    """
    if data_type == "raster":
        return [None]
    value = envelope
    while (
        _is_envelope(value)
        and value["dataType"] not in ("outputs", "raster")
        and value["dataType"] not in _FRAME_KINDS
    ):
        value = value["data"]
    value = _keyed_frames_as_outputs(value) or value
    if _is_raster_by_path(value):
        return [None]
    if _is_envelope(value) and value["dataType"] == "outputs" and isinstance(value["data"], list):
        return [
            index
            for index, item in enumerate(value["data"])
            if _is_raster_by_path(item) and not (isinstance(item.get("path"), str) and item["path"])
        ]
    return []


def _raster_record(filename: str, part: Optional[int], answer: dict) -> dict:
    """What the page carries for one raster: ``/raster``'s answer, by name."""
    status = int(answer.get("status") or 0)
    record = {"filename": filename, "part": part, "status": status, "meta": answer.get("meta")}
    geotiff = answer.get("geotiff")
    if status == 200 and isinstance(geotiff, (bytes, bytearray)):
        record["geotiff"] = base64.b64encode(bytes(geotiff)).decode("ascii")
    else:
        record["message"] = str(answer.get("message") or f"HTTP {status}")
    return record


def _json_bytes(value: object) -> int:
    return len(json.dumps(value, default=str).encode("utf-8"))


def _in_frame_order(envelope: dict) -> dict:
    """*envelope* with its frame's columns in the frame's own order (#1166).

    The sandbox answers through ``jsonify``, which sorts an object's keys: a
    dataframe's columns and a feature's properties arrive alphabetical, and a
    page shows a table's columns in the order its rows list them. The
    envelope's ``columns`` list keeps the frame's order, so the keys are put
    back in it; a name the list does not hold keeps its place after them.
    """
    order = envelope.get("columns") if isinstance(envelope, dict) else None
    if not isinstance(order, list):
        return envelope
    rank = {name: index for index, name in enumerate(order)}

    def ordered(record: dict) -> dict:
        return {name: record[name] for name in sorted(record, key=lambda n: rank.get(n, len(rank)))}

    data = envelope.get("data")
    if envelope.get("dataType") == "dataframe" and isinstance(data, dict):
        return {**envelope, "data": ordered(data)}
    if envelope.get("dataType") == "geodataframe" and isinstance(data, dict) and isinstance(data.get("features"), list):
        features = [
            {**feature, "properties": ordered(feature["properties"])}
            if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else feature
            for feature in data["features"]
        ]
        return {**envelope, "data": {**data, "features": features}}
    return envelope


@dataclass
class DashboardPayload:
    """What gets inlined into the page."""

    spec: dict
    outputs: Dict[str, dict]
    meta: dict
    weights: List[TileWeight] = field(default_factory=list)
    rasters: List[dict] = field(default_factory=list)

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
            "rasters": self.rasters,
        }


def build_dashboard_payload(
    *,
    spec: dict,
    output_refs: Iterable,
    fetch_envelope: Callable[[str], dict],
    fetch_raster: Optional[Callable[[str, Optional[int]], dict]] = None,
    meta: Optional[dict] = None,
    limit_bytes: int = DEFAULT_PAYLOAD_LIMIT_BYTES,
    missing_refs: Iterable = (),
    packages: Optional["TemplateGrammars"] = None,
) -> DashboardPayload:
    """Assemble the standalone payload for one dashboard.

    *packages* reads what the dataflow's node templates declare: the owner's
    store, the catalog, then the packages Curio ships
    (``TemplateGrammars.for_account()`` when None).

    *output_refs* are the project's saved outputs, each carrying ``node_id``,
    ``filename`` and ``data_type`` (the manifest shape; either objects with
    those attributes or plain dicts). *missing_refs*, in the same shape, are
    the saved outputs the manifest lists that the load found no copy of
    (``load_shared_project``'s ``missing_outputs``).

    *fetch_envelope* is handed a filename and returns that artifact's
    ``{dataType, data, schema}`` envelope. Injected rather than called directly
    so the assembly can be tested without a sandbox, and so the caller decides
    whether it reads over HTTP or off the disk.

    *fetch_raster* is handed a filename and a ``part`` (``None`` for the whole
    output) for each raster an Autark map asks ``/raster`` for in an output a
    tile reads as its input (:func:`raster_places`), and returns what
    ``/raster`` answered:
    ``{"status": 200, "meta", "geotiff": bytes}``, or ``{"status", "meta",
    "message"}`` for a refusal. Its GeoTIFF counts toward *limit_bytes* with
    the output's rows.

    A dashboard over *limit_bytes* raises :class:`DashboardTooLargeError`.
    Under it, a tile that needs a missing output, one whose envelope cannot be
    read, or one whose raster the sandbox could not be asked for, raises
    :class:`DashboardOutputUnreadableError`, which says to try again, rather
    than drawing the tile without it. Every refusal carries *meta*'s ``name``,
    and every output or raster that cannot be read is logged.
    """
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    name = (meta or {}).get("name")
    packages = packages or TemplateGrammars.for_account()
    _refuse_tiles_that_fetch_their_own_data(spec, packages, name=name)

    # The outputs the tiles read as their inputs, which a map on the page may
    # ask /raster for.
    needed = dashboard_source_node_ids(spec, packages)
    unreadable: List[str] = []

    def cannot_read(node_id: str, filename: str, reason: str) -> None:
        logger.warning(
            "Dashboard %s cannot read the saved output %s of node %s: %s",
            (meta or {}).get("projectId"), filename, node_id, reason,
        )
        if node_id not in unreadable:
            unreadable.append(node_id)

    for ref in missing_refs:
        node_id = _ref_field(ref, "node_id")
        if node_id in needed:
            cannot_read(node_id, _ref_field(ref, "filename"), "no copy of it was left to load")

    outputs: Dict[str, dict] = {}
    weights: List[TileWeight] = []
    rasters: List[dict] = []
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
        except Exception as exc:
            cannot_read(node_id, filename, f"{type(exc).__name__}: {exc}")
            continue
        if envelope is None:
            cannot_read(node_id, filename, "the sandbox answered nothing")
            continue
        envelope = _in_frame_order(envelope)
        outputs[filename] = envelope
        size = _json_bytes(envelope)
        for part in raster_places(envelope, data_type) if fetch_raster else []:
            try:
                answer = fetch_raster(filename, part)
            except Exception as exc:
                cannot_read(
                    node_id, filename,
                    f"the sandbox could not be asked for its raster (part {part}): {type(exc).__name__}: {exc}",
                )
                continue
            if not isinstance(answer, dict):
                cannot_read(node_id, filename, f"the sandbox answered nothing for its raster (part {part})")
                continue
            record = _raster_record(filename, part, answer)
            rasters.append(record)
            size += _json_bytes(record)
        weights.append(
            TileWeight(
                node_id=node_id,
                filename=filename,
                data_type=data_type,
                bytes=size,
            )
        )

    total = sum(weight.bytes for weight in weights)
    if total > limit_bytes:
        # Reading the rest could only add to it, so trying again would not help.
        raise DashboardTooLargeError(total, limit_bytes, weights, name=name)
    if unreadable:
        raise DashboardOutputUnreadableError(unreadable, name=name)

    return DashboardPayload(
        spec=spec,
        outputs=outputs,
        meta=dict(meta or {}),
        weights=weights,
        rasters=rasters,
    )


def _ref_field(ref: object, name: str):
    if isinstance(ref, dict):
        return ref.get(name)
    return getattr(ref, name, None)
