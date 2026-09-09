# Implementation Memo: Save computed node outputs to the account-level Data Catalog by default (no auto-install, no auto-publish, lineage preserved)

**Status:** IMPLEMENTED (unstaged working-tree edits; decisions O1–O3 resolved, see end). Backend 496 passed / frontend 404 passed / tsc clean. · **Branch:** `datacatalog` · **Author:** Karla

> **Implementation note (as-built):** two refinements vs. the memo. (1) The
> per-project manifest-output persistence gate (`storage._durable_source_for`)
> now resolves the deterministic account-store dir directly, so a generated
> output stays durable with no project ref. (2) The dataflow-scoped catalog
> surfaces this dataflow's own account-store computed datasets
> (`UserDatasetRepository.list_dataflow_computed_items`) so they appear in the
> open project's drawer as available-not-installed right after execution. The
> obsolete `_preserve_persisted_computed_refs` was removed (it re-added
> uninstalled refs once the account dir was retained). Migration entrypoint:
> `datasets/application/migrations.py` (`ensure_computed_ids_migrated`, memoized
> per process, run from the account-level listing).
**Area (backend):** `datasets/application/auto_install.py`, `projects/services.py` (`_auto_install_computed_outputs`, `_preserve_persisted_computed_refs`), `datasets/repositories/user_store.py`, `datasets/application/listing.py`, `datasets/install/installer.py` + `install/bundle.py` (manifest write), `datasets/domain/manifest.py`, `datasets/application/mutations.py` (`uninstall_dataset`, `install_dataset`, `publish_dataset`), `datasets/domain/computed.py`
**Area (frontend):** `hook/useWorkflowOperations.ts` (`buildOutputRefs`), `utils/flowOutputRef.ts`, `api/projectsApi.ts` (`OutputRef`), `providers/FlowProvider.tsx` (`scheduleInstallSyncRef`), `components/datasets/catalog/useDatasetCatalogDrawer.ts`, `services/datasetCatalog/datasetCatalogApi.ts`
**Related memos:** [`dataset-import-register-decouple.md`](./dataset-import-register-decouple.md) (same decoupling pattern for imports — Issue 2), [`computed-dataset-execution-persistence.md`](./computed-dataset-execution-persistence.md) (execution-time persistence), [`computed-dataset-title-reinstall.md`](./computed-dataset-title-reinstall.md), [`dataset-details-lineage-single-hop.md`](./dataset-details-lineage-single-hop.md), [`dataset-timestamps-and-uninstall-cleanup.md`](./dataset-timestamps-and-uninstall-cleanup.md)

---

## 1. Problem Statement

**Current behavior.** When a workflow node produces an output, Curio persists it in **two** places at once, automatically:

1. **Account-level user store** — `.curio/users/<user_key>/datasets/computed.<sanitizedNodeId>@1/` (`manifest.json` + `data/`). Written by `install_node_output` (`datasets/install/bundle.py:299` → `install/installer.py:144` `install_computed_file_for_node`). This is the correct, desired persistence.
2. **Project-level ref (auto-install into the palette)** — a lean entry appended to `spec.dataflow.datasets[]` with `{datasetId, dirName, origin:"computed", producerNodeId, consumerNodeIds}`. Written automatically by:
   - `projects/services.py::_auto_install_computed_outputs` at save time (`services.py:233-258`, called from `services.py:487` create / `:537` update), and
   - `datasets/application/auto_install.py::auto_install_node_output` at execution time via `project_storage.merge_dataflow_dataset_ref` (`auto_install.py:47-172`), triggered from the frontend by `FlowProvider.tsx` `scheduleInstallSyncRef` → `persistDataflowForInstall()` → save.

The project ref is what makes a computed dataset show up as **installed** in the current project (left DATA palette + counted against the dataflow). So today, *generating* an output silently *installs* it into the project you happen to have open.

**Why this is wrong for the new model.** A computed dataset is an account-level asset that belongs to the user's Data Catalog. Attaching it to the open project on generation:
- pollutes the project palette with every intermediate output whether or not the user wants it there,
- conflates "this dataset exists in my catalog" with "this dataset is installed in this project,"
- and couples an account-level artifact's lifecycle to one dataflow (e.g. uninstall/cleanup deletes the account copy — see §6).

This is the same coupling already removed for **imports** in [`dataset-import-register-decouple.md`](./dataset-import-register-decouple.md) (Issue 2), where `import_dataset`'s `if dataflow_id: install_dataset(...)` was cut and an account-level listing source was added so imports stay visible without a project ref.

**Expected behavior.**
- Generating a computed dataset **saves it to the user's account-level Data Catalog** (store write — already happens; keep it).
- It is **not** auto-published to the global/hub catalog. (Already true — `publish_dataset` is explicit-only. Assert and guard against regression.)
- It is **not** auto-installed into the current project palette. (New — remove the automatic project-ref write.)
- Its **lineage metadata is preserved**, linking the dataset to (a) the producing workflow/dataflow, (b) the source node that generated it, and (c) the upstream input datasets/nodes used to produce it.
- The dataset is browsable in the Data Catalog drawer as an **available, not-installed** item and can be installed into a project **later, by explicit user action** (drawer `Install`). Global publish is likewise **explicit-only** (drawer `Publish`).

**Why it matters.** Correctness (account assets shouldn't be silently project-scoped), consistency (matches the import decoupling already shipped and the palette-vs-drawer product model where the palette lists only *installed* items and install/publish live in the drawer), and lineage integrity (the connection to producer node + workflow + upstream inputs must survive the decoupling and any later reinstall/publish).

---

## 2. Scope

**In scope**

- **Stop the automatic project-ref write** in both persistence paths while keeping the account-store write:
  - `services.py::_auto_install_computed_outputs` — keep the `install_node_output` store write (`:198-204`); remove the `dataflow.datasets[]` append/update (`:233-258`).
  - `auto_install.py::auto_install_node_output` — keep the store write; remove the `merge_dataflow_dataset_ref` project-ref merge.
- **Surface account-level computed datasets in the Data Catalog** so they remain visible without a project ref: add a computed source to the **account-level (`include_hub` / no-`dataflow_id`) branch** of `CatalogListing.list_catalog` (`listing.py:90-114`). Today `UserDatasetRepository` deliberately excludes `computed.*` dirs (`user_store.py:9-14,54`); this is the enabler that prevents computed datasets from vanishing after decoupling (exact analog of the import gotcha).
- **Namespace the account-level computed identity by producing dataflow (decision O1).** Change the computed id/dir scheme from `computed.<sanitizedNodeId>` (account-global, keyed on node id only) to `computed.<sanitizedDataflowId>.<sanitizedNodeId>`, so two dataflows that reuse the same node id produce **distinct** account assets instead of overwriting one folder. Affects: `install/installer.py::install_computed_file_for_node` / `install/bundle.py::install_computed_bundle_for_node` (id/dir minting — must accept `dataflow_id`), `domain/computed.py` indexer (must build the same namespaced id so dedup holds), `mutations.py::_producer_segment_from_computed_id` + `export.py::_producer_node_id_for` (parse the node id back out of the two-segment id), and `storage.py::DATASET_DIR_RE` / `_sanitize_node_id_segment` (allow the extra dotted segment). Includes a **migration** for existing `computed.<nodeId>@1` dirs (see §3F).
- **Add an explicit "Delete from catalog" action (decision O2)** for account-level computed datasets, distinct from project uninstall: a new backend delete (account-store `rmtree` + cascade cleanup) reached from a drawer `Delete` control. Backend: new `CatalogMutations.delete_dataset(id)` + route `DELETE /api/datasets/{id}`; frontend: `datasetCatalogApi.deleteDataset` + drawer handler.
- **Persist lineage into the computed manifest** at store-write time (`installer.py:196-216` / `manifest.py` `DatasetManifest`): `producerNodeId`, `producerNodeType`, `producerDataflowId`, `producerDataflowName`, and `upstreamInputs` (upstream input dataset ids and upstream producer node ids). Per **decision O3**, `upstreamInputs` is **derived on the backend** from the saved spec (edges + `spec.nodeProvenance`/`spec.dataflowProvenance`, already attached at `useWorkflowOperations.ts:635-636`) — the single source of truth, no frontend contract change for upstream. Only the producer label/type is threaded from the frontend (`resolveNodeDisplayLabel`, already available on `OutputRef.node_name`); `producerDataflowId`/`producerDataflowName` come from the save context.
- **`_preserve_persisted_computed_refs`** (`services.py:268-334`) — update semantics + docstring: it must preserve only refs the user **explicitly** installed, not re-synthesize refs from the mere existence of an account-store dir.
- **`uninstall_dataset`** (`mutations.py:659`+, per [`dataset-timestamps-and-uninstall-cleanup.md`](./dataset-timestamps-and-uninstall-cleanup.md)) — for computed datasets, uninstall-from-project removes the **ref only** and must **not** delete the account-store dir (it's now a catalog asset). Deleting from the catalog is the separate explicit Delete action above.
- **Explicit install path** (`mutations.py::install_dataset`, `origin=="computed"`, `:428-534`) — verify it still promotes/attaches correctly and carries the new lineage. Drawer trigger `useDatasetCatalogDrawer.ts::onInstall` → `POST /api/dataflows/{id}/datasets/install`.
- **Explicit publish path** (`mutations.py::publish_dataset`) — verify unchanged and lineage-preserving. Drawer trigger `onPublish` → `POST /api/datasets/publish`.
- **Frontend:** `OutputRef` / `FlowOutputRef` gain only an optional `producer_node_type` (label already flows via `node_name`); upstream lineage is backend-derived (O3), so no upstream fields on the ref. Confirm the auto-save trigger (`scheduleInstallSyncRef`/`persistDataflowForInstall`) still fires so outputs reach the account store, but now produces **no** palette entry. Drawer install-state marking must show account-level computed items as *not installed* in a project that didn't install them, and computed cards gain a **Delete** control (O2) alongside `Install`/`Publish`.
- Tests (see §7).

**Out of scope / must not regress**

- The **account-store write itself** and the "Save output dataset" toggle semantics (`CURIO_DEFAULT_SAVE_NODE_OUTPUT`, `saveOutputDataset`, `buildSaveableLiveOutputs` at `utils/saveOutputDataset.ts:57`) — a node with the toggle off still contributes nothing.
- **Imports** — already decoupled; do not touch that path.
- **OSM PBF grouping** and the bundle install path — behavior preserved; if bundles are treated as computed, they follow the same rule.
- **Global publish being explicit-only** — must stay explicit; this memo must not introduce any auto-publish.
- Sink/viz pruning (`_prune_sink_node_dataset_refs`) and the shared-intermediate-artifact dedup guard (`auto_install.py:30-33`).
- The per-project **computed indexer** (`domain/computed.py`) that surfaces live outputs in the *dataflow-scoped* drawer view — keep it (it powers "install this output"); this memo adds the *account-level* view, it does not remove the dataflow-scoped one.

---

## 3. Recommended Implementation Approach

Follow the import-decouple blueprint: **add the account-level listing source first, then cut the auto-install ref**, so computed datasets never disappear between commits.

**A. Add an account-level computed catalog source (enabler, do first).**
Surface `computed.*` user-store dirs as standalone catalog items in the `include_hub`/no-`dataflow_id` branch only. Options, in order of preference:
- Extend `UserDatasetRepository.list_items()` to also emit `computed.*` dirs (origin `"computed"`), OR add a sibling `ComputedUserDatasetRepository`. Keep the dataflow-scoped branch (`installed` + `computed` indexer) unchanged so the module's original concern — "don't show a node's output as a standalone item in a dataflow that never produced it" (`user_store.py:11-14`) — still holds: account-level items appear only in the account-level (no-dataflow) view. `dedupe_items` (`listing.py:161`) merges by `id` where the two views overlap.
- Reuse `item_from_manifest` and the new manifest lineage fields so the account-level item carries producer/workflow/upstream metadata directly (no cross-project scan needed at list time).
- Emit the namespaced id `computed.<sanitizedDataflowId>.<sanitizedNodeId>` (A′ below) so account items from different dataflows stay distinct.

**A′. Namespace the computed identity by dataflow (O1).**
Thread `dataflow_id` into the store write so the id/dir becomes `computed.<sanitizedDataflowId>.<sanitizedNodeId>` (`@1`). The save path (`_auto_install_computed_outputs`) already holds the spec (dataflow id available); the execution path (`auto_install_node_output`) already resolves a `dataflow_id` for `merge_dataflow_dataset_ref`, so both callers can supply it. Update the id↔node-id parsers (`_producer_segment_from_computed_id`, `_producer_node_id_for`) to split on the **last** dotted segment for the node id and treat the middle segment as the dataflow, and widen `DATASET_DIR_RE`/`_sanitize_node_id_segment` to permit the extra segment. The computed indexer (`domain/computed.py`) must mint the identical namespaced id from its dataflow context so account-level and per-dataflow rows still dedupe via `dedupe_items`.

**B. Remove the automatic project-ref writes (keep store writes).**
- `_auto_install_computed_outputs`: keep the loop's `install_node_output` call and failure recording; delete the ref append/update block and the `changed`/spec-rewrite that adds `dataflow.datasets` entries. It should still return the spec (unmodified re: datasets) and still record per-output failures so silent skips remain visible (preserve the [`computed-dataset-execution-persistence.md`](./computed-dataset-execution-persistence.md) diagnostics).
- `auto_install_node_output`: keep the store write + structured diagnostic result; drop `merge_dataflow_dataset_ref`.

**C. Persist lineage in the manifest at write time (centralized).**
Add lineage fields to `DatasetManifest` / `build_manifest_dict` and populate them in `install_computed_file_for_node` / `install_computed_bundle_for_node`. Source values from a single resolver so execution and save agree (mirrors Approach D in the execution-persistence memo):
- `producerNodeId` — already implicit in the id; store it explicitly too.
- `producerNodeType` — from the `OutputRef`/spec node (`nodeType`/`packageTemplateLabel`).
- `producerDataflowId` / `producerDataflowName` — from the save context (the project being saved).
- `upstreamInputs` — upstream producer node ids and input dataset ids feeding this node, **derived on the backend** from `spec` edges + `spec.nodeProvenance` (O3). Add one backend helper `resolve_upstream_inputs(spec, node_id)` used by both the execution and save writes.
This makes lineage **self-contained** on the account-level asset, so it survives decoupling, reinstall, and publish without depending on read-time cross-project resolution (`resolve_dataset_producer`, `listing.py:388`) — that resolver stays as a fallback/backfill for legacy manifests.

**D. Keep explicit install/publish as the only project/global entry points.**
No new endpoints. `install_dataset` (computed branch) and `publish_dataset` already exist and are the sole explicit paths, reached from the drawer (`onInstall`/`onPublish`). Verify both read and carry the new lineage fields onto the resulting ref/hub manifest.

**E. Fix uninstall to spare the account copy.**
Computed uninstall-from-project removes the ref (`replace_refs`) and must skip the account-store rmtree that [`dataset-timestamps-and-uninstall-cleanup.md`](./dataset-timestamps-and-uninstall-cleanup.md) introduced for computed dirs. Deleting the account-level asset is the explicit Delete action (G).

**F. Migration for the renamed computed identity (O1).**
Existing account-store dirs use the old `computed.<nodeId>@1` scheme. Provide an idempotent one-time migration (run on startup/first-list, or a small script) that, for each old computed dir, resolves the producing dataflow — via the newly persisted `producerDataflowId` if present, else `resolve_dataset_producer` scanning the user's specs — and renames the dir to `computed.<dataflowId>.<nodeId>@1`, rewriting the manifest `id`/`dir_name` and any matching `spec.dataflow.datasets[].datasetId`/`dirName` refs in lockstep so installed projects don't break. A dir whose dataflow can't be resolved keeps the legacy id and is still read (parsers accept both one- and two-segment forms). Note: the repo-root `datasets/computed.*@1` dirs seen in `git status` are **hub/`catalog_root()`** entries, not user-store dirs — the migration targets `.curio/users/<user_key>/datasets/` only; hub ids are remapped by publish and left as-is here.

**G. Explicit "Delete from catalog" (O2).**
Add `CatalogMutations.delete_dataset(id)` + route `DELETE /api/datasets/{id}`. Semantics: if published, `unpublish_dataset` first (remove hub dir); remove every project ref that points at the dataset (`owner.dataset_usage(id)` → `replace_refs` per dataflow); then `rmtree` the account-store dir (manifest + `data/` + `.meta.json` sidecar, reusing the cleanup from the uninstall-cleanup memo). Guard with a client `window.confirm` that names how many projects still reference it. Frontend: `datasetCatalogApi.deleteDataset(id)` and a drawer `Delete` handler that refreshes (`catalog.reload({bustCache:true})` + `notifyDatasetCatalogRefresh()`), mirroring the existing uninstall/unpublish handlers.

---

## 4. Data and State Handling

- **Source of truth for existence:** the account-level user store (`.curio/users/<user_key>/datasets/computed.<dataflowId>.<nodeId>@1/`). Written on generation (execution) and reaffirmed on save. Independent of any project; distinct per producing dataflow (O1).
- **Source of truth for "installed in this project":** `spec.dataflow.datasets[]` refs — now written **only** by explicit `install_dataset`, never by generation.
- **Source of truth for lineage:** the computed manifest's new lineage fields (primary); `resolve_dataset_producer` cross-project scan (fallback for legacy rows).
- **Derived values:** installed-state marking in `list_catalog` (`listing.py:116-159`) — an account-level computed item shows `installed:false` unless the *current* dataflow has a ref matching its `producerNodeId`/id. `needsReinstall` (filename-diff) semantics preserved.
- **State after actions:**
  - *Generate/run:* dataset appears in the account Data Catalog; project palette unchanged.
  - *Explicit Install:* ref added; item flips to `installed:true` in that dataflow; appears in the DATA palette; `catalog.reload({bustCache:true})` + `notifyDatasetCatalogRefresh()` already fan out (`useDatasetCatalogDrawer.ts`).
  - *Explicit Uninstall:* ref removed; item reverts to available; **account copy stays**.
  - *Explicit Delete (O2):* unpublish if published → remove all project refs → rmtree account dir; item disappears from every surface.
  - *Explicit Publish/Unpublish:* hub manifest written/removed; `publishedToHub` toggled on the ref; lineage preserved on the hub manifest.
- **No stale/flicker/dupes:** the account-level id (`computed.<dataflowId>.<nodeId>`) equals the per-project computed id minted by the indexer, so `dedupe_items` merges cleanly; re-execution replaces the same dir (stable id) and must **rewrite** the lineage block each run so it never goes stale; reconciliation on save (`syncDatasetsFromSavedSpec`) reads back only the explicit refs.

---

## 5. UI and UX Requirements

- After running a workflow, computed outputs appear in the **Data Catalog drawer** (account-level browse) as **available, not-installed** items with an `Install` action — they do **not** appear in the left DATA palette until installed (consistent with [[curio-palette-vs-drawer-publish]]: palette = installed only; install/publish live in the drawer).
- The dataset card shows lineage: producing node label (via `resolveNodeDisplayLabel` / `resolveComputedInstallTitle`), the producing workflow name, and upstream inputs (detail panel lineage rows — align with `dataset-details-lineage-single-hop.md`).
- Publish stays a single explicit toggle in the drawer (`CatalogPublishPill`, `Publish` → `Published`); no scope tiers, no auto-publish.
- Account-level computed cards expose an explicit **Delete** control (O2), visually distinct from `Uninstall` (project-scoped) and guarded by a `window.confirm` that states how many projects still reference the dataset. Uninstall wording must make clear it removes the dataset *from this project only*, not from the catalog.
- No visible jank: generation must not cause the palette to flash new rows and then need manual cleanup; the drawer refresh is debounced/cache-busted as today.
- Accessibility: install/publish controls keep existing button semantics and confirm dialogs (uninstall/unpublish already `window.confirm`-guarded).

---

## 6. Edge Cases

- **Account-level node-id collision — resolved by namespacing (O1).** Ids/dirs are now `computed.<dataflowId>.<nodeId>@1`, so two dataflows reusing a node id no longer overwrite one folder. Verify every id producer/parser is updated in lockstep (installer, indexer, `_producer_segment_from_computed_id`, `_producer_node_id_for`, `DATASET_DIR_RE`), or account items will fail to dedupe or resolve their producer.
- **Migration of legacy `computed.<nodeId>@1` dirs (§3F)** must be idempotent, rename the dir + rewrite manifest id/dir_name + all matching project refs atomically, and fall back to the legacy id (still readable) when the dataflow can't be resolved. A half-migrated ref (dir renamed but spec ref not) would orphan an installed dataset — cover with a test.
- **Uninstall must not delete the account asset** (§3E) — otherwise "install later" is impossible after one uninstall.
- **Delete cascade (O2):** deleting a dataset that is installed in N projects must remove all N refs and unpublish from the hub before rmtree; a delete that races an in-flight save must not leave a dangling ref (re-check `dataset_usage` under the same locking as uninstall). Deleting an already-unpublished / not-installed dataset is a plain rmtree.
- **Re-execution / Play All:** same dir replaced; lineage block rewritten with fresh upstream/producer values; `needsReinstall`/filename-diff preserved; existing stale manifests self-correct on next run/save.
- **"Save output dataset" toggle off:** node contributes nothing to the account store (unchanged).
- **Sink/viz nodes** (`vis-vega`/`vis-simple`) and **data-pool passthrough:** excluded from persistence as today; never create an account item.
- **Bundle / tuple outputs & OSM groups:** follow the same rule (store write, no auto-ref); group expansion on explicit install/uninstall unchanged.
- **Legacy manifests without lineage fields:** fall back to `resolve_dataset_producer`; don't crash the listing (best-effort, matching `user_store.py` malformed-dir handling).
- **JSON/dict/list/scalar outputs** (from the execution-persistence work): persist to the account store; no auto-ref; diagnostics for skips still surface.
- **Publish of a not-installed computed dataset:** publishing from the account catalog without a prior project install — confirm `publish_dataset` handles `dataflow_id` absent/optional (it re-points refs when a dataflow is in context; must not require one).
- **Cross-dataflow browse of the hub** (`_prefer_user_store_computed_title`, cross-dataflow title fix) — remains correct since lineage/title now live on the manifest.
- **Concurrent save + run:** save path (`spec_write_lock`) and execution path both only do store writes now; no ref race to the spec from generation.

---

## 7. Testing Strategy

**Backend (pytest, near `tests/test_datasets/`)**
- *Decoupling:* run/save a node output → account-store dir created with lineage fields; `spec.dataflow.datasets` has **no** new computed ref (regression vs. old auto-install).
- *Account listing:* `list_catalog(include_hub=True)` (no `dataflow_id`) lists the computed item as `installed:false`; a `dataflow_id` that never installed it does **not** list it as installed.
- *Explicit install:* `install_dataset` (computed) adds a ref, flips `installed:true`, preserves lineage on the ref.
- *Explicit uninstall:* removes the ref, **account dir survives**, item still listed account-level.
- *No auto-publish:* after run/save/install, no hub manifest exists until `publish_dataset` is called; `publish_dataset` writes hub manifest with lineage; `unpublish_dataset` reverses.
- *Lineage:* manifest carries `producerNodeId/producerNodeType/producerDataflowId/producerDataflowName/upstreamInputs`; upstream ids match the spec edges/provenance.
- *`_preserve_persisted_computed_refs`:* preserves an explicitly-installed ref across save; does **not** synthesize a ref for an account-store dir that was never installed.
- *Namespacing (O1):* two dataflows with the same node id produce two distinct `computed.<dataflowId>.<nodeId>@1` dirs and two distinct account items; `_producer_node_id_for` round-trips the node id from the two-segment id; the indexer id matches the store id (dedup holds).
- *Migration (§3F):* a legacy `computed.<nodeId>@1` dir + an installed ref → migrated to the namespaced id with manifest and ref rewritten together; running the migration twice is a no-op; an unresolvable dataflow leaves the legacy id readable.
- *Delete (O2):* `delete_dataset` on an installed+published dataset unpublishes, removes every project ref (assert via `dataset_usage`), and rmtree's the account dir; deleting a not-installed dataset just rmtree's; item no longer listed anywhere afterward.
- *Regression:* Autark what-if dataflows (dict/list nodes) still persist to the account store and still surface diagnostics; imports untouched.

**Frontend (vitest)**
- `buildOutputRefs` populates the new lineage fields on `OutputRef`.
- Post-generation: drawer shows the computed item as not-installed; DATA palette shows **no** new row until `onInstall`.
- `onInstall`/`onUninstall`/`onPublish`/`onDelete` call the right endpoints and refresh; install-state marking correct; Delete is confirm-guarded and names project usage count.
- `datasetCatalogApi` shape tests for the lineage fields + `deleteDataset`; `DatasetDetailPanel` renders producer/workflow/upstream rows.

**Integration/regression**
- End-to-end: run a workflow → dataset in account catalog only → explicit install → appears in project → uninstall → gone from project, still in catalog → explicit publish → in hub.

---

## 8. Acceptance Criteria

1. Generating a computed dataset writes it to the **account-level Data Catalog** and it is browsable there without any project reference.
2. Generation adds **no** entry to `spec.dataflow.datasets[]` and **no** row to the project DATA palette.
3. No global/hub publish happens automatically; the hub manifest exists only after an explicit `Publish`.
4. The computed manifest carries lineage linking the dataset to its **producer node**, its **producing workflow/dataflow**, and its **upstream input datasets/nodes**; this survives reinstall and publish.
5. A user can **explicitly install** the dataset into a project later (drawer `Install`), which is the only path that creates a project ref, and **explicitly publish** it (drawer `Publish`), the only path to the hub.
6. Uninstalling a computed dataset from a project removes the project ref but **retains** the account-level asset, so it can be reinstalled later.
7. Two dataflows reusing the same node id yield **two distinct** account-level computed datasets (`computed.<dataflowId>.<nodeId>`), with correct producer resolution and dedup; existing legacy dirs are migrated without breaking installed refs.
8. An explicit **Delete** action permanently removes the account-level computed dataset, cascading through hub unpublish and all project refs; it is the only path that deletes the account asset.
9. Live outputs still appear (in the drawer) immediately after execution; the "Save output dataset" toggle, sink/viz pruning, dedup guard, and JSON-output persistence all behave as before.
10. Imports, OSM grouping, and existing lineage/title behavior do not regress.

---

## 9. Recommended Commit Breakdown

1. **Namespaced identity (O1) + migration + lineage on the manifest.** Change the computed id/dir scheme to `computed.<dataflowId>.<nodeId>`, thread `dataflow_id` into the installers, update the id parsers + `DATASET_DIR_RE`, add the idempotent migration (§3F), and add the lineage fields (`producer*` + backend-derived `upstreamInputs`) to `DatasetManifest`/`build_manifest_dict` + the `resolve_upstream_inputs` helper. Backend unit tests (id round-trip, migration, manifest). *(Still green with the old ref path intact.)*
2. **Account-level computed listing source (enabler).** Surface namespaced `computed.*` dirs in the account-level branch of `list_catalog` via `item_from_manifest` + manifest lineage; keep the dataflow-scoped branch unchanged; dedup verified. Backend listing tests. *(Now visible via both the ref path and the account source — the safety net before the cut.)*
3. **Cut the automatic project-ref writes.** Remove the ref append in `_auto_install_computed_outputs` and the `merge_dataflow_dataset_ref` in `auto_install_node_output`; update `_preserve_persisted_computed_refs` semantics/docstring. Backend tests asserting no auto-ref while the store write + account listing persist.
4. **Frontend lineage/label threading + palette/drawer behavior.** Add `producer_node_type` to `OutputRef`/`FlowOutputRef` + `buildOutputRefs`; confirm the auto-save trigger still stores without creating a palette row; drawer install-state marking + detail-panel lineage rows. Frontend tests.
5. **Uninstall spares the account copy + explicit Delete action (O2) + install/publish verification.** Adjust computed uninstall cleanup; add `delete_dataset` + `DELETE /api/datasets/{id}` + `datasetCatalogApi.deleteDataset` + drawer Delete handler; verify `install_dataset`/`publish_dataset` carry lineage. Lifecycle/regression tests + docstring/comment cleanup.

---

## 10. Engineering Quality Checklist

- [ ] Account-level computed source added **before** the auto-ref cut (no vanish window between commits).
- [ ] One shared lineage resolver feeds both execution and save paths (no divergence).
- [ ] Lineage (producer node, workflow, upstream inputs) is self-contained on the manifest; cross-project resolver is fallback only.
- [ ] Generation performs **only** the store write; no `dataflow.datasets` mutation, no hub write.
- [ ] Explicit install is the sole project-ref creator; explicit publish is the sole hub writer.
- [ ] Uninstall-from-project never deletes the account-level asset; explicit Delete is the only path that does (O2).
- [ ] `_preserve_persisted_computed_refs` preserves only explicitly-installed refs.
- [ ] Computed identity namespaced by dataflow (O1); every id producer/parser updated in lockstep; legacy dirs migrated idempotently without breaking installed refs.
- [ ] Delete cascades: unpublish + remove all refs + rmtree, under the same locking as uninstall.
- [ ] Palette lists installed-only; drawer carries install/publish/delete (matches product model).
- [ ] No palette flicker/auto-populate on generation; drawer refresh debounced/cache-busted.
- [ ] Tests cover decouple, account listing, install/uninstall/delete/publish lifecycle, lineage, preserve-refs, namespacing, migration, JSON outputs, and no-auto-publish.
- [ ] Imports, OSM grouping, sink/viz pruning, dedup guard, and title behavior unregressed.

---

## Resolved decisions

- **O1 — Account-level identity.** Namespace the computed id/dir by producing dataflow: `computed.<sanitizedDataflowId>.<sanitizedNodeId>@1`. Includes the id-parser updates and the idempotent migration for legacy dirs (§2, §3A′/§3F).
- **O2 — Delete from catalog.** Add a distinct explicit Delete action (`delete_dataset` + `DELETE /api/datasets/{id}` + drawer control) that cascades unpublish + ref removal + rmtree; uninstall never deletes the account copy (§3G, §5, §6).
- **O3 — Upstream lineage source.** Derive `upstreamInputs` on the backend from the saved spec (edges + `nodeProvenance`) via one shared helper; only the producer label/type is threaded from the frontend (§3C).

No open questions remain — ready to implement on confirmation.
