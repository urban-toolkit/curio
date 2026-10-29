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
  /** The dataflow this one copies (Save a copy): a node whose output is the
   *  one that dataflow saved gets that saved output, whichever account owns
   *  it, copied from its owner's Data Catalog. */
  copy_of?: string;
}

export interface UpdateBody {
  spec?: Record<string, unknown>;
  outputs?: OutputRef[];
  name?: string;
  description?: string;
  thumbnail_accent?: string;
  /** Replaces the hand-set categories (`dataflow.categories`). */
  categories?: HandCategories;
}

/** What recording a canvas's outputs answers: the outputs the dataflow now
 *  records, and those that could not be installed in the Data Catalog. */
export interface RecordedOutputs {
  outputs: OutputRef[];
  dataset_install_warnings?: DatasetInstallWarning[];
  /** The dataflow's categories as it is now, which the canvas title shows. */
  categories?: DataflowCategories;
}

/** A tile's place and size on the dashboard page, as its node holds them;
 *  each pair is sent whole or not at all. */
export interface TileLayout {
  dashboardX?: number;
  dashboardY?: number;
  dashboardWidth?: number;
  dashboardHeight?: number;
}

/** How long the page waits for a dataflow to be made before it gives up.
 *  Generous, since a new dataflow installs every output it carries. */
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

  /**
   * The dataflow, its spec and its outputs: the saved ones, or with
   * `lastResults` the results its canvas was left with, each node its
   * owner's runs ran showing its newest kept result where one matches.
   */
  get(id: string, options?: { lastResults?: boolean }): Promise<LoadResponse> {
    return apiFetch<LoadResponse>(`/api/projects/${id}${options?.lastResults ? "?results=last" : ""}`);
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

  /** Record the outputs the owner's canvas holds that the dataflow records:
   *  no tab saves the dataflow, which its doc keeps. */
  recordOutputs(id: string, outputs: OutputRef[]): Promise<RecordedOutputs> {
    return sendSave((signal) =>
      apiFetch<RecordedOutputs>(`/api/projects/${id}/outputs`, {
        method: "POST",
        body: JSON.stringify({ outputs }),
        signal,
      }),
    );
  },

  /** An invited editor's rename on the canvas: the project row's name and the
   *  dataflow's, as the owner's name-only `update` renames them. */
  renameShared(id: string, name: string): Promise<{ id: string; name: string }> {
    return apiFetch<{ id: string; name: string }>(`/api/projects/${id}/name`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    });
  },

  /** The dashboard's Save layout: each tile's place and size, and nothing else. */
  saveLayout(id: string, tiles: Record<string, TileLayout>): Promise<{ saved: boolean }> {
    return apiFetch<{ saved: boolean }>(`/api/projects/${id}/dashboard/layout`, {
      method: "PUT",
      body: JSON.stringify({ tiles }),
    });
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
