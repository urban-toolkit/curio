import { apiFetch } from "../../utils/authApi";
import { invalidateLakeCatalogCache } from "./dataLakeCatalogCache";
import type {
  LakeCatalogQuery,
  LakeCatalogResponse,
  LakeResourceDetail,
  LakeSearchQuery,
  LakeSearchResponse,
  LakeSourceRow,
} from "./dataLakeCatalogTypes";

function query(params: LakeCatalogQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  if (params.provider) search.set("provider", params.provider);
  if (params.auth) search.set("auth", params.auth);
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * The Data Lake Catalog's HTTP client.
 *
 * Only the roster in this phase: both endpoints are served from disk, so
 * nothing here can be slow because a portal is. Live search and acquisition
 * arrive with the providers.
 */
export const dataLakeCatalogApi = {
  listCatalog(params: LakeCatalogQuery = {}): Promise<LakeCatalogResponse> {
    return apiFetch<LakeCatalogResponse>(`/api/datalakes/catalog${query(params)}`);
  },

  getSource(dirName: string): Promise<LakeSourceRow> {
    // Encoded because a dirName carries an `@`. Legal in a path segment, but
    // not every proxy agrees, and encoding costs nothing.
    return apiFetch<LakeSourceRow>(`/api/datalakes/sources/${encodeURIComponent(dirName)}`);
  },

  /** Search every searchable portal at once. A leg that fails comes back in
   *  `sources[]` rather than failing the call. */
  searchAll(params: LakeSearchQuery, signal?: AbortSignal): Promise<LakeSearchResponse> {
    return apiFetch<LakeSearchResponse>(`/api/datalakes/search${searchQuery(params)}`, {
      signal,
    });
  },

  /** Search one portal. The only paginated search: a fan-out has no coherent
   *  cursor across portals that paginate independently. */
  searchSource(
    dirName: string,
    params: LakeSearchQuery,
    signal?: AbortSignal
  ): Promise<LakeSearchResponse> {
    return apiFetch<LakeSearchResponse>(
      `/api/datalakes/sources/${encodeURIComponent(dirName)}/search${searchQuery(params)}`,
      { signal }
    );
  },

  describeResource(
    dirName: string,
    resourceId: string,
    signal?: AbortSignal
  ): Promise<LakeResourceDetail> {
    return apiFetch<LakeResourceDetail>(
      `/api/datalakes/sources/${encodeURIComponent(dirName)}/resources/` +
        encodeURIComponent(resourceId),
      { signal }
    );
  },
};

function searchQuery(params: LakeSearchQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  if (params.format) search.set("format", params.format);
  if (params.provider) search.set("provider", params.provider);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.cursor) search.set("cursor", params.cursor);
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Drop the cached roster. Call after anything that could change it. */
export function notifyLakeCatalogRefresh(): void {
  invalidateLakeCatalogCache();
}
