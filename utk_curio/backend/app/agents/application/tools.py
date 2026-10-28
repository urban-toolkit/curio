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

**Native tools.** Each contract carries the JSON Schema of its params. A run
whose LLM configuration calls tools natively (``chat_capabilities``) is offered
its grants as native tools (:func:`native_tools`), named by the reversible
:func:`wire_name`; every other run asks for a tool in a fenced ``toolRequest``
block (``content.tail_instruction``). Either way the request passes the same
parser, budgets, grant check and mint: the schema tells the model the shape,
and never replaces the server's own validation.

**What a run is told.** A contract's description and the text of each of its
params are the base entry's ``tools.md``, the section named by its id
(:func:`tool_text`); this module holds each schema's shape.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType
from typing import Iterable

from utk_curio.backend.app.agents.application.turns import examples as worked_examples
from utk_curio.backend.app.agents.domain import (
    agent_text,
    builtin,
    contracts,
    data_pool_settings,
    node_settings,
    plan_topology,
)
from utk_curio.backend.app.agents.domain.tool_names import (
    DELEGATE_TOOL,
    tool_id_of,
    wire_name,
)
from utk_curio.backend.app.agents.domain.manifest import ToolRequirement
from utk_curio.backend.app.agents.domain import dashboards
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.common import spatial
from utk_curio.backend.app.execution.code_references import WIDGET_KINDS

_EFFECTS = ("read", "mutate")

# Tool results are untrusted context data: bounded, truncated with a marker.
TOOL_RESULT_MAX_CHARS = 32_000


def _object(properties: dict, *required: str) -> dict:
    """A JSON Schema object. Keys it does not list stay allowed: the reader or
    the mint refuses a wrong call, with a reason the model can act on."""
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _text(description: str) -> dict:
    return {"type": "string", "description": description}


def _texts(description: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _map(description: str) -> dict:
    """An object whose keys the tool does not fix, such as a manifest."""
    return {"type": "object", "description": description}


#: models.search bounds: the most rows a call returns, and the most labels per
#: row (``contracts``, which the tool's text reads them from too).
_MODELS_SEARCH_MAX_ROWS = contracts.MODELS_SEARCH_MAX_ROWS
_MODEL_LABELS_MAX = contracts.MODEL_LABELS_MAX


# --- What a run is told of each tool -------------------------------------------
#
# The base entry's tools.md: one section per tool by its id, the native
# delegation tool's (``delegate``), and ``parameters``, the texts of the
# parameters several tools take. A section's first part is the tool's
# description, ``### Native`` the description a run on native tools gets in its
# place, and ``### Parameters`` one ``- <path>: <text>`` line per parameter, by
# its path in the tool's parameters: ``nodes.ref`` is the ``ref`` of each entry
# of ``nodes``, and ``widgets[]`` an entry of ``widgets``.

#: The section of ``tools.md`` with the texts of the parameters several tools take.
SHARED_PARAMETERS = "parameters"
_SUBSECTION_RE = re.compile(r"^### (.+?)[ \t]*$", re.MULTILINE)
_SUBSECTIONS = ("Native", "Parameters")
_PARAMETER_RE = re.compile(
    r"^- (?P<path>[A-Za-z][A-Za-z0-9]*(?:\[\])?(?:\.[A-Za-z][A-Za-z0-9]*(?:\[\])?)*): (?P<text>\S.*)$"
)


@dataclass(frozen=True)
class ToolText:
    """What ``tools.md`` says of one tool."""

    description: str
    #: What a run on native tools gets in place of the description, or None.
    native_description: str | None
    #: The text of each parameter, by its path in the tool's parameters.
    parameters: Mapping[str, str]


def tool_texts() -> Mapping[str, ToolText]:
    """Every section of the base entry's ``tools.md``, by name, read as an
    agent reads the page (``agent_text``)."""
    return _tool_texts(agent_text.page_text(builtin.TOOLS_FILE))


@lru_cache(maxsize=8)
def _tool_texts(text: str) -> Mapping[str, ToolText]:
    where = agent_text.PAGE_PREFIX + builtin.TOOLS_FILE
    return MappingProxyType({
        name: _tool_text(name, body, f"{where}, section {name}")
        for name, body in agent_text.split_sections(text, where).items()
    })


def _tool_text(name: str, body: str, where: str) -> ToolText:
    """One section of ``tools.md``. The section ``parameters`` is parameter
    lines alone."""
    lead, *rest = ("", "Parameters", body) if name == SHARED_PARAMETERS else _SUBSECTION_RE.split(body)
    parts = dict(zip(rest[0::2], rest[1::2]))
    if set(parts) - set(_SUBSECTIONS) or len(parts) != len(rest) // 2:
        raise agent_text.AgentTextError(
            f"{where}: a tool's subsections are {' and '.join(_SUBSECTIONS)}, each at most once, "
            f"not {rest[0::2]}"
        )
    parameters: dict[str, str] = {}
    for line in parts.get("Parameters", "").splitlines():
        if not line.strip():
            continue
        match = _PARAMETER_RE.match(line)
        if match is None:
            raise agent_text.AgentTextError(f"{where}: {line!r} is no '- <path>: <text>' line")
        if match["path"] in parameters:
            raise agent_text.AgentTextError(f"{where} gives the parameter {match['path']!r} twice")
        parameters[match["path"]] = match["text"]
    native = parts.get("Native", "").strip("\n")
    return ToolText(lead.strip("\n"), native or None, MappingProxyType(parameters))


def tool_text(tool_id: str) -> ToolText:
    """What ``tools.md`` says of the tool *tool_id*, or of the native
    delegation tool. Raises ``agent_text.AgentTextError`` when it has no
    section for it."""
    texts = tool_texts()
    if tool_id not in texts:
        raise agent_text.AgentTextError(
            f"{agent_text.PAGE_PREFIX}{builtin.TOOLS_FILE} has no section for the tool {tool_id!r}"
        )
    return texts[tool_id]


class _Say:
    """The text of each parameter one tool's schema asks for, by its path:
    the tool's own, else one several tools share. ``asked`` keeps each path
    asked for."""

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        self.own = tool_text(tool_id).parameters
        self.shared = tool_text(SHARED_PARAMETERS).parameters
        self.asked: list[str] = []

    def __call__(self, path: str) -> str:
        self.asked.append(path)
        for found in (self.own, self.shared):
            if path in found:
                return found[path]
        raise agent_text.AgentTextError(
            f"{agent_text.PAGE_PREFIX}{builtin.TOOLS_FILE} gives no text for the parameter {path!r} "
            f"of {self.tool_id}, in its section or in {SHARED_PARAMETERS}"
        )


Say = Callable[[str], str]


def _no_parameters(_say: Say) -> dict:
    return _object({})


def _node_id(say: Say) -> dict:
    return _text(say("nodeId"))


def _appearance(say: Say) -> dict:
    return _object({"backgroundColor": _text(say("appearance.backgroundColor"))})


def _widgets(say: Say) -> dict:
    """#662: the widgets a node declares (``$defs.widget``); the server checks the rest."""
    return {
        "type": "array",
        "items": {
            **_object(
                {
                    "name": _text(say("widgets.name")),
                    "type": {"type": "string", "enum": list(WIDGET_KINDS)},
                    "label": _text(say("widgets.label")),
                },
                "name", "type",
            ),
            "description": say("widgets[]"),
        },
        "description": say("widgets"),
    }


def _spatial_join(say: Say) -> dict:
    """A Spatial Join's operation and output (``$defs.nodeMetadata.spatialJoin``),
    with the join's own choices; the server checks the rest."""
    return {
        **_object({
            "predicate": {"type": "string", "enum": list(spatial.PREDICATES)},
            "output": {"type": "string", "enum": list(spatial.OUTPUTS)},
        }),
        "description": say("spatialJoin"),
    }


def _data_pool(say: Say) -> dict:
    """A Data Pool's conflict modes (``$defs.nodeMetadata.dataPool``), with the
    pool's own modes; the server checks the rest."""
    def mode(text: str) -> dict:
        return {"type": "string", "enum": list(data_pool_settings.MODES), "description": text}

    return {
        **_object({
            "insideChart": mode(say("dataPool.insideChart")),
            "betweenCharts": mode(say("dataPool.betweenCharts")),
        }),
        "description": say("dataPool"),
    }


def _simple_vis(say: Say) -> dict:
    """A Simple View's image column (``$defs.nodeMetadata.simpleVis``); the
    server checks the rest."""
    return {
        **_object({"imageColumn": _text(say("simpleVis.imageColumn"))}),
        "description": say("simpleVis"),
    }


#: The tool a chat run loads a skill with (``skill_runs``).
SKILL_TOOL = "skill.read"


def _skill_read(say: Say) -> dict:
    """``skill.read``'s params: the name of a skill, one Curio ships unless
    the run gives its own list (:func:`native_tools`), and one of its files."""
    names = [folder.name for folder in skill_format.shipped_folders()]
    return _object(
        {
            "name": {"type": "string", "enum": names, "description": say("name")},
            "path": _text(say("path")),
        },
        "name",
    )


def _scenario(say: Say) -> dict:
    """#662: one scenario a plan saves: a selection, or a duplicate of one."""
    return _object(
        {
            "name": _text(say("scenarios.name")),
            "nodes": _texts(say("scenarios.nodes")),
            "duplicateOf": _text(say("scenarios.duplicateOf")),
            "copies": _map(say("scenarios.copies")),
            "values": _map(say("scenarios.values")),
            "description": _text(say("scenarios.description")),
            "color": _text(say("scenarios.color")),
        },
        "name",
    )


@dataclass(frozen=True)
class ToolContract:
    """A typed, versioned reference to one domain-owned operation.

    What a run is told of it is the section of ``tools.md`` named by its id
    (:func:`tool_text`). ``parameters`` is the JSON Schema of its params,
    offered to a model that calls tools natively: its shape is
    ``parameter_schema``'s and each parameter's text the section's.
    ``native_description`` replaces ``description`` there when the fenced one
    teaches a block syntax a native call does not use, or spells out params
    the schema already gives: a native description holds at most 1,024
    characters (OpenAI's limit)."""

    id: str
    contract_version: str
    effect: str  # "read" | "mutate"
    #: The JSON Schema of its params, given the text of each (``_Say``).
    parameter_schema: Callable[[Say], dict] = field(default=_no_parameters, compare=False)
    #: What the tool does, in plain words for people, where the agent details
    #: window lists an agent's tools. A mutate contract's starts "Propose".
    label: str = ""

    def __post_init__(self):
        if self.effect not in _EFFECTS:
            raise ValueError(f"tool effect must be one of {_EFFECTS}, got {self.effect!r}")

    @property
    def description(self) -> str:
        return tool_text(self.id).description

    @property
    def native_description(self) -> str | None:
        return tool_text(self.id).native_description

    @property
    def parameters(self) -> dict:
        return self.parameter_schema(_Say(self.id))


# The server-owned allowlist (DEC-017). Each contract has a named consumer in
# the built-in roster (dev/41 §4.3, dev/48): nothing speculative.
REGISTRY: dict[str, ToolContract] = {
    "dataflow.read": ToolContract(
        id="dataflow.read",
        contract_version="2",
        effect="read",
        label="Read the dataflow",
        parameter_schema=lambda say: _object({
            "include": {
                "type": "array",
                "items": {"type": "string", "enum": ["content"]},
                "description": say("include"),
            },
        }),
    ),
    # dev/67-4 (DEC-053), consumer: the Researcher, in its chat. Policy-gated
    # egress (SSRF guards, byte caps, per-run budget): verification of
    # external dataset APIs, never crawling.
    "web.fetch": ToolContract(
        id="web.fetch",
        contract_version="1",
        effect="read",
        label="Read a web page",
        parameter_schema=lambda say: _object({"url": _text(say("url"))}, "url"),
    ),
    "web.search": ToolContract(
        id="web.search",
        contract_version="1",
        effect="read",
        label="Search the web",
        parameter_schema=lambda say: _object({"q": _text(say("q"))}, "q"),
    ),
    # dev/67-2 (DEC-052), consumers: the builder/debug/explainer agents. The
    # runtime journal's read surface: why a node's last run failed.
    "node.runtime.read": ToolContract(
        id="node.runtime.read",
        contract_version="1",
        effect="read",
        label="Read a node's last run",
        parameter_schema=lambda say: _object({"nodeId": _node_id(say)}),
    ),
    "node.read": ToolContract(
        id="node.read",
        contract_version="1",
        effect="read",
        label="Read a node",
        parameter_schema=lambda say: _object({"nodeId": _node_id(say)}),
    ),
    # Consumers: the Node Builder and the Dataflow Builder, in their chats.
    # What changed in a node: its runs and edits as its Provenance drawer
    # lists them, from the saved dataflow (the projects domain keys them as a
    # load does).
    "node.history.read": ToolContract(
        id="node.history.read",
        contract_version="1",
        effect="read",
        label="Read a node's history",
        parameter_schema=lambda say: _object({
            "nodeId": _node_id(say),
            "entryId": {"type": "integer", "description": say("entryId")},
        }),
    ),
    "node.content.write": ToolContract(
        id="node.content.write",
        contract_version="1",
        effect="mutate",
        label="Propose a content change",
        parameter_schema=lambda say: _object(
            {"nodeId": _node_id(say), "content": _text(say("content"))},
            "content",
        ),
    ),
    # Consumers: the Node Builder and the Dataflow Builder. A node already on
    # the canvas: a Data Pool's modes, a Simple View's image column, a Spatial
    # Join's operation and output and its widget values, each judged by its
    # node's own rule; the apply writes them, and the canvas makes the change
    # through the node's own setters.
    "node.settings.write": ToolContract(
        id="node.settings.write",
        contract_version="1",
        effect="mutate",
        label="Propose a settings change",
        parameter_schema=lambda say: _object({
            "nodeId": _node_id(say),
            "dataPool": _data_pool(say),
            "simpleVis": _simple_vis(say),
            "spatialJoin": _spatial_join(say),
            "widgets": _map(say("widgets")),
        }),
    ),
    # dev/50, consumer: the Dataset Finder. Grounds the "From your Data
    # Catalog" lane in the real catalog (the datasets domain owns the data;
    # this module owns none of its own).
    "catalog.search": ToolContract(
        id="catalog.search",
        contract_version="1",
        effect="read",
        label="Search the Data Catalog",
        parameter_schema=lambda say: _object({
            "q": _text(say("q")),
            "format": _text(say("format")),
            "origin": _text(say("origin")),
        }),
    ),
    # Consumer: the Node Builder, in its chat and its content mode. Grounds a
    # node that runs a model in the model packages this account holds (the
    # packages domain owns the data and the loader line; this module owns
    # none of its own).
    "models.search": ToolContract(
        id="models.search",
        contract_version="1",
        effect="read",
        label="Search the Model Catalog",
        parameter_schema=lambda say: _object({
            "q": _text(say("q")),
            "limit": {"type": "integer", "description": say("limit")},
        }),
    ),
    # Consumer: the Dataflow Builder. Any worked example on request, beside
    # the ones its runs are given (turns/examples owns the index and the view).
    "examples.read": ToolContract(
        id="examples.read",
        contract_version="1",
        effect="read",
        label="Read worked examples",
        parameter_schema=lambda say: _object({"key": _text(say("key"))}),
    ),
    # Consumer: the Dataflow Builder. A scenario of another project is one the
    # user drags in from the Scenario Catalog, which owns the listing (this
    # module owns none of its own).
    "scenarios.search": ToolContract(
        id="scenarios.search",
        contract_version="1",
        effect="read",
        label="Search the Scenario Catalog",
        parameter_schema=lambda say: _object({"q": _text(say("q"))}),
    ),
    # Consumers: every chat run whose system turn lists skills, an agent's
    # Curio ships or a user's (``skill_runs.grants``): it is granted exactly
    # then, never by a manifest, and executed against the run's skills
    # (``skill_runs.read``), never here.
    SKILL_TOOL: ToolContract(
        id=SKILL_TOOL,
        contract_version="1",
        effect="read",
        label="Read a skill",
        parameter_schema=_skill_read,
    ),
    # Discovery Catalog, consumer: the Dataset Finder. Three contracts, not
    # two, and deliberately the same roster/detail/reviewed-mutate shape
    # packages.catalog + packages.resolve + package.install already has: it is
    # the shape that stops the model inventing a source id.
    "discovery.sources": ToolContract(
        id="discovery.sources",
        contract_version="1",
        effect="read",
        label="List the data portals",
    ),
    "discovery.search": ToolContract(
        id="discovery.search",
        contract_version="1",
        effect="read",
        label="Search the data portals",
        parameter_schema=lambda say: _object({
            "q": _text(say("q")),
            "sourceId": _text(say("sourceId")),
            "format": _text(say("format")),
        }),
    ),
    "discovery.acquire": ToolContract(
        id="discovery.acquire",
        contract_version="1",
        effect="mutate",
        label="Propose a download",
        parameter_schema=lambda say: _object(
            {
                "sourceId": _text(say("sourceId")),
                "resourceId": _text(say("resourceId")),
                "format": _text(say("format")),
            },
            "sourceId", "resourceId",
        ),
    ),
    # dev/84, consumer: the Node Builder, in its chat. Grounds package
    # recommendations in the real Nodes Catalog + this project's lockfile
    # (the packages domain owns the data; this module owns none of its own).
    "packages.catalog": ToolContract(
        id="packages.catalog",
        contract_version="1",
        effect="read",
        label="Search the Node Catalog",
        parameter_schema=lambda say: _object({"q": _text(say("q"))}),
    ),
    # dev/84, consumer: the Node Builder, in its chat.
    # deps/permissions/conflicts come from the real resolver, never invented.
    "packages.resolve": ToolContract(
        id="packages.resolve",
        contract_version="1",
        effect="read",
        label="Check a package's dependencies and permissions",
        parameter_schema=lambda say: _object({"dirNames": _texts(say("dirNames"))}, "dirNames"),
    ),
    # dev/52, consumer: the Dataflow Builder. The DR-1 graph-level
    # mutation: the model emits a `dataflowPlan` tail block (not a
    # toolRequest) and the runtime mints the reviewed plan proposal from it;
    # the authenticated apply endpoint inserts the whole ADDITIVE graph.
    "dataflow.plan.write": ToolContract(
        id="dataflow.plan.write",
        contract_version="1",
        effect="mutate",
        label="Propose a plan",
        parameter_schema=lambda say: _object(
            {
                "goal": _text(say("goal")),
                "nodes": {
                    "type": "array",
                    "items": _object(
                        {
                            "ref": _text(say("nodes.ref")),
                            "nodeType": _text(say("nodes.nodeType")),
                            "title": _text(say("nodes.title")),
                            "intent": _text(say("nodes.intent")),
                            "expects": _text(say("nodes.expects")),
                            "widgets": _widgets(say),
                            "spatialJoin": _spatial_join(say),
                            "dataPool": _data_pool(say),
                            "simpleVis": _simple_vis(say),
                        },
                        "ref", "nodeType", "title", "intent",
                    ),
                },
                "edges": {
                    "type": "array",
                    "items": _object(
                        {
                            "from": _text(say("edges.from")),
                            "to": _text(say("edges.to")),
                            "kind": {"type": "string", "enum": ["data", "interaction"]},
                            "toHandle": _text(say("edges.toHandle")),
                        },
                        "from", "to",
                    ),
                },
                "scenarios": {"type": "array", "items": _scenario(say)},
                "removeNodes": _texts(say("removeNodes")),
                "removeEdges": _texts(say("removeEdges")),
            },
            "goal",
        ),
    ),
    # dev/50, consumer: the Dataset Finder. The catalog lane's reviewed
    # handoff: applying installs ONE dataset through the existing
    # dataset-only flow; never an agent.
    "dataset.install": ToolContract(
        id="dataset.install",
        contract_version="1",
        effect="mutate",
        label="Propose adding a dataset",
        parameter_schema=lambda say: _object({"datasetId": _text(say("datasetId"))}, "datasetId"),
    ),
    # dev/84, consumers: the Node Builder and the Researcher. The reviewed install
    # lane: applying routes through the existing package install flow
    # (permissions + dependencies + conflicts); never a silent install,
    # never a built-in.
    "package.install": ToolContract(
        id="package.install",
        contract_version="1",
        effect="mutate",
        label="Propose a package install",
        parameter_schema=lambda say: _object(
            {
                "dirName": _text(say("dirName")),
                "reason": _text(say("reason")),
                "notes": {
                    "type": "array",
                    "items": _object(
                        {
                            "title": _text(say("notes.title")),
                            "content": _text(say("notes.content")),
                            "color": _text(say("notes.color")),
                        },
                        "content",
                    ),
                    "description": say("notes"),
                },
            },
            "dirName",
        ),
    ),
    # dev/48, consumer: the Node Builder. Reuse-first: nodeType must come
    # from the run's "Available node templates" list (composed at run time
    # from the packages registry; this module owns no template knowledge).
    "node.create": ToolContract(
        id="node.create",
        contract_version="1",
        effect="mutate",
        label="Propose a node",
        parameter_schema=lambda say: _object(
            {
                "nodeType": _text(say("nodeType")),
                "content": _text(say("content")),
                "title": _text(say("title")),
                "goal": _text(say("goal")),
                "appearance": _appearance(say),
                "widgets": _widgets(say),
                "spatialJoin": _spatial_join(say),
                "dataPool": _data_pool(say),
                "simpleVis": _simple_vis(say),
            },
            "nodeType", "content",
        ),
    ),
    # dev/89, consumers: the Node Builder (its package-writing mode's drafts),
    # the Researcher and the Dataflow Builder (the drafts they ask for). The
    # ONE package-authoring mutate contract, and the one way an agent makes a
    # node type: requesting it checks every template the draft adds
    # (justification, label, grounded code), runs the isolated build service
    # (validate, resolve, compile, preview, package, all staged and
    # content-addressed) and mints the reviewed package-draft proposal; Apply
    # promotes the exact reviewed artifact digest through the promotion
    # coordinator, never a silent install.
    "package.draft.apply": ToolContract(
        id="package.draft.apply",
        contract_version="1",
        effect="mutate",
        label="Propose a package draft",
        parameter_schema=lambda say: _object(
            {
                "mode": {"type": "string", "enum": ["create", "extend"]},
                "baseDigest": _text(say("baseDigest")),
                "target": _text(say("target")),
                "manifest": _map(say("manifest")),
                "files": _map(say("files")),
                "behaviorEntries": _texts(say("behaviorEntries")),
                "dependencies": _map(say("dependencies")),
                "previewTemplates": _texts(say("previewTemplates")),
                "nodes": {
                    "type": "array",
                    "items": _object(
                        {
                            "templateId": _text(say("nodes.templateId")),
                            "title": _text(say("nodes.title")),
                            "content": _text(say("nodes.content")),
                            "appearance": _appearance(say),
                        },
                        "templateId",
                    ),
                    "description": say("nodes"),
                },
                "justification": _text(say("justification")),
            },
            "mode", "manifest",
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


def delegate_tool(capabilities: Iterable[str]) -> dict:
    """The native delegation tool, its ``capability`` limited to *capabilities*
    (the delegates this agent may use), described by ``tools.md``'s section
    ``delegate``. Who handles each one is in the run's delegation paragraph
    (``content.delegation_instruction``)."""
    say = _Say(DELEGATE_TOOL)
    return {
        "name": DELEGATE_TOOL,
        "description": tool_text(DELEGATE_TOOL).description,
        "parameters": _object(
            {
                "capability": {
                    "type": "string",
                    "enum": list(capabilities),
                    "description": say("capability"),
                },
                "inputs": _map(say("inputs")),
            },
            "capability",
        ),
    }


def native_tools(
    granted: Iterable[str], delegate_capabilities: Iterable[str] = (), skills: Iterable[str] | None = None,
) -> list[dict]:
    """The run's grants as native tools, ``{name, description, parameters}``
    each, in grant order, then the delegation tool when there is something to
    delegate. ``skill.read``'s ``name`` takes exactly *skills*, the skills the
    run lists, when it gives them. Copies: a provider's conversion never
    reaches the registry."""
    specs: list[dict] = []
    for tool_id in granted:
        contract = REGISTRY.get(tool_id)
        if contract is None:
            continue
        parameters = copy.deepcopy(contract.parameters)
        if contract.id == SKILL_TOOL and skills is not None:
            parameters["properties"]["name"]["enum"] = list(skills)
        specs.append({
            "name": wire_name(contract.id),
            "description": contract.native_description or contract.description,
            "parameters": parameters,
        })
    capabilities = list(dict.fromkeys(delegate_capabilities))
    if capabilities:
        specs.append(delegate_tool(capabilities))
    return specs


def _truncate(text: str) -> str:
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + ("\n" + agent_text.message("tools.result-truncated"))


# catalog.search bounds (dev/50): plenty for ranking, small enough to never
# crowd the context; description is display metadata, not a document.
#: Bounds for the discovery tools, matching the catalog ones above. A portal can
#: answer with hundreds; a model needs the first handful.
_DISCOVERY_MAX_ROWS = 20
_DISCOVERY_DESC_MAX_CHARS = 200

_CATALOG_SEARCH_MAX_ROWS = 40
_CATALOG_DESC_MAX_CHARS = 200
_CATALOG_PARAM_MAX_CHARS = 200
#: scenarios.search bounds, as the Data Catalog's.
_SCENARIOS_SEARCH_MAX_ROWS = 40


def _cut(key: str, rows: list, bound: int) -> dict:
    """``{key: the first *bound* rows}``, and, when it left rows out,
    ``{key}Elided``: how many, so a model shown a cut list knows it is one
    (the ``columnsElided`` of ``upstream_schema``). The count comes first, so
    a result cut at the tool output bound still carries it."""
    payload: dict = {}
    if len(rows) > bound:
        payload[f"{key}Elided"] = len(rows) - bound
    payload[key] = rows[:bound]
    return payload


def _catalog_search_rows(user_key: str, project_id: str, params: dict) -> list[dict]:
    """Bounded catalog rows for the dev/50 read tool: the first
    ``_CATALOG_SEARCH_MAX_ROWS`` of :func:`_catalog_listing_rows`."""
    return _catalog_listing_rows(user_key, project_id, params)[:_CATALOG_SEARCH_MAX_ROWS]


def _catalog_listing_rows(user_key: str, project_id: str, params: dict) -> list[dict]:
    """Every row of the Data Catalog listing *params* filters, as the
    catalog.search tool shows a row. A candidate row is checked against
    these, all of them, since a dataset past the rows a search shows is
    still one the Data Catalog holds.

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
    for item in listing.get("items") or []:
        row = {
            "id": item.get("id"),
            "name": item.get("title"),
            "format": item.get("format"),
            "origin": item.get("origin"),
            "installed": bool(item.get("installed")),
            "description": (item.get("description") or "")[:_CATALOG_DESC_MAX_CHARS],
        }
        # dev/114 (DEC-072): the resolved data path — the listing already
        # confined it to the allowed read roots (#143 chokepoint) — and the
        # domain's ONE loader recipe for it. These are the only local paths
        # generated node content may open; the grounding gate checks against
        # the same listing, so a row here is grounded by construction.
        path = item.get("path")
        if isinstance(path, str) and path.strip():
            row["path"] = path
            snippet = item.get("loaderSnippet")
            if not (isinstance(snippet, dict) and isinstance(snippet.get("code"), str)):
                from utk_curio.backend.app.datasets.domain.catalog_item import loader_snippet

                snippet = loader_snippet(item.get("format"), path)
            row["loader"] = snippet.get("code")
        rows.append(row)
    return rows


def _request_user():
    """The signed-in account the request runs as (``g.user``), as
    :func:`_catalog_listing_rows` reads it; None outside a request or with no
    one signed in."""
    from flask import g, has_app_context

    return getattr(g, "user", None) if has_app_context() else None


def _execute_scenarios_search(project_id: str, params: dict) -> tuple[str, str]:
    """``scenarios.search``: the Scenario Catalog's own listing, the one its
    drawer browses (``ScenarioCatalogService.list_catalog``), read as the
    signed-in account, as :func:`_catalog_listing_rows` reads the Data
    Catalog's. One row per scenario, never its project's graph preview, the
    first ``_SCENARIOS_SEARCH_MAX_ROWS`` with how many were left out
    (:func:`_cut`). The catalog is an account's, so a run with none is told
    so before anything is read."""
    from utk_curio.backend.app.scenario_catalog.service import ScenarioCatalogService

    user = _request_user()
    if user is None:
        return "error", agent_text.message("tools.scenarios-no-account")
    query = params.get("q")
    q = query.strip()[:_CATALOG_PARAM_MAX_CHARS] if isinstance(query, str) and query.strip() else None
    rows = [
        {
            "key": item["key"],
            "name": item["name"],
            "description": (item.get("description") or "")[:_CATALOG_DESC_MAX_CHARS],
            "project": item["project"]["name"],
            "nodeCount": item["nodeCount"],
            "inThisDataflow": item["project"]["id"] == project_id,
        }
        for item in ScenarioCatalogService(user).list_catalog(q=q).get("items") or []
    ]
    return "ok", _truncate(json.dumps(_cut("scenarios", rows, _SCENARIOS_SEARCH_MAX_ROWS), ensure_ascii=False))


def _whole_number(value: object) -> int | None:
    """*value* as a whole number, however a model wrote it (``5``, ``"5"``, or
    ``5.0``: Gemini's arguments carry every number as a float), or None."""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _row_limit(value: object, bound: int) -> int:
    """A ``limit`` param as a row count from 1 to *bound*; *bound* when absent or not a whole number."""
    number = _whole_number(value)
    return bound if number is None else max(1, min(number, bound))


def _models_search_rows(user_key: str, params: dict) -> list[dict]:
    """Bounded rows for ``models.search``: the first *limit* (at most
    ``_MODELS_SEARCH_MAX_ROWS``) of :func:`_models_search_all`."""
    return _models_search_all(user_key, params)[:_row_limit(params.get("limit"), _MODELS_SEARCH_MAX_ROWS)]


def _models_search_all(user_key: str, params: dict) -> list[dict]:
    """Every row ``models.search`` matches: the model packages in
    *user_key*'s store, the only models its node code runs, each with the line
    that loads it, and its labels up to ``_MODEL_LABELS_MAX``, with
    ``labelsElided`` when it has more.

    A thin wrapper over the packages domain (`ADR-AG-007`), which owns the
    listing and the loader line.
    """
    from utk_curio.backend.app.packages import service as packages

    query = params.get("q")
    needle = query.strip()[:_CATALOG_PARAM_MAX_CHARS].lower() if isinstance(query, str) and query.strip() else ""
    rows = []
    for held in packages.held_model_packages(user_key):
        manifest, block = held.manifest, held.manifest.model
        publisher = block.publisher or manifest.publisher
        haystack = " ".join([manifest.name, manifest.package_id, manifest.description, publisher]).lower()
        if needle and needle not in haystack:
            continue
        rows.append({
            "id": manifest.package_id,
            "name": manifest.name,
            "task": block.type,
            "runtime": block.runtime,
            "origin": "downloaded" if held.in_store else "shipped",
            "description": (manifest.description or "")[:_CATALOG_DESC_MAX_CHARS],
            **_cut("labels", list(block.labels), _MODEL_LABELS_MAX),
            "loader": packages.model_loader_line(manifest.package_id),
        })
    rows.sort(key=lambda row: (row["origin"] != "shipped", row["name"].lower()))
    return rows


def _execute_examples_read(user_key: str, project_id: str, params: dict) -> tuple[str, str]:
    """``examples.read``: the list of worked examples, or one by key.

    The project's spec decides what is left out, by the rule the per-run block
    follows (``excluded_by``): an evaluation project never shows the example it
    is scored against, nor one that shares part of it. A project with no saved
    spec leaves nothing out.
    """
    from utk_curio.backend.app.projects import storage as projects_storage

    key = params.get("key")
    if key is not None and not isinstance(key, str):
        return "error", agent_text.message("tools.example-key-invalid")
    exclude = worked_examples.excluded_by(projects_storage.read_spec(user_key, project_id))
    if not (key or "").strip():
        return "ok", _truncate(json.dumps({"examples": worked_examples.listing(exclude=exclude)}, ensure_ascii=False))
    try:
        example = worked_examples.find(key.strip(), exclude=exclude)
    except LookupError as exc:
        return "error", str(exc)
    return "ok", _truncate(worked_examples.shown(example))


# packages.catalog bounds (dev/84): mirrors the catalog.search posture —
# plenty for ranking, small enough to never crowd the context.
_PACKAGES_CATALOG_MAX_ROWS = 40
_PACKAGES_DESC_MAX_CHARS = 200
_PACKAGES_RESOLVE_MAX_DIRNAMES = 8


def _packages_catalog_rows(user_key: str, project_id: str, params: dict) -> list[dict]:
    """Every package row the dev/84 read tool matches, each description
    bounded; the tool shows the first ``_PACKAGES_CATALOG_MAX_ROWS``. A thin
    wrapper over the packages domain's agent overview (`ADR-AG-007`: one
    truth, owned there)."""
    from utk_curio.backend.app.packages import service as packages_services

    rows = packages_services.agent_catalog_overview(user_key, project_id)
    query = params.get("q")
    if isinstance(query, str) and query.strip():
        needle = query.strip().lower()[:_CATALOG_PARAM_MAX_CHARS]
        rows = [
            r for r in rows
            if needle in f"{r['dirName']} {r['packageId']} {r['name']} {r['description']}".lower()
        ]
    return [{**r, "description": r["description"][:_PACKAGES_DESC_MAX_CHARS]} for r in rows]


def _execute_packages_resolve(user_key: str, params: dict) -> tuple[str, str]:
    """The dev/84 identify surface: real resolver output, never invented."""
    from utk_curio.backend.app.packages import service as packages_services

    dir_names = params.get("dirNames")
    if not isinstance(dir_names, list) or not dir_names or not all(
        isinstance(d, str) and d.strip() for d in dir_names
    ):
        return "error", agent_text.message("tools.dir-names-invalid")
    cleaned = [d.strip() for d in dir_names[:_PACKAGES_RESOLVE_MAX_DIRNAMES]]
    try:
        report = packages_services.agent_resolve_report(user_key, cleaned)
    except packages_services.PackageServiceError as exc:
        return "error", str(exc)
    return "ok", _truncate(json.dumps(report, ensure_ascii=False))


def _node_row(node: dict, goal_cap: int) -> dict:
    from utk_curio.backend.app.execution.code_references import (
        effective_value,
        normalize_selections,
        normalize_widgets,
    )

    content = str(node.get("content") or "")
    row = {
        "id": node.get("id"),
        "type": node.get("type"),
        "goal": str(node.get("goal") or "")[:goal_cap],
        "hasContent": bool(content.strip()),
        "contentChars": len(content),
    }
    # A node pinned to the dataflow's dashboard is one of its tiles.
    if dashboards.is_pinned(node):
        row["pinned"] = True
    # #662: the values its code reads through widget references, and the node
    # a copy was copied from; each only when there is one.
    widgets = normalize_widgets((node.get("metadata") or {}).get("widgets"))
    if widgets:
        row["widgets"] = [{"name": w["name"], "type": w["type"], "value": effective_value(w)} for w in widgets]
    # The selection tags its code reads as [!! selection <name> !!]: each
    # names its view and the column that identifies the view's rows. How many
    # ids each holds, never the ids (up to SELECTION_ID_CAP of them).
    selections = normalize_selections((node.get("metadata") or {}).get("selections"))
    if selections:
        row["selections"] = [
            {"name": tag["name"], "view": tag["node"], "column": tag["column"],
             "selected": len(tag["ids"]) if "ids" in tag else tag["count"]}
            for tag in selections
        ]
    lineage = (node.get("metadata") or {}).get("copiedFrom")
    if isinstance(lineage, list) and lineage:
        row["copiedFrom"] = [str(i) for i in lineage]
    # What its body's settings make it do, each only when it is not the
    # node's default: a Spatial Join's operation and output, a Data Pool's
    # conflict modes, a Simple View's image column.
    row.update(node_settings.saved(node.get("metadata")))
    return row


def _scenario_rows(stripped: dict) -> list[dict]:
    """#662: the dataflow's scenarios, each with what it is made of: its
    levers (its nodes), its fixed context (the nodes outside it that it reads)
    and its outcomes (what gets compared). The parts are read by the rule the
    canvas and the Scenario Catalog read them by (``scenarioParts``). A
    scenario dragged in from another project also names where it came from
    (:func:`_scenario_sources`)."""
    from utk_curio.backend.app.projects.scenarios import normalize_scenarios
    from utk_curio.backend.app.scenario_catalog.domain.parts import scenario_parts, spec_nodes_and_edges

    nodes, edges = spec_nodes_and_edges(stripped)
    raw = (stripped.get("dataflow") or {}).get("scenarios")
    scenarios = normalize_scenarios(raw, [n["id"] for n in nodes])
    sources = _scenario_sources([scenario["source"] for scenario in scenarios if "source" in scenario])
    rows = []
    for scenario in scenarios:
        parts = scenario_parts(scenario, nodes, edges)
        row = {"id": scenario["id"], "name": scenario["name"], "color": scenario["color"]}
        if scenario.get("description"):
            row["description"] = scenario["description"]
        row = {**row, "levers": parts["levers"], "context": parts["context"], "outcomes": parts["outcomes"]}
        source = scenario.get("source")
        if source is not None and (source["project"], source["scenario"]) in sources:
            row["source"] = sources[(source["project"], source["scenario"])]
        rows.append(row)
    return rows


def _scenario_sources(sources: list[dict]) -> dict[tuple[str, str], dict]:
    """Where each scenario dragged in from another project came from, by
    ``(projectId, scenarioId)``, the ids its ``source`` keeps: that project's
    and that scenario's names as they are now, ``{"project", "scenario"}``;
    ``{"project", "status": "scenario-gone"}`` when the project no longer holds
    the scenario; ``{"status": "project-gone"}`` when the project is gone or is
    none of the account's.

    Reads only the projects *sources* name, each once, as the signed-in
    account owns them (``owned_project``). dataflow.read runs on every turn, so
    with no source nothing is read, not even the request's account; with no
    signed-in account no source is named."""
    if not sources:
        return {}
    user = _request_user()
    if user is None:
        return {}
    from utk_curio.backend.app.projects.scenarios import scenario_summaries
    from utk_curio.backend.app.scenario_catalog.infrastructure import projects as scenario_projects

    held: dict[str, tuple[str, dict[str, str]] | None] = {}
    named: dict[tuple[str, str], dict] = {}
    for source in sources:
        project_id, scenario_id = source["project"], source["scenario"]
        if project_id not in held:
            try:
                row, spec, _is_example = scenario_projects.owned_project(user, project_id)
            except scenario_projects.ProjectNotFound:
                held[project_id] = None
            else:
                held[project_id] = (row.name, {s["id"]: s["name"] for s in scenario_summaries(spec)})
        project = held[project_id]
        if project is None:
            named[(project_id, scenario_id)] = {"status": "project-gone"}
        elif scenario_id in project[1]:
            named[(project_id, scenario_id)] = {"project": project[0], "scenario": project[1][scenario_id]}
        else:
            named[(project_id, scenario_id)] = {"project": project[0], "status": "scenario-gone"}
    return named


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
        # dev/125 §3.6: the edge KIND, in the plan grammar's own vocabulary and
        # with its byte-absent default (present only when "interaction"). The
        # instruction tells the builder to re-read the graph and confirm the
        # topology before claiming a repair; without this the projection could
        # not show that the feedback edge it just asked for is in fact an
        # interaction edge, so the read-back was not executable — the same
        # DEC-063 defect the plan grammar had, one layer up.
        if plan_topology.is_interaction_edge(edge):
            row["kind"] = "interaction"
        edges.append(row)
    projection = {
        "name": dataflow.get("name"),
        "goal": dataflow.get("task"),
        "nodes": [_node_row(n, goal_cap=200) for n in nodes_raw],
        "edges": edges,
        "datasets": dataflow.get("datasets") or [],
        "runtime": runtime_journal.status_map(user_key, project_id),
    }
    scenarios = _scenario_rows(stripped)
    if scenarios:
        projection["scenarios"] = scenarios
    if len(json.dumps(projection, ensure_ascii=False)) > TOOL_RESULT_MAX_CHARS:
        projection["nodes"] = [_node_row(n, goal_cap=40) for n in nodes_raw]
        projection["elided"] = agent_text.message("tools.goals-shortened")
    return projection


def _resolve_node_id(target: dict | None, params: dict) -> str | None:
    node_id = params.get("nodeId")
    if isinstance(node_id, str) and node_id:
        return node_id
    if isinstance(target, dict) and target.get("kind") == "node":
        return target.get("targetId")
    return None


#: node.history.read bounds: the newest entries a list shows, and the most of
#: one entry's code, and of the code it replaced, that a read gives.
_NODE_HISTORY_MAX_ENTRIES = 40
_NODE_HISTORY_CODE_MAX_CHARS = 12_000


def _cut_text(key: str, text: str, bound: int) -> dict:
    """``{key: the first *bound* characters of text}``, and, when it left
    characters out, ``{key}Elided``: how many, first, as :func:`_cut` says of
    rows."""
    payload: dict = {}
    if len(text) > bound:
        payload[f"{key}Elided"] = len(text) - bound
    payload[key] = text[:bound]
    return payload


def _history_row(record: dict) -> dict:
    """One entry of a node's history as node.history.read lists it: its id and
    parent, run or edit, an edit's label (whoever made it, or what it
    changed), when it started and ended, the kinds of data it read and
    returned, and how long its code is."""
    edit = record.get("kind") == "edit"
    row: dict = {"id": record.get("id"), "parentId": record.get("parentId"), "kind": "edit" if edit else "run"}
    if edit and isinstance(record.get("label"), str):
        row["label"] = record["label"]
    code = record.get("code")
    return {
        **row,
        "startTime": record.get("startTime"),
        "endTime": record.get("endTime"),
        "inputs": record["inputs"] if isinstance(record.get("inputs"), list) else [],
        "outputs": record["outputs"] if isinstance(record.get("outputs"), list) else [],
        "codeChars": len(code) if isinstance(code, str) else 0,
    }


def _execute_node_history_read(spec: dict, target: dict | None, params: dict) -> tuple[str, str]:
    """``node.history.read``: a node's entries, newest first, or with
    ``entryId`` that entry's code, from the saved dataflow's
    ``nodeProvenance``, keyed by node id as a load keys it
    (``projects/node_provenance``, the twin of ``utils/nodeProvenanceKeys.ts``)."""
    from utk_curio.backend.app.projects.node_provenance import rekey_node_provenance

    node_id = _resolve_node_id(target, params)
    if not node_id:
        return "error", agent_text.message("tools.no-node-id")
    nodes = [n for n in (spec.get("dataflow") or {}).get("nodes") or [] if isinstance(n, dict)]
    if not any(n.get("id") == node_id for n in nodes):
        return "error", agent_text.message("tools.node-not-in-spec", node_id=repr(node_id))
    saved = spec.get("nodeProvenance")
    keyed = rekey_node_provenance(saved if isinstance(saved, dict) else {}, [str(n.get("id")) for n in nodes])
    records = sorted(
        (record for record in keyed.get(node_id) or [] if isinstance(record, dict)),
        key=lambda record: _whole_number(record.get("id")) or 0,
        reverse=True,
    )
    if not records:
        note = agent_text.message("tools.node-history-none", node_id=repr(node_id))
        return "ok", json.dumps({"nodeId": node_id, "entries": [], "note": note}, ensure_ascii=False)
    asked = params.get("entryId")
    if asked is None:
        rows = [_history_row(record) for record in records]
        return "ok", _truncate(json.dumps(
            {"nodeId": node_id, **_cut("entries", rows, _NODE_HISTORY_MAX_ENTRIES)}, ensure_ascii=False,
        ))
    entry_id = _whole_number(asked)
    record = next((r for r in records if entry_id is not None and _whole_number(r.get("id")) == entry_id), None)
    if record is None:
        return "error", agent_text.message("tools.node-history-no-entry", node_id=repr(node_id), entry_id=repr(asked))
    payload = {
        "nodeId": node_id,
        "entry": _history_row(record),
        **_cut_text("code", str(record.get("code") or ""), _NODE_HISTORY_CODE_MAX_CHARS),
    }
    # An edit whose parent does not hold the code it replaced holds it itself.
    if isinstance(record.get("before"), str):
        payload.update(_cut_text("before", record["before"], _NODE_HISTORY_CODE_MAX_CHARS))
    return "ok", _truncate(json.dumps(payload, ensure_ascii=False))


def _discovery_service():
    """The discovery service for the acting user.

    Thin wrapper over the discovery domain (`ADR-AG-007`), the same way
    ``_catalog_search_rows`` wraps the datasets one: the user rides the request
    context, and the service is the same one the Discovery Catalog pages use.
    """
    from flask import g

    from utk_curio.backend.app.discovery.service import DiscoveryService
    from utk_curio.backend.app.projects.services import _user_dir_key

    user = getattr(g, "user", None)
    return DiscoveryService(
        _user_dir_key(user) if user is not None else None, user=user
    )


def _portal_rows(sources) -> list[dict]:
    """The portals among *sources*. Storage and service sources are added from
    the Discovery Catalog page, where a row can be narrowed and a service's area
    is set, so no agent tool offers them; a model source adds models, not data."""
    return [s for s in sources or [] if s.get("kind") not in ("storage", "service", "model")]


def _discovery_source_rows() -> list[dict]:
    """The roster. Disk only - no portal is contacted."""
    listing = _discovery_service().list_catalog()
    rows = []
    for source in _portal_rows(listing.get("sources"))[:_DISCOVERY_MAX_ROWS]:
        auth = source.get("auth") or {}
        rows.append(
            {
                "sourceId": source.get("dirName"),
                "name": source.get("name"),
                "provider": source.get("provider"),
                "publisher": source.get("publisher"),
                "description": (source.get("description") or "")[:_DISCOVERY_DESC_MAX_CHARS],
                "formats": (source.get("capabilities") or {}).get("formats") or [],
                "searchable": bool((source.get("capabilities") or {}).get("search")),
                # Whether a token will be sent, never the token. A model that
                # knows a source is unusable can say so instead of proposing it.
                "credentialReady": not auth.get("required") or bool(auth.get("present")),
            }
        )
    return rows


def _discovery_search_rows(params: dict) -> list[dict]:
    def _param(name: str) -> str | None:
        value = params.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_CATALOG_PARAM_MAX_CHARS]
        return None

    service = _discovery_service()
    query = _param("q") or ""
    source_id = _param("sourceId")
    fmt = _param("format")
    if source_id:
        from utk_curio.backend.app.discovery.domain.errors import DiscoveryError

        try:
            manifest = service.get_manifest(source_id)
            storage = manifest.is_storage or manifest.is_service or manifest.is_model
        except DiscoveryError:
            storage = False
        if storage:
            return [], [{"sourceId": source_id, "status": "unsupported"}]
        payload = service.search_source(
            source_id, q=query, fmt=fmt, limit=_DISCOVERY_MAX_ROWS
        )
    else:
        payload = service.search_all(
            q=query, fmt=fmt, limit=_DISCOVERY_MAX_ROWS, include_storage=False
        )
    rows = []
    for row in (payload.get("resources") or [])[:_DISCOVERY_MAX_ROWS]:
        rows.append(
            {
                "sourceId": row.get("sourceId"),
                "sourceName": row.get("sourceName"),
                "resourceId": row.get("resourceId"),
                "name": row.get("name"),
                "publisher": row.get("publisher"),
                "description": (row.get("description") or "")[:_DISCOVERY_DESC_MAX_CHARS],
                "formats": row.get("formats") or [],
                "updatedAt": row.get("updatedAt"),
                "alreadyInDataCatalog": bool(row.get("alreadyHeldDatasetId")),
            }
        )
    # The per-source statuses ride along: a model told that one portal did not
    # answer can say so, instead of reporting a short list as the whole truth.
    return rows, [
        {"sourceId": leg.get("sourceId"), "status": leg.get("status")}
        for leg in (payload.get("sources") or [])
        if leg.get("status") != "ok"
    ]


def discovery_sources_contacted(params: dict) -> int:
    """How many portals a ``discovery.search`` with these params will contact.

    The budget is charged per portal, so a fan-out costs what it costs. Counted
    here rather than assumed to be one: charging a fan-out a single tick would
    let one tool call issue five requests against a budget of four.
    """
    source_id = params.get("sourceId")
    if isinstance(source_id, str) and source_id.strip():
        return 1
    try:
        listing = _discovery_service().list_catalog()
    except Exception:  # noqa: BLE001 - a count must never fail a run
        return 1
    return max(
        1,
        sum(
            1
            for s in _portal_rows(listing.get("sources"))
            if (s.get("capabilities") or {}).get("search")
        ),
    )


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
    from utk_curio.backend.app.agents.repositories import project_agents
    from utk_curio.backend.app.projects import storage as projects_storage

    try:
        # dev/67-4: the web tools need no project spec — handled first.
        if tool_id == "web.fetch":
            return _execute_web_fetch(params)
        if tool_id == "web.search":
            return _execute_web_search(params)
        # dev/84: the package tools read through the packages domain (which
        # does its own project/lockfile reads) — handled before the spec read.
        # The discovery tools read the discovery domain, which does its own
        # manifest reads - handled before the project spec read, like the
        # package tools below.
        if tool_id == "discovery.sources":
            return "ok", _truncate(
                json.dumps({"sources": _discovery_source_rows()}, ensure_ascii=False)
            )
        if tool_id == "discovery.search":
            rows, unavailable = _discovery_search_rows(params)
            payload = {"resources": rows}
            if unavailable:
                payload["unavailableSources"] = unavailable
            return "ok", _truncate(json.dumps(payload, ensure_ascii=False))
        if tool_id == "models.search":
            payload = _cut(
                "models", _models_search_all(user_key, params),
                _row_limit(params.get("limit"), _MODELS_SEARCH_MAX_ROWS),
            )
            return "ok", _truncate(json.dumps(payload, ensure_ascii=False))
        if tool_id == "examples.read":
            return _execute_examples_read(user_key, project_id, params)
        if tool_id == "packages.catalog":
            rows = _packages_catalog_rows(user_key, project_id, params)
            return "ok", _truncate(json.dumps(_cut("packages", rows, _PACKAGES_CATALOG_MAX_ROWS), ensure_ascii=False))
        if tool_id == "packages.resolve":
            return _execute_packages_resolve(user_key, params)
        if tool_id == "scenarios.search":
            return _execute_scenarios_search(project_id, params)
        spec = projects_storage.read_spec(user_key, project_id)
        if spec is None:
            return "error", agent_text.message("mint.no-saved-spec")
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
                return "error", agent_text.message("tools.no-node-id")
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
            if node is None:
                return "error", agent_text.message("tools.node-not-in-spec", node_id=repr(node_id))
            return "ok", _truncate(json.dumps(node, ensure_ascii=False))
        if tool_id == "node.runtime.read":
            from utk_curio.backend.app.execution import runtime_journal

            node_id = _resolve_node_id(target, params)
            if not node_id:
                return "error", agent_text.message("tools.no-node-id")
            nodes = (spec.get("dataflow") or {}).get("nodes") or []
            node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == node_id), None)
            if node is None:
                return "error", agent_text.message("tools.node-not-in-spec", node_id=repr(node_id))
            # dev/137: two origins describe two different things about one node
            # — what its CODE did and what its RENDER drew. The run leads when
            # there is one; a grammar node has only its render; and a code node
            # that also rendered carries both, because a run that passed can
            # still have drawn nothing (dev/136).
            record = runtime_journal.read_record(user_key, project_id, node_id)
            render = runtime_journal.read_render_record(user_key, project_id, node_id)
            if record is None and render is None:
                return "ok", json.dumps(
                    {"nodeId": node_id, "status": "never-executed"}, ensure_ascii=False
                )
            record = dict(record or render or {})
            if record is not None and render is not None and (
                runtime_journal.read_record(user_key, project_id, node_id) is not None
            ):
                record["render"] = render
            executed_sha = record.get("executedCodeSha256")
            current_sha = runtime_journal.normalized_code_sha256(str(node.get("content") or ""))
            # Best-effort staleness signal: the run predates the current content.
            record["contentChangedSinceRun"] = bool(executed_sha) and executed_sha != current_sha
            return "ok", _truncate(json.dumps(record, ensure_ascii=False))
        if tool_id == "node.history.read":
            return _execute_node_history_read(spec, target, params)
        if tool_id == "catalog.search":
            rows = _catalog_listing_rows(user_key, project_id, params)
            return "ok", _truncate(json.dumps(_cut("datasets", rows, _CATALOG_SEARCH_MAX_ROWS), ensure_ascii=False))
        return "error", agent_text.message("tools.unknown-read-tool", tool_id=repr(tool_id))
    except Exception as exc:  # tool failures are data, never run errors
        return "error", agent_text.message("tools.tool-failed", exc=exc)


# web.fetch preview bound: enough to judge an API's shape, small enough to
# never crowd the context (the tool-result cap still applies on top).
_WEB_BODY_PREVIEW_MAX_CHARS = 4000
_WEB_SEARCH_MAX_ROWS = 8


def _execute_web_fetch(params: dict) -> tuple[str, str]:
    """dev/67-4 (DEC-053): one policy-gated fetch, framed as bounded data."""
    from utk_curio.backend.app.agents.infrastructure import egress

    url = params.get("url")
    if not isinstance(url, str) or not url.strip():
        return "error", agent_text.message("tools.url-required")
    try:
        result = egress.fetch(url.strip())
    except egress.EgressRefused as exc:
        return "error", f"{agent_text.message("tools.egress-refused")}: {exc}"
    except Exception as exc:
        return "error", agent_text.message("tools.endpoint-unreachable", exc=exc)
    return "ok", _truncate(json.dumps({
        "url": result.url,
        "finalUrl": result.final_url,
        "status": result.status,
        "contentType": result.content_type[:100],
        "bodyPreview": result.body[:_WEB_BODY_PREVIEW_MAX_CHARS],
        "truncated": result.truncated or len(result.body) > _WEB_BODY_PREVIEW_MAX_CHARS,
    }, ensure_ascii=False))


def _execute_web_search(params: dict) -> tuple[str, str]:
    """Web search - ``CURIO_SEARCH_URL`` is a URL template with ``{q}``
    (GET; any API key rides the URL) returning JSON. Unset, it falls back to
    :data:`DEFAULT_SEARCH_URL`, so search works without configuration.

    Accepted response shapes (dev/90 A3 — the common public search APIs over
    a plain keyed GET, so no provider server is ever required): a top-level
    list, or rows under ``results`` (SearXNG), ``organic_results`` (SerpAPI,
    SearchApi.io), ``items`` (Google Programmable Search), or
    ``web.results`` (Brave-shaped proxies); row fields ``title``,
    ``url|link|href``, ``snippet|content|description``. Header-authenticated
    APIs are NOT supported — the contract is key-in-URL, stated honestly.
    DuckDuckGo's ``RelatedTopics`` is handled too, since that is the default.
    Results flow through the egress policy either way; the provider host is
    trusted because configuration (or this module's default) named it, never
    because a model asked for it."""
    import os
    from urllib.parse import quote

    from utk_curio.backend.app.agents.infrastructure import egress

    query = params.get("q")
    if not isinstance(query, str) or not query.strip():
        return "error", agent_text.message("tools.query-required")
    template = os.environ.get("CURIO_SEARCH_URL") or DEFAULT_SEARCH_URL
    if "{q}" not in template:
        return "error", agent_text.message("tools.search-not-configured", q="{q}")
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
        return "error", f"{agent_text.message("tools.egress-refused")}: {exc}"
    except Exception as exc:
        return "error", agent_text.message("tools.search-provider-failed", exc=exc)
    rows_raw = _search_rows_of(payload)
    rows = []
    for row in (rows_raw or [])[:_WEB_SEARCH_MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        rows.append({
            "title": str(row.get("title") or "")[:160],
            "url": str(row.get("url") or row.get("link") or row.get("href") or "")[:300],
            "snippet": str(row.get("snippet") or row.get("content")
                           or row.get("description") or "")[:300],
        })
    return "ok", _truncate(json.dumps({"results": rows}, ensure_ascii=False))


#: Where ``web.search`` looks when the deployment names no provider.
#:
#: DuckDuckGo's Instant Answer API needs no key and no signup, so an install
#: nobody configured still has a working search tool. Two honest caveats: it
#: returns instant-answer topics rather than ranked web results, so coverage
#: is thinner than a real search API; and, like any default endpoint, a query
#: reaches a third party. That is narrower than it sounds - the tool runs only
#: when a user runs an agent that declares a search capability, never on its
#: own - but an operator who wants somewhere else (a local SearXNG, SerpAPI,
#: Google Programmable Search) sets ``CURIO_SEARCH_URL`` or
#: ``--agent-search-url``.
DEFAULT_SEARCH_URL = "https://api.duckduckgo.com/?q={q}&format=json&no_html=1"


def _search_rows_of(payload) -> list | None:
    """The result rows of one provider response."""
    if not isinstance(payload, dict):
        return payload if isinstance(payload, list) else None
    for key in ("results", "organic_results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    web = payload.get("web")
    if isinstance(web, dict) and isinstance(web.get("results"), list):
        return web["results"]
    related = payload.get("RelatedTopics")
    if isinstance(related, list):
        return _duckduckgo_rows(related)
    return None


def _duckduckgo_rows(related: list) -> list:
    """Flatten DuckDuckGo's ``RelatedTopics`` into the common row shape.

    The default provider answers in its own format: a flat list of
    ``{FirstURL, Text}``, interleaved with category groups that nest the same
    thing under ``{Name, Topics}``. One level of nesting is all the API
    produces, so this flattens exactly one level rather than recursing.

    ``Text`` is a single string that leads with the title, so it serves as
    both title and snippet; the title is clipped at the first sentence-like
    break so a card is not the whole paragraph twice over.
    """
    rows: list = []
    for entry in related:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("Topics")
        if isinstance(nested, list):
            rows.extend(
                item for item in nested
                if isinstance(item, dict) and item.get("FirstURL")
            )
        elif entry.get("FirstURL"):
            rows.append(entry)
    out = []
    for row in rows:
        text = str(row.get("Text") or "")
        title = text.split(" - ", 1)[0] if " - " in text else text
        out.append({"title": title, "url": row.get("FirstURL"), "snippet": text})
    return out
