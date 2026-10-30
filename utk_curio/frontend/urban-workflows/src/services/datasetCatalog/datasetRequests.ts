/**
 * An invited editor's own dataset, asked of the dataflow's owner: the requests
 * of her install review (`datasets/application/editor_requests.py`).
 *
 * An editor's drop of a file, his Add to project and his drag of a card of his
 * own Data Catalog onto her dataflow each ask her (`useAskTheOwner`). Only she
 * applies or dismisses a request, on the review card an install an agent asks
 * for has (`AgentReviewCard`): a request is a `dataset.install` of
 * `contracts/agentInstalls.json`. Her Apply copies the dataset into her store
 * and adds it to the dataflow.
 *
 * The canvas holds the requests of its dataflow in one store, which the Data
 * Catalog drawer's provider loads, and loads again whenever the dataflow's
 * room says they changed (`DATASET_REQUESTS_CHANGED_EVENT`): the drawer shows
 * them, and a node that loads a dataset asked for says it waits for the owner.
 */
import { useSyncExternalStore } from "react";

import { apiFetch } from "../../utils/authApi";
import type { AgentProposalPart } from "../agents/types/proposal";

/** What the dataflow's room is told when its requests change. */
export const DATASET_REQUESTS_CHANGED_EVENT = "dataset_requests_changed";

/** One request in the owner's review. */
export interface DatasetRequest {
  proposalId: string;
  /** `dataset.install`, an install of `contracts/agentInstalls.json`. */
  tool: string;
  status: "pending";
  summary: string;
  preview: string;
  datasetId: string;
  datasetName: string;
  format?: string;
  /** The editor who asked, as a history point names a person. */
  by: { kind: "person"; account: string; name: string };
  /** The nodes the editor dropped it on or made with it. */
  nodeIds: string[];
  requestedAt?: string;
}

/** What an ask answers: the request, or why none was needed. */
export interface DatasetAsk {
  requested: boolean;
  reason?: "listed" | "shared";
  request?: DatasetRequest;
}

/** Who reads the requests: the dataflow's owner reviews them, an editor waits. */
export type DatasetRequestViewer = "owner" | "editor";

function requestsPath(dataflowId: string): string {
  return `/api/dataflows/${encodeURIComponent(dataflowId)}/datasets/requests`;
}

export const datasetRequestsApi = {
  async list(dataflowId: string): Promise<DatasetRequest[]> {
    const answer = await apiFetch<{ requests?: DatasetRequest[] }>(requestsPath(dataflowId));
    return answer?.requests ?? [];
  },

  /** An editor asks the owner for *datasetId*: dropped on the node *nodeId*,
   * or added with Add to project (*add*). */
  ask(dataflowId: string, body: { datasetId: string; nodeId?: string; add?: boolean }): Promise<DatasetAsk> {
    return apiFetch<DatasetAsk>(requestsPath(dataflowId), { method: "POST", body: JSON.stringify(body) });
  },

  apply(
    dataflowId: string,
    proposalId: string,
  ): Promise<{ status: string; installedDataset?: { id: string; name: string } }> {
    return apiFetch(`${requestsPath(dataflowId)}/${encodeURIComponent(proposalId)}/apply`, { method: "POST" });
  },

  dismiss(dataflowId: string, proposalId: string): Promise<{ status: string }> {
    return apiFetch(`${requestsPath(dataflowId)}/${encodeURIComponent(proposalId)}`, { method: "DELETE" });
  },
};

// ── The canvas's requests ────────────────────────────────────────────────────

interface Held {
  dataflowId: string | null;
  viewer: DatasetRequestViewer | null;
  requests: DatasetRequest[];
}

const NONE: Held = { dataflowId: null, viewer: null, requests: [] };
let held: Held = NONE;
let generation = 0;
const listeners = new Set<() => void>();

function hold(next: Held): void {
  held = next;
  for (const listener of Array.from(listeners)) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Read the requests of *dataflowId* into the store, for *viewer*; with no
 * dataflow, or for a watcher, the store holds none. A read that fails keeps
 * what the store held, and a read a later one overtook changes nothing.
 */
export async function loadDatasetRequests(
  dataflowId: string | null,
  viewer: DatasetRequestViewer | null,
): Promise<DatasetRequest[]> {
  const mine = ++generation;
  if (!dataflowId || !viewer) {
    hold(NONE);
    return [];
  }
  try {
    const requests = await datasetRequestsApi.list(dataflowId);
    if (mine === generation) hold({ dataflowId, viewer, requests });
    return requests;
  } catch {
    return held.dataflowId === dataflowId ? held.requests : [];
  }
}

/** Read the requests of the dataflow the store holds again. */
export function reloadDatasetRequests(): Promise<DatasetRequest[]> {
  return loadDatasetRequests(held.dataflowId, held.viewer);
}

/** The requests the store holds, with whose view of them. */
export function useHeldDatasetRequests(): Held {
  return useSyncExternalStore(subscribe, () => held);
}

/** A request as the review card shows it: an install of `agentInstalls.json`. */
export function datasetRequestPart(request: DatasetRequest): AgentProposalPart {
  return {
    type: "proposal",
    proposalId: request.proposalId,
    tool: request.tool,
    summary: request.summary,
    preview: request.preview,
    pins: { datasetId: request.datasetId },
    status: request.status,
  };
}

/** What the owner's Apply of a request does, as its card says it in place of
 * the line an agent's dataset install has: the dataset is copied into her
 * Data Catalog, from the editor's or from the shared one, and added to the
 * dataflow (`editor_requests.apply`). Said to her, and on an editor's canvas
 * of her. */
export function datasetRequestEffect(viewer: DatasetRequestViewer | null): string {
  return viewer === "owner"
    ? "Applying copies this dataset into your Data Catalog and adds it to this dataflow."
    : "Applying copies this dataset into the Data Catalog of the dataflow's owner and adds it to this dataflow.";
}

/** What a node that loads the dataset of *request* says of it: on an editor's
 * canvas it waits for the dataflow's owner, and on hers she is asked. */
export function datasetRequestWaitText(request: DatasetRequest, viewer: DatasetRequestViewer | null): string {
  return viewer === "owner"
    ? `${request.by.name} asks you to add ${request.datasetName} to this dataflow: review it in the Data Catalog.`
    : `Waits for the dataflow's owner to add ${request.datasetName} to it.`;
}
