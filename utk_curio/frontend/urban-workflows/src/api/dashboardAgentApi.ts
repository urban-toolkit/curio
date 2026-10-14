import { apiFetch } from "../utils/authApi";
import type { AgentChange, AgentControl } from "../utils/dashboardAgent";

/**
 * REST client for the dashboard agent (`/api/agents/dashboard-chat`): one
 * turn that may set the dashboard's widgets and ask for a run. Nothing is
 * saved on the server; the page keeps the transcript.
 */

export interface DashboardChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface DashboardChatRequest {
  message: string;
  history: DashboardChatTurn[];
  controls: Omit<AgentControl, "nodeId">[];
  scenarios: string[];
  canRun: boolean;
}

export interface DashboardChatAnswer {
  reply: string;
  changes: AgentChange[];
  rejected: { id: string; problem: string }[];
  run: boolean;
  needsClarification: boolean;
}

export const dashboardAgentApi = {
  turn(body: DashboardChatRequest): Promise<DashboardChatAnswer> {
    return apiFetch("/api/agents/dashboard-chat", { method: "POST", body: JSON.stringify(body) });
  },
};
