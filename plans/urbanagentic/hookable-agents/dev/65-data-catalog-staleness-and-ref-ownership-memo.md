# Dev/65 — Data Catalog: stale listings, dataset-ref ownership, and install-replace semantics

Implementation memo. Covers the three approved fixes from the 2026-08-06 data-catalog investigation:

1. **Fix 1 — catalog cache staleness:** wholesale, generation-guarded invalidation of the frontend catalog response cache (plus eviction).
2. **Fix 2 — dataset-ref ownership:** make `spec.dataflow.datasets` backend-owned on save, mirroring the `preserve_agent_state` pattern, so canvas saves can never clobber install/uninstall state.
3. **Fix 3 — install-replace semantics:** each install **completely replaces** any existing ref for the same `datasetId` (no dict-merge of old fields).

---

## 1. Problem Statement

### 1a. The catalog serves pre-mutation (stale) listings

`catalogResponseCache` is a module-level map shared by every catalog surface
(`services/datasetCatalog/datasetCatalogHooks.ts:30`). Each distinct query — tab origin ×
search × sort × `includeHub` × `groupOsm` × serialized `liveOutputs` — is its own cache key
(`catalogFetchKey`, `:33-44`). After a mutation (install, uninstall, publish, unpublish,
delete, import), `reload({ bustCache: true })` deletes **only the invoking hook's current
key** (`:113-115`). Every other key keeps its pre-mutation response and is served as the
*initial* render whenever that key is next viewed: the `useState` initializer peeks the
cache (`:100-101`) and the hydrate effect re-applies it on key change (`:154-161`) before
the network refetch lands. On a slow backend the stale view persists visibly.

Two aggravators:

- `notifyDatasetCatalogRefresh()` (`datasetCatalogApi.ts:37-41`) is a window event; only
  *mounted* listeners refetch (`useDatasetCatalogDrawer.ts:71-76`,
  `DatasetPaletteContext.tsx:53-57`), and each busts only its own key. Nothing ever clears
  the shared cache wholesale.
- The cache never evicts. Every `liveOutputs` change (i.e., every node execution) mints a
  new key, so the map grows without bound for the life of the page.

There is also a latent **stale write-back race**: `reload()` writes
`catalogResponseCache[fetchKey] = next` after `await` (`:136`), gated only on that hook
instance's `fetchGenRef`. A fetch that *started before* a mutation can complete *after* it
and re-populate the cache with pre-mutation data that then survives as the "fresh" entry.

### 1b. Canvas saves clobber backend-written dataset refs (last-writer-wins)

`installed`/`uninstalled` state derives from `spec.dataflow.datasets` refs persisted in the
project spec (`backend/app/datasets/repositories/installed.py:33-39`). Those refs are
written by **two independent writers**:

- The dataset endpoints (install/uninstall/publish/unpublish/delete) via
  `InstalledDatasetRepository.replace_refs` (`installed.py:132-146`), which read-modify-writes
  the on-disk spec through `update_project`.
- **Every canvas save**, which serializes the client's in-memory `dataflowDatasetsRef` into
  the spec (`hook/useWorkflowOperations.ts:675` and `:936`, 7th argument to
  `TrillGenerator.generateTrill`).

Whichever writes last wins. In-session mitigations exist (serialized saves, live refs,
`syncDatasetsFromSavedSpec` after each save), but a second tab, a second session, or any
divergence between client state and what the backend wrote (e.g., an install that landed
between the client's last sync and its next save) resurrects removed refs or drops fresh
installs. This is the same defect class already fixed for `dataflow.agents` /
`agentAttachments`, which are backend-owned on save via `preserve_agent_state`
(`backend/app/projects/services.py:455-459`).

### 1c. Reinstalling merges into the old ref instead of replacing it

`install_dataset` upserts the dataflow ref with `existing.update(ref)`
(`backend/app/datasets/application/mutations.py:564-571`). `dict.update` merges: keys
present on the **old** ref but absent from the new one survive forever. Consequences:

- A legacy "fat ref" (title/path/format/sizeBytes stored inline,
  `mutations.py:806-830`) never converges to the lean `{datasetId, dirName, origin,
  producerNodeId, installedAt}` form on reinstall — its stale inline metadata (old path,
  old title, old format) keeps leaking into the catalog via `installed.list_items`'s
  legacy branch (`installed.py:102-129`).
- Stale flags (`publishedToHub`, `sourceOrigin`) ride along across reinstalls even when the
  new install knows nothing about them.

**Decided behavior:** an install fully replaces any existing ref for the same `datasetId`.
The new ref is exactly what `_ref_from_item` produces from the freshly installed item —
nothing is inherited from the old ref.

### Affected surfaces

Data Catalog drawer (all four tabs: Featured / Browse all / Installed / Computed), dataset
palette dropdown and `DatasetPaletteContext` producer chips, `DatasetDetailModal` fallback
row, installed/computed tab counts, and spec persistence (project save / load / reload).

### Why it matters

Correctness (uninstalled datasets reappear; fresh installs vanish on the next save; a
reinstall shows the previous install's metadata), user trust (the catalog visibly
contradicts actions the user just took), memory (unbounded cache growth), and
maintainability (two writers for one spec section is an invariant violation that will keep
producing new bugs until ownership is single).

---

## 2. Scope

### In scope

Frontend:

- `src/services/datasetCatalog/datasetCatalogHooks.ts` — cache invalidation, generation
  guard, eviction.
- `src/services/datasetCatalog/datasetCatalogApi.ts` — `notifyDatasetCatalogRefresh`
  becomes the single invalidation chokepoint; `applyInstalledDatasetToProject` call path.
- `src/components/datasets/catalog/useDatasetCatalogDrawer.ts`,
  `src/providers/DatasetPaletteContext.tsx`, palette dropdown hook — simplify now-redundant
  per-key `bustCache` calls.
- `src/hook/useWorkflowOperations.ts` — stop serializing dataset refs into saved specs;
  re-point `persistInstalledDataset` at the install endpoint; keep
  `syncDatasetsFromSavedSpec` as the read-back.
- `TrillGenerator.generateTrill` call sites (the `dataflowDatasetsRef.current` argument).

Backend:

- `backend/app/projects/services.py::update_project` (and the create path) — carry
  `dataflow.datasets` forward from the on-disk spec on client saves.
- A datasets-section writer used by `InstalledDatasetRepository.replace_refs` that is
  exempt from the carry-forward (see §3, Fix 2c).
- `backend/app/datasets/application/mutations.py::install_dataset` — ref replace semantics.

Tests on both sides (see §7).

### Out of scope (intentionally)

- Per-installation card identity (one card per install). Explicitly rejected in favor of
  replace semantics; the catalog remains one card per dataset id.
- `dedupe_items` / `merge_catalog_items` behavior, OSM grouping, preview/download.
- Hub-registry publish-time snapshot staleness (stale titles when browsing from another
  dataflow). Real, but a separate metadata-refresh workstream; nothing here regresses it.
- The drawer/palette UI components' rendering logic beyond what the state changes require.

---

## 3. Recommended Implementation Approach

### Fix 1 — single invalidation chokepoint + generation guard + eviction

- Add a module-level **cache epoch** to `datasetCatalogHooks.ts` and an exported
  `invalidateDatasetCatalogCache()` that clears the whole `catalogResponseCache` and bumps
  the epoch. One function, one map, one file — no per-surface knowledge required.
- Call it **inside `notifyDatasetCatalogRefresh()`**, before dispatching the window event.
  This is the key move: invalidation becomes independent of which components happen to be
  mounted. Mounted hooks still refetch via the existing event listeners; unmounted surfaces
  simply find no stale entry on their next mount.
- **Generation guard:** `reload()` records the epoch when its fetch starts and only writes
  the response into the cache if the epoch is unchanged when it resolves. The local
  `setResponse` may still apply (freshest data the hook has), but the *shared cache* must
  never be repopulated by a fetch that straddled an invalidation.
- **Eviction:** cap the cache (LRU, ~16 entries; touch on read in `peekCatalogCache` and on
  write). This bounds the `liveOutputs`-driven key churn.
- Simplify call sites: with wholesale invalidation, the mutation paths in
  `useDatasetCatalogDrawer` can call plain `reload()` after `notifyDatasetCatalogRefresh()`
  — the `bustCache` option becomes internal-only or is removed. Keep the
  stale-while-revalidate behavior for ordinary navigation (tab switches within one epoch);
  it is only *cross-mutation* reuse that must die.
- `prefetchDatasetCatalog` needs no change: post-invalidation the map is empty, so prefetch
  fetches fresh by construction.

### Fix 2 — `dataflow.datasets` becomes backend-owned on save

Mirror the agents pattern, with one extra wrinkle: unlike agents, the datasets section has
a *legitimate backend writer* that itself goes through the project-save path.

- **(a) Client stops serializing the section.** `TrillGenerator.generateTrill` call sites
  stop passing `dataflowDatasetsRef.current` (the generator omits `dataflow.datasets`
  entirely, exactly as it already omits `dataflow.agents`). `dataflowDatasets` state
  remains as a **read-only mirror** for UI (palette counts, optimistic rows), hydrated by
  `syncDatasetsFromSavedSpec(detail.spec)` after every save and by catalog fetches.
- **(b) Backend carries the section forward.** In `update_project`, inside the existing
  `spec_write_lock` block and alongside `preserve_agent_state`
  (`projects/services.py:447-469`): when `data.spec is not None`, overwrite
  `effective_spec.dataflow.datasets` with the on-disk `existing_spec`'s list (empty list
  when absent). Implement as `preserve_dataset_refs(effective_spec, existing_spec)` in the
  datasets application layer so ownership logic lives with the datasets domain, imported by
  the projects service the same way `preserve_agent_state` is.
- **(c) The dataset endpoints must bypass the carry-forward** — otherwise
  install/uninstall would clobber themselves (`replace_refs` sends a full spec through
  `update_project`, and the preserve step would immediately reset its fresh refs to the
  on-disk ones). Recommended shape: `replace_refs` stops round-tripping through
  `update_project` and instead uses a dedicated section writer that, under the same
  `storage.spec_write_lock`, re-reads the on-disk spec, replaces only
  `dataflow.datasets`, and writes it back (bumping the project row's timestamp the same
  way `update_project` does). This makes the datasets endpoints the *only* writer of the
  section and removes the two-writer race by construction, rather than by a flag. (An
  alternative — a `datasets_authoritative` flag on `ProjectUpdate` — works but widens a
  public schema for an internal concern; prefer the dedicated writer.)
- **(d) Re-point the one client path that stages refs via save.**
  `persistInstalledDataset` (`useWorkflowOperations.ts:797-825`) currently stages a ref
  into `dataflowDatasetsRef` and relies on the next save to persist it. Under (a) that
  ride-along no longer persists anything. Replace it: call the install endpoint
  (`datasetCatalogApi.installToDataflow`) for the payload's dataset (after
  `ensureProjectId()`), keep the optimistic mirror update for immediate UI, then
  `notifyDatasetCatalogRefresh()`. Fix 3's replace semantics make this call idempotent and
  safe to repeat.
- **(e) Load path unchanged.** `syncDatasetsFromSavedSpec` and project load continue to
  read `spec.dataflow.datasets`; only write ownership changes.
- The removed-`_preserve_persisted_computed_refs` rationale (`services.py:484-490`) is
  superseded: with the client no longer sending the section, the carry-forward is the only
  way refs survive a save, and it cannot resurrect uninstalled refs because uninstall
  removes them from the on-disk spec — the thing being carried forward.

### Fix 3 — install fully replaces the existing ref

In `install_dataset` (`mutations.py:564-571`): build the new ref via `_ref_from_item`,
then `refs = [r for r in refs if r.get("datasetId") != item["id"]] + [new_ref]` (append at
end — matches the frontend's `upsertDataflowDatasetRef` ordering). Remove the
`existing.update(ref)` branch.

Intentional field-drop semantics (document in the code):

- **Legacy fat-ref fields** (`title`, `path`, `format`, `sizeBytes`, …): dropped by design —
  a reinstall of a folder-backed dataset converges the ref to the lean form, and the
  manifest becomes the metadata authority again.
- **`publishedToHub`:** dropped from the ref. The Published badge derives from the
  authoritative source — the hub registry row merged in by `dedupe_items` /
  `merge_catalog_items` (`domain/dedup.py:52-58`) — so an installed-and-published dataset
  still shows Published. This follows the project convention of fixing primary paths over
  carrying compensating state.
- **`consumerNodeIds`:** no behavior change in practice — `_ref_from_item` always emits the
  key (`mutations.py:802`, `:824`), so the old `dict.update` already overwrote it. Consumer
  linkage remains derived from canvas bindings at read time (`listing.py:293` comment).
- **`installedAt`:** always the new install's timestamp — "reinstalled now" is the truthful
  state and drives Installed-tab sorting.

### Recommended order

Fix 3 → Fix 2 → Fix 1. Fix 3 makes the install endpoint a safe idempotent replace, which
Fix 2(d) depends on; Fix 1 is independent but verifying it end-to-end is easiest when the
backend state transitions are already trustworthy.

---

## 4. Data and State Handling

Source-of-truth table after this change:

| Data | Owner / source of truth | Consumers |
| --- | --- | --- |
| Hub registry rows | `<repo_root>/datasets/` manifests (request-scoped scan) | catalog listing |
| Account-level assets | user store manifests | catalog listing, palette |
| Per-dataflow installs (`dataflow.datasets`) | **backend dataset endpoints only** (section writer under `spec_write_lock`) | listing `installed` flags, load path, client mirror |
| Client `dataflowDatasets` | read-only mirror of last saved spec + optimistic install rows | palette counts, drawer optimistic UI |
| `catalogResponseCache` | per-session render cache, epoch-scoped | all `useDatasetCatalog` hooks |

- **Derived values:** `installed` flags, Published badges, consumer counts are computed at
  listing time from the authoritative rows — never persisted redundantly on refs beyond
  what `_ref_from_item` emits.
- **Loading / refresh:** stale-while-revalidate is kept *within* an epoch (tab switches
  render the cached list instantly while refetching). Across a mutation the epoch bumps, so
  the next render of any key starts from loading/skeleton or the hook's in-memory response —
  never a pre-mutation cache entry.
- **After user actions:** mutation → backend persists → `notifyDatasetCatalogRefresh()`
  (clears cache + event) → mounted hooks refetch → `syncDatasetsFromSavedSpec` keeps the
  mirror aligned on the next save round-trip.
- **Race safety:** epoch guard prevents in-flight fetches from repopulating the cache
  post-invalidation; `fetchGenRef` (existing) keeps per-hook responses ordered; all
  `dataflow.datasets` writes serialize under `spec_write_lock`; saves remain serialized
  client-side via `saveChainRef`.
- **No duplicated state introduced:** the mirror already exists; this change narrows its
  role rather than adding state.

---

## 5. UI and UX Requirements

- After install/uninstall/publish/unpublish/delete/import, every open catalog surface
  (drawer tab, palette dropdown, producer chips) reflects the new state after one refetch —
  no page refresh, no drawer close/reopen required.
- No pre-mutation rows may reappear after the action's toast has shown (the current
  symptom).
- Keep existing loading affordances: skeleton cards only on a truly empty first load
  (`aria-busy` list, `DatasetCatalogDrawer.tsx:171-177`); the `refreshing` dim state for
  revalidation — no list-clearing flash, no layout shift when a mutation invalidates the
  cache while the list is visible.
- Installed/Computed tab badge counts stay consistent with the rendered lists across tab
  switches during a refetch.
- A reinstalled dataset's card shows the *new* install's metadata (title from the current
  manifest, fresh `installedAt`); the Published badge persists when the dataset is still in
  the hub registry.
- Toasts unchanged. Keyboard/focus behavior of the drawer unchanged (provider focus
  restore already handled). No new interactive elements → no new a11y surface beyond
  keeping existing `aria-busy`/`role="status"` semantics intact.

---

## 6. Edge Cases

1. **Two tabs / two sessions:** install in tab A, then canvas save in tab B → B's save no
   longer carries a datasets section, the backend carries the on-disk refs forward, the
   install survives. Uninstall in A, save in B → the ref stays removed (nothing to
   resurrect).
2. **In-flight fetch straddling a mutation:** fetch starts, install completes and bumps the
   epoch, fetch resolves → response must not enter the shared cache (epoch guard); hook may
   render it momentarily but the already-triggered refetch supersedes it.
3. **Reinstall of a legacy fat ref:** ref converges to lean form; the listing renders from
   the manifest; no stale inline path/title remains.
4. **Reinstall of a published dataset:** `publishedToHub` dropped from the ref; badge still
   shown via hub-row merge. Verify the unpublish flow (which sets an explicit
   `publishedToHub: false` on the ref, `useDatasetCatalogDrawer.ts:299-309` /
   `dedup.py:52-58`) still suppresses the badge.
5. **OSM group install/uninstall:** loops per member (`mutations.py:585-608`); each member
   ref is replaced independently; group uninstall stays tolerant of never-installed members.
6. **Brand-new unsaved dataflow:** `ensureProjectId()` creates the project first; the
   create path has no existing spec, so carry-forward must treat "no on-disk spec" as an
   empty section, not an error — and must not wipe refs written by an install that raced
   the first save (serialized by `spec_write_lock` + the section writer re-reading disk).
7. **Auto-install payload after execution** (`persistInstalledDataset`): endpoint call
   fails (offline) → keep the optimistic mirror row, show the existing toast, and let the
   next successful refresh reconcile; repeated payloads for the same dataset are idempotent
   under replace semantics.
8. **Rapid repeated install clicks:** `busyId` guard plus idempotent replace — the second
   install yields the same single ref.
9. **Import (register-only):** writes no ref; invalidation must still refresh all surfaces
   so the new account-level rows appear (existing `notifyDatasetCatalogRefresh` call,
   now with teeth).
10. **`liveOutputs` churn:** many short-lived keys → LRU eviction keeps the map bounded;
    evicting a key a mounted hook still uses only costs one refetch.
11. **Spec with malformed/duplicate refs on disk** (pre-fix residue): the section writer
    and `preserve_dataset_refs` pass through only `isinstance(ref, dict)` rows (matching
    `list_refs`); duplicate `datasetId`s collapse naturally on the next install of that id.

---

## 7. Testing Strategy

Frontend (jest, under `src/tests/` — run via the `curio-feat` conda env):

- **Unit — cache:** `invalidateDatasetCatalogCache` clears all keys and bumps the epoch;
  post-invalidation `peekCatalogCache` misses for every key; LRU evicts beyond the cap and
  refreshes recency on read; the epoch guard blocks a straddling fetch from writing the
  shared cache (extend `src/tests/services/datasetCatalogApi.test.ts` /
  hooks tests).
- **Unit — notify:** `notifyDatasetCatalogRefresh` clears the cache even with zero mounted
  listeners.
- **Component:** drawer shows post-mutation items after install/uninstall without remount;
  switching to a tab whose key was cached pre-mutation does not flash pre-mutation rows;
  palette producer chips update on the refresh event (extend
  `useDatasetCatalogDrawer.import.test.ts`, `DatasetGroupRow`/palette tests).
- **Integration — save path:** generated Trill spec omits `dataflow.datasets`;
  `syncDatasetsFromSavedSpec` hydrates the mirror from `detail.spec`;
  `persistInstalledDataset` calls the install endpoint and no longer stages refs into the
  saved spec (extend `src/tests/hook/useWorkflowOperations.installSync.test.ts`).

Backend (pytest, `backend/tests/test_datasets/`):

- **Replace semantics:** install → reinstall yields exactly one ref whose key set equals
  `_ref_from_item`'s output (stale keys gone); legacy fat ref converges to lean on
  reinstall; `installedAt` updates; published dataset's badge survives reinstall via hub
  row; explicit unpublish still suppresses it.
- **Ownership:** client-style `update_project(spec=...)` without a datasets section
  preserves on-disk refs; a client save *with* a (stale) datasets section is ignored in
  favor of on-disk (the clobber regression test); uninstall → client save does not
  resurrect; install → client save does not drop.
- **Section writer:** replaces only `dataflow.datasets`, leaves agents/nodes/edges intact,
  serializes under `spec_write_lock` (concurrent install + save test), bumps project
  timestamps consistently.
- **Create path:** first-ever save of a new dataflow with a racing install keeps the ref.

Required before completion: the two regression tests named for the reported symptoms —
"uninstalled dataset reappears after canvas save" and "catalog serves pre-mutation listing
after install" — plus the replace-semantics unit tests.

---

## 8. Acceptance Criteria

1. After any dataset mutation, no catalog surface (drawer tab, palette dropdown, detail
   modal fallback) renders pre-mutation data — regardless of which surfaces were mounted at
   mutation time, on the next paint-plus-refetch, with no page refresh.
2. Installing a dataset, then saving the canvas (same or different tab/session), leaves the
   ref installed; uninstalling then saving leaves it uninstalled. `spec.dataflow.datasets`
   on disk changes **only** via dataset endpoints.
3. Client-generated specs contain no `dataflow.datasets` section; loading a project still
   restores installed state from the on-disk spec.
4. Reinstalling a dataset produces exactly one ref containing only `_ref_from_item` fields;
   no field from the prior ref survives; a legacy fat ref becomes lean.
5. A published, installed dataset still shows its Published badge after reinstall; an
   explicitly unpublished one does not.
6. `catalogResponseCache` never exceeds its cap; a fetch resolving after an invalidation
   does not repopulate the cache.
7. No new flicker: revalidation keeps the current list visible (dim/`refreshing`), skeletons
   only on genuinely empty first load.
8. All new/updated tests in §7 pass; existing catalog test suites
   (`test_computed_catalog_api.py`, `test_computed_uninstall_and_delete.py`,
   `useDatasetCatalogDrawer` suites) pass unchanged in intent.

---

## 9. Recommended Commit Breakdown

1. **Commit 1 — backend install-replace semantics (Fix 3):** `install_dataset` ref
   replacement + field-drop rationale comment + replace/convergence/badge tests. Smallest,
   independent, unblocks the rest.
2. **Commit 2 — backend-owned datasets section (Fix 2, server half):**
   `preserve_dataset_refs` in `update_project`; dedicated datasets-section writer;
   `replace_refs` re-pointed to it; ownership + concurrency + create-path tests.
3. **Commit 3 — frontend save/ref plumbing (Fix 2, client half):** stop passing datasets to
   `TrillGenerator.generateTrill`; `persistInstalledDataset` → install endpoint; mirror
   hydration unchanged; installSync/spec-shape tests.
4. **Commit 4 — frontend cache invalidation (Fix 1):** epoch + wholesale clear inside
   `notifyDatasetCatalogRefresh`; LRU eviction; epoch-guarded cache writes; simplify
   `bustCache` call sites; cache/regression tests.

Each commit leaves the app consistent: 1 and 2 are backward-compatible with a client that
still sends the section (the preserve step simply ignores it), so 3 can ship separately.

---

## 10. Engineering Quality Checklist

- [ ] Single writer for `spec.dataflow.datasets`; no compensating client-side merge logic
      remains.
- [ ] Invalidation logic lives in one module (`datasetCatalogHooks.ts`) behind one exported
      function; no per-surface cache knowledge.
- [ ] No duplicated ref-shape logic: `_ref_from_item` (backend) and
      `dataflowRefFromCatalogItem` (frontend mirror) remain the only builders; note their
      required parity in both files.
- [ ] Types explicit for the new exports (invalidate function, section writer signature);
      no `any` additions.
- [ ] State updates race-safe: epoch guard, `spec_write_lock`, serialized saves all
      verified by tests, not by inspection alone.
- [ ] UI: no list-clearing flash, no layout shift, `aria-busy`/`role="status"` semantics
      preserved.
- [ ] Loading / empty / error / success states re-verified on the Installed and Computed
      tabs (counts + empty copy) after invalidation.
- [ ] Regression tests exist for both reported symptoms and for the fat-ref convergence.
- [ ] No behavior change outside the requested ones: dedupe/merge, OSM grouping, publish
      flows untouched.
- [ ] Follows existing conventions: `preserve_agent_state` pattern, lean-ref philosophy,
      "fix primary paths, no fallbacks."
