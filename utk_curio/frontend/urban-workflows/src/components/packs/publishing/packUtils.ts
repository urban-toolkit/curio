import { PackPayload } from "../../../api/packsApi";
import { SortMode } from "./packTypes";

/**
 * Returns a 1–2 character initials string from a pack display name.
 * Used as a fallback icon inside PackCard.
 */
export function packInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const words = trimmed.split(/\s+/);
  if (words.length >= 2) return (words[0]![0]! + words[1]![0]!).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

/**
 * Returns the primary human-readable category for a pack.
 * Collapses all "vis*" categories to a single "vis" label.
 */
export function primaryCategory(pack: PackPayload): string {
  const cat = pack.kinds[0]?.category;
  if (!cat) return "pack";
  if (cat.startsWith("vis")) return "vis";
  return cat;
}

/**
 * Returns a sorted copy of the supplied pack array.
 * "new" sorts by creation time (newest first, then alphabetically).
 * "name" sorts alphabetically (case-insensitive).
 */
export function sortPacks(packs: PackPayload[], mode: SortMode): PackPayload[] {
  const next = [...packs];
  if (mode === "name") {
    next.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    return next;
  }
  next.sort((a, b) => {
    const c = (b.createdAtMs ?? 0) - (a.createdAtMs ?? 0);
    if (c !== 0) return c;
    return a.dirName.localeCompare(b.dirName, undefined, { sensitivity: "base" });
  });
  return next;
}

/**
 * Returns true when the pack matches a free-text search query
 * against its name, publisher, description and packId fields.
 */
export function matchesSearch(pack: PackPayload, query: string): boolean {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return (
    pack.name.toLowerCase().includes(q) ||
    pack.publisher.toLowerCase().includes(q) ||
    pack.description.toLowerCase().includes(q) ||
    pack.packId.toLowerCase().includes(q)
  );
}

