import type { GraphPreview } from "../../api/projectsApi";

/** The project a scenario lives in. */
export interface ScenarioProjectRef {
  id: string;
  name: string;
  /** Seeded from Curio's examples. */
  isExample: boolean;
  updatedAt: string;
}

/** One scenario as `GET /api/scenarios/catalog` lists it. */
export interface ScenarioRow {
  /** `<projectId>/<scenarioId>`: a scenario's id is unique in its project only. */
  key: string;
  id: string;
  name: string;
  color: string;
  description: string;
  /** How many nodes it holds: its levers. */
  nodeCount: number;
  project: ScenarioProjectRef;
  /** Its project's graph, drawn as plain boxes with its own nodes marked. */
  preview: GraphPreview | null;
}

export interface ScenarioCatalogResponse {
  items: ScenarioRow[];
}

export interface ScenarioCatalogQuery {
  q?: string;
}

/** An output a project saved to the Data Catalog. */
export interface ScenarioResult {
  datasetId: string;
  /** The node that made it: the node itself, or what feeds a chart or a pool. */
  nodeId: string;
  title: string;
  format: string | null;
  rowCount: number | null;
  featureCount: number | null;
  updatedAt: string | null;
}

/** A node of the scenario's fixed context, levers or outcomes. */
export interface ScenarioNodeEntry {
  id: string;
  /** The node's template, `curio.builtin/vis-vega@1`. */
  type: string;
  /** Its title, when it has one. */
  label?: string;
  /** A Parameter node's one widget, with the value it holds. */
  parameter?: { name: string; value: unknown };
  results: ScenarioResult[];
}

/** One scenario as `GET /api/scenarios/<project>/<scenario>` describes it. */
export interface ScenarioDetails extends ScenarioRow {
  context: ScenarioNodeEntry[];
  levers: ScenarioNodeEntry[];
  outcomes: ScenarioNodeEntry[];
}

export type ScenarioSortMode = "recent" | "name" | "project";

export const SCENARIO_SORT_OPTIONS: { value: ScenarioSortMode; label: string }[] = [
  { value: "recent", label: "Recently edited" },
  { value: "name", label: "Name" },
  { value: "project", label: "Project" },
];

const byName = (a: ScenarioRow, b: ScenarioRow) => a.name.localeCompare(b.name);

export function sortScenarios(items: ScenarioRow[], mode: ScenarioSortMode): ScenarioRow[] {
  const rows = [...items];
  if (mode === "name") return rows.sort(byName);
  if (mode === "project") {
    return rows.sort((a, b) => a.project.name.localeCompare(b.project.name) || byName(a, b));
  }
  // Newest project first; a project's scenarios keep their own order.
  return rows.sort((a, b) => b.project.updatedAt.localeCompare(a.project.updatedAt));
}

/** The address of a scenario's details over the Scenario Catalog page. */
export function scenarioCatalogPath(row?: Pick<ScenarioRow, "project" | "id"> | null): string {
  if (!row) return "/catalog/scenarios";
  return `/catalog/scenarios/${encodeURIComponent(row.project.id)}/${encodeURIComponent(row.id)}`;
}
