import { apiFetch } from "../utils/authApi";

/**
 * dev/122 (DEC-078): Model training. Fine-tunes the configured model on
 * Curio's own approved example fixtures — or reports, in the endpoint's own
 * words, that this endpoint cannot.
 *
 * Kept light beside `connectionKeysApi` for the same dev/91 reason: nothing
 * here drags the vega-heavy `agentsApi` into a settings screen.
 *
 * Nothing in these types carries a credential. Capability is asked of the
 * endpoint and recorded, so `source: "remembered"` always arrives with the
 * date it was true — a recording presented as the present tense is how someone
 * ends up staring at a feature their endpoint does not have.
 */

export interface TrainingCapability {
  supported: boolean;
  /** Always populated: the endpoint's own reason, or why it could not be asked. */
  reason: string;
  baseModels: string[];
  surface: string;
  probedAt: string;
  source: "live" | "remembered";
  seenAt: string | null;
  provider: { apiType: string; baseUrlHost: string };
}

export interface TrainingConsent {
  destinationHost: string;
  rows: number;
  bytes: number;
  rowsDigest: string;
  fixtureIds: string[];
  licences: { fixtureId: string; licence: string }[];
  excluded: { fixtureId: string; reason: string }[];
  note: string;
  sentence: string;
}

export interface TrainingDataset {
  split: string;
  rows: number;
  bytes: number;
  sha256: string;
  fixtureIds: string[];
  excluded: { fixtureId: string; reason: string }[];
  instructionSha256: string;
  rosterDigest: string;
}

export interface TrainingPreview {
  dataset: TrainingDataset;
  consent: TrainingConsent;
  provider: { apiType: string; baseUrlHost: string };
}

export interface TrainingGate {
  satisfied: boolean;
  /** Present when it is not satisfied: which of the four refusals applies. */
  reason?: string;
  trainedModel?: string;
  split?: string;
  runId?: string;
  evaluatedAt?: string;
  fixtures?: number;
  scores?: Record<string, number>;
  meanScore?: number | null;
  comparator?: string;
  note?: string;
}

export interface TrainingJob {
  jobId: string;
  provider: { apiType: string; baseUrlHost: string; baseModel?: string };
  dataset: TrainingDataset;
  consent: Record<string, unknown>;
  providerJobId: string | null;
  status: "consented" | "queued" | "running" | "succeeded" | "failed" | "cancelled";
  rawStatus: string;
  /** When the endpoint was last asked. Shown, because a status without it is a guess. */
  statusReadAt: string;
  trainedModel: string | null;
  usage: { trainedTokens: number | null };
  cost: { operatorSupplied: boolean; estimatedUsd: number } | null;
  evaluation: Record<string, unknown> | null;
  activation: {
    activatedAt: string | null;
    previousModel: string | null;
    rolledBackAt: string | null;
  };
  events: { at: string; kind: string; [key: string]: unknown }[];
  createdAt: string;
  error: string | null;
  submitted: boolean;
  consentedOnly: boolean;
  gate?: TrainingGate | null;
  statusError?: string;
  rollbackNote?: string;
}

const BASE = "/api/agents/training";

export const trainingApi = {
  /** `refresh: false` serves the recording instead of re-probing the endpoint. */
  capability(refresh = true): Promise<TrainingCapability> {
    return apiFetch(`${BASE}/capability?refresh=${refresh ? "1" : "0"}`);
  },

  /** What would be sent. Its digest is what a later start must echo. */
  preview(split = "train"): Promise<TrainingPreview> {
    return apiFetch(`${BASE}/dataset/preview`, {
      method: "POST",
      body: JSON.stringify({ split }),
    });
  },

  start(input: {
    baseModel: string;
    rowsDigest: string;
    confirmed: boolean;
    split?: string;
  }): Promise<TrainingJob> {
    return apiFetch(`${BASE}/jobs`, { method: "POST", body: JSON.stringify(input) });
  },

  list(): Promise<{ jobs: TrainingJob[]; inFlight: string | null }> {
    return apiFetch(`${BASE}/jobs`);
  },

  status(jobId: string): Promise<TrainingJob> {
    return apiFetch(`${BASE}/jobs/${encodeURIComponent(jobId)}`);
  },

  cancel(jobId: string): Promise<TrainingJob> {
    return apiFetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
    });
  },

  /** Refused unless a held-out evaluation of this exact model exists. */
  activate(jobId: string): Promise<TrainingJob> {
    return apiFetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/activate`, {
      method: "POST",
    });
  },

  rollback(jobId: string): Promise<TrainingJob> {
    return apiFetch(`${BASE}/jobs/${encodeURIComponent(jobId)}/rollback`, {
      method: "POST",
    });
  },
};
