/**
 * The Data Lake Catalog's wire types.
 *
 * Mirrors `backend/app/datalakes/schemas/payloads.py`, which builds every row
 * by explicit allowlist. Keep the two in step: a field that exists on the
 * backend manifest but not in that builder never reaches here, which is
 * deliberate - it is how a credential cannot leak into a response.
 */

/** Matches `PROVIDER_TYPES` in `datalakes/domain/manifest.py`. */
export type LakeProviderType = "socrata" | "ckan" | "arcgis" | "wfs" | "direct";

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
  | "needs-token";

export interface LakeSearchLeg {
  sourceId: string;
  status: LakeLegStatus;
  /** Present on anything but `ok`. Written for a user, not a log. */
  detail?: string;
  count?: number;
}

export interface LakeResourceRow {
  sourceId: string;
  sourceName: string;
  resourceId: string;
  name: string;
  description: string;
  publisher: string;
  formats: LakeAcquirableFormat[];
  updatedAt: string | null;
  landingUrl: string | null;
  sizeHint: number | null;
  acquirable: boolean;
  /** Set when this account already downloaded this resource, so the row links
   *  to the dataset instead of offering a second copy. */
  alreadyHeldDatasetId: string | null;
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
}

/** What `POST .../acquire` answers: either a job to poll, or the dataset you
 *  already had - in which case no portal was contacted at all. */
export interface LakeAcquireStart extends Partial<LakeAcquireJob> {
  dataset?: Record<string, unknown> | null;
  alreadyPresent?: boolean;
}

/** 0..1, or null when the total is unknown. */
export function jobProgress(job: LakeAcquireJob): number | null {
  if (!job.totalBytes || job.totalBytes <= 0) return null;
  return Math.min(1, job.bytesRead / job.totalBytes);
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
