/**
 * A dashboard viewer's runs (#1117; backend `runs/viewer_routes.py`): a
 * viewer changes a pinned control and the dataflow runs again on the server,
 * with nothing saved to it. None of these routes needs a sign-in.
 */
import dashboardRuns from "../../contracts/dashboardRuns.json";
import { apiFetch } from "../../utils/authApi";
import { postSseStream } from "../../utils/sseStream";
import type { DashboardValues } from "../../utils/widgets/dashboardControls";
import type { RunEvent } from "./runsApi";

/** The header a run is followed, and its private outputs read, with. */
export const RUN_TOKEN_HEADER: string = dashboardRuns.runTokenHeader;

/** What a start answers: a run and its token, or no run when nothing needs to run. */
export interface DashboardRunStart {
  runId: string | null;
  token: string | null;
  /** The run of these values was already going, and this start joined it. */
  joined: boolean;
  /** Every node the run plans, the steps whose events it sends. */
  nodeIds: string[];
}

/** One step's outcome, as a viewer's stream sends it: no reply, the artifacts its output holds. */
export type DashboardRunEvent = RunEvent & { artifactIds?: string[] };

/** What the page made of the steps a run left to it, under that run's token. */
export interface PageResults {
  token: string;
  /** Each step's output, as `keepStep` answered it. */
  browserOutputs: Record<string, string>;
}

/** What the run keeps of a step the page ran: its output and the artifacts it holds. */
export interface KeptStep {
  output: { path: string; dataType: string };
  artifactIds: string[];
}

const dashboardPath = (projectId: string) => `/api/projects/${encodeURIComponent(projectId)}/dashboard`;

export const dashboardRunsApi = {
  /**
   * Run the dashboard with *values*, or join the run of them already going.
   * With *page*, the steps a run left to this page stand on what the page made
   * of them, and the run is followed with the same token.
   */
  start(projectId: string, values: DashboardValues, page?: PageResults): Promise<DashboardRunStart> {
    return apiFetch<DashboardRunStart>(`${dashboardPath(projectId)}/runs`, {
      method: "POST",
      headers: page ? { [RUN_TOKEN_HEADER]: page.token } : {},
      body: JSON.stringify(page ? { values, browserOutputs: page.browserOutputs } : { values }),
    });
  },

  /** Send what the page made of *nodeId*, a step the run left to it, for the run to keep. */
  keepStep(projectId: string, runId: string, token: string, nodeId: string, value: unknown): Promise<KeptStep> {
    return apiFetch<KeptStep>(
      `${dashboardPath(projectId)}/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(nodeId)}`,
      { method: "POST", headers: { [RUN_TOKEN_HEADER]: token }, body: JSON.stringify({ value }) },
    );
  },

  /** Follow a run: its events, replayed and then live. Resolves when the stream ends. */
  follow(
    projectId: string,
    runId: string,
    token: string,
    onEvent: (event: DashboardRunEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    return postSseStream(
      `${dashboardPath(projectId)}/runs/${encodeURIComponent(runId)}/stream`,
      undefined,
      (event, payload) => onEvent({ kind: event, ...payload } as DashboardRunEvent),
      signal,
      "GET",
      { [RUN_TOKEN_HEADER]: token },
    );
  },
};
