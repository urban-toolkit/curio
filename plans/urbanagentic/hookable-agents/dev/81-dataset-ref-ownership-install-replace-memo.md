# Dev/81 — Dataset-ref ownership (Fix 2) and install-replace semantics (Fix 3)

Status: implemented (2026-08-18, commits `00310cb6` Fix 3 / `70d54177` Fix 2 backend /
`c5ac63eb` Fix 2 frontend cleanup; build-log entry BL-P5-20260818-27). Implementation
notes: two existing suites encoded the old contract and were updated intent-preserved —
`test_computed_catalog_api.py::test_published_computed_dataset_stays_installed_in_dataflow_catalog`
now seeds its publish ref through `replace_refs` instead of a client-style save, and the
three `merge_dataflow_dataset_ref` unit tests in `test_projects/test_storage.py` became
`replace_dataflow_datasets` tests (missing-project, section-isolation replace, section
creation). One pre-existing exposure surfaced (documented, not fixed here): two
concurrent installs of *different* datasets can lose one, because `install_dataset`'s
`list_refs` → `replace_refs` read-modify-write spans two lock acquisitions — the old
`update_project` round-trip had the identical window.

Implementation memo operationalizing the two remaining approved fixes from dev/65
(`65-data-catalog-staleness-and-ref-ownership-memo.md`, approved 2026-08-06; Fix 1 —
catalog cache invalidation — was implemented in `COMMIT-f857e3f3`). This memo re-grounds
Fixes 3 and 2 against the code as of 2026-08-18 (branch `bug/datacalog`, HEAD `ed66a638`)
and records three deviations from the dev/65 design, each forced by changes that landed
in between:

- **D1 — the client keeps serializing `dataflow.datasets`; the backend ignores it on
  update.** dev/65 §Fix 2(a) had the client stop sending the section entirely. Since
  then, two flows were confirmed to *depend* on the client-sent section as a create-time
  seed: `saveAsNewProject` ("Save a copy", `hook/useWorkflowOperations.ts:941`) and trill
  import (`loadParsedTrill` → `incomingDatasets`, `:253`). Ownership is therefore enforced
  server-side: **update ignores the client section (carry-forward from disk); create
  accepts it as the seed.** This is also rollout-safe — an old frontend against the new
  backend changes nothing.
- **D2 — dev/65 §Fix 2(d) is moot; the code it re-pointed is dead.** The
  computed-datasets-→-account-catalog change removed every production caller of
  `persistInstalledDataset` and `applyInstalledDatasetToProject`. The live execution path
  is `persistDataflowForInstall` (a plain save; `FlowProvider.tsx:1560`), and neither
  execution-time auto-install (`auto_install.py:176-180`) nor save-time
  `_auto_install_computed_outputs` (`projects/services.py:172` docstring) writes a
  `dataflow.datasets` ref anymore. The dead client staging path is *removed*, not
  re-pointed.
- **D3 — `merge_dataflow_dataset_ref` is deleted.** `projects/storage.py:465-503` has no
  callers (only two stale comments reference it) and contains its own `{**existing,
  **ref}` merge — the exact Fix-3 defect in a second location. The new datasets-section
  writer replaces it.

---

## 1. Problem Statement

### 1a. Canvas saves clobber backend-written dataset refs (last-writer-wins)

`spec.dataflow.datasets` — the per-dataflow install state — has **two writers**:

- The dataset endpoints (install / uninstall / publish / unpublish), which persist refs
  via `InstalledDatasetRepository.replace_refs`
  (`backend/app/datasets/repositories/installed.py:132-146`) — currently by
  round-tripping a **full spec** through `projects.services.update_project`.
- **Every canvas save**: the client serializes its in-memory `dataflowDatasetsRef` into
  the spec (`hook/useWorkflowOperations.ts:680`, `:941` — 7th argument to
  `TrillGenerator.generateTrill`, `TrillGenerator.ts:119`) and the backend writes it
  verbatim.

Whichever writes last wins. In-session mitigations (serialized saves via `saveChainRef`,
live refs, `syncDatasetsFromSavedSpec` after each save) narrow but cannot close the
window: a second tab, a second session, the 30-second auto-save
(`useWorkflowOperations.ts:920-930`), or any drift between the client mirror and what the
backend wrote resurrects uninstalled refs or drops fresh installs. The identical defect
class was already fixed for `dataflow.agents`/`agentAttachments` via `preserve_agent_state`
(`projects/services.py:455-459`) — and the memory note `agent-spec-backend-owned-sections`
records what happens without it: state vanishes on refresh.

### 1b. Reinstalling merges into the old ref instead of replacing it

`install_dataset` upserts with `existing.update(ref)`
(`backend/app/datasets/application/mutations.py:564-571`). `dict.update` merges: keys on
the **old** ref absent from the new one survive forever.

- A legacy "fat ref" (inline `title`/`path`/`format`/`sizeBytes`, emitted by
  `_ref_from_item`'s no-`dirName` branch, `mutations.py:806-830`) never converges to the
  lean `{datasetId, dirName, origin, producerNodeId, consumerNodeIds, installedAt}` form
  on reinstall, so its stale inline metadata keeps rendering through
  `installed.list_items`'s legacy branch (`installed.py:102-129`).
- Stale flags ride along: `publishedToHub` (written onto refs by publish/unpublish,
  `mutations.py:339-356` and `:711-723`) and `sourceOrigin` survive reinstalls the new
  install knows nothing about.

**Decided behavior (dev/65, owner decision):** an install fully replaces any existing ref
for the same `datasetId`; the new ref is exactly `_ref_from_item`'s output. One card per
dataset id stays (per-installation card identity was explicitly rejected).

### Affected surfaces

Data Catalog drawer (all tabs and their mutation handlers,
`components/datasets/catalog/useDatasetCatalogDrawer.ts:176-355`), dataset palette /
`DatasetPaletteContext` counts (fed by the `dataflowDatasets` mirror), project
save/load/copy/import, and the dataset endpoints' persistence path.

### Why it matters

Correctness (uninstalled datasets reappear after a save; installs vanish; reinstalls show
the previous install's metadata), user trust (the catalog contradicts actions the user
just took), and maintainability (two writers of one spec section is an invariant
violation that keeps minting new bugs — the dev/65 Fix 1 cache work fixed the *display*
of stale state; this closes the *source* of it).

---

## 2. Scope

### In scope

Backend:

- `backend/app/datasets/application/mutations.py` — `install_dataset` replace semantics
  (`:564-571`).
- `backend/app/datasets/repositories/installed.py` — `replace_refs` re-pointed from the
  `update_project` round-trip to the new section writer.
- `backend/app/projects/services.py` — `update_project` carry-forward for
  `dataflow.datasets` (beside `preserve_agent_state`, inside `spec_write_lock`); the
  superseded rationale comment at `:484-490` rewritten; a service-level
  `replace_dataflow_datasets` (section write + project-row timestamp + commit).
- `backend/app/projects/storage.py` — new `replace_dataflow_datasets` storage primitive
  (lock → read → set section → write, modeled on `packages/services.py::_write_lockfile`,
  `:361-371`); delete dead `merge_dataflow_dataset_ref` (`:465-503`) and fix the two
  comments naming it (`projects/services.py:443`, `packages/services.py:363`).
- New ownership helper `preserve_dataset_refs` in the datasets application layer,
  imported by the projects service the same way `preserve_agent_state` is.

Frontend:

- `hook/useWorkflowOperations.ts` — remove dead `persistInstalledDataset` (`:802-830`)
  and its exports; comment updates at the `generateTrill` call sites documenting the
  create-seed / update-inert contract.
- `services/datasetCatalog/datasetCatalogApi.ts` — remove dead
  `applyInstalledDatasetToProject` (`:92-100`), `buildInstalledDatasetRef` (`:67-75`),
  `upsertDataflowDatasetRef` (`:78-89`); `InstalledDatasetPayload` if nothing else uses it.
- `providers/FlowProvider.tsx` — drop the `persistInstalledDataset` context entry
  (`:167`, `:290`).

Tests on both sides (§7).

### Out of scope (intentionally)

- Any change to the drawer/palette rendering, dedupe/merge (`domain/dedup.py`), OSM
  grouping, preview/download, or the Fix-1 cache layer (`datasetCatalogCache.ts`).
- `_prune_sink_node_dataset_refs` behavior (it stays, running after the carry-forward).
- The datasets id-migration writer (`datasets/application/migrations.py::_rewrite_spec_ref`)
  — it is a datasets-domain writer and already writes disk directly under the lock;
  backend ownership subsumes it unchanged.
- Hub publish-time metadata staleness (separate workstream, per dev/65).
- `persistDataflowForInstall` and the execution auto-install pipeline — live and correct;
  untouched.

---

## 3. Recommended Implementation Approach

### Fix 3 — install fully replaces the existing ref

In `install_dataset` (`mutations.py:564-571`), replace the upsert:

- Build `new_ref = self._ref_from_item(item)`, then
  `refs = [r for r in refs if r.get("datasetId") != item["id"]] + [new_ref]` and
  `self.installed.replace_refs(dataflow_id, refs)`. Delete the `existing.update(ref)`
  branch. (Append-at-end matches the previous no-existing behavior; the removed entry's
  position is not meaningful anywhere.)
- The producer-preservation block above it (`:543-562`) operates on the *item* before the
  ref is built and is untouched — `test_reinstall_producer.py` must pass unchanged.

Intentional field-drop semantics (state in a code comment):

- **Legacy fat-ref fields** (`title`, `path`, `format`, `sizeBytes`, …): dropped — a
  reinstall converges the ref to the lean form and the manifest becomes the metadata
  authority again.
- **`publishedToHub`:** dropped from the ref on reinstall. The badge still derives from
  the authoritative source: `dedupe_items`/`merge_catalog_items` set it from the hub-row
  merge (`domain/dedup.py:44-58`), and an *explicit* `publishedToHub: False` (written by
  unpublish, `mutations.py:711-723`) still suppresses it. Publish/unpublish continue to
  write the flag onto the ref (`mutations.py:339-356`) — that is a dataset-endpoint
  write and legitimate under Fix 2.
- **`installedAt`:** always the new install's timestamp — truthful "reinstalled now",
  drives Installed-tab recency.
- **`consumerNodeIds`:** no practical change; `_ref_from_item` always emits the key, so
  the old merge already overwrote it.

### Fix 2 — `dataflow.datasets` becomes backend-owned on update

**(a) Carry-forward in `update_project`.** New `preserve_dataset_refs(effective_spec,
existing_spec)` in the datasets application layer (suggested:
`datasets/application/ref_ownership.py`, mirroring `agents/project_agents.py::
preserve_agent_state`), called in `update_project` when `data.spec is not None`, inside
the `spec_write_lock` block right beside `preserve_agent_state`
(`projects/services.py:455-459`):

- `existing_spec` is a dict → overwrite `effective_spec["dataflow"]["datasets"]` with the
  on-disk section, filtered to `isinstance(ref, dict)` rows (matching `list_refs`,
  `installed.py:39`); absent section → `[]`. An on-disk spec *without* refs means "no
  installs" and must yield `[]` — keeping the client's rows here would reintroduce
  resurrection.
- `existing_spec` is `None` (no spec on disk yet) → leave the client section untouched.
  This is the create/seed rule expressed once: `create()` has no carry-forward at all, so
  "Save a copy" and trill import keep seeding refs (D1).
- Runs before `_prune_sink_node_dataset_refs` (`services.py:496-499`), which then cleans
  carried-forward stale sink refs exactly as it does today.
- Rewrite the now-superseded comment at `services.py:484-490`: the carry-forward is the
  mechanism by which refs survive a save, and it cannot resurrect uninstalled refs
  because uninstall removes them from the very on-disk section being carried.

**(b) Dedicated section writer; `replace_refs` stops round-tripping.** With (a) in place,
the current `replace_refs` → `update_project(spec=full_spec)` path would clobber itself
(the preserve step would reset its fresh refs to on-disk). Replace it:

- `projects/storage.py::replace_dataflow_datasets(user_key, project_id, refs) -> dict`:
  under `spec_write_lock` — re-read the spec, `spec.setdefault("dataflow", {})["datasets"]
  = refs`, `write_spec`, return the written spec. Direct precedent:
  `packages/services.py::_write_lockfile` (`:361-371`). Raise (or return `None` for the
  caller to 404) when the project has no spec.
- `projects/services.py::replace_dataflow_datasets(user, project_id, refs)`: resolve the
  project (`repo.get_for_user`), call the storage primitive, bump the project row's
  timestamp (`repo.upsert_project` with unchanged fields — same touch `update_project`
  performs), `db.session.commit()`, return the spec. No manifest rewrite: the manifest
  carries outputs/name/description only, so skipping it avoids churn.
- `InstalledDatasetRepository.replace_refs` (`installed.py:132-146`) delegates to that
  service function; its return contract (the written spec) is preserved for the routes'
  response shapes (`uninstallFromDataflow` returns `{datasets}`).
- Delete `merge_dataflow_dataset_ref` (`storage.py:465-503`, dead) and update the two
  comments that name it (D3).

After this, every writer of `dataflow.datasets` is backend-and-datasets-domain-owned:
the section writer (endpoints), the carry-forward + sink-prune (save path), and the id
migration — the two-writer race is gone by construction, not by a flag.

**(c) Client half — deletion, not re-pointing (D2).** Remove
`persistInstalledDataset` (`useWorkflowOperations.ts:802-830`, its export at `:1077`, the
FlowProvider context entries at `:167`/`:290`) and the dead API helpers
(`applyInstalledDatasetToProject`, `buildInstalledDatasetRef`, `upsertDataflowDatasetRef`
in `datasetCatalogApi.ts`). Their contract — "stage a ref client-side and let the next
save persist it" — becomes permanently wrong under (a); leaving them invites reuse
(memory: fix primary paths, no fallbacks). The `generateTrill` call sites and
`syncDatasetsFromSavedSpec` (`:652-662`) stay as they are: the client keeps sending the
section (create seed, update inert) and reconciles its mirror from the returned
`detail.spec`, which now always carries the authoritative refs.

### Recommended order

Fix 3 → Fix 2 (unchanged from dev/65): Fix 3 makes the install endpoint an idempotent
replace before Fix 2 concentrates all writes behind it. Each lands green independently.

---

## 4. Data and State Handling

| Data | Owner / source of truth | Consumers |
| --- | --- | --- |
| `spec.dataflow.datasets` on disk | dataset endpoints via the section writer; save-path carry-forward + sink-prune; id migration | `installed` flags, project load, `detail.spec` responses |
| Client `dataflowDatasets` + `dataflowDatasetsRef` | read-mostly mirror: hydrated by `syncDatasetsFromSavedSpec` after every save/create, optimistically updated by drawer mutation handlers | palette counts, drawer optimistic UI, **create-time seed only** |
| `publishedToHub` badge | hub-row merge (`dedup.py:44-58`) + explicit ref flag written by publish/unpublish | catalog cards |
| Ref shape | `_ref_from_item` (backend); the frontend no longer builds refs at all after (c) | — |

- **Update flow:** drawer action → endpoint → section writer under `spec_write_lock` →
  `notifyDatasetCatalogRefresh()` (Fix 1 clears the cache) → refetch; the next save's
  carry-forward preserves it; `syncDatasetsFromSavedSpec(detail.spec)` re-aligns the
  mirror — self-correcting even if the optimistic update drifted.
- **Create flow:** `ensureProjectId()` creates first (`useWorkflowOperations.ts:774-793`),
  so installs always target an existing project; "Save a copy"/import seed the new spec
  from the mirror; from the first update onward the section is backend-owned.
- **Race safety:** all disk writes of the section serialize under `spec_write_lock`
  (writer, carry-forward, migration); client saves stay serialized via `saveChainRef`; a
  save racing an install can no longer clobber it — the save's carry-forward re-reads
  disk *inside* the lock (`services.py:447-448`).
- **No new state**; the change narrows the mirror's role and deletes a dead write path.

---

## 5. UI and UX Requirements

No visual redesign — behavior-correctness only:

- Install → canvas save (manual, auto-save, other tab): the dataset stays installed;
  uninstall → save: it stays uninstalled. No page refresh needed anywhere.
- A reinstalled dataset's card shows the fresh manifest metadata and new `installedAt`
  (Installed-tab "Recent" ordering reflects the reinstall); the Published badge persists
  when the dataset is still in the hub, and stays suppressed after an explicit unpublish.
- "Save a copy" and trill import still carry the source dataflow's installed datasets
  into the new project.
- Existing loading/refresh affordances are untouched (Fix 1 owns those); no new flicker,
  layout shift, or list clearing may appear. Toasts, focus, and keyboard behavior
  unchanged; no new interactive elements → no new a11y surface.

---

## 6. Edge Cases

1. **Two tabs:** install in A, save in B → B's section is ignored on update, carry-forward
   keeps the ref. Uninstall in A, auto-save fires in B → stays removed. (The regression
   pair.)
2. **Save racing an install:** both serialize on `spec_write_lock`; whichever runs second
   re-reads disk inside the lock, so the install survives either ordering.
3. **First-ever save / no on-disk spec:** `preserve_dataset_refs` leaves the client
   section untouched (seed rule); `create()` unchanged.
4. **"Save a copy" of a dataflow with installs:** create path seeds the copied refs;
   verify computed refs still resolve (same user store, same node ids on the copied
   canvas).
5. **Trill import with `incomingDatasets`:** seeds on the subsequent create; an import
   whose refs point at datasets absent from this machine's store renders the existing
   broken-placeholder row (`installed.py:84-99`) — unchanged behavior.
6. **Reinstall of a legacy fat ref:** converges to the lean form; listing renders from
   the manifest; no stale inline title/path remains.
7. **Reinstall of a published dataset:** ref loses `publishedToHub`; badge derives from
   the hub-row merge. Explicit unpublish (`publishedToHub: False` + hub row removed)
   stays suppressed.
8. **OSM group install/uninstall:** loops per member (`mutations.py:585-608`); each member
   ref replaced independently; group uninstall stays tolerant of never-installed members.
9. **Publish/unpublish ref rewrites:** `mutations.py:325-358`/`:711-723` mutate refs then
   call `replace_refs` — now landing through the section writer; their id-remap +
   `dirName` rewrite behavior must be regression-tested through the new path.
10. **Endpoint failure mid-flow:** drawer optimistic mirror may briefly disagree; the
    existing error toasts fire and the next save's `syncDatasetsFromSavedSpec` restores
    the authoritative section — no permanent drift.
11. **Malformed/duplicate refs on disk (pre-fix residue):** carry-forward filters to dict
    rows; duplicates for one `datasetId` collapse on that dataset's next install.
12. **Guest/viewer saves:** blocked before any write (unchanged); `replace_refs` keeps
    its 401 on missing user.

---

## 7. Testing Strategy

Backend (`pytest backend/tests/test_datasets/`, run in the `curio-feat` conda env):

- **Fix 3 — new `test_install_replace_semantics.py`:** reinstall yields exactly one ref
  whose key set equals `_ref_from_item`'s lean output; a synthetic legacy fat ref
  converges on reinstall; `installedAt` updates; `publishedToHub` dropped from the ref
  but the badge survives via hub merge (compose with `test_publish_dataset.py` /
  `test_catalog_dedup.py` fixtures); explicit-unpublish suppression regression; OSM-group
  member replacement.
- **Fix 2 — new `test_dataset_ref_ownership.py`:** client-style `update_project` with a
  stale datasets section neither resurrects an uninstalled ref nor drops a fresh install
  (the two named regressions); outputs-only update untouched; no-on-disk-spec seed rule;
  create path seeds ("Save a copy" shape); section writer replaces only
  `dataflow.datasets` (agents/nodes/edges/packages byte-identical), bumps the project
  row's timestamp, 404s on a spec-less project; publish/unpublish id-remap through the
  new writer; concurrent install + save interleaving under the lock.
- **Unchanged-in-intent suites that must stay green:** `test_reinstall_producer.py`,
  `test_phantom_installed_computed.py`, `test_computed_uninstall_and_delete.py`,
  `test_import_uninstall_lifecycle.py`, `test_execution_dataset_persistence.py`.

Frontend (`npx jest` full, conda env for node):

- `tests/hook/useWorkflowOperations.installSync.test.ts`: delete the
  `persistInstalledDataset` describe block (`:141-274`); keep/extend
  `persistDataflowForInstall` and `ensureProjectId` coverage; add an assertion that a
  save round-trip re-hydrates the mirror from `detail.spec` (the authoritative section
  wins over a drifted mirror).
- `tests/services/datasetCatalogApi.test.ts`: drop tests for the removed helpers.
- `tsc --noEmit` clean (modulo the two pre-existing tsconfig deprecation notices).

Required before completion: the two ownership regressions ("uninstalled dataset does not
reappear after a canvas save", "fresh install survives a stale-mirror save") and the
fat-ref convergence test.

---

## 8. Acceptance Criteria

1. `spec.dataflow.datasets` on disk changes only via dataset-domain writers; a client
   `update_project` call can neither add nor remove refs, regardless of what its spec
   contains.
2. Install → save (same or other session) keeps the ref; uninstall → save keeps it
   removed — verified by automated regressions, not inspection.
3. "Save a copy" and trill import produce a new project whose spec contains the source's
   dataset refs.
4. Reinstalling produces exactly one ref containing only `_ref_from_item` fields; nothing
   from the prior ref survives; a legacy fat ref becomes lean; `installedAt` is the
   reinstall time.
5. Published+installed datasets keep their badge across reinstall; explicitly unpublished
   ones stay unbadged.
6. `merge_dataflow_dataset_ref`, `persistInstalledDataset`,
   `applyInstalledDatasetToProject`, `buildInstalledDatasetRef`, and
   `upsertDataflowDatasetRef` no longer exist in the codebase.
7. Full backend datasets suite and full frontend jest suite pass; publish/unpublish/
   import/OSM flows behave exactly as before through the new writer.
8. No UI regressions: no new flicker, no changes to drawer/palette rendering or timing
   beyond correct data.

---

## 9. Recommended Commit Breakdown

1. **Commit 1 — Fix 3, backend:** `install_dataset` replace semantics + field-drop
   rationale comment + `test_install_replace_semantics.py`. Smallest, independent.
2. **Commit 2 — Fix 2, backend:** `preserve_dataset_refs` + `update_project` wiring +
   rewritten `:484-490` comment; `replace_dataflow_datasets` (storage primitive + service
   wrapper); `replace_refs` re-pointed; `merge_dataflow_dataset_ref` deleted + comment
   fixes; `test_dataset_ref_ownership.py`. Backward-compatible with the unchanged client
   (its section is simply ignored on update).
3. **Commit 3 — Fix 2, frontend cleanup:** remove the dead staging path
   (`persistInstalledDataset`, FlowProvider entries, dead `datasetCatalogApi` helpers);
   contract comments at the `generateTrill` call sites; test updates.
4. **Docs commit:** this memo flipped to implemented + build-log entry (BL-P5), per the
   established pattern.

---

## 10. Engineering Quality Checklist

- [ ] Single ownership: no client-side ref construction or staging remains; every disk
      write of the section goes through datasets-domain code under `spec_write_lock`.
- [ ] `_ref_from_item` is the only ref builder anywhere.
- [ ] The seed rule (`existing_spec is None` → keep client section) is implemented once,
      in `preserve_dataset_refs`, with the copy/import rationale in its docstring.
- [ ] Section writer touches only `dataflow.datasets`; proven by a byte-comparison test
      on the rest of the spec.
- [ ] Project-row timestamp semantics match `update_project` (Recent sorting unaffected).
- [ ] No behavior change to dedupe/merge, OSM grouping, publish metadata, preview,
      Fix-1 cache, or `persistDataflowForInstall`.
- [ ] Both named regressions and the fat-ref convergence are covered by tests.
- [ ] Comments referencing deleted code (`merge_dataflow_dataset_ref`, the `:484-490`
      rationale) are updated in the same commit that changes the behavior.
- [ ] `pytest` datasets suite and frontend `npx jest` + `tsc --noEmit` verified green
      before each commit, per the build-log verification convention.
