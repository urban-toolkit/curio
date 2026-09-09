# dev/108 — The agent chat panel pops instead of sliding: the "flickering drawer" is `AgentChatPanel`, not the Agents Catalog drawer

**Status: IMPLEMENTED (2026-08-26) — commits `d7d237a5` (1, `useSlideDrawerPresentation` + 8 tests), `ebca211f` (2, panel presented/transitionend/Escape guard + CSS + 3 tests), `d2a18527` (3, overlay adoption + 7-test `AgentDockOverlay.test.tsx`), docs in the closing commit. Backlog `BL-P4-20260826-17`. Defaults taken: catalog providers NOT migrated (follow-up). Full jest 90/1020 green. Owner live re-test pending — re-record and re-run the frame diff (expect ≥8 intermediate frames per transition at 42 fps).**

Date: 2026-08-26
Branch / tree: `feat/agentscatalog` @ `dd1c5d74`. Line numbers pinned to that commit.
Origin: owner report "the drawer slide animation doesn't seem to be working properly … very flickering", with `~/Desktop/Screen Recording 2026-08-26 at 7.06.33 PM.mov`.
Evidence: frame analysis of the recording (42.3 fps, 506 frames, 12.0 s). The right half of the screen changes in exactly **six single-frame jumps** (#68, #248, #312, #369, #433, #501 — three open/close pairs) with **zero intermediate frames**; a 300 ms slide would show ~12. The panel in every frame is the **agent chat panel** ("Researcher: Paris weather request 2/2", "Attached to canvas", "Message this agent…"), not the Agents Catalog roster. The Agents Catalog drawer itself was probed live in Chrome the same evening and does slide, indistinguishably from the Node Catalog drawer under the same probe (dev/43 is working).
Family: dev/43 (Agents Catalog drawer two-phase presentation — the exact pattern to reuse) → dev/46 (chat panel adopted the catalog drawer's *sizing*, 560px/92vw, but not its motion) → `BL-P4-20260721-13` (chat restyle + close control) / `BL-P4-20260721-14` (`DEC-042` header split) → dev/19/20/25 (chat behaviors that must not change).
Design decisions consumed: `DEC-042` (agent-view header carries ‹ › cycling and Close — unchanged). **No new DEC** — this is UI-parity polish; a `BL-P4-20260826-17` entry is minted at closure.

---

## 1. Problem Statement

**Current behavior.** `AgentDockOverlay.tsx:60-64` renders the chat as `selected ? createPortal(<AgentChatPanel …/>, document.body) : null`. Opening (dock tile, node badge, ‹ › cycle, delegation link) and closing (Close button, Escape at `AgentChatPanel.tsx:314-320`, detaching the selected agent) therefore **mount and unmount the 560px panel in one frame**. `.panel` (`AgentChatPanel.module.css:11-27`) is `position: fixed; right: 0` with no `transform`, no `transition`, no presented/exit state. The full-height panel snapping in and out over the canvas is the flicker in the recording.

**Expected behavior.** The chat panel is the fourth right-hand drawer in the app. It should enter with the same slide the Nodes / Datasets / Agents Catalog drawers use (panel `translate3d(100%,0,0) → 0`, 300 ms `cubic-bezier(0.32, 0.72, 0, 1)`) and exit by sliding out while its content stays intact, unmounting only after the transform transition ends (with a timer fallback), honoring `prefers-reduced-motion`. Unlike the catalog drawers it is **non-modal**: no scrim, no body scroll lock, the canvas stays interactive (users chat while working — dev/44 grounded context reads the live canvas).

**What must not change.** Switching agents with ‹ › or a delegation link (`onOpenAgentChat`) swaps `selected` while the panel stays open — today the panel element persists (same React position, no key) and content re-renders in place. That must remain a **content swap, not a re-slide**. Escape/Close semantics, `DEC-042` header, transcript auto-scroll (dev/75), composer auto-grow (dev/77), run status (dev/80), and the settings modal are untouched.

**Why it matters.** Consistency with the three sibling drawers (dev/43 fixed the identical defect on the catalog drawer and cited "visible flicker/pop on open and close"), perceived quality on the surface users touch most, and the owner's explicit report.

## 2. Scope

**Included**
- `src/components/agents/attach/AgentDockOverlay.tsx` — own the two-phase presentation: keep the last `selected` attachment mounted through the exit, drive `presented`.
- `src/components/agents/attach/AgentChatPanel.tsx` — accept `presented: boolean` and `onExitComplete?: () => void`; toggle a `panelPresented` class; report the panel's own `transform` `transitionend`. Root stays `div.panel role="dialog"`.
- `src/components/agents/attach/AgentChatPanel.module.css` — the transition rules (transform/duration/easing/`will-change`, reduced-motion block), same values as `AgentsCatalogDrawer.module.css:31-61` minus the scrim.
- **Shared hook (new)**: `src/hooks/useSlideDrawerPresentation.ts` — the dev/43 state machine extracted once (`mounted`/`presented`, double-rAF enter, exit timer `motionMs + 80`, `onExitComplete` settle guard, reduced-motion snap via `useSyncExternalStore`, jsdom-safe `matchMedia` guard). This is the **fourth** copy of that machine otherwise (`NodeCatalogDrawerProvider`, `AgentsCatalogDrawerProvider`, `DatasetCatalogDrawerProvider` each inline it); the memo standard's "centralize reused logic" applies. The hook takes `open: boolean` and returns `{ mounted, presented, finishExit }`. Focus-restore and body scroll lock stay **out** of the hook (they are modal concerns; the chat is non-modal) — providers keep those lines.
- Tests: hook unit test; `AgentChatPanel` class/transitionend test; overlay behavior test (mounted-through-exit, no re-slide on agent switch).
- Docs: `docs/AGENTS.md` chat-panel paragraph (one sentence), `BL-P4-20260826-17`.

**Out of scope (explicitly)**
- Migrating the three catalog providers onto the new hook. Correct and desirable, but it touches three verified surfaces for zero user-visible change; do it as a follow-up commit series with the existing provider tests as the gate (`BL` follow-up line). The hook is written so that migration is a deletion, not a rewrite.
- A scrim or scroll lock for the chat panel (would change the non-modal interaction model — a product decision, not parity).
- Animating the dock tiles, node badges, or the settings modal.
- The Agents Catalog drawer — verified working; nothing to do.

## 3. Recommended Implementation Approach

**Hook** — `useSlideDrawerPresentation(open, { motionMs = 300 })`:
- `open` rising edge: `mounted=true`, `presented=false`, then `presented=true` on the second `requestAnimationFrame` (or synchronously under reduced motion). Clears any pending exit timer and resets the settle guard — reopening mid-exit reverses smoothly (dev/43's "reopen-during-exit" test).
- `open` falling edge: `presented=false`; arm `setTimeout(finishExit, reduced ? 0 : motionMs + 80)`.
- `finishExit()` (idempotent via ref): clear timer, `mounted=false`. Exposed so the panel's `transitionend` can call it early.
- Cleanup on unmount clears the timer. Same code as `AgentsCatalogDrawerProvider.tsx:49-115`, minus focus/scroll-lock.

**Overlay** — `AgentDockOverlay`:
- `open = selected !== null`. Hold `lastSelectedRef`/state updated whenever `selected` is non-null; render the panel with `selected ?? lastSelected` **while `mounted`** so the exiting panel keeps its content (and its `turns`, `runStatus`, etc. — read them by the retained attachment id, not `selected`).
- Pass `presented` and `onExitComplete={finishExit}`. When `selected` changes between two non-null ids, `open` stays true → no state-machine transition → content swap only.
- Edge: if the retained attachment is **detached** during the exit slide (`onDetach` closes then detaches), the panel is already sliding out with its last props — fine; guard prop lookups with `?? []`/`?? null` as today.

**Panel** — `AgentChatPanel`:
- New props `presented: boolean` (required — every caller is the overlay; tests pass `presented`), `onExitComplete?`.
- Root: `className={`${styles.panel} ${presented ? styles.panelPresented : ""}`}` and `onTransitionEnd` filtered to `e.target === rootRef.current && e.propertyName === "transform" && !presented` (dev/43's exact filter — inner elements transition `opacity` and must not settle the exit).
- `aria-hidden={!presented}` is **not** added: the panel is non-modal and briefly hidden-but-focusable would trip a11y checks; instead the exiting panel keeps `role="dialog"` for ≤380 ms, as the catalog drawers effectively do.
- Escape listener (`:314-320`) should be active only while `presented` — add `presented` to its condition so Escape during the exit slide is a no-op rather than a second `onClose`.

**CSS** — `.panel` gains `transform: translate3d(100%, 0, 0); transition: transform 300ms cubic-bezier(0.32, 0.72, 0, 1); will-change: transform;` and `.panelPresented { transform: translate3d(0, 0, 0); }`, plus the `@media (prefers-reduced-motion: reduce) { .panel { transition-duration: 0.01ms } }` block. `overflow: hidden`, `z-index: 1100`, width, shadow unchanged. `DRAWER_MOTION_MS` lives once, in the hook's default, with the CSS comment pointing at it (same convention as the providers).

**No new abstraction beyond the hook.** No animation library, no `key` on the panel (a key would force a re-slide on agent switch — the opposite of the requirement).

## 4. Data and State Handling

- Source of truth for "which chat is open" stays `ctx.selectedId` in `AgentAttachmentsProvider` (`:789`). The overlay adds only presentation state (`mounted`, `presented`, `lastSelected`); no provider change.
- Derived: `open = !!selected`; `renderedAttachment = selected ?? lastSelected`; `panelProps` resolve by `renderedAttachment.attachmentId`.
- Open: mount closed → next frames presented. Content (transcript hydration, `loadingHistory`) proceeds exactly as today — the panel is in the tree from the first frame, so `hydrateSession` timing is unchanged.
- Close: `presented=false` → slide → `transitionend` (or timer) → unmount. `lastSelected` is cleared on unmount so a stale attachment can't be rendered later.
- Agent switch while open: no `mounted`/`presented` change; props swap. Transcript auto-scroll's per-attachment behavior (dev/75) is untouched because it already handles `attachment` prop changes.
- Reopen during exit: timer cleared, `presented=true` re-applied; CSS reverses the in-flight transform — no jump.
- No stale data risk from the retained attachment: it is only used while `mounted && !selected`, i.e., during the ≤380 ms exit.

## 5. UI and UX Requirements

- Enter: panel slides in from the right edge over 300 ms with the catalog drawers' easing; dark `DEC-042` header arrives with it. No scrim; canvas remains fully interactive during and after.
- Exit: slides out over 300 ms with content intact (no blank frame, no collapse to an empty panel). Nothing else on the canvas moves (no scroll-lock toggling, so no scrollbar-induced layout shift).
- Agent switch: instantaneous content swap in a stationary panel (as today).
- Reduced motion: appears/disappears without slide (the 0.01 ms path), no timer wait on close.
- Accessibility: `role="dialog"` + `aria-label` unchanged; Escape closes only while presented; focus behavior unchanged (the panel does not steal focus today and this memo does not add that).
- No visible jank: transform-only animation on a `will-change: transform` layer; no layout properties animate.

## 6. Edge Cases

- **Detach the open agent** (`onDetach` → `closeChat` then `detach`): panel slides out showing the detached agent's last content; `lastSelected` may reference an attachment no longer in `ctx.attachments` — every lookup already tolerates missing keys (`?? []`, `?? null`); `index/total` are computed from the retained id and may read "0/N" briefly — acceptable, or pin `index`/`total` at close time (recommended: pin).
- **Open a different agent during the exit slide** (‹ › can't, but a node badge click can): `open` rises again → reopen path → panel reverses and content swaps to the new agent. Same as dev/43's reopen-during-exit.
- **Rapid open/close/open**: timer cleared on each transition; the settle guard prevents a late `transitionend` from unmounting a re-presented panel (filter `!presented`).
- **`transitionend` never fires** (tab hidden, display:none ancestor, zero-duration): the `motionMs + 80` timer unmounts.
- **Reduced-motion toggled while open**: `useSyncExternalStore` re-renders; next close uses the 0 ms path.
- **Shared view** (`MainCanvas.tsx:576`, `isSharedView`): overlay not rendered — unaffected.
- **Title rename in progress on close**: unchanged (`finishTitleEdit` semantics); Escape-while-editing still cancels the edit, not the panel.
- **Settings modal open when the panel closes**: independent portal, unaffected.
- **jsdom**: `matchMedia` absent → hook degrades to "no reduced motion" (the dev/43 guard); tests drive `transitionend` manually via `fireEvent.transitionEnd(panel, { propertyName: "transform" })`.

## 7. Testing Strategy

**`src/tests/hooks/useSlideDrawerPresentation.test.ts`** (new; `jest.useFakeTimers` + rAF mock as in `AgentsCatalogDrawerProvider.test.tsx`):
1. `open=true` → `mounted` true immediately, `presented` false, then true after two rAFs.
2. `open=false` → `presented` false, `mounted` stays true; `finishExit()` → `mounted` false.
3. Timer fallback: no `finishExit` call → `mounted` false after `motionMs + 80`.
4. Reopen during exit: timer cancelled, `presented` back to true, never unmounts.
5. Reduced motion (mock `matchMedia` matches): `presented` true synchronously on open; unmount at 0 ms on close.
6. `finishExit` idempotent; unmount clears the timer (no act warnings).

**`src/tests/attach/AgentChatPanel.test.tsx`** (extend `renderPanel`, default `presented: true`):
7. `presented=false` → root lacks `panelPresented`; `presented=true` → has it.
8. `transitionend` with `propertyName: "transform"` on the root while `!presented` → `onExitComplete` called once; same event with `propertyName: "opacity"` or from a child, or while `presented` → not called.
9. Escape while `!presented` → `onClose` not called (regression for the new condition); while presented → called (existing test stays green).

**Overlay** — `src/tests/attach/AgentDockOverlay.test.tsx` (new; reuse the `agentCanvasBridge.integration.test.tsx:96` harness: FlowProvider + ReactFlowProvider + a mocked `useAgentAttachmentsContext`):
10. Selecting an attachment mounts the panel closed then presented (class appears after rAFs).
11. `closeChat` (selectedId → null) keeps the panel mounted with the same `aria-label` until `transitionend`, then unmounts.
12. Switching `selectedId` between two attachments keeps `panelPresented` throughout and never unmounts (no re-slide).
13. Detach of the open agent during exit does not throw and still unmounts.

**Regression**: full `npx jest` (1002 today) green; the four dev/43 provider tests untouched.

## 8. Acceptance Criteria

- Opening a chat from a dock tile, node badge, ‹ ›, or delegation link slides the panel in over ~300 ms; closing via Close, Escape, or detaching slides it out with content intact; no single-frame pop in either direction (verifiable by re-recording and re-running the frame-diff: ≥8 intermediate frames per transition at 42 fps).
- Switching agents while open does not re-slide.
- Canvas remains interactive during and after opening (no scrim, no scroll lock).
- `prefers-reduced-motion: reduce` yields instant show/hide with no lingering mounted panel.
- Escape during the exit slide is a no-op.
- All tests in §7 pass; `tsc` clean in touched files; the three catalog providers are byte-identical (migration deferred).
- `docs/AGENTS.md` names the shared hook as the required pattern for any future right-hand drawer.

## 9. Recommended Commit Breakdown

1. **`useSlideDrawerPresentation` hook + tests** — extracted verbatim from `AgentsCatalogDrawerProvider` minus focus/scroll-lock; no consumers yet.
2. **Chat panel presentation** — `AgentChatPanel` props/class/transitionend/Escape guard + CSS; `AgentChatPanel.test.tsx` cases 7–9.
3. **Overlay adoption** — `AgentDockOverlay` uses the hook, retains the exiting attachment, pins index/total; `AgentDockOverlay.test.tsx` cases 10–13.
4. **Docs/backlog** — `docs/AGENTS.md`, `BL-P4-20260826-17`, memo → IMPLEMENTED; follow-up line: migrate the three catalog providers onto the hook.

## 10. Engineering Quality Checklist

- Duplication reduced, not added: one hook; the fourth inline copy is never written.
- Types explicit: `presented: boolean` required on the panel; hook returns a typed tuple/object.
- Components focused: overlay gains ~12 lines; panel gains a class toggle and one handler.
- State predictable: single `open` input, ref-guarded settle, timer always cleared.
- UI consistent: identical timings/easing to `AgentsCatalogDrawer.module.css`; non-modal by design.
- Loading/empty/error: unchanged (panel already handles `loadingHistory`/`historyError`).
- Accessibility: Escape guarded; dialog semantics kept; reduced motion honored.
- Tests cover hook, panel, overlay, and the no-re-slide-on-switch requirement.
- Conventions: memo → pathspec commits, no trailer, no push; `BL-P4` entry; `plans/` is tracked on `feat/agentscatalog`.
- Performance: transform-only, `will-change: transform`; no extra re-renders beyond two presentation booleans.

## Open question for the owner (non-blocking — default stated)

- **Migrate the three catalog providers to the hook now or later?** Default **later** (separate follow-up; keeps this change to the surface you reported). Say "migrate now" and commit 1 grows a provider-migration pass gated by their existing 8 + N tests.
