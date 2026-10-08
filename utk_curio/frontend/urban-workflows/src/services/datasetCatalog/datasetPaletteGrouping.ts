import type {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetFormat,
  DatasetGroupLayerRef,
  DatasetOrigin,
} from "./datasetCatalogTypes";
import { compareCatalogDates } from "./catalogDates";
import { layerGroupKind } from "./datasetCatalogTypes";
import { osmGroupLoaderSnippet } from "./datasetLoaderSnippets";

/**
 * Dataset Palette entries after folding multi-layer OSM PBF imports into groups.
 *
 * The palette fetches datasets flat (each OSM layer is its own draggable
 * dataset), so grouping is a pure, client-side transform keyed on the shared
 * ``groupId`` the backend stamps on every layer of one import. A group renders
 * as a collapsible parent (the multilayer OSM PBF import) whose children are the
 * individual, still-draggable layer datasets; everything else passes through as
 * a single row.
 */
export interface DatasetPaletteGroup {
  kind: "group";
  /** Shared ``groupId`` of every member layer (stable across re-renders). */
  groupId: string;
  /** Base import name (member titles minus their ``(layer)`` suffix). */
  title: string;
  /** The individual layer datasets, in listing order. */
  members: DatasetCatalogItem[];
  /** Most-recent member record-update time — the header's relative time. */
  updatedAt: string | null;
  /** Most-recent member import/creation time (persisted ``createdAt``). */
  importedAt: string | null;
  /** Most-recent member install time (persisted ``installedAt``). */
  installedAt: string | null;
}

export interface DatasetPaletteSingle {
  kind: "single";
  dataset: DatasetCatalogItem;
}

export type DatasetPaletteEntry = DatasetPaletteGroup | DatasetPaletteSingle;

// Strips a trailing " (points)" / " (multipolygons)" layer suffix from a member
// title to recover the import's base name. Mirrors the backend
// ``osm_group.group_base_title`` regex so both ends derive the same name.
const LAYER_SUFFIX_RE = /\s*\([^)]*\)\s*$/;

/** Base title for an OSM layer group — the first member's title with its
 * ``(layer)`` suffix removed, falling back to the group id. */
export function osmGroupBaseTitle(
  members: DatasetCatalogItem[],
  groupId: string,
): string {
  const raw = members[0]?.title ?? "";
  return raw.replace(LAYER_SUFFIX_RE, "").trim() || groupId;
}

/** Import/creation timestamp of a dataset for palette sorting: the persisted
 * record-creation time, falling back to the last-updated time. */
export function datasetImportedAt(dataset: DatasetCatalogItem): string | null {
  return dataset.createdAt ?? dataset.updatedAt ?? null;
}

/** Install timestamp of a dataset for palette sorting (persisted; ``null`` when
 * the dataset is not installed in a dataflow). */
export function datasetInstalledAt(dataset: DatasetCatalogItem): string | null {
  return dataset.installedAt ?? null;
}

/** The latest non-empty date ``pick`` gives across members, read as a time
 * (``compareCatalogDates``), or null. The backend dates a layer group the same
 * way (``build_layer_group_item``). */
function latest(
  members: DatasetCatalogItem[],
  pick: (m: DatasetCatalogItem) => string | null | undefined,
): string | null {
  let max: string | null = null;
  for (const m of members) {
    const value = pick(m);
    if (value && (max === null || compareCatalogDates(value, max) > 0)) max = value;
  }
  return max;
}

/**
 * Fold same-``groupId`` datasets into {@link DatasetPaletteGroup} entries,
 * preserving first-seen order; datasets without a ``groupId`` pass through as
 * {@link DatasetPaletteSingle}. A group with a single member is still a group
 * (an OSM import always registers under a group id).
 */
export function groupDatasetsForPalette(
  items: DatasetCatalogItem[],
): DatasetPaletteEntry[] {
  const out: DatasetPaletteEntry[] = [];
  const membersByGroup = new Map<string, DatasetCatalogItem[]>();
  const slotByGroup = new Map<string, number>();

  for (const item of items) {
    const groupId = item.groupId;
    if (!groupId) {
      out.push({ kind: "single", dataset: item });
      continue;
    }
    let members = membersByGroup.get(groupId);
    if (!members) {
      members = [];
      membersByGroup.set(groupId, members);
      slotByGroup.set(groupId, out.length);
      out.push({
        kind: "group",
        groupId,
        title: groupId,
        members,
        updatedAt: null,
        importedAt: null,
        installedAt: null,
      });
    }
    members.push(item);
  }

  for (const [groupId, members] of membersByGroup) {
    const slot = slotByGroup.get(groupId)!;
    out[slot] = {
      kind: "group",
      groupId,
      title: osmGroupBaseTitle(members, groupId),
      members,
      updatedAt: latest(members, (m) => m.updatedAt),
      importedAt: latest(members, datasetImportedAt),
      installedAt: latest(members, datasetInstalledAt),
    };
  }

  return out;
}

/** The real per-layer datasets of a group, as drag-payload layer refs. */
export function osmGroupLayerRefs(
  group: DatasetPaletteGroup,
): DatasetGroupLayerRef[] {
  return group.members.map((m) => ({
    id: m.id,
    title: m.title,
    uri: m.uri,
    path: m.path,
    format: m.format,
    layerName: m.layerName,
  }));
}

/**
 * The format a layer group shows and drops as. Layers that were all downloaded
 * from the Discovery Catalog show their own format, as each layer's row does
 * (#586); an import shows its file's, which its id says. A GTFS feed is always
 * a download and always shows GTFS: its tables' Parquet says nothing about it.
 * Mirrors the backend ``build_layer_group_item``.
 */
export function layerGroupFormat(group: DatasetPaletteGroup): DatasetFormat {
  const kind = layerGroupKind(group.groupId);
  if (kind === "gtfs") return kind;
  const [first] = group.members;
  if (first && group.members.every((m) => m.discoverySource)) return first.format;
  return kind;
}

/**
 * Drag payload for a layer group (an OSM PBF or a GeoPackage import, the layers
 * of one Discovery download, a GTFS feed, NetCDF variables), from the canvas
 * palette's group row or the Data Catalog drawer's group card. Dropping it
 * creates a single node representing the *whole* group: the loader reads every
 * layer, and the node references the real per-layer dataset ids (via
 * ``groupLayers``) so the saved spec never carries the synthetic group id. The
 * group id is kept only as the drag's identity/linkage marker, and its prefix
 * gives the ``curio://`` scheme.
 */
export function createLayerGroupDragPayload(group: {
  groupId: string;
  title: string;
  format: DatasetFormat;
  origin?: DatasetOrigin;
  layers: DatasetGroupLayerRef[];
}): DatasetDragPayload {
  const kind = layerGroupKind(group.groupId);
  return {
    datasetId: group.groupId,
    title: group.title,
    uri: `curio://${kind}/${group.groupId}`,
    path: null,
    format: group.format,
    origin: group.origin ?? "imported",
    loaderSnippet: osmGroupLoaderSnippet(group.layers),
    groupLayers: group.layers,
  };
}

/** Drag payload for a palette group row (see {@link createLayerGroupDragPayload}). */
export function createOsmGroupDragPayload(
  group: DatasetPaletteGroup,
): DatasetDragPayload {
  return createLayerGroupDragPayload({
    groupId: group.groupId,
    title: group.title,
    format: layerGroupFormat(group),
    layers: osmGroupLayerRefs(group),
  });
}

/** Which persisted timestamp the palette sorts entries by. */
export type DatasetPaletteSortKey = "importedAt" | "installedAt";

/** The sort timestamp for an entry under ``key`` — a group's representative
 * value, or the dataset's own persisted metadata. ``null`` when unknown. */
export function entrySortValue(
  entry: DatasetPaletteEntry,
  key: DatasetPaletteSortKey,
): string | null {
  if (entry.kind === "group") return entry[key];
  return key === "installedAt"
    ? datasetInstalledAt(entry.dataset)
    : datasetImportedAt(entry.dataset);
}

/**
 * Order palette entries by a persisted timestamp, most recent first, read as a
 * time (``compareCatalogDates``). Groups sort as a single unit by their
 * representative value. An entry whose timestamp is missing or unreadable is
 * the oldest. Entries at the same time keep the order they came in, the
 * catalog listing's (``_sort_catalog_items``). Pure: returns a new array and
 * never reads UI state.
 */
export function sortDatasetPaletteEntries(
  entries: DatasetPaletteEntry[],
  key: DatasetPaletteSortKey,
): DatasetPaletteEntry[] {
  return entries
    .map((entry, index) => ({ entry, index, value: entrySortValue(entry, key) }))
    .sort((a, b) => compareCatalogDates(b.value, a.value) || a.index - b.index)
    .map((wrapped) => wrapped.entry);
}
