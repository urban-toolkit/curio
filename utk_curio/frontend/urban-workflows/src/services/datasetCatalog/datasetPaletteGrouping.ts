import type {
  DatasetCatalogItem,
  DatasetDragPayload,
  DatasetGroupLayerRef,
} from "./datasetCatalogTypes";
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

/** Latest (max) non-empty value produced by ``pick`` across members, or null. */
function latest(
  members: DatasetCatalogItem[],
  pick: (m: DatasetCatalogItem) => string | null | undefined,
): string | null {
  let max: string | null = null;
  for (const m of members) {
    const value = pick(m);
    if (value && (max === null || value > max)) max = value;
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
 * Drag payload for a multilayer OSM PBF group parent. Dropping it creates a
 * single node representing the *whole* import: the loader reads every layer, and
 * the node references the real per-layer dataset ids (via ``groupLayers``) so the
 * saved spec never carries the synthetic group id. The group id is kept only as
 * the drag's identity/linkage marker.
 */
export function createOsmGroupDragPayload(
  group: DatasetPaletteGroup,
): DatasetDragPayload {
  const layers = osmGroupLayerRefs(group);
  return {
    datasetId: group.groupId,
    title: group.title,
    uri: `curio://osm/${group.groupId}`,
    path: null,
    format: "osm",
    origin: "imported",
    loaderSnippet: osmGroupLoaderSnippet(layers),
    groupLayers: layers,
  };
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
 * Order palette entries by a persisted timestamp, most-recent first. Groups sort
 * as a single unit by their representative value. Entries whose timestamp is
 * unknown sort last; ties keep their original (stable) order. Pure — returns a
 * new array and never reads UI state.
 */
export function sortDatasetPaletteEntries(
  entries: DatasetPaletteEntry[],
  key: DatasetPaletteSortKey,
): DatasetPaletteEntry[] {
  return entries
    .map((entry, index) => ({ entry, index, value: entrySortValue(entry, key) }))
    .sort((a, b) => {
      if (a.value === b.value) return a.index - b.index;
      if (a.value === null) return 1;
      if (b.value === null) return -1;
      return a.value < b.value ? 1 : -1;
    })
    .map((wrapped) => wrapped.entry);
}
