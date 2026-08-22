import type { DatasetOrigin } from "../../../services/datasetCatalog";

export type DrawerTab = "featured" | "browse" | "installed" | "computed";

export const TAB_LABEL: Record<DrawerTab, string> = {
  featured: "Featured",
  browse: "Browse all",
  installed: "In dataflow",
  computed: "Computed",
};

export function tabOrigin(_tab: DrawerTab): DatasetOrigin | "" {
  return "";
}
