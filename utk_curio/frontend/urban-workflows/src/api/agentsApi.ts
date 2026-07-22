import { apiFetch, getToken } from "../utils/authApi";

const BACKEND_URL = process.env.BACKEND_URL || "";

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
  /**
   * The attachment's initial intent: the user's edit when present, otherwise
   * the definition's instruction prompt resolved server-side from the actual
   * prompt source (never duplicated client-side). Null when the definition has
   * no prompt asset.
   */
  intent: string | null;
  /** True when the intent is a user edit (an override of the prompt source). */
  intentEdited: boolean;
}

/** One persisted chat turn of an attachment's session. */
export interface AgentSessionTurn {
  role: "user" | "agent";
  text: string;
  ts?: string;
  /** Display-only failure marker; excluded from the agent's context. */
  error?: boolean;
}

export interface AgentSession {
  attachmentId: string;
  sessionId: string | null;
  turns: AgentSessionTurn[];
}

export interface AgentTarget {
  kind: "node" | "canvas" | "connection";
  targetId?: string;
}

/** The project-agent-default scope for one installed template (memo dev/23). */
export interface ProjectAgentDefaults {
  coord: string;
  name: string;
  revision: number;
  settings: Record<string, unknown>;
  effective: {
    quotas: { runsPerDay: { value: number; usedToday: number; source: string } };
    cost: { configured: boolean; source: string };
    resources: { source: string; provider?: string; model?: string };
  };
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

  /** The project-agent-default scope for one installed template (read-only at v1). */
  getProjectAgentDefaults(projectId: string, coord: string): Promise<ProjectAgentDefaults> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/defaults/${coordParam(coord)}`,
    );
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

  /** Set/clear the attachment's editable intent; null/empty restores the prompt source. */
  updateAttachmentIntent(
    projectId: string,
    attachmentId: string,
    intent: string | null,
  ): Promise<AgentAttachment> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: "PATCH", body: JSON.stringify({ intent }) },
    );
  },

  /** The attachment's persisted chat transcript (its session history). */
  getSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`,
    );
  },

  /** Clear the transcript; the attachment and its session id are kept. */
  clearSession(projectId: string, attachmentId: string): Promise<AgentSession> {
    return apiFetch(
      `/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/session`,
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

  /**
   * Run one turn and stream the reply as it is generated (memo dev/22).
   *
   * POSTs to the SSE endpoint via raw fetch (EventSource cannot POST), calls
   * `onDelta` per text chunk, and resolves with the full reply on the `done`
   * event. Pre-stream failures (quota 429, 404, …) throw an Error carrying
   * `status`/`body` like `apiFetch`; a mid-stream `error` event throws too.
   */
  async runAttachmentStream(
    projectId: string,
    attachmentId: string,
    message: string,
    onDelta: (text: string) => void,
  ): Promise<string> {
    const token = getToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(
      `${BACKEND_URL}/api/agents/projects/${encodeURIComponent(projectId)}/attachments/${encodeURIComponent(attachmentId)}/run/stream`,
      { method: "POST", headers, body: JSON.stringify({ message }) },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({} as Record<string, unknown>));
      const err = new Error((body as { error?: string }).error || `HTTP ${res.status}`);
      (err as Error & { status?: number; body?: unknown }).status = res.status;
      (err as Error & { status?: number; body?: unknown }).body = body;
      throw err;
    }
    if (!res.body) throw new Error("streaming not supported");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let reply: string | null = null;

    const handleFrame = (frame: string) => {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) return;
      const payload = JSON.parse(data) as { text?: string; reply?: string; error?: string };
      if (event === "delta" && payload.text) onDelta(payload.text);
      else if (event === "done") reply = payload.reply ?? "";
      else if (event === "error") throw new Error(payload.error || "agent run failed");
    };

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep >= 0) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        handleFrame(frame);
        sep = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) handleFrame(buffer);
    if (reply === null) throw new Error("stream ended without a reply");
    return reply;
  },
};
