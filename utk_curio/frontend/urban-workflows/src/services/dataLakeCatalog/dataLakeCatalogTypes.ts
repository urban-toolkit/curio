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
