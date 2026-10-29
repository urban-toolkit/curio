import { apiFetch } from "../../utils/authApi";
import type {
  ScenarioCatalogQuery,
  ScenarioCatalogResponse,
  ScenarioCopyOutput,
  ScenarioCopyPlan,
  ScenarioCopyResult,
  ScenarioDetails,
  ScenarioSetDetails,
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

function setPath(drag: Pick<ScenarioDragPayload, "projectId" | "setId">): string {
  return `/api/scenarios/sets/${encodeURIComponent(drag.projectId)}/${encodeURIComponent(drag.setId)}`;
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

  /** A scenario set: its scenarios, and which of them use each shared node. */
  getSet(projectId: string, setId: string): Promise<ScenarioSetDetails> {
    return apiFetch<ScenarioSetDetails>(
      `/api/scenarios/sets/${encodeURIComponent(projectId)}/${encodeURIComponent(setId)}`,
    );
  },

  /** What dropping *drag*'s scenarios into *targetProjectId* copies. Changes
   *  nothing. A scenario of no set is asked for alone. */
  getCopyPlan(drag: ScenarioDragPayload, targetProjectId: string): Promise<ScenarioCopyPlan> {
    const target = `target=${encodeURIComponent(targetProjectId)}`;
    if (!drag.setId) {
      return apiFetch<ScenarioCopyPlan>(`${scenarioPath(drag.projectId, drag.scenarioIds[0])}/copy?${target}`);
    }
    const scenarios = drag.scenarioIds.map(encodeURIComponent).join(",");
    return apiFetch<ScenarioCopyPlan>(`${setPath(drag)}/copy?${target}&scenarios=${scenarios}`);
  },

  /** Copy the saved outputs and packages a drop needs into *targetProjectId*. */
  copyInto(drag: ScenarioDragPayload, targetProjectId: string, outputs: ScenarioCopyOutput[]): Promise<ScenarioCopyResult> {
    const body = drag.setId
      ? { targetProjectId, scenarioIds: drag.scenarioIds, outputs }
      : { targetProjectId, outputs };
    const path = drag.setId ? setPath(drag) : scenarioPath(drag.projectId, drag.scenarioIds[0]);
    return apiFetch<ScenarioCopyResult>(`${path}/copy`, { method: "POST", body: JSON.stringify(body) });
  },
};
