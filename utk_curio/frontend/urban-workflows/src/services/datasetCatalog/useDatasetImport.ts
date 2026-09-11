import { useCallback, useRef, useState } from "react";
import { notifyDatasetCatalogRefresh } from "./datasetCatalogApi";
import type { DatasetCatalogItem } from "./datasetCatalogTypes";

/**
 * The ONE dataset-import pathway, shared by the Data Catalog drawer's footer
 * and the Data Catalog page's header.
 *
 * Both surfaces do the same three things and must keep doing them together:
 * register the file, fan out a catalog-refresh notification (the palette
 * provider and the dropdown hold separate caches and will not see the new row
 * otherwise), and report the count, because one OSM PBF registers one dataset
 * per layer and "Registered file.osm.pbf" would undercount it by a lot.
 *
 * Import is register-only on BOTH surfaces: it adds an account-level catalog
 * item and attaches it to no dataflow. A node/dataflow link is created only by
 * an explicit install. That is why the page can offer it at all - the page has
 * no dataflow, and this import never needed one.
 */
export interface DatasetImportOptions {
  /** ``importDataset`` from ``useDatasetCatalog``; it reloads the listing. */
  importDataset: (file: File) => Promise<DatasetCatalogItem | null | undefined>;
  showToast: (message: string, kind: "success" | "error") => void;
  /** Optional in-list placeholder, which only the drawer renders. */
  onBegin?: (key: string, label: string) => void;
  onEnd?: (key: string) => void;
}

export function useDatasetImport({
  importDataset,
  showToast,
  onBegin,
  onEnd,
}: DatasetImportOptions) {
  const [importing, setImporting] = useState(false);
  // A second pick while the first is still in flight would double-register the
  // file and race the two reloads.
  const inFlight = useRef(false);

  const importFile = useCallback(
    async (file: File) => {
      if (inFlight.current) return null;
      inFlight.current = true;
      setImporting(true);
      // No catalog row exists yet for a brand-new import, so the placeholder is
      // the only in-list feedback until it lands.
      onBegin?.("import", file.name);
      try {
        const imported = await importDataset(file);
        notifyDatasetCatalogRefresh();
        const count =
          (imported as { importedDatasetCount?: number } | null | undefined)
            ?.importedDatasetCount ?? 1;
        showToast(
          count > 1
            ? `Registered ${count} datasets from ${file.name} in the Data Catalog.`
            : `Registered ${file.name} in the Data Catalog.`,
          "success",
        );
        return imported ?? null;
      } catch (err) {
        showToast((err as Error)?.message || "Could not import dataset.", "error");
        return null;
      } finally {
        onEnd?.("import");
        inFlight.current = false;
        setImporting(false);
      }
    },
    [importDataset, showToast, onBegin, onEnd],
  );

  return { importing, importFile };
}
