# Implementation Memo: Auto-Generated Descriptive Titles for Agent Conversation Instances

Status: IMPLEMENTED 2026-07-23 (backend + frontend + tests, including manual rename)
Branch context: `feat/hookable-agents`
Date: 2026-07-23

Feature: automatically generate a descriptive title for each attached-agent conversation
instance, displayed as `<Template Name>: <Custom Title>` (e.g. `Chat: Dataset Import Help`),
derived from the user's first meaningful message via an LLM call. The custom portion can
also be renamed manually via single-click inline editing in the chat header; a manually
edited title takes precedence over generation, is never auto-overwritten, and survives
conversation clears. The underlying agent template is never renamed.

---

## 1. Problem Statement

**Current behavior.** Every attached agent instance is displayed using the template
manifest's name only. The backend assembles it at read time in `_attachment_card()`
(`utk_curio/backend/app/agents/services.py:404-425`, `"name": m.name if m else coord`),
and every frontend surface renders that same `attachment.name`:

- Dock tooltip and badge aria-labels — `AgentAvatarBadge.tsx:27,38,48`
- Opened chat header — `AgentChatPanel.tsx:144,160`
- Node badges — `NodeAgentBadges.tsx:23-33` (via the same badge component)

**Why it matters.** When two or more instances of the same template are attached (e.g. two
"Chat" agents on different nodes), they are visually indistinguishable in the dock, the
tooltip, and the chat header. The only differentiator today is the raw `sessionId` chip in
the chat panel, which is meaningless to users. This hurts usability directly and gets worse
as the hookable-agents feature encourages multiple attachments.

**Expected behavior.** After a user sends their first meaningful message to an instance,
the system generates a concise three-to-four-word title from that message and displays
`"<Template Name>: <Custom Title>"` on every surface that identifies the instance. Before
any message exists, the display stays the plain template name. The user can rename the
custom portion at any time by clicking the displayed title once in the chat header — the
agent-name prefix stays fixed, and a manual title permanently opts the instance out of
automatic generation. The underlying agent template is never renamed.

## 2. Scope

**In scope**

Backend (`utk_curio/backend/app/agents/`):

- `attachments.py` — persist an optional `title` plus a `titleEdited` flag on the
  attachment record; new `set_title()` mutator mirroring `set_intent()` (lines 137-157),
  taking an auto/manual origin so manual writes set `titleEdited`.
- `services.py` — title generation in the run path (`_prepare_run` / `run_attachment` /
  `stream_attachment`, ~lines 563-691); a manual-title update service mirroring
  `update_attachment_intent()` (lines 474-486); expose `title`/`titleEdited` in
  `_attachment_card()`; clear the title in the conversation-clear service **only when it
  was not manually edited**.
- `providers.py` — no changes; reuse `run_chat_completion()` as-is.
- `routes.py` — no new endpoint required; extend the existing
  `PATCH …/attachments/<aid>` (lines 269-289) to accept `title` alongside `intent`;
  run/stream responses and the attachment listing already flow through
  `_attachment_card`.

Frontend (`utk_curio/frontend/urban-workflows/src/`):

- `api/agentsApi.ts` — add `title: string | null` and `titleEdited: boolean` to
  `AgentAttachment` (lines 41-60); new `updateAttachmentTitle()` mirroring
  `updateAttachmentIntent()` (lines 252-262).
- New shared display helper (one pure function) composing
  `title ? \`${name}: ${title}\` : name`.
- Render sites: `AgentAvatarBadge.tsx`, `AgentChatPanel.tsx` (dock, node badges, and
  overlay inherit through these); the chat-header title in `AgentChatPanel.tsx`
  additionally becomes the single-click inline title editor.
- `AgentAttachmentsProvider.tsx` — refresh the title after the first exchange completes;
  new `saveTitle` action mirroring `saveIntent` (lines 169-177).

Tests: `backend/tests/test_agents/` (pytest) and `frontend/.../src/tests/attach/`,
`src/tests/api/` (Jest/RTL).

**Out of scope**

- The agents catalog drawer (`AgentsCatalogDrawer.tsx`) — it lists *templates*, not
  instances; it must keep showing plain template names.
- `AgentSettingsModal.tsx` — its `data?.name` is the template/project-default name,
  untouched.
- Renaming from the dock tooltip, avatar badges, or node badges — those surfaces stay
  display-only (clicking a badge opens the chat); inline editing lives in the chat header
  exclusively.
- Removing a manual title to re-enable auto-generation — submitting an empty field
  cancels the edit rather than deleting the title; a "reset title" affordance is a
  possible follow-up.
- Template manifests (`manifest.py`) and the catalog `AgentCard` shape.
- `preserve_agent_state` (`project_agents.py:113-150`) — no change needed; `title` lives
  inside `agentAttachments`, which is already in `_AGENT_SPEC_KEYS`, so it is automatically
  preserved across canvas saves.
- Provider selection logic — titles use whatever `resolve_provider_config(user)` already
  yields (default `gemma4`).

## 3. Recommended Implementation Approach

**Store the title server-side on the attachment record**
(`spec["dataflow"]["agentAttachments"]`), exactly like `intent`. This is the established
home for per-instance, backend-owned state, and it survives publish/save cycles for free
via `preserve_agent_state`.

**Generate the title server-side in the run path.** Both `run_attachment` and
`stream_attachment` already call `_prepare_run()`, which reads
`prior = sessions.read_turns(...)` (`services.py:582`). The trigger condition: the record
has no `title` **and** `prior` contains no user turn — i.e., the incoming `message` is the
first meaningful one. Generation is a second, small, non-streaming `run_chat_completion()`
call with the resolved `ProviderConfig`, a fixed system prompt ("Summarize this request as
a 3–4 word title. Reply with the title only."), and a small `max_output_tokens` (~16).

Key properties of the generation call:

- **Best-effort and non-blocking for the reply.** Wrap in try/except; on any provider
  error or garbage output, persist nothing. Because the trigger is `title is None`, a
  failed attempt retries naturally only if the transcript is still empty — after the first
  successful exchange, a failed title simply leaves the instance untitled rather than
  re-firing on every message. Run it *after* the main reply is produced (after
  `_persist_exchange` in the blocking path; after the `done` branch,
  `services.py:687-689`, in the streaming path) so title latency never delays the agent's
  answer.
- **Sanitize the output**: strip quotes/newlines, collapse whitespace, cap at ~40
  characters, reject empty results. The user's message is untrusted input to the prompt,
  so treat the model output as untrusted too — plain-text truncation, never rendered as
  markup.
- **Composition happens at display time, not in storage.** Store only the custom portion
  (`"Dataset Import Help"`); never bake the template name into the stored value, so a
  template rename later doesn't strand stale prefixes.

**Expose `title` as a separate field** in `_attachment_card()` rather than folding it into
`name`. Folding would be zero frontend changes, but it conflates template identity with
instance identity, pollutes contexts that want the raw name, and makes "preserve the
original agent name as the prefix" a backend formatting concern. Instead: `name` stays the
template name; `title` is nullable; a single frontend helper (e.g.
`attachmentDisplayName(attachment)` next to the attach components) does the
`"name: title"` composition. All four render sites call the helper — no duplicated string
logic.

**Manual renaming clones the `intent`/`intentEdited` pattern end-to-end.** The codebase
already models "server-owned field with a user-edited override flag": `set_intent()`
stores the value and bumps `revision`, `intentEdited` marks user authorship,
`PATCH …/attachments/<aid>` carries the update, and `saveIntent` →
`updateAttachmentIntent` → `reload()` closes the loop. Mirror every piece for `title`:

- `set_title(value, edited)` in `attachments.py` — auto-generation calls it with
  `edited=False`; the PATCH path calls it with `edited=True`.
- **Precedence rule, enforced at every write site:** auto-generation persists only if, at
  write time under the spec lock, `title is None` **and** `titleEdited` is falsy. A manual
  edit at any moment — before the first message, mid-stream, or after — wins permanently;
  no later message or regeneration path may touch it. Conversation-clear resets the title
  only when `titleEdited` is falsy.
- The PATCH handler validates server-side: trim, reject empty/whitespace-only, enforce
  the same ~40-char cap as the sanitizer, plain text only.

**Inline editor in the chat header only.** The visible header title
(`AgentChatPanel.tsx:160`) becomes a click-to-edit control: a single click swaps the
custom portion for an inline text input while the `"<Template Name>: "` prefix remains
static text beside it. No separate edit button or icon — the affordance is the click
target itself (plus hover styling and an accessible name). Enter or blur commits via
`saveTitle`; Escape cancels and restores the previous display. Badges and tooltips render
the composed title but are not editable.

**Frontend refresh after generation.** The title is created server-side during the first
run, but the frontend's `attachments` array was fetched before it existed. Reuse the
existing refresh pattern: `saveIntent` already calls `state.reload()`
(`AgentAttachmentsProvider.tsx:169-177`), and `useAgentAttachments` listens for
`curio:agent-dock-refresh`. In `sendMessage`, after the run/stream completes, call
`reload()` **only when the attachment had no title before the send** — this avoids a
listing round-trip on every message. (Alternative considered: emit the title as a terminal
SSE event. Cleaner long-term, but it adds a protocol change to both stream parser and
blocking fallback for marginal benefit; the conditional reload matches existing
conventions.)

## 4. Data and State Handling

- **Source of truth:** `record["title"]` plus `record["titleEdited"]` inside
  `agentAttachments` in the project spec, written under the same spec write-lock/mutator
  discipline as `set_intent` (with a `revision` bump so the frontend's revision-based
  reconciliation sees the change). `titleEdited` is the single authority on manual
  precedence; the frontend never infers it.
- **Derived value:** the display string `"<name>: <title>"` is computed by the one
  frontend helper; nothing stores the composed string.
- **Flow:** first user message → run/stream endpoint → main reply persisted → title
  generated and persisted (best-effort) → frontend `sendMessage` completes → conditional
  `reload()` → `attachments` state carries `title` → all badge/header/tooltip surfaces
  re-render via context.
- **Loading/empty states:** while `title` is null (before first message, during
  generation, or after a failed generation), every surface shows the plain template name —
  no placeholder, no spinner. The title appearing is a quiet upgrade, not a loading state.
- **Manual edit flow:** click header title → local edit state in `AgentChatPanel`
  (initialized from the current custom portion, or empty when none exists) → Enter/blur →
  `saveTitle` → `PATCH` → `reload()` (same shape as `saveIntent`). Escape or an
  empty/unchanged submit discards the local state with no request.
- **After clear conversation:** `clearConversation` also clears an **auto-generated**
  title (service-side, in the same mutation), since it describes a conversation that no
  longer exists; the next first message regenerates it. A **manually edited** title
  (`titleEdited` true) is retained untouched — the user named the instance deliberately,
  and the clear must not undo that.
- **Staleness/races:** generation is keyed on `title is None and not titleEdited`,
  checked at write time under the spec lock, so two rapid first messages can't produce
  dueling titles, and a manual edit landing while a reply streams beats the post-reply
  auto-write — the generator re-checks and skips. The conditional reload avoids flicker:
  the name never blanks out; it only ever gains a suffix.

## 5. UI and UX Requirements

- **Format:** exactly `<Template Name>: <Custom Title>`, custom portion 3–4 words. With no
  title: template name only, no trailing colon.
- **Surfaces (all via the shared helper):**
  - Dock hover tooltip (`AgentAvatarBadge.tsx:48`) — full composed title.
  - Badge aria-labels (`AgentAvatarBadge.tsx:27,38`) — `Open chat with <composed>` /
    `Detach <composed>`, so screen-reader users can distinguish instances too.
  - Chat header visible title (`AgentChatPanel.tsx:160`) and panel aria-label (line 144).
  - Node badges inherit through `AgentAvatarBadge`.
- **Overflow:** the chat header and tooltip must ellipsize long composed titles (CSS
  truncation) rather than wrap or push the header controls; the 40-char server cap keeps
  this rare.
- **No layout shift:** the title arrives as a text change on existing elements — no
  re-mount, no clearing, no skeleton.
- **Inline editing (chat header only):**
  - A single click on the header title enters edit mode: the custom portion becomes a
    text input in place; the `"<Template Name>: "` prefix stays as static text before it
    and is never editable. When no custom title exists yet, the click opens an empty
    input after the prefix — saving it sets a manual title and blocks auto-generation.
  - No separate edit button or icon. Editability is signaled by hover styling (e.g.
    subtle underline/background) and a tooltip such as "Click to rename".
  - Enter commits; clicking/tabbing outside (blur) commits; Escape cancels and restores
    the previous display. On commit the input swaps back to text immediately (optimistic
    display of the trimmed value), reconciled by the reload.
  - Entering edit mode focuses the input with the current value selected; leaving edit
    mode returns focus to the title element. The input carries `maxLength` matching the
    server cap.
  - **Accessibility:** the display title is a focusable control (button semantics) with
    an accessible name like `Rename conversation title`, activatable by Enter/Space —
    click-only activation is not acceptable. The input gets an `aria-label`; Escape/Enter
    behavior follows standard editable-label patterns.
- **Catalog drawer and settings modal remain template-name-only** — a user comparing the
  roster of installable agents should not see one instance's conversation topic there.

## 6. Edge Cases

- **First message is trivial** ("hi", "test"): the LLM will still emit something; accept
  it — "meaningful" is approximated by "first non-empty user turn", which the routes
  already validate. Refining meaningfulness heuristics is not worth the complexity.
- **Provider unavailable / `ProviderConfigError` / timeout:** main reply already failed or
  succeeded on its own; title generation independently no-ops. Never surface a
  title-generation error to the user.
- **Garbage LLM output** (empty string, whole-sentence answer, quotes, markdown, the
  prompt echoed): sanitize; if the result is empty after sanitizing or degenerate after
  truncation, persist nothing.
- **Streaming disconnect mid-reply:** title generation runs only after the `done` branch;
  an aborted stream persists no title and retries on the next first-message attempt (the
  transcript may now be non-empty — then the instance stays untitled, acceptable).
- **Two instances of the same template, same first message:** both get titles
  independently; identical titles are possible and acceptable (still better than today).
- **Intent-pinned agents:** the pinned `intent` is not a session turn (`record["intent"]`
  is separate from the transcript), so the trigger on "no prior user turns" is unaffected;
  the title derives from the first actual user message, which is correct.
- **Publish → uninstall → reinstall / canvas save:** `title` rides in `agentAttachments`,
  preserved by `preserve_agent_state`; verify with a test rather than assuming.
- **Clear conversation then immediately re-message:** an auto-generated title is cleared
  with the transcript and regeneration fires on the new first message; a manually edited
  title is retained and suppresses regeneration.
- **Manual edit before any message:** valid — sets `titleEdited`, so auto-generation
  never fires for this instance.
- **Manual edit while a reply is streaming:** the PATCH lands independently; the
  post-reply auto-generation re-checks `titleEdited` under the spec lock and skips.
- **Empty or whitespace-only submit:** treated as cancel — nothing persisted, previous
  display restored (deleting a manual title is out of scope).
- **Submit with unchanged value:** no PATCH, no revision bump.
- **Over-long manual input:** client `maxLength` prevents it; the server independently
  trims and rejects values over the cap (never trust the client).
- **Panel closed or attachment detached mid-edit:** local edit state is discarded; an
  in-flight PATCH either lands (title persisted) or fails against a gone attachment with
  a standard error — no crash, no orphan write.
- **Legacy attachments without the fields:** `record.get("title")` defaults to `None`,
  `record.get("titleEdited")` to falsy; `_attachment_card` emits `title: null`,
  `titleEdited: false`. No migration needed.

## 7. Testing Strategy

**Backend (pytest, `tests/test_agents/`)**

- `test_attachments.py`: `set_title` unit tests — sets value, bumps `revision`, sets
  `titleEdited` only for manual writes, rejects unknown attachment; `attach()` records
  omit `title` initially; clear-conversation clears an auto title but retains a manual
  one.
- `test_routes.py` (integration, patching `services.run_chat_completion` per the existing
  convention at lines 344-359): first run on an empty session triggers a second LLM call
  with the title prompt and persists a sanitized title; second run does not re-trigger;
  failed title call still returns a successful reply and leaves `title` null; attachment
  listing includes `title`/`titleEdited`; streaming path sets the title after `done`.
- PATCH route tests (alongside the existing intent tests at lines 594-680): accepts
  `title`, sets `titleEdited`, bumps `revision`; rejects empty/whitespace-only and
  over-cap values; a manually titled attachment's next run performs no title LLM call;
  manual edit racing a run never gets overwritten by the auto-write.
- Sanitizer unit tests: quotes/newlines stripped, 40-char cap, empty → rejected.
- `test_preserve_agent_state.py`: a record with `title` survives a client canvas save.

**Frontend (Jest + RTL)**

- Display-helper unit tests: with title → `"Name: Title"`; without → `"Name"`.
- `AgentAvatarBadge.test.tsx` / `AgentChatPanel.test.tsx`: composed title in tooltip,
  header, and aria-labels; plain name when `title` is null.
- `AgentChatPanel.test.tsx` inline-editor tests: single click (and Enter/Space on the
  focused title) enters edit mode with the prefix still rendered as static text; Enter
  and blur commit via `saveTitle`; Escape cancels and restores the previous value; empty
  and unchanged submits make no request; no edit button/icon is rendered.
- `AgentAttachmentsProvider.test.tsx`: `sendMessage` on a title-less attachment triggers
  `reload()` after completion; a titled attachment's send does not; `saveTitle` PATCHes
  then reloads (mirroring the `saveIntent` tests).
- `agentsApi.test.ts`: `AgentAttachment` parsing tolerates missing/`null`
  `title`/`titleEdited`; `updateAttachmentTitle` sends the expected PATCH body.

Required before completion: the route-level first-message trigger tests, the sanitizer
tests, the badge/header render tests, and the inline-editor commit/cancel/precedence
tests — these cover the regression surface.

## 8. Acceptance Criteria

1. Sending the first message to a newly attached agent results (after the reply completes)
   in the dock tooltip, badge aria-labels, and chat header all reading
   `<Template Name>: <3–4 word title>` without a page reload.
2. Before any message, and whenever generation fails, all surfaces show the plain template
   name with no colon and no error.
3. Subsequent messages never change or regenerate an existing title (auto or manual);
   per-message traffic does not include a title LLM call.
4. Clearing a conversation removes an auto-generated title and the next first message
   generates a fresh one; a manually edited title is retained by the clear and is never
   regenerated.
5. The agents catalog drawer and settings modal continue to show template names only; the
   template manifest is byte-identical.
6. The title survives canvas save/refresh (via `preserve_agent_state`) and appears in the
   attachments listing response as a distinct `title` field.
7. The agent's reply latency is unaffected by title generation (title call runs after the
   reply is persisted/streamed).
8. Long titles ellipsize in the header/tooltip without layout shift; titles are plain text
   (no markup rendering).
9. A single click on the chat-header title (or Enter/Space with it focused) puts only the
   custom portion into an inline editable field, with the agent-name prefix rendered as
   fixed text; no separate edit button or icon exists anywhere.
10. Enter or clicking outside the field commits the edit; the saved title immediately
    appears on the header, dock tooltip, and badges, and persists across reopening the
    chat and reloading the project. Escape cancels with no change; empty or unchanged
    submits persist nothing.
11. A manually edited title is never overwritten by automatic generation, later
    messages, or conversation clears; after a manual edit no title LLM calls occur for
    that instance.

## 9. Recommended Commit Breakdown

1. **Backend storage + exposure:** `title` on the attachment record, `set_title`,
   clear-on-clear-conversation, `title` in `_attachment_card`, with `test_attachments.py`
   + listing tests.
2. **Backend generation:** first-message trigger in run/stream paths, title prompt,
   sanitizer, best-effort error handling, with route-level tests patching
   `run_chat_completion`.
3. **Frontend display:** `AgentAttachment.title`, shared display helper,
   badge/header/aria updates + ellipsis CSS, with helper and component tests.
4. **Manual rename, backend:** PATCH `title` support, `titleEdited` flag, precedence
   guards on the auto-write and conversation-clear paths, server-side validation, with
   route and attachment tests.
5. **Manual rename, frontend:** `updateAttachmentTitle` + `saveTitle`, the chat-header
   inline editor (click-to-edit, Enter/blur/Escape, accessibility), with component tests.
6. **Frontend refresh + regression:** conditional `reload()` in `sendMessage`, provider
   tests, and the preserve-agent-state regression test.

## 10. Engineering Quality Checklist

- Composition logic lives in exactly one frontend helper; storage holds only the custom
  portion — no duplicated formatting, no baked-in prefixes.
- `title` is `string | null` end-to-end; legacy records need no migration.
- Generation is idempotent (guarded on `title is None and not titleEdited` under the
  spec lock), post-reply, and failure-silent — no added latency, no race between rapid
  sends or against a concurrent manual edit.
- The manual-precedence guard (`titleEdited`) is checked at every title write site
  (auto-generation and conversation-clear); manual writes are validated server-side.
- The inline editor is keyboard-accessible (focusable, Enter/Space to edit, Escape to
  cancel) — not click-only.
- Conditional reload prevents a listing fetch per message and prevents flicker (name only
  ever gains a suffix).
- Aria-labels updated alongside visible text, so assistive tech distinguishes instances
  too.
- Template-scoped surfaces (catalog, settings) verified untouched.
- Tests follow the existing conventions: `monkeypatch` on `services.run_chat_completion`
  backend-side, RTL component tests frontend-side.

---

**Decision (confirmed 2026-07-23):** clearing a conversation also clears the title — the
title tracks the transcript's lifecycle, and the next first message regenerates it.
**Amended same day with the manual-editing scope:** this applies to auto-generated titles
only. A manually edited title (`titleEdited` true) survives conversation clears, is never
auto-regenerated or overwritten, and persists with the attachment across reopen/reload.
§4, §6, and §8 above are binding as written.
