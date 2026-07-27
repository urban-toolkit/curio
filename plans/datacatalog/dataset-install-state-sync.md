# Implementation Memo: Persist & display dataset installation state without a manual project save

**Status:** Implemented · **Branch:** `datacatalog` · **Author:** Karla
**Area:** `utk_curio/frontend/urban-workflows` (execution + save flow) and `utk_curio/backend/app/datasets`/`projects` (persistence)

---

## Addendum — follow-up fix: re-run after dataset removal

**Symptom:** After *removing* installed datasets and re-running the flow, the regenerated
datasets installed but did not appear until a manual disk-icon save. First-time install
worked (it creates the project, which round-trips and re-syncs the spec), but the
existing-project path did **not**.

**Root cause:** The original `persistInstalledDataset` took a lightweight path for an
existing project — optimistic in-memory ref + `notifyDatasetCatalogRefresh()` — relying on
the backend's *execution-time* `merge_dataflow_dataset_ref` to make the dataset show as
installed-for-the-dataflow. That merge was not reaching the same persisted+visible state
that a manual `update_project` save produces (which the user confirmed works). So the UI
stayed stale until a manual save.

**Fix (parity with the disk icon):** `persistInstalledDataset` now **always saves** the
project — create for a brand-new dataflow, **update** for an existing one — through a
single serialized save (`requestProjectSave`). `saveCurrentProject` already calls
`syncDatasetsFromSavedSpec(detail.spec)`, so the catalog refreshes from the **final
persisted spec** regardless of removal/re-run history. Supporting changes:

- **`projectIdRef`** mirrors `projectId`; `saveCurrentProject` now decides create-vs-update
  from the live ref (set the instant a create resolves), so a save chained right after a
  create can't POST a duplicate project.
- **`requestProjectSave`** serializes saves (one create can never run twice in parallel;
  every chained save then updates) and keeps a never-rejecting tail so a failed save can't
  leak an unhandled rejection or wedge the chain.
- **`ensureProjectId`** (used by the catalog drawer) keeps its create-only, de-duped
  behavior — it does **not** force a redundant save for an already-saved project.

**Tests updated:** the old "does not re-save an already-saved project" expectation was
replaced by "updates (not re-creates) an already-saved project so the UI resyncs", plus a
"serializes concurrent installs into one create + one update (no duplicate projects)" case.

> Note: each producing-node execution now triggers a project save (create/update). For
> "play all" this surfaces datasets incrementally as they're produced (desirable). If a
> very large flow makes the repeated full-spec saves costly, coalescing the serialized
> chain into a single trailing save is a safe follow-up optimization.

---

## 1. Problem Statement

**Current behavior.** When a node executes and produces a saveable output, the backend
auto-installs the dataset and the catalog UI *can* show it during the session — but the
dataset only becomes a **durable, reload-surviving member of the project** after the user
clicks the **Save Project** disk icon. Until that manual save, the installation looks
"done" in the moment yet is not actually persisted into the project, so:

- the install state reads as stale relative to what the user just did, and
- reloading the page **before** the manual save loses the linkage (and, for a brand-new
  dataflow, loses the project entirely).

**Root cause (precise).** The authoritative, reload-surviving "this dataset belongs to
this dataflow" association is the project spec's `dataflow.datasets` ref array
(`spec.trill.json`). On node execution:

- The backend (`processPythonCode` / `processJavaScriptCode` in
  `utk_curio/backend/app/api/routes.py`, ~L441–L451 / L531–L541) calls
  `auto_install_node_output(...)`. That function installs the parquet into the user
  dataset store **and**, *only when a `dataflow_id` is supplied*, merges a lean ref into
  the on-disk spec via `project_storage.merge_dataflow_dataset_ref(...)`
  (`utk_curio/backend/app/datasets/auto_install.py:73-87`).
- `merge_dataflow_dataset_ref` is a **no-op that returns `False` when the project spec
  file does not exist on disk** (`utk_curio/backend/app/projects/storage.py:417-455`,
  guard at `:428`).
- The frontend sends `dataflowId` **only when it is truthy**:
  `...(dataflowId ? { dataflowId } : {})` (`PythonInterpreter.ts:79`,
  mirrored in `JavaScriptInterpreter.ts`). The caller passes `projectId`
  (`CodeEditor.tsx:227`).

So for a **never-saved dataflow** (`projectId === null`): no `dataflowId` is sent → the
backend never writes a project ref → the dataset's membership in the dataflow exists only
in volatile React state (`dataflowDatasets` in `useWorkflowOperations.ts:96-101`) plus a
loose computed-dataset folder in the user store with no project linkage.

`applyInstalledDatasetToProject(...)`
(`services/datasetCatalog/datasetCatalogApi.ts:51-74`, invoked from
`CodeEditor.tsx:180-182`) updates that in-memory state and fires
`notifyDatasetCatalogRefresh()`, which is why the row can *appear* mid-session (the
backend listing also has a user-store fallback, `catalog_listing.py:96-104` →
`_mark_user_store_computed_installs`). But none of that is durable. Only the manual save
path makes it authoritative: `saveCurrentProject()` creates/updates the project, writes a
spec generated from `dataflowDatasetsRef.current`, and calls `syncDatasetsFromSavedSpec()`
(`useWorkflowOperations.ts:574-633`, `:562-572`). Hence "appears only after the disk
icon" and "lost on reload before save."

**Asymmetry that confirms the fix shape.** The manual catalog **Install** button already
does the right thing: `onInstall` calls `ensureProjectId()` (which runs
`saveCurrentProject()` to create the project) **before** installing
(`useDatasetCatalogDrawer.ts:148-186`). The auto-install-on-execution path does **not**
ensure a project first. The fix is to bring the execution path to parity.

**Expected behavior.** Installing a dataset (by either path) must immediately and durably
persist the project and reflect the **final persisted project state** in the UI, with no
manual save required and full survival across reload.

---

## 2. Scope

**In scope**

- Frontend execution result handling that triggers auto-install sync:
  `utk_curio/frontend/urban-workflows/src/components/editing/CodeEditor.tsx`
  (`processExecutionResult`, L151-200; install hook L180-182).
- Shared install/sync helpers:
  `services/datasetCatalog/datasetCatalogApi.ts` (`applyInstalledDatasetToProject`,
  `notifyDatasetCatalogRefresh`, `DATASET_CATALOG_REFRESH_EVENT`).
- Project create/save + dataset-state sync:
  `src/hook/useWorkflowOperations.ts` (`saveCurrentProject`, `saveAsNewProject`,
  `syncDatasetsFromSavedSpec`, `dataflowDatasets`/`dataflowDatasetsRef`).
- The "ensure a project exists" primitive currently private to the drawer:
  `src/components/datasets/catalog/useDatasetCatalogDrawer.ts` (`ensureProjectId`,
  L148-160) — to be promoted to a shared, reusable operation.
- Backend persistence semantics that the frontend depends on:
  `utk_curio/backend/app/datasets/auto_install.py`,
  `utk_curio/backend/app/projects/storage.py` (`merge_dataflow_dataset_ref`),
  and the execution routes in `utk_curio/backend/app/api/routes.py`.

**Out of scope (do not change unless required by the behavior above)**

- The catalog listing/dedup logic and the user-store install fallback
  (`services/catalog_listing.py`, `catalog_dedup.py`) — keep as a display safety net.
- The manual catalog **Install** / **Uninstall** / **Publish** flows in
  `useDatasetCatalogDrawer.ts` beyond extracting the shared `ensureProjectId` primitive;
  their behavior must be preserved.
- `WidgetsEditor.tsx` (L150) and `autkGrammarBehavior.tsx` (L820, L1007) interpret-code
  call sites: they do **not** opt into auto-install (no `saveOutputDataset`/`dataflowId`/
  `nodeName` passed), so they are non-producing paths. Confirm they remain non-producing;
  no behavior change intended.

**Related code paths to check**

- `ProjectLoader.tsx` (load on `/dataflow/:id`, applies spec via `loadParsedTrill`,
  hydrates `dataflowDatasets`) — verify reload shows the persisted dataset.
- Auto-save effect (`useWorkflowOperations.ts:636-646`) — must not double-fire or fight
  the new immediate save.

---

## 3. Recommended Implementation Approach

Mirror the proven manual-install pattern and centralize it, so **both** install entry
points (catalog drawer button and node-execution auto-install) guarantee a persisted
project and a UI driven by persisted state.

1. **Promote `ensureProjectId` to a shared operation.** Move the
   `ensureProjectId` logic out of `useDatasetCatalogDrawer.ts` into the central
   workflow operations (`useWorkflowOperations.ts`) / `FlowProvider` context, so it is
   callable from `CodeEditor`'s execution handler and anywhere else. It must:
   create the project via `saveCurrentProject()` when `projectId` is null, return the
   resolved id (or null on failure), and surface a toast on failure. Keep the drawer's
   `onInstall` calling the same shared primitive (no behavioral change there).

2. **Make the execution auto-install path "ensure-then-persist."** In
   `CodeEditor.processExecutionResult`, when `result.installedDataset` is present **and**
   the node is a saving producer (`resolveSaveOutputDataset(...)` true):
   - If there is **no `projectId`**, call the shared `ensureProjectId()` first. This
     creates the project and, critically, persists the dataset ref because
     `saveCurrentProject()` generates the spec from the dataset ref array (see §4 on the
     ref-vs-state race). After creation, the row is durable and survives reload.
   - If a `projectId` already exists, the backend already merged the ref to disk
     (reload-durable); still reconcile the UI to persisted state (step 3).

3. **Drive the UI from persisted state, not an optimistic guess.** After install/create,
   prefer the canonical refs the backend returns over a locally-fabricated ref:
   - `saveCurrentProject()` already returns `detail.spec`; route it through
     `syncDatasetsFromSavedSpec(detail.spec)` (it already does) so `dataflowDatasets`
     equals the persisted `dataflow.datasets`.
   - Keep `applyInstalledDatasetToProject` as the **optimistic** in-session update for
     the already-saved-project case, but follow it with a reconcile to persisted refs
     (re-sync from the save/merge response or a lightweight project refetch) so a partial
     payload can never leave the UI ahead of disk.
   - Keep `notifyDatasetCatalogRefresh()` as the single fan-out signal that makes the
     palette/drawer refetch `/api/datasets/catalog?dataflowId=<id>` (now that `<id>`
     exists, `installed.list_items` returns the persisted ref → `installed === true`).

4. **Keep the backend as the source of truth.** No new persistence mechanism: continue to
   use `merge_dataflow_dataset_ref` for existing projects and `saveCurrentProject` →
   `projectsApi.create` for new ones. Optionally make the execution route resilient by
   returning the canonical ref/spec slice it persisted, so the frontend reconciles to an
   authoritative value rather than reconstructing one.

This preserves the existing architecture (single save funnel, single refresh event,
backend-owned spec), centralizes the "ensure project" rule instead of duplicating it, and
removes reliance on manual save.

---

## 4. Data and State Handling

- **Source of truth:** the persisted project spec `dataflow.datasets` (refs) on disk,
  surfaced to the frontend through `loadProject`/`saveCurrentProject` responses and the
  `/api/datasets/catalog` listing. In-memory `dataflowDatasets` is a derived cache that
  must be reconciled to the persisted value after any install.
- **Derived values:** `installed === true` in the catalog is derived per `dataflowId`
  from persisted refs (`catalog_listing.py:55-94`), with a user-store fallback for
  freshly computed files (`:96-104`). The palette/drawer filter on this flag
  (`useDatasetCatalogDrawer.ts:111`, `DatasetsPaletteDropdown.tsx`).
- **State updates after the action:** install → (ensure project, creating it if needed)
  → ref persisted to spec → `syncDatasetsFromSavedSpec(detail.spec)` sets
  `dataflowDatasets` from persisted refs → `notifyDatasetCatalogRefresh()` → subscribers
  refetch with a busted cache.
- **Race to eliminate — stale `dataflowDatasetsRef`.** `applyInstalledDatasetToProject`
  calls `setDataflowDatasets` (async); `dataflowDatasetsRef.current` is updated *during
  render*, not synchronously. If `saveCurrentProject()` is invoked in the same tick it may
  read a `dataflowDatasetsRef` that does **not** yet include the new ref, persisting a
  spec without it. Mitigations (pick one, prefer the first):
  1. Persist via the backend ref itself — pass the just-installed ref explicitly into the
     save (or let the create call include it deterministically), rather than depending on
     the ref array having flushed.
  2. Compute the next dataset array synchronously and hand it to `saveCurrentProject`
     instead of reading the lagging ref.
  Then always reconcile from the returned persisted spec.
- **Avoid flicker / stale UI:** update from persisted refs (not a fabricated optimistic
  ref) so the row never shows attributes that differ from disk; the existing
  `bustCache: true` reload prevents serving the pre-install cached listing.
- **No duplicate state:** continue routing all dataset-state changes through
  `dataflowDatasets` + the refresh event; do not introduce a parallel store.

---

## 5. UI and UX Requirements

- Immediately after a producing node finishes, the installed dataset appears in the
  dataset **palette** and **catalog drawer** (Installed/Computed tabs) with
  `installed === true`, with **no disk-icon click required**.
- The save-status indicator (`UpMenu.tsx:612-633`) should truthfully reflect that a save
  occurred (e.g. transitions to "Saved at HH:MM:SS"), since a project create/save now
  happens as part of install. A brand-new dataflow should transition from
  `/dataflow/new` to its canonical `/dataflow/:id` URL (same navigation `handleSave`
  performs after first save — reuse that behavior, see `UpMenu.tsx:165-184`).
- No visible jank: the palette refetch is incremental; avoid clearing the list to empty
  before repopulating (rely on the cached list + busted refetch, not a hard reset).
- Counts (Installed/Computed tab badges) update consistently from the same listing.
- Accessibility: the install toast (`showToast`) already announces success/failure; keep
  parity for the execution path. Ensure any auto-navigation does not steal focus
  unexpectedly.

---

## 6. Edge Cases

- **Brand-new unsaved dataflow** (primary bug): node produces a dataset → project must be
  auto-created and the ref persisted; reload shows it.
- **Concurrent producing nodes** before any save: multiple `installedDataset` payloads in
  quick succession must not each create a separate project; `ensureProjectId` must be
  idempotent/guarded so the first call creates and subsequent calls reuse the id.
- **Ref-vs-state race** (§4): the just-installed ref must end up in the persisted spec
  even though `setDataflowDatasets` hasn't flushed to the ref yet.
- **Save failure** during ensure-project (guest user `blockGuestSaves`, shared/read-only
  `viewerMode === "shared"`): surface the existing toast, do not lose the in-memory ref,
  do not leave the UI claiming "installed" durably.
- **Existing saved project:** backend already merged the ref; avoid a redundant full
  re-save on every execution if it is unnecessary (the merge already made it durable) —
  but still reconcile the UI to persisted state.
- **Re-execution / reinstall:** a node re-run that produces a new output filename should
  upsert (not duplicate) the ref (`merge_dataflow_dataset_ref` upserts by `datasetId`/
  `producerNodeId`; `needsReinstall` handling at `catalog_listing.py:87-94`).
- **Non-producing executions** (`saveOutputDataset` false, `installedDataset` null): no
  project create, no save, no refresh — must remain a pure no-op.
- **Backend merge silently failing** (spec missing, lock contention): the
  `try/except` in `auto_install.py:86-87` swallows errors; the frontend must not assume
  persistence succeeded — reconcile from an authoritative response or refetch.
- **Auto-save interplay:** the 30s auto-save (`useWorkflowOperations.ts:636-646`) must not
  race or double-write with the new immediate save.
- **Shared/read-only view:** never auto-create or save; installation UI should already be
  gated, but verify the execution path respects `viewerMode`.

---

## 7. Testing Strategy

**Frontend unit / hook tests**

- `applyInstalledDatasetToProject`: upserts by id, fires refresh, ignores null/partial
  payloads (existing behavior — add coverage if missing).
- Shared `ensureProjectId`: creates a project when `projectId` is null; returns existing
  id when set; idempotent under concurrent calls; toasts and returns null on save failure;
  refuses in shared/guest modes.
- `syncDatasetsFromSavedSpec`: sets `dataflowDatasets` from `spec.dataflow.datasets` and
  fires refresh.

**Component / integration tests**

- `CodeEditor.processExecutionResult`: given an `installedDataset` and no `projectId`,
  it ensures a project (create called once), persists the ref, and the UI reflects the
  persisted refs; given an existing `projectId`, it reconciles to persisted state without
  a duplicate create.
- Race test: install then immediate save does not drop the new ref from the persisted
  spec.
- Palette/drawer: after a refresh event with a real `dataflowId`, the row shows
  `installed === true`.

**Backend tests**

- `merge_dataflow_dataset_ref`: no-op (`False`) when spec is missing; upsert vs append by
  `datasetId`/`producerNodeId`; lock-serialized correctness (extend existing tests).
- Execution route returns `installedDataset` payload shape; `dataflowId` omitted vs
  present behaves correctly.

**Regression / reload tests**

- End-to-end: new dataflow → run producing node → no manual save → reload → dataset still
  present and `installed`.
- Manual catalog Install path remains unchanged (guard against regressions from extracting
  `ensureProjectId`).

---

## 8. Acceptance Criteria

1. Running a node that saves an output on a **brand-new** dataflow auto-creates the
   project and the dataset appears in the palette/drawer **immediately**, with no disk-icon
   click.
2. The URL transitions from `/dataflow/new` to `/dataflow/:id` on that first auto-create,
   and the save-status indicator reflects a real save.
3. Reloading the page after such an install **preserves and displays** the installed
   dataset (`installed === true`).
4. On an already-saved project, the same install is reflected immediately and remains
   durable across reload, without requiring a manual save.
5. The displayed dataset attributes match the **persisted** spec refs (no optimistic
   values that differ from disk).
6. The manual catalog **Install** flow behaves exactly as before.
7. Non-producing executions cause no project create, save, or refresh.
8. No duplicate projects or duplicate dataset refs under rapid/concurrent producing runs.
9. Shared/read-only and guest modes never auto-create/save and surface the existing
   error toast.

---

## 9. Recommended Commit Breakdown

- **Commit 1 — shared primitive + tests.** Extract `ensureProjectId` into a centralized
  workflow operation (FlowProvider/`useWorkflowOperations`), with unit tests; refactor the
  drawer's `onInstall` to consume it (no behavior change).
- **Commit 2 — execution path parity.** Wire `CodeEditor.processExecutionResult` to
  ensure-then-persist on auto-install, reconciling `dataflowDatasets` from persisted refs;
  reuse the first-save URL navigation.
- **Commit 3 — race + reconcile hardening.** Eliminate the `dataflowDatasetsRef` flush
  race (persist via explicit ref / synchronous array) and reconcile UI strictly from
  persisted state; optional backend response enrichment for an authoritative ref.
- **Commit 4 — regression coverage.** Reload-survival e2e/integration tests, concurrency
  test, and backend `merge_dataflow_dataset_ref` edge tests; cleanup.

---

## 10. Engineering Quality Checklist

- [ ] "Ensure project exists" logic centralized (no duplication between drawer and
      execution paths).
- [ ] UI reflects persisted state; no optimistic value can diverge from disk.
- [ ] Single dataset-state channel (`dataflowDatasets` + `DATASET_CATALOG_REFRESH_EVENT`);
      no parallel store introduced.
- [ ] `ensureProjectId` idempotent and concurrency-safe; no duplicate project creation.
- [ ] Ref-vs-state flush race eliminated and covered by a test.
- [ ] Shared/guest/read-only modes respected; failures toast and degrade gracefully.
- [ ] No redundant full re-save on every execution for already-saved projects.
- [ ] Auto-save effect does not race the new immediate save.
- [ ] Reload survival verified for both new and existing projects.
- [ ] Manual Install/Uninstall/Publish flows unaffected.
- [ ] No unnecessary re-renders, list flicker, or perceived full reloads.