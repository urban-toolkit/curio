"""Server-authoritative tool contracts + grant resolution (memo ``dev/39``).

Manifest ``tools`` entries are untrusted *requirements*, never grants
(`DEC-017`, `REQ-PERM-001`); this module owns what actually exists and what a
run may be granted. Per `ADR-AG-007` a contract only *names* a domain-owned
operation — implementations stay in their domains; nothing here executes.

The registry deliberately **ships empty** (v1 of this tranche): no current
agent executes tools, and a tool without a consumer would be dead code with a
security surface (`RISK-SEC-001`). What must exist first — and does — is the
typed contract shape, the grammar, and the grant pipe the T2b/P5 composites
will populate.

Grant policy (v1): ``granted = requested ∩ registry ∩ policy`` where policy
admits ``read``-effect contracts only. A ``mutate`` contract can never be
granted until the review-before-apply application flow exists (`DEC-006`,
`REQ-REVIEW-001`) — fail-closed by construction. Granted ids are pinned on the
execution record (``pins.tools``, the tools half of `REQ-CAP-002`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from utk_curio.backend.app.agents.manifest import ToolRequirement

_EFFECTS = ("read", "mutate")


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


# The server-owned allowlist (DEC-017). Empty by design — see the module
# docstring; the first real contract lands with its first consumer.
REGISTRY: dict[str, ToolContract] = {}


def resolve_grants(requested: Iterable[ToolRequirement]) -> list[str]:
    """The tool ids this run is granted: requested ∩ registry ∩ policy.

    v1 policy grants ``read``-effect contracts only; anything unregistered or
    ``mutate``-effect resolves to "not granted" silently (required-ness is
    :func:`missing_required`'s concern)."""
    granted: list[str] = []
    for req in requested:
        contract = REGISTRY.get(req.id)
        if contract is not None and contract.effect == "read" and contract.id not in granted:
            granted.append(contract.id)
    return granted


def missing_required(requested: Iterable[ToolRequirement]) -> list[str]:
    """Required tool ids that resolve no grant — each one refuses the run
    (fail-closed, same posture as a missing instruction prompt)."""
    requested = list(requested)
    granted = set(resolve_grants(requested))
    return [r.id for r in requested if r.required and r.id not in granted]
