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
        contract_version="1",
        effect="read",
        description=(
            "Read the project's saved dataflow spec (agent-private sections "
            "removed). No params."
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


def execute_read_tool(
    tool_id: str, *, user_key: str, project_id: str, target: dict | None, params: dict
) -> tuple[str, str]:
    """Execute one granted read contract; returns ``(status, text)``, never
    raises (a tool failure is data the model recovers from, not a run error).

    Implementations stay domain-owned (`ADR-AG-007`): these are thin wrappers
    over ``projects.storage`` reads. Output is untrusted context data —
    bounded, and the dataflow read passes ``strip_agent_state`` so
    agent-private sections never enter model context (the rule-9 posture
    applies to tool output too).
    """
    from utk_curio.backend.app.agents import project_agents
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return "error", "no saved project spec is available"
        if tool_id == "dataflow.read":
            stripped = project_agents.strip_agent_state(spec)
            return "ok", _truncate(json.dumps(stripped, ensure_ascii=False))
        if tool_id == "node.read":
            node_id = params.get("nodeId")
            if not isinstance(node_id, str) or not node_id:
                node_id = (
                    target.get("targetId")
                    if isinstance(target, dict) and target.get("kind") == "node"
                    else None
                )
            if not node_id:
                return "error", "no nodeId given and this agent is not attached to a node"
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
            if node is None:
                return "error", f"node {node_id!r} not found in the saved spec"
            return "ok", _truncate(json.dumps(node, ensure_ascii=False))
        return "error", f"unknown read tool {tool_id!r}"
    except Exception as exc:  # tool failures are data, never run errors
        return "error", f"tool failed: {exc}"
