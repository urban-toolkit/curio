# Implementation Memo: Stop collapsing distinct saved datasets (Autark map outputs hidden)

**Status:** Proposed (memo only — no code written) · **Branch:** `datacatalog` · **Author:** Karla
**Area:** `utk_curio/backend/app/datasets` (catalog listing dedup/collapse) + its tests

---

## 1. Problem Statement

**Current behavior.** Outputs from **Autark map node executions** are saved correctly to the
user dataset store as distinct records (each in its own `computed.<nodeId>@1/` directory with
its own dataset id), but they are **silently hidden** from the dataset list (palette + Data
Catalog drawer) when sibling outputs exist — e.g. `whatif-baseline-compute` and
`whatif-modified-compute`. The hidden entry only reappears after the sibling versions are
deleted.

**Root cause (confirmed).** The catalog listing collapses computed datasets by **data-file
basename**:

- `collapse_computed_by_file()` — `utk_curio/backend/app/datasets/catalog_dedup.py:110-139`.
  The collapse key is `Path(path_val).name` (the **basename only**, line 127). It keeps just
  the single "richest" row per basename (by `catalog_item_rank()`).
- Called last in the listing pipeline: `services/catalog_listing.py:176` (after
  `dedupe_items()` at `:111` and path resolution).

Autark/compute outputs from **different producer nodes** get **different dataset ids and
different directories** (`computed.whatif-baseline-compute@1`,
`computed.whatif-modified-compute@1` — `installer.py:165`, `bundle.py:194-196`,
`computed_indexer.py:55`), but their generated data files often share the **same basename**
(timestamp/artifact-id-derived, e.g. `1781903321396_c8572ee7.parquet`). So
`collapse_computed_by_file` merges these genuinely-distinct datasets into one and the others
vanish. Deleting a sibling removes its file, leaving a different "richest" winner — which is
why hidden rows "reappear" on delete.

`dedupe_items()` (`catalog_dedup.py:97-107`, keyed on dataset `id`) is **not** the culprit:
distinct nodes have distinct ids, so it does not merge them (and it correctly merges a hub
registry row with its installed copy of the *same* dataset — that must stay).

**Expected behavior.** Every saved execution output is its own visible dataset entry,
immediately. Distinct datasets are never hidden because they share a filename, origin,
compute type, or other metadata. Deleting one dataset never reveals a previously hidden one.
The list reflects the actual saved dataset records at all times.

---

## 2. Scope

**In scope**

- `utk_curio/backend/app/datasets/catalog_dedup.py` — `collapse_computed_by_file()` (remove,
  or neutralize so it never merges distinct dataset records).
- `utk_curio/backend/app/datasets/services/catalog_listing.py:176` — the call site.
- `utk_curio/backend/tests/test_datasets/test_catalog_dedup.py` — the two tests that currently
  assert the basename collapse (`test_collapse_computed_by_file_keeps_richest:118`,
  `test_published_node_collapses_with_same_file_twin_in_drawer:176`) must be updated to lock in
  the new "show every distinct record" contract.

**Out of scope (must NOT change)**

- `dedupe_items()` / `merge_catalog_items()` keyed on dataset `id` — these correctly merge the
  *same* dataset's representations (hub registry row ↔ installed copy, live ephemeral row ↔
  installed row, both `computed.<node>`). Keep, including the publish/unpublish merge rules
  (`test_merge_*` tests stay green).
- Frontend filters (`useDatasetCatalogDrawer.ts:77-83`, `DatasetsPaletteDropdown.tsx:91-98`):
  dropping **non-installed** ephemeral computed rows is correct and unrelated. No React key
  collisions exist (rows keyed by unique `id`).
- The install/storage layer (`installer.py`, `bundle.py`): outputs are already saved as
  distinct records; the bug is purely in listing presentation.

---

## 3. Recommended Implementation Approach

**Stop the listing from merging distinct saved dataset records.** Because `dedupe_items()`
(by `id`) already collapses every legitimate "same dataset, two representations" case, the
basename collapse only ever *hides distinct datasets*. The recommended change:

- **Remove `collapse_computed_by_file()` and its call at `catalog_listing.py:176`** (preferred —
  it is redundant with `dedupe_items` for legitimate merges and is the sole cause of hiding).

If a conservative, reversible change is preferred over outright removal, the equivalent
behavior is to **re-key the collapse on the dataset's storage identity** rather than the file
basename — i.e. collapse only when two rows share the same `dirName` (and/or the same dataset
`id`). Since `dirName` = `computed.<seg>@1` is unique per producing node and is itself derived
from the same `id` that `dedupe_items` already merges on, this makes the function a no-op for
distinct datasets while still tolerating any same-dataset twin. Net effect is identical to
removal; pick whichever the team finds clearer to maintain.

Either way: **the data file basename must never be a collapse/dedup/grouping key.** Two
distinct dataset records that happen to share a filename are two rows.

Keep the change backend-only and behavior-preserving for genuine duplicates (same `id`).

---

## 4. Data and State Handling

- **Source of truth:** the saved dataset records — installed refs in the project spec
  (`installed.list_items(dataflowId)`) plus the on-disk `computed.<node>@1/` manifests. The
  listing must surface one row per distinct record.
- **Derived values:** identity for merging is the dataset **`id`/`dirName`**, never the data
  file path/basename. `catalog_item_rank()` / `merge_catalog_items()` remain only for merging
  same-`id` rows (hub ↔ installed, live ↔ installed).
- **Ordering/counts:** removing the collapse increases row counts where siblings were hidden;
  tab badges and palette counts derive from the same (now complete) list, so they stay
  consistent automatically.
- **No flicker/stale state:** with the auto-install + resync flow already in place, a new
  Autark output appears as its own row on execution; deleting any dataset only removes that one
  row (no hidden-row resurrection).

---

## 5. UI and UX Requirements

- Each saved Autark map output appears as its **own** entry in both the palette and the Data
  Catalog drawer, immediately after it is created, even when baseline/modified siblings exist.
- Datasets that share a name/origin/compute-type/metadata each render as separate rows (titles
  may legitimately repeat — this is acceptable per the requirement).
- Deleting one dataset removes exactly that row; no other row appears or disappears as a
  side-effect.
- Existing per-row affordances (drag, install/uninstall, publish, details, reinstall hints)
  continue to work per row; no row is a stand-in for a hidden sibling.

---

## 6. Edge Cases

- **Same producer node re-run:** still one record (install replaces `computed.<node>@1`,
  `bundle.py:199-200`); `dedupe_items` keeps it single. No change.
- **Hub registry row + installed copy of the same dataset (same id):** still merges via
  `dedupe_items`/`merge_catalog_items` (publish badge, current-name preference preserved).
- **Two distinct nodes, identical filename, identical content:** now shown as **two** rows
  (intended — they are two saved records).
- **Live ephemeral computed row (not installed):** still filtered out client-side; unaffected.
- **Bundle outputs (`format: "bundle"`, `data/bundle.json`):** one record per producing node;
  distinct bundle nodes stay distinct.
- **Legacy "fat ref" computed rows / `curio://outputs/` URIs:** still resolved for loader
  snippets; just not collapsed by basename.

---

## 7. Testing Strategy

- **Update** `test_catalog_dedup.py`:
  - `test_collapse_computed_by_file_keeps_richest` → assert two distinct-node computed datasets
    sharing a basename are **both kept** (no collapse).
  - `test_published_node_collapses_with_same_file_twin_in_drawer` → assert the published-node
    case yields the merged-by-id row **plus** the distinct second node's row (2 rows).
  - Keep `test_collapse_computed_by_file_keeps_distinct_files` (distinct files → 2 rows) as-is.
  - Keep all `test_merge_*` tests (same-id merge semantics unchanged).
- **Add** a regression test reproducing the report: three computed rows
  (`whatif-baseline-compute`, `whatif-modified-compute`, an Autark map output) sharing a
  basename → the listing keeps all three; removing one leaves the other two unchanged.
- If a listing-level test harness exists, add an integration test asserting
  `list_catalog(...)` returns one row per distinct `computed.<node>@1` record for that fixture.

---

## 8. Acceptance Criteria

1. Running an Autark map node that saves output shows that output as its own row in the palette
   and drawer immediately, regardless of existing baseline/modified siblings.
2. Two distinct saved datasets that share a data-file basename both appear (no collapse).
3. Deleting one dataset removes only that row; no previously hidden row appears.
4. A hub registry row and the installed copy of the **same** dataset still merge into one row
   (no regression in publish/unpublish display).
5. The dataset list row-set equals the set of distinct saved dataset records (installed refs +
   on-disk computed manifests) for the dataflow.
6. Backend listing tests encode the new "show all distinct records" contract; `test_merge_*`
   stay green.

---

## 9. Recommended Commit Breakdown

- **Commit 1 — remove basename collapse + update tests.** Delete `collapse_computed_by_file`
  (or re-key to `dirName`/`id`) and its call at `catalog_listing.py:176`; update the two
  collapse tests to the new contract; add the baseline/modified/Autark regression test.
- **Commit 2 — listing integration coverage (optional).** A test asserting `list_catalog`
  returns one row per distinct computed record for a multi-output fixture.

---

## 10. Engineering Quality Checklist

- [ ] The data-file basename is no longer a collapse/dedup/group/filter key anywhere in the
      listing pipeline.
- [ ] `dedupe_items`/`merge_catalog_items` (same-`id` merges) are unchanged and still covered.
- [ ] No frontend filter or React key hides distinct rows.
- [ ] Distinct saved records always render as distinct rows; deleting one never reveals another.
- [ ] Tests reverse the old collapse expectation and add a baseline/modified/Autark regression;
      `test_merge_*` remain green.
- [ ] Change is backend-only; install/storage untouched.
- [ ] Row counts / tab badges derive from the complete list and stay consistent.
