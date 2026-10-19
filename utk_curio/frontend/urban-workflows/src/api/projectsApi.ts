import { apiFetch } from "../utils/authApi";
import type { DataflowCategories, HandCategories } from "../utils/dataflowCategories";
import type { Scenario } from "../utils/scenarios/scenarioModel";

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
  /** The category the node's template declares (`data`, `computation`,
   *  `vis_grammar`, `vis_simple` or `flow`), which colours its box; null or
   *  absent for a node type no package provides. */
  category?: string | null;
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
  graph_preview?: GraphPreview | null;
  /** Seeded from ``docs/examples/``. Curio put it there, so Delete is not
   *  offered for it - see `projectActions`. Absent on older responses, which
   *  read as "not an example" and leave the actions as they were. */
  is_example?: boolean;
  /** Source, automatic and hand-set categories - see `utils/dataflowCategories`. */
  categories?: DataflowCategories;
  /** The dataflow's scenarios (#662), as `projects/scenarios.py` lists them.
   *  Absent on older responses. */
  scenarios?: Array<Pick<Scenario, "id" | "name" | "color" | "description" | "nodes">>;
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
  /** The spec revision this client last synced with (memo dev/124). The
   *  server refuses a save whose basis is older than the spec on disk AND
   *  which would delete a node, an edge or a node's code that the client
   *  never saw. Omitting it means "no opinion" and is not checked. */
  baseRevision?: number;
  /** Replaces the hand-set categories (`dataflow.categories`). */
  categories?: HandCategories;
  /** This tab's id and the save's number among its saves (`saveOrder.ts`).
   *  The server refuses a number lower than one it has already applied from
   *  the same tab. Omitting them means the save is not checked. */
  saveTab?: string;
  saveNumber?: number;
}

/** How long the page waits for a save before it gives up. Generous, since a
 *  save installs every output it sends. Giving up frees the save queue for
 *  the next save; the server may still finish this one, which the save's
 *  number (`saveOrder.ts`) keeps from landing over a newer save. */
export const SAVE_TIMEOUT_MS = 2 * 60 * 1000;

export const SAVE_TIMEOUT_MESSAGE =
  "Saving took longer than 2 minutes, so Curio stopped waiting. Your changes " +
  "are still on this page; save again to try once more.";

/** Send a save, and give up after {@link SAVE_TIMEOUT_MS}: the request is
 *  aborted and the save rejects with {@link SAVE_TIMEOUT_MESSAGE}, which
 *  callers show as it is. */
async function sendSave<T>(send: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const gaveUp = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      // Rejected before the abort, so the timeout is the answer rather than
      // the AbortError the request then fails with.
      reject(new Error(SAVE_TIMEOUT_MESSAGE));
      controller.abort();
    }, SAVE_TIMEOUT_MS);
  });
  try {
    return await Promise.race([send(controller.signal), gaveUp]);
  } finally {
    clearTimeout(timer);
  }
}

export interface LoadResponse {
  project: ProjectDetail;
  spec: Record<string, unknown>;
  outputs: OutputRef[];
}

export interface ListParams {
  sort?: "last_opened" | "name" | "created";
}

export const projectsApi = {
  list(params?: ListParams): Promise<ProjectSummary[]> {
    const qs = new URLSearchParams();
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
    return sendSave((signal) =>
      apiFetch<ProjectDetail>("/api/projects", {
        method: "POST",
        body: JSON.stringify(body),
        signal,
      }),
    );
  },

  update(id: string, body: UpdateBody): Promise<ProjectDetail> {
    return sendSave((signal) =>
      apiFetch<ProjectDetail>(`/api/projects/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
        signal,
      }),
    );
  },

  /** Hard-deletes the project and its files. There is no soft variant (#261). */
  delete(id: string): Promise<void> {
    return apiFetch(`/api/projects/${id}`, {
      method: "DELETE",
    });
  },

  duplicate(id: string): Promise<ProjectDetail> {
    return apiFetch<ProjectDetail>(`/api/projects/${id}/duplicate`, {
      method: "POST",
    });
  },
};
