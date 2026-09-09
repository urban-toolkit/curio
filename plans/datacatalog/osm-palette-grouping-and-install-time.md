# Implementation Memo — OSM PBF Palette Grouping + Dataset Install-Time Metadata

Branch: `datacatalog`. Two focused commits.

## 1. Problem Statement

**Commit 1 — OSM layers are flat in the Dataset Palette.** An imported OSM PBF
expands into one dataset per layer (points / lines / multipolygons / …), each
sharing a `groupId`. The Data Catalog *drawer* folds these into one entry
(`groupOsm=true` → synthetic `format:"osm"` item), but the Dataset Palette fetches
flat (`groupOsm=false`) and renders every layer as a separate top-level row. The
palette should show them as a **collapsible group** (parent = the multilayer OSM
PBF import; children = the individual layers), matching the `chicago_loop`
reference screenshots, while each layer stays individually draggable.

**Commit 2 — no persisted install time; can't sort by it.** Catalog items expose
`createdAt` (import/record time) and `updatedAt`, but not *when the dataset was
installed into the dataflow* — even though the dataflow ref already stores
`installedAt`. The palette therefore can't offer "sort by install time" vs "sort
by import time" from persisted metadata.

## 2. Scope

**Commit 1 (UI only, no backend):**
- `services/datasetCatalog/datasetPaletteGrouping.ts` (new, pure) + test.
- `components/menus/nodes/datasetPalette/DatasetPaletteRows.tsx` — add
  `DatasetGroupRow`.
- `DatasetPaletteRows.module.css` — group header, member indent + accent, caret.
- `DatasetsPaletteDropdown.tsx` — render grouped entries.
- service `index.ts` export.

**Commit 2:**
- Backend: `repositories/installed.py` surface `installedAt` from the ref;
  `domain/catalog_item.py` `base_item` default `installedAt`.
- Frontend: `datasetCatalogTypes.ts` add `installedAt`; extend grouping helper
  with representative `importedAt`/`installedAt` + `sortDatasetPaletteEntries`;
  palette sort toggle. Tests.

**Out of scope:** the drawer's OSM group card, backend list sort, computed/hub
install paths, publish/unpublish.

## 3. Recommended Implementation Approach

**Group client-side (Commit 1).** Keep the palette's flat fetch — the members
already carry `groupId`/`layerName` and are individually draggable as-is. Add a
pure `groupDatasetsForPalette(items)` that folds same-`groupId` items into a
`DatasetPaletteGroup` (first-seen order preserved, singles pass through), so the
grouping is testable and shared. Derive the group title by stripping the trailing
` (layer)` suffix from a member title (mirror backend `group_base_title`). Render
a non-draggable `DatasetGroupRow` header (OSM PBF icon/badge, title, IMPORTED
chip, timestamp, expand caret) that, when open, lists the existing `DatasetRow`
members inside an indented container with a coloured left accent bar. Reuse the
existing package-palette row classes and format-chip styling — no new visual
language.

**Persist + surface install time (Commit 2).** `installedAt` is written to the
ref by `_ref_from_item`; surface it onto the item in
`InstalledDatasetRepository.list_items` (both folder-based and legacy-ref paths)
and default it in `base_item` for type-safety. Import time is already persisted
as `createdAt`. The palette sort is client-side over the grouped entries
(`sortDatasetPaletteEntries(entries, mode)`), keyed on persisted metadata only —
`createdAt` for import, `installedAt` for install — never UI state. A group sorts
as a unit by its representative timestamp (max across members, matching the
backend group's `updatedAt` rule).

## 4. Data and State Handling

- Source of truth: manifest `createdAt` (import) + dataflow ref `installedAt`
  (install), both persisted; the palette reads them off the catalog item.
- Grouping/sorting are pure transforms of `catalog.items`; no new fetch, no
  duplicated state. Expand/collapse is local component state (view-only, not
  persisted) — this is presentation, distinct from the sort key which must be
  persisted metadata.
- Representative group timestamps = `max` of members' respective fields; `null`
  when unknown (sorts last).

## 5. UI and UX Requirements

- Collapsed group: single row with OSM PBF badge, base title (`chicago_loop`),
  `IMPORTED` chip, relative time, down-caret. Expanded: up-caret + indented
  member rows with a left accent bar; each member draggable and selectable
  exactly as today.
- Preserve palette spacing, hierarchy, icons, hover/drag behaviour. Caret toggle
  is a real `<button>` with `aria-expanded` and an accessible label; members
  remain in a labelled region.
- Sort control: a small toggle (default Import date) switching to Install date,
  re-ordering both singles and groups; label states the active key.
- No layout shift or flicker: grouping/sorting are memoised; expand state keyed
  by `groupId` so it survives re-renders.

## 6. Edge Cases

- A `groupId` with a single member still renders as a group (consistent).
- Members missing `layerName`/`title` → title falls back to `groupId`.
- Missing `createdAt`/`installedAt` → entry sorts last; never throws.
- Non-OSM datasets (no `groupId`) always render as singles.
- Empty palette / loading / installing placeholders unchanged.
- Re-import (new `groupId`) forms a separate group — no collision with a prior
  import (aligns with the unique-id import behaviour already shipped).

## 7. Testing Strategy

- `datasetPaletteGrouping.test.ts` — folds same-group items, preserves order,
  passes singles through, derives base title, computes representative
  timestamps, and `sortDatasetPaletteEntries` orders by import vs install time
  (groups sort as a unit; missing timestamps last).
- Backend `installed.py` surfacing: an installed dataset's item carries the ref's
  `installedAt` (extend existing installed-repo/route tests).
- Frontend palette render: group collapses/expands; members draggable; sort
  toggle reorders. (Add focused tests; keep existing palette tests green.)

## 8. Acceptance Criteria

1. Importing an OSM PBF and installing its layers shows one collapsible group in
   the palette; expanding reveals each layer; each layer drags onto the canvas.
2. The group parent is clearly marked as a multilayer OSM PBF import (OSM PBF
   badge + import provenance).
3. The palette can sort by install time and by import time, correctly ordering
   both single datasets and OSM groups, using persisted metadata.
4. `installedAt` is persisted metadata surfaced on the catalog item; import time
   remains separate (`createdAt`).
5. Existing palette visuals/interactions and all existing tests are unchanged.

## 9. Commit Breakdown

- **Commit 1:** grouping helper + `DatasetGroupRow` + CSS + dropdown wiring +
  grouping test.
- **Commit 2:** backend `installedAt` surfacing + `base_item` default + type;
  representative timestamps + `sortDatasetPaletteEntries`; palette sort toggle;
  sort/backend tests.

## 10. Engineering Quality Checklist

- Grouping/sorting centralized in one pure, typed module (no logic in JSX).
- Reuses existing row components, chips, provenance/title helpers — minimum diff.
- `installedAt` consistently named across backend item, type, and UI; sourced
  from persisted metadata, not UI state.
- Memoised transforms; expand state keyed by id → no needless re-renders/flicker.
- Accessible caret/region; existing tests kept green.
