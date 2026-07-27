# Unified Attached-Agent Chat

## Summary

Conversational refinement, proposals, reviews, and execution happen through one unified chat
drawer used by *every* attached agent. One shared settings modal supplies scope-appropriate cost,
quota, resource, and read-only prompt provenance from the chat header; prompt authoring/evaluation/
audit belongs to an owned imported definition. It is not a bespoke agent panel. Attachments are visually
indistinguishable from one another; they differ only by:

- **agent type** (name + icon),
- **instantiation / configuration**, and
- **chat / execution history**.

The chat replaces the earlier bespoke, per-agent refinement and review interfaces
(the Node Explainer refinement sidebar, the Dataset Finder overview, the source-
review panel, and the dataset review modal). Agent workflow behavior lives in the conversation,
in the style of Cursor or Claude chat; reusable policy and prompt governance lives in the shared
settings shell.

## Sessions

Each agent attachment behaves like an **agent session**, uniquely identified by:

```text
session identity = attachmentId
display label = (target, agent type, project/flow)
```

- Attached agents appear in a **macOS-Dock-style dock** (compact square, icon-only
  tiles that magnify on hover and show the agent name in a tooltip; see
  `03-ui-decisions.md`). Clicking a dock tile opens the drawer for that specific
  attachment and shows the history of what that agent has done on that node.
- Re-opening the dock tile resumes the same session with its full transcript.
- The transcript **is** the execution/run history — there is no second execution-history panel.
  Prompt Audit is a different, access-controlled governance record for prompt changes,
  evaluations, and releases.
- The attachment/session is a private project/target derivation identified by `attachmentId` and
  concurrency `revision`, not by SemVer. It references a project template and exposes no Publish,
  Share, Release, or catalog identity.
- Switching projects replaces the project AGENTS palette and clears attachment navigation/chat,
  streams, settings drafts, and sessions that do not belong to the newly active project.
- When a flow/Trill is shared, agent-private data is not exposed in the shared result: the
  attachment, dock, session ID, provider, configuration, transcript, and execution payload never
  appear in the public result view.

## Drawer anatomy (identical for all agents)

Per `DEC-042` (`dev/21`) the opened agent view has **one top header** carrying the
agent identity, and the static `Agents Catalog` bar is exclusive to the Agents
Roster drawer (see below).

```text
Top header (opened agent view — the only header):
         ‹  🤖 <Agent name>  <idx> / <total>  ›   session <attachment-id>    ✕
         Attached to <target node>                <target·agent·project>
         (identity + cycling live here; ✕ closes the agent view without
          detaching; NO Pin button in the opened agent view)
Below the header, at the top of the white content area:
         ⚙ Attachment settings
Body:    chat transcript — its FIRST message is the attachment's initial
         intent, rendered as a plain user bubble (dev/26): collapsed to a few
         lines with Show more/less and an edit pencil (edits persist to the
         attachment; emptying restores the prompt source). No pinned intent
         field exists above the transcript.
           · system line   (context / permissions the agent reads)
           · user message  (dark bubble, right-aligned)
           · agent message (bot avatar, left) — may contain an inline card:
               - suggestions card  (external + Data Catalog lanes; multi-select, no preview link, no button)
               - behavior card      (quick-reply chips; one selected)
               - preview card       (dataset node: fetch code, credential requirement, sample; no button)
               - result card        (what was created / changed)
Footer:  SUGGESTED PROMPTS  [ chip ] [ chip ] [ chip ]      (alternatives)
         chat input  [ Build the NOAA node and install …   ↑ ]  (primary, prefilled + editable)
```

### Header navigation

The top header exposes **previous / next arrows** that walk through all attached
agents in the current dataflow (e.g. `1 / 4`). This lets a user move between every
attachment without hunting for dock tiles on the canvas. A labeled `Attachment settings` cog
(in the content area beneath the header, unchanged) opens the shared settings modal scoped to
this attachment. The header's close control (`✕`) dismisses the opened agent view — it never
detaches the agent — and there is no Pin button in the opened agent view (`DEC-042`).

### Agents Roster drawer header

The static dark catalog-style header (`🤖 Agents Catalog`) is used **exclusively** by the
Agents Roster drawer (the three-scope catalog). Of the former shared bar's controls it keeps
the **Pin button only** — no Close button, no master-agent identity, no agent-cycling
controls (`DEC-042`). The separately approved labeled `Agent settings` cog (account policy
entry — memo `dev/11`, `02-hook-model-and-flows.md`) remains valid in this header.

### Conversational behavior is a chat turn

- **Suggestions** (Dataset Finder): the agent posts a suggestions card with two lanes —
  external sources and Data Catalog datasets — multi-selectable. There is **no inline
  preview link**; dataset preview and detailed inspection happen later through the existing
  Data Catalog drawer detail modal / screen. Confirmation routes each pick to Node Builder
  (external → generated fetch node) or the install flow (catalog).
- **Lightweight behaviour choices** (Node Explainer and others): configured with in-chat
  quick-reply chips (e.g. Planner-friendly / Technical / Public), not a bespoke form. Durable
  cost, quota, resource, or prompt-governance settings use the shared modal.
- **Preview**: the agent posts an inline card showing the exact dataset node (fetch code,
  required provider/credential profile, params, checks, data sample). Secret values are
  never displayed or stored in the attachment. The card has **no action button**.
- **Agent workflow actions are suggested prompts, not bespoke buttons.** This is the generic,
  reusable pattern for every agent: confirmations, options, follow-ups, and next steps are surfaced as
  **suggested prompts** the user can review, edit, and submit from the chat input box — the
  primary one prefilled (editable) in the input with an active send button, alternatives as
  a "SUGGESTED PROMPTS" chip row above it. No agent renders dedicated action buttons
  (e.g. "Create Node", "Create Dataset", "Add dataset node"). Generic system controls such as
  `Attachment settings`, `Save`, `Cancel`, `Save draft`, and `Run evaluation` are permitted in
  the shared settings workflow.
- **Results** are logged as a result card, so the run history is simply the transcript.
- **Agent and tool content is untrusted.** Every Markdown or rich-content part uses the
  centralized safe renderer; raw HTML, scripts, event handlers, unsafe URL schemes, and
  unapproved embeds are disabled while ordinary text, code, and safe links remain usable.
- **Interrupted work** retains committed transcript/events and offers an explicit Retry.
  Retry creates a new execution linked to the interrupted one; provider or tool calls are
  never replayed automatically after a restart.

## Shared Settings Modal

The modal structure is identical across agents and uses six dedicated screens, but its per-agent
defaults are never a generic/global preset:

- **Cost** — per-run and rolling budgets, alerts, current usage, pricing effective date, and
  explicit `Estimated` versus provider-reported `Actual` labels.
- **Quotas** — executions, tokens, tool calls, concurrency/rate windows, reservations, and reset
  time.
- **Resource policies** — provider profile/model/locality, Local versus Remote processing,
  context/output/time limits, egress, tools/network, and supported local resource bounds. Secret
  values are never returned or rendered.
- **Prompt quality** — pinned validation suite/rubric/threshold, queued/running/completed/failed/
  cancelled/stale evaluations, findings, and evaluation usage/cost.
- **Prompt editor** — owner-authorized prompt drafts, variables/schema checks, preview, and diff.
  Saving a draft does not mutate the immutable imported definition artifact.
- **Prompt audit** — versioned privacy/security/compliance rules, audit runs/findings, and
  append-only authorized prompt-governance events/hashes for edits, evaluations, releases,
  activation, and publication. It is separate from this chat transcript.

The modal header identifies one of four scopes:

- **Account policy** — Cost, Quotas, and Resources establish upper bounds/defaults.
- **Imported definition** — an owned My Imports package enables Prompt Editor, Prompt Quality, and
  Prompt Audit. Release creates a new private definition; Publish and Install remain separate.
- **Project agent default** — `Project agent settings` edits Cost, Quotas, and Resources for one
  installed project template. Prompt source/evidence is read-only and no Publish/Release exists.
- **Attached instance** — `Attachment settings` may only tighten Cost, Quotas, and Resources.
  Prompt source/evidence is read-only and the instance has no Version/Release/Publish/Share action.

The effective policy is server-computed from deployment/account limits, project-template defaults,
attachment overrides, and execution reservations. Every field shows its effective value and
inherited source; attachment values can narrow but not exceed inherited limits.

Manifest `settingsDefaults` are immutable, validated seeds for one exact definition, not active
policy. Each explicit project install copies them into an independent project-private revisioned
profile after clamping current deployment/account ceilings. `Reset to agent default` changes only
that project template and repeats the clamped materialization using current ceilings. Attachments
may only tighten the selected project profile.

Prompt editing follows an owned explicit-import release flow: imported definition → draft →
validate → evaluate → audit → release a new private definition version/digest. Built-in/global,
project-template, and attachment sources remain read-only. Updating a
project template, migrating an attachment, and publishing are separate reviewed actions; none is
automatic. Any future fork/export must be packaged and explicitly re-imported and is out of scope.
Evaluation never silently uses the unresolved generated-content evaluator.

Server-returned authorization capabilities decide whether each screen is editable, read-only, or
unavailable. The shared result has no settings control and cannot enumerate private
projects, templates, attachments, policies, prompts, drafts, evaluations, or audit events. Dirty changes are guarded on close,
navigation, logout, and account switch; revisions prevent lost updates.

The dialog traps focus, has a semantic title/description, supports keyboard screen navigation and
a plain-text editor fallback, announces saves and evaluation progress, restores focus to the cog,
and becomes full-screen at narrow widths. It must meet WCAG 2.2 AA for zoom/reflow, contrast,
forced colors, reduced motion, error association, and non-color state communication.

All of these components share one **Claude-like visual system** — subtle grouped surfaces,
hairline borders, raised inner panels, readable radio/checkbox option rows with soft accent
selection states, gentle status/result tones, soft tokens, and polished spacing — expressed
with Curio's tokens/accents. The canonical details are in the "Chat feedback visual system"
section of `03-ui-decisions.md`.

## Invariants preserved

- **Review before apply** — the agent proposes; the user confirms. Creation and
  changes are explicit chat actions; nothing happens silently.
- **Provenance** — datasets created by an agent are still tagged in the palette
  (see `09`).
- **Labels over colour** — the drawer chrome is identical; the agent type is carried
  by the name + icon and never by layout.
- **Private by construction** — agent docks/chat are not exposed in the shared result.
  Recipients never inherit definitions, imports, templates, attachments, agent flows, providers,
  policies, prompts, evaluations, audit/history, tools, usage/cost, or private IDs.

## What was removed

- `draw_refinement` (bespoke Node Explainer refinement sidebar).
- `draw_dataset_finder_overview` (bespoke intent/suggestions overview).
- `draw_dataset_source_review` + `source_card` (bespoke source-review panel).
- `draw_dataset_review_modal` (bespoke review modal).

(The built-in node `Explanation` tab, its direct `single_box_explanation_prompt` request, loading/
error state, and node-store cache were formerly on this removal list; per `DEC-041` (`dev/18`) they
are **retained** and coexist with the agent chat.)

The bespoke surfaces remain superseded by `draw_agent_chat`. The new shared settings modal is a
generic system surface, not a return to per-agent refinement forms. Node Explainer attached-agent
chat is a node-explanation workflow coexisting with the retained built-in Explanation tab
(`DEC-041`, `dev/18`); `agent.dataflow-explainer` remains a distinct canvas/full-flow behavior.
The current renderer and generated visual artifacts do not yet reflect the lifecycle/share changes
or settings screens and must be regenerated (any artifact depicting the Explanation tab as removed
is stale on that point).

## Screens

| Screen | Shows |
| --- | --- |
| `03` | Attaching Dataset Finder opens its chat session; suggestions inline. |
| `06` | The same drawer for Node Explainer; conversational refinement and lightweight behaviour choices remain in chat. |
| `07` | A persistent session's chat history (intent → suggest → create). |
| `08` | Dataset preview as an inline chat card (replaces the modal). |
| `09` | Created datasets in the DATA palette; the create is a logged chat turn. |
| `12`–`17` *(planned)* | Cost, Quotas, Resource policies, Prompt quality, Prompt editor, and Prompt audit in the shared settings shell; not yet generated. |
| `18`–`22` *(planned)* | Drawer lifecycle, scope applicability, and Node Explainer-only explanation evidence; not yet generated. |
