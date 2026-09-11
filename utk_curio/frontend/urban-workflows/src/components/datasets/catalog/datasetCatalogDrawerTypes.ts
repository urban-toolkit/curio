import type { DatasetOrigin } from "../../../services/datasetCatalog";

/**
 * "featured" is gone. It was an arbitrary top-6 slice of "from the hub, or
 * already installed" - no curation behind it, no way for anything to become
 * featured, and it sat first so it was what the drawer opened on for anyone who
 * had not switched tabs. The Node drawer dropped its Featured and Updates tabs
 * for the same reason. What remains are real content scopes: everything, the
 * ones in this project, and the ones nodes produced.
 */
export type DrawerTab = "browse" | "installed" | "computed";

export const TAB_LABEL: Record<DrawerTab, string> = {
  browse: "Browse all",
  installed: "In project",
  computed: "Computed",
};

export function tabOrigin(_tab: DrawerTab): DatasetOrigin | "" {
  return "";
}
