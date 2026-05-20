import { PackPayload } from "../../../api/packsApi";

/** Tab identifiers for the catalog browse rail. */
export type Tab = "all" | "data" | "computation" | "vis" | "installed";

/** Human-readable label for each tab, used in the rail and as aria labels. */
export const CATEGORY_LABELS: Record<Tab, string> = {
  all: "All packs",
  data: "Data",
  computation: "Computation",
  vis: "Visualisation",
  installed: "Installed",
};

/** Category IDs that map to the "vis" tab. */
const VIS_CATEGORIES = new Set(["vis_grammar", "vis_simple"]);

/**
 * Returns true when `pack` should appear under the given `tab`.
 * The "installed" tab relies on `pack.installed` being set by the loader.
 */
export function matchesTab(pack: PackPayload, tab: Tab): boolean {
  if (tab === "all") return true;
  if (tab === "installed") return !!pack.installed;
  if (tab === "vis") return pack.kinds.some((k) => VIS_CATEGORIES.has(k.category));
  return pack.kinds.some((k) => k.category === tab);
}

