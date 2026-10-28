"""Hookable-agent manifest reader and validator.

Implements the supported subset of the agent-manifest schema (canonical
spec: ``docs/schemas/agent-package.v1.json``). This mirrors the node-package
validator in ``utk_curio/backend/app/packages/manifest.py`` — same shape:
a ``ManifestError`` subtype, frozen dataclasses with ``from_json`` classmethods,
and hand-rolled field validation with ``{where}.field`` error context.

Key invariants enforced here (the point of this module):

* Agent package ids begin with ``agent.``, then name their publisher and the
  agent (``agent.acme.heat-risk-summarizer``), as Discovery source ids begin with
  ``source.``. An agent's folder is ``<id>@<major>``, the major of its
  version, as a node package's, a dataset's and a source's are.
* **Capability ids are semantic behavior contracts, never asset paths.** A
  capability id must be two-or-more dot-separated lowercase segments
  (``node.explain``, ``dataflow.orchestrate``, ``package.recommend``) and must
  not contain a prompt filename, path separator, underscore, ``.txt`` or ``.md``.
* Prompt assets are referenced by a package-relative path contained in the
  package (no absolute path, no ``..`` escape) or, for a page of Curio's
  agent text, by ``curio:<path>``: a page of the base entry, read from Curio
  and never from the agent's folder (``agent_text.page_file``).
* ``catalog`` takes exactly ``listed`` and ``order``. It is parsed here for
  every manifest but counts only for the agents Curio ships (``builtin``).
* ``skills`` names the skills the agent's runs may hold, each by its name
  (``skills.is_name``), at most once; without it, every skill Curio ships. A
  capability's own ``skills`` are handed to every run of it, and the
  instruction's (``prompts.instruction.skills``) to every run of the
  instruction: the agent's chat, and each capability with no instruction of
  its own. No other prompt names skills.
* A manifest of ``kind`` ``base`` is the base entry Curio ships, no agent:
  it never loads as one.

The agents Curio ships are folders of this format in ``agents/``, read by
:func:`load_agent_manifest` as a user's agent is (``builtin``).

User-facing overview: ``docs/AGENT-CATALOG.md``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.agents.domain import agent_text, skills as skill_format
from utk_curio.common import shared_constants

# ── identifier grammars ─────────────────────────────────────────────────────
# One segment of an agent id, as of a Discovery source id (``source_id._SEG``).
_SEG = r"[a-z][a-z0-9-]{0,62}"
# Agent package id: 'agent.', the publisher, then the agent, each a segment,
# e.g. 'agent.acme.heat-risk-summarizer'.
AGENT_ID_RE = re.compile(rf"^agent\.{_SEG}(?:\.{_SEG}){{1,4}}$")
# The major in an agent's folder name, as in a node package's.
MAJOR_RE = re.compile(r"^(?:0|[1-9][0-9]{0,3})$")

# Semantic capability id: two or more dot-separated lowercase segments, e.g.
# 'node.explain', 'dataset.fetch.author', 'package.recommend'. Deliberately
# excludes underscores, slashes, '.txt' and '.md' so a prompt filename can never
# double as a capability id.
CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")

# Semver-style version (matches the node-package rule).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")

# Package-relative asset path: printable, no whitespace, no leading slash.
_ASSET_PATH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")

#: The manifest category vocabulary, exported so the catalog facets rail on
#: exactly these keys instead of restating them. ``agentCategories.json`` in the
#: frontend's ``src/contracts/`` holds it for the agent palette too.
AGENT_CATEGORIES: tuple[str, ...] = tuple(shared_constants.read("agentCategories")["categories"])
_CATEGORIES = AGENT_CATEGORIES
_EXECUTIONS = ("foreground", "background")
_REVIEW_POLICIES = ("report-only", "review-before-apply")
_TARGET_KINDS = ("node", "canvas", "connection")
_TRUST_TIERS = ("built-in", "global", "imported")

# Tokens a capability id must never contain (prompt-filename / path leakage).
_FORBIDDEN_CAPABILITY_SUBSTRINGS = ("_prompt", ".txt", ".md", "/", "\\", "_")

#: How a manifest names a page of Curio's agent text: ``curio:`` and the
#: page's path in the base entry (``agent_text.pages``), such as
#: ``curio:default_preamble.md``, the preamble every agent Curio ships runs,
#: which a user's agent may name too.
SHARED_PROMPT_PREFIX = agent_text.PAGE_PREFIX
#: Where a bundle (an export, an install's copy) carries such a page as a
#: file of the agent's own: ``prompts/<path>``.
SHARED_PROMPT_FOLDER = "prompts"
#: The keys of ``catalog``, all required, no other allowed.
_CATALOG_KEYS = ("listed", "order")
#: What a manifest that loads as an agent says it is (``kind``), when it says.
_KIND_AGENT = "agent"
#: The prompt an agent's chat runs, and each capability with no instruction
#: of its own: the only prompt that names skills.
_INSTRUCTION = "instruction"


class AgentManifestError(ValueError):
    """Raised when an agent manifest is malformed or violates the supported schema."""


def version_order(version: str) -> tuple:
    """A semver string as a sort key: ``10.0.0`` after ``2.0.0``, and a
    release after its pre-releases."""
    core, _, pre_release = str(version).partition("-")
    numbers = tuple(int(part) if part.isdigit() else 0 for part in core.split("+", 1)[0].split("."))
    return numbers, not pre_release


def coord_order(coord: str) -> tuple:
    """An ``<id>@<major>`` coordinate as a sort key: by id, then by major as a
    number, so ``@10`` comes after ``@2``."""
    agent_id, _, major = str(coord).partition("@")
    return agent_id, int(major) if major.isdigit() else -1, major


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


def _require_bool(raw: object, *, where: str) -> bool:
    if not isinstance(raw, bool):
        raise AgentManifestError(f"{where} must be true or false (got {raw!r})")
    return raw


def _skill_names(raw: object, *, where: str) -> tuple[str, ...]:
    """A ``skills`` list: skill names, each a name as the Agent Skills format
    has it (``skills.is_name``) and each once."""
    if not isinstance(raw, list):
        raise AgentManifestError(f"{where} must be a list of skill names")
    names: list[str] = []
    for i, name in enumerate(raw):
        if not skill_format.is_name(name):
            raise AgentManifestError(
                f"{where}[{i}] {name!r} is no skill's name: 1 to {skill_format.NAME_MAX} lowercase letters, "
                "digits and single hyphens"
            )
        if name in names:
            raise AgentManifestError(f"{where}: duplicate skill {name!r}")
        names.append(name)
    return tuple(names)


def _validate_asset_path(raw: object, *, where: str) -> str:
    path = _require_str(raw, where=where)
    if path.startswith(SHARED_PROMPT_PREFIX):
        try:
            agent_text.page_file(path[len(SHARED_PROMPT_PREFIX):])
        except agent_text.AgentTextError as exc:
            raise AgentManifestError(f"{where} {path!r}: {exc}") from None
        return path
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
    """A semantic capability the agent declares, by id and contract version.

    A capability may be a MODE: its own instruction (a ``prompts`` key), the
    context it reads and the catalog settings it needs. A delegated run of the
    capability runs that mode; without one it runs the agent's instruction.

    ``label`` names it in the agent details window, and a mode's
    ``worked_examples`` says whether its runs get worked examples; both count
    for the agents Curio ships only. ``skills`` are the skills every run of
    the capability is handed, its own procedures.
    """

    id: str
    contract_version: str
    instruction: str | None = None
    reads: tuple[str, ...] = ()
    required_config: tuple[str, ...] = ()
    label: str | None = None
    worked_examples: bool = False
    skills: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "CapabilityDeclaration":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where}: expected object, got {type(raw).__name__}")
        cap_id = _validate_capability_id(raw.get("id"), where=where)
        contract_version = _require_str(raw.get("contractVersion"), where=f"{where}.contractVersion")
        instruction = raw.get("instruction")
        if instruction is not None:
            instruction = _require_str(instruction, where=f"{where}.instruction")
        lists = {}
        for key in ("reads", "requiredConfig"):
            value = raw.get(key, [])
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise AgentManifestError(f"{where}.{key} must be a list of strings")
            lists[key] = tuple(value)
        label = raw.get("label")
        if label is not None:
            label = _require_str(label, where=f"{where}.label")
        worked = raw.get("workedExamples")
        if worked is not None:
            worked = _require_bool(worked, where=f"{where}.workedExamples")
            if instruction is None:
                raise AgentManifestError(
                    f"{where}.workedExamples: only a mode, a capability with its own instruction, "
                    "says whether its runs get worked examples; any other run follows the "
                    "agent's workedExamples"
                )
        own_skills = _skill_names(raw["skills"], where=f"{where}.skills") if "skills" in raw else ()
        return cls(id=cap_id, contract_version=contract_version, instruction=instruction,
                   reads=lists["reads"], required_config=lists["requiredConfig"],
                   label=label, worked_examples=bool(worked), skills=own_skills)


@dataclass(frozen=True)
class PromptAsset:
    """A prompt file referenced by contained package-relative path and digest,
    or a page of Curio's agent text, by ``curio:<path>``.

    ``runs`` says when a prompt that is neither the preamble, the instruction
    nor a mode's runs, in the words the agent details window shows (the
    Node Builder's Autark prompt); it counts for the agents Curio ships only.
    ``skills`` are the skills every run of the instruction is handed, the
    procedures it follows; only the instruction names them.
    """

    name: str
    path: str
    sha256: str | None
    variables: list[str]
    runs: str | None = None
    skills: tuple[str, ...] = ()

    @property
    def shared(self) -> str | None:
        """The path of the page of Curio's agent text that *path* names
        (``curio:<path>``), else None."""
        if self.path.startswith(SHARED_PROMPT_PREFIX):
            return self.path[len(SHARED_PROMPT_PREFIX):]
        return None

    @property
    def file(self) -> str:
        """Where a bundle holds the prompt: its path, or ``prompts/<path>``
        for a page of Curio's agent text, which an export and an install carry
        as a file."""
        shared = self.shared
        return self.path if shared is None else f"{SHARED_PROMPT_FOLDER}/{shared}"

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
        runs = raw.get("runs")
        if runs is not None:
            runs = _require_str(runs, where=f"{where}.runs")
        own_skills = _skill_names(raw["skills"], where=f"{where}.skills") if "skills" in raw else ()
        return cls(name=name, path=path, sha256=sha_raw or None, variables=list(vars_raw), runs=runs,
                   skills=own_skills)


@dataclass(frozen=True)
class CatalogPlacement:
    """Where an agent Curio ships stands in the Agent Catalog: a card
    (``listed``) or a helper that runs only as other agents' delegate, and its
    place in the roster (``order``), the order the details window names the
    agents that ask for a mode in. Parsed for every manifest; read only for a
    folder in Curio's ``agents/`` (``builtin``)."""

    listed: bool
    order: int

    @classmethod
    def from_json(cls, raw: object, *, where: str) -> "CatalogPlacement":
        if not isinstance(raw, dict):
            raise AgentManifestError(f"{where} must be an object with {list(_CATALOG_KEYS)}")
        unknown = sorted(set(raw) - set(_CATALOG_KEYS))
        if unknown:
            raise AgentManifestError(f"{where} takes only {list(_CATALOG_KEYS)}, not {unknown}")
        missing = [key for key in _CATALOG_KEYS if key not in raw]
        if missing:
            raise AgentManifestError(f"{where} must give {missing}")
        listed = _require_bool(raw["listed"], where=f"{where}.listed")
        order = raw["order"]
        if isinstance(order, bool) or not isinstance(order, int) or order < 0:
            raise AgentManifestError(f"{where}.order must be a whole number, 0 or more (got {order!r})")
        return cls(listed=listed, order=order)


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
    # A delegatesTo entry that names capabilities: agent id -> the only
    # capabilities of it this agent delegates. Absent means all of them.
    delegate_scopes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Where an agent Curio ships stands in the catalog; None for most
    # manifests. Read only for a folder in Curio's agents/ (builtin).
    catalog: CatalogPlacement | None = None
    # Whether a run under the instruction or a variant prompt gets worked
    # examples (a mode's capability decides for itself). Read only for the
    # agents Curio ships (builtin.gets_worked_examples).
    worked_examples: bool = False
    # The skills the agent's runs may hold, by name; None, for a manifest
    # that names none, is every skill Curio ships, and () none.
    skills: tuple[str, ...] | None = None

    @property
    def major(self) -> int:
        """The major of :attr:`version`: ``1`` for ``1.4.0``."""
        return int(self.version.split(".", 1)[0])

    @property
    def dir_name(self) -> str:
        """The agent's coordinate and folder: ``<id>@<major>``."""
        return f"{self.agent_id}@{self.major}"

    @property
    def capability_ids(self) -> list[str]:
        return [c.id for c in self.capabilities]

    def capability(self, capability_id: str) -> CapabilityDeclaration | None:
        return next((c for c in self.capabilities if c.id == capability_id), None)

    @property
    def instruction_skills(self) -> tuple[str, ...]:
        """The skills every run of the instruction is handed: its chat, and
        each capability with no instruction of its own."""
        instruction = self.prompts.get(_INSTRUCTION)
        return instruction.skills if instruction is not None else ()

    def delegates(self, agent_id: str, capability_id: str) -> bool:
        """Whether this agent delegates *capability_id* to *agent_id*."""
        if agent_id not in self.delegates_to:
            return False
        scope = self.delegate_scopes.get(agent_id)
        return scope is None or capability_id in scope

    def config_keys(self, capability_id: str | None = None) -> tuple[str, ...]:
        """The catalog settings a run reads: every run's
        (``inputs.requiredConfig``) and, for a run of *capability_id*, that
        capability's own."""
        declared = self.capability(capability_id) if capability_id else None
        own = declared.required_config if declared is not None else ()
        return tuple(dict.fromkeys([*self.inputs_required_config, *own]))


def _check_self_entry(
    scope_ids: tuple[str, ...] | None,
    capabilities: list[CapabilityDeclaration],
    *,
    where: str,
) -> None:
    """A ``delegatesTo`` entry naming the agent itself hands work to its own
    modes: it must name its capabilities, and each must be one of the agent's
    modes (a capability with an ``instruction`` of its own)."""
    if scope_ids is None:
        raise AgentManifestError(
            f"{where} names the agent itself: an entry for the agent itself must name "
            "the capabilities it delegates, each one of its own modes"
        )
    modes = {c.id for c in capabilities if c.instruction}
    outside = [c for c in scope_ids if c not in modes]
    if outside:
        raise AgentManifestError(
            f"{where} names the agent itself, so each of its capabilities must be one of "
            f"the agent's own modes; {outside} are not"
        )


def parse_agent_manifest(raw: object, *, where: str = "manifest") -> AgentManifest:
    """Validate an already-parsed manifest object and return an ``AgentManifest``."""
    if not isinstance(raw, dict):
        raise AgentManifestError(f"{where}: top-level must be an object")

    agent_id = _require_str(raw.get("id"), where=f"{where}.id")
    if not AGENT_ID_RE.match(agent_id):
        raise AgentManifestError(
            f"{where}.id {agent_id!r} must be 'agent.', its publisher and its name, "
            f"such as 'agent.acme.heat-risk-summarizer', matching {AGENT_ID_RE.pattern}"
        )
    kind = raw.get("kind", _KIND_AGENT)
    if kind != _KIND_AGENT:
        raise AgentManifestError(
            f"{where}.kind {kind!r}: an agent's manifest says kind {_KIND_AGENT!r} or no kind; "
            f"kind {agent_text.KIND_BASE!r} is Curio's base entry, the pages its agents read, which is no agent"
        )

    version = _require_str(raw.get("version"), where=f"{where}.version")
    if not VERSION_RE.match(version):
        raise AgentManifestError(f"{where}.version {version!r} is not a valid semver string")
    if not MAJOR_RE.match(version.split(".", 1)[0]):
        raise AgentManifestError(
            f"{where}.version {version!r} has a major that is not 0 to 9999 without leading zeros"
        )

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
    delegate_scopes: dict[str, tuple[str, ...]] = {}
    for i, d in enumerate(delegates_raw):
        if isinstance(d, dict):
            # {"id": ..., "capabilities": [...]}: only those capabilities of it.
            scope = d.get("capabilities")
            if not isinstance(scope, list) or not scope:
                raise AgentManifestError(
                    f"{where}.delegatesTo[{i}].capabilities must be a non-empty list"
                )
            scope_ids = tuple(
                _validate_capability_id(c, where=f"{where}.delegatesTo[{i}].capabilities[{j}]")
                for j, c in enumerate(scope)
            )
            d = d.get("id")
        else:
            scope_ids = None
        d_id = _require_str(d, where=f"{where}.delegatesTo[{i}]")
        if not AGENT_ID_RE.match(d_id):
            raise AgentManifestError(
                f"{where}.delegatesTo[{i}] {d_id!r} must be an agent id matching {AGENT_ID_RE.pattern}"
            )
        if d_id == agent_id:
            _check_self_entry(scope_ids, capabilities, where=f"{where}.delegatesTo[{i}]")
        if d_id in delegates_to:
            raise AgentManifestError(f"{where}.delegatesTo: duplicate {d_id!r}")
        delegates_to.append(d_id)
        if scope_ids is not None:
            delegate_scopes[d_id] = scope_ids

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
    for i, cap in enumerate(capabilities):
        if cap.instruction is not None and cap.instruction not in prompts:
            raise AgentManifestError(
                f"{where}.capabilities[{i}].instruction {cap.instruction!r} names no prompts entry"
            )
    # The preamble, the instruction and a mode's prompt run when the details
    # window says; only another prompt says when it runs.
    named = {"system", "instruction", *(cap.instruction for cap in capabilities if cap.instruction)}
    for name, asset in prompts.items():
        if asset.runs is not None and name in named:
            raise AgentManifestError(
                f"{where}.prompts.{name}.runs: the preamble, the instruction and a mode's prompt "
                "say no runs; only another prompt says when it runs"
            )
        if asset.skills and name != _INSTRUCTION:
            raise AgentManifestError(
                f"{where}.prompts.{name}.skills: only the instruction names the skills its runs are "
                "handed; a mode's own are its capability's skills"
            )

    catalog_raw = raw.get("catalog")
    catalog = None if catalog_raw is None else CatalogPlacement.from_json(catalog_raw, where=f"{where}.catalog")
    worked_examples = raw.get("workedExamples", False)
    _require_bool(worked_examples, where=f"{where}.workedExamples")
    agent_skills = _skill_names(raw["skills"], where=f"{where}.skills") if "skills" in raw else None

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
        name=_require_str(raw.get("name"), where=f"{where}.name"),
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
        delegate_scopes=delegate_scopes,
        catalog=catalog,
        worked_examples=worked_examples,
        skills=agent_skills,
    )


def load_agent_manifest(agent_dir_path: Path) -> AgentManifest:
    """Read ``<agent_dir>/manifest.json`` and validate the supported subset.

    Cross-checks the directory name against the manifest's ``id`` and the
    major of its ``version`` (the on-disk dir ``<id>@<major>`` is authoritative
    for which agent is being loaded; the manifest must agree), mirroring the
    node-package loader's dir/manifest agreement check.
    """
    manifest_path = agent_dir_path / "manifest.json"
    if not manifest_path.is_file():
        raise AgentManifestError(f"missing manifest.json in {agent_dir_path}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentManifestError(f"{manifest_path}: invalid JSON: {exc}") from exc

    manifest = parse_agent_manifest(raw, where=str(manifest_path))

    expected_dir = manifest.dir_name
    if agent_dir_path.name != expected_dir:
        raise AgentManifestError(
            f"directory name {agent_dir_path.name!r} does not match "
            f"the manifest's id and major {expected_dir!r}"
        )
    return manifest
