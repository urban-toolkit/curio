import { apiFetch } from "../utils/authApi";

export interface OutputRef {
  node_id: string;
  filename: string;
  /** Sandbox dataType (e.g. raster, dataframe) for extensionless artifact paths. */
  data_type?: string;
  /** Producing node's friendly display label, so the save-time installer titles
   * computed datasets by their node (matching execution-time auto-install)
   * instead of the raw generated filename. */
  node_name?: string;
  /** Producing node's type slug (e.g. ``curio.builtin/autk-grammar``), so the
   * computed dataset's manifest records producer lineage. */
  node_type?: string;
}

export interface GraphPreviewNode {
  id: string;
  type: string;
  x: number;
  y: number;
  w?: number | null;
  h?: number | null;
}

export interface GraphPreviewEdge {
  source: string;
  target: string;
}

export interface GraphPreview {
  nodes: GraphPreviewNode[];
  edges: GraphPreviewEdge[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  thumbnail_accent: string;
  spec_revision: number;
  last_opened_at: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  graph_preview?: GraphPreview | null;
}

/** A computed output the backend could not auto-install on a save (e.g. its
 * artifact was missing at save time). Response-only; lets the client warn the
 * user about a silently-skipped dataset instead of leaving it invisible. */
export interface DatasetInstallWarning {
  node_id: string;
  filename: string;
  reason: string;
}

export interface ProjectDetail extends ProjectSummary {
  folder_path: string;
  spec: Record<string, unknown> | null;
  outputs: OutputRef[];
  dataset_install_warnings?: DatasetInstallWarning[];
}

export interface SaveBody {
  name: string;
  spec: Record<string, unknown>;
  outputs: OutputRef[];
  description?: string;
  thumbnail_accent?: string;
}

export interface UpdateBody {
  spec?: Record<string, unknown>;
  outputs?: OutputRef[];
  name?: string;
  description?: string;
  thumbnail_accent?: string;
}

export interface LoadResponse {
  project: ProjectDetail;
  spec: Record<string, unknown>;
  outputs: OutputRef[];
}

export interface ListParams {
  scope?: "mine" | "recent" | "archived";
  sort?: "last_opened" | "name" | "created";
}

export const projectsApi = {
  list(params?: ListParams): Promise<ProjectSummary[]> {
    const qs = new URLSearchParams();
    if (params?.scope) qs.set("scope", params.scope);
    if (params?.sort) qs.set("sort", params.sort);
    const query = qs.toString();
    return apiFetch<ProjectSummary[]>(
      `/api/projects${query ? `?${query}` : ""}`
    );
  },

  get(id: string): Promise<LoadResponse> {
    return apiFetch<LoadResponse>(`/api/projects/${id}`);
  },

  getShared(id: string): Promise<LoadResponse> {
    return apiFetch<LoadResponse>(`/api/projects/${id}/shared`);
  },

  create(body: SaveBody): Promise<ProjectDetail> {
    return apiFetch<ProjectDetail>("/api/projects", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  update(id: string, body: UpdateBody): Promise<ProjectDetail> {
    return apiFetch<ProjectDetail>(`/api/projects/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  delete(id: string, opts?: { purge?: boolean }): Promise<void> {
    return apiFetch(`/api/projects/${id}?purge=${opts?.purge ?? false}`, {
      method: "DELETE",
    });
  },

  duplicate(id: string): Promise<ProjectDetail> {
    return apiFetch<ProjectDetail>(`/api/projects/${id}/duplicate`, {
      method: "POST",
    });
  },
};
