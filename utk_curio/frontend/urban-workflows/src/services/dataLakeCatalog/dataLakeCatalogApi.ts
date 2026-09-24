import { apiFetch } from "../../utils/authApi";
import { invalidateLakeCatalogCache } from "./dataLakeCatalogCache";
import type {
  LakeCatalogQuery,
  LakeCatalogResponse,
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
};

/** Drop the cached roster. Call after anything that could change it. */
export function notifyLakeCatalogRefresh(): void {
  invalidateLakeCatalogCache();
}
