import { apiFetch } from "../../utils/authApi";
import type {
  ScenarioCatalogQuery,
  ScenarioCatalogResponse,
  ScenarioDetails,
} from "./scenarioCatalogTypes";

function query(params: ScenarioCatalogQuery): string {
  const search = new URLSearchParams();
  if (params.q?.trim()) search.set("q", params.q.trim());
  const text = search.toString();
  return text ? `?${text}` : "";
}

/**
 * The Scenario Catalog's HTTP client. Scenarios live in projects, so both
 * routes read the account's projects; there is nothing to write here. A
 * scenario changes when its project is edited.
 */
export const scenarioCatalogApi = {
  listCatalog(params: ScenarioCatalogQuery = {}): Promise<ScenarioCatalogResponse> {
    return apiFetch<ScenarioCatalogResponse>(`/api/scenarios/catalog${query(params)}`);
  },

  getScenario(projectId: string, scenarioId: string): Promise<ScenarioDetails> {
    return apiFetch<ScenarioDetails>(
      `/api/scenarios/${encodeURIComponent(projectId)}/${encodeURIComponent(scenarioId)}`
    );
  },
};
