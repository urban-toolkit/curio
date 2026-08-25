"""Hookable-agent manifest reader and validator.

Implements the supported subset of the agent-manifest schema (canonical
spec: ``docs/schemas/agent-package.v1.json``). This mirrors the node-package
validator in ``utk_curio/backend/app/packages/manifest.py`` — same shape:
a ``ManifestError`` subtype, frozen dataclasses with ``from_json`` classmethods,
and hand-rolled field validation with ``{where}.field`` error context.

Key invariants enforced here (the point of this module):

* Agent package ids begin with ``agent.`` (kebab-case), distinct from node
  package ids like ``curio.builtin`` (see ``dev`` plan memo 07).
* **Capability ids are semantic behavior contracts, never asset paths.** A
  capability id must be two-or-more dot-separated lowercase segments
  (``node.explain``, ``dataflow.orchestrate``, ``package.recommend``) and must
  not contain a prompt filename, path separator, underscore, or ``.txt``.
* Prompt assets are referenced by *contained* package-relative path — no
  absolute paths and no ``..`` escapes.

User-facing overview: ``docs/AGENTS.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── identifier grammars ─────────────────────────────────────────────────────
# Agent package id: 'agent.' + kebab-case, e.g. 'agent.node-explainer'.
AGENT_ID_RE = re.compile(r"^agent\.[a-z0-9]+(?:-[a-z0-9]+)*$")

# Semantic capability id: two or more dot-separated lowercase segments, e.g.
# 'node.explain', 'dataset.fetch.author', 'package.recommend'. Deliberately
# excludes underscores, slashes, and '.txt' so a prompt filename can never
# double as a capability id.
CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")

# Semver-style version (matches the node-package rule).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")

# Package-relative asset path: printable, no whitespace, no leading slash.
_ASSET_PATH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")

_CATEGORIES = ("data", "node", "canvas", "package", "evaluate")
_EXECUTIONS = ("foreground", "background")
_REVIEW_POLICIES = ("report-only", "review-before-apply")
_TARGET_KINDS = ("node", "canvas", "connection")
_TRUST_TIERS = ("built-in", "global", "imported")

# Tokens a capability id must never contain (prompt-filename / path leakage).
_FORBIDDEN_CAPABILITY_SUBSTRINGS = ("_prompt", ".txt", "/", "\\", "_")


class AgentManifestError(ValueError):
    """Raised when an agent manifest is malformed or violates the supported schema."""


def _require_str(raw: object, *, where: str, allow_empty: bool = False) -> str:
    if not isinstance(raw, str):
        raise AgentManifestError(f"{where} must be a string (got {type(raw).__name__})")
    if not allow_empty and not raw.strip():
        raise AgentManifestError(f"{where} must be a non-empty string")
    return raw


def _validate_capability_id(cap_id: str, *, where: str) -> str:
    if not isinstance(cap_id, str) or not cap_id:
        raise AgentManifestError(f"{where}.id must be a non-empty string")
    for bad in _FORBIDDEN_CAPABILITY_SUBSTRINGS:
        if bad in cap_id:
            raise AgentManifestError(
                f"{where}.id {cap_id!r} must not contain {bad!r}; capability ids are "
                f"semantic behavior contracts, not prompt filenames or paths"
            )
    if not CAPABILITY_ID_RE.match(cap_id):
        raise AgentManifestError(
            f"{where}.id {cap_id!r} must be two or more dot-separated lowercase segments "
            f"matching {CAPABILITY_ID_RE.pattern}"
        )
    return cap_id


def _validate_asset_path(raw: object, *, where: str) -> str:
    path = _require_str(raw, where=where)
    if path.startswith("/"):
        raise AgentManifestError(f"{where} must be a package-relative path, not absolute: {path!r}")
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        raise AgentManifestError(f"{where} must not escape the package with '..': {path!r}")
    if not _ASSET_PATH_RE.match(path):
        raise AgentManifestError(
            f"{where} {path!r} is not a valid contained package-relative path"
        )
    return path


@dataclass(frozen=True)
class CapabilityDeclaration:
    """A semantic capability the agent declares, by id and contract version."""

    id: str
    contract_version: str

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "CapabilityDeclaration":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        cap_id = _validate_capability_id(raw.get("id"), where=where)
        contract_version = _require_str(raw.get("contractVersion"), where=f"{where}.contractVersion")
        return cls(id=cap_id, contract_version=contract_version)


@dataclass(frozen=True)
class PromptAsset:
    """A prompt file referenced by contained package-relative path and digest."""

    name: str
    path: str
    sha256: str | None
    variables: list[str]

    @classmethod
    def from_json(cls, name: str, raw: object, *, where: str) -> "PromptAsset":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        path = _validate_asset_path(raw.get("path"), where=f"{where}.path")
        sha_raw = raw.get("sha256")
        if sha_raw is not None and not isinstance(sha_raw, str):
            raise AgentManifestError(f"{where}.sha256 must be a string when present")
        vars_raw = raw.get("variables", [])
        if not isinstance(vars_raw, list) or not all(isinstance(v, str) for v in vars_raw):
            raise AgentManifestError(f"{where}.variables must be a list of strings")
        return cls(name=name, path=path, sha256=sha_raw or None, variables=list(vars_raw))


@dataclass(frozen=True)
class CompatibleTarget:
    """Where the agent may attach (node / canvas / connection) plus constraints."""

    kind: str
    requires: list[str]

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "CompatibleTarget":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        kind = raw.get("kind")
        if kind not in _TARGET_KINDS:
            raise AgentManifestError(f"{where}.kind must be one of {_TARGET_KINDS}, got {kind!r}")
        requires_raw = raw.get("requires", [])
        if not isinstance(requires_raw, list) or not all(isinstance(r, str) for r in requires_raw):
            raise AgentManifestError(f"{where}.requires must be a list of strings")
        return cls(kind=kind, requires=list(requires_raw))


@dataclass(frozen=True)
class ToolRequirement:
    """A typed, allowlisted tool requirement — not executable code or a grant."""

    id: str
    required: bool

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "ToolRequirement":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        tool_id = _require_str(raw.get("id"), where=f"{where}.id")
        # Tool ids share the capability-id grammar (dotted lowercase; DEC-017
        # — server-allowlisted typed ids, never paths or executable names).
        if not CAPABILITY_ID_RE.match(tool_id) or any(
            s in tool_id for s in _FORBIDDEN_CAPABILITY_SUBSTRINGS
        ):
            raise AgentManifestError(
                f"{where}.id {tool_id!r} must be dot-separated lowercase segments "
                f"matching {CAPABILITY_ID_RE.pattern}"
            )
        required_raw = raw.get("required", False)
        if not isinstance(required_raw, bool):
            raise AgentManifestError(f"{where}.required must be a boolean when present")
        return cls(id=tool_id, required=required_raw)


@dataclass(frozen=True)
class Provenance:
    """Origin and trust tier of the definition artifact."""

    publisher: str
    license: str | None
    trust: str | None

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "Provenance":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        publisher = _require_str(raw.get("publisher"), where=f"{where}.publisher")
        license_raw = raw.get("license")
        if license_raw is not None and not isinstance(license_raw, str):
            raise AgentManifestError(f"{where}.license must be a string or null")
        trust_raw = raw.get("trust")
        if trust_raw is not None and trust_raw not in _TRUST_TIERS:
            raise AgentManifestError(f"{where}.trust must be one of {_TRUST_TIERS} when present")
        return cls(publisher=publisher, license=license_raw, trust=trust_raw)


@dataclass(frozen=True)
class AgentManifest:
    """A parsed, validated hookable-agent manifest (supported subset)."""

    agent_id: str
    version: str
    name: str
    category: str
    purpose: str
    roles: list[str]
    capabilities: list[CapabilityDeclaration]
    delegates_to: list[str]
    # dev/106: hard dependencies — a SUBSET of delegates_to whose capability a
    # server code path of this agent invokes without model choice (e.g. the
    # Dataflow Builder's Solve). The agent is not functional in a project
    # without them; install resolves the closure (services.install_in_project).
    requires_agents: list[str]
    prompts: dict[str, PromptAsset]
    compatible_targets: list[CompatibleTarget]
    inputs_reads: list[str]
    inputs_required_config: list[str]
    outputs: list[str]
    tools: list[ToolRequirement]
    provider_capabilities: list[str]
    execution: str | None
    review_policy: str | None
    settings_profile_id: str | None
    settings_profile_version: str | None
    provenance: Provenance

    @property
    def dir_name(self) -> str:
        return f"{self.agent_id}@{self.version}"

    @property
    def capability_ids(self) -> list[str]:
        return [c.id for c in self.capabilities]


def parse_agent_manifest(raw: object, *, where: str = "manifest") -> AgentManifest:
    """Validate an already-parsed manifest object and return an ``AgentManifest``."""
    if not isinstance(raw, dict):
        raise AgentManifestError(f"{where}: top-level must be an object")

    agent_id = _require_str(raw.get("id"), where=f"{where}.id")
    if not AGENT_ID_RE.match(agent_id):
        raise AgentManifestError(
            f"{where}.id {agent_id!r} must begin with 'agent.' and be kebab-case, "
            f"matching {AGENT_ID_RE.pattern}"
        )

    version = _require_str(raw.get("version"), where=f"{where}.version")
    if not VERSION_RE.match(version):
        raise AgentManifestError(f"{where}.version {version!r} is not a valid semver string")

    category = raw.get("category")
    if category not in _CATEGORIES:
        raise AgentManifestError(f"{where}.category must be one of {_CATEGORIES}, got {category!r}")

    caps_raw = raw.get("capabilities")
    if not isinstance(caps_raw, list) or not caps_raw:
        raise AgentManifestError(f"{where}.capabilities must be a non-empty list")
    capabilities = [
        CapabilityDeclaration.from_json(c, where=f"{where}.capabilities[{i}]")
        for i, c in enumerate(caps_raw)
    ]
    seen: set[str] = set()
    for cap in capabilities:
        if cap.id in seen:
            raise AgentManifestError(f"{where}.capabilities: duplicate capability id {cap.id!r}")
        seen.add(cap.id)

    delegates_raw = raw.get("delegatesTo", [])
    if not isinstance(delegates_raw, list):
        raise AgentManifestError(f"{where}.delegatesTo must be a list")
    delegates_to: list[str] = []
    for i, d in enumerate(delegates_raw):
        d_id = _require_str(d, where=f"{where}.delegatesTo[{i}]")
        if not AGENT_ID_RE.match(d_id):
            raise AgentManifestError(
                f"{where}.delegatesTo[{i}] {d_id!r} must be an agent id matching {AGENT_ID_RE.pattern}"
            )
        if d_id == agent_id:
            raise AgentManifestError(f"{where}.delegatesTo must not reference the agent itself")
        delegates_to.append(d_id)

    requires_raw = raw.get("requiresAgents", [])
    if not isinstance(requires_raw, list):
        raise AgentManifestError(f"{where}.requiresAgents must be a list")
    requires_agents: list[str] = []
    for i, d in enumerate(requires_raw):
        r_id = _require_str(d, where=f"{where}.requiresAgents[{i}]")
        if not AGENT_ID_RE.match(r_id):
            raise AgentManifestError(
                f"{where}.requiresAgents[{i}] {r_id!r} must be an agent id matching {AGENT_ID_RE.pattern}"
            )
        if r_id == agent_id:
            raise AgentManifestError(f"{where}.requiresAgents must not reference the agent itself")
        if r_id not in delegates_to:
            raise AgentManifestError(
                f"{where}.requiresAgents[{i}] {r_id!r} must also be listed in delegatesTo"
            )
        if r_id in requires_agents:
            raise AgentManifestError(f"{where}.requiresAgents: duplicate {r_id!r}")
        requires_agents.append(r_id)

    prompts_raw = raw.get("prompts", {})
    if not isinstance(prompts_raw, dict):
        raise AgentManifestError(f"{where}.prompts must be an object")
    prompts = {
        name: PromptAsset.from_json(name, asset, where=f"{where}.prompts.{name}")
        for name, asset in prompts_raw.items()
    }

    targets_raw = raw.get("compatibleTargets", [])
    if not isinstance(targets_raw, list):
        raise AgentManifestError(f"{where}.compatibleTargets must be a list")
    compatible_targets = [
        CompatibleTarget.from_json(t, where=f"{where}.compatibleTargets[{i}]")
        for i, t in enumerate(targets_raw)
    ]

    inputs_raw = raw.get("inputs", {}) or {}
    if not isinstance(inputs_raw, dict):
        raise AgentManifestError(f"{where}.inputs must be an object")
    reads = inputs_raw.get("reads", [])
    required_config = inputs_raw.get("requiredConfig", [])
    for label, val in (("reads", reads), ("requiredConfig", required_config)):
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            raise AgentManifestError(f"{where}.inputs.{label} must be a list of strings")

    outputs = raw.get("outputs", [])
    if not isinstance(outputs, list) or not all(isinstance(x, str) for x in outputs):
        raise AgentManifestError(f"{where}.outputs must be a list of strings")

    tools_raw = raw.get("tools", [])
    if not isinstance(tools_raw, list):
        raise AgentManifestError(f"{where}.tools must be a list")
    tools = [ToolRequirement.from_json(t, where=f"{where}.tools[{i}]") for i, t in enumerate(tools_raw)]
    seen_tools: set[str] = set()
    for tool in tools:
        if tool.id in seen_tools:
            raise AgentManifestError(f"{where}.tools: duplicate tool id {tool.id!r}")
        seen_tools.add(tool.id)

    provider_raw = raw.get("providerRequirements", {}) or {}
    if not isinstance(provider_raw, dict):
        raise AgentManifestError(f"{where}.providerRequirements must be an object")
    provider_caps = provider_raw.get("capabilities", [])
    if not isinstance(provider_caps, list) or not all(isinstance(x, str) for x in provider_caps):
        raise AgentManifestError(f"{where}.providerRequirements.capabilities must be a list of strings")

    runtime_raw = raw.get("runtime", {}) or {}
    if not isinstance(runtime_raw, dict):
        raise AgentManifestError(f"{where}.runtime must be an object")
    execution = runtime_raw.get("execution")
    if execution is not None and execution not in _EXECUTIONS:
        raise AgentManifestError(f"{where}.runtime.execution must be one of {_EXECUTIONS} when present")
    review_policy = runtime_raw.get("reviewPolicy")
    if review_policy is not None and review_policy not in _REVIEW_POLICIES:
        raise AgentManifestError(
            f"{where}.runtime.reviewPolicy must be one of {_REVIEW_POLICIES} when present"
        )

    settings_raw = raw.get("settingsDefaults", {}) or {}
    if not isinstance(settings_raw, dict):
        raise AgentManifestError(f"{where}.settingsDefaults must be an object")
    profile_id = settings_raw.get("profileId")
    profile_version = settings_raw.get("profileVersion")
    if profile_id is not None and not isinstance(profile_id, str):
        raise AgentManifestError(f"{where}.settingsDefaults.profileId must be a string when present")
    if profile_version is not None and not isinstance(profile_version, str):
        raise AgentManifestError(f"{where}.settingsDefaults.profileVersion must be a string when present")

    provenance = Provenance.from_json(raw.get("provenance"), where=f"{where}.provenance")

    return AgentManifest(
        agent_id=agent_id,
        version=version,
        name=str(raw.get("name", agent_id)),
        category=category,
        purpose=str(raw.get("purpose", "")),
        roles=[r for r in raw.get("roles", []) if isinstance(r, str)],
        capabilities=capabilities,
        delegates_to=delegates_to,
        requires_agents=requires_agents,
        prompts=prompts,
        compatible_targets=compatible_targets,
        inputs_reads=list(reads),
        inputs_required_config=list(required_config),
        outputs=list(outputs),
        tools=tools,
        provider_capabilities=list(provider_caps),
        execution=execution,
        review_policy=review_policy,
        settings_profile_id=profile_id,
        settings_profile_version=profile_version,
        provenance=provenance,
    )


def load_agent_manifest(agent_dir_path: Path) -> AgentManifest:
    """Read ``<agent_dir>/manifest.json`` and validate the supported subset.

    Cross-checks the directory name against the manifest's ``id`` and
    ``version`` (the on-disk dir ``<id>@<version>`` is authoritative for which
    agent is being loaded; the manifest must agree), mirroring the node-package
    loader's dir/manifest agreement check.
    """
    manifest_path = agent_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise AgentManifestError(f"missing manifest.json in {agent_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc

    manifest = parse_agent_manifest(raw, where=str(manifest_path))

    expected_dir = f"{manifest.agent_id}@{manifest.version}"
    if agent_dir_path.name != expected_dir:
        raise AgentManifestError(
            f"directory name {agent_dir_path.name!r} does not match "
            f"manifest id/version {expected_dir!r}"
        )
    return manifest
