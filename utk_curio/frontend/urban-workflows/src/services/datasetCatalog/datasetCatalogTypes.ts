export type DatasetOrigin = "source_node" | "computed" | "imported" | "hub";

export type DatasetFormat = "csv" | "geojson" | "json" | "parquet" | "geotiff" | "shp" | "bundle";

export type DatasetSortMode = "recent" | "name";

/** A dataflow that uses a dataset, as returned by ``GET /datasets/<id>/usage``. */
export interface DatasetDataflowUsageRef {
  dataflowId: string;
  dataflowName: string | null;
  nodeCount: number;
  /** Consumer nodes within this dataflow (downstream of the dataset). */
  nodes?: Array<{ nodeId: string; nodeType?: string | null }>;
}

export interface DatasetSchemaField {
  name: string;
  type: string;
  nullable?: boolean;
  sample?: string | number | boolean | null;
}

export interface DatasetSchema {
  fields: DatasetSchemaField[];
  geometryType?: string | null;
  crs?: string | null;
  /** Present on ``bundle`` datasets — one entry per tuple/output part. */
  bundleParts?: Array<{ label?: string; format?: string; kind?: string }>;
}

export interface DatasetLoaderSnippet {
  language: "python";
  imports: string[];
  code: string;
  pathVariable: string;
  /** Variable name that should be returned from a standalone Data Loading node (e.g. "df"). */
  returnVariable?: string | null;
}

export interface DatasetCatalogItem {
  id: string;
  title: string;
  description?: string;
  origin: DatasetOrigin;
  format: DatasetFormat;
  uri: string;
  path?: string | null;
  /** Folder name in the dataset store (e.g. ``data.urbanlab.chicago-boundary@1``). Present for catalog (hub) datasets. */
  dirName?: string | null;
  sizeBytes?: number | null;
  rowCount?: number | null;
  featureCount?: number | null;
  producerNodeId?: string | null;
  consumerNodeIds: string[];
  updatedAt: string;
  sourceLabel?: string | null;
  license?: string | null;
  tags: string[];
  schema?: DatasetSchema | null;
  loaderSnippet?: DatasetLoaderSnippet | null;
  installed?: boolean;
  /** True when the producer node has been re-executed since the dataset was last installed. */
  needsReinstall?: boolean;
  /** True when a computed dataset (origin="computed") has been published to the Data Catalog.
   * The origin field stays "computed" — use this flag to determine published state. */
  publishedToHub?: boolean;
}

export interface DatasetCatalogFacets {
  /** Per-origin counts from the API; ``computed`` includes hub-published node outputs (tags/description). */
  origin: Record<DatasetOrigin, number>;
  format: Record<DatasetFormat, number>;
}

export interface DatasetCatalogResponse {
  items: DatasetCatalogItem[];
  facets: DatasetCatalogFacets;
}

export interface DatasetPreviewPart {
  label: string;
  format: DatasetFormat;
  schema: DatasetSchema;
  rows: Record<string, unknown>[];
  rowLimit: number;
  offset: number;
  totalRows: number;
  truncated: boolean;
  unsupported?: boolean;
  message?: string;
  kind?: string;
}

export interface DatasetPreviewResponse {
  schema: DatasetSchema;
  rows: Record<string, unknown>[];
  rowLimit: number;
  offset: number;
  totalRows: number;
  truncated: boolean;
  unsupported?: boolean;
  message?: string;
  /** Multi-part tuple / ``outputs`` installs. */
  bundle?: boolean;
  parts?: DatasetPreviewPart[];
}

export interface DatasetPreviewQuery {
  dataflowId?: string | null;
  liveOutputs?: DatasetCatalogQuery["liveOutputs"];
  offset?: number;
  rowLimit?: number;
  /** Bundle datasets only: paginate a single part (its rows at ``offset``). */
  part?: number;
}

export interface DatasetCatalogQuery {
  dataflowId?: string | null;
  search?: string;
  format?: DatasetFormat | "";
  origin?: DatasetOrigin | "";
  sort?: DatasetSortMode;
  includeHub?: boolean;
  /** Current (possibly unsaved) node outputs to show as computed datasets immediately. */
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
}

export interface DatasetDragPayload {
  datasetId: string;
  title: string;
  uri: string;
  path?: string | null;
  format: DatasetFormat;
  origin?: DatasetOrigin;
  loaderSnippet?: DatasetLoaderSnippet | null;
}

/**
 * Origin marker stamped on a canvas node that was *created* from the dataset
 * palette (drag-to-create). It is the linkage back to the installed dataset
 * listing and is what distinguishes a dataset-palette node from a plain code
 * node that merely references a dataset (``applyDatasetToNodeData``). Present
 * only on palette-created nodes — never set by drop-onto-existing-node.
 */
export interface DatasetNodeSource {
  datasetId: string;
  title: string;
  format: DatasetFormat;
  origin: DatasetOrigin;
}

/** User-facing provenance: only Imported vs Computed (API still uses hub/source_node). */
export const DATASET_ORIGIN_LABEL: Record<DatasetOrigin, string> = {
  source_node: "Imported",
  computed: "Computed",
  imported: "Imported",
  hub: "Imported",
};

/** Binary provenance for chips and filters (maps hub/source_node → imported). */
export type DatasetProvenanceKind = "computed" | "imported";

export function datasetProvenanceKind(
  origin: DatasetOrigin,
  _format?: DatasetFormat,
): DatasetProvenanceKind {
  // Provenance is authoritative from ``origin`` (mirrors the backend facet and
  // DATASET_ORIGIN_LABEL). Don't infer from format: ``.parquet`` is also an
  // accepted *import* format, so a user-imported parquet (origin "imported")
  // must read "Imported", not "Computed".
  return origin === "computed" ? "computed" : "imported";
}

export function datasetProvenanceLabel(
  origin: DatasetOrigin,
  format?: DatasetFormat,
): string {
  return datasetProvenanceKind(origin, format) === "computed" ? "Computed" : "Imported";
}

/** True when the dataset is listed in the committed catalog (``hub``) or marked published from a project. */
export function isDatasetPublishedToCatalog(dataset: DatasetCatalogItem): boolean {
  return dataset.origin === "hub" || dataset.publishedToHub === true;
}

/** Installed into the current project/dataflow — computed, imported, or a
 * hub copy — and usable as a dataset node. Publishing a dataset to the Data
 * Catalog does NOT uninstall its local copy, so published-and-installed
 * datasets still count here (the bug in #140 was excluding them). Ephemeral
 * live outputs and merely-browsable hub entries have ``installed`` falsy and
 * are excluded. */
export function isUserInstalledDataset(dataset: DatasetCatalogItem): boolean {
  return dataset.installed === true;
}

/**
 * True when the dataset actually originated from the Data Catalog — either the
 * canonical ``hub`` entry or a copy installed into the project (``imported``).
 * Computed node outputs always keep ``origin="computed"`` (even after auto-install
 * or publishing), so they are excluded here and must not be labelled as installed
 * from the catalog.
 */
export function isDatasetFromCatalog(dataset: DatasetCatalogItem): boolean {
  return dataset.origin === "hub" || dataset.origin === "imported";
}

/**
 * True only when the dataset was genuinely *installed* into the project from the
 * Data Catalog. A catalog entry that is merely browsable (``installed`` falsy,
 * Availability "Available") must not be described as installed.
 */
export function isDatasetInstalledFromCatalog(dataset: DatasetCatalogItem): boolean {
  return dataset.installed === true && isDatasetFromCatalog(dataset);
}

/** Live node output in the current session that is not yet in the user dataset store. */
export function isProjectSessionDataset(dataset: DatasetCatalogItem): boolean {
  return dataset.origin === "computed" && dataset.installed !== true;
}

/** Total for the “Imported” rail: ``imported`` + ``hub`` + ``source_node`` facet buckets (hub rows bucketed as computed are excluded). */
export function facetImportedTotal(
  originCounts: DatasetCatalogFacets["origin"],
): number {
  return originCounts.imported + originCounts.hub + originCounts.source_node;
}

/** Normalize legacy publisher / provenance strings. */
export function sanitizePublisherLabel(raw: string | null | undefined): string {
  if (raw == null) return "";
  const t = String(raw).trim();
  if (!t) return "";
  const lower = t.toLowerCase();
  if (lower === "data hub" || lower === "data catalog") return "Imported";
  if (lower === "current dataflow" || lower === "current workflow") return "Computed";
  return t.replace(/\bdata\s*hub\b/gi, "Imported");
}

/** Subtitle under the title on dataset cards / browse rows — only Imported vs Computed. */
export function datasetListSourceCaption(dataset: DatasetCatalogItem): string {
  return datasetProvenanceLabel(dataset.origin, dataset.format);
}

export const DATASET_FORMAT_LABEL: Record<DatasetFormat, string> = {
  csv: "CSV",
  geojson: "GeoJSON",
  json: "JSON",
  parquet: "Parquet",
  geotiff: "GeoTIFF",
  shp: "SHP",
  bundle: "Bundle",
};
