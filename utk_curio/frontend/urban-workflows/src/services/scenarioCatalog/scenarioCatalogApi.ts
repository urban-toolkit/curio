import { apiFetch } from "../../utils/authApi";
import type {
  ScenarioCatalogQuery,
  ScenarioCatalogResponse,
  ScenarioCopyOutput,
  ScenarioCopyPlan,
  ScenarioCopyResult,
  ScenarioDetails,
} from "./scenarioCatalogTypes";
import type { ScenarioDragPayload } from "./scenarioDrag";

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

  /** What dropping *drag*'s scenario into *targetProjectId* copies, where the
   *  copy of its set holds *present* already (its project's scenario ids).
   *  Changes nothing. */
  getCopyPlan(drag: ScenarioDragPayload, targetProjectId: string, present: readonly string[]): Promise<ScenarioCopyPlan> {
    const search = new URLSearchParams({ target: targetProjectId });
    if (present.length > 0) search.set("present", present.join(","));
    return apiFetch<ScenarioCopyPlan>(`${scenarioPath(drag.projectId, drag.scenarioId)}/copy?${search.toString()}`);
  },

  /** Copy the saved outputs and packages a drop needs into *targetProjectId*. */
  copyInto(
    drag: ScenarioDragPayload,
    targetProjectId: string,
    present: readonly string[],
    outputs: ScenarioCopyOutput[],
  ): Promise<ScenarioCopyResult> {
    return apiFetch<ScenarioCopyResult>(`${scenarioPath(drag.projectId, drag.scenarioId)}/copy`, {
      method: "POST",
      body: JSON.stringify({ targetProjectId, present, outputs }),
    });
  },
};
