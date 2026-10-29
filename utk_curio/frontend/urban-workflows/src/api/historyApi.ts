import { apiFetch } from "../utils/authApi";
import type { GraphPreview } from "./projectsApi";

/** Who made a version or an entry (`collaboration/history.py`): a person, or
 *  an agent with the account that asked it. */
export interface HistoryAuthor {
  kind?: string;
  account?: string;
  name?: string | null;
  agent?: string;
  agentName?: string;
}

/** A version of the dataflow: a point of its history the drawer lists. */
export interface ServerVersion {
  id: string;
  parent: string | null;
  /** When it was made, in milliseconds. */
  at: number;
  by?: HistoryAuthor | null;
  /** load, imported, graph, agent, typing, edit, saved, putBack or code. */
  kind: string;
  /** What changed: "Node added", "Ana edited", "Saved". */
  what?: string;
  /** The version a put-back put on the canvas. */
  restores?: string;
  /** The graph as it stood at the version, for its thumbnail. */
  preview?: GraphPreview | null;
}

export interface ServerVersions {
  versions: ServerVersion[];
  /** The version on the canvas. */
  head: string | null;
  /** Whether the dataflow has a history of its own yet. */
  kept: boolean;
  /** Whether you may clear it: the owner may. */
  canClear: boolean;
}

/** A node's run or edit, with its code (`NodeExecRecord`'s fields). */
export interface ServerEntry {
  id: number;
  parentId: number | null;
  code: string;
  inputs: string[];
  outputs: string[];
  startTime: string;
  endTime: string;
  kind?: "edit";
  label?: string;
  before?: string;
  /** The version it was made at. */
  point: string;
  by?: HistoryAuthor | null;
}

export interface ServerEntries {
  entries: ServerEntry[];
  /** The entry the node's next one descends from. */
  current: number | null;
}

export interface RunNote {
  code: string;
  inputs: string[];
  outputs: string[];
  startTime: string;
  endTime: string;
}

const base = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/history`;
const node = (projectId: string, nodeId: string) => `${base(projectId)}/nodes/${encodeURIComponent(nodeId)}`;
const post = (body?: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body ?? {}) });

/**
 * The history the server keeps of a dataflow (`projects/routes.py`), for its
 * owner and the editors the owner invited. A refusal rejects with the
 * server's sentence and its status: 403 for anyone else, 409 for code put
 * back after someone else changed the node.
 */
export const historyApi = {
  versions(projectId: string): Promise<ServerVersions> {
    return apiFetch<ServerVersions>(base(projectId));
  },

  entries(projectId: string, nodeId: string): Promise<ServerEntries> {
    return apiFetch<ServerEntries>(node(projectId, nodeId));
  },

  /** A run of the node on this tab. */
  noteRun(projectId: string, nodeId: string, run: RunNote): Promise<unknown> {
    return apiFetch(`${node(projectId, nodeId)}/runs`, post(run));
  },

  /** An edit made in the node's body (a Map Editor's), named *label*. */
  noteEdit(projectId: string, nodeId: string, label: string): Promise<unknown> {
    return apiFetch(`${node(projectId, nodeId)}/edits`, post({ label }));
  },

  /** Put *code* in the node, only if it still holds *from*. */
  writeCode(projectId: string, nodeId: string, change: { from: string; code: string; label: string }): Promise<unknown> {
    return apiFetch(`${node(projectId, nodeId)}/code`, post(change));
  },

  /** File > Save: a version named Saved. */
  saved(projectId: string): Promise<unknown> {
    return apiFetch(`${base(projectId)}/saved`, post());
  },

  /** Put the version back on the canvas, for every tab. `refused`: the nodes
   *  whose code someone changed meanwhile, which keep theirs. */
  putBack(projectId: string, versionId: string): Promise<{ refused: string[] }> {
    return apiFetch<{ refused: string[] }>(`${base(projectId)}/${encodeURIComponent(versionId)}/put-back`, post());
  },

  /** The owner clears the history before the version *versionId*. */
  clearBefore(projectId: string, versionId: string): Promise<{ first: string; versions: number }> {
    return apiFetch<{ first: string; versions: number }>(`${base(projectId)}/clear`, post({ before: versionId }));
  },
};
