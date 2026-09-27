/**
 * The Data Lake Catalog's wire types.
 *
 * Mirrors `backend/app/datalakes/schemas/payloads.py`, which builds every row
 * by explicit allowlist. Keep the two in step: a field that exists on the
 * backend manifest but not in that builder never reaches here, which is
 * deliberate - it is how a credential cannot leak into a response.
 */

/** Matches `PROVIDER_TYPES` in `datalakes/domain/manifest.py`: the portal
 *  types, then the storage types. */
export type LakeProviderType =
  | "socrata"
  | "ckan"
  | "arcgis"
  | "wfs"
  | "direct"
  | "folder"
  | "s3"
  | "huggingface";

/** Matches `STORAGE_PROVIDER_TYPES`: sources that declare their resources. */
export const STORAGE_PROVIDER_TYPES: readonly LakeProviderType[] = ["folder", "s3", "huggingface"];

/** A `portal` is searched for its datasets; a `storage` source declares them. */
export type LakeSourceKind = "portal" | "storage";

/** Matches `RESOURCE_KINDS`. `table` is copied; every other kind is a
 *  collection, referenced where its files are. */
export type LakeResourceKind =
  | "table"
  | "rasters"
  | "frames"
  | "images"
  | "videos"
  | "media"
  | "audio";

/** Matches `KIND_LABEL` in `datalakes/application/scan.py`. */
export const LAKE_RESOURCE_KIND_LABEL: Record<LakeResourceKind, string> = {
  table: "Table",
  rasters: "Rasters",
  frames: "Frames",
  images: "Images",
  videos: "Videos",
  media: "Photos and videos",
  audio: "Audio",
};

/** Matches `AUTH_MODES`. */
export type LakeAuthMode = "public" | "optional-token" | "required-token";

/**
 * Matches `LAKE_ACQUIRABLE_FORMATS`. A strict subset of the Data Catalog's
 * `DatasetFormat`: `shp` needs sibling files and `bundle` is a node output, so
 * neither is acquirable from a portal.
 */
export const LAKE_ACQUIRABLE_FORMATS = [
  "csv",
  "geojson",
  "json",
  "parquet",
  "geotiff",
] as const;
export type LakeAcquirableFormat = (typeof LAKE_ACQUIRABLE_FORMATS)[number];

export const LAKE_PROVIDER_LABEL: Record<LakeProviderType, string> = {
  socrata: "Socrata",
  ckan: "CKAN",
  arcgis: "ArcGIS",
  wfs: "OGC WFS",
  direct: "Direct URL",
  folder: "Folder",
  s3: "S3 bucket",
  huggingface: "Hugging Face",
};

export const LAKE_AUTH_LABEL: Record<LakeAuthMode, string> = {
  public: "Public",
  "optional-token": "Token optional",
  "required-token": "Token required",
};

export interface LakeSourceAuth {
  mode: LakeAuthMode;
  /** True only for `required-token`: this source cannot be used without one. */
  required: boolean;
  usesToken: boolean;
  /** The credential SLOT this source wants, never a value. Null when public. */
  secretId: string | null;
  /** Whether this account has that slot filled. */
  present: boolean;
  helpUrl: string | null;
}

export interface LakeSourceCapabilities {
  search: boolean;
  describe: boolean;
  download: boolean;
  formats: LakeAcquirableFormat[];
  maxDownloadBytes: number;
}

/** One resource a storage manifest declares, before any scan. */
export interface LakeDeclaredResource {
  resourceId: string;
  name: string;
  description: string;
  kind: LakeResourceKind;
  /** What lands in the Data Catalog: a table's file format, or `collection`. */
  format: string;
  /** A table's file format; null for a collection. */
  fileFormat: string | null;
  path: string;
  datasets: string;
  splitBy: string[];
  fields: { name: string; type: string }[];
}

export interface LakeSourceRow {
  sourceId: string;
  /** The versioned coordinate, `<sourceId>@<major>`. This is the route param. */
  dirName: string;
  name: string;
  version: string;
  description: string;
  publisher: string;
  homepage: string | null;
  license: string;
  tags: string[];
  /** Null when the source ships no icon, or its file is missing or oversized.
   *  The UI renders the shared lake glyph for a null. */
  iconUrl: string | null;
  provider: LakeProviderType;
  baseUrl: string;
  auth: LakeSourceAuth;
  capabilities: LakeSourceCapabilities;
  kind: LakeSourceKind;
  /** A storage source's declared resources; empty for a portal. */
  resources: LakeDeclaredResource[];
  createdAt: string | null;
  updatedAt: string | null;
}

export interface LakeCatalogFacets {
  provider: Record<string, number>;
  auth: Record<string, number>;
}

export interface LakeCatalogResponse {
  sources: LakeSourceRow[];
  facets: LakeCatalogFacets;
}

export interface LakeCatalogQuery {
  q?: string;
  provider?: LakeProviderType | "";
  auth?: LakeAuthMode | "";
}

export function isStorageSource(source: Pick<LakeSourceRow, "kind">): boolean {
  return source.kind === "storage";
}

/** The declared resource a storage row belongs to. A row's id is the
 *  resource's, or `<resource>@<field>=<value>` for one split value, or
 *  `<resource>/<relpath>` for one file. */
export function declaredResourceFor(
  source: Pick<LakeSourceRow, "resources">,
  resourceId: string,
): LakeDeclaredResource | undefined {
  const head = resourceId.split(/[@/]/, 1)[0];
  return (source.resources ?? []).find((r) => r.resourceId === head);
}

/** A source you can actually search. Narrower than `capabilities.search`
 *  alone, because a required token you do not hold also rules it out. */
export function isSearchable(source: LakeSourceRow): boolean {
  if (!source.capabilities.search) return false;
  return !source.auth.required || source.auth.present;
}

/** Why a source cannot be searched, phrased for a user. Null when it can. */
export function unsearchableReason(source: LakeSourceRow): string | null {
  if (!source.capabilities.search) {
    return `${source.name} has nothing to browse - paste a link to a file instead.`;
  }
  if (source.auth.required && !source.auth.present) {
    return `${source.name} needs a token before it can be searched.`;
  }
  return null;
}


// ── Live search ────────────────────────────────────────────────────────────

/** Why one portal's leg of a federated search did not return rows.
 *  Mirrors `LEG_STATUSES` in `datalakes/application/browse.py`. */
export type LakeLegStatus =
  | "ok"
  | "failed"
  | "refused"
  | "rate-limited"
  | "unsupported"
  | "needs-token"
  | "scanning";

export interface LakeSearchLeg {
  sourceId: string;
  status: LakeLegStatus;
  /** Present on anything but `ok`. Written for a user, not a log. */
  detail?: string;
  count?: number;
}

/** What a storage row's files took for one path field: every value when
 *  there are few, the range otherwise. */
export interface LakeFieldValues {
  name: string;
  type: string;
  distinct: number;
  values?: string[];
  min?: string;
  max?: string;
}

export interface LakeResourceRow {
  sourceId: string;
  sourceName: string;
  resourceId: string;
  name: string;
  description: string;
  publisher: string;
  /** A portal's downloadable formats, or what a storage row adds as
   *  (`collection`, `parquet`, `csv`...). */
  formats: string[];
  updatedAt: string | null;
  landingUrl: string | null;
  sizeHint: number | null;
  acquirable: boolean;
  /** Set when this account already downloaded this resource, so the row links
   *  to the dataset instead of offering a second copy. */
  alreadyHeldDatasetId: string | null;
  /** Storage rows only, null for a portal's. */
  kind?: LakeResourceKind | null;
  fileCount?: number | null;
  fieldValues?: LakeFieldValues[];
  /** Relpaths of the row's first files, whose thumbnails the row shows. */
  samples?: string[];
}

export interface LakeResourceField {
  name: string;
  type: string | null;
  description: string;
}

export interface LakeResourceDetail extends LakeResourceRow {
  fields: LakeResourceField[];
  license: string;
  /** Provider-specific extras, e.g. a WFS layer's crs and bbox. */
  extra: Record<string, string | number | boolean | unknown[]>;
}

export interface LakeSearchResponse {
  resources: LakeResourceRow[];
  sources: LakeSearchLeg[];
  nextCursor: string | null;
  totalHint: number | null;
  truncated: boolean;
  /** Storage sources: files under the source that no resource declares. */
  unmatched?: number;
  scannedAt?: string | null;
}

/** One file of a storage row, from its Files list. */
export interface LakeStorageFile {
  /** Its position in the row, which its thumbnail is addressed by. */
  index: number;
  relpath: string;
  size: number;
  updatedAt: string | null;
  values: Record<string, string>;
}

export interface LakeStorageFilesPage {
  files: LakeStorageFile[];
  total: number;
  offset: number;
  /** True for a collection row, whose files have thumbnails. */
  previews: boolean;
}

/** How a storage row is narrowed when it is added: the values to keep per
 *  field, or an inclusive range. */
export type LakeFieldFilter = string[] | { min: string; max: string };

export interface LakeAcquireBody {
  format?: string;
  title?: string;
  refresh?: boolean;
  filters?: Record<string, LakeFieldFilter>;
  files?: string[];
}

/** Where a collection's files are, from `GET /collections/<id>`. */
export interface LakeCollectionStatus {
  datasetId: string;
  provider: LakeProviderType;
  /** A folder on this machine: every file is readable as it is. */
  local: boolean;
  fileCount: number;
  totalBytes: number;
  cachedFiles: number;
  cachedBytes: number;
  samples: { fileId: string; name: string; kind: string }[];
}

export interface LakeSearchQuery {
  q: string;
  format?: LakeAcquirableFormat | "";
  limit?: number;
  cursor?: string;
  /** Narrow a federated search to one provider family. */
  provider?: LakeProviderType | "";
}

/** The legs worth telling the user about: everything that is not a plain `ok`,
 *  and not the "this source has nothing to browse" that a link-only source
 *  reports every single time and which is not news. */
export function notableLegs(legs: LakeSearchLeg[]): LakeSearchLeg[] {
  return legs.filter((leg) => leg.status !== "ok" && leg.status !== "unsupported");
}

/** One line naming the portals that did not answer. Null when all did. */
export function partialFailureMessage(
  legs: LakeSearchLeg[],
  nameOf: (sourceId: string) => string
): string | null {
  const notable = notableLegs(legs);
  if (notable.length === 0) return null;
  const names = notable.map((leg) => nameOf(leg.sourceId) || leg.sourceId);
  const list =
    names.length === 1
      ? names[0]
      : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  return `${list} did not answer. Showing what the other portals returned.`;
}


// ── Acquisition ────────────────────────────────────────────────────────────

export type LakeJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "refused"
  | "cancelled";

export const LAKE_JOB_TERMINAL: readonly LakeJobStatus[] = [
  "completed",
  "failed",
  "refused",
  "cancelled",
];

export function isTerminal(status: LakeJobStatus): boolean {
  return LAKE_JOB_TERMINAL.includes(status);
}

export interface LakeAcquireJob {
  jobId: string;
  status: LakeJobStatus;
  bytesRead: number;
  /** From the portal's Content-Length when it sent one. Null means the bar is
   *  indeterminate - plenty of portals stream without declaring a length. */
  totalBytes: number | null;
  stageMessage: string;
  error: string | null;
  datasetId: string | null;
  dataset: Record<string, unknown> | null;
  alreadyPresent: boolean;
  unchanged: boolean;
  sourceId: string;
  resourceId: string;
  /** Files done and in all, when the work is counted in files. */
  itemsDone?: number;
  itemsTotal?: number | null;
}

/** What `POST .../acquire` answers: either a job to poll, or the dataset you
 *  already had - in which case no portal was contacted at all. */
export interface LakeAcquireStart extends Partial<LakeAcquireJob> {
  dataset?: Record<string, unknown> | null;
  alreadyPresent?: boolean;
}

/** 0..1, or null when the total is unknown. Files when the job counts
 *  files, bytes otherwise. */
export function jobProgress(job: LakeAcquireJob): number | null {
  if (job.itemsTotal && job.itemsTotal > 0) {
    return Math.min(1, (job.itemsDone ?? 0) / job.itemsTotal);
  }
  if (!job.totalBytes || job.totalBytes <= 0) return null;
  return Math.min(1, job.bytesRead / job.totalBytes);
}

/** The progress label: files done, bytes read, or the stage. */
export function jobProgressLabel(job: LakeAcquireJob): string {
  if (job.itemsTotal && job.itemsTotal > 0) {
    return `${(job.itemsDone ?? 0).toLocaleString()} of ${job.itemsTotal.toLocaleString()} files`;
  }
  return job.bytesRead > 0 ? formatBytes(job.bytesRead) : job.stageMessage;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}
