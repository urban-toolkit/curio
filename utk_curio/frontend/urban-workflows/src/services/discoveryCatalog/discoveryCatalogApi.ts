import { apiFetch } from "../../utils/authApi";
import { invalidateDiscoveryCatalogCache } from "./discoveryCatalogCache";
import type {
  DiscoveryCatalogQuery,
  DiscoveryCatalogResponse,
  DiscoveryAcquireBody,
  DiscoveryAcquireJob,
  DiscoveryAcquireStart,
  DiscoveryCollectionStatus,
  DiscoveryResourceDetail,
  DiscoverySearchQuery,
  DiscoverySearchResponse,
  DiscoverySourceRow,
  DiscoveryStorageFilesPage,
} from "./discoveryCatalogTypes";

function query(params: DiscoveryCatalogQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  if (params.provider) search.set("provider", params.provider);
  if (params.auth) search.set("auth", params.auth);
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * The Discovery Catalog's HTTP client.
 *
 * Only the roster in this phase: both endpoints are served from disk, so
 * nothing here can be slow because a portal is. Live search and acquisition
 * arrive with the providers.
 */
export const discoveryCatalogApi = {
  listCatalog(params: DiscoveryCatalogQuery = {}): Promise<DiscoveryCatalogResponse> {
    return apiFetch<DiscoveryCatalogResponse>(`/api/discovery/catalog${query(params)}`);
  },

  getSource(dirName: string): Promise<DiscoverySourceRow> {
    // Encoded because a dirName carries an `@`. Legal in a path segment, but
    // not every proxy agrees, and encoding costs nothing.
    return apiFetch<DiscoverySourceRow>(`/api/discovery/sources/${encodeURIComponent(dirName)}`);
  },

  /** Search every searchable portal at once. A leg that fails comes back in
   *  `sources[]` rather than failing the call. */
  searchAll(params: DiscoverySearchQuery, signal?: AbortSignal): Promise<DiscoverySearchResponse> {
    return apiFetch<DiscoverySearchResponse>(`/api/discovery/search${searchQuery(params)}`, {
      signal,
    });
  },

  /** Search one portal. The only paginated search: a fan-out has no coherent
   *  cursor across portals that paginate independently. A storage source
   *  answers from its last scan; `rescan` walks it again. */
  searchSource(
    dirName: string,
    params: DiscoverySearchQuery & { rescan?: boolean },
    signal?: AbortSignal
  ): Promise<DiscoverySearchResponse> {
    return apiFetch<DiscoverySearchResponse>(
      `/api/discovery/sources/${encodeURIComponent(dirName)}/search${searchQuery(params)}`,
      { signal }
    );
  },

  /** One page of a storage row's files, in the order its thumbnails number them. */
  listFiles(
    dirName: string,
    resourceId: string,
    page: { offset?: number; limit?: number } = {},
    signal?: AbortSignal
  ): Promise<DiscoveryStorageFilesPage> {
    const search = new URLSearchParams();
    if (page.offset) search.set("offset", String(page.offset));
    if (page.limit) search.set("limit", String(page.limit));
    const text = search.toString();
    return apiFetch<DiscoveryStorageFilesPage>(
      `/api/discovery/sources/${encodeURIComponent(dirName)}/files/` +
        `${encodeURIComponent(resourceId)}${text ? `?${text}` : ""}`,
      { signal }
    );
  },

  /** Where a collection's files are, and a few of them by id. */
  getCollection(datasetId: string): Promise<DiscoveryCollectionStatus> {
    return apiFetch<DiscoveryCollectionStatus>(
      `/api/discovery/collections/${encodeURIComponent(datasetId)}`
    );
  },

  /** Fetch a bucket collection's files to this machine, as a job. */
  cacheCollection(datasetId: string): Promise<DiscoveryAcquireJob> {
    return apiFetch<DiscoveryAcquireJob>(
      `/api/discovery/collections/${encodeURIComponent(datasetId)}/cache`,
      { method: "POST" }
    );
  },

  /** Start a download. Answers `{dataset, alreadyPresent: true}` when this
   *  account already holds the resource, in which case nothing was fetched. */
  acquire(
    dirName: string,
    resourceId: string,
    body: DiscoveryAcquireBody = {}
  ): Promise<DiscoveryAcquireStart> {
    return apiFetch<DiscoveryAcquireStart>(
      `/api/discovery/sources/${encodeURIComponent(dirName)}/resources/` +
        `${encodeURIComponent(resourceId)}/acquire`,
      { method: "POST", body: JSON.stringify(body) }
    );
  },

  getJob(jobId: string): Promise<DiscoveryAcquireJob> {
    return apiFetch<DiscoveryAcquireJob>(`/api/discovery/jobs/${encodeURIComponent(jobId)}`);
  },

  cancelJob(jobId: string): Promise<void> {
    return apiFetch<void>(`/api/discovery/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    });
  },

  describeResource(
    dirName: string,
    resourceId: string,
    signal?: AbortSignal
  ): Promise<DiscoveryResourceDetail> {
    return apiFetch<DiscoveryResourceDetail>(
      `/api/discovery/sources/${encodeURIComponent(dirName)}/resources/` +
        encodeURIComponent(resourceId),
      { signal }
    );
  },
};

/** The path of a storage row's file thumbnail, by its position in the row.
 *  Served to a signed-in caller, so it is fetched with the token. */
export function discoveryThumbnailPath(dirName: string, resourceId: string, index: number): string {
  return (
    `/api/discovery/sources/${encodeURIComponent(dirName)}/thumbnails/${index}/` +
    encodeURIComponent(resourceId)
  );
}

function searchQuery(params: DiscoverySearchQuery & { rescan?: boolean }): string {
  const search = new URLSearchParams();
  if (params.rescan) search.set("rescan", "1");
  if (params.q?.trim()) search.set("q", params.q.trim());
  if (params.format) search.set("format", params.format);
  if (params.provider) search.set("provider", params.provider);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.cursor) search.set("cursor", params.cursor);
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Drop the cached roster. Call after anything that could change it. */
export function notifyDiscoveryCatalogRefresh(): void {
  invalidateDiscoveryCatalogCache();
}
