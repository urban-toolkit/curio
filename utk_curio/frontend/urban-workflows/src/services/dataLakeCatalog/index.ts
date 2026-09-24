export * from "./dataLakeCatalogTypes";
export * from "./dataLakeCatalogCache";
export * from "./dataLakeCatalogHooks";
export { dataLakeCatalogApi, notifyLakeCatalogRefresh } from "./dataLakeCatalogApi";

/**
 * The cross-catalog seam.
 *
 * A finished download is a new **Data Catalog** dataset, so the surface that
 * has to be invalidated belongs to the other catalog: its drawer, its palette,
 * its browse page, and the same in every other open tab. Re-exported here so a
 * lake page does not have to reach across into the datasets service to say so
 * - and so it is obvious that not calling it is the bug where a download
 * succeeds and the dataset appears to be missing.
 */
export { notifyDatasetCatalogRefresh } from "../datasetCatalog";
