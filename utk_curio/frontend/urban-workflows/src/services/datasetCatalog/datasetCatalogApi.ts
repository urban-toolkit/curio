import type { Dispatch, SetStateAction } from "react";
import { apiFetch, getToken } from "../../utils/authApi";
import {
  DatasetCatalogItem,
  DatasetCatalogQuery,
  DatasetCatalogResponse,
  DatasetDataflowUsageRef,
  DatasetFormat,
  DatasetPreviewQuery,
  DatasetPreviewResponse,
} from "./datasetCatalogTypes";

const BACKEND_URL = process.env.BACKEND_URL || "";

/** Canonical file extension per dataset format (mirror of the backend map). */
const DATASET_FORMAT_EXTENSIONS: Record<string, string> = {
  csv: ".csv",
  geojson: ".geojson",
  json: ".json",
  parquet: ".parquet",
  geotiff: ".tif",
  shp: ".shp",
};

/** MIME type → extension, used as a last-resort fallback for the export name. */
const MIME_EXTENSIONS: Record<string, string> = {
  "text/csv": ".csv",
  "application/json": ".json",
  "application/geo+json": ".geojson",
  "application/vnd.apache.parquet": ".parquet",
  "image/tiff": ".tif",
};

/** Dispatched after a node auto-installs a computed dataset so open drawers reload. */
export const DATASET_CATALOG_REFRESH_EVENT = "curio:dataset-catalog-refresh";

export function notifyDatasetCatalogRefresh(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(DATASET_CATALOG_REFRESH_EVENT));
  }
}

export interface InstalledDatasetPayload {
  id: string;
  dirName: string;
  origin?: string;
  producerNodeId?: string | null;
}

/** A lean dataflow dataset ref as stored in ``spec.dataflow.datasets``. */
export type DataflowDatasetRef = {
  datasetId: string;
  dirName: string;
  origin: string;
  producerNodeId: string | null;
  installedAt: string;
};

/** Build the canonical lean ref for an auto-installed dataset payload. */
export function buildInstalledDatasetRef(inst: InstalledDatasetPayload): DataflowDatasetRef {
  return {
    datasetId: inst.id,
    dirName: inst.dirName,
    origin: inst.origin ?? "computed",
    producerNodeId: inst.producerNodeId ?? null,
    installedAt: new Date().toISOString(),
  };
}

/** Upsert one dataset ref into a refs array, replacing any existing entry by id. */
export function upsertDataflowDatasetRef(
  rows: unknown,
  datasetId: string,
  ref: DataflowDatasetRef,
): unknown[] {
  const list = Array.isArray(rows) ? rows : [];
  const next = list.filter((row: unknown) => {
    const r = row as { datasetId?: string; id?: string };
    return (r?.datasetId || r?.id) !== datasetId;
  });
  return [...next, ref];
}

/** Sync a backend auto-install into project spec state and refresh open catalog UIs. */
export function applyInstalledDatasetToProject(
  inst: InstalledDatasetPayload | null | undefined,
  setDataflowDatasets: Dispatch<SetStateAction<unknown[]>>,
): void {
  if (!inst?.id || !inst?.dirName) return;
  const ref = buildInstalledDatasetRef(inst);
  setDataflowDatasets((prev: unknown[]) => upsertDataflowDatasetRef(prev, inst.id, ref));
  notifyDatasetCatalogRefresh();
}

/**
 * Base64-encode a string as UTF-8 bytes, matching the backend's
 * ``base64.b64decode(raw).decode("utf-8")``. Plain ``btoa`` is Latin1-only: it
 * throws on code points > 0xFF (CJK, emoji) and mis-encodes 0x80–0xFF, so a
 * live-output filename/data_type with such characters would break the whole
 * catalog/preview/download request.
 */
function base64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Encode a ``liveOutputs`` array into the UTF-8-safe base64 the backend decodes
 * with ``base64.b64decode(raw).decode("utf-8")``. Centralized so the catalog,
 * preview and download requests all encode identically: a call site that
 * hand-rolled ``btoa`` would throw (or mis-encode) on a non-Latin1
 * filename/data_type and 404 on the backend (issue #139). Exported for tests.
 */
export function encodeLiveOutputsParam(
  liveOutputs: Array<{ node_id: string; filename: string; data_type?: string }>,
): string {
  return base64Utf8(JSON.stringify(liveOutputs));
}

function queryString(query: DatasetCatalogQuery = {}): string {
  const params = new URLSearchParams();
  if (query.dataflowId) params.set("dataflowId", query.dataflowId);
  if (query.search) params.set("q", query.search);
  if (query.format) params.set("format", query.format);
  if (query.origin) params.set("origin", query.origin);
  if (query.sort) params.set("sort", query.sort);
  if (query.includeHub !== undefined) params.set("includeHub", String(query.includeHub));
  if (query.groupOsm) params.set("groupOsm", "true");
  if (query.liveOutputs && query.liveOutputs.length > 0) {
    params.set("liveOutputs", encodeLiveOutputsParam(query.liveOutputs));
  }
  const raw = params.toString();
  return raw ? `?${raw}` : "";
}

function previewQueryString(query: DatasetPreviewQuery = {}): string {
  const params = new URLSearchParams();
  if (query.dataflowId) params.set("dataflowId", query.dataflowId);
  if (query.liveOutputs && query.liveOutputs.length > 0) {
    params.set("liveOutputs", encodeLiveOutputsParam(query.liveOutputs));
  }
  if (query.offset != null) params.set("offset", String(query.offset));
  if (query.rowLimit != null) params.set("rowLimit", String(query.rowLimit));
  if (query.part != null) params.set("part", String(query.part));
  const raw = params.toString();
  return raw ? `?${raw}` : "";
}

export const datasetCatalogApi = {
  listCatalog(query: DatasetCatalogQuery = {}): Promise<DatasetCatalogResponse> {
    return apiFetch(`/api/datasets/catalog${queryString(query)}`);
  },

  getDataset(
    datasetId: string,
    query: Pick<DatasetCatalogQuery, "dataflowId" | "liveOutputs"> = {},
  ): Promise<DatasetCatalogItem> {
    return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}${queryString(query)}`);
  },

  preview(datasetId: string, query: DatasetPreviewQuery = {}): Promise<DatasetPreviewResponse> {
    return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}/preview${previewQueryString(query)}`);
  },

  /** Dataflows (across the user's projects) that use this dataset. */
  async datasetUsage(datasetId: string): Promise<DatasetDataflowUsageRef[]> {
    const res = await apiFetch<{ dataflows?: DatasetDataflowUsageRef[] }>(
      `/api/datasets/${encodeURIComponent(datasetId)}/usage`,
    );
    return res?.dataflows ?? [];
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
    // The original file's last-modified date (epoch ms), so the catalog can show
    // the *source file's* date distinctly from the Curio import/record date.
    if (typeof file.lastModified === "number" && file.lastModified > 0) {
      form.append("sourceUpdatedAt", String(file.lastModified));
    }
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
    metadata: {
      title?: string;
      description?: string;
      tags?: string[];
      license?: string;
      dataflowId?: string | null;
      liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
    },
  ): Promise<DatasetCatalogItem> {
    return apiFetch("/api/datasets/publish", {
      method: "POST",
      body: JSON.stringify({ datasetId, ...metadata }),
    });
  },

  installToDataflow(
    dataflowId: string,
    datasetId: string,
    sourceItem?: DatasetCatalogItem,
    nodeTitle?: string,
  ): Promise<DatasetCatalogItem> {
    return apiFetch(`/api/dataflows/${encodeURIComponent(dataflowId)}/datasets/install`, {
      method: "POST",
      body: JSON.stringify({
        datasetId,
        ...(sourceItem ? { sourceItem } : {}),
        ...(nodeTitle ? { nodeTitle } : {}),
      }),
    });
  },

  uninstallFromDataflow(dataflowId: string, datasetId: string): Promise<{ datasets: unknown[] }> {
    return apiFetch(`/api/dataflows/${encodeURIComponent(dataflowId)}/datasets/${encodeURIComponent(datasetId)}`, {
      method: "DELETE",
    });
  },

  unpublishDataset(datasetId: string, opts: { dataflowId?: string | null } = {}): Promise<{ id: string; unpublished: boolean }> {
    const qs = opts.dataflowId ? `?dataflowId=${encodeURIComponent(opts.dataflowId)}` : "";
    return apiFetch(`/api/datasets/publish/${encodeURIComponent(datasetId)}${qs}`, {
      method: "DELETE",
    });
  },

  /**
   * Permanently delete an account-level dataset from the user's Data Catalog.
   * Distinct from {@link uninstallFromDataflow} (which only detaches it from one
   * dataflow): this cascades an unpublish + ref removal across every dataflow,
   * then deletes the account-store folder.
   */
  deleteDataset(
    datasetId: string,
  ): Promise<{ id: string; deleted: boolean; removedFrom: string[]; failedDirs?: string[] }> {
    return apiFetch(`/api/datasets/${encodeURIComponent(datasetId)}`, {
      method: "DELETE",
    });
  },

  /**
   * Export the dataset's serialized data file. Streams the raw file (parquet
   * stays parquet, csv stays csv, etc.) and triggers a browser download.
   */
  async downloadDataset(
    datasetId: string,
    opts: {
      dataflowId?: string | null;
      liveOutputs?: Array<{ node_id: string; filename: string; data_type?: string }>;
      format?: DatasetFormat | "";
    } = {},
  ): Promise<void> {
    const params = new URLSearchParams();
    if (opts.dataflowId) params.set("dataflowId", opts.dataflowId);
    if (opts.liveOutputs && opts.liveOutputs.length > 0) {
      params.set("liveOutputs", encodeLiveOutputsParam(opts.liveOutputs));
    }
    const raw = params.toString();
    const token = getToken();
    const res = await fetch(
      `${BACKEND_URL}/api/datasets/${encodeURIComponent(datasetId)}/download${raw ? `?${raw}` : ""}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : undefined },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new Error(body.error || `HTTP ${res.status}`);
      (err as { status?: number }).status = res.status;
      throw err;
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    // Prefer RFC 5987 filename* (UTF-8) then the plain filename token.
    const extMatch = /filename\*=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
    const match = extMatch || plainMatch;
    // Fallback: dataset ids can contain dots (e.g. "computed.n13…"), which the
    // OS treats as an extension. Reserve the dot for a real extension by
    // replacing dots in the fallback stem with underscores.
    let filename = match
      ? decodeURIComponent(match[1])
      : datasetId.replace(/\./g, "_");
    // Guarantee the extension is present even if the server name or CORS-exposed
    // header omitted it. Prefer the response Content-Type (the actual exported
    // bytes — e.g. a parquet dataset is exported as csv/geojson), then fall back
    // to the nominal dataset format.
    const contentType = (blob.type || "").split(";")[0].trim().toLowerCase();
    const ext =
      MIME_EXTENSIONS[contentType] ||
      DATASET_FORMAT_EXTENSIONS[opts.format ?? ""] ||
      "";
    if (ext && !filename.toLowerCase().endsWith(ext)) {
      filename += ext;
    }

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  },
};
