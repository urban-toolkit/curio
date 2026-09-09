# dev/77 — Multiline input in the agent chat

Status: implemented (unstaged, 2026-08-13)

## 1. Problem Statement

The agent chat composer (`AgentChatPanel.tsx:661-672`) is a single-line
`<input type="text">`. Consequences today:

- **Line breaks cannot be entered.** The `onKeyDown` handler already carries
  the intended contract (`Enter && !e.shiftKey` → send), but Shift+Enter is a
  no-op inside an `<input>` — the element cannot hold a newline, so the guard
  is dead code.
- **Pasted multiline text is flattened.** Browsers strip/collapse newlines
  when multiline text is pasted into a single-line input, so a pasted code
  snippet, list, or multi-paragraph prompt reaches the agent as one run-on
  line.
- **The transcript is already ready for newlines and never gets any.**
  `.msgUser` and `.msgAgent` both render with `white-space: pre-wrap`
  (`AgentChatPanel.module.css:365-376, 402-411`), so preserved line breaks
  would display correctly with zero rendering work — the input is the only
  place they are lost.

Affected surface: the AgentChatPanel footer composer, used by every agent
attachment chat, including delegated-agent chats (dev/72 reuses this panel).

Expected behavior: a textarea that starts at one-line height, grows with
content up to a sensible cap, then scrolls internally; Enter sends,
Shift+Enter inserts a newline; paste keeps its formatting; visual style stays
identical to today's pill at single-line height.

Why it matters: users routinely paste structured prompts (code, dataset
descriptions, step lists) to agents; flattening them degrades both what the
agent receives and what the transcript shows. Correctness of the message
payload is the primary concern, usability of composing longer prompts the
secondary one.

## 2. Scope

**In scope**

- `utk_curio/frontend/urban-workflows/src/components/agents/attach/AgentChatPanel.tsx`
  — the footer composer only (lines ~660-683).
- `AgentChatPanel.module.css` — `.input` and `.footer` adjustments for
  multiline growth.
- New shared hook `components/agents/attach/useAutoGrowTextarea.ts`
  (placement follows the dev/76 encapsulation decision: agent-chat transcript
  and composer primitives live in `agents/attach/`, not `src/hook/`).
- Tests: new `tests/attach/useAutoGrowTextarea.test.tsx`, extensions to
  `tests/attach/AgentChatPanel.test.tsx`.

**Code paths that must be checked, not changed**

- `send()` (`AgentChatPanel.tsx:246-259`) — `input.trim()` strips only
  leading/trailing whitespace; interior newlines survive. No change needed.
- Suggested-prompt prefill + `composePrompt` (`AgentChatPanel.tsx:187-199`) —
  set the input value programmatically; the growth logic must re-measure on
  those updates too (handled by keying the measurement on the value, §4).
- Transcript rendering (`pre-wrap` already in place). No change.
- Send-path plumbing (`onSend` → provider → backend): plain string transport;
  newlines are ordinary characters. Verify once in the round-trip test, no
  code change expected.

**Out of scope**

- `LLMChat.tsx` (the LLM Assistant sidebar) — separate surface, same
  limitation, but this issue targets the agent chat. Note as follow-up.
- The intent editor `<textarea className={styles.intentTextarea}>`
  (`AgentChatPanel.tsx:463-468`) — already multiline; adopting the auto-grow
  hook there is optional polish, not part of this change.
- Title rename input, dock, cards, proposals — untouched.

## 3. Recommended Implementation Approach

**a) Shared hook: `useAutoGrowTextarea`**

There is no existing auto-grow utility in the codebase (checked: no
`scrollHeight`-based sizing outside transcript scrolling, no autosize dep).
CSS `field-sizing: content` is not yet cross-browser, so a small hook is the
right primary path:

```
useAutoGrowTextarea({ value, maxHeightPx }) → { textareaRef }
```

- On every `value` change (a `useLayoutEffect` keyed on `value`), set
  `el.style.height = "auto"`, then
  `el.style.height = Math.min(el.scrollHeight, maxHeightPx) + "px"`, and set
  `overflowY` to `auto` only when clamped (else `hidden`, avoiding a
  transient scrollbar flash).
- Keying on the value — not on keystrokes — means programmatic updates
  (suggested-prompt prefill, `composePrompt`, the post-send reset to `""`)
  re-measure for free.
- `useLayoutEffect` so the height is set before paint: no one-frame jump.

**b) Swap the composer element**

Replace the footer `<input>` with `<textarea rows={1}>`:

- Same `className={styles.input}`, same `value`/`onChange` wiring.
- Keep the existing `onKeyDown` handler verbatim — it was already written for
  this contract. Add one guard: ignore Enter while an IME composition is
  active (`e.nativeEvent.isComposing`), so CJK input doesn't send on the
  composition-commit Enter.
- Add `aria-label="Message this agent"` (the placeholder alone is not a
  reliable accessible name once the field has content).
- Paste needs no handler — a textarea preserves pasted newlines natively.

**c) Enter semantics stay where they are**

`Enter` (no Shift, not composing) → `preventDefault()` + `send()`.
`Shift+Enter` falls through to the textarea's default newline insertion.
This matches the handler already in place; only the element changes.

## 4. Data and State Handling

- **Source of truth:** the existing `input` string state (`useState` at
  `AgentChatPanel.tsx:139`). Newlines are just characters in that string; no
  new state is introduced for content.
- **Height is derived, not state:** the hook writes `style.height` directly
  from `scrollHeight`. Keeping it out of React state avoids re-render churn
  per keystroke and any possibility of stale-height flicker.
- **After send:** `setInput("")` triggers the value-keyed measurement, which
  collapses the textarea back to one row in the same paint. `pinToLatest()`
  behavior (dev/75) is unchanged.
- **Prefill interplay (dev/39 rule):** prefills and `composePrompt` continue
  to go through `setInput`; because measurement keys on `input`, a multi-line
  prefill grows the box correctly and a user draft is never overwritten —
  that rule lives upstream and is untouched.
- **Attachment switch:** `input` state currently survives cycling agents
  (pre-existing behavior, unchanged); the measurement effect keeps the height
  matching whatever value is shown.
- **No race conditions:** height writes are synchronous DOM mutations in a
  layout effect; `send()` keeps its `!message || sending` guard.

## 5. UI and UX Requirements

- **Single-line appearance is pixel-identical to today.** `.input` keeps its
  padding, font, background, and focus ring. One adjustment: replace
  `border-radius: 999px` with a fixed radius equal to half the one-row height
  (≈18px given 9px vertical padding and the 12.5px/1.45 line). At one row
  this renders the same pill; when grown it reads as a rounded rectangle
  instead of a distorted stadium.
- **Textarea specifics:** `resize: none` (no manual drag handle), explicit
  `line-height: 1.45`, `font: inherit`-equivalent so growth math is stable.
- **Growth cap:** max height ≈ 6 rows (~120px). Beyond that the textarea
  scrolls internally. The transcript area shrinks naturally because the panel
  is a flex column — verify the messages scroller keeps `min-height: 0` so
  growth never pushes the footer off-panel.
- **Footer alignment:** change `.footer` from `align-items: center` to
  `flex-end` so the send button stays anchored beside the last line as the
  textarea grows (matching common chat composers), rather than floating
  mid-height.
- **No jank:** `useLayoutEffect` sizing means no visible height snap;
  `overflow-y: hidden` until clamped means no scrollbar flicker.
- **Accessibility:** textarea keeps the `textbox` role with
  `aria-multiline="true"` implicit; `aria-label` added; Enter/Shift+Enter is
  the de-facto standard chat convention and Escape (panel close) still works
  since the textarea doesn't consume it.

## 6. Edge Cases

- **Whitespace-only message** (spaces/newlines): `input.trim()` yields `""` →
  send stays disabled / no-op. Already handled; add a test.
- **Interior newlines with trailing newline:** `"a\n\nb\n"` sends as
  `"a\n\nb"` (trim), interior blank line preserved.
- **Pasted large block** (hundreds of lines): height clamps at max, internal
  scroll takes over, no layout blowout.
- **IME composition:** Enter that commits a CJK composition must not send
  (`isComposing` guard).
- **Send while grown:** clearing the value collapses height in the same
  frame; the follow-at-bottom pin (dev/75) still fires.
- **Multi-line suggested-prompt prefill:** box grows without a keystroke.
- **Repeated Enter while `sending`:** guard in `send()` drops it; the draft
  typed during sending is preserved (unchanged behavior).
- **jsdom in tests:** `scrollHeight` is 0 in jsdom, so the hook must tolerate
  a 0 measurement (height becomes minimal, never NaN/negative), and hook
  tests mock `scrollHeight`.
- **Panel resize / narrow dock:** re-wrap changes `scrollHeight`; acceptable
  to re-measure only on value change (matching standard composers) — note
  this as a known, benign limitation.

## 7. Testing Strategy

- **Hook unit tests** (`tests/attach/useAutoGrowTextarea.test.tsx`):
  - sets height from mocked `scrollHeight` on value change;
  - clamps at `maxHeightPx` and flips `overflowY` to `auto`;
  - re-measures when value is set programmatically (prefill path);
  - collapses when value resets to `""`.
- **Component tests** (`tests/attach/AgentChatPanel.test.tsx`):
  - Enter (no shift) calls `onSend` with the trimmed value and clears the
    field (existing behavior, now against a textarea — keep queries working);
  - Shift+Enter does **not** call `onSend`;
  - Enter with `isComposing: true` does not send;
  - `fireEvent.change` with `"line1\nline2"` (the paste-equivalent in jsdom)
    then Enter → `onSend` receives the string with the `\n` intact —
    **this is the regression test for the issue**;
  - whitespace/newline-only input does not send.
- **Round-trip sanity:** one existing transcript-rendering assertion extended
  to confirm a user turn containing `\n` renders inside `.msgUser`
  (pre-wrap does the visual work; the test asserts the text content
  survives).

## 8. Acceptance Criteria

1. Typing Shift+Enter in the agent chat composer inserts a line break;
   the message is not sent.
2. Pressing Enter sends the message exactly as composed (interior newlines
   preserved; only leading/trailing whitespace trimmed) and clears the field
   back to one-row height.
3. Pasting multiline text into the composer preserves every line break, both
   in the composer and in the sent user bubble.
4. The composer grows as content wraps or newlines are added, up to ~6 rows,
   then scrolls internally; the transcript and footer never overflow the
   panel.
5. At one line of content, the composer is visually indistinguishable from
   the current pill input (padding, colors, focus ring, radius at that
   height).
6. Suggested-prompt chips and candidate composition still prefill correctly,
   including multi-line prefills, and never clobber a user draft (dev/39
   rule intact).
7. IME users can commit compositions with Enter without accidentally
   sending.
8. No bespoke sizing logic lives inline in `AgentChatPanel` — growth comes
   from the shared `useAutoGrowTextarea` hook.

## 9. Recommended Commit Breakdown

1. **Commit 1 — hook + tests:** `useAutoGrowTextarea` in
   `components/agents/attach/` with its unit tests.
2. **Commit 2 — composer swap:** `AgentChatPanel` input → textarea (keydown
   guard incl. `isComposing`, aria-label), `.input`/`.footer` CSS
   adjustments; update any component-test queries broken by the element
   change.
3. **Commit 3 — regression coverage:** multiline send/paste-preservation and
   Shift+Enter/IME tests, plus the transcript newline round-trip assertion.

## 10. Engineering Quality Checklist

- Growth logic centralized in one hook; no duplicated sizing code (and a
  clear adoption path for the intent editor and LLMChat later).
- No new state for derived height; no per-keystroke re-renders beyond the
  existing controlled-input update.
- Types explicit on the hook's options/return.
- Existing behaviors preserved: send guard, prefill rules (dev/39),
  follow-at-bottom pin (dev/75), Escape-to-close.
- Loading/disabled states unchanged and re-verified.
- Accessibility: named textbox, standard chat key convention, no keyboard
  traps.
- Tests cover the core contract (Enter/Shift+Enter), the regression (paste
  preserves `\n`), and edge cases (IME, whitespace-only, clamp).
- Styling stays within the existing module; single-line rendering unchanged.
