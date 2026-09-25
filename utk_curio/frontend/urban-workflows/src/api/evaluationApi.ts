import { apiFetch } from "../utils/authApi";

/**
 * dev/123 (DEC-079): Evaluation mode. Runs one of Curio's own example prompts
 * through the real agent lifecycle with the model this account uses, then
 * scores the dataflow it built against the reference.
 *
 * Kept light beside `connectionKeysApi` and `trainingApi` for the dev/91
 * reason: a settings screen should not drag the vega-heavy `agentsApi` in.
 *
 * No type here carries an expected graph. The reference dataflow is read
 * server-side in the scoring phase and never reaches a client — a payload that
 * could carry it is one hop from being in a prompt.
 */

export interface EvaluationReadiness {
  configured: boolean;
  /** Populated when it is not configured: what to do about it. */
  reason: string;
  /** Where the model came from: the account's settings, or the start command. */
  source: "account" | "deployment" | "none";
  provider: { apiType: string; baseUrlHost: string; model: string };
  account: { apiType: string; baseUrlHost: string; model: string; hasApiKey: boolean };
  deployment: { apiType: string; baseUrlHost: string; model: string; hasApiKey: boolean };
}

export interface EvaluationFixture {
  fixtureId: string;
  prompt: string;
  context: string | null;
  tier: string;
  needs: string[];
  split: string;
  reviewStatus: "pending-owner-review" | "approved" | "rejected";
  reviewedBy: string | null;
  reviewedAt: string | null;
  source: string;
  required: { datasets: string[]; packages: string[]; paths?: string[] };
  expectedNodes: number;
  expectedEdges: number;
  skip: { when: string; reason: string; scope?: string }[];
}

export interface EvaluationScore {
  total: number;
  dimensions: Record<string, number | null>;
  weights: Record<string, number>;
  categories: string[];
  cappedByFabrication: boolean;
  notes: string[];
}

export interface EvaluationRun {
  runId: string;
  fixtureId: string;
  provider: { apiType: string; baseUrlHost: string; model: string };
  digests: Record<string, string>;
  projectId: string | null;
  attachmentId: string | null;
  phase:
    | "preparing" | "project" | "provisioning" | "installing" | "prompting"
    | "reviewing" | "solving" | "scoring" | "done"
    | "failed" | "cancelled" | "interrupted";
  reviewStatus: string;
  startedAt: string;
  finishedAt: string | null;
  latencyMs: number;
  usage: { inputTokens: number; outputTokens: number };
  score: EvaluationScore | null;
  comparison: Record<string, unknown> | null;
  failures: { phase: string; detail: string }[];
  applied: { tool: string; target: string; status?: string }[];
  pending: { tool: string; target: string; reason: string }[];
  events: { at: string; kind: string; [key: string]: unknown }[];
  cancelRequested: boolean;
  error: string | null;
  terminal: boolean;
}

const BASE = "/api/agents/evaluation";

export const evaluationApi = {
  /** Can a run happen, and which model would answer. */
  readiness(): Promise<EvaluationReadiness> {
    return apiFetch(`${BASE}/readiness`);
  },

  fixtures(): Promise<{ fixtures: EvaluationFixture[] }> {
    return apiFetch(`${BASE}/fixtures`);
  },

  /** Record a prompt review. A prompt is drafted by a model, approved by a person. */
  review(
    fixtureId: string,
    status: "approved" | "pending-owner-review",
  ): Promise<{ fixtureId: string; status: string; reviewedBy: string | null; reviewedAt: string | null }> {
    return apiFetch(`${BASE}/fixtures/${encodeURIComponent(fixtureId)}/review`, {
      method: "POST",
      body: JSON.stringify({ status }),
    });
  },

  start(fixtureId: string): Promise<EvaluationRun> {
    return apiFetch(`${BASE}/runs`, {
      method: "POST",
      body: JSON.stringify({ fixtureId }),
    });
  },

  list(): Promise<{ runs: EvaluationRun[]; inFlight: string | null }> {
    return apiFetch(`${BASE}/runs`);
  },

  status(runId: string): Promise<EvaluationRun> {
    return apiFetch(`${BASE}/runs/${encodeURIComponent(runId)}`);
  },

  cancel(runId: string): Promise<EvaluationRun> {
    return apiFetch(`${BASE}/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
  },
};

/** What each phase is called where a person can read it. */
export const PHASE_LABEL: Record<string, string> = {
  preparing: "preparing",
  project: "creating an isolated project",
  provisioning: "installing the datasets and packages",
  installing: "installing and attaching the Dataflow Builder",
  prompting: "waiting for the model",
  reviewing: "applying the plan",
  solving: "solving the nodes",
  scoring: "comparing with the reference",
  done: "finished",
  failed: "failed",
  cancelled: "cancelled",
  interrupted: "interrupted — the server stopped while it was running",
};
