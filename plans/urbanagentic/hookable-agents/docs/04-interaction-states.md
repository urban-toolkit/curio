# Interaction States

## Default View

The user sees the Agents drawer and current project/dataflow. No agent is being attached or edited.

Expected UI:

- `Global Catalog`, `My Imports`, and `Installed in this project` are visibly distinct
- the AGENTS palette contains only the active project's installed templates
- dataflow nodes are unchanged
- node tabs and keyboard order keep the built-in `Explanation` tab in its existing position (`DEC-041` — the former removal is cancelled)
- no refinement sidebar is open unless an attached-agent dock tile is selected

## Attachment Preview

The user selects or drags a template from the active project's AGENTS palette.

Expected UI:

- compatible targets show hook indicators
- incompatible targets remain neutral
- a lightweight attachment path points from the project palette row to the target
- the target label clarifies what can be attached

## Attached-Agent Visible State

The agent has been connected.

Expected UI:

- the attached agent appears as a **dock tile** (macOS Dock pattern) beneath the target node
- the tile is a compact square showing only the bot-head icon; the name appears in a hover tooltip
- the tile remains visible after selection changes
- multiple agents stack as square tiles in the node's dock
- the instance is private and shows no SemVer, Publish, Share, or Release action

## Attached-Agent Selected / Hover State

The user hovers or opens an attached-agent dock tile.

Expected UI:

- the tile magnifies (with neighbour falloff) and shows the agent name tooltip
- a running dot marks active agents
- a subtle relation line connects the opened tile to its chat drawer
- the target node is lightly highlighted; the chat header matches the agent

## Chat Session Open State

The selected agent's chat session is open in the unified drawer.

Expected UI:

- the drawer shows the agent identity, attached target, and session id
  (`node · agent · project`), with previous/next arrows to move between attachments and a
  labeled `Attachment settings` cog
- the transcript shows what the agent has done on this node (the run history)
- the user refines by chatting; suggestions, behaviour config, previews, and results
  appear as inline chat turns
- creation/changes are explicit chat actions (review before apply)
- closing returns to the Agent Catalog; re-opening the dock tile resumes the same session

Conversational refinement remains in chat. Cost, quota, resource policy, prompt quality, prompt
editing, and prompt auditing open in the shared settings modal; they are not encoded as transcript
turns or bespoke per-agent chat panels.

Every attached agent uses this same chat drawer; they differ only by agent type,
configuration, and history. See `08-unified-agent-chat.md`.

## Agent Settings Modal Open State

The user opens the shared modal from drawer `Agent settings`, My Imports `Definition settings for
<agent>`, project-template `Project agent settings`, or chat-header `Attachment settings`. Project
palette rows remain action-free.

Expected UI:

- the dialog header names `Account policy`, `Imported definition`, `Project agent default`, or
  `Attached instance`, with definition version/project/target only where applicable and authorized
- six labeled screens are available: Cost, Quotas, Resource policies, Prompt quality, Prompt
  editor, and Prompt audit
- policy fields show effective value, inherited value/source, and locked versus editable state
- account scope edits Cost/Quotas/Resources; owned imported-definition scope edits/evaluates/audits
  prompts; project-template scope edits Cost/Quotas/Resources with prompt evidence read-only;
  attached scope only tightens policy and keeps prompt evidence read-only
- project templates and attachments show no Release, Publish, Share, or attachment-version action
- the server's permission projection determines which screens are editable, read-only, or
  unavailable while the six-screen navigation remains stable; the public result view has no
  entry point
- loading preserves layout; validation and save errors remain beside the relevant fields and in an
  error summary; revision conflicts preserve the local draft
- switching screen keeps valid unsaved form state, while closing, changing scope, logging out, or
  switching account prompts before discarding dirty changes
- every explicit project install has its own project-private revisioned defaults materialized from
  validated manifest seeds; the same definition in another project is independent
- `Reset to agent default` reapplies that artifact's reviewed seeds under the deployment/account
  ceilings currently in force for the selected project; attachment overrides can only tighten it
- focus is trapped in the modal, the screen navigation and editor are keyboard usable, progress is
  announced, Escape follows the dirty-state rule, and focus returns to the opening cog

## Prompt Draft, Evaluation, And Audit States

Prompt editing is available only for an authorized owned definition in My Imports and never
changes existing immutable bytes. An edit creates a private draft derived from an exact coordinate.
The editor exposes dirty, validating, saved, conflict, and read-only states. Release creates a new
private imported-definition version/digest; project templates and attached instances remain
unchanged until separate reviewed update/migration actions.

Prompt quality evaluation exposes queued, running, completed, failed, cancelled, and stale states.
Every result identifies the evaluated draft/artifact revision and suite version; any LLM judge is
an explicitly approved evaluator, never an implicit replacement for the blocked generated-content
evaluator. Evaluation does not automatically release, activate, install, migrate, or publish.

Prompt Audit is a separate governance view. It pins a privacy/security/compliance rule-set version,
shows queued/running/completed/failed/cancelled/stale audit runs and findings, and provides an
append-only, filtered, paginated history of authorized prompt changes, evaluations, releases, and
publication events. It exposes no secrets or private execution context. The chat transcript remains
the run history.

## Import, Install, Publish, And Project-Switch States

- `Import package` validates into My Imports and stops; it does not install, publish, or alter the
  active project palette.
- Only an owned validated My Imports definition shows `Publish`; it also shows a separate `Install
  in project` when a project is selected. Repeated commands are idempotent.
- Global/built-in cards show `Install in project`, never user Publish. Installed-project entries
  show `Project agent settings` and `Uninstall from project`, never Publish/Share.
- Switching projects replaces the AGENTS palette, attachment navigation, settings drafts, streams,
  and sessions with the selected project's state. Nothing carries across implicitly.

## Shared Result State

When a flow/Trill is shared, agent-private data is not exposed in the shared result: there is no
DATA/PACKAGES/AGENTS palette, dock, settings, prompt/evaluation/audit/history, provider/tool/cost
UI, private ID, edit/run action, or hidden-resource placeholder in the public result view.

## Node Explanation State

The built-in node `Explanation` tab keeps its existing empty/loading/error state, keyboard
target, cache, and direct request unchanged (`DEC-041`, `dev/18` — the former removal is
cancelled). `Explain with Node Explainer` may additionally enter the normal project install →
attach → dock tile → unified chat path. Canvas/full-flow explanation uses
`agent.dataflow-explainer` and is a separate workflow from the node tab.
