/**
 * The Discovery Catalog's wire types.
 *
 * Mirrors `backend/app/discovery/schemas/payloads.py`, which builds every row
 * by explicit allowlist. Keep the two in step: a field that exists on the
 * backend manifest but not in that builder never reaches here, which is
 * deliberate - it is how a credential cannot leak into a response.
 */

/** Matches `PROVIDER_TYPES` in `discovery/domain/manifest.py`: the portal
 *  types, then the storage types. */
export type DiscoveryProviderType =
  | "socrata"
  | "ckan"
  | "arcgis"
  | "wfs"
  | "direct"
  | "folder"
  | "s3"
  | "huggingface";

/** Matches `STORAGE_PROVIDER_TYPES`: sources that declare their resources. */
export const STORAGE_PROVIDER_TYPES: readonly DiscoveryProviderType[] = ["folder", "s3", "huggingface"];

/** A `portal` is searched for its datasets; a `storage` source declares them. */
export type DiscoverySourceKind = "portal" | "storage";

/** Matches `RESOURCE_KINDS`. `table` is copied; every other kind is a
 *  collection, referenced where its files are. */
export type DiscoveryResourceKind =
  | "table"
  | "rasters"
  | "frames"
  | "images"
  | "videos"
  | "media"
  | "audio";

/** Matches `KIND_LABEL` in `discovery/application/scan.py`. */
export const DISCOVERY_RESOURCE_KIND_LABEL: Record<DiscoveryResourceKind, string> = {
  table: "Table",
  rasters: "Rasters",
  frames: "Frames",
  images: "Images",
  videos: "Videos",
  media: "Photos and videos",
  audio: "Audio",
};

/** Matches `AUTH_MODES`. */
export type DiscoveryAuthMode = "public" | "optional-token" | "required-token";

/**
 * Matches `DISCOVERY_ACQUIRABLE_FORMATS`. A strict subset of the Data Catalog's
 * `DatasetFormat`: `shp` needs sibling files and `bundle` is a node output, so
 * neither is acquirable from a portal.
 */
export const DISCOVERY_ACQUIRABLE_FORMATS = [
  "csv",
  "geojson",
  "json",
  "parquet",
  "geotiff",
] as const;
export type DiscoveryAcquirableFormat = (typeof DISCOVERY_ACQUIRABLE_FORMATS)[number];

/** What a source's rows add as: a portal's formats, and a storage source's
 *  table formats and `collection`. */
export type DiscoverySourceFormat = DiscoveryAcquirableFormat | "shp" | "gpkg" | "pbf" | "collection";

export const DISCOVERY_PROVIDER_LABEL: Record<DiscoveryProviderType, string> = {
  socrata: "Socrata",
  ckan: "CKAN",
  arcgis: "ArcGIS",
  wfs: "OGC WFS",
  direct: "Direct URL",
  folder: "Folder",
  s3: "S3 bucket",
  huggingface: "Hugging Face",
};

export const DISCOVERY_AUTH_LABEL: Record<DiscoveryAuthMode, string> = {
  public: "Public",
  "optional-token": "Token optional",
  "required-token": "Token required",
};

export interface DiscoverySourceAuth {
  mode: DiscoveryAuthMode;
  /** True only for `required-token`: this source cannot be used without one. */
  required: boolean;
  usesToken: boolean;
  /** The credential SLOT this source wants, never a value. Null when public. */
  secretId: string | null;
  /** Whether this account has that slot filled. */
  present: boolean;
  helpUrl: string | null;
}

/** One key slot, as API Settings lists it (`GET /api/discovery/keys`). */
export interface DiscoveryKeyRow {
  /** The manifest's `auth.secretId`. */
  slot: string;
  label: string;
  /** The field `PATCH /api/auth/me` takes the key under. */
  field: string;
  helpUrl: string | null;
  placeholder: string | null;
  note: string | null;
  /** This account saved one. */
  present: boolean;
  /** The deployment supplies one everybody gets. */
  inherited: boolean;
  /** The sources on this Curio that send it. */
  sources: { name: string; dirName: string }[];
  /** Other parts of Curio that read the same key. */
  alsoUsedBy: string[];
}

export interface DiscoveryKeysResponse {
  keys: DiscoveryKeyRow[];
}

export interface DiscoverySourceCapabilities {
  search: boolean;
  describe: boolean;
  download: boolean;
  formats: DiscoverySourceFormat[];
  maxDownloadBytes: number;
}

/** One resource a storage manifest declares, before any scan. */
export interface DiscoveryDeclaredResource {
  resourceId: string;
  name: string;
  description: string;
  kind: DiscoveryResourceKind;
  /** What lands in the Data Catalog: a table's file format, or `collection`. */
  format: string;
  /** A table's file format; null for a collection. */
  fileFormat: string | null;
  path: string;
  datasets: string;
  splitBy: string[];
  fields: { name: string; type: string }[];
}

export interface DiscoverySourceRow {
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
   *  The UI renders the shared source glyph for a null. */
  iconUrl: string | null;
  provider: DiscoveryProviderType;
  baseUrl: string;
  auth: DiscoverySourceAuth;
  capabilities: DiscoverySourceCapabilities;
  kind: DiscoverySourceKind;
  /** A storage source's declared resources; empty for a portal. */
  resources: DiscoveryDeclaredResource[];
  createdAt: string | null;
  updatedAt: string | null;
}

export interface DiscoveryCatalogFacets {
  provider: Record<string, number>;
  auth: Record<string, number>;
}

export interface DiscoveryCatalogResponse {
  sources: DiscoverySourceRow[];
  facets: DiscoveryCatalogFacets;
}

export interface DiscoveryCatalogQuery {
  q?: string;
  provider?: DiscoveryProviderType | "";
  auth?: DiscoveryAuthMode | "";
}

export function isStorageSource(source: Pick<DiscoverySourceRow, "kind">): boolean {
  return source.kind === "storage";
}

/** The declared resource a storage row belongs to. A row's id is the
 *  resource's, or `<resource>@<field>=<value>` for one split value, or
 *  `<resource>/<relpath>` for one file. */
export function declaredResourceFor(
  source: Pick<DiscoverySourceRow, "resources">,
  resourceId: string,
): DiscoveryDeclaredResource | undefined {
  const head = resourceId.split(/[@/]/, 1)[0];
  return (source.resources ?? []).find((r) => r.resourceId === head);
}

/** A source you can actually search. Narrower than `capabilities.search`
 *  alone, because a required token you do not hold also rules it out. */
export function isSearchable(source: DiscoverySourceRow): boolean {
  if (!source.capabilities.search) return false;
  return !source.auth.required || source.auth.present;
}

/** Why a source cannot be searched, phrased for a user. Null when it can. */
export function unsearchableReason(source: DiscoverySourceRow): string | null {
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
 *  Mirrors `LEG_STATUSES` in `discovery/application/browse.py`. */
export type DiscoveryLegStatus =
  | "ok"
  | "failed"
  | "refused"
  | "rate-limited"
  | "unsupported"
  | "needs-token"
  | "scanning";

export interface DiscoverySearchLeg {
  sourceId: string;
  status: DiscoveryLegStatus;
  /** Present on anything but `ok`. Written for a user, not a log. */
  detail?: string;
  count?: number;
}

/** What a storage row's files took for one path field: every value when
 *  there are few, the range otherwise. */
export interface DiscoveryFieldValues {
  name: string;
  type: string;
  distinct: number;
  values?: string[];
  min?: string;
  max?: string;
}

export interface DiscoveryResource {
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
  kind?: DiscoveryResourceKind | null;
  fileCount?: number | null;
  fieldValues?: DiscoveryFieldValues[];
  /** Relpaths of the row's first files, whose thumbnails the row shows. */
  samples?: string[];
}

export interface DiscoveryResourceField {
  name: string;
  type: string | null;
  description: string;
}

export interface DiscoveryResourceDetail extends DiscoveryResource {
  fields: DiscoveryResourceField[];
  license: string;
  /** Provider-specific extras, e.g. a WFS layer's crs and bbox. */
  extra: Record<string, string | number | boolean | unknown[]>;
}

export interface DiscoverySearchResponse {
  resources: DiscoveryResource[];
  sources: DiscoverySearchLeg[];
  nextCursor: string | null;
  totalHint: number | null;
  truncated: boolean;
  /** Storage sources: files under the source that no resource declares. */
  unmatched?: number;
  scannedAt?: string | null;
}

/** One file of a storage row, from its Files list. */
export interface DiscoveryStorageFile {
  /** Its position in the row, which its thumbnail is addressed by. */
  index: number;
  relpath: string;
  size: number;
  updatedAt: string | null;
  values: Record<string, string>;
}

export interface DiscoveryStorageFilesPage {
  files: DiscoveryStorageFile[];
  total: number;
  offset: number;
  /** True for a collection row, whose files have thumbnails. */
  previews: boolean;
}

/** How a storage row is narrowed when it is added: the values to keep per
 *  field, or an inclusive range. */
export type DiscoveryFieldFilter = string[] | { min: string; max: string };

export interface DiscoveryAcquireBody {
  format?: string;
  title?: string;
  refresh?: boolean;
  filters?: Record<string, DiscoveryFieldFilter>;
  files?: string[];
}

/** Where a collection's files are, from `GET /collections/<id>`. */
export interface DiscoveryCollectionStatus {
  datasetId: string;
  provider: DiscoveryProviderType;
  /** A folder on this machine: every file is readable as it is. */
  local: boolean;
  fileCount: number;
  totalBytes: number;
  cachedFiles: number;
  cachedBytes: number;
  samples: { fileId: string; name: string; kind: string }[];
}

export interface DiscoverySearchQuery {
  q: string;
  format?: DiscoveryAcquirableFormat | "";
  limit?: number;
  cursor?: string;
  /** Narrow a federated search to one provider family. */
  provider?: DiscoveryProviderType | "";
}

/** The legs worth telling the user about: everything that is not a plain `ok`,
 *  and not the "this source has nothing to browse" that a link-only source
 *  reports every single time and which is not news. */
export function notableLegs(legs: DiscoverySearchLeg[]): DiscoverySearchLeg[] {
  return legs.filter(
    (leg) => leg.status !== "ok" && leg.status !== "unsupported" && leg.status !== "scanning"
  );
}

function namesOf(legs: DiscoverySearchLeg[], nameOf: (sourceId: string) => string): string {
  const names = legs.map((leg) => nameOf(leg.sourceId) || leg.sourceId);
  return names.length === 1
    ? names[0]
    : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** One line naming the portals that did not answer. Null when all did. */
export function partialFailureMessage(
  legs: DiscoverySearchLeg[],
  nameOf: (sourceId: string) => string
): string | null {
  const notable = notableLegs(legs);
  if (notable.length === 0) return null;
  return `${namesOf(notable, nameOf)} did not answer. Showing what the other portals returned.`;
}

/** One line naming the storage sources still being scanned, whose rows join
 *  the results when they are. Null when none is. */
export function scanningMessage(
  legs: DiscoverySearchLeg[],
  nameOf: (sourceId: string) => string
): string | null {
  const scanning = legs.filter((leg) => leg.status === "scanning");
  if (scanning.length === 0) return null;
  const names = namesOf(scanning, nameOf);
  return scanning.length === 1
    ? `${names} is still being scanned; its rows appear here when it is done.`
    : `${names} are still being scanned; their rows appear here when they are done.`;
}


// ── Acquisition ────────────────────────────────────────────────────────────

export type DiscoveryJobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "refused"
  | "cancelled";

export const DISCOVERY_JOB_TERMINAL: readonly DiscoveryJobStatus[] = [
  "completed",
  "failed",
  "refused",
  "cancelled",
];

export function isTerminal(status: DiscoveryJobStatus): boolean {
  return DISCOVERY_JOB_TERMINAL.includes(status);
}

export interface DiscoveryAcquireJob {
  jobId: string;
  status: DiscoveryJobStatus;
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
export interface DiscoveryAcquireStart extends Partial<DiscoveryAcquireJob> {
  dataset?: Record<string, unknown> | null;
  alreadyPresent?: boolean;
}

/** 0..1, or null when the total is unknown. Files when the job counts
 *  files, bytes otherwise. */
export function jobProgress(job: DiscoveryAcquireJob): number | null {
  if (job.itemsTotal && job.itemsTotal > 0) {
    return Math.min(1, (job.itemsDone ?? 0) / job.itemsTotal);
  }
  if (!job.totalBytes || job.totalBytes <= 0) return null;
  return Math.min(1, job.bytesRead / job.totalBytes);
}

/** The progress label: files done, bytes read, or the stage. */
export function jobProgressLabel(job: DiscoveryAcquireJob): string {
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
