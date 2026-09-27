import { apiFetch } from "../utils/authApi";

/**
 * REST client for the account's LLM configurations (`/api/agents/llm`) and the
 * model listing AI Settings offers while one is edited. Kept apart from
 * `agentsApi` so the settings screen does not pull in the agents bundle.
 *
 * No response carries a key: a configuration reports `hasApiKey` only, and a
 * key is sent once, in a create or an update, and never read back.
 */

/** One configuration, as every response carries it. */
export interface LlmConfig {
  id: string;
  label: string;
  /** `own`: the user's type, URL and key. `deployment`: This Curio install. */
  endpoint: "own" | "deployment";
  apiType: string;
  baseUrl: string;
  baseUrlHost: string;
  hasApiKey: boolean;
  model: string;
  /** `trained`: made by activating a model trained in Curio. */
  origin: "user" | "trained";
  jobId?: string;
  sourceId?: string;
  createdAt: number | null;
  updatedAt: number | null;
}

/** What this Curio offers of its own. */
export interface LlmDeployment {
  label: string;
  /** This Curio install can be chosen as a configuration's endpoint. */
  endpointOffered: boolean;
  apiType: string | null;
  baseUrlHost: string | null;
  /** The Deployment default's model, or null when there is no Deployment default. */
  model: string | null;
}

/** What answers a run now. */
export interface LlmActive {
  source: "default" | "deployment" | "guest" | null;
  configId?: string | null;
  label?: string;
  model?: string;
  apiType?: string;
  baseUrlHost?: string;
  error?: string;
}

export interface LlmListing {
  configs: LlmConfig[];
  /** The default configuration's id; null means the Deployment default. */
  default: string | null;
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
  endpoint?: "own" | "deployment";
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

  remove(id: string): Promise<{ deleted: string; moved: string[]; default: string | null }> {
    return apiFetch(`${BASE}/configs/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  /** Copy a configuration, its key included, server-side. */
  duplicate(id: string, body: { label?: string; model?: string } = {}): Promise<{ config: LlmConfig }> {
    return apiFetch(`${BASE}/configs/${encodeURIComponent(id)}/duplicate`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** Choose the default; null is the Deployment default. */
  setDefault(configId: string | null): Promise<LlmListing> {
    return apiFetch(`${BASE}/default`, { method: "PUT", body: JSON.stringify({ configId }) });
  },

  /**
   * The models an endpoint serves, for the editor's Model field. Posted with
   * what is on screen. A stored key is used only when `configId` names the
   * configuration being edited and the endpoint is still its own, or when
   * `endpoint` is `"deployment"` (This Curio install); with neither, no key is
   * borrowed.
   */
  models(input: {
    configId?: string;
    endpoint?: "deployment";
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
