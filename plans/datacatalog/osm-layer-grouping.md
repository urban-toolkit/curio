# Implementation Memo: Group OSM layer datasets under one tabbed card

**Status:** Implemented (Approach X) · **Branch:** `datacatalog` · **Author:** Karla

> **Implemented 2026-07-13** in three commits:
> - `073881f` — persist `group_id`/`layer_name` on each layer dataset (manifest → item).
> - `0f8e26f` — synthesize the group as a `bundle`-shaped catalog entry across
>   list (`group_osm`) / get / preview (tabbed parts) / install-all / uninstall-all.
> - `23e7e83` — drawer sets `groupOsm:true` (palette stays flat); install/uninstall
>   expand over the group's real `groupLayerIds` so dataflow refs stay accurate.
>
> The frontend reuses the existing bundle card + tabbed preview verbatim (the
> group is a `format:"bundle"` item). Key correctness point discovered during
> build: `generateTrill(..., dataflowDatasetsRef)` serializes installed refs into
> the saved spec, so installing the synthetic group id directly would have let a
> later save drop the real per-layer refs — hence the drawer installs each
> member layer by its real id.
**Area:** `utk_curio/backend/app/datasets` (group synthesis) and a small
`utk_curio/frontend/urban-workflows` polish

> **Decision (user, 2026-07-13):** *Single bundle-like entry* + a group-level
> **"Install all layers"** action (not per-layer visual grouping). So the OSM
> import is presented as **one `bundle`-shaped catalog entity**: one card, a
> tabbed detail (one tab per layer), and one install that attaches every layer.
> The per-layer datasets still exist on disk (standalone), but the catalog
> drawer/detail/install treat the group as a unit. This means the **frontend
> reuses the existing bundle UI verbatim** (a `format: "bundle"` item with a
> `parts[]` preview); the work is backend group synthesis. Supersedes the
> Approach Y recommendation below.

---

## 1. Problem Statement

Importing an OSM `.pbf` now registers **one standalone GeoParquet dataset per
non-empty layer** (points / lines / multipolygons / …), each independently
installable (commit `8679aae`). But in the Data Catalog drawer they appear as N
separate cards ("back_bay (points)", "back_bay (lines)", …), cluttering the list
and hiding the fact that they came from one file.

**Desired:** the layers stay standalone datasets, but the drawer shows **one
card per import**, and its detail page shows the layers **as tabs** — the same
tabbed UX as a `bundle` dataset's parts.

## 2. Scope

**In scope**
- Backend: persist a shared `group_id` + `layer_name` on each per-layer OSM
  dataset (manifest → catalog item). No new routes; no synthetic datasets.
- Frontend (drawer only): collapse items sharing `groupId` into one group card;
  a grouped detail view with a per-layer tab bar that renders the existing
  single-dataset detail for the active layer.

**Out of scope / unchanged**
- Per-layer registration & storage (done). Each layer stays a real dataset.
- The dataset **palette** and palette dropdown keep listing individual layers
  (draggable standalone datasets) — grouping is a drawer presentation concern.
- Computed/bundle datasets, install/uninstall backend, OSM ingestion itself.

## 3. Recommended Implementation Approach

**Approach Y — visual grouping over real datasets (recommended).** Keep each
layer a first-class dataset; group only in the drawer UI. Chosen over a
backend-synthesized "group = one bundle entity" (Approach X) because the user
asked for *standalone* datasets, X would need synthetic group entities threaded
through list/get/preview/install (large surface, awkward install semantics), and
Y keeps per-layer install/preview/lineage working for free.

**Backend (minimal, additive)**
- `domain/manifest.py`: add optional `group_id: str | None`, `layer_name:
  str | None` to `DatasetManifest`; read in `_parse_manifest` (JSON keys
  `groupId` / `layerName`), write in `build_manifest_dict`.
- `install/installer.py`: `install_imported_file(..., group_id=None,
  layer_name=None)` → into the `DatasetManifest(...)`.
- `application/mutations.py::_import_osm_pbf_layers`: mint one **deterministic**
  group id per import — `osm.x<sha256(pbf_bytes)[:8]>` — and thread it +
  `layer.name` through `_install_imported_bytes` → `install_imported_file`.
- `domain/catalog_item.py`: `base_item` defaults `groupId=None, layerName=None`;
  `item_from_manifest` surfaces `manifest.group_id` / `manifest.layer_name`.
- `schemas/catalog_item.py`: add the two keys (doc/type only).

**Frontend (drawer only)**
- `DatasetCatalogItem`: add `groupId?: string | null`, `layerName?: string | null`.
- `useDatasetCatalogDrawer` `items` memo: after filtering, fold consecutive
  items sharing a non-empty `groupId` into a single **group descriptor**
  `{ isGroup: true, groupId, title: <base>, layers: DatasetCatalogItem[] }`.
  Ungrouped items pass through unchanged. Installed-count/tab filters operate on
  the flattened layers (a group counts as installed only if a layer is).
- Card list (`DatasetCatalogDrawer.tsx`): render a **group card** for group
  descriptors — title = base name, format badge "OSM", subtitle "N layers",
  installed pill if any layer installed. Clicking opens the grouped detail.
  Ordinary items still render `DatasetCard`.
- Grouped detail: a new `DatasetGroupDetailModal` (thin) that renders a tab bar
  (one tab per layer, label = `layerName`) above the **existing**
  `DatasetDetailPanel` for the active layer's real dataset id. This reuses all
  per-layer detail (Overview / Schema / Table Preview / Lineage / Install) and
  matches the "layers separated by tabs" requirement. `openDatasetDetails`
  learns to open a group (store the group's layers + active layer id).

Rationale for tabbing at the detail level (vs inside Table Preview like a
bundle): the layers are separate datasets with their own schema/lineage/install,
so a top-level layer tab that swaps the whole panel is both simpler and richer
than a bundle's preview-only parts — while reading as the same "tabs per layer".

## 4. Data and State Handling

- **Source of truth:** each layer dataset's manifest (`group_id`, `layer_name`).
  Group membership is derived by grouping catalog items on `groupId`.
- **Deterministic group id** (`osm.x<pbf-hash>`) so re-importing the same file
  reuses the same group. (Edge: parquet bytes aren't guaranteed byte-stable, so
  a re-import could create fresh layer dirs that still share the groupId — see
  §6; acceptable, flagged.)
- **installed state:** a group is "installed" iff ≥1 layer is installed; the
  Installed tab shows individual installed layers (not the group), so partial
  installs read correctly.
- Reuses the existing shared catalog cache + refresh event; grouping is pure
  derivation in the memo, no new fetch/cache.

## 5. UI and UX Requirements

- **Group card:** title = base file name (e.g. "back_bay"), "OSM" badge, "N
  layers" subtitle; opens the grouped detail. No inline install on the card
  (install is per-layer in the detail) — keeps standalone semantics explicit.
- **Grouped detail:** horizontal tab bar (Points / Lines / Multipolygons / …),
  `role="tablist"`, arrow-key navigation, active tab renders the layer's full
  detail incl. its own Install. Tab labels from `layerName`.
- **Palette / dropdown:** unchanged — individual layers remain listed/draggable.
- No layout shift; group collapse is deterministic on the already-loaded list.

## 6. Edge Cases

- Import with a **single** non-empty layer → still a group of one; render it as
  an ordinary card (no group wrapper) to avoid a pointless one-tab detail.
- **Legacy** OSM datasets imported before this change have no `groupId` → they
  render as individual cards (graceful; not retro-grouped).
- **Re-import** same pbf: same `groupId`; layer dirs idempotent if parquet bytes
  are stable, otherwise duplicate layers share the group (visible as repeated
  tabs) — acceptable; a follow-up could key layer dirs on `groupId+layerName`.
- A layer **uninstalled** while its sibling stays installed → group card shows
  installed (any-layer), detail reflects per-layer state.
- Non-OSM imports and computed/bundle datasets: `groupId` empty → unchanged.
- Search: a group matches if any layer matches; matched group still opens to all
  layers (don't hide non-matching tabs — or filter tabs? default: show all).

## 7. Testing Strategy

- **Backend:** manifest round-trips `group_id`/`layer_name`; `_import_osm_pbf_layers`
  stamps one shared `groupId` across layers + distinct `layerName`; catalog items
  expose them. (Extend `test_dataset_catalog_routes.py` /
  `test_user_store_repository.py`.)
- **Frontend:** `items` memo groups siblings into one descriptor and leaves
  ordinary items alone; single-layer import is not wrapped; grouped detail tab
  switching renders the active layer; palette listing stays flat.

## 8. Acceptance Criteria

- Importing a multi-layer `.pbf` shows **one** card in the drawer; its detail
  has one tab per layer, each showing that layer's table/schema and its own
  Install. The palette still lists individual layers.
- Each layer remains an independently installable standalone dataset.
- Non-OSM and legacy datasets are unaffected.

## 9. Recommended Commit Breakdown

1. Backend: manifest + installer + item `group_id`/`layer_name`; mint shared id
   in `_import_osm_pbf_layers`; tests.
2. Frontend: `DatasetCatalogItem` fields + drawer `items` grouping + group card;
   tests.
3. Frontend: grouped detail (layer tab bar over `DatasetDetailPanel`) + open flow.

## 10. Engineering Quality Checklist

- Group metadata is first-class manifest fields (not tag-string hacks).
- Grouping is drawer-only derivation; palette/other surfaces untouched.
- Reuses `DatasetDetailPanel` per layer — no duplicated detail rendering.
- Single-layer and legacy/no-group cases degrade to ordinary cards.
- Per-layer install/preview/lineage keep working; installed state is
  partial-install-correct.
- Deterministic group id; re-import limitation documented.
