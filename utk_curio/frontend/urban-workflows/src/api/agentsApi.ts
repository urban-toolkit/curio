import { apiFetch } from "../utils/authApi";

/**
 * REST client for ``/api/agents`` — the three-scope Agents Catalog and its
 * lifecycle commands. Mirrors ``packagesApi.ts``: every request goes through
 * the shared ``apiFetch`` (Bearer header + JSON parse + error handling).
 *
 * The three scopes:
 *  - Global Catalog       → ``catalog()`` (the built-in definitions)
 *  - My Imports (account) → ``listImports()`` + ``import``/``removeImport``
 *  - Installed in project → ``listProjectAgents()`` + ``install``/``uninstall``
 *
 * Import (account) and Install (project) are separate commands; neither chains.
 */

/** One agent card as returned by the backend (camelCase). */
export interface AgentCard {
  id: string; // e.g. "agent.node-explainer"
  version: string;
  dirName: string; // "<id>@<version>"
  name: string;
  category: string; // data | node | canvas | package | evaluate
  purpose: string;
  capabilities: string[];
  hooks: string[]; // compatible target kinds: node | canvas | connection
  provenance: { publisher: string; trust: string | null };
  imported: boolean;
  installedInProject: boolean;
  published: boolean;
  /** Eligible for Publish: an owned, store-backed definition (not a built-in). */
  publishable: boolean;
  scope: "global" | "my-imports" | "installed";
}

interface AgentListResponse {
  agents: AgentCard[];
}

/** A private agent instance attached to a node/canvas/connection. */
export interface AgentAttachment {
  attachmentId: string;
  coord: string;
  target: { kind: "node" | "canvas" | "connection"; targetId?: string };
  sessionId: string;
  revision: number;
  name: string;
  category: string | null;
  hooks: string[];
}

export interface AgentTarget {
  kind: "node" | "canvas" | "connection";
  targetId?: string;
}

/** ``@``/``.`` are legal in a coordinate but must be escaped in a path param. */
function coordParam(coord: string): string {
  return encodeURIComponent(coord);
}

export const agentsApi = {
  /** Global Catalog — the built-in definitions. Pass a projectId to mark installed ones. */
  catalog(projectId?: string): Promise<AgentListResponse> {
    const q = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return apiFetch(`/api/agents/catalog${q}`);
  },

  /** Account "My Imports". */
  listImports(): Promise<AgentListResponse> {
    return apiFetch("/api/agents/imports");
  },

  /** Record a definition coordinate in My Imports (does not install into a project). */
  import(coord: string): Promise<{ coord: string; imported: boolean }> {
    return apiFetch("/api/agents/imports", {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /** Drop a coordinate from My Imports. */
  removeImport(coord: string): Promise<{ coord: string; imported: boolean }> {
    return apiFetch(`/api/agents/imports/${coordParam(coord)}`, { method: "DELETE" });
  },

  /** Agents installed in a project's ``dataflow.agents`` lockfile. */
  listProjectAgents(projectId: string): Promise<AgentListResponse> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}`);
  },

  /** Install a definition into a project (explicit; never auto-imports). */
  installToProject(projectId: string, coord: string): Promise<{ agents: string[] }> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/install`, {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /** Remove a definition from a project's lockfile. */
  uninstallFromProject(projectId: string, coord: string): Promise<{ agents: string[] }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/${coordParam(coord)}`,
      { method: "DELETE" },
    );
  },

  /** Publish an owned, imported definition to the Global Catalog (imported-only). */
  publish(coord: string): Promise<{ coord: string; published: boolean }> {
    return apiFetch("/api/agents/publications", {
      method: "POST",
      body: JSON.stringify({ coord }),
    });
  },

  /** Unpublish an owned definition (owner only). */
  unpublish(coord: string): Promise<{ coord: string; published: boolean }> {
    return apiFetch(`/api/agents/publications/${coordParam(coord)}`, { method: "DELETE" });
  },

  /** List the project's private attachments. */
  listAttachments(projectId: string): Promise<{ attachments: AgentAttachment[] }> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/attachments`);
  },

  /** Attach an installed template to a target (requires it installed; never auto-installs). */
  attach(projectId: string, coord: string, target: AgentTarget): Promise<AgentAttachment> {
    return apiFetch(`/api/agents/projects/${encodeURIComponent(projectId)}/attachments`, {
      method: "POST",
      body: JSON.stringify({ coord, target }),
    });
  },

  /** Detach a private instance. */
  detachAttachment(
    projectId: string,
    attachmentId: string,
  ): Promise<{ attachmentId: string; detached: boolean }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "DELETE" },
    );
  },

  /** Run one turn of an attached agent and get its reply. */
  runAttachment(
    projectId: string,
    attachmentId: string,
    message: string,
  ): Promise<{ attachmentId: string; coord: string; reply: string }> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/run`,
      { method: "POST", body: JSON.stringify({ message }) },
    );
  },
};
