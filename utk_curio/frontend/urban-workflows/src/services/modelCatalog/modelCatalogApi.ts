import { apiFetch } from "../../utils/authApi";
import { invalidateModelCatalogCache } from "./modelCatalogCache";
import type { ModelCatalogQuery, ModelCatalogResponse, ModelRow } from "./modelCatalogTypes";

/** Dispatched after anything that changes the listing, so every open Model
 *  Catalog surface (page, drawer, palette) reloads. */
export const MODEL_CATALOG_REFRESH_EVENT = "curio:model-catalog-refresh";

function query(params: ModelCatalogQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * The Model Catalog's HTTP client.
 *
 * Every route reads manifests from disk, so nothing here waits on a third
 * party. Models arrive from the Discovery Catalog, so there is no import here.
 */
export const modelCatalogApi = {
  listCatalog(params: ModelCatalogQuery = {}): Promise<ModelCatalogResponse> {
    return apiFetch<ModelCatalogResponse>(`/api/models/catalog${query(params)}`);
  },

  getModel(modelId: string): Promise<ModelRow> {
    return apiFetch<ModelRow>(`/api/models/${encodeURIComponent(modelId)}`);
  },

  /** The license's full text. 404 when the model ships none. */
  async getLicense(modelId: string): Promise<string> {
    const res = await apiFetch<{ text?: string }>(
      `/api/models/${encodeURIComponent(modelId)}/license`
    );
    return res?.text ?? "";
  },

  /** Delete a downloaded model from this account. The server refuses a
   *  shipped one with 403. */
  deleteModel(modelId: string): Promise<{ deleted: string }> {
    return apiFetch<{ deleted: string }>(`/api/models/${encodeURIComponent(modelId)}`, {
      method: "DELETE",
    });
  },
};

/** Drop the cached listing, then tell every mounted surface to reload. The
 *  cache goes first so a surface that mounts later cannot find the old rows. */
export function notifyModelCatalogRefresh(): void {
  invalidateModelCatalogCache();
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(MODEL_CATALOG_REFRESH_EVENT));
}
