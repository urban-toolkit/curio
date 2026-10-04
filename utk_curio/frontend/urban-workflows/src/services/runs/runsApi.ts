/**
 * Dataflow runs on the server (`utk_curio/backend/app/runs/routes.py`): start
 * one, follow it, stop it, and report a node only the browser can run.
 */
import type { MissingModuleNotice } from "../../types/nodeTypes";
import { apiFetch } from "../../utils/authApi";
import { postSseStream } from "../../utils/sseStream";

export type RunStatus =
  | "queued" | "running" | "succeeded" | "failed" | "needs_canvas" | "cancelled" | "interrupted";

/** What a run does with a node: execute it, pass its input on, or leave it to a tab. */
export type StepRole = "run" | "forward" | "browser";

export type StepStatus =
  | "pending" | "running" | "ok" | "error" | "skipped" | "cancelled" | "interrupted"
  | "forwarded" | "browser" | "waiting";

export interface RunStep {
  nodeId: string;
  label: string | null;
  nodeType: string | null;
  level: number | null;
  role: StepRole;
  status: StepStatus;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
  outputPath: string | null;
  outputType: string | null;
  installedDatasetId: string | null;
  codeSha256: string | null;
  stdoutTail: string | null;
  stderrTail: string | null;
  skipReason: string | null;
  /** The library the step's code could not import, as a run's reply names it. */
  missingModule?: MissingModuleNotice | null;
  /** Read by `getRun`: whether the node still holds the code this step ran. */
  codeCurrent?: boolean;
}

export interface Run {
  id: string;
  projectId: string;
  projectName: string | null;
  trigger: "all" | "node" | "rerun";
  targetNodeId: string | null;
  wholeDataflow: boolean;
  rerunOf: string | null;
  specRevision: number | null;
  status: RunStatus;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  counts: { ok: number; failed: number; skipped: number; waiting: number };
  error: string | null;
  live: boolean;
  steps?: RunStep[];
}

/** A run that has not ended. */
export const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set(["queued", "running"]);

/** The stream's events (`run_engine.run_events`, after the leading `run`). */
export type RunEvent =
  | { kind: "run"; run: Run }
  | { kind: "run_started"; nodeIds: string[] }
  | { kind: "step_started"; nodeId: string; startedAt: number }
  | {
      kind: "step_finished";
      nodeId: string;
      status: StepStatus;
      output?: { path?: string; dataType?: string; dataset?: string };
      stdoutTail?: string;
      stderrTail?: string;
      skipReason?: string;
      /** The reply Play would have had, stdout and stderr cut to their tails. */
      reply?: Record<string, unknown>;
      startedAt?: number;
      finishedAt?: number;
      durationMs?: number;
    }
  | { kind: "run_finished"; status: RunStatus; ok: number; failed: number; skipped: number; waiting: number };

export const runsApi = {
  /** Run the saved dataflow, or one node of it. A 409 carries `runId` when the dataflow already runs. */
  start(
    projectId: string,
    body: { target?: string; reuse?: Record<string, unknown>; specRevision?: number | null },
  ): Promise<Run> {
    return apiFetch<Run>(`/api/projects/${projectId}/runs`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** The dataflow's runs, newest first. */
  async listForProject(projectId: string, { limit = 1 } = {}): Promise<Run[]> {
    const body = await apiFetch<{ runs: Run[] }>(`/api/projects/${projectId}/runs?limit=${limit}`);
    return body.runs ?? [];
  },

  /** One run with its steps. */
  get(runId: string): Promise<Run> {
    return apiFetch<Run>(`/api/runs/${runId}`);
  },

  cancel(runId: string): Promise<Run> {
    return apiFetch<Run>(`/api/runs/${runId}/cancel`, { method: "POST" });
  },

  /** How a node only the browser runs went. */
  reportStep(runId: string, nodeId: string, body: { status: "ok" | "error"; message?: string }): Promise<Run> {
    return apiFetch<Run>(`/api/runs/${runId}/steps/${encodeURIComponent(nodeId)}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  /** Follow a run: its state, then its events replayed and live. Resolves when the stream ends. */
  follow(runId: string, onEvent: (event: RunEvent) => void, signal?: AbortSignal): Promise<void> {
    return postSseStream(
      `/api/runs/${runId}/stream`,
      undefined,
      (event, payload) => {
        if (event === "run") onEvent({ kind: "run", run: payload as unknown as Run });
        else onEvent({ kind: event, ...payload } as RunEvent);
      },
      signal,
      "GET",
    );
  },
};
