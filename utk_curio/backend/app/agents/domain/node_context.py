"""The one node-context composer (memo dev/67-6).

Every content generation for a node — Solve children, the Node Builder's
Node Content Builder delegation, and the 67-9 sequence — receives the SAME
structured neighborhood: the node's intent and current content, its nearest
upstream/downstream nodes (goals, content lengths, runtime status from the
dev/67-2 journal), the graph summary, and the dataset references. One
composer, so no per-caller context drift; bounded, so it can never crowd a
child prompt.

Honesty rules: a neighbor that never executed says ``never-executed`` —
nothing here fabricates schemas or results; ``outputSchema`` joins when the
runtime journal starts capturing column metadata (recorded 67-2 follow-up).

dev/135: the status WORD was all this composer forwarded, so a child asked to
fix a node that had failed was told ``error`` and nothing else — not the
message, not the output type, not when it ran or where. The journal has held
all of that since dev/67-2 (and, since dev/135, for browser-rendered kinds
too), so every node row now carries a bounded ``runtime`` block beside the
legacy word: what happened, what it said, what it produced, and which origin
produced the record.
"""

from __future__ import annotations

from utk_curio.backend.app.execution import runtime_journal

_MAX_NEIGHBORS = 8
_GOAL_MAX_CHARS = 200
_INTENT_MAX_CHARS = 300
_CONTENT_MAX_CHARS = 6000
_MAX_DATASETS = 12
_CONTENT_TRUNCATION_MARKER = "\n…[truncated: content exceeds the context bound]"
#: dev/135: the same bound dev/111's client-side summary uses, so the runtime
#: and the browser cannot describe one node's failure at different sizes.
_RUNTIME_MESSAGE_CHARS = 240
#: The keys a node row's ``runtime`` block can carry, in its order: what one
#: journal record says, then ``render``, the render's own block beside a run's.
#: The Node Content Builder's instruction lists them from here.
RUNTIME_BLOCK_KEYS = ("status", "message", "outputType", "origin", "kind", "ranAt", "durationMs", "render")


def _widget_context(node: dict, nodes) -> dict:
    """#662: the node's widgets, which its code places as ``[!! name !!]``
    references, and the dataflow's shared tags (one per Parameter node), which
    any node's code places as ``[!! @name !!]``. Each key only when there are
    some, so a node without them is described as before."""
    from utk_curio.backend.app.execution.code_references import effective_value, normalize_widgets
    from utk_curio.backend.app.execution.workflow_spec import PARAMETER_TYPE

    def rows(widgets) -> list[dict]:
        return [
            {"name": w["name"], "type": w["type"], **({"label": w["label"]} if w.get("label") else {}),
             "value": effective_value(w), **({"options": w["options"]} if w.get("options") else {})}
            for w in widgets
        ]

    out: dict = {}
    own = normalize_widgets((node.get("metadata") or {}).get("widgets"))
    if own and str(node.get("type") or "").split("@", 1)[0] != PARAMETER_TYPE:
        out["widgets"] = rows(own)
    shared = [
        w
        for n in nodes
        if isinstance(n, dict) and str(n.get("type") or "").split("@", 1)[0] == PARAMETER_TYPE
        for w in normalize_widgets((n.get("metadata") or {}).get("widgets"))
    ]
    if shared:
        out["sharedTags"] = rows(shared)
    return out


def _neighbors(adjacency: dict[str, list[str]], start: str) -> list[str]:
    """Nearest-first BFS from *start*, capped at ``_MAX_NEIGHBORS``."""
    out: list[str] = []
    seen = {start}
    frontier = [start]
    while frontier and len(out) < _MAX_NEIGHBORS:
        next_frontier: list[str] = []
        for node_id in frontier:
            for neighbor in adjacency.get(node_id, []):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                out.append(neighbor)
                next_frontier.append(neighbor)
                if len(out) >= _MAX_NEIGHBORS:
                    return out
        frontier = next_frontier
    return out


def compose_node_context(
    user_key: str, project_id: str, spec: dict | None, node_id: str
) -> dict | None:
    """The structured context for generating/modifying one node's content,
    or ``None`` when the node is not in the spec (the caller reports that
    honestly rather than composing against a ghost)."""
    dataflow = (spec or {}).get("dataflow") or {}
    nodes = {
        n.get("id"): n for n in dataflow.get("nodes") or [] if isinstance(n, dict)
    }
    node = nodes.get(node_id)
    if node is None:
        return None
    edges = [e for e in dataflow.get("edges") or [] if isinstance(e, dict)]
    forward: dict[str, list[str]] = {}
    reverse: dict[str, list[str]] = {}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source in nodes and target in nodes:
            forward.setdefault(source, []).append(target)
            reverse.setdefault(target, []).append(source)
    runtime = runtime_journal.status_map(user_key, project_id)

    def _status(nid: str) -> str:
        return (runtime.get(nid) or {}).get("status") or "never-executed"

    def _describe(record: dict | None) -> dict:
        """One journal record as a bounded block, or ``{}``."""
        record = record if isinstance(record, dict) else {}
        if not record:
            return {}
        status = str(record.get("status") or "")
        message = str(
            (record.get("stderrTail") if status == "error" else record.get("stdoutTail"))
            or ""
        ).strip()
        output = record.get("output") if isinstance(record.get("output"), dict) else {}
        values = {
            "status": status or None,
            "message": message[-_RUNTIME_MESSAGE_CHARS:] or None,
            "outputType": str(output["dataType"])[:60] if output.get("dataType") else None,
            "origin": str(record["origin"])[:20] if record.get("origin") else None,
            # dev/136: `empty-render:<cause>` — what KIND of outcome this was.
            "kind": str(record["kind"])[:40] if record.get("kind") else None,
            "ranAt": (str(record.get("startedAt") or record.get("updatedAt"))[:40]
                      if record.get("startedAt") or record.get("updatedAt") else None),
            "durationMs": (int(record["durationMs"])
                           if isinstance(record.get("durationMs"), (int, float)) else None),
        }
        return {key: values[key] for key in RUNTIME_BLOCK_KEYS if values.get(key) is not None}

    def _runtime_block(nid: str) -> dict:
        """What this node's last run and last render DID (dev/135, dev/137).

        dev/137: two origins describe two different things about one node — what
        its CODE did (the artifact, the dataType, the traceback) and what its
        RENDER drew — and neither may stand in for the other. The block leads
        with the run when there is one (a code node), falls back to the render
        (a grammar node has only that), and carries the render beside it when
        both exist, because a node whose code passed can still have drawn
        nothing.
        """
        status = _status(nid)
        if status == "never-executed":
            return {"status": status}
        run = runtime_journal.read_record(user_key, project_id, nid)
        render = runtime_journal.read_render_record(user_key, project_id, nid)
        block = _describe(run) or _describe(render) or {"status": status}
        if run and render:
            described = _describe(render)
            if described:
                block["render"] = described
        return block

    def _row(nid: str) -> dict:
        neighbor = nodes[nid]
        content_text = str(neighbor.get("content") or "")
        return {
            "id": nid,
            "type": neighbor.get("type"),
            "goal": str(neighbor.get("goal") or "")[:_GOAL_MAX_CHARS],
            "hasContent": bool(content_text.strip()),
            "contentChars": len(content_text),
            "runtimeStatus": _status(nid),
            # dev/135: an upstream that FAILED is the commonest reason a node
            # cannot be fixed in isolation — its reason travels with it.
            "runtime": _runtime_block(nid),
        }

    current = str(node.get("content") or "")
    if len(current) > _CONTENT_MAX_CHARS:
        current = current[:_CONTENT_MAX_CHARS] + _CONTENT_TRUNCATION_MARKER
    datasets = []
    for entry in (dataflow.get("datasets") or [])[:_MAX_DATASETS]:
        if isinstance(entry, dict):
            # dev/114: the installed-dataset ref written by the datasets domain
            # is the THIN shape ``{datasetId, dirName, origin, …}`` (no name,
            # no path); the legacy fat ref carries ``id``/``name``/``title``.
            # Reading only the fat keys sent every child ``{"id": null,
            # "name": ""}`` — an absence that was a bug, not honesty.
            row = {
                "id": entry.get("id") or entry.get("datasetId"),
                "name": (
                    entry.get("name") or entry.get("title") or entry.get("dirName") or ""
                )[:_GOAL_MAX_CHARS],
            }
            if entry.get("origin"):
                row["origin"] = str(entry.get("origin"))[:40]
            datasets.append(row)
    return {
        "nodeId": node_id,
        "nodeType": node.get("type"),
        "intent": str(node.get("goal") or "")[:_INTENT_MAX_CHARS],
        "currentContent": current,
        "runtimeStatus": _status(node_id),
        # dev/135: the owner's `a29d1ad8` — a Vega node visibly red, and the
        # agent attached to it told nothing but "never-executed".
        "runtime": _runtime_block(node_id),
        "upstream": [_row(nid) for nid in _neighbors(reverse, node_id)],
        "downstream": [_row(nid) for nid in _neighbors(forward, node_id)],
        "graphSummary": {
            "name": dataflow.get("name"),
            "goal": dataflow.get("task"),
            "nodes": len(nodes),
            "edges": len(edges),
        },
        "datasetRefs": datasets,
        **_widget_context(node, nodes.values()),
    }
