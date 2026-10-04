import { apiFetch } from "../../utils/authApi";
import type {
  ScenarioCatalogQuery,
  ScenarioCatalogResponse,
  ScenarioCopyOutput,
  ScenarioCopyPlan,
  ScenarioCopyResult,
  ScenarioDetails,
} from "./scenarioCatalogTypes";

function query(params: ScenarioCatalogQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  const text = search.toString();
  return text ? `?${text}` : "";
}

function scenarioPath(projectId: string, scenarioId: string): string {
  return `/api/scenarios/${encodeURIComponent(projectId)}/${encodeURIComponent(scenarioId)}`;
}

/**
 * The Scenario Catalog's HTTP client. Scenarios live in projects, so the
 * reads read the account's projects. A scenario changes when its project is
 * edited; a drag of one into another dataflow copies what that needs into it.
 */
export const scenarioCatalogApi = {
  listCatalog(params: ScenarioCatalogQuery = {}): Promise<ScenarioCatalogResponse> {
    return apiFetch<ScenarioCatalogResponse>(`/api/scenarios/catalog${query(params)}`);
  },

  getScenario(projectId: string, scenarioId: string): Promise<ScenarioDetails> {
    return apiFetch<ScenarioDetails>(scenarioPath(projectId, scenarioId));
  },

  /** What dropping the scenario into *targetProjectId* copies. Changes nothing. */
  getCopyPlan(projectId: string, scenarioId: string, targetProjectId: string): Promise<ScenarioCopyPlan> {
    return apiFetch<ScenarioCopyPlan>(
      `${scenarioPath(projectId, scenarioId)}/copy?target=${encodeURIComponent(targetProjectId)}`
    );
  },

  /** Copy the saved outputs and packages a drop needs into *targetProjectId*. */
  copyInto(
    projectId: string,
    scenarioId: string,
    targetProjectId: string,
    outputs: ScenarioCopyOutput[],
  ): Promise<ScenarioCopyResult> {
    return apiFetch<ScenarioCopyResult>(`${scenarioPath(projectId, scenarioId)}/copy`, {
      method: "POST",
      body: JSON.stringify({ targetProjectId, outputs }),
    });
  },
};
