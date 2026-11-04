/**
 * What an invited editor asks the owner of a dataflow to add to it: the
 * requests of her install review (`projects/editor_requests.py`).
 *
 * An editor's tab adds nothing of his own to her dataflow. A dataset, layer
 * group or collection of his Data Catalog (a file he drops, his Add to
 * project, a card he drags), and a package or model of his store or of the
 * shared catalog (his Add to project, a card he drops, a model he drops on a
 * node) each ask her instead (`useAskTheOwner`). Only she applies or dismisses
 * a request, on the review card an install an agent asks for has
 * (`AgentReviewCard`): a request is a `dataset.install` or a `package.install`
 * of `contracts/agentInstalls.json`, kept by its kind's routes.
 *
 * The canvas holds the requests of its dataflow in one store, which the Data
 * Catalog drawer's provider loads, and loads again whenever the dataflow's
 * room says they changed (`EDITOR_REQUESTS_CHANGED_EVENT`). Each catalog
 * drawer shows the requests of its kind (`EditorRequestsSection`), and a node
 * a request names says it waits for the owner.
 */
import { useEffect, useSyncExternalStore } from "react";

import { apiFetch } from "../utils/authApi";
import { describePackagePermission } from "../utils/packagePermissions";
import type { AgentProposalPart } from "./agents/types/proposal";
import type { PackagePayload, ResolveConflict } from "./packages/types";

/** What the dataflow's room is told when its requests change. */
export const EDITOR_REQUESTS_CHANGED_EVENT = "editor_requests_changed";

/** The kinds of request, as their routes name them. */
export type RequestKind = "datasets" | "packages";

/** The editor who asked, as a history point names a person. */
export interface RequestAsker {
  kind: "person";
  account: string;
  name: string;
}

interface RequestBase {
  proposalId: string;
  /** Missing on a request kept before there were kinds: a dataset's. */
  kind?: RequestKind;
  /** `dataset.install` or `package.install`, installs of `contracts/agentInstalls.json`. */
  tool: string;
  status: "pending";
  summary: string;
  preview: string;
  by: RequestAsker;
  /** The nodes the editor dropped it on or made with it. */
  nodeIds: string[];
  /** For an item of a shared catalog, which no copy brings. */
  shared?: boolean;
  requestedAt?: string;
}

/** A request for a dataset, a layer group or a collection. */
export interface DatasetRequest extends RequestBase {
  datasetId: string;
  datasetName: string;
  /** `collection` for a collection. */
  format?: string;
}

/** A request for a node package or a model package. */
export interface PackageRequest extends RequestBase {
  kind: "packages";
  /** `<packageId>@<major>`. */
  dirName: string;
  packageName: string;
  packageKind: "node" | "model";
  version: string;
  publisher: string;
  permissions: string[];
}

export type EditorRequest = DatasetRequest | PackageRequest;

/** What an ask answers: the request, or why none was needed. */
export interface RequestAsk {
  requested: boolean;
  reason?: "listed" | "shared";
  request?: EditorRequest;
}

/** What the owner's review of a package request shows before her Apply. */
export interface PackageRequestReview {
  package: PackagePayload;
  conflicts: ResolveConflict[];
}

/** Who reads the requests: the dataflow's owner reviews them, an editor waits. */
export type RequestViewer = "owner" | "editor";

/** The catalog drawer that shows a request: the Data, Node or Model Catalog's. */
export type RequestCatalog = "datasets" | "node" | "model";

export function isPackageRequest(request: EditorRequest): request is PackageRequest {
  return request.kind === "packages";
}

export function isDatasetRequest(request: EditorRequest): request is DatasetRequest {
  return !isPackageRequest(request);
}

/** The catalog drawer *request* shows in. */
export function requestCatalog(request: EditorRequest): RequestCatalog {
  if (!isPackageRequest(request)) return "datasets";
  return request.packageKind === "model" ? "model" : "node";
}

/** The name of what *request* asks for. */
export function requestedName(request: EditorRequest): string {
  return isPackageRequest(request) ? request.packageName : request.datasetName;
}

function requestsPath(dataflowId: string, kind: RequestKind): string {
  return `/api/dataflows/${encodeURIComponent(dataflowId)}/${kind}/requests`;
}

function requestPath(dataflowId: string, request: EditorRequest): string {
  return `${requestsPath(dataflowId, request.kind ?? "datasets")}/${encodeURIComponent(request.proposalId)}`;
}

export const editorRequestsApi = {
  async list(dataflowId: string, kind: RequestKind): Promise<EditorRequest[]> {
    const answer = await apiFetch<{ requests?: EditorRequest[] }>(requestsPath(dataflowId, kind));
    return answer?.requests ?? [];
  },

  /** An editor asks the owner for a dataset (`datasetId`) or a package
   * (`dirName`): dropped on the node *nodeId*, or added with Add to project
   * (*add*). */
  ask(
    dataflowId: string,
    kind: RequestKind,
    body: { datasetId?: string; dirName?: string; nodeId?: string; add?: boolean },
  ): Promise<RequestAsk> {
    return apiFetch<RequestAsk>(requestsPath(dataflowId, kind), { method: "POST", body: JSON.stringify(body) });
  },

  /** What the owner's review of a package request shows: the package and its conflicts. */
  review(dataflowId: string, request: EditorRequest): Promise<PackageRequestReview> {
    return apiFetch<PackageRequestReview>(`${requestPath(dataflowId, request)}/review`);
  },

  apply(dataflowId: string, request: EditorRequest): Promise<{ status: string }> {
    return apiFetch(`${requestPath(dataflowId, request)}/apply`, { method: "POST" });
  },

  dismiss(dataflowId: string, request: EditorRequest): Promise<{ status: string }> {
    return apiFetch(requestPath(dataflowId, request), { method: "DELETE" });
  },
};

// ── The canvas's requests ────────────────────────────────────────────────────

interface Held {
  dataflowId: string | null;
  viewer: RequestViewer | null;
  requests: EditorRequest[];
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
 * Read the requests of *dataflowId*, every kind's, into the store, for
 * *viewer*; with no dataflow, or for a watcher, the store holds none. A kind
 * whose read fails keeps what the store held of it, and a read a later one
 * overtook changes nothing.
 */
export async function loadEditorRequests(
  dataflowId: string | null,
  viewer: RequestViewer | null,
): Promise<EditorRequest[]> {
  const mine = ++generation;
  if (!dataflowId || !viewer) {
    hold(NONE);
    return [];
  }
  const kept = held.dataflowId === dataflowId ? held.requests : [];
  const read = async (kind: RequestKind): Promise<EditorRequest[]> => {
    try {
      const requests = await editorRequestsApi.list(dataflowId, kind);
      return requests.map((request) => ({ ...request, kind }) as EditorRequest);
    } catch {
      return kept.filter((request) => (request.kind ?? "datasets") === kind);
    }
  };
  const [datasets, packages] = await Promise.all([read("datasets"), read("packages")]);
  const requests = [...datasets, ...packages];
  if (mine === generation) hold({ dataflowId, viewer, requests });
  return requests;
}

/** Read the requests of the dataflow the store holds again. */
export function reloadEditorRequests(): Promise<EditorRequest[]> {
  return loadEditorRequests(held.dataflowId, held.viewer);
}

/** The requests the store holds, with whose view of them. */
export function useHeldEditorRequests(): Held {
  return useSyncExternalStore(subscribe, () => held);
}

/** The pending request a node waits on: one for the dataset it loads
 * (*datasetId*), or for the package it comes from (*dirName*), or one that
 * names it (a model dropped on it). */
export function requestFor(
  requests: readonly EditorRequest[],
  { datasetId, dirName, nodeId }: { datasetId?: string; dirName?: string; nodeId?: string },
): EditorRequest | undefined {
  return requests.find((request) =>
    isPackageRequest(request)
      ? (!!dirName && request.dirName === dirName) || (!!nodeId && request.nodeIds.includes(nodeId))
      : !!datasetId && request.datasetId === datasetId,
  );
}

// ── What the review card and a waiting node say ─────────────────────────────

/** A package's permissions in plain words, as its card says what it may do. */
export function permissionsLine(permissions: readonly string[]): string {
  if (permissions.length === 0) return "Permissions requested: none";
  const each = permissions.map((permission) => {
    const meaning = describePackagePermission(permission);
    return meaning ? `${permission} (${meaning})` : permission;
  });
  return `Permissions requested: ${each.join("; ")}`;
}

/** A request as the review card shows it: an install of `agentInstalls.json`.
 * A package's says what it may do under its name, version and publisher. */
export function requestPart(request: EditorRequest): AgentProposalPart {
  return {
    type: "proposal",
    proposalId: request.proposalId,
    tool: request.tool,
    summary: request.summary,
    preview: isPackageRequest(request)
      ? `${request.preview}\n${permissionsLine(request.permissions ?? [])}`
      : request.preview,
    pins: isPackageRequest(request) ? { dirName: request.dirName } : { datasetId: request.datasetId },
    status: request.status,
  };
}

/** Whether *request* is for an item of a shared catalog, which no copy brings. */
function fromTheSharedCatalog(request: EditorRequest): boolean {
  return request.shared === true;
}

/** What the owner's Apply of *request* does, as its card says it in place of
 * the line an agent's install has (`editor_requests.apply` and each kind's):
 * said to her, and on an editor's canvas of her. */
export function requestEffect(request: EditorRequest, viewer: RequestViewer | null): string {
  const owner = viewer === "owner";
  if (isPackageRequest(request)) {
    const model = request.packageKind === "model";
    const noun = model ? "model" : "package";
    const catalog = model ? "Model Catalog" : "Node Catalog";
    const review = "Applying opens its review (permissions, libraries, conflicts).";
    if (fromTheSharedCatalog(request)) {
      return owner
        ? `${review} Confirming there installs the ${noun} from the shared ${catalog} with its libraries and adds it to this dataflow.`
        : `Applying installs the ${noun} from the shared ${catalog} into the account of the dataflow's owner and adds it to this dataflow.`;
    }
    const copied = model ? "the model with its weights" : "the package";
    return owner
      ? `${review} Confirming there checks its files, copies ${copied} into your ${catalog} unless it is there already, installs its libraries under your account and adds it to this dataflow.`
      : `Applying copies ${copied} into the ${catalog} of the dataflow's owner, installs its libraries under the owner's account and adds it to this dataflow.`;
  }
  if (fromTheSharedCatalog(request)) {
    return owner
      ? "Applying adds this dataset of the shared Data Catalog to this dataflow."
      : "Applying adds this dataset of the shared Data Catalog to this dataflow, for the dataflow's owner.";
  }
  if (request.format === "collection") {
    return owner
      ? "Applying copies this collection into your Data Catalog, its files with its index, and adds it to this dataflow."
      : "Applying copies this collection into the Data Catalog of the dataflow's owner, its files with its index, and adds it to this dataflow.";
  }
  return owner
    ? "Applying copies this dataset into your Data Catalog and adds it to this dataflow."
    : "Applying copies this dataset into the Data Catalog of the dataflow's owner and adds it to this dataflow.";
}

const CATALOG_NAME: Record<RequestCatalog, string> = {
  datasets: "Data Catalog",
  node: "Node Catalog",
  model: "Model Catalog",
};

/** What a node a request names says of it: on an editor's canvas it waits
 * for the dataflow's owner, and on hers she is asked. */
export function requestWaitText(request: EditorRequest, viewer: RequestViewer | null): string {
  const name = requestedName(request);
  return viewer === "owner"
    ? `${request.by.name} asks you to add ${name} to this dataflow: review it in the ${CATALOG_NAME[requestCatalog(request)]}.`
    : `Waits for the dataflow's owner to add ${name} to it.`;
}

/** What the owner is told of requests she was not told of yet. */
export function requestsToldText(fresh: readonly EditorRequest[]): string {
  return fresh.length === 1
    ? `${fresh[0].by.name} asks you to add ${requestedName(fresh[0])} to this dataflow.`
    : `${fresh.length} items your editors asked for wait for your review.`;
}

// ── Opening the review ──────────────────────────────────────────────────────

/** Asks the catalog drawer of a kind to open, where its requests wait. */
export const REVIEW_REQUESTS_EVENT = "curio:review-editor-requests";

/** Open the catalog drawer *catalog*'s requests show in. */
export function openRequestsReview(catalog: RequestCatalog): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<RequestCatalog>(REVIEW_REQUESTS_EVENT, { detail: catalog }));
}

/** A catalog drawer's provider's side: *open* runs when the review of the
 * requests of *catalog* is asked for (`openRequestsReview`). */
export function useOpensForRequests(catalog: RequestCatalog, open: () => void): void {
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onReview = (event: Event) => {
      if ((event as CustomEvent<RequestCatalog>).detail === catalog) open();
    };
    window.addEventListener(REVIEW_REQUESTS_EVENT, onReview);
    return () => window.removeEventListener(REVIEW_REQUESTS_EVENT, onReview);
  }, [catalog, open]);
}
