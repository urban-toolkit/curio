import { apiFetch, getToken } from "../../utils/authApi";
import {
  DatasetCatalogItem,
  DatasetCatalogQuery,
  DatasetCatalogResponse,
  DatasetPreviewQuery,
  DatasetPreviewResponse,
} from "./datasetCatalogTypes";

const BACKEND_URL = process.env.BACKEND_URL || "";

function queryString(query: DatasetCatalogQuery = {}): string {
  const params = new URLSearchParams();
  if (query.dataflowId) params.set("dataflowId", query.dataflowId);
  if (query.search) params.set("q", query.search);
  if (query.format) params.set("format", query.format);
  if (query.origin) params.set("origin", query.origin);
  if (query.sort) params.set("sort", query.sort);
  if (query.includeHub !== undefined) params.set("includeHub", String(query.includeHub));
  const raw = params.toString();
  return raw ? `?${raw}` : "";
}

function previewQueryString(query: DatasetPreviewQuery = {}): string {
  const params = new URLSearchParams();
  if (query.dataflowId) params.set("dataflowId", query.dataflowId);
  if (query.offset != null) params.set("offset", String(query.offset));
  if (query.rowLimit != null) params.set("rowLimit", String(query.rowLimit));
  const raw = params.toString();
  return raw ? `?${raw}` : "";
}

export const datasetCatalogApi = {
  listCatalog(query: DatasetCatalogQuery = {}): Promise<DatasetCatalogResponse> {
    return apiFetch(`/api/datasets/catalog${queryString(query)}`);
  },

  getDataset(datasetId: string, query: Pick<DatasetCatalogQuery, "dataflowId"> = {}): Promise<DatasetCatalogItem> {
    return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}${queryString(query)}`);
  },

  preview(datasetId: string, query: DatasetPreviewQuery = {}): Promise<DatasetPreviewResponse> {
    return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}/preview${previewQueryString(query)}`);
  },

  async importDataset(
    file: File,
    opts: { dataflowId?: string | null; title?: string } = {},
  ): Promise<DatasetCatalogItem> {
    const token = getToken();
    const form = new FormData();
    form.append("file", file);
    if (opts.dataflowId) form.append("dataflowId", opts.dataflowId);
    if (opts.title) form.append("title", opts.title);
    const res = await fetch(`${BACKEND_URL}/api/datasets/import`, {
      method: "POST",
      body: form,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new Error(body.error || `HTTP ${res.status}`);
      (err as { status?: number }).status = res.status;
      (err as { body?: unknown }).body = body;
      throw err;
    }
    return await res.json();
  },

  publishDataset(
    datasetId: string,
    metadata: { title?: string; description?: string; tags?: string[]; license?: string; dataflowId?: string | null },
  ): Promise<DatasetCatalogItem> {
    return apiFetch("/api/datasets/publish", {
      method: "POST",
      body: JSON.stringify({ datasetId, ...metadata }),
    });
  },

  installToDataflow(dataflowId: string, datasetId: string): Promise<DatasetCatalogItem> {
    return apiFetch(`/api/dataflows/${encodeURIComponent(dataflowId)}/datasets/install`, {
      method: "POST",
      body: JSON.stringify({ datasetId }),
    });
  },

  uninstallFromDataflow(dataflowId: string, datasetId: string): Promise<{ datasets: unknown[] }> {
    return apiFetch(`/api/dataflows/${encodeURIComponent(dataflowId)}/datasets/${encodeURIComponent(datasetId)}`, {
      method: "DELETE",
    });
  },
};
