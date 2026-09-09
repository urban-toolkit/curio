# dev/109 — Three catalog-drawer providers still inline the slide state machine that `useSlideDrawerPresentation` now owns: migrate them onto the hook

**Status: IMPLEMENTED (2026-08-26) — commits `23f2fe9c` (1, characterization suites Node 10 / Dataset 11 + hook `onExited`), `f1f9cf1f` (2, Node), `53f33782` (3, Dataset — double-rAF + `isOpen`/scroll-lock on `mounted`, the two `it.failing` flipped), `30b88c04` (4, Agents), docs in the closing commit. Backlog `BL-P3-20260826-14`. Default taken: Dataset `isOpen` unified on `mounted` (palette effects verified to only suppress dismissal). Full jest 92/1042 green; acceptance grep under `src/providers/` empty.**

Date: 2026-08-26
Branch / tree: `feat/agentscatalog` @ `2f1c1a47`. Line numbers pinned to that commit.
Origin: the follow-up recorded in `BL-P4-20260826-17` / memo `dev/108` §2 ("migration is a deletion, not a rewrite").
Family: dev/43 (the machine, first written in `AgentsCatalogDrawerProvider`, copied from `NodeCatalogDrawerProvider`) → `DatasetCatalogDrawerProvider` (third copy) → dev/108 (fourth consumer avoided by extracting `hook/useSlideDrawerPresentation.ts`; `docs/AGENTS.md` now says new drawers must use it).
Design decisions consumed: none new. `DEC-042` (Agents roster header Pin blocks scrim/Escape dismissals) is preserved verbatim. Refactor-only: **zero intended user-visible change** except two consistency fixes called out in §1 and accepted here explicitly.

---

## 1. Problem Statement

`NodeCatalogDrawerProvider.tsx` (135 lines), `AgentsCatalogDrawerProvider.tsx` (169), and `datasetCatalog/DatasetCatalogDrawerProvider.tsx` (154) each hand-roll the same two-phase presentation: `mounted`/`presented` state, `exitTimerRef`, `exitSettledRef`, `clearExitTimer`, `finishClose`, a double-`requestAnimationFrame` enter, a `DRAWER_MOTION_MS + 80` fallback, and a `useSyncExternalStore` reduced-motion subscription. `useSlideDrawerPresentation` (dev/108, `d7d237a5`) is that machine, tested in isolation (8 tests). Keeping three private copies means a fix lands in one place and not the others — which has **already happened**, three ways:

1. **Enter frames**: Node and Agents use a double rAF (`NodeCatalogDrawerProvider.tsx:84-86`, `AgentsCatalogDrawerProvider.tsx:105-107`); Dataset uses a **single** rAF (`DatasetCatalogDrawerProvider.tsx:87`). A single rAF can fire before the mounted-closed frame paints in some engines → the enter slide is occasionally skipped (the drawer pops). The hook uses the double rAF.
2. **jsdom guard**: Agents guards `window.matchMedia` being absent (`:39-51`); Node (`:24-32`) and Dataset (`:26-34`) call it unguarded — which is why **neither has a provider test today** (they would throw under jsdom). The hook is guarded.
3. **`isOpen` semantics**: Node and Agents expose `is…Open = mounted` (`:100`, `:130`); Dataset exposes `= presented` (`:130`). The two palettes consume these to suppress their own Escape/outside-click closing while the drawer is up (`DatasetsPaletteDropdown.tsx:74-92`, `AgentsPaletteDropdown.tsx:60-78`). With `presented`, the Datasets palette can close on an Escape pressed during the drawer's ≤380 ms exit slide; with `mounted` it cannot. Unify on `mounted` (the drawer still occupies the screen while sliding out).

Also duplicated: `DRAWER_MOTION_MS = 300` three times plus the CSS comments pointing at each.

**Expected state.** Each provider owns only what is genuinely its own — the context value, the portal, focus capture/restore, body scroll lock, the Agents Pin (`DEC-042`), the Dataset prefetch effect — and delegates mount/present/exit to the hook. Behavior is identical to today except the three fixes above.

**Why it matters.** Maintainability (one machine, one test suite), the latent Dataset enter-pop, and testability: Node and Dataset providers gain their first tests as the migration gate.

## 2. Scope

**Included**
- `src/providers/NodeCatalogDrawerProvider.tsx`, `src/providers/AgentsCatalogDrawerProvider.tsx`, `src/providers/datasetCatalog/DatasetCatalogDrawerProvider.tsx` — replace the inline machine with `useSlideDrawerPresentation(open)`.
- `src/hook/useSlideDrawerPresentation.ts` — **one small addition**: an optional `onExited?: () => void` callback fired once when `mounted` falls, so providers restore focus at the right moment without re-deriving the falling edge (the hook already has the single point where that happens). Alternative without touching the hook: a `useEffect` on `mounted` in each provider — three copies of a falling-edge detector, which is the smell being removed. Take the hook option.
- New tests: `src/tests/providers/NodeCatalogDrawerProvider.test.tsx`, `src/tests/providers/DatasetCatalogDrawerProvider.test.tsx` — written **first**, against the current inline code, as characterization; then the migration must keep them green. Extend `AgentsCatalogDrawerProvider.test.tsx` only if a gap is found (its 8 cases already cover mounted-through-exit, transitionend unmount, reopen-during-exit, Escape, Pin).
- CSS comments in the three drawer module files that say "keep in sync with `DRAWER_MOTION_MS` in …Provider.tsx" → point at `SLIDE_DRAWER_MOTION_MS` in the hook.
- `docs/AGENTS.md`: drop the "still carry their original inline copies pending migration" clause; `BL-P3-20260826-14` (or the next free `BL-P3` number on disk) at closure.

**Out of scope**
- Any change to the three drawer *components* (`NodeCatalogDrawer`, `DatasetCatalogDrawer`, `AgentsCatalogDrawer`) or their CSS motion values.
- Changing what the palettes do with `is…Open` beyond receiving the unified `mounted` semantics.
- The chat panel (`AgentDockOverlay`) — already on the hook.
- Consolidating the three providers into one generic provider. Their context APIs, names, and extras (Pin, prefetch, `projectId`) differ; a generic provider would be a new abstraction for three call sites and would churn every consumer import. Not justified.

## 3. Recommended Implementation Approach

**Hook addition** (`useSlideDrawerPresentation`):
```
useSlideDrawerPresentation(open, { motionMs?, onExited? })
```
`onExited` is invoked from `finishExit` after `setMounted(false)` (i.e., both the transitionend path and the timer path), guarded by the existing `exitSettledRef` so it fires once per exit and never after a reopen. Stored in a ref so callers can pass an inline closure without re-subscribing. One new hook test.

**Provider shape** (identical for all three; shown for Node):
```
const [open, setOpen] = useState(false);
const preOpenFocusRef = useRef<HTMLElement | null>(null);
const { mounted, presented, finishExit } = useSlideDrawerPresentation(open, {
  onExited: () => {
    const el = preOpenFocusRef.current;
    preOpenFocusRef.current = null;
    queueMicrotask(() => el?.focus?.());
  },
});
const openNodeCatalogDrawer = useCallback(() => {
  preOpenFocusRef.current = document.activeElement as HTMLElement | null;
  setOpen(true);
}, []);
const closeNodeCatalogDrawer = useCallback(() => setOpen(false), []);
// scroll lock on `mounted` (unchanged for Node/Agents; Dataset moves from `presented` → `mounted`, see §6)
useEffect(() => { if (!mounted) return; const prev = document.body.style.overflow; document.body.style.overflow = "hidden"; return () => { document.body.style.overflow = prev; }; }, [mounted]);
const ctx = useMemo(() => ({ openNodeCatalogDrawer, closeNodeCatalogDrawer, isNodeCatalogDrawerOpen: mounted }), [...]);
const drawer = mounted ? createPortal(<NodeCatalogDrawer presented={presented} onRequestClose={closeNodeCatalogDrawer} onExitComplete={finishExit} />, document.body) : null;
```
Deleted per provider: `DRAWER_MOTION_MS`, `subscribeReducedMotion`, `getReducedMotionSnapshot`, `useSyncExternalStore`, `mounted`/`presented` state, `exitTimerRef`, `exitSettledRef`, `clearExitTimer`, `finishClose`, the rAF choreography, the unmount-cleanup effect. ~50–60 lines each.

**Agents extras kept**: `pinned` state + `onPinToggle`; the Escape listener stays in the provider, conditioned on `presented && !pinned` exactly as today (`:117-124`); `projectId` from `useFlowContext`.
**Dataset extras kept**: the `prefetchDatasetCatalog` effect on `projectId` (`:100-113`) — unrelated to presentation, untouched.

**Reopen-while-closing**: previously `open…()` cleared the exit timer and reset the settle guard by hand; now `setOpen(true)` on the rising edge does the same inside the hook (tested by "reopening during the exit slide cancels the pending unmount"). Focus capture on reopen: `preOpenFocusRef` is overwritten with the current `activeElement` — same as today.

**No behavioral additions.** No new props on the drawers, no CSS changes, no scrim changes.

## 4. Data and State Handling

- Source of truth per provider becomes a single `open: boolean`; `mounted`/`presented` are derived by the hook. Nothing else in the app reads them except the portal condition, the drawer's `presented` prop, and `is…Open`.
- `is…Open` = `mounted` for all three (Dataset changes from `presented`): true from the open call until the exit settles. Consumers (palettes) therefore treat "sliding out" as "still open", which is the conservative reading.
- Focus restore fires exactly once per completed exit (via `onExited`), never on reopen-during-exit (the guard), matching today's `finishClose` semantics.
- Scroll lock keyed on `mounted` for all three (Dataset changes from `presented`): the lock now spans the ≤380 ms exit as well — the canvas can't scroll under a drawer that is still visibly on screen. Node/Agents already behave this way.
- Reduced motion: unchanged behavior; the source moves into the hook.
- No new async paths, no new race windows: the hook's timer/settle guard is the same code path that ran inline.

## 5. UI and UX Requirements

- Visually identical open/close for all three drawers. Only intended deltas: the Datasets drawer's enter slide no longer risks being skipped (double rAF), and Escape in the Datasets *palette* no longer closes the palette during the drawer's exit slide.
- Keyboard: Escape handling for the Agents roster (provider-owned, Pin-aware) unchanged; Node/Dataset drawers' own close controls unchanged.
- Focus returns to the pre-open element after the exit settles — unchanged.
- Accessibility attributes live in the drawer components — untouched.

## 6. Edge Cases

- **Dataset `isOpen` flip (`presented` → `mounted`)**: `DatasetsPaletteDropdown.tsx:74-92` — palette Escape/outside-click suppression now extends through the exit slide. Also the palette's "reopen dropdown on drawer close" behavior (if any) fires ~380 ms later; verify by reading those two effects — if either intentionally keys off "presented" (e.g. to reopen the palette the instant the drawer starts closing), keep exposing an additional `isDatasetCatalogDrawerPresented` rather than changing timing silently. Decide in commit 1 after reading the palette; default = unify on `mounted`.
- **Dataset scroll lock (`presented` → `mounted`)**: the lock now covers the first (closed) frame and the exit slide. Harmless; matches the other two.
- **Node/Dataset under jsdom**: the hook's guard makes them testable; the characterization tests in commit 1 must therefore stub `matchMedia` *for the pre-migration run* (a `beforeAll` shim) and can drop the shim after migration — or keep it; either way they run in both states.
- **`finishExit` called by a drawer whose transitionend fires after a reopen**: the hook ignores it (dev/108 "stray finishExit" test). Today's providers have the same guard via `exitSettledRef` reset on open. Parity.
- **Provider unmount mid-exit** (route change while a drawer is closing): the hook clears its timer on unmount; focus restore is skipped (no `onExited`) — today `finishClose` would also never run. Parity.
- **`prefersReducedMotion` toggled between open and close**: the hook reads the live value at each edge, as the providers do.
- **StrictMode double-invoke of effects**: the hook's effects are idempotent (rAF/timer refs cleared before re-arm); `AgentDockOverlay` already runs under the app's StrictMode setting without issue.

## 7. Testing Strategy

**Commit 1 — characterization tests (written against the inline code, must pass before any provider changes):**
- `NodeCatalogDrawerProvider.test.tsx` (mock `NodeCatalogDrawer` deps as the Agents test mocks `agentsApi`; shim `matchMedia`): (1) not rendered until opened; (2) open → `role=dialog` present after rAFs; (3) close → root `[data-curio-node-catalog-drawer]` stays mounted, `aside` transitionend(`transform`) unmounts; (4) timer fallback unmounts at 380 ms; (5) reopen during exit keeps it mounted past 450 ms; (6) `isNodeCatalogDrawerOpen` true through the exit slide, false after; (7) focus returns to the opener after exit; (8) body `overflow` locked while mounted, restored after.
- `DatasetCatalogDrawerProvider.test.tsx` (mock `useFlowContext`, `prefetchDatasetCatalog`, the drawer's data hook): same eight, plus (9) `prefetchDatasetCatalog` called twice on mount with `includeHub` true/false — pins the untouched extra. Case (6) is written for the **target** semantics (`mounted`) and is expected to fail pre-migration on the exit-slide assertion; mark it `it.failing` in commit 1 and flip to `it` in commit 3 — the flip *is* the documented behavior change.
- Hook: (10) `onExited` fires once per exit (transitionend path and timer path), not after a reopen, and not on unmount.

**Commits 2–4 — migration**: each provider's suite green unchanged (except the planned flip); `AgentsCatalogDrawerProvider.test.tsx` 8/8 unchanged.

**Regression**: full `npx jest` (1020 today) green; `tsc --noEmit` clean in touched files; a manual open/close of all three drawers plus the chat panel in the running app.

## 8. Acceptance Criteria

- The string `requestAnimationFrame` and the identifiers `exitTimerRef` / `exitSettledRef` / `DRAWER_MOTION_MS` no longer appear under `src/providers/`; `useSyncExternalStore` appears there only if a provider needs it for something other than reduced motion (none do today).
- All three providers call `useSlideDrawerPresentation`; the three drawer components receive `presented` and `onExitComplete` exactly as before.
- All three `is…Open` values equal `mounted`; the Datasets palette suppresses Escape/outside-click through the drawer's exit slide.
- Datasets drawer enters via the double-rAF path (no pop on open).
- Focus restore, scroll lock, Agents Pin/Escape semantics, and the Dataset prefetch behave as today (tests 7–9 + the Agents suite).
- New tests: Node ≥8, Dataset ≥9, hook +1; full suite green; each intermediate commit type-clean.
- `docs/AGENTS.md` no longer says the providers carry inline copies; backlog entry minted.

## 9. Recommended Commit Breakdown

1. **Characterization tests + hook `onExited`** — the two new provider suites against current code (with the one `it.failing`), the hook option + its test. No provider changes.
2. **Migrate `NodeCatalogDrawerProvider`** — smallest provider, no extras. Suite green.
3. **Migrate `DatasetCatalogDrawerProvider`** — includes the `isOpen`/scroll-lock unification (flip the `it.failing`), keeps prefetch. Suite green.
4. **Migrate `AgentsCatalogDrawerProvider`** — keeps Pin/Escape/`projectId`. Its existing 8 tests green.
5. **Docs/cleanup** — CSS "keep in sync" comments → `SLIDE_DRAWER_MOTION_MS`; `docs/AGENTS.md`; backlog entry; memo → IMPLEMENTED.

Each provider in its own commit so a regression bisects to one file.

## 10. Engineering Quality Checklist

- Duplication removed: three copies → zero; ~160 lines deleted net of the hook option (~10 lines).
- Types: provider context types unchanged; hook option typed and optional.
- Components/providers focused: each provider is now context + portal + its genuine extras.
- State predictable: one `open` boolean per provider; edges handled in one tested place.
- UI consistency: the three drawers and the chat panel share one machine and one motion constant.
- Loading/empty/error: not applicable (presentation only).
- Accessibility: focus restore and Escape semantics preserved and now tested for Node/Dataset for the first time.
- Tests: characterization-first, so the migration is verified against recorded behavior rather than intent.
- Conventions: memo → pathspec commits, no trailer, no push; `plans/` tracked on this branch.
- Performance: no additional renders (same two booleans, now from the hook).

## Open question for the owner (non-blocking — default stated)

- **Dataset `isDatasetCatalogDrawerOpen`: unify on `mounted` (default) or preserve `presented` timing** for the palette? Default unify; §6 describes the check that would justify keeping a separate `…Presented` flag instead.
