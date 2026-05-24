import { PackagePayload } from "../../../api/packagesApi";
import { SortMode } from "./packageTypes";

/**
 * Returns a 1–2 character initials string from a package display name.
 * Used as a fallback icon inside PackageCard.
 */
export function packageInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const words = trimmed.split(/\s+/);
  if (words.length >= 2) return (words[0]![0]! + words[1]![0]!).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

/**
 * Returns the primary human-readable category for a package.
 * Collapses all "vis*" categories to a single "vis" label.
 */
export function primaryCategory(package: PackagePayload): string {
  const cat = package.kinds[0]?.category;
  if (!cat) return "package";
  if (cat.startsWith("vis")) return "vis";
  return cat;
}

/**
 * Returns a sorted copy of the supplied package array.
 * "new" sorts by creation time (newest first, then alphabetically).
 * "name" sorts alphabetically (case-insensitive).
 */
export function sortPackages(packages: PackagePayload[], mode: SortMode): PackagePayload[] {
  const next = [...packages];
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
 * Returns true when the package matches a free-text search query
 * against its name, publisher, description and packageId fields.
 */
export function matchesSearch(package: PackagePayload, query: string): boolean {
  if (!query.trim()) return true;
  const q = query.trim().toLowerCase();
  return (
    package.name.toLowerCase().includes(q) ||
    package.publisher.toLowerCase().includes(q) ||
    package.description.toLowerCase().includes(q) ||
    package.packageId.toLowerCase().includes(q)
  );
}

