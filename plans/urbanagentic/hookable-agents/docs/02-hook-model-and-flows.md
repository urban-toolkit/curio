# Hook Model And Attachment Flows

## Hook Targets

Agents attach to explicit targets. A target declares what it is and what context it can expose.

| Hook target | Examples | Context exposed |
| --- | --- | --- |
| Data Load node | CSV load, database load, API fetch | source, schema, preview, region, upstream lineage |
| Analysis node | Python, JS, transform, statistics | code, inputs, outputs, errors, lineage |
| Visualization node | Map, chart, dashboard, HTML widget | data bindings, encoding, view state |
| Connection | edge between two nodes | source type, target type, data contract |
| Canvas | full dataflow | mission, graph, selected region, all nodes, run state |
| Data catalog | dataset listing | dataset metadata, provenance, permissions |
| Document source | PDF, web page, report | extracted text, citations, source metadata |

## Attachment Rule

An agent can attach only when one of its compatible hooks matches the selected or hovered target.

```text
agent.compatibleTargets includes target.kind
```

The UI should make compatible targets glow lightly during drag or attach mode. Incompatible targets should stay neutral and optionally show `Not compatible` on hover.

## Flow 1: Dataset Finder To Data Load Node

Purpose: help a user find the right urban datasets for a loading step.

1. User explicitly chooses `Install in project` for `Dataset Finder` from Global Catalog or My
   Imports if needed, then drags its template from the active project's AGENTS palette.
2. Compatible Data Load nodes show a green hook indicator.
3. User attaches it to `Load climate + census data`.
4. A `Dataset Finder` tile appears in the node's attached-agent dock.
5. Opening the tile shows the attachment's unified chat with suggested external dataset APIs, public data portals, endpoints, and catalog sources.
6. User reviews source candidates and selects one.
7. The selected source populates the Data Load node input.
8. The user can run the node or continue configuring joins and schema fields.

Review policy: always confirm before adding or replacing datasets.

## Flow 2: Node Explainer To A Node

Purpose: make an existing node explainable and inspectable.

1. User explicitly chooses `Install in project` for `Node Explainer` if needed, then drags its
   template from the active project's AGENTS palette.
2. Compatible nodes show a blue hook indicator.
3. User attaches it to `Compute vulnerability index`.
4. A `Node Explainer` tile appears in the node's attached-agent dock.
5. Clicking the tile opens that attachment's unified chat.
6. User refines explanation style and intent through chat turns. The chat-header
   `Attachment settings` cog opens the shared settings modal for effective policy and prompt
   provenance without replacing the conversation. Prompt authoring remains on an owned imported
   definition, not the attachment.

The built-in node **Explanation** tab, its direct explanation request, and its node-store
explanation cache are retained permanently (`DEC-041`, `dev/18` — the former removal is
cancelled). `Node Explainer` attached-agent chat is a coexisting node-explanation workflow.

Review policy: no destructive changes; can generate explanation text and suggestions.

## Flow 3: Dataflow Builder To Canvas (master orchestration)

Purpose: orchestrate a full agentic dataflow from a mission. The Dataflow Builder is
the **master orchestrator** — it plans, spawns specialized agents, coordinates them,
evaluates progress, and delivers an executable dataflow (see `09-agent-architecture`).

1. User explicitly installs `Dataflow Builder` in the active project if needed, then drags its
   template from that project's AGENTS palette.
2. The whole canvas shows an orange canvas-level hook boundary.
3. User attaches it to the canvas; it opens in the unified chat drawer.
4. It states its **initial intent**, then posts an **execution plan** (subtasks).
5. It delegates to installed specialized agents (Dataset Finder, Node Builder, Connection Builder,
   Package Recommendation, Validation, Optimization, Dataflow Explainer) and shows each one's
   **status** (queued / running / interrupted / done). If a required specialist is missing,
   it presents a reviewed `Install in project` proposal; it never silently imports, installs, attaches,
   grants permissions, executes, or publishes an agent.
6. It merges intermediate outputs, evaluates coherence, refines if needed, and presents
   the final dataflow with recommendations and explanations.

Review policy: confirm plan changes before altering the graph.

## Attached-Agent Visibility

Attached agents should remain visible after connection.

Node-level agents:

```text
Node card
  content
  attached-agent dock (compact square, icon-only tiles; hover shows the name)
```

Canvas-level agents:

```text
Canvas agent dock
  Dataflow Builder
  Evaluator
  Dataflow Explainer
```

## Refinement (unified chat plus shared settings)

Conversational refinement, suggestions, reviews, and execution happen through one unified chat
drawer shared by every attached agent. Clicking an attached-agent dock tile opens that
attachment's **chat session**,
keyed by immutable `attachmentId`, showing the history of what that agent attachment has
done on that node. The header carries previous/next arrows to move through all attached
agents in the dataflow and a clearly labeled `Attachment settings` cog. Suggestions, lightweight
behaviour choices, previews, and results remain chat turns; the transcript is execution/run
history. Cross-agent cost, quota, resource, prompt quality, prompt editing, and prompt auditing
use the shared settings modal rather than bespoke agent panels. See `08-unified-agent-chat.md`.

Each attachment is a private project/target derivation identified by `attachmentId` plus a
concurrency `revision`. It references `projectAgentTemplateId` and has no SemVer, release,
catalog, Publish, or Share identity. Each execution privately pins the resolved definition digest,
project-settings revision, attachment revision, prompt digest, provider-profile revision, and
effective-policy snapshot without turning the attachment into a versioned artifact.
The project AGENTS palette contains only `ProjectAgentTemplate` records for the active project;
switching projects replaces its rows and clears mismatched attachment navigation, settings drafts,
streams, and sessions. Rows stay action-free; `Project agent settings` and `Uninstall from project`
remain on Installed in this project drawer details.

When a flow/Trill is shared, agent-private data is not exposed in the shared result. Recipients
never see datasets, packages/code, definitions/imports/project templates/attachments, agent
flows/docks, settings, prompts, evaluations/audits, transcripts/history, providers/tools,
usage/cost, or private IDs; agents are omitted entirely.

Attachments are visually indistinguishable and differ only by agent type, configuration,
and chat history.

## Agent Settings Flow

The shared shell has four applicability scopes and no palette-row action:

1. An `Agent settings` cog in the Agents Catalog header opens account policy/defaults.
2. `Definition settings for <agent>` on an owned **My Imports** definition enables Prompt Editor, Prompt
   Quality, and Prompt Audit. Release creates a new private definition artifact; Install and
   Publish remain separate explicit actions.
3. `Project agent settings` on **Installed in this project** enables Cost, Quotas, and Resource
   policies for that project template. Prompt screens are provenance/evidence read-only and no
   Publish or Release action exists.
4. `Attachment settings` enables downward-only Cost, Quotas, and Resource overrides. Prompt
   source/evidence is read-only; the instance cannot be versioned, released, published, or shared.
5. The draggable project AGENTS palette row remains dedicated to selection and attachment.

The modal has six dedicated screens: **Cost**, **Quotas**, **Resource policies**, **Prompt
quality**, **Prompt editor**, and **Prompt audit**. It shows the applicable account, imported
definition, project template, or attached instance scope, effective values, inherited values, and
the source of each locked limit. Server-returned
capabilities determine whether a screen is editable, read-only, or unavailable; the client does
not infer permissions from ownership labels.

Cost, quota, and resource policy are mutable records outside the immutable manifest. The server
computes and enforces the effective policy from deployment, account, project-template, attachment,
and execution scopes. An exact artifact's schema-validated manifest `settingsDefaults` are only
immutable seed suggestions. Every explicit project install materializes a distinct project-private,
revisioned per-agent profile; another project installing the same definition receives independent
settings and its palette updates independently. `Reset to agent default` resets only the selected
project template while re-clamping current deployment/account ceilings; attachment overrides only
tighten. Prompt editing creates a revisioned draft from an owned imported definition. Quality
evaluation pins the draft/artifact, suite version, and any approved evaluator; releasing creates
a new private imported-definition artifact rather than changing a project template or attachment.
Prompt Audit pins a
versioned privacy/security/compliance rule set, records findings, and appends governance events; it
is not a second transcript/history surface.

The dialog traps focus, supports keyboard navigation and zoom/reflow, announces save and
evaluation state, restores focus to its opening cog, and guards dirty drafts before close or
scope changes. The shared result exposes no settings entry point and cannot enumerate private
projects, settings, prompts, evaluations, or audit events.
