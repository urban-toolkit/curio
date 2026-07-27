# Implementation Memo: Decouple dataset import (account-level register) from project install

**Status:** Implemented · **Branch:** `datacatalog` · **Author:** Karla

> **Implemented 2026-07-09** in three commits, as planned in §9:
> - `4ecb274` — account-level source (`UserDatasetRepository`) merged into
>   `list_catalog` (additive).
> - `0a517a5` — register-only import (removed the auto-install block).
> - `6ad9a60` — frontend drawer UX (no `dataflowDatasets` upsert, register-copy
>   toast, no `dataflowId` on import, and the card `isInstalled` now respects the
>   `installed` flag instead of origin).
>
> Discovered during implementation: the drawer's card `isInstalled` was derived
> from origin (`origin !== hub && !== computed`), which treated every imported
> dataset as installed — valid only while imports auto-installed. Fixed to
> `installed === true || origin === "source_node"`. The Installed-tab filter and
> installed count already gated on `installed === true`, so no change there.
> Tests: backend `test_user_store_repository.py` + two route tests in
> `test_dataset_catalog_routes.py`; frontend `useDatasetCatalogDrawer.import.test.ts`.
> Full backend datasets suite (141) and frontend suite (364) green.
**Area:** `utk_curio/backend/app/datasets` (import + listing) and
`utk_curio/frontend/urban-workflows` (catalog drawer import/install UX)
**Scope decision (confirmed):** *Import only.* Node-output / computed
auto-install (already gated by the Save-output toggle) is **out of scope** and
left unchanged.

> **Relationship to Issue 3 (reviewed 2026-07-09).** Issue 3's "OSM PBF import
> adds no dataset" symptom is **not** caused by the import→node linkage. In
> `import_dataset` the format gate rejects `.pbf` *before* the `if dataflow_id:`
> auto-install block ever runs, so decoupling linkage would not make `.pbf`
> import — it is a genuine format-support gap (`.pbf` is an Autark-node input
> via in-browser `db.loadOsm`, not a standalone dataset format; there is no
> server-side OSM parser in the deps). What *is* Issue 2 is the auto-attach of
> **supported** formats (csv/geojson/json/parquet/tif/shp) to the open dataflow
> on import. This memo delivers the user's stated expectation for those formats:
> **imports become standalone catalog items and a node/dataflow linkage is
> created only on explicit install/select.** OSM PBF's end-state (keep the
> redirect vs. implement standalone `.pbf` ingestion) is a separate decision
> pending; it does not block this work.

---

## 1. Problem Statement

**Current behavior.** Importing a file into the Data Catalog is fused with
installing it into the currently-open dataflow. `CatalogMutations.import_dataset`
copies the file into the account-level user store **and**, whenever a
`dataflowId` is present, immediately writes a project dataset ref:

```python
# utk_curio/backend/app/datasets/application/mutations.py  (import_dataset)
if dataflow_id:
    self.install_dataset(dataflow_id, item["id"], source_item=item)
    item["installed"] = True
```

The HTTP route always forwards `dataflowId`
(`routes.py:159-163`), and the frontend `importDataset` hook always passes the
open project's id (`datasetCatalogHooks.ts:194`). So **there is no way to
register a dataset in the catalog without also attaching it to the open
project.**

This conflates two distinct concepts the product wants separated:

- **Data Catalog = account-level.** A dataset a user has registered and can
  reuse across any of their projects.
- **Installed datasets = workflow-specific.** The subset of catalog datasets a
  given dataflow actually uses, recorded as refs in that project's spec
  (`spec.trill.json → dataflow.datasets[]`).

**Root cause / structural gap.** The account-level tier physically exists — the
user store at `.curio/users/<user_key>/datasets/<id>@<major>/`
(`infrastructure/storage.py:104-118`) — but it is **only ever written as a
side-effect of a project-scoped install and only ever read back through project
refs.** `CatalogListing.list_catalog` builds its universe from:

- hub registry + workspace/sample (`registry` + `local`) when `include_hub`, and
- project refs + computed outputs (`installed` + `computed`) when `dataflow_id`.

It has **no source that lists the user store on its own**
(`application/listing.py:80-97`). Consequently, if we simply stop
auto-installing on import, a freshly imported dataset would **vanish from the
catalog** — it would sit in the user store with no project ref and nothing to
list it.

**Expected behavior.**

1. Importing any **supported** file type **registers** it as a **standalone
   catalog item** in the account-level Data Catalog and shows it in the Browse
   view immediately, whether or not a project is open.
2. Import does **not** attach the dataset to any node or dataflow.
3. A **node/dataflow linkage is created only when the user explicitly
   installs/selects** the dataset for use — via the *already-existing* install
   action and route ("Use in this project").
4. Uninstalling from a project removes the ref but leaves the dataset a
   **standalone, registered** catalog item.

**Why it matters.** Matches the intended product model (catalog = account,
install = per-workflow), removes surprise cross-project coupling (importing
while dataflow A is open silently pins the dataset to A), and makes the existing
Install/Uninstall affordances meaningful for imported datasets, not just hub and
computed ones.

---

## 2. Scope

**In scope**

- Backend
  - `datasets/application/mutations.py` — `import_dataset`: drop the
    auto-install block; import is register-only.
  - New **account-level catalog source** listing registered user-store imported
    datasets, merged into `CatalogListing.list_catalog` under `include_hub`.
    Likely a small `UserDatasetRepository` (or a method on an existing repo)
    over `infrastructure/storage.list_user_datasets(user_key)` +
    `domain/manifest.load_dataset_manifest` + `catalog_item.item_from_manifest`.
  - `datasets/routes.py` — keep the `/datasets/import` route; it may keep
    accepting `dataflowId` but must no longer cause an attach (backend ignores
    it for import). No new route needed: the explicit-install path
    (`/dataflows/<id>/datasets/install`) already exists and already works for an
    `origin: "imported"` dataset (verified: `install_dataset` resolves the item
    via `get_dataset` and writes the ref through `replace_refs`,
    `mutations.py:456-463`).
- Frontend
  - `components/datasets/catalog/useDatasetCatalogDrawer.ts` — `onPickImport`:
    stop upserting into `dataflowDatasets` (import no longer installs); keep the
    `notifyDatasetCatalogRefresh()` fan-out (from the issue-1 fix); reword the
    toast to "Registered … in the data catalog".
  - `services/datasetCatalog/datasetCatalogHooks.ts` — `importDataset`: stop
    sending `dataflowId` so intent is explicit (backend-agnostic either way).
  - Verify Browse/Featured shows imported items with an **Install** ("Use in
    this project") action and the **Installed** tab shows only project-attached
    ones. This is already driven by the `installed` flag; expected to need no
    structural change, only confirmation + copy.
- Tests: backend (register-only import, account listing, explicit install/
  uninstall lifecycle) and frontend (onPickImport behavior, installed-flag
  gating).

**Out of scope (do not change)**

- Node-output / computed **auto-install on execution** (`auto_install.py`,
  `useWorkflowOperations` install-sync, `SaveOutputToggle`). Its behavior and
  tests stay as-is.
- Hub publish/unpublish, computed titling, lineage — untouched.
- Any DB schema (datasets remain filesystem-based; no migration).

**Related code paths to check (no behavior change intended)**

- `domain/dedup.dedupe_items` / `catalog_facets` — must merge the new
  account-level rows with project-ref rows by id (see §4).
- `installed_ids` / computed install-hint logic in `list_catalog`
  (`listing.py:99-142`) — the `installed` flag must resolve correctly for an
  imported dataset that *is* attached to the open project.
- `get_dataset` (`listing.py:312-329`) — already uses `include_hub=True`, so it
  inherits the new source automatically; confirm install-by-id still resolves.

---

## 3. Recommended Implementation Approach

**Split the fused operation at its two seams, then restore visibility with an
account-level read source.**

1. **Register-only import.** In `import_dataset`, remove the
   `if dataflow_id: self.install_dataset(...)` block. Return the item with
   `installed = False`. Import still writes the file to the user store via
   `install_imported_file` (unchanged) — that *is* the account-level register.

2. **Account-level listing source.** Add a repository that enumerates the user
   store and yields catalog items for **imported** datasets:
   - Iterate `storage.list_user_datasets(user_key)`; for each dir, load the
     manifest and build an item with `item_from_manifest(manifest, dir, origin=…)`.
   - **Filter to imported provenance** (`id.startswith("imported.")` / manifest
     tag `"imported"`). Computed user-store copies are deliberately excluded here
     — they remain surfaced through the `installed`/`computed` sources so the
     import-only scope holds and we don't change computed behavior.
   - Best-effort per dir: skip unreadable/malformed manifests (mirror the
     existing `_prefer_user_store_computed_title` try/except discipline).
   - Merge into `list_catalog` **only when `include_hub`** (the Browse universe),
     right after `registry`/`local`, so browse-without-a-project shows registered
     imports and a project view still merges them with its refs.

3. **Let dedup + the `installed` flag do the rest.** `dedupe_items` collapses by
   dataset id, so when the open project references an imported dataset, its
   account-level row and its installed-ref row merge into one; the existing
   `installed_ids` pass sets `installed = True`. When no project references it,
   it lists once with `installed = False` → the UI shows **Install**.

4. **Explicit install is unchanged.** `onInstall` → `ensureProjectId()` →
   `installToDataflow` → `install_dataset` already writes the project ref for an
   `origin: "imported"` item. No new backend write path.

5. **Frontend intent.** `onPickImport` stops treating the import as installed
   (no `dataflowDatasets` upsert); it refreshes the catalog and reports a
   *register* success. Install becomes a separate, explicit user action.

This keeps UI rendering, the account-level read model, the per-project ref model,
and the (unchanged) execution side effects cleanly separated, and centralizes the
user-store→item mapping in one repository rather than duplicating manifest
parsing.

---

## 4. Data and State Handling

- **Source of truth.** Account-level = user store dirs (`list_user_datasets`).
  Workflow-level = project spec `dataflow.datasets[]` (via
  `InstalledDatasetRepository`). Neither is the DB.
- **Derived `installed` flag.** Computed in `list_catalog`: `True` iff the
  dataset id is in the open project's refs (`installed_ids`), else `False`.
  A registered-but-unattached import ⇒ `False`.
- **Dedup.** By dataset id in `dedupe_items`. The account-level row and the
  project-ref row for the same import must share the same `id`
  (`imported.x<hash>`) so they merge — they do, since both derive from the same
  user-store manifest. Verify the merge keeps the richer fields (path, counts).
- **Loading / empty / error.**
  - Empty user store → account source yields `[]`; Browse still shows hub/local.
  - Unreadable manifest in a user-store dir → skipped, listing continues
    (best-effort, logged), never 500.
- **State after actions.**
  - *Import:* catalog refresh event fires (issue-1 fix retained); the item
    appears in Browse with `installed:false`. No change to `dataflowDatasets`.
  - *Install:* existing flow flips `installed:true`, upserts `dataflowDatasets`,
    moves the card to the Installed tab.
  - *Uninstall:* ref removed; the dataset stays in the account-level source, so
    it remains visible in Browse with `installed:false` (no disappearance).
- **Avoiding stale/flicker/races.** Reuse the existing shared catalog cache +
  `DATASET_CATALOG_REFRESH_EVENT` fan-out; no new client cache. The import
  in-flight guard (`importInFlightRef`) stays.

---

## 5. UI and UX Requirements

- **Import button** registers to the catalog. Toast: *"Registered `<file>` in the
  data catalog."* (not "Imported … " implying installed). The OSM-PBF guard
  (issue 3) stays ahead of this path.
- **Browse / Featured**: imported datasets appear as cards with an **Install**
  action labeled to read as *use in this project* (match the existing install
  affordance/label; no new component). Consistent card/bundle styling with hub
  and computed.
- **Installed tab**: shows only datasets attached to the open dataflow
  (`installed === true`) — unchanged filter, now meaningfully excludes freshly
  imported-but-unattached datasets.
- If **no project is open**, Install must first create/ensure a project
  (`ensureProjectId`, already wired) or be clearly gated — preserve current
  behavior; do not regress.
- No layout shift/flicker: the card transitions Browse→Installed via the same
  refresh path used today for hub installs.
- **Accessibility**: Install control keyboard-focusable with a clear
  accessible label distinguishing *register* (done at import) from *install*.

---

## 6. Edge Cases

- Import with **no open project** → registers, visible in Browse, not attached.
- **Re-import identical file** → content-hash id ⇒ idempotent; same row, no dup.
- **Import while project A open, then open project B** → dataset visible in both
  (account-level), attached to neither until installed.
- **Install then uninstall** → remains registered/visible (must not vanish).
- **Same dataset installed in multiple projects** → one account-level row;
  `installed` reflects the *currently open* project only.
- **Malformed / partial manifest** in a user-store dir → skipped, listing
  survives.
- **Computed user-store copies** must NOT be surfaced by the new account source
  (scope guard) — filter by imported provenance.
- **Dedup collision** between account row and hub row of a published-then-…
  dataset — verify id namespaces don't accidentally merge unrelated datasets.
- Legacy specs with "fat" imported refs — unaffected (still listed via
  `installed`), must still dedupe against the account row by id.

---

## 7. Testing Strategy

**Backend (`utk_curio/backend/tests/test_datasets/`)**

- `import_dataset` writes to the user store and **does not** add a project ref
  (assert `dataflow.datasets` unchanged; returned item `installed is False`),
  with and without `dataflowId` supplied.
- Account-level listing: after a register-only import, `list_catalog(include_hub=True)`
  (no dataflow) includes the imported dataset with `installed=False`; a computed
  user-store copy is **not** surfaced by the account source.
- Explicit install lifecycle: `install_dataset(dataflow_id, imported_id)` writes
  the ref and the item lists `installed=True` for that dataflow; a *different*
  dataflow still lists it `installed=False`.
- Uninstall keeps the dataset registered (still listed, `installed=False`).
- Best-effort: a malformed manifest dir doesn't fail the listing.

**Frontend (`src/tests/catalog/`)**

- `onPickImport` (extend the existing `useDatasetCatalogDrawer.import.test.ts`):
  does **not** call `setDataflowDatasets`, still fires the refresh event, toast
  copy is the register wording. (Update the existing "imports" assertions.)
- Installed-flag gating: a catalog item with `installed:false` renders an
  Install action; `installed:true` renders in the Installed tab. (Component-level
  where a seam exists.)

**Regression**

- Issue-1 refresh-on-import behavior preserved.
- Hub install and computed auto-install paths unchanged (run their existing
  suites: `test_execution_dataset_persistence`, `test_reinstall_producer`,
  `test_dataset_catalog_routes`, `useWorkflowOperations.installSync.test.ts`).

---

## 8. Acceptance Criteria

- Importing a file adds it to the Data Catalog Browse view immediately (no
  reload) and shows an Install action; it is **not** in the Installed tab and
  **no** `dataflow.datasets` ref is written.
- With no project open, import still succeeds and the dataset is visible.
- Clicking Install attaches the dataset to the current dataflow (ref written),
  moves it to the Installed tab, and `installed` reads `true`.
- Uninstalling removes it from the Installed tab but it remains in Browse.
- A dataset registered while project A is open is equally available to project B.
- Node-output/computed auto-install behavior is unchanged.
- Backend never 500s on an unreadable user-store dir; import of OSM PBF still
  shows the Autark redirect (issue 3).

---

## 9. Recommended Commit Breakdown

- **Commit 1 — Account-level catalog source (backend, additive).** Add the
  user-store imported-dataset repository/method and merge it into
  `list_catalog` under `include_hub`; tests for the listing + dedup/`installed`
  resolution. (Purely additive: imported datasets now *also* visible
  account-level; import still auto-installs at this point, so nothing breaks.)
- **Commit 2 — Register-only import (backend).** Remove the auto-install block
  in `import_dataset`; update/add tests asserting no ref is written and the
  explicit install path still attaches. (Behavior flip, safe because Commit 1
  guarantees visibility.)
- **Commit 3 — Frontend import UX.** `onPickImport` stops upserting
  `dataflowDatasets`, keeps the refresh, updates toast copy; `importDataset`
  hook stops sending `dataflowId`; confirm Install/Installed gating; update
  `useDatasetCatalogDrawer.import.test.ts`.
- **Commit 4 — Copy/label + regression polish** (only if needed): Install action
  label ("Use in this project"), a11y label, any empty-state text.

Ordering matters: Commit 1 before Commit 2 so imported datasets never
disappear between commits.

---

## 10. Engineering Quality Checklist

- [ ] User-store→item mapping centralized in one repository (no duplicated
      manifest parsing across listing/mutations).
- [ ] `import_dataset` no longer performs a project write; single responsibility.
- [ ] `installed` flag derivation unchanged and correct for imported datasets.
- [ ] Dedup merges account + ref rows by id; no unrelated merges.
- [ ] Types explicit on the new repository method and item shape.
- [ ] Account source is best-effort (skip bad dirs), never fails the listing.
- [ ] Computed/execution auto-install untouched; its tests still green.
- [ ] Issue-1 (refresh) and issue-3 (OSM PBF guard) behavior preserved.
- [ ] Frontend: no extra re-renders; reuse existing cache + refresh event.
- [ ] Toast/label copy distinguishes *register* from *install*.
