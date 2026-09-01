export type DatasetOrigin = "source_node" | "computed" | "imported" | "hub";

export type DatasetFormat = "csv" | "geojson" | "json" | "parquet" | "geotiff" | "shp" | "bundle" | "osm";

export type DatasetSortMode = "recent" | "name";

/**
 * File extensions the dataset importer can ingest. Mirrors the backend
 * ``SUPPORTED_SUFFIXES`` (``datasets/domain/constants.py``) plus OSM PBF, which
 * the backend converts to a single GeoParquet on import
 * (``install/osm_pbf.py``). Keep in lockstep with the backend.
 */
export const IMPORTABLE_DATASET_EXTENSIONS = [
  ".csv",
  ".geojson",
  ".json",
  ".parquet",
  ".tif",
  ".tiff",
  ".shp",
  ".pbf",
  ".osm.pbf",
] as const;

/** ``accept`` attribute for the Data Catalog import picker. */
export const DATASET_IMPORT_ACCEPT = IMPORTABLE_DATASET_EXTENSIONS.join(",");

/** Prefix of a synthetic OSM layer-group id (mirrors the backend). The group
 * is a bundle-shaped catalog entry whose id addresses all its member layers. */
export const OSM_GROUP_ID_PREFIX = "osm.";

/** True when an id addresses a synthetic OSM layer group. */
export function isOsmGroupId(id: string | null | undefined): boolean {
  return typeof id === "string" && id.startsWith(OSM_GROUP_ID_PREFIX);
}

/**
 * A dataset install that is currently in flight, surfaced as an "Installing…"
 * placeholder in the dataset palette and Data Catalog drawer until the real
 * installed row lands (or the operation fails). Volatile, session-only state.
 */
export interface PendingInstall {
  /** Stable key: producer node id (auto-install), datasetId (manual), or "import". */
  key: string;
  /** Human label shown on the placeholder (node display name / dataset title / file name). */
  label: string;
  /** Producer node id when the install comes from a node execution. */
  producerNodeId?: string;
  /** Catalog dataset id when known (manual install of a listed dataset). */
  datasetId?: string;
  /** Dataset format when known, so the placeholder can mirror the real row's chrome. */
  format?: DatasetFormat;
  /** Epoch ms when the install started (used only for the safety timeout). */
  startedAt: number;
}

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
  /** Name of the generated data file. For computed datasets the ``title``
   * carries the producing node's name; the original filename is kept here as
   * metadata (the subtitle now shows ``dirName`` — see {@link datasetSubtitle}). */
  fileName?: string | null;
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
  /** Node type of the producing node, resolved across the user's projects (not
   * just the open dataflow) so a computed dataset opened from a dataflow that
   * only imported it can still label its generating node. */
  producerNodeType?: string | null;
  /** Dataflow that actually produced this computed dataset, when it differs from
   * the dataflow the details page was opened from. */
  producerDataflowId?: string | null;
  producerDataflowName?: string | null;
  /** Upstream inputs (producer nodes / input datasets) feeding the producing
   * node, persisted as lineage on computed datasets. Each entry is
   * ``{ nodeId, nodeType? }`` and/or ``{ datasetId }``. */
  upstreamInputs?: Array<{
    nodeId?: string;
    nodeType?: string | null;
    datasetId?: string;
  }>;
  /** Shared id stamped on every layer of one multilayer import (OSM PBF), so
   * the dataset palette can fold the layers into a single group row. Absent on
   * a dataset that is not part of such an import. Emitted by the backend (see
   * ``catalog_item.py``); `datasetPaletteGrouping` reads it. */
  groupId?: string | null;
  /** This dataset's layer within a multilayer import, e.g. ``buildings``. Used
   * as the row label under the group parent, and as the layer name in the
   * loader's drag payload. */
  layerName?: string | null;
  consumerNodeIds: string[];
  /** Real count of nodes consuming this dataset, summed across the user's
   * dataflows — the source of truth for the "N nodes consume" browse label.
   * Derived server-side from the dependency graph (see backend
   * ``_consumer_counts``); ``consumerNodeIds`` is a canvas-binding array that is
   * empty in persisted specs and must not be used for this count. Optional so
   * older/detail payloads without it default to 0 in the UI. */
  consumerNodeCount?: number;
  /** When the dataset *record* was created/imported in Curio. Distinct from
   * ``sourceUpdatedAt`` (the original file's date). Optional so older payloads
   * fall back to ``updatedAt`` in the UI. */
  createdAt?: string | null;
  /** When the dataset *record* was last changed in Curio. */
  updatedAt: string;
  /** When the dataset was installed into the current dataflow (from the project
   * ref). Persisted metadata, distinct from ``createdAt`` (import time). Used to
   * sort the palette by install time. ``null``/absent when not installed. */
  installedAt?: string | null;
  /** Last-modified date of the *original source file* (from the browser's
   * ``File.lastModified`` at import), distinct from the Curio record dates.
   * ``null``/absent when unknown (older imports, programmatic imports). */
  sourceUpdatedAt?: string | null;
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
  /** Number of catalog datasets produced by a single import. 1 for ordinary
   * files; N for an OSM PBF, which registers one dataset per layer (this item is
   * the first — the rest appear via the catalog listing on refresh). */
  importedDatasetCount?: number;
  /** On a synthetic OSM group entry (``format: "osm"``, id = group id): the
   * real per-layer dataset ids, so the client installs/uninstalls each member. */
  groupLayerIds?: string[];
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
  /** Fold the per-layer datasets of an OSM import into one bundle-shaped group
   * entry (catalog drawer). Off elsewhere (e.g. palette) so each layer stays a
   * separate, draggable dataset. */
  groupOsm?: boolean;
  /** Current (possibly unsaved) node outputs to show as computed datasets immediately. */
  liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
}

/** One layer of a dragged OSM PBF group — a real, installed layer dataset. */
export interface DatasetGroupLayerRef {
  id: string;
  title: string;
  uri: string;
  path?: string | null;
  format: DatasetFormat;
  layerName?: string | null;
}

export interface DatasetDragPayload {
  datasetId: string;
  title: string;
  uri: string;
  path?: string | null;
  format: DatasetFormat;
  origin?: DatasetOrigin;
  loaderSnippet?: DatasetLoaderSnippet | null;
  /** Present only when dragging a multilayer OSM PBF group parent: the real
   * per-layer datasets the created node loads. The node references these (not
   * the synthetic group id) so the saved spec never carries a phantom ref. */
  groupLayers?: DatasetGroupLayerRef[];
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

/**
 * True when a string looks like a raw node-execution output filename rather than
 * a human-chosen name — an epoch-ms timestamp prefix (e.g. ``1782757759504
 * 31640Bba``) and/or a trailing data-file extension (``.json``/``.Json``, csv,
 * parquet, …). Real node/dataset names never look like this. Used so a generated
 * filename is never shown as a title even when it isn't byte-identical to
 * ``fileName`` (e.g. a hub copy whose stored file is ``….json.zlib``).
 */
const GENERATED_DATA_FILE_RE =
  /(^\d{10,}[\s._-])|\.(json|csv|parquet|geojson|shp|geotiff|zlib)$/i;

export function isGeneratedDataFileName(name: string | null | undefined): boolean {
  const n = name?.trim();
  return !!n && GENERATED_DATA_FILE_RE.test(n);
}

/**
 * Display form of a computed dataset's store folder.
 *
 * Computed datasets are stored under a dataflow-namespaced id
 * (``computed.<dataflowId>.<nodeId>@<major>``) so the same node id reused in two
 * dataflows stays distinct on disk. That dataflow segment is an opaque project
 * UUID and must never surface in the UI: for display we drop it and keep the
 * node-scoped folder (``computed.<nodeId>@<major>``), which is the stable,
 * readable identifier the catalog showed before namespacing. Legacy
 * (un-namespaced) computed folders and non-computed folders are returned
 * unchanged.
 */
export function displayFolderName(
  dirName: string | null | undefined,
): string | null | undefined {
  const d = dirName?.trim();
  if (!d) return dirName;
  // ``@<major>`` is OPTIONAL (a dataset ID never carries it, only a dirName
  // does) — the Python twin ``display_folder_name`` agrees; requiring it here
  // leaked raw namespaced ids (with the dataflow UUID) into titles (#175).
  const m = d.match(/^computed\.(.+?)(@\d+)?$/);
  if (!m) return dirName;
  const segments = m[1].split(".");
  if (segments.length < 2) return dirName; // legacy ``computed.<node>``
  const nodeSegment = segments[segments.length - 1];
  return `computed.${nodeSegment}${m[2] ?? ""}`;
}

/**
 * The clean, user-facing display name for a dataset — the single source of
 * truth for *which* field to render as a dataset's title.
 *
 * ``title`` holds the real name for every origin: a catalog/imported dataset's
 * published name, and — for computed node outputs — the producing node's canvas
 * name (the backend stamps it at install time). The generated output filename
 * lives in ``fileName`` and is shown as a subtitle, not the title.
 *
 * A computed output with no captured node name carries the generated filename as
 * its ``title`` (matching ``fileName``, or just *looking* like a generated file
 * name — e.g. a stale hub copy browsed from another dataflow). That raw filename
 * must never be the title, so we fall back to the store folder (``dirName``) —
 * never to ``fileName``. Same fallback applies if ``title`` is blank.
 *
 * Use this everywhere a dataset title is rendered (palette, catalog browse,
 * detail panel, breadcrumb) instead of reading ``title`` directly, so the
 * displayed name stays consistent across the UI.
 */
export function datasetDisplayTitle(
  dataset: Pick<
    DatasetCatalogItem,
    "origin" | "title" | "dirName" | "fileName" | "sourceLabel"
  >,
): string {
  const title = dataset.title?.trim();
  // Display the node-scoped folder, never the dataflow-namespaced store id
  // (whose dataflow segment is an opaque project UUID).
  const dirName = displayFolderName(dataset.dirName)?.trim();
  const isComputed = isDatasetComputed(dataset);
  // For a computed dataset, the title is a generated filename when it equals
  // ``fileName`` or simply looks like one — in either case it must not be shown.
  const isGeneratedFilename =
    isComputed &&
    !!title &&
    (title === dataset.fileName?.trim() || isGeneratedDataFileName(title));
  if (!title || isGeneratedFilename) {
    return dirName || dataset.title;
  }
  return title;
}

/**
 * Strip a trailing ``.json`` / ``.Json`` extension from a generated data-file
 * name. Case-insensitive and limited to the ``.json`` extension computed outputs
 * are serialized as; names without it (or ``null``/``undefined``) are returned
 * unchanged.
 */
export function stripDataFileExtension(
  name: string | null | undefined,
): string | null | undefined {
  if (name == null) return name;
  return name.replace(/\.json$/i, "");
}

/**
 * Secondary line shown beneath {@link datasetDisplayTitle}: the dataset's store
 * folder (``dirName``, e.g. ``computed.whatif-data@1``), so the subtitle is a
 * stable, meaningful identifier rather than the raw generated filename.
 *
 * When the ``dirName`` would merely repeat the displayed title — a computed
 * dataset with no captured node name falls back to ``dirName`` for its title —
 * we instead show the generated filename (with its ``.json`` extension stripped)
 * so the subtitle still adds information rather than echoing the title.
 *
 * Returns ``null``/``undefined`` when there is nothing to show (e.g. a
 * session-only computed output not yet in the store), so callers can omit the line.
 */
export function datasetSubtitle(
  dataset: Pick<DatasetCatalogItem, "origin" | "title" | "dirName" | "fileName" | "sourceLabel">,
): string | null | undefined {
  // Show the node-scoped folder, never the dataflow-namespaced store id.
  const displayed = displayFolderName(dataset.dirName);
  const dirName = displayed?.trim();
  if (dirName && dirName === datasetDisplayTitle(dataset).trim()) {
    return stripDataFileExtension(dataset.fileName);
  }
  return displayed; // preserves null/undefined when there is no store folder
}

/** True when the dataset is listed in the committed catalog (``hub``) or marked published from a project. */
export function isDatasetPublishedToCatalog(dataset: DatasetCatalogItem): boolean {
  return dataset.origin === "hub" || dataset.publishedToHub === true;
}

/** True when the dataset comes from a node execution - computed*/
export function isDatasetComputed(
  dataset: Pick<DatasetCatalogItem, "origin"> & { sourceLabel?: string | null },
): boolean {
  return dataset.origin === "computed" || dataset.sourceLabel?.toLowerCase() === "computed";
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

/**
 * Is this dataset the user's own, rather than something the installation shipped?
 *
 * Publishing means "put this into the catalog everyone on this Curio shares".
 * That only makes sense for something the user made or brought: their upload,
 * or an output one of their nodes computed. A dataset that came FROM the shared
 * catalog is already there, and republishing it just writes a duplicate - the
 * backend has no guard against it, so the affordance has to.
 *
 * Told apart by the store folder, the same signal the backend's uninstall uses
 * (``_remove_orphaned_imported_store_dir`` keys on ``imported.``): catalog
 * datasets land under their publisher's id (``data.urbanlab.…@1``), uploads
 * under ``imported.…`` and node outputs under ``computed.…``. ``origin`` cannot
 * answer this - installing a catalog dataset flips it from ``hub`` to
 * ``imported``, so an installed catalog row and an upload look identical there.
 */
export function isUserOwnedDataset(dataset: DatasetCatalogItem): boolean {
  const dir = String(dataset.dirName ?? "");
  if (dir.startsWith("imported.") || dir.startsWith("computed.")) return true;
  // A live node output that has not been persisted yet has no folder at all,
  // and is still the user's own.
  if (!dir && (dataset.origin === "computed" || dataset.origin === "source_node")) {
    return true;
  }
  return false;
}

/**
 * Did this dataset come from the catalog everyone on this Curio shares?
 *
 * The positive counterpart to {@link isUserOwnedDataset}, and deliberately not
 * its negation. Publish must fail CLOSED - never offer to publish unless the
 * thing is provably the user's - while Delete must fail OPEN, because hiding it
 * on a row we simply cannot classify would take away a working action. So
 * Delete asks "do we KNOW this came from the catalog", which a `data.*` store
 * folder or a still-`hub` origin answers.
 */
export function isSharedCatalogDataset(dataset: DatasetCatalogItem): boolean {
  if (dataset.origin === "hub") return true;
  return String(dataset.dirName ?? "").startsWith("data.");
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
  osm: "OSM PBF",
};
