# Consolidated Plan

## Product Thesis

Urban Agentic should be an agentic dataflow builder for urban analysis. The user gives Curio an urban mission, and Curio helps plan, revise, solve, evaluate, and explain an editable dataflow.

Reusable agents are the building blocks. They are not isolated chatbots. They attach to specific Curio contexts such as datasets, nodes, the canvas, lineage, code, outputs, or external sources.

```text
Urban mission
  -> reusable agents
  -> hookable Curio targets
  -> editable dataflow
  -> evaluation and explanation loop
```

## Product Direction

The immediate UI direction is a catalog of reusable agents that can be attached to a dataflow.

The catalog should help users answer:

- What can this agent do?
- Where can I attach it?
- What context can it read?
- What can it change?
- What needs review before it acts?
- What will it cost, which quotas apply, and which resources may it use?
- Which prompt version was evaluated, edited, released, or audited?

The canvas should help users answer:

- Which agents are attached?
- Which node or canvas area are they attached to?
- Which agent is currently selected?
- What happens if I refine or run the agent?

## Core Building Blocks

| Agent | Primary hook | Purpose |
| --- | --- | --- |
| **Dataflow Builder** | Canvas | **Master orchestrator** — interpret the user's intent, decompose it into subtasks, spawn and coordinate the specialized agents below, evaluate progress, and produce a complete, executable dataflow. |
| Dataset Finder | Data Load node | **Discover + select** relevant datasets (external sources + Data Catalog). External picks hand off to Node Builder; catalog picks reuse the dataset-only install flow. It never authors fetch code. |
| Node Builder | Canvas or selected connection | Create computation, transform, visualization, or HTML nodes — **including the executable dataset-fetch node** for an external source selected in Dataset Finder (request code, params, auth, parsing, error handling, output). |
| Connection Builder | Canvas or selected nodes | Suggest and create valid dataflow connections. |
| Package Recommendation | Node or canvas | Recommend packages that fit the task. |
| Validation | Node or full canvas | Check code, coherence, data types, outputs, and assumptions. |
| Optimization | Canvas | Improve performance and structure of the graph. |
| Node Explainer | Any compatible node with code, output, or provenance | An agent-based node-explanation workflow: install its project template, attach it, then explain through unified agent chat. It coexists with the retained built-in node Explanation tab (`DEC-041`, `dev/18` — the former removal is cancelled). |

The Dataflow Builder no longer recommends isolated resources itself; it **orchestrates**
the specialized agents. See `09-agent-architecture.md` for the definition-vs-assignment
split (LangChain implementation vs UI) and the orchestration flow, and
`10-prompt-architecture.md` for how current prompts become manifest-defined hookable agents.

## Agent Manifest

Each agent is a **manifest** — a single structured definition that the catalog,
palette, attachment, and refinement UIs all read from. It captures purpose,
roles, prompt assets, compatible attachment targets, inputs, outputs, configuration options,
runtime behavior, provider requirements, and static provenance:

```json
{
  "id": "agent.dataset-finder",
  "name": "Dataset Finder",
  "category": "data",
  "version": "1.0.0",
  "purpose": "Discover and select relevant datasets.",
  "roles": ["dataset-discovery"],
  "capabilities": [{ "id": "dataset.discover", "contractVersion": "1" }],
  "delegatesTo": ["agent.node-builder"],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>" },
    "instruction": { "path": "prompts/instruction.txt", "sha256": "<sha256>" }
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["data-loading"] }],
  "inputs": { "reads": ["mission", "nodeContext"], "requiredConfig": ["geography"] },
  "outputs": ["datasetCandidates"],
  "configuration": { "options": [], "defaults": {} },
  "runtime": { "execution": "background", "reviewPolicy": "review-before-apply" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

Account import ownership, global publication, project installation, attachment, session, and
execution status are separate records joined into UI read models; they are not written into the
immutable manifest.
The canonical manifest serialization uses camelCase JSON field names. Semantic capabilities
describe what the artifact can do; they are discovery and compatibility metadata, not permission
grants. Context reads, provider use, tool access, and mutations are authorized independently.

The Agents drawer separates **Global Catalog**, **My Imports**, and **Installed in this project**.
Importing a validated manifest creates only an account-private reusable definition in My Imports;
it never installs into the open project or publishes. Explicit `Install in project` creates a
`ProjectAgentTemplate` and that project's palette entry. Only an owned, validated My Imports
definition exposes the user `Publish` action. Built-ins, global items, project templates, and
attached instances cannot be user-republished. Publish and Install remain independent commands.
The draggable AGENTS palette is populated only from the active project's templates; switching
projects replaces the palette and clears mismatched template/settings/attachment/session state.
Palette rows remain action-free, with project settings/uninstall on the installed drawer detail.

An attached instance is a private configured project/target derivation identified by
`attachmentId` plus an optimistic concurrency `revision`. It references its project template but
has no SemVer, catalog/release identity, Publish, or Share lifecycle. Each execution—not the
attachment UI—persists the resolved source digest, project-settings revision, attachment revision,
prompt digest, provider-profile revision, and effective policy for reproducibility. See
`11-agent-manifest-and-product-model.md` for the full lifecycle.

Sharing never projects the live project or private resources; agent-private data is not exposed in
the shared result. Datasets, node packages/code, definitions, imports, project installations,
attachments/docks, agent flows, settings, prompts, quality/audit evidence, transcripts/history,
providers, tools, usage/cost, and private account/project/storage IDs never appear in the shared
result.

Imported agent packages are hostile archives: bounded private staging, contained regular-file
extraction, full schema/digest validation, and atomic visibility are required. Agent/model/tool
rich content is likewise untrusted and reaches the UI only through one allowlist renderer with
active HTML and unsafe URL/embed behavior disabled.

## Agent Settings And Prompt Governance

All agents use one shared `Agent settings` modal shell with six dedicated, labeled screens:

1. **Cost** — per-run and rolling monetary budgets, alerts, and clearly distinguished
   estimated versus provider-reported usage.
2. **Quotas** — execution, token, tool-call, concurrency, and rate-window limits with reset
   information.
3. **Resource policies** — allowed provider profiles/models, Local versus Remote processing,
   context/output bounds, timeouts, tools, and egress constraints.
4. **Prompt quality** — versioned validation suites, rubrics, thresholds, evaluation runs,
   findings, usage, and status.
5. **Prompt editor** — owner-authorized editing in a draft derived from an exact artifact;
   saving never mutates immutable source-artifact bytes.
6. **Prompt audit** — versioned privacy/security/compliance rules and findings plus append-only,
   access-controlled governance history for prompt changes, evaluations, releases, activations,
   and publication events. This is distinct from the chat transcript, which remains execution
   history.

A labeled `Agent settings` cog in the drawer opens account policy. `Project agent settings` on a
project-installed template opens that project's per-agent defaults; its prompt screens are
source-provenance/evidence read-only. An owned My Imports `Definition settings for <agent>` cog
opens Prompt Editor, Prompt Quality, and Prompt Audit for the reusable definition and is the only
user scope that can Release; the separate definition-detail `Publish` action remains eligibility-
controlled. `Attachment settings` opens downward-only runtime overrides; its prompt source/
evidence is read-only and it has no Release/Version/Publish/Share actions. Project palette rows
remain action-free. Shared results expose no settings controls or private settings/governance data.

Effective runtime policy is calculated server-side from deployment hard limits, account policy,
project-template defaults, attachment overrides, and an execution reservation. Lower scopes may
narrow inherited limits but cannot bypass them. There is no generic/global agent preset: an exact
definition's immutable, validated manifest `settingsDefaults` are seed suggestions, and every
explicit project install materializes a separate project-private revisioned profile. Installing
the same definition in another project produces another profile. `Reset to agent default`
reapplies those seeds under the deployment/account ceilings currently in force without changing
another project or attachment. Attachment overrides only tighten the selected project profile.
Prompt changes on an owned imported definition follow a draft → validate →
evaluate → audit → release flow; release creates a new immutable artifact coordinate, and an
explicit project-template update or attachment migration is required. Existing project templates
and instances never change implicitly.

## Relationship To Agentic Dataflows

Agentic dataflows are compositions produced by attached agents.

Examples such as Climate Resilience Analysis, Mobility Access Study, and Displacement Risk Monitor remain useful as mission templates. They should not replace the fine-grained Agents Catalog. Instead, templates can preselect and configure a set of reusable agents.

```text
Mission template -> suggested agent set -> attached agents -> editable dataflow
```

## Recommended First Release

The first release should focus on three attachment cases:

- Attach Dataset Finder to a Data Load node.
- Attach Node Explainer to a node.
- Attach Dataflow Builder to the canvas.

These three cases prove the hook model across data, node, and whole-dataflow contexts.
The same release should establish the shared settings shell and server-enforced cost, quota,
resource, prompt-draft, evaluation, and audit contracts so later agents do not invent their own
configuration surfaces.
