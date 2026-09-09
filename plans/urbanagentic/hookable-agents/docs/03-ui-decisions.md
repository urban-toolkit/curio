# UI Decisions

## Layout

The proposed screen uses four familiar Curio regions:

- top navigation
- compact left canvas tool palette
- central dataflow canvas
- right sidebar drawer for the Agent Catalog or selected-agent refinement

This arrangement matches the current Curio Data Catalog pattern. The right drawer can show the
browseable Agent Catalog by default, then switch to contextual refinement when a user opens an
attached-agent dock tile. Agent governance opens as a modal over the current surface rather than
replacing the drawer.

## Agents Drawer, Project Palette, And Private Attachments

The drawer separates lifecycle scopes instead of presenting one blended catalog:

The card action controls reuse the **exact Data / Node Catalog primitives** — a dark `Install`
primary, a neutral white-outline `Uninstall` secondary, the shared `Publish` → `Published` pill,
and `Delete` — with the same styling, placement, spacing, pill states, and behavior. No bespoke
labels, colors, or per-card settings button.

- **Global Catalog** shows built-in and published reusable definitions. Cards expose `Install`
  (available) or `Uninstall` (already installed in the project). They never expose user Publish,
  Share, or republish actions.
- **My Imports** shows validated account-private manifest definitions created by explicit
  `Import package`. Import ends on the private definition detail and never installs into the open
  project or publishes. An owned validated imported definition exposes `Install`, the shared
  `Publish` → `Published` pill, and `Delete`; `Install` and `Publish` are separate — either can
  happen first and neither triggers the other.
- **Installed in this project** shows `ProjectAgentTemplate` records for the active project. These
  entries expose `Uninstall` (settings open from the `Project agent settings` cog, not a card
  button), and never Publish, Share, global release, or account-wide-installed language.

Additional rules:

- **Left `AGENTS` palette = active project only.** It lists only that project's installed
  templates using an icon tile, agent name/source reference, and category chip. The whole row is
  draggable and has no per-row install/publish/settings action. Switching projects replaces the
  palette; no template, attachment, settings, or session follows implicitly.
- **Attachment = private derivation.** Dragging a project template to a compatible target creates
  an `AttachedAgentInstance` with stable `attachmentId`, `projectAgentTemplateId`, target, and an
  optimistic concurrency `revision`. It has no SemVer, catalog/release identity, Publish, or Share
  action. Execution snapshots privately pin source/settings/prompt/provider details for
  reproducibility without versioning the instance.
- **Orchestrator proposals are project installs.** A missing specialist produces a reviewed
  `Install in project` proposal. It never imports, publishes, attaches, grants, or runs silently.
- **Conversational refinement stays in the right drawer.** The dock tile opens unified chat; its
  `Attachment settings` cog exposes only applicable private configuration and read-only source
  evidence (see `08-unified-agent-chat`).
- **Lifecycle commands remain distinct.** Import, Publish, Install in project, Attach, Detach, and
  Uninstall from project are explicit independent commands. Project uninstall is
  blocked by live references in that project and never silently detaches. (Agents add no share
  command; a flow is shared through Curio's existing sharing.)
- **Providers are profiles, not key fields.** Configuration selects an authorized profile and
  identifies Local versus Remote processing. Secret values are never returned, and local failure
  never silently falls back to remote.

See `11-agent-manifest-and-product-model.md` for the full definition → import/catalog → project
template → private attachment lifecycle.

Required elements:

- `Agent Catalog` title
- clear `Global Catalog`, `My Imports`, and `Installed in this project` scope controls
- context-correct `Import package` footer, `Install` / `Uninstall`, the imported-definition-only
  `Publish` → `Published` pill, and `Delete` — the same card action controls the Data / Node
  catalogs use
- search input
- category filters
- compact agent cards
- hook target metadata
- review policy metadata
- selected card state
- labeled catalog-header `Agent settings`, owned-import `Definition settings for <agent>`, and
  installed-detail `Project agent settings` cogs where the server grants settings visibility

Agent cards should use compact labels:

```text
Dataset Finder
Data agent
Hook: Data Load node
Review: confirm datasets
```

## Canvas: Hookable Dataflow

The canvas should show the current dataflow with normal node cards. The agent layer should be visible but not overpower the workflow.

Node cards keep their built-in `Explanation` tab, explanation configuration state, direct LLM
request, and explanation cache unchanged (`DEC-041`, `dev/18` — the former removal is cancelled).
`Explain with Node Explainer` may additionally open the normal project install → attach →
unified-chat workflow. Canvas/full-flow explanation remains the separate
`agent.dataflow-explainer` behavior and is distinct from the node tab.

Recommended visual devices:

- dotted attachment lines while demonstrating or dragging
- small hook chips on compatible targets
- attached-agent docks beneath nodes
- a canvas-level agent dock for whole-dataflow agents
- selected tile outline and connection to the open sidebar

## Attached-Agent Dock (macOS Dock pattern)

Attached agents appear in a **dock** beneath the node they belong to (node agents) or
on the canvas (whole-dataflow agents). This makes ownership obvious while staying compact.

Dock behaviour follows the macOS Dock:

- **Compact square, icon-only tiles** — each tile shows only the agent's bot-head icon
  (tinted by agent type). Tiles are visually identical; type is the only differentiator.
- **Free-floating, no shelf** — there is no background container; tiles float, each with its
  own soft shadow. Node-agent tiles are left-aligned to their node's left edge; canvas agents
  float near the top of the canvas.
- **Hover tooltip** — hovering a tile shows the agent name in a small label above it
  (dark bubble + caret).
- **Magnification** — the hovered tile enlarges (~1.6×) and immediate neighbours enlarge
  a little (falloff).
- **Running indicator** — a small dot beneath a tile marks a running / active agent.
- Sizing/spacing: resting tile ~40px, magnified ~66px, ~12px gaps, rounded corners with a
  soft shadow — consistent with the app's card style.

Clicking a dock tile opens that attachment's chat session (see `08-unified-agent-chat.md`).

Example states surfaced by the tile: idle, configured, running (dot), needs review, error.

## Refinement: one unified chat drawer

The same right drawer switches into a **chat session** when an attached-agent dock tile is
selected. There is exactly one conversational refinement UI for all agents — no bespoke
per-agent chat panels. It is visually identical across agents; only the agent type (name +
icon), effective configuration, and chat history differ. Cross-agent policy and prompt
governance use the shared modal defined below.

The drawer includes:

- a **top header** (`DEC-042`, `dev/21` — the opened agent view's only header) with
  previous/next arrows to navigate all attached agents in the dataflow, the agent identity,
  private project template/target provenance, and immutable attachment/session ID (with a
  friendly `target · agent · project` label), plus a **Close** control that dismisses the view
  without detaching; **no Pin button** here, and the static `Agents Catalog` bar does not
  appear (it is exclusive to the Agents Roster drawer, whose header keeps the Pin only). A
  labeled **`Attachment settings`** cog sits in the content area beneath the header; no
  attachment SemVer, Publish, Share, or Release control is shown
- the attached target
- a chat transcript (system context lines, user messages, agent replies)
- inline chat cards for suggestions, behaviour quick-replies, dataset previews, and results
  (informational — the cards carry **no action buttons**)
- a chat input that shows the primary **suggested prompt** prefilled and editable, with a
  "SUGGESTED PROMPTS" chip row of alternatives above it

Conversational refinement, suggestions, lightweight behaviour choices, reviews, and previews
happen in chat, in the style of Cursor or Claude. **Agent workflow actions are suggested prompts,
not bespoke buttons:** any agent surfaces confirmations, options, follow-ups, and next steps as
suggested prompts the user reviews, edits, and submits from the input box — never as per-agent
controls such as "Create Node", "Create Dataset", or "Add dataset node". Generic system controls
such as the settings cog and modal `Save`, `Cancel`, `Run evaluation`, `Run audit`, and `Save draft` actions are
explicit exceptions. The transcript is execution/run history, not prompt-governance history. See
`08-unified-agent-chat.md`.

## Shared Agent Settings Modal

Use one reusable `Agent settings` modal shell with applicability determined by scope:

- drawer `Agent settings` opens account Cost, Quotas, and Resource policy bounds/defaults;
- My Imports `Definition settings for <agent>` opens owned-definition Prompt Editor, Prompt Quality, and
  Prompt Audit; Release creates a new private imported definition and Publish remains separate;
- Installed in this project `Project agent settings` opens project-template Cost, Quotas, and
  Resource defaults, with prompt provenance/evidence read-only and no Publish/Release;
- chat-header `Attachment settings` opens downward-only Cost, Quotas, and Resource overrides,
  with prompt source/evidence read-only and no Version/Release/Publish/Share.

The header shows `Account policy`, `Imported definition`, `Project agent default`, or `Attached
instance`, plus agent/source/project/target identity only where authorized. Draggable project
palette rows stay action-free, and the shared result exposes no settings entry point.

The shell contains six dedicated screens in a persistent labeled navigation rail:

| Screen | Responsibility |
| --- | --- |
| **Cost** | Per-run and rolling monetary budgets, alerts, pricing effective date, and estimated versus provider-reported actual usage. This is usage control, not marketplace billing or payment UI. |
| **Quotas** | Execution, token, tool-call, concurrency, and rate-window limits, current usage, reservations, and reset time. |
| **Resource policies** | Allowed provider profiles/models, Local versus Remote processing, context/output limits, timeouts, tool/network constraints, and supported local CPU/RAM bounds. Secret values are never displayed. |
| **Prompt quality** | Versioned suite/rubric/threshold selection, validation and evaluation runs, status, findings, usage/cost, and stale-result warnings. |
| **Prompt editor** | Owner-authorized package-local prompt drafts with variables/schema validation, preview, and semantic diff. Saving creates or updates a draft, never immutable artifact bytes. |
| **Prompt audit** | Versioned privacy/security/compliance rule sets, audit runs/findings, and append-only governance events: actor, time, reason, hashes/diff metadata, validation/evaluation, release, activation, and publication links. It is not a second execution transcript. |

### Policy scope and state

Cost, quota, and resource policies are mutable records separate from the manifest. Each control
shows its effective value, inherited value, source, and whether the value is locked. The backend
computes deployment hard limit → account limit → project-template default → attachment override
→ execution reservation; lower scopes may narrow a limit but never relax an inherited boundary.
Client estimates are explanatory only. Enforcement and concurrent usage reservation are
server-authoritative.

There is no universal/global agent preset. Each exact artifact declares immutable, schema-valid
`settingsDefaults` seed suggestions that reference one reviewed profile family/version. Installing
the definition in a project materializes independent project-private typed revisions for that
template; the same definition installed in another project receives a separate profile. `Reset to
agent default` changes only the selected project template, reapplies the reviewed seeds, and
re-clamps current deployment/account ceilings. Attachment overrides may only tighten it.

Prompt editing applies only to an owned imported definition and follows `exact artifact → private
draft → validate → evaluate → audit → release`. Releasing creates a new private definition
coordinate and never retargets a project template or attachment. Third-party/built-in/global,
project-template, and attachment prompts remain read-only. Any future fork/export must be packaged
and explicitly re-imported and is out of scope. Quality evaluation never
silently substitutes the missing generated-content evaluator or installs/publishes a definition.

The modal preserves stable geometry for loading, inherited/read-only, dirty, validating, saving,
saved, conflict, forbidden, and unavailable states. Evaluation and audit runs additionally support
queued, running, completed, failed, cancelled, and stale. Audit history supports loading, empty,
error, filters, and cursor pagination. A revision conflict retains the local draft and offers reload/review rather
than silently overwriting server state.

### Settings accessibility

- Cog controls use a familiar gear icon plus an accessible, visible or tooltip label; the gear is
  never the sole programmatic name. Use at least a 44px pointer target and
  `aria-haspopup="dialog"`.
- The modal has a semantic title/description, focus trap, logical initial focus, keyboard-complete
  screen navigation, error summary plus field errors, and meaningful live announcements for saves
  and evaluation progress.
- Closing, pressing Escape, changing scope, or switching account guards unsaved edits. On close,
  focus returns to the opening cog. The editor provides a keyboard-safe plain-text fallback.
- Narrow viewports use a full-screen presentation; zoom/reflow, forced colors, contrast, and
  reduced motion follow WCAG 2.2 AA. State is never conveyed by color alone.
- Authorization comes from server-returned capabilities such as manage policy, edit prompt,
  evaluate prompt, and view audit. The UI does not infer permission from labels or hide a failed
  request as success.

## Sharing Privacy

When a flow/Trill is shared, agent-private data is not exposed in the shared result: datasets, node
packages, definitions/imports/project installations/attachments, agent flows, private
configuration, prompts, quality/audit evidence, history, providers, tools, usage/cost, and private
IDs never appear in the public result view.

### Chat feedback visual system (Claude-like, on Curio tokens)

All chat feedback components — change feedback, confirmation/result cards, radio and checkbox
options, selection states, inline decisions/status, and other in-chat controls — share one
visual language that reads like Claude's agent chat while staying on Curio's tokens and
accents:

- **Grouped surfaces.** Cards are a single subtle surface (`#f7f7f8`) with a hairline border
  (`#ececee`) and a `12px` radius — no heavy shadows or full-height colored bars. Identity is
  a small **leading accent dot** in the header (agent-type colour), not a bar.
- **Raised inner panels.** Dense content (generated code, data samples, option groups) sits in
  a white inner panel with its own hairline, for clear grouping within the card.
- **Readable option states.** Checkboxes (multi-select) and **radio rows** (single-select) are
  full-width option rows; the selected row gets a soft accent tint (a low-saturation wash,
  e.g. mint for green, sky for blue) plus a hairline accent outline and a filled control — a
  lightweight, obvious selected state.
- **Soft status / result tones.** Confirmation, install, hand-off, and agent-status surfaces
  use gentle per-accent tone fills (success mint, install peach, delegate sky) with matching
  hairline borders and a leading icon — never saturated blocks.
- **Soft tokens & chips.** Pills/tokens are filled soft surfaces with optional hairlines (no
  hard outlines); the "SUGGESTED PROMPTS" chips and status chips share this treatment.
- **Polished spacing.** Consistent `16px` gutters, roomy header rows, and even option-row
  rhythm; labels always accompany colour.

The tokens live in `render_hookable_agents_png_concepts.py`
(`CHAT_SURFACE` / `CHAT_INNER` / `CHAT_BORDER` / `CHAT_RADIUS` / `_OPT_SEL` / `_TONE`) and are
applied by the shared `_card_shell`, `_radio`, `_checkbox`, and `_chip` helpers so every card
is consistent. This section is the canonical chat-feedback visual contract.

## Visual Language

The mockup uses:

- black top nav for Curio continuity
- light gray canvas and subtle dot grid
- white node cards
- orange as the primary action and selected state
- green for data-oriented agents
- blue for node explanation and inspection
- purple for evaluation and explanation-related agents

Labels are always present, so color is never the only identifier.
