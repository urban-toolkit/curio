# Implementation Memo: Agents Drawer Open/Close Transition Parity

Date: 2026-07-29
Status: implemented 2026-07-29 (same session)
Feature slice: UI-parity bug fix; no behavior, layout, or API changes beyond the presentation transition.
Design sources: the two shipped drawer patterns this must match — `NodeCatalogDrawerProvider` + `NodeCatalogDrawer` (the canonical two-phase presentation) and `DatasetCatalogDrawerProvider` + `DatasetCatalogDrawer` (the same pattern, component-owned overlay); `DEC-042` (the Agents Roster drawer header keeps the Pin; pinned blocks backdrop/Escape dismissal — unchanged here).

## 1. Problem Statement

The Agents Catalog drawer pops in and out with no animation while the Nodes and Datasets drawers slide. Root cause, confirmed in code:

- `AgentsCatalogDrawerProvider` renders `open ? createPortal(...) : null` — **instant mount/unmount**, a backdrop with no opacity transition, and a panel with no transform transition (`AgentsCatalogDrawerProvider.module.css` has static `.backdrop`/`.panel` rules only).
- `AgentsCatalogDrawer` itself contains `if (!presented) return null` with `presented` hardcoded `true` at the call site — the prop exists but the two-phase machinery behind it was never built.
- By contrast, both other drawers use one shared pattern: the provider holds `mounted` + `presented` (double-`requestAnimationFrame` to trigger the enter transition, an exit timer + `onExitComplete` on the panel's `transform` transitionend, `prefers-reduced-motion` handling, focus restore, body scroll lock), and the component owns an `overlayRoot`/`scrim`/`drawer` structure whose CSS animates scrim opacity (240ms, `cubic-bezier(0.4, 0, 0.2, 1)`) and panel `translate3d(100%,0,0) → 0` (300ms, `cubic-bezier(0.32, 0.72, 0, 1)`).

Consequences: visible flicker/pop on open and close, an abrupt scrim flash, and inconsistency with every other catalog surface.

One non-problem, verified: `useAgentsCatalogDrawer` fetches when `presented` flips true and never clears on false — so keeping the drawer mounted during the exit slide shows intact content, not an empty shell.

## 2. Scope

**Included**: `AgentsCatalogDrawerProvider.tsx` (adopt the NodeCatalogDrawerProvider two-phase state machine verbatim — mounted/presented, double-rAF enter, exit timer `300ms + 80ms` grace, reduced-motion snap, focus restore, scroll lock); `AgentsCatalogDrawer.tsx` (own the `overlayRoot`/`scrim`/`aside` structure like the Datasets drawer, `onTransitionEnd` → `onExitComplete`, drop the `if (!presented) return null`); `AgentsCatalogDrawer.module.css` (the same transition rules, timings, and easings as `NodeCatalogDrawer.module.css`, keeping the Agents drawer's 560px width and shadow); delete `AgentsCatalogDrawerProvider.module.css` (its markup moves into the component); tests.
**Out of scope**: any change to the drawer's inner layout, data flow, pin semantics (`DEC-042`), scopes, or actions; the other drawers; the chat panel.

## 3. Recommended Implementation Approach

Copy the shipped pattern rather than inventing a third variant: the provider becomes a line-for-line sibling of `NodeCatalogDrawerProvider` (same constants, same `finishClose`/`exitSettledRef` idempotence, same reduced-motion `useSyncExternalStore`), plus the Agents-specific `pinned` state it already owns (Escape stays provider-side, gated on `presented && !pinned`). The component takes `presented`/`onRequestClose`/`onExitComplete` like the Datasets drawer, renders the scrim (click closes unless pinned) and the sliding `aside`, and reports exit completion from the panel's own `transform` transitionend — with the provider's timer as the reduced-motion/lost-event fallback, exactly as the others do.

## 4/5. Data and State Handling

- Mount lifecycle: `mounted` keeps the DOM alive through the exit slide; `presented` drives the CSS classes. Content persists during exit (hook verified); on enter, the panel mounts one frame before the slide starts, so no empty/duplicated intermediate state can render.
- `isAgentsCatalogDrawerOpen` now reports `mounted` (open-through-exit), matching the Node drawer's context semantics.
- No API, store, or persistence changes.

## 6. Edge Cases

- Rapid open→close→open: `clearExitTimer` + `exitSettledRef` make close idempotent and reopening cancel a pending exit (same as the sibling providers).
- `prefers-reduced-motion`: present immediately, close immediately (0ms timer; CSS `transition-duration: 0.01ms` guard).
- Pinned: scrim click and Escape do nothing; the programmatic close (menu toggle) still animates out.
- Exit transitionend lost (tab hidden mid-close): the provider's `+80ms` timer settles the close anyway; `finishClose` runs once.
- Focus: restored to the pre-open element after the exit settles (parity with Node drawer).

## 7. Testing Strategy

Provider tests (new, mirroring the pattern's coverage): open mounts with the presented class applied on the next frames; close keeps the drawer mounted until `onExitComplete`/timer, then unmounts; reopen during exit cancels the pending unmount; pinned blocks Escape/scrim close. Component tests: existing `AgentsCatalogDrawer` suite updated for the new wrapper (queries unchanged where possible); `transitionEnd(transform)` while not presented fires `onExitComplete`, while presented does not. All existing suites green.

## 8. Acceptance Criteria

- [x] The Agents drawer opens and closes with the identical scrim fade (240ms) and panel slide (300ms, same easing) as the Nodes and Datasets drawers — no flicker, flash, or layout jump.
- [x] During exit the drawer stays mounted and slides out with its content intact; no empty, duplicated, or partially rendered intermediate state at any point.
- [x] Pin semantics (`DEC-042`), Escape behavior, layout, and all drawer functionality are byte-for-byte unchanged.
- [x] Reduced-motion users get instant open/close; focus returns to the opener after close.

## 9. Commits

One commit: `fix(agents): drawer open/close transition parity with the Nodes/Datasets drawers, with tests` (+ this memo).

## 10. Engineering Quality Checklist

- No third transition variant: constants, easings, and state machine are the shipped ones.
- The exit path is dual-guarded (transitionend + timer) and idempotent.
- Only presentation moved; the drawer's inner tree, hook, and provider contract consumers are untouched.
