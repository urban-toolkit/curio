# Implementation Memo: "Installing…" placeholder rows for in-flight dataset installs

**Status:** Proposed (memo only — no code written) · **Branch:** `datacatalog` · **Author:** Karla
**Area:** `utk_curio/frontend/urban-workflows` — dataset palette + Data Catalog drawer + install/execution flow

---

## 1. Problem Statement

**Current behavior.** When a dataset is being installed there is no per-dataset progress
feedback in the dataset surfaces:

- **Flow-execution auto-install (primary gap):** running a producing node installs a
  dataset on the backend and then saves the project; the dataset only *pops into* the
  palette / drawer once the whole round-trip (execute → install → save → refetch) finishes.
  During that window the user sees nothing indicating a dataset is on its way.
- **Manual drawer install/import:** the source card disables its button while
  `busyId === dataset.id` (`DatasetCard.tsx:168-177`), but there is no explicit "installing"
  affordance, and an **import** (brand-new dataset with no existing row) shows nothing in the
  list until it lands — only the footer button reads "Importing…" (`DatasetCatalogDrawer.tsx:231`).

**Expected behavior.** For every dataset currently being installed, show a **placeholder
row** — in both the **palette** (`DatasetsPaletteDropdown`) and the **drawer**
(`DatasetCatalogDrawer`) — with a loading icon and the dataset/node label, until the dataset
is fully installed (or the operation fails), at which point the placeholder is replaced by the
real row (or removed on failure).

**Why it matters.** Installs are now automatic on flow execution (see
`plans/dataset-install-state-sync.md`); without feedback the UI looks idle/stale while work is
happening, and a multi-node "play all" gives no sense of progress.

---

## 2. Scope

**In scope**

- A shared, context-level **pending-installs store** (source of truth for "what is installing
  right now"), added to `src/hook/useWorkflowOperations.ts` and exposed via `FlowProvider`
  (auto-spread through `...workflowOps`, see `FlowProvider.tsx:1397`).
- Marking/clearing pending installs:
  - **Flow execution:** `src/components/editing/CodeEditor.tsx` — begin on the execution
    `useEffect` (`:218-231`) when the node is a saver (`resolveSaveOutputDataset(...)`); clear in
    `processExecutionResult` (`:151-201`) on success and on error.
  - **Manual install/import:** `src/components/datasets/catalog/useDatasetCatalogDrawer.ts`
    (`onInstall` `:148-181`, `onPickImport` `:264-285`) — begin/clear around the API call.
- Placeholder rendering:
  - Palette: `src/components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx`
    (`:187-198`) + a new `DatasetInstallingRow` mirroring `DatasetPaletteRows.tsx`.
  - Drawer: `src/components/datasets/catalog/DatasetCatalogDrawer.tsx` (`:161-220`) +
    `InstalledDatasetsList.tsx` (`:136`) + a new `DatasetInstallingCard` mirroring `DatasetCard`.
- Shared spinner/skeleton visual (one component each) + minimal CSS (reuse the drawer's existing
  `styles.skeletonCard` where it fits).

**Out of scope**

- Backend changes — the pending state is purely client-side UI; the existing install/save/
  refresh pipeline is unchanged.
- Progress percentages or cancellation — this is a binary "installing → done/failed" indicator.
- Reworking the existing `busyId`/`publishingId` button-disable behavior (kept as-is; the
  placeholder is additive).

---

## 3. Recommended Implementation Approach

Single source of truth + dumb presentational placeholders, so both surfaces stay in sync and
the loading visual is defined once.

1. **Pending-installs store (context).** In `useWorkflowOperations`, add:
   - `pendingInstalls: PendingInstall[]` where
     `PendingInstall = { key: string; label: string; producerNodeId?: string; datasetId?: string; format?: DatasetFormat; startedAt: number }`.
   - `beginPendingInstall(p: Omit<PendingInstall,"startedAt">): void` — upsert by `key`
     (idempotent; a re-run with the same key replaces the entry and restarts its timer).
   - `endPendingInstall(key: string): void` — remove by `key`.
   Hold it as `useState` plus a synced ref (mirror the `dataflowDatasetsRef` pattern,
   `useWorkflowOperations.ts:101-106`) so begin/clear from async callbacks never fight a stale
   closure. Expose all three through the context type + defaults (like `persistInstalledDataset`).

   **Key choice:** for auto-install use the **producer node id** as `key` (the eventual dataset is
   deterministically `computed.<nodeId>@1`), so the placeholder can be matched against — and
   replaced by — the real installed item. For manual install use the catalog `datasetId`; for
   import use a stable sentinel (`"import"`).

2. **Begin/clear at the real boundaries.**
   - *Flow execution* (`CodeEditor.tsx`): in the execution `useEffect`, if
     `resolveSaveOutputDataset(data, defaultSaveOutputDataset)` is true, call
     `beginPendingInstall({ key: data.nodeId, producerNodeId: data.nodeId, label: resolveNodeDisplayLabel(data) })`
     right before `interpreter.interpretCode(...)`. In `processExecutionResult`, call
     `endPendingInstall(data.nodeId)` in a `finally`-style path for **both** outcomes (success →
     after `persistInstalledDataset`; error → in the `else` branch). Because `persistInstalledDataset`
     already awaits the save+resync, clearing after it means the placeholder yields directly to the
     real row with no flicker gap.
   - *Manual install/import* (`useDatasetCatalogDrawer.ts`): wrap the existing `try/finally`
     (`onInstall`, `onPickImport`) with `beginPendingInstall`/`endPendingInstall`. This is mostly
     redundant with `busyId` for an existing card, but gives **import** a real placeholder row.

3. **Derive non-duplicating placeholder rows.** In each surface, compute
   `visiblePending = pendingInstalls.filter(p => !realItems.some(matches(p)))` where `matches`
   compares `producerNodeId`/`datasetId` against the catalog item — so once the real installed row
   arrives (catalog refetch), its placeholder is suppressed even if `endPendingInstall` hasn't fired
   yet (belt-and-suspenders against ordering). Render `visiblePending` **above** the real rows.

4. **Shared presentational components.**
   - `DatasetInstallingRow` (palette) — same row chrome as `DatasetRow` (drag handle area replaced
     by a spinner), label = `p.label`, subtitle "Installing…", non-interactive (not draggable, no
     click).
   - `DatasetInstallingCard` (drawer) — `DatasetCard` shell with a spinner avatar, title `p.label`,
     a disabled/absent action area, caption "Installing…".
   Both take a single `PendingInstall` prop. Centralizes the visual; no logic.

5. **Safety timeout.** `beginPendingInstall` arms a timeout (e.g. 60s, matching the client exec
   timeout ceiling) that auto-clears the entry, so a crashed/aborted run can never leave a
   permanent spinner. Clear the timer on `endPendingInstall`.

---

## 4. Data and State Handling

- **Source of truth:** `pendingInstalls` in `FlowProvider` (volatile, session-only — placeholders
  are inherently transient and must not persist or be saved into the spec).
- **Derived values:** each surface filters out pending entries already represented by a real
  installed catalog item (match by `producerNodeId` then `datasetId`). The palette's trigger count
  (`DatasetsPaletteDropdown.tsx:101`) and the drawer tab badges may optionally include pending
  entries so counts don't visibly "jump" when the real row replaces the placeholder — decide per
  surface; default: include pending in the count.
- **Lifecycle:** begin at operation start → clear on completion/error → reconcile-suppress when the
  real row lands → hard timeout as a backstop. No begin without a guaranteed clear path.
- **Race/flicker avoidance:**
  - Clear *after* `persistInstalledDataset` resolves so the placeholder is replaced, not briefly
    removed-then-re-added.
  - The reconcile-suppress filter prevents a transient state where both the placeholder and the real
    row show.
  - Synced ref for `pendingInstalls` so concurrent node completions add/remove correctly.

---

## 5. UI and UX Requirements

- A placeholder row/card appears **immediately** when an install starts (node run begins, or
  install/import is clicked), in the palette and the (open) drawer.
- Placeholder shows: a **spinner/loading icon**, the dataset/node **label**, and an "Installing…"
  caption. It is visually subdued (skeleton/disabled styling) and **non-interactive** (no drag, no
  install/uninstall actions).
- When the install completes, the placeholder is replaced by the real installed row (no duplicate,
  no flicker). On failure, the placeholder disappears (and the existing error toast remains the
  failure channel).
- Consistent placement: pending rows render at the **top** of the installed list in both surfaces.
- The empty-state copy ("No installed datasets yet." / "Install, import, or compute a dataset…")
  must **not** show while a placeholder is present.
- **Accessibility:** each placeholder uses `role="status"` / `aria-busy="true"` with accessible
  text like "Installing <label>…"; the spinner icon is `aria-hidden` with visually-hidden label.
  Matches the drawer's existing `aria-busy`/`aria-label` skeleton pattern (`DatasetCatalogDrawer.tsx:155`).

---

## 6. Edge Cases

- **Node run that errors / produces no dataset:** clear the pending entry in
  `processExecutionResult`'s error path and when `result.installedDataset` is absent.
- **Re-run while a pending entry for that node exists:** keyed by `nodeId` → idempotent upsert
  (single placeholder, timer restarts). Covers the remove-then-rerun flow.
- **Multiple producing nodes ("play all"):** one placeholder per node, all visible, each clearing
  as its node finishes.
- **Real row already present (re-install / needsReinstall):** reconcile-suppress prevents a
  duplicate placeholder; optionally still show a subtle "updating" state (out of scope — keep it
  simple: suppress).
- **Drawer closed during install, reopened later:** `pendingInstalls` lives in context, so reopening
  shows any still-pending placeholders; completed ones are already gone.
- **Crashed/aborted execution (no callback):** safety timeout clears the entry.
- **Guest / shared (read-only) mode:** installs don't happen, so no pending entries; nothing to
  render.
- **Import sentinel collisions:** only one import runs at a time (`importInFlightRef`,
  `useDatasetCatalogDrawer.ts`), so the `"import"` key is safe.

---

## 7. Testing Strategy

- **Pending store (unit, `useWorkflowOperations`):** `beginPendingInstall` upserts by key (no
  duplicates on re-run); `endPendingInstall` removes; timeout auto-clears; ref stays in sync for
  rapid begin/clear. (Extend `tests/hook/useWorkflowOperations.installSync.test.ts`.)
- **CodeEditor wiring (component):** begins a pending entry for a saver node on run and clears it on
  success and on error; never begins for a non-saver node.
- **Palette (component):** renders an installing placeholder for a pending entry; suppresses it once
  a matching installed catalog item is present; empty-state hidden while pending.
- **Drawer (component):** same placeholder behavior in the list and Installed tab; import shows a
  placeholder card.
- **Reconcile/no-duplicate (integration):** with both a pending entry and its real installed item,
  only the real row renders.

---

## 8. Acceptance Criteria

1. Running a producing node shows an "Installing…" placeholder (spinner + node label) in the palette
   and the open drawer **immediately**, before the dataset is visible.
2. When the install+save completes, the placeholder is replaced by the real installed row, with no
   duplicate and no visible flicker.
3. If the run fails (or yields no dataset), the placeholder is removed and no stale spinner remains.
4. Manual install shows a busy/placeholder affordance; **import** shows a placeholder row until it
   lands.
5. Multiple concurrent installs show multiple placeholders, each clearing independently.
6. Placeholders are non-interactive and never persist to the project spec or survive a reload.
7. A crashed/aborted install cannot leave a permanent placeholder (timeout backstop).
8. Empty-state messaging is suppressed while any placeholder is shown.
9. Accessible: placeholders expose `role="status"`/`aria-busy` with an "Installing <label>…" label.

---

## 9. Recommended Commit Breakdown

- **Commit 1 — pending-installs store + tests.** Add `pendingInstalls` state/ref +
  `beginPendingInstall`/`endPendingInstall` (with timeout) to `useWorkflowOperations`; expose via
  `FlowProvider` type + defaults; unit tests.
- **Commit 2 — wire the boundaries.** Begin/clear in `CodeEditor` (execution + result) and in
  `useDatasetCatalogDrawer` (`onInstall`, `onPickImport`).
- **Commit 3 — palette placeholders.** `DatasetInstallingRow` + render `visiblePending` in
  `DatasetsPaletteDropdown`; count + empty-state handling; CSS.
- **Commit 4 — drawer placeholders.** `DatasetInstallingCard` + render in `DatasetCatalogDrawer`
  list and `InstalledDatasetsList`; CSS; component/regression tests.

---

## 10. Engineering Quality Checklist

- [ ] Single source of truth for pending installs (no per-surface duplicate state).
- [ ] Every `beginPendingInstall` has a guaranteed clear path (success, error, timeout).
- [ ] Reconcile-suppress prevents placeholder + real-row duplication and flicker.
- [ ] Placeholder components are presentational only; loading visual defined once per surface.
- [ ] Pending state is volatile — never serialized into the spec, never survives reload.
- [ ] Types explicit (`PendingInstall`); context defaults provided.
- [ ] Accessible status semantics; spinner has non-visual label.
- [ ] Empty-state and counts stay consistent with placeholders present.
- [ ] Concurrent installs handled (keyed by node id / dataset id / import sentinel).
- [ ] Tests cover store lifecycle, wiring, both surfaces, and the no-duplicate case.
