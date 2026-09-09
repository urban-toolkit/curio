# Implementation Memo — Dataset Timestamps & Full-Cleanup Uninstall / Fresh Re-import

Branch: `datacatalog`

## 1. Problem Statement

Two related defects in the imported-dataset lifecycle:

### 1a. Timestamp labels mix Curio-record metadata with source-file metadata

The dataset detail panel presents timestamps that conflate two different
concepts:

- `DatasetDetailPanel.tsx:487` renders **"Created"** from `dataset.updatedAt`.
- `DatasetDetailPanel.tsx:488` renders **"Last updated"** from
  `dataset.updatedAt`.

Both rows read the *same* field, and that field (`updatedAt`) is always the
**Curio record time** — for imports it is set to "now" at import
(`installer.install_imported_file` writes `created_at = updated_at =
datetime.now(...)`). There is **no field at all** capturing the *source file's*
own last-modified date. So the panel:

- shows the Curio import time under a "Created" label sourced from `updatedAt`
  (semantically wrong — "Created" should come from a creation field);
- offers nothing that tells the user when the **original file** was last
  changed, even though the browser `File` object carries `File.lastModified`.

Expected behavior: clearly separate **(a) the dataset record's import/creation
date in Curio** from **(b) the source file's last-updated date**, and label each
so a user is never misled about which is which.

### 1b. Uninstall leaves stale metadata; identical re-import reuses the old folder

Imported datasets live in the account-level user store
(`.curio/users/<key>/datasets/imported.x<hash>@1/`) and are surfaced,
project-independently, by `UserDatasetRepository.list_items()`.

- **Stale metadata on uninstall.** `CatalogMutations.uninstall_dataset`
  (`mutations.py:563`) only `rmtree`s the store folder when
  `origin == "computed"`. For `origin == "imported"` it deletes *only the
  dataflow ref* and leaves the store folder, its `manifest.json`, the data file,
  and the `.meta.json` counts sidecar behind. The dataset therefore keeps
  appearing in the catalog (via the account-level listing) after the user
  "removed" it — traces are **not** fully removed.
- **Identical-file re-import reuses the folder.**
  `installer.install_imported_file` (`installer.py:305`) derives the dataset id
  and directory name from `sha256(file_bytes)` (`imported.x<hash>@1`) and has a
  fast-path that returns the *existing* install when the folder is present. So
  re-importing a byte-identical file (whether or not it was uninstalled) reuses
  the previous folder / id instead of creating a new dataset. Combined with 1b's
  leftover folder, an "uninstall then re-import" silently resurrects the old
  dataset's directory and metadata.

Expected behavior: uninstalling an imported dataset removes **all traces**
(store folder, manifest, data file, sidecars, ref). Re-importing a file — even a
byte-identical one — is treated as a **new** dataset with a fresh folder;
content-hash "identical-file detection" must not influence re-import.

Why it matters: correctness (users see datasets they deleted), storage hygiene
(orphaned folders accumulate), and predictability (import should always produce
a new, independent dataset).

## 2. Scope

**In scope**

- Backend
  - `install/installer.py` — `install_imported_file` id generation + new
    `source_updated_at` param; drop content-hash keying & fast-path reuse for
    imports.
  - `application/mutations.py` — `import_dataset` / `_install_imported_bytes` /
    `_import_osm_pbf_layers` thread `source_updated_at`; `uninstall_dataset`
    removes the store folder for imported datasets (guarded against other
    dataflows that still reference it).
  - `domain/manifest.py` — add `source_updated_at` to `DatasetManifest`,
    `_parse_manifest`, `build_manifest_dict`.
  - `domain/catalog_item.py` — expose `createdAt` + `sourceUpdatedAt` on catalog
    items.
  - `routes.py` — accept `sourceUpdatedAt` on the import form.
- Frontend
  - `services/datasetCatalog/datasetCatalogApi.ts` — send `file.lastModified` as
    `sourceUpdatedAt`.
  - `services/datasetCatalog/datasetCatalogTypes.ts` — add `createdAt`,
    `sourceUpdatedAt` fields.
  - `components/datasets/catalog/DatasetDetailPanel.tsx` — fix the "Created"
    row source and add a distinct "Source updated" row.
- Tests: installer id-uniqueness + source timestamp; mutations uninstall
  cleanup + re-import freshness; user-store listing after uninstall; detail
  panel timestamp rendering.

**Out of scope / unchanged**

- Computed and hub dataset install/uninstall paths (`computed.<node>@1` keying,
  reinstall-producer behavior) — untouched.
- Publish/unpublish flows and the committed catalog tree.
- The OSM per-layer *grouping* UX; only the group-id **uniqueness per import**
  changes (so two imports of the same PBF don't collapse into one group).
- Preview/export/lineage.

## 3. Recommended Implementation Approach

**Fresh identity per import (1b, re-import).** Replace the content-hash id in
`install_imported_file` with a per-import unique token. Backend code may use
`uuid.uuid4().hex` (the Workflow-sandbox `Math.random`/`Date.now` ban does not
apply to server Python). Emit `imported.x<uuid12>` — the `x` prefix keeps the
first char a letter so the id still satisfies `DATASET_ID_RE`. Because each id is
unique, the destination never pre-exists; remove the now-dead content-hash
fast-path and the `hashlib` import if unused. Keep the `replace` parameter
signature for call-site stability but it is moot for new imports.

- For OSM: generate **one** unique group token per `_import_osm_pbf_layers`
  call and reuse it for every layer of that call, so layers of the *same* import
  still share a group but a *second* import of the same PBF forms a separate
  group. Drop the `sha256(pbf_bytes)` group id.

**Full-cleanup uninstall (1b, stale metadata).** In `uninstall_dataset`, after
computing `removed_ref`, extend the store-folder removal beyond `computed` to
imported/folder-backed datasets: when the removed ref's `dirName` resolves to a
folder in the user's store, `rmtree` it — but **only if no other dataflow still
references it**. Reuse the existing `owner.dataset_usage(dataset_id)` resolver
(reads every project spec) *after* `replace_refs` persists this dataflow's
removal, so a dataset shared by another project is preserved. `rmtree` naturally
removes the manifest, data file, and `.meta.json` sidecar in the folder.

**Timestamp separation (1a).** Introduce a first-class `source_updated_at`
manifest field, populated from the browser `File.lastModified` sent at import.
Keep `created_at`/`updated_at` as the Curio *record* dates (unchanged meaning).
Surface three catalog-item fields — `createdAt` (record created), `updatedAt`
(record updated), `sourceUpdatedAt` (source file's own last-modified) — and let
the panel label each explicitly. This follows the existing "manifest is the
source of truth; `item_from_manifest` maps it to the catalog item" pattern and
adds no per-component date logic.

## 4. Data and State Handling

- **Source of truth:** `manifest.json` in the user store. `created_at` =
  import/creation time (server clock at import). `updated_at` = last record
  update (import time for imports). `source_updated_at` = ISO string derived from
  the client-sent `File.lastModified`; `None` when the client omits it (older
  clients, programmatic imports).
- **Derived values:** `item_from_manifest` maps manifest → item; `createdAt`
  falls back to `updatedAt` only in the UI, never fabricated in the manifest.
- **Import flow:** route parses `sourceUpdatedAt` (epoch-ms or ISO) → ISO →
  `_install_imported_bytes` → `install_imported_file` → manifest. Each import
  yields a brand-new folder/id.
- **Uninstall flow:** remove ref → persist (`replace_refs`) → check
  `dataset_usage`; if empty, `rmtree` the store folder. Account-level listing
  (`UserDatasetRepository`) then no longer sees it, so the drawer refresh drops
  the card with no stale row.
- **Avoiding races/stale UI:** the existing `notifyDatasetCatalogRefresh()` fan
  out already re-fetches the catalog after uninstall/import; no new client cache
  work is needed. Folder removal is best-effort wrapped (never fails the
  uninstall response), matching the current computed-uninstall pattern.

## 5. UI and UX Requirements

In the detail panel "General" info list:

- **Created** (or "Imported") → `dataset.createdAt ?? dataset.updatedAt`,
  formatted as an absolute date. This is the Curio record date.
- **Last updated** → `relativeTime(dataset.updatedAt)` — the Curio record's last
  change (unchanged behavior, now correctly *not* doubling as "Created").
- **Source updated** → shown only when `dataset.sourceUpdatedAt` is present:
  `relativeTime(dataset.sourceUpdatedAt)` (with an absolute-date title/tooltip),
  labeled to make clear it refers to the original file, not the Curio record.

Labels must be unambiguous ("Created"/"Last updated" = the Curio record;
"Source updated" = the original file). No layout shift: the source row is
conditionally rendered and the two record rows always render. Consistent with
existing `<dl className={styles.infoRows}>` styling; `relativeTime`/`formatBytes`
helpers reused. Screen readers get real `<dt>`/`<dd>` pairs (already the
pattern).

## 6. Edge Cases

- **Client omits `sourceUpdatedAt`** (old frontend, API import): manifest
  `source_updated_at = None`; panel hides the "Source updated" row. No crash.
- **Malformed `sourceUpdatedAt`**: route coerces defensively; unparseable →
  treated as absent (None), never 500.
- **Byte-identical re-import**: new uuid → new folder/id → two distinct catalog
  entries. Verified by test.
- **Uninstall a dataset still used by another dataflow**: `dataset_usage`
  non-empty → folder preserved; only this dataflow's ref removed.
- **Uninstall a register-only import with no ref in this dataflow**: unchanged —
  still raises "not installed" 404 (the drawer only offers uninstall for
  installed items). Removing a purely-registered-but-uninstalled dataset stays
  out of scope (no such action exists today).
- **OSM group re-import**: second import of the same PBF creates a new group id
  → both imports listed as separate grouped entries, not merged.
- **Partial/failed prior install folder**: irrelevant now — unique ids never
  collide with a leftover dir.
- **`rmtree` failure (locked file / perms)**: caught; uninstall still succeeds
  (best-effort, matches computed path).

## 7. Testing Strategy

- **Installer unit** (`test_datasets/`):
  - two `install_imported_file` calls with identical bytes → **different**
    `dataset_id` / `dir_name`, two folders on disk.
  - `source_updated_at` passed through → present in manifest and re-read by
    `load_dataset_manifest`.
- **Mutations / service:**
  - import → install into dataflow → uninstall → store folder gone; manifest,
    data file, `.meta.json` sidecar all removed; account-level listing empty.
  - import → install into two dataflows → uninstall from one → folder retained;
    still listed.
  - uninstall → re-import identical file → new id, folder recreated fresh.
  - OSM PBF imported twice → distinct group ids.
- **Route:** import form with `sourceUpdatedAt` → item carries `sourceUpdatedAt`;
  without it → `sourceUpdatedAt` null.
- **Frontend:**
  - `datasetCatalogApi.import.test` — form includes `sourceUpdatedAt` from
    `file.lastModified`.
  - `DatasetDetailPanel.test.tsx` — "Created" uses `createdAt` (falls back to
    `updatedAt`); "Source updated" row appears iff `sourceUpdatedAt` set, hidden
    otherwise.
- **Regression:** `test_user_store_repository` still lists imports (unaffected
  by uuid ids); computed uninstall unchanged.

## 8. Acceptance Criteria

1. Importing the same file twice creates two independent datasets with different
   ids and folders; neither reuses the other's directory.
2. Uninstalling an imported dataset removes its store folder, `manifest.json`,
   data file, and `.meta.json` sidecar, and the dataflow ref; it no longer
   appears in the catalog after refresh.
3. A dataset referenced by another dataflow is **not** deleted from the store
   when uninstalled from one dataflow.
4. The detail panel "Created" row shows the Curio record date (from
   `createdAt`), not a value doubling as "Last updated".
5. When the source file's modified date is known, a distinct "Source updated"
   row shows it, clearly labeled as the original file's date; when unknown, the
   row is absent (no blank/placeholder, no layout shift).
6. Computed/hub install/uninstall/publish behavior is unchanged.
7. All new and existing dataset tests pass.

## 9. Recommended Commit Breakdown

1. **Manifest + item + installer plumbing** — add `source_updated_at` to
   manifest/build/parse; expose `createdAt`/`sourceUpdatedAt` on items; unique
   per-import id + drop hash fast-path in `install_imported_file`; installer
   unit tests.
2. **Mutations** — thread `source_updated_at`; unique OSM group id; full-cleanup
   `uninstall_dataset` with cross-dataflow guard; mutations/service tests.
3. **Route** — accept + normalize `sourceUpdatedAt`; route test.
4. **Frontend** — send `file.lastModified`; type fields; panel timestamp rows;
   frontend tests.

## 10. Engineering Quality Checklist

- No duplicated date logic — one manifest field, one mapper, UI reads mapped
  fields.
- `uuid` id generation centralized in the installer; callers unchanged.
- Uninstall cleanup reuses the existing `dataset_usage` resolver (no new
  spec-walking code) and mirrors the established best-effort `rmtree` pattern.
- Types explicit end-to-end (`source_updated_at: str | None`; `sourceUpdatedAt?:
  string | null`).
- Loading/empty/error handled: absent source date hides its row; `rmtree` and
  date-parse failures never break the request.
- No new re-renders/flicker; existing refresh event drives the drawer.
- Accessibility preserved (semantic `<dt>/<dd>`).
- Follows existing datacatalog conventions (`imported.x…` ids, manifest as
  source of truth).
