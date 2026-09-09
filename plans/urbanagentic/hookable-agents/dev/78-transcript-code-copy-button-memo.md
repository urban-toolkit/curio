# dev/78 — Copy button on transcript code blocks

Status: implemented (2026-08-14). BL-P5-20260814-23. Commits `dafd61f6` / `1ed4a707` / `e1bbcc73`. Recorded deviations: none

## 1. Problem Statement

Agent chat transcripts render fenced code blocks (agents frequently emit
Python/SQL/JSON snippets), but there is no way to copy one except manual
text selection inside a scrollable bubble:

- Fenced code renders through `SafeAgentContent`
  (`components/agents/content/SafeAgentContent.tsx`) via react-markdown's
  default `<pre><code>` handling — display only, no actions.
- Selecting text inside `.msgAgent pre` is fiddly: the block has
  `overflow-x: auto` (`AgentChatPanel.module.css:511-518`), so long lines
  require horizontal scrolling mid-selection, and a sloppy selection drags
  in surrounding bubble text.
- There is **no clipboard integration anywhere in the frontend today**
  (verified: zero hits for `navigator.clipboard` / `execCommand` /
  `ClipboardItem` outside node_modules), so nothing can be reused — this
  change introduces the first one.

Affected surface: every agent chat transcript — `AgentChatPanel` renders
all agent turns through `SafeAgentContent`, including delegated-agent
chats (dev/72 reuses the panel). Other ReactMarkdown surfaces (LLMChat,
FloatingPanel, NodeExplanation) use bare `<ReactMarkdown>` and are separate
surfaces.

Expected behavior: each fenced code block shows a compact Copy control on
the block itself; clicking it puts exactly the code content on the
clipboard — no ``` fences, no language tag, no neighboring transcript
text — and the control briefly confirms success ("Copied" + check icon)
before reverting.

Why it matters: copy-out is the primary way users act on agent-suggested
code (paste into a node editor, a terminal, a query console). Manual
selection is error-prone (truncated lines, leading prompt text), and every
comparable chat UI ships this affordance, so its absence reads as a gap.

## 2. Scope

**In scope**

- `components/agents/content/SafeAgentContent.tsx` — add a `pre` entry to
  the existing `components` map (alongside `a`/`img`), routing fenced
  blocks through the new component.
- New `components/agents/content/AgentCodeBlock.tsx` +
  `AgentCodeBlock.module.css` — the block wrapper with the Copy button
  (mirrors the `TranscriptJumpButton` small-presentational-component
  pattern: own module CSS, aria-label, no business logic).
- New pure utility `extractNodeText` (exported from `AgentCodeBlock.tsx`
  or a sibling `extractNodeText.ts`) — derives the raw code string from
  the rendered children.
- Tests: new `tests/content/AgentCodeBlock.test.tsx`; extensions to
  `tests/content/SafeAgentContent.test.tsx`; one integration assertion in
  `tests/attach/AgentChatPanel.test.tsx`; a jsdom clipboard mock (local to
  the tests, not global `setupTests.ts`).

**Code paths that must be checked, not changed**

- `.msgAgent pre` / `.msgAgent code` rules
  (`AgentChatPanel.module.css:511-521`) — the `<pre>` stays a real `<pre>`
  inside the wrapper, so these descendant selectors keep matching. Verify
  visually; no rule changes expected beyond the new module file.
- `.msgAgent` sets `white-space: pre-wrap`
  (`AgentChatPanel.module.css:408`) — the wrapper/button must reset to
  `normal` in the new module CSS or the control inherits pre-wrap.
- REQ-SEC-002 policy in `SafeAgentContent` (no raw HTML, URL sanitizing) —
  untouched; the `pre` override adds chrome around already-inert text.
- Transcript auto-scroll (dev/75/76) — the button adds constant-height
  chrome only when hovered/focused if absolutely positioned (it is, §5),
  so no layout shift and no scroll-contract interaction.

**Out of scope**

- `LLMChat.tsx`, `FloatingPanel.tsx`, `NodeExplanation.tsx` — bare
  ReactMarkdown, separate surfaces. Same follow-up posture as dev/77's
  LLMChat note: if cross-surface copy is wanted later, the lever is
  extracting a shared `components` map, not duplicating the button.
- Plain non-markdown `<pre>` usages (`AgentReviewCard.tsx:352` stderr
  tail, `OutputContent.tsx`, `PackageManagerWindow.tsx`) — different
  contracts (diagnostics, outputs), not chat code suggestions.
- Syntax highlighting, language badges, line numbers, "insert into node"
  actions — explicitly not part of this change.
- Inline code spans (single-backtick) — no button; only fenced blocks.

## 3. Recommended Implementation Approach

**a) Hook point: a `pre` override in `SafeAgentContent`**

react-markdown@10 renders a fence as `<pre><code class="language-x">…</code></pre>`
and lets `components.pre` replace the outer element. Overriding `pre`
(not `code`) is the discriminator for free: inline code never has a
`<pre>` parent, so it is untouched without any inline-vs-block check.

```tsx
components={{
  a: …, img: …,                       // unchanged
  pre: ({ children }) => <AgentCodeBlock>{children}</AgentCodeBlock>,
}}
```

Because `SafeAgentContent` is the ONLY renderer for agent rich content
(dev/39 contract), this single hook covers every agent chat surface,
delegated chats included.

**b) `AgentCodeBlock` component**

```tsx
<div className={styles.block}>
  <pre>{children}</pre>
  {code ? <button …>copy</button> : null}
</div>
```

- `code` is derived once per render via `extractNodeText(children)` — a
  small recursive reducer over React children (string → itself, array →
  join, element → recurse into `props.children`). For a normal fence the
  children are one `<code>` element wrapping a string, but the recursive
  form is trivially robust and unit-testable as a pure function.
- Normalization: strip exactly one trailing `\n` (the parser-supplied
  fence terminator); interior newlines and indentation are copied verbatim.
  No trimming of leading whitespace — indentation is content.
- Empty/whitespace-only block (```` ``` ```` with nothing in it): render
  the `<pre>` but no button — a Copy control that copies nothing is noise.
- Copy action: `navigator.clipboard.writeText(code)`. **Primary path
  only, no `document.execCommand` fallback** — the app runs on
  localhost/HTTPS (secure contexts where the async API exists), and a
  failed copy must be loud, not silently half-work: the catch path flips
  the button into a transient "Failed" state.
- Feedback state machine: `"idle" | "copied" | "failed"`, reverting to
  `idle` after ~1.8 s via a timeout held in a ref — cleared on unmount and
  on re-click (rapid clicks restart the window rather than stacking
  timeouts).

**c) Icons and visual language**

FontAwesome is already the icon system (`faCopy` is already imported
elsewhere in the repo; add `faCheck` for the copied state). The button
follows the compact icon-button pattern of `.intentEdit` / the suggested
chips: hairline `#ececee`, soft `#f7f7f8` surface, small radius,
`font-size` in the 0.7rem range.

## 4. Data and State Handling

- **Source of truth for the copied text:** the rendered children of the
  fence — the same inert text REQ-SEC-002 already guarantees. No re-parse
  of the raw markdown, so the copied string can never disagree with what
  the block displays.
- **Derived, not stored:** the code string is computed during render
  (`useMemo` keyed on `children` is sufficient; blocks are small). No
  state mirrors the content.
- **Only UI state is the feedback status** (`useState<"idle"|"copied"|"failed">`),
  local to each block — two blocks in one message have independent
  buttons. Timeout id lives in a ref; the cleanup effect clears it so an
  unmounted block (message re-render, panel close) never sets state late.
- **Async safety:** `writeText` resolves/rejects; both paths set state
  only via the mounted component (guarded by the cleanup pattern above).
  No races beyond the single timeout, which is reset-on-click.
- **Streaming/turn updates:** if a turn re-renders mid-feedback, the block
  remounts and the state resets to idle — acceptable and invisible in
  practice (feedback window is 1.8 s).
- No loading state (copy is near-instant); failure state is the error
  surface.

## 5. UI and UX Requirements

- **Placement:** button absolutely positioned in the top-right corner of
  the block, inside a `position: relative` wrapper; the `<pre>` gets
  enough right padding (or the button a translucent backdrop) so it never
  sits on top of unscrolled code.
- **Compactness:** icon-only (`faCopy`, ~12px) with `aria-label="Copy
  code"` and `title`; in feedback states it shows icon + short text
  ("Copied" / "Failed") to make the confirmation legible.
- **Reveal behavior:** always rendered but subtle (reduced opacity),
  full-opacity on block hover, on `:focus-visible`, and while in a
  feedback state. Hover-only reveal is rejected: it is undiscoverable and
  unusable on touch; a permanently subtle control matches the quiet
  chrome of the bubbles.
- **Feedback:** icon swaps to `faCheck` + "Copied" for ~1.8 s, then
  reverts. Failure shows "Failed" in the existing error hue
  (`.msgError`'s `#b3261e` family) for the same window. No toasts, no
  layout shift — the button's box reserves its size (min-width or
  fixed-height) so idle↔copied does not shift the block.
- **Style tokens:** hairline `#ececee`, surface `#f7f7f8`/
  `var(--curio-card-bg)`, text `#555`-range secondary; radius 6px;
  consistent with `.suggestedChip` / `.intentEdit`. `white-space: normal`
  on the wrapper's chrome (the `.msgAgent` pre-wrap caveat, §2).
- **Accessibility:** a real `<button type="button">`; accessible name
  flips with the state ("Copy code" → "Copied" → "Copy failed") and the
  feedback text sits in an `aria-live="polite"` region so screen readers
  hear the confirmation; keyboard reachable in transcript tab order;
  focus ring never clipped by the `<pre>`'s `overflow-x: auto` (the
  button lives outside the scrolling element, on the wrapper).
- **No jank:** absolute positioning + reserved button size ⇒ zero layout
  shift on hover or state change; the transcript scroll pin (dev/75) sees
  no height change.

## 6. Edge Cases

- **Multiple fences in one message:** each block gets its own button and
  its own feedback state; copying one never flips another.
- **Fence with language tag** (```` ```python ````): the tag lives in the
  `<code>` className, never in text content — copied string excludes it
  by construction. Test locks this in.
- **Trailing newline:** parser emits `"code\n"`; exactly one trailing
  newline is stripped, interior blank lines preserved
  (`"a\n\nb\n"` → copies `"a\n\nb"`).
- **Empty fence:** no button (§3b).
- **Very long/wide block:** button stays pinned top-right of the visible
  box (wrapper-anchored, not content-anchored) while the `<pre>` scrolls
  horizontally beneath it.
- **Clipboard API missing or rejecting** (permissions policy, browser
  quirk, jsdom): catch → "Failed" feedback, console.warn with the error;
  never a silent no-op and never a crash.
- **Rapid repeated clicks:** each click rewrites the clipboard and
  restarts the feedback timer; stale timers are cleared, so no flicker
  back to idle mid-confirmation.
- **Unmount during feedback window** (panel closed, agent cycled):
  timeout cleared on cleanup; no setState-after-unmount warning.
- **Hostile content** (RISK-RENDER-001): a fence containing
  `<script>…</script>` copies that text verbatim as inert characters —
  same guarantee the renderer already makes for display; the button adds
  no HTML interpretation anywhere.
- **jsdom in tests:** `navigator.clipboard` is undefined — tests define a
  mock (`Object.defineProperty`) per-suite; the component's catch path
  also makes an unmocked environment fail loudly rather than throw.

## 7. Testing Strategy

- **Unit — `extractNodeText`** (pure function): string child; `<code>`
  element wrapping a string; nested arrays; `null`/`undefined` children →
  `""`.
- **Component — `tests/content/AgentCodeBlock.test.tsx`** (clipboard
  mocked, fake timers):
  - click → `writeText` called with exactly the code content (no fences,
    no language tag, single trailing newline stripped) — **the core
    regression test**;
  - success feedback: accessible name flips to "Copied", reverts to
    "Copy code" after the window;
  - `writeText` rejection → "Copy failed" state, then reverts;
  - two blocks: clicking one leaves the other idle;
  - empty fence renders no button;
  - unmount during the feedback window triggers no act() warning
    (timeout cleared).
- **Renderer — `tests/content/SafeAgentContent.test.tsx`** (extend the
  existing suite next to "renders code fences as inert text"):
  - a fenced block renders one Copy button; inline `` `code` `` renders
    none;
  - hostile fence (`<script>` body): still no `<script>` element, and the
    button's copy payload is the literal text (policy regression);
  - existing assertions (pre textContent) still pass with the wrapper in
    place.
- **Integration — `tests/attach/AgentChatPanel.test.tsx`:** one assertion
  that an agent turn containing a fence renders the Copy button inside
  `.msgAgent` (wiring proof; behavior is covered at component level).
- Verification gate: full `npx jest` (813-test baseline stays green) +
  `tsc --noEmit`.

## 8. Acceptance Criteria

1. Every fenced code block in an agent transcript bubble shows a compact
   Copy control on the block itself; inline code spans show none.
2. Clicking Copy places exactly the code content on the clipboard: no
   ``` fences, no language tag, no surrounding transcript text; interior
   newlines and indentation intact; at most one trailing newline removed.
3. After a successful copy the control shows a check + "Copied" for
   roughly two seconds, then reverts; a failed copy shows a visible
   failure state instead of silently doing nothing.
4. Multiple code blocks in one message operate independently.
5. The control is keyboard-operable, has an accessible name that reflects
   its state, and announces the confirmation politely to screen readers.
6. No layout shift, flicker, or transcript scroll jump occurs on hover,
   copy, or feedback revert; existing bubble/code styling is visually
   unchanged apart from the new control.
7. The change lives entirely in the safe-renderer path: `SafeAgentContent`
   remains the only renderer for agent rich content, and the REQ-SEC-002
   hostile-content tests still pass.
8. All copy/feedback logic is in `AgentCodeBlock`; no clipboard code is
   duplicated in `AgentChatPanel` or elsewhere.

## 9. Recommended Commit Breakdown

1. **Commit 1 — component + tests:** `AgentCodeBlock.tsx` (+
   `extractNodeText`) and `AgentCodeBlock.module.css` in
   `agents/content/`, with the full component/unit test suite and the
   jsdom clipboard mock.
2. **Commit 2 — renderer wiring:** the `pre` override in
   `SafeAgentContent.tsx`; extend `SafeAgentContent.test.tsx` (button
   presence, inline-code exclusion, hostile-fence policy regression).
3. **Commit 3 — integration + polish:** `AgentChatPanel.test.tsx`
   assertion, any padding/z-index adjustments found in visual
   verification.

## 10. Engineering Quality Checklist

- Clipboard + feedback logic centralized in one presentational component;
  the renderer override is one line.
- Copied text derived from rendered children (single source of truth); no
  duplicated parse of the markdown.
- Explicit types: `extractNodeText(children: React.ReactNode): string`;
  the status union is a named type.
- Primary-path clipboard call with loud failure; no legacy fallback code.
- Timeout in a ref, cleared on unmount and re-click; no
  setState-after-unmount, no stacked timers.
- REQ-SEC-002 posture unchanged and re-verified by the hostile-content
  tests; the button introduces no HTML interpretation.
- Accessibility: named button, live-region confirmation, focus-visible
  reveal, no keyboard trap.
- Visual consistency: existing `.msgAgent pre` styling untouched; new
  chrome uses the established hairline/soft-surface tokens; zero layout
  shift by construction.
- Tests cover the core contract (exact payload), feedback lifecycle,
  failure path, independence of blocks, and the security regression.
- Out-of-scope surfaces (LLMChat etc.) documented as follow-up, not
  half-included.
