import type { DatasetCatalogItem } from "./datasetCatalogTypes";

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

/** Latest (max) non-empty value of ``field`` across members, or ``null``. */
function latest(
  members: DatasetCatalogItem[],
  field: "updatedAt",
): string | null {
  let max: string | null = null;
  for (const m of members) {
    const value = m[field];
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
      out.push({ kind: "group", groupId, title: groupId, members, updatedAt: null });
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
      updatedAt: latest(members, "updatedAt"),
    };
  }

  return out;
}
