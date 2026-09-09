# Implementation Memo: Agent Chat Concept Alignment, Close Control, and Prompt-Sourced Initial Intent

Date: 2026-07-21
Status: **implemented** (2026-07-21; `BL-P4-20260721-13` — commits `e3a4863`/`906ad92`/`2d3478a`/`bd956c4`)
Feature slice: P4 — attachments & chat (`BL-P4` follow-on; complements the deferred persistent-sessions item)
Canonical visual sources: `docs/08-unified-agent-chat.md` (drawer anatomy), `docs/03-ui-decisions.md` §"Chat feedback visual system", concept screens `03`/`06` (`png-concepts/`)

## 1. Problem Statement

The shipped chat panel (`components/agents/attach/AgentChatPanel.tsx` + the chat section of `AgentDock.module.css`) is a functional but generic floating card. It diverges from the approved concept screens in every visual dimension the spec defines:

- **Header**: a flat dark strip with a robot glyph, name, raw target string, and an unstyled `✕`, instead of the concept's white-surface header row (category-tinted agent avatar, agent name, "Attached to <target>" subtitle, session chip, clear close affordance).
- **Messages**: user and agent turns are both plain rounded rectangles; the concept shows dark right-aligned user bubbles and agent replies rendered as avatar-prefixed left rows on the light surface — plus capability/system chips — per the "grouped surfaces / hairline borders / 12px radius" contract.
- **Input**: a bordered text field plus a rectangular "Send" button, instead of the concept's pill-shaped input with a circular accent `↑` send control.
- **Surfaces/tokens**: ad-hoc greys (`#f2f2f4`, top-bar black) rather than the canonical chat tokens (surface `#f7f7f8`, hairline `#ececee`, radius `12px`, soft accent selection washes) already used as the reference for the drawer/palette restyle.

Behavioral gaps:

- **Close/reopen loses the conversation.** The transcript lives in `useState` inside `AgentChatPanel`; `AgentDockOverlay` unmounts the panel when `selectedId` clears, so clicking close and reopening the same agent shows an empty chat. The requirement is that closing dismisses the panel without detaching, and reopening restores the session's chat state (within the app session — server-persistent sessions remain the separately-tracked P4 follow-up).
- **No initial intent exists anywhere.** The concept pins an editable **INITIAL INTENT** block at the top of the chat ("the attachment's starting intent — editable, pinned", `docs/08` anatomy). Today nothing shows the agent's instruction, the attachment record (`spec.dataflow.agentAttachments`) has no intent field, the API card (`_attachment_card`) doesn't expose one, and `run_attachment` always reads the prompt file. If the frontend hardcoded intent strings per agent it would duplicate the prompt source — exactly what the requirement forbids. The intent must be initialized from the actual prompt bytes (built-ins: `utk_curio/llm-prompts/<prompt_file>`; installed/materialized: the store copy `_resolve_instruction_text` already reads) and be editable per attachment.

Why it matters: the chat is the single unified surface for every attached agent (`docs/08`); visual drift here forks the design system the drawer, palette, and badges already follow, and the lost-transcript close makes the close button actively harmful. A duplicated hardcoded intent would rot the moment a prompt file changes.

## 2. Scope

**Included**

- Frontend: `components/agents/attach/AgentChatPanel.tsx`, `AgentDock.module.css` (chat classes → a dedicated `AgentChatPanel.module.css`), `AgentAttachmentsProvider.tsx` (transcript + intent state lift), `useAgentAttachments.ts` (intent update passthrough), `api/agentsApi.ts` (type + methods), reuse of `menus/nodes/agentsPalette/agentCategoryStyle.ts` for the avatar tint.
- Backend: `app/agents/attachments.py` (pure intent set/clear on the record), `app/agents/services.py` (`_attachment_card` intent resolution, `update_attachment_intent`, `run_attachment` override), `app/agents/routes.py` (`PATCH .../attachments/<id>`), `docs/AGENTS.md`.
- Tests listed in §7.

**Out of scope (unchanged)**

- Attachment/detach lifecycle, dock, node badges, palette, drawer, drop-to-attach — all preserved as-is.
- Server-persistent chat sessions/history (separately tracked P4 follow-up; this memo only stops the close button from destroying in-memory state).
- Suggestions/behavior/preview/result **cards** and the SUGGESTED PROMPTS chip row from the concept: they require agent-produced structured content the stateless single-turn runtime does not emit yet. The restyle lays out the transcript so cards/chips can slot in later; no fabricated content ships now.
- The shared settings modal, header prev/next attachment navigation (needs multi-attachment session UX beyond this slice), prompt governance.
- The retained node Explanation tab (`DEC-041`) — untouched.

## 3. Recommended Implementation Approach

**Backend — intent as an attachment-record field resolved from the prompt source.**

1. `attachments.py`: pure `set_intent(spec, attachment_id, intent: str | None)` — sets or clears `record["intent"]`, bumps `revision`, returns the record (mirrors the existing pure-helper style; ids in, testable without I/O).
2. `services.py`:
   - `_attachment_card` gains `"intent": record.get("intent") or _resolve_instruction_text(user_key, coord)` — the displayed initial intent **is** the resolved prompt bytes unless the user has edited it. No copy of prompt text is stored at attach time, so an unedited intent always tracks the current prompt source (single source of truth; store-first resolution unchanged).
   - `update_attachment_intent(user_key, project_id, attachment_id, intent)` — validates existence, applies `set_intent` under the spec write path used by attach/detach, persists, returns the refreshed card. Empty-string/None clears the override (falls back to the prompt source).
   - `run_attachment`: `instruction = record.get("intent") or _resolve_instruction_text(...)` — an edited intent becomes the system turn, so what the user sees pinned is what actually runs.
3. `routes.py`: `PATCH /api/agents/projects/<pid>/attachments/<attachment_id>` with body `{"intent": string | null}` → the card. 404 unknown attachment, 400 non-string.

**Frontend — one provider-owned chat state; concept-styled panel.**

4. `agentsApi.ts`: `AgentAttachment.intent: string | null`; `updateAttachmentIntent(projectId, attachmentId, intent)`.
5. `AgentAttachmentsProvider.tsx`: own `transcripts: Map<attachmentId, Turn[]>` and an `appendTurns`/`runInChat` wrapper so the transcript survives panel unmount. Clear an attachment's transcript on detach; the map resets naturally on project switch (provider re-keys by `projectId`). Expose `updateIntent` (optimistic update, reconcile with the returned card, revert on error).
6. `AgentChatPanel.tsx` restyle to the concept anatomy, reusing existing design tokens (`--curio-*` vars, `agentCategoryStyle` tint) — no new visual language:
   - Header (white surface, hairline bottom): category-tinted rounded-square avatar (same treatment as `AgentAvatarBadge`), agent name (13px/600), subtitle "Attached to <node title | canvas>", muted session chip (`session <short-id>`), and a **clear close button** — icon `✕` in a 28px hit-area with hover surface, `aria-label="Close chat"`, `title="Close chat"`. Close calls `ctx.closeChat()` only (attachment untouched).
   - **INITIAL INTENT** block pinned under the header: small-caps muted label, intent text in a raised inner white panel (hairline, 12px radius), clamped to ~4 lines with an expand toggle for long prompts. An edit affordance (pencil) swaps it to a textarea with Save/Cancel; Save → `updateIntent`; clearing text restores the prompt-sourced default.
   - Transcript on the `#f7f7f8` surface: user turns as dark right-aligned bubbles (12px radius); agent turns as left rows with a small category-tinted avatar and plain text on white inner panels; error turns use the soft status tone (hairline, gentle fill), not raw red.
   - Footer: pill input (hairline, fully rounded) + circular accent send button with an `↑` icon (`aria-label="Send"`), disabled/spinner states preserved.
   - Spacing per the contract: 16px gutters, even row rhythm.
7. `AgentDockOverlay.tsx`: unchanged wiring apart from passing the provider transcript/intent props.

Rendering stays plain text through React (no HTML injection), consistent with the untrusted-content rule.

## 4. Data and State Handling

- **Source of truth — intent**: the attachment record's `intent` override; when absent, the definition's instruction prompt bytes resolved server-side at read time. The frontend never hardcodes or caches prompt text beyond the fetched card.
- **Source of truth — transcript**: provider-held per-attachment array (app-session scope). Panel components are stateless views over it.
- **Updates**: intent Save is optimistic; on success the card from the server replaces the local attachment (keeps `revision` in sync); on failure the previous value is restored and an inline error shown. Concurrent send during intent edit is allowed — the run uses the last persisted intent (server reads the record).
- **Loading/empty/error**: intent block renders a muted placeholder if the card's intent is `null` (no prompt asset — the same condition where run returns 422); empty transcript keeps the current "ask something" hint restyled as a muted centered line; send errors append a soft-tone error turn (existing behavior, restyled).
- **No stale/flicker**: close/reopen re-renders from provider state (no refetch needed); the dock-refresh event already reconciles attachment lists after saves.

## 5. UI and UX Requirements

- Visual parity with concept screens `03`/`06` and the `docs/03` chat-feedback contract: surface `#f7f7f8`, hairlines `#ececee`, 12px radii, raised white inner panels, dark user bubbles, soft chips/tones, 16px gutters. Category tint comes from the shared `agentCategoryStyle` map so palette rows, badges, and the chat avatar agree.
- Close button: visually clear (not a bare glyph), keyboard focusable, `aria-label="Close chat"`; Escape also closes the panel; focus returns to the invoking badge/tile.
- Intent editor: textarea labelled "Initial intent"; Save/Cancel reachable by keyboard; expanded/clamped state announced via the toggle button text.
- Labels accompany color everywhere (agent name next to the tinted avatar); contrast per WCAG 2.2 AA on the new surfaces.
- No layout shift on open: fixed panel geometry retained (right-anchored, current width), only the inner anatomy changes.

## 6. Edge Cases

- Long instruction prompts (multi-KB, e.g. `chat_prompt.txt` ≈ 2.7 KB): clamped intent with expand; textarea scrolls.
- Definition without a prompt asset: `intent: null` → placeholder text; run keeps returning 422 (unchanged).
- Detach while the chat is open (dock hover ✕): panel closes and its transcript is dropped (existing close-on-detach path preserved).
- Intent PATCH races a canvas save: both go through the backend spec write path; `preserve_agent_state` keeps `agentAttachments` authoritative server-side, so a client canvas snapshot cannot clobber the new intent.
- Clearing the intent (empty Save) restores the prompt-sourced default on the next read — verify the card round-trips `null`/absent correctly.
- Project switch while open: provider re-keys, panel closes, transcripts drop (matches the session-privacy rule in `docs/08`).
- Repeated rapid sends: input disabled while `sending` (unchanged).
- Prompt file edited on disk after attach: unedited intent reflects the new text on next fetch (by construction — nothing cached server-side).

## 7. Testing Strategy

Backend (`tests/test_agents/`):
- `test_attachments.py`: `set_intent` sets/clears + bumps revision; unknown id returns None.
- `test_routes.py`: attachment card's `intent` equals the built-in's prompt-file text after attach (read the same file in the test — no literal duplication); PATCH persists across GET; PATCH with `null` restores prompt-sourced intent; PATCH unknown id → 404; run uses the edited intent as the system turn (provider port mocked) and falls back to prompt text when unedited.

Frontend (`src/tests/`):
- `attach/AgentChatPanel.test.tsx`: renders header name/target/session; close button calls `onClose` and does not call detach; intent block shows fetched intent; edit→Save calls the update handler; clamp/expand toggle; error turn styling class.
- `attach/AgentAttachmentsProvider` (new test): transcript survives close/reopen (unmount panel, remount, turns still render); detach clears that attachment's transcript.
- `api/agentsApi.test.ts`: `updateAttachmentIntent` method + `intent` field passthrough.
- Regression: existing `AgentDock`, `NodeAgentBadges`, palette, and drawer suites stay green (attachment/dock/palette behavior unchanged).

## 8. Acceptance Criteria

- [ ] The opened chat visually matches concept `06`/`03`: white header row with tinted avatar + "Attached to …", pinned INITIAL INTENT panel, `#f7f7f8` transcript surface, dark right-aligned user bubbles, avatar-prefixed agent rows, pill input with circular `↑` send — using existing Curio tokens only.
- [ ] A clear, labelled close button dismisses the panel; the attachment remains attached and its dock tile/badge unchanged.
- [ ] Reopening the same attachment shows the prior in-session transcript and current intent.
- [ ] A freshly attached built-in shows an initial intent identical to its `llm-prompts/<prompt_file>` text (or its materialized store copy), served by the API — no frontend/back-end string duplicates it.
- [ ] Editing the intent persists on the attachment, is used as the system turn on subsequent runs, and clearing it falls back to the prompt source.
- [ ] Attach, detach, drop-to-attach, dock, node badges, and palette behavior are unchanged; all existing suites pass.

## 9. Recommended Commit Breakdown

1. `feat(agents): attachment intent — pure set_intent + card/run resolution from the prompt source, with tests` (backend, no route yet).
2. `feat(agents): PATCH attachment intent route + docs/AGENTS.md, with route tests`.
3. `feat(agents): lift chat transcripts & intent into AgentAttachmentsProvider; agentsApi intent support, with tests`.
4. `feat(agents): restyle AgentChatPanel to the approved concept (header/intent/bubbles/input + close), with component tests`.
5. `docs: BL-P4 build-log entry` (same commit as 4 or separate, per tracking rule 13).

## 10. Engineering Quality Checklist

- No duplicated business logic: intent resolution reuses `_resolve_instruction_text`; avatar tint reuses `agentCategoryStyle`; no prompt text copied into code.
- Types explicit end-to-end (`intent: string | null` on card, API, and TS type).
- State centralized in the provider; panel stays presentational.
- Race-safety via server-side record reads and the existing spec write path/`preserve_agent_state`.
- Loading/empty/error states specified (§4); accessibility specified (§5).
- Tests cover the regression ("close loses chat") and the single-source intent guarantee.
- No unrelated node/agent functionality modified; `DEC-041` untouched.
