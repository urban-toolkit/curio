"""Server-authoritative tool contracts + grant resolution + read execution
(memos ``dev/39``/``dev/41``).

Manifest ``tools`` entries are untrusted *requirements*, never grants
(`DEC-017`, `REQ-PERM-001`); this module owns what actually exists and what a
run may be granted. Per `ADR-AG-007` a contract only *names* a domain-owned
operation — the read executors below are thin wrappers over the owning
domain's functions (``projects.storage``, ``project_agents``), and the one
mutate contract is executed **only** by the review-before-apply apply endpoint
(memo dev/41), never here and never by the model loop.

Grant policy: ``granted = requested ∩ registry ∩ policy``. ``read`` contracts
execute inside the bounded run loop; ``mutate`` contracts are grantable **for
proposal purposes only** — requesting one mints a review proposal, and
execution authority lives solely in the authenticated apply endpoint
(`DEC-006`/`REQ-REVIEW-001` — the gate is structural, not a flag). Granted ids
are pinned on the execution record (``pins.tools``, `REQ-CAP-002`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from utk_curio.backend.app.agents.manifest import ToolRequirement

_EFFECTS = ("read", "mutate")

# Tool results are untrusted context data: bounded, truncated with a marker.
TOOL_RESULT_MAX_CHARS = 32_000
_TRUNCATION_MARKER = "\n…[truncated: result exceeded the tool output bound]"


@dataclass(frozen=True)
class ToolContract:
    """A typed, versioned reference to one domain-owned operation."""

    id: str
    contract_version: str
    effect: str  # "read" | "mutate"
    description: str

    def __post_init__(self):
        if self.effect not in _EFFECTS:
            raise ValueError(f"tool effect must be one of {_EFFECTS}, got {self.effect!r}")


# The server-owned allowlist (DEC-017). Each contract has a named consumer in
# the built-in roster (dev/41 §4.3, dev/48) — nothing speculative.
REGISTRY: dict[str, ToolContract] = {
    "dataflow.read": ToolContract(
        id="dataflow.read",
        contract_version="2",
        effect="read",
        description=(
            "Read the project's saved dataflow, structure-first: every node "
            "(id, type, goal, content length) and ALL edges, plus each node's "
            "last runtime status. Node content is elided — use node.read for "
            'one node\'s content, or params {"include": ["content"]} for the '
            "full spec (large)."
        ),
    ),
    # dev/67-4 (DEC-053) — consumer: agent.node-researcher. Policy-gated
    # egress (SSRF guards, byte caps, per-run budget) — verification of
    # external dataset APIs, never crawling.
    "web.fetch": ToolContract(
        id="web.fetch",
        contract_version="1",
        effect="read",
        description=(
            'Fetch one public https URL and return its status, content type, '
            'and a bounded body preview. Params: {"url": "https://..."}. '
            "Use it to VERIFY endpoints, dataset ids, and API shapes — never "
            "to crawl. Private/internal addresses are refused; at most 4 "
            "web calls per run."
        ),
    ),
    "web.search": ToolContract(
        id="web.search",
        contract_version="1",
        effect="read",
        description=(
            'Search the web for factual verification. Params: {"q": "<query>"}. '
            "Returns bounded {title, url, snippet} rows when this deployment "
            "has a search provider configured — otherwise an honest "
            '"not configured" error. At most 4 web calls per run.'
        ),
    ),
    # dev/67-2 (DEC-052) — consumers: the builder/debug/explainer agents. The
    # runtime journal's read surface: why a node's last run failed.
    "node.runtime.read": ToolContract(
        id="node.runtime.read",
        contract_version="1",
        effect="read",
        description=(
            "Read one node's LAST execution outcome: status, error traceback "
            "tail, stdout tail, output metadata, and whether the node's "
            'content changed since that run. Params: {"nodeId": "..."} — '
            "defaults to the node this agent is attached to. A node that "
            'never ran reports status "never-executed".'
        ),
    ),
    "node.read": ToolContract(
        id="node.read",
        contract_version="1",
        effect="read",
        description=(
            'Read one node from the saved spec. Params: {"nodeId": "..."} — '
            "defaults to the node this agent is attached to."
        ),
    ),
    "node.content.write": ToolContract(
        id="node.content.write",
        contract_version="1",
        effect="mutate",
        description=(
            'Propose replacing one node\'s content. Params: {"nodeId": "...", '
            '"content": "..."}. The user reviews the proposal before anything '
            "is applied; nothing changes without their explicit approval."
        ),
    ),
    # dev/50 — consumer: agent.dataset-finder. Grounds the "From your Data
    # Catalog" lane in the real catalog (the datasets domain owns the data;
    # this module owns none of its own).
    "catalog.search": ToolContract(
        id="catalog.search",
        contract_version="1",
        effect="read",
        description=(
            "Search the project's Data Catalog. Params (all optional): "
            '{"q": "<text>", "format": "<fmt>", "origin": "<origin>"}. '
            "Returns dataset rows with id, name, format, origin, installed "
            "state, and description — catalog-lane candidates must come from "
            "these results only."
        ),
    ),
    # dev/84 — consumer: agent.package-recommendation. Grounds package
    # recommendations in the real Nodes Catalog + this project's lockfile
    # (the packages domain owns the data; this module owns none of its own).
    "packages.catalog": ToolContract(
        id="packages.catalog",
        contract_version="1",
        effect="read",
        description=(
            "List the Nodes Catalog's node packages with this project's "
            'install state. Params (optional): {"q": "<text>"} substring '
            "filter. Returns rows with dirName, packageId, name, description, "
            "installed, and builtin — recommendation candidates must come from "
            "these results only; builtin packages are always present and are "
            "never proposed."
        ),
    ),
    # dev/84 — consumer: agent.package-recommendation. The identify half:
    # deps/permissions/conflicts come from the real resolver, never invented.
    "packages.resolve": ToolContract(
        id="packages.resolve",
        contract_version="1",
        effect="read",
        description=(
            "Resolve one or more catalog packages against this account's "
            'installed set. Params: {"dirNames": ["<dirName from '
            'packages.catalog>", ...]}. Returns each package\'s requested '
            "permissions and python/js dependencies, plus any version "
            "conflicts — use it to enrich an identify/recommend answer before "
            "proposing an install."
        ),
    ),
    # dev/52 — consumer: agent.dataflow-builder. The DR-1 graph-level
    # mutation: the model emits a `dataflowPlan` tail block (not a
    # toolRequest) and the runtime mints the reviewed plan proposal from it;
    # the authenticated apply endpoint inserts the whole ADDITIVE graph.
    "dataflow.plan.write": ToolContract(
        id="dataflow.plan.write",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose an ADDITIVE plan of connected new nodes, by ending a "
            "reply with a dataflowPlan block (not a toolRequest): "
            '{"dataflowPlan": {"goal": "...", "nodes": [{"ref": "n1", '
            '"nodeType": "<packageId>/<templateId>", "title": "...", '
            '"intent": "..."}], "edges": [{"from": "n1", "to": "n2"}]}}. '
            "nodeType must come from the Available node templates list. The "
            "user reviews the whole plan; nothing is added without approval, "
            "and existing nodes are never touched."
        ),
    ),
    # dev/50 — consumer: agent.dataset-finder. The catalog lane's reviewed
    # handoff: applying installs ONE dataset through the existing
    # dataset-only flow; never an agent.
    "dataset.install": ToolContract(
        id="dataset.install",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose installing ONE dataset from the Data Catalog into this "
            'project. Params: {"datasetId": "<id from catalog.search results>"}. '
            "The user reviews the proposal; nothing is installed without "
            "their approval, and this never installs an agent."
        ),
    ),
    # dev/84 — consumer: agent.package-recommendation. The reviewed install
    # lane: applying routes through the existing package install flow
    # (permissions + dependencies + conflicts); never a silent install,
    # never a built-in.
    "package.install": ToolContract(
        id="package.install",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose installing ONE node package from the Nodes Catalog into "
            'this project. Params: {"dirName": "<dirName from '
            'packages.catalog results>", "reason": "why this work needs it"}. '
            "The user reviews the proposal through the package install dialog "
            "(permissions, dependencies, conflicts); nothing is installed "
            "without their approval. Built-in packages are always present and "
            "must never be proposed."
        ),
    ),
    # dev/48 — consumer: agent.node-builder. Reuse-first: nodeType must come
    # from the run's "Available node templates" list (composed at run time
    # from the packages registry — this module owns no template knowledge).
    "node.create": ToolContract(
        id="node.create",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose adding ONE new node to the canvas. Params: "
            '{"nodeType": "<packageId>/<templateId>", "content": "...", '
            '"goal": "..."} (goal optional). nodeType must be an id from the '
            '"Available node templates" list — never invented. The user '
            "reviews the proposal; nothing is added without their approval."
        ),
    ),
    # dev/89 — consumer: agent.package-builder. The ONE package-authoring
    # mutate contract: requesting it runs the isolated build service
    # (validate → resolve → compile → preview → package, all staged and
    # content-addressed) and mints the reviewed package-draft proposal;
    # Apply promotes the exact reviewed artifact digest through the
    # promotion coordinator — never a silent install.
    "package.draft.apply": ToolContract(
        id="package.draft.apply",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose ONE built node package as a reviewed draft. Params: the "
            'typed build request — {"mode": "create"|"extend", "target": '
            '"<packageId>@<major>", "baseDigest": "<64-hex, extend only>", '
            '"manifest": {...}, "files": {"<path>": {"text"|"base64": "..."}}, '
            '"behaviorEntries": ["sources/<entry>.tsx", ...], "dependencies": '
            '{"python"|"js"|"packages": {name: constraint}}, '
            '"previewTemplates": [...], "nodes": [{"templateId": "...", '
            '"title": "...", "content": "...", "appearance": '
            '{"backgroundColor": "<palette name or #RRGGBB>"}}]}. The build '
            "service compiles/validates/previews the draft; the user reviews "
            "the diff, dependencies, and preview before anything installs. "
            "Never claim the package exists before the user applies it."
        ),
    ),
    # dev/48 §3.2b — consumer: agent.node-builder. The justified creation
    # fallback: ONLY when no available template fits; the apply endpoint
    # executes it solely through the existing package factory.
    "node.template.create": ToolContract(
        id="node.template.create",
        contract_version="1",
        effect="mutate",
        description=(
            "Propose a NEW custom node type — only after the Available node "
            "templates list has been considered and none can adequately hold "
            'the task. Params: {"justification": "...", "template": {"label": '
            '"...", "description": "...", "engine": "python"|"javascript", '
            '"content": "..."}}. justification must name the closest existing '
            "templates and why each is inadequate — the user judges it during "
            "review. Applying registers the node type in this project AND "
            "adds its first node; nothing happens without the user's approval."
        ),
    ),
}


def resolve_grants(requested: Iterable[ToolRequirement]) -> list[str]:
    """The tool ids this run is granted: requested ∩ registry ∩ policy.

    Both effects are grantable (dev/41): ``read`` executes inside the bounded
    loop; ``mutate`` may only be *proposed* — execution authority is the apply
    endpoint alone. Anything unregistered resolves to "not granted" silently
    (required-ness is :func:`missing_required`'s concern)."""
    granted: list[str] = []
    for req in requested:
        contract = REGISTRY.get(req.id)
        if contract is not None and contract.id not in granted:
            granted.append(contract.id)
    return granted


def missing_required(requested: Iterable[ToolRequirement]) -> list[str]:
    """Required tool ids that resolve no grant — each one refuses the run
    (fail-closed, same posture as a missing instruction prompt)."""
    requested = list(requested)
    granted = set(resolve_grants(requested))
    return [r.id for r in requested if r.required and r.id not in granted]


def grant_descriptions(granted: Iterable[str]) -> list[tuple[str, str]]:
    """(id, description) pairs for the grant-aware tail instruction."""
    out: list[tuple[str, str]] = []
    for tool_id in granted:
        contract = REGISTRY.get(tool_id)
        if contract is not None:
            out.append((contract.id, contract.description))
    return out


def _truncate(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + _TRUNCATION_MARKER


# catalog.search bounds (dev/50): plenty for ranking, small enough to never
# crowd the context; description is display metadata, not a document.
_CATALOG_SEARCH_MAX_ROWS = 40
_CATALOG_DESC_MAX_CHARS = 200
_CATALOG_PARAM_MAX_CHARS = 200


def _catalog_search_rows(user_key: str, project_id: str, params: dict) -> list[dict]:
    """Bounded catalog rows for the dev/50 read tool.

    Thin wrapper over the datasets domain (`ADR-AG-007`): the acting user
    rides the request context (the datasets service is user-object keyed,
    unlike the key-based agents/packages stores), and the listing is the
    same `list_catalog` the Data Catalog drawer browses — one truth.
    """
    from flask import g

    from utk_curio.backend.app.datasets.application.catalog_service import (
        DatasetCatalogService,
    )

    user = getattr(g, "user", None)

    def _param(name: str) -> str | None:
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_CATALOG_PARAM_MAX_CHARS]
        return None

    listing = DatasetCatalogService(user).list_catalog(
        dataflow_id=project_id,
        q=_param("q"),
        fmt=_param("format"),
        origin=_param("origin"),
    )
    rows = []
    for item in (listing.get("items") or [])[:_CATALOG_SEARCH_MAX_ROWS]:
        rows.append(
            {
                "id": item.get("id"),
                "name": item.get("title"),
                "format": item.get("format"),
                "origin": item.get("origin"),
                "installed": bool(item.get("installed")),
                "description": (item.get("description") or "")[:_CATALOG_DESC_MAX_CHARS],
            }
        )
    return rows


# packages.catalog bounds (dev/84): mirrors the catalog.search posture —
# plenty for ranking, small enough to never crowd the context.
_PACKAGES_CATALOG_MAX_ROWS = 40
_PACKAGES_DESC_MAX_CHARS = 200
_PACKAGES_RESOLVE_MAX_DIRNAMES = 8


def _packages_catalog_rows(user_key: str, project_id: str, params: dict) -> list[dict]:
    """Bounded package rows for the dev/84 read tool — a thin wrapper over the
    packages domain's agent overview (`ADR-AG-007`: one truth, owned there)."""
    from utk_curio.backend.app.packages import services as packages_services

    rows = packages_services.agent_catalog_overview(user_key, project_id)
    query = params.get("q")
    if isinstance(query, str) and query.strip():
        needle = query.strip().lower()[:_CATALOG_PARAM_MAX_CHARS]
        rows = [
            r for r in rows
            if needle in f"{r['dirName']} {r['packageId']} {r['name']} {r['description']}".lower()
        ]
    out = []
    for r in rows[:_PACKAGES_CATALOG_MAX_ROWS]:
        out.append({**r, "description": r["description"][:_PACKAGES_DESC_MAX_CHARS]})
    return out


def _execute_packages_resolve(user_key: str, params: dict) -> tuple[str, str]:
    """The dev/84 identify surface: real resolver output, never invented."""
    from utk_curio.backend.app.packages import services as packages_services

    dir_names = params.get("dirNames")
    if not isinstance(dir_names, list) or not dir_names or not all(
        isinstance(d, str) and d.strip() for d in dir_names
    ):
        return "error", 'params.dirNames must be a non-empty list of package dirName strings'
    cleaned = [d.strip() for d in dir_names[:_PACKAGES_RESOLVE_MAX_DIRNAMES]]
    try:
        report = packages_services.agent_resolve_report(user_key, cleaned)
    except packages_services.PackageServiceError as exc:
        return "error", str(exc)
    return "ok", _truncate(json.dumps(report, ensure_ascii=False))


def _node_row(node: dict, goal_cap: int) -> dict:
    content = str(node.get("content") or "")
    return {
        "id": node.get("id"),
        "type": node.get("type"),
        "goal": str(node.get("goal") or "")[:goal_cap],
        "hasContent": bool(content.strip()),
        "contentChars": len(content),
    }


def _dataflow_projection(stripped: dict, user_key: str, project_id: str) -> dict:
    """Structure-first dataflow.read payload (dev/67-2).

    Edges are NEVER the truncation casualty: node content is elided to lengths
    (node.read serves any one node's content), goals are bounded, and the
    runtime journal's status map rides along so one call answers "what exists,
    how it is wired, what ran, what failed". If the projection still exceeds
    the tool budget, node GOALS shrink next — never the edge list.
    """
    from utk_curio.backend.app.execution import runtime_journal

    dataflow = stripped.get("dataflow") or {}
    nodes_raw = [n for n in dataflow.get("nodes") or [] if isinstance(n, dict)]
    edges = []
    for edge in dataflow.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        row = {"id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target")}
        for key in ("sourceHandle", "targetHandle"):
            if edge.get(key) is not None:
                row[key] = edge.get(key)
        edges.append(row)
    projection = {
        "name": dataflow.get("name"),
        "goal": dataflow.get("task"),
        "nodes": [_node_row(n, goal_cap=200) for n in nodes_raw],
        "edges": edges,
        "datasets": dataflow.get("datasets") or [],
        "runtime": runtime_journal.status_map(user_key, project_id),
    }
    if len(json.dumps(projection, ensure_ascii=False)) > TOOL_RESULT_MAX_CHARS:
        projection["nodes"] = [_node_row(n, goal_cap=40) for n in nodes_raw]
        projection["elided"] = "node goals shortened to fit the tool output bound"
    return projection


def _resolve_node_id(target: dict | None, params: dict) -> str | None:
    node_id = params.get("nodeId")
    if isinstance(node_id, str) and node_id:
        return node_id
    if isinstance(target, dict) and target.get("kind") == "node":
        return target.get("targetId")
    return None


def execute_read_tool(
    tool_id: str, *, user_key: str, project_id: str, target: dict | None, params: dict
) -> tuple[str, str]:
    """Execute one granted read contract; returns ``(status, text)``, never
    raises (a tool failure is data the model recovers from, not a run error).

    Implementations stay domain-owned (`ADR-AG-007`): these are thin wrappers
    over ``projects.storage`` reads (+ the dev/67-2 runtime journal). Output
    is untrusted context data — bounded, and the dataflow read passes
    ``strip_agent_state`` so agent-private sections never enter model context
    (the rule-9 posture applies to tool output too).
    """
    from utk_curio.backend.app.agents import project_agents
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        # dev/67-4: the web tools need no project spec — handled first.
        if tool_id == "web.fetch":
            return _execute_web_fetch(params)
        if tool_id == "web.search":
            return _execute_web_search(params)
        # dev/84: the package tools read through the packages domain (which
        # does its own project/lockfile reads) — handled before the spec read.
        if tool_id == "packages.catalog":
            rows = _packages_catalog_rows(user_key, project_id, params)
            return "ok", _truncate(json.dumps({"packages": rows}, ensure_ascii=False))
        if tool_id == "packages.resolve":
            return _execute_packages_resolve(user_key, params)
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return "error", "no saved project spec is available"
        if tool_id == "dataflow.read":
            stripped = project_agents.strip_agent_state(spec)
            include = params.get("include")
            if isinstance(include, list) and "content" in include:
                # The pre-dev/67-2 full dump, on request (large; may truncate).
                return "ok", _truncate(json.dumps(stripped, ensure_ascii=False))
            projection = _dataflow_projection(stripped, user_key, project_id)
            return "ok", _truncate(json.dumps(projection, ensure_ascii=False))
        if tool_id == "node.read":
            node_id = _resolve_node_id(target, params)
            if not node_id:
                return "error", "no nodeId given and this agent is not attached to a node"
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
            if node is None:
                return "error", f"node {node_id!r} not found in the saved spec"
            return "ok", _truncate(json.dumps(node, ensure_ascii=False))
        if tool_id == "node.runtime.read":
            from utk_curio.backend.app.execution import runtime_journal

            node_id = _resolve_node_id(target, params)
            if not node_id:
                return "error", "no nodeId given and this agent is not attached to a node"
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
            if node is None:
                return "error", f"node {node_id!r} not found in the saved spec"
            record = runtime_journal.read_record(user_key, project_id, node_id)
            if record is None:
                return "ok", json.dumps(
                    {"nodeId": node_id, "status": "never-executed"}, ensure_ascii=False
                )
            record = dict(record)
            executed_sha = record.get("executedCodeSha256")
            current_sha = runtime_journal.normalized_code_sha256(str(node.get("content") or ""))
            # Best-effort staleness signal: the run predates the current content.
            record["contentChangedSinceRun"] = bool(executed_sha) and executed_sha != current_sha
            return "ok", _truncate(json.dumps(record, ensure_ascii=False))
        if tool_id == "catalog.search":
            rows = _catalog_search_rows(user_key, project_id, params)
            return "ok", _truncate(json.dumps({"datasets": rows}, ensure_ascii=False))
        return "error", f"unknown read tool {tool_id!r}"
    except Exception as exc:  # tool failures are data, never run errors
        return "error", f"tool failed: {exc}"


# web.fetch preview bound: enough to judge an API's shape, small enough to
# never crowd the context (the tool-result cap still applies on top).
_WEB_BODY_PREVIEW_MAX_CHARS = 4000
_WEB_SEARCH_MAX_ROWS = 8


def _execute_web_fetch(params: dict) -> tuple[str, str]:
    """dev/67-4 (DEC-053): one policy-gated fetch, framed as bounded data."""
    from utk_curio.backend.app.agents import egress

    url = params.get("url")
    if not isinstance(url, str) or not url.strip():
        return "error", "params.url must be a non-empty URL string"
    try:
        result = egress.fetch(url.strip())
    except egress.EgressRefused as exc:
        return "error", f"refused by the egress policy: {exc}"
    except Exception as exc:
        return "error", f"the endpoint is unreachable: {exc}"
    return "ok", _truncate(json.dumps({
        "url": result.url,
        "finalUrl": result.final_url,
        "status": result.status,
        "contentType": result.content_type[:100],
        "bodyPreview": result.body[:_WEB_BODY_PREVIEW_MAX_CHARS],
        "truncated": result.truncated or len(result.body) > _WEB_BODY_PREVIEW_MAX_CHARS,
    }, ensure_ascii=False))


def _execute_web_search(params: dict) -> tuple[str, str]:
    """dev/67-4: deployment-configured search — ``CURIO_SEARCH_URL`` is a URL
    template with ``{q}`` returning a JSON list of {title, url, snippet}-like
    rows (a SearXNG/portal endpoint, for example). Absent configuration
    errors honestly; results still flow through the egress policy."""
    import os
    from urllib.parse import quote

    from utk_curio.backend.app.agents import egress

    query = params.get("q")
    if not isinstance(query, str) or not query.strip():
        return "error", "params.q must be a non-empty query string"
    template = os.environ.get("CURIO_SEARCH_URL") or ""
    if "{q}" not in template:
        return "error", (
            "web search is not configured for this deployment "
            "(set CURIO_SEARCH_URL) — verify direct URLs with web.fetch instead"
        )
    try:
        # dev/90 A2: the provider host is OPERATOR configuration, so it is
        # exempt from the address policy (a local SearXNG works); redirects
        # off it — and every web.fetch URL — keep the full default-deny gate.
        result = egress.fetch(
            template.replace("{q}", quote(query.strip())),
            trusted_host=egress.trusted_host_of(template),
        )
        payload = json.loads(result.body)
    except egress.EgressRefused as exc:
        return "error", f"refused by the egress policy: {exc}"
    except Exception as exc:
        return "error", f"the search provider failed: {exc}"
    rows_raw = payload.get("results") if isinstance(payload, dict) else payload
    rows = []
    for row in (rows_raw or [])[:_WEB_SEARCH_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        rows.append({
            "title": str(row.get("title") or "")[:160],
            "url": str(row.get("url") or row.get("link") or "")[:300],
            "snippet": str(row.get("snippet") or row.get("content") or "")[:300],
        })
    return "ok", _truncate(json.dumps({"results": rows}, ensure_ascii=False))
