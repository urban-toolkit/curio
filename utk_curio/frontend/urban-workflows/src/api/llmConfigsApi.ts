import { apiFetch } from "../utils/authApi";

/**
 * REST client for the account's LLM configurations (`/api/agents/llm`), the
 * configuration chosen per agent, and the model listing API Settings offers
 * while one is edited. Kept apart from `agentsApi` so the settings screen
 * does not pull in the agents bundle.
 *
 * No response carries a key: a configuration reports `hasApiKey` only, and a
 * key is sent once, in a create or an update, and never read back.
 */

/** One configuration of the user's own endpoint, as every response carries it. */
export interface LlmConfig {
  id: string;
  label: string;
  endpoint: "own";
  apiType: string;
  baseUrl: string;
  baseUrlHost: string;
  hasApiKey: boolean;
  model: string;
  createdAt: number | null;
  updatedAt: number | null;
}

/** One of this Curio's own endpoints: its name and its models, never its URL or key. */
export interface LlmDeploymentEndpoint {
  name: string;
  models: string[];
}

/** What this Curio offers of its own. Its endpoints' URLs and keys never leave the server. */
export interface LlmDeployment {
  /** "Curio's default". */
  label: string;
  apiType: string | null;
  /** Curio's default model (the first endpoint's first), or null without an endpoint file. */
  model: string | null;
  /** This Curio's endpoints, in the operator's order: any of their models can be picked. */
  endpoints: LlmDeploymentEndpoint[];
}

/** What answers a run now. */
export interface LlmActive {
  source: "assigned" | "default" | "deployment" | "guest" | "caller" | null;
  configId?: string | null;
  label?: string;
  model?: string;
  apiType?: string;
  /** Empty when it runs on this Curio's own endpoint. */
  baseUrlHost?: string;
  error?: string;
}

/** An agent whose configuration the account may choose. */
export interface LlmAgentRow {
  id: string;
  name: string;
  category: string;
  /** The capabilities its manifest declares. */
  capabilities?: string[];
  /** For an agent with Solve, the agents its Solve runs, by name, in the order it asks them. */
  solveRuns?: string[];
  /**
   * What is chosen for it: a configuration id, a pick of one of this Curio's
   * models (`curio:["<endpoint>","<model>"]`), `"deployment"` (Curio's
   * default), or null: it follows the rules.
   */
  choice: string | null;
  /** What it answers with when attached, or why nothing does. */
  answers: LlmActive;
}

export interface LlmListing {
  configs: LlmConfig[];
  /** The default: a configuration id or a pick of one of this Curio's models; null means Curio's default. */
  default: string | null;
  /** agentId to configuration id, pick or `"deployment"`, for the agents with a choice. */
  assignments: Record<string, string>;
  /** The agents whose configuration may be chosen, never an internal one. */
  agents: LlmAgentRow[];
  deployment: LlmDeployment;
  active: LlmActive;
  /** False for a guest on a hosted Curio, with the reason. */
  editable: boolean;
  reason: string | null;
  /** The local shared guest: everyone on this Curio shares the account. */
  shared: boolean;
  maxConfigs: number;
}

export interface LlmConfigInput {
  label?: string;
  endpoint?: "own";
  apiType?: string;
  baseUrl?: string;
  /** Write-only. Blank on an update keeps the stored key. */
  apiKey?: string;
  model?: string;
  /** Remove the stored key. */
  clearApiKey?: boolean;
}

export interface ModelListing {
  models: string[];
  listable: boolean;
  source?: "live" | "remembered";
  remembered?: string[];
  rememberedAt?: string | null;
  warning?: string | null;
}

const BASE = "/api/agents/llm";

export const llmConfigsApi = {
  listing(): Promise<LlmListing> {
    return apiFetch(BASE);
  },

  create(body: LlmConfigInput): Promise<{ config: LlmConfig }> {
    return apiFetch(`${BASE}/configs`, { method: "POST", body: JSON.stringify(body) });
  },

  update(id: string, body: LlmConfigInput): Promise<{ config: LlmConfig }> {
    return apiFetch(`${BASE}/configs/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  },

  /** Remove one; `moved` names the agents whose choice it was. */
  remove(id: string): Promise<{ deleted: string; moved: string[]; default: string | null }> {
    return apiFetch(`${BASE}/configs/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  /** Choose what agents run on: an id, a pick, `"deployment"`, or null to clear. */
  setAssignments(choices: Record<string, string | null>): Promise<LlmListing> {
    return apiFetch(`${BASE}/assignments`, { method: "PUT", body: JSON.stringify(choices) });
  },

  /** Copy a configuration, its key included, server-side. */
  duplicate(id: string, body: { label?: string; model?: string } = {}): Promise<{ config: LlmConfig }> {
    return apiFetch(`${BASE}/configs/${encodeURIComponent(id)}/duplicate`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** Choose the default: an id or a pick; null is Curio's default. */
  setDefault(configId: string | null): Promise<LlmListing> {
    return apiFetch(`${BASE}/default`, { method: "PUT", body: JSON.stringify({ configId }) });
  },

  /**
   * The models an endpoint serves, for the editor's Model field. Posted with
   * what is on screen. A stored key is used only when `configId` names the
   * configuration being edited and the endpoint is still its own; with none,
   * no key is borrowed.
   */
  models(input: {
    configId?: string;
    apiType?: string;
    baseUrl?: string;
    apiKey?: string;
  }): Promise<ModelListing> {
    return apiFetch("/api/agents/provider-models", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
};
