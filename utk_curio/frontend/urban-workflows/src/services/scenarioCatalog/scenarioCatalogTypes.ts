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
  /** How many nodes it holds: its own nodes. */
  nodeCount: number;
  /** The scenario set it is in, in its project. */
  set?: { id: string; name: string };
  project: ScenarioProjectRef;
  /** Its project's graph, drawn as plain boxes with its own nodes marked. */
  preview: GraphPreview | null;
  /** The ids its card marks on `preview`: its own nodes, and the shared
   *  context and outcomes it keeps. */
  marks?: { members: string[]; context: string[]; outcomes: string[] };
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

/** A node of the scenario's shared context, its own nodes or its shared outcomes. */
export interface ScenarioNodeEntry {
  id: string;
  /** The node's template, `curio.builtin/vis-vega@1`. */
  type: string;
  /** Its title, when it has one. */
  label?: string;
  /** The outputs its project saved for it, for a node whose output the
   *  scenario saves (a context node whose output crosses into it, or a shared
   *  outcome); absent for another, which is listed without an output line. */
  results?: ScenarioResult[];
}

/** One scenario as `GET /api/scenarios/<project>/<scenario>` describes it:
 *  its parts by role (`scenarioParts`). */
export interface ScenarioDetails extends ScenarioRow {
  /** Its Shared context. */
  context: ScenarioNodeEntry[];
  /** Its Scenario-specific nodes. */
  levers: ScenarioNodeEntry[];
  /** Its Shared outcomes. */
  outcomes: ScenarioNodeEntry[];
}

/** A node of a saved spec, as a copy plan carries it. */
export interface SpecNodeShape {
  id: string;
  type?: string;
  x?: number;
  y?: number;
  content?: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SpecEdgeShape {
  id: string;
  source: string;
  target: string;
  type?: string;
  sourceHandle?: string;
  targetHandle?: string;
  [key: string]: unknown;
}

/** A node whose output crosses into what a drop copies, in its own project. */
export interface ScenarioCopyContext {
  nodeId: string;
  label: string;
  /** The node whose saved output stands for this one's, which arrives as data. */
  source?: { nodeId: string; copiedFrom: string[]; datasetId?: string };
}

/**
 * What `GET /api/scenarios/<project>/<scenario>/copy?target=<id>&present=<ids>`
 * says a drop of the scenario into the target copies, where the target's copy
 * of its set holds the scenarios *present* already. Ids are the source
 * project's.
 */
export interface ScenarioCopyPlan {
  scenario: { id: string; name: string; color: string; description: string };
  /** Its set in the source project. */
  set: { id: string; name: string };
  project: { id: string; name: string };
  /** Its Scenario-specific nodes. */
  nodes: string[];
  /** Its own last nodes, each with the copied nodes whose saved outputs stand for it. */
  last: { nodeId: string; sources: string[] }[];
  /** What crosses into the nodes it copies from outside, each arriving as data. */
  context: ScenarioCopyContext[];
  /** The set's shared outcomes that land with it: every input of theirs is in
   *  once it is. Each with the scenarios dragged or present that list it and
   *  the copied nodes whose saved outputs stand for it. */
  shared: { nodeId: string; label: string; scenarios: string[]; sources: string[] }[];
  /** The ids of its own shared outcomes. */
  outcomes: string[];
  /** Its nodes and the shared outcomes that land, and the edges into them. */
  dataflow: { nodes: SpecNodeShape[]; edges: SpecEdgeShape[] };
  /** Packages the target project gets. */
  packages: string[];
  /**
   * The context nodes with no saved output, which a run on the server makes
   * in the scenario's project before the copy; empty when every one has one.
   */
  toRun: { nodeId: string; label: string }[];
  /** Why the scenario cannot be dropped there; empty when it can. */
  problems: string[];
}

/** One saved output to copy: the source's node, and its copy's id. */
export interface ScenarioCopyOutput {
  source: string;
  node: string;
}

/** What `POST /api/scenarios/<project>/<scenario>/copy` did. */
export interface ScenarioCopyResult {
  /** The target project's packages, after. */
  packages: string[];
  /** Those it added. */
  added: string[];
  /** The dataset each context loader reads, by the loader's id. */
  datasets: Record<string, any>;
  /** Outputs restored for the copies, as opening a project restores them. */
  outputs: { node_id: string; filename: string; data_type?: string }[];
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

/** One project's scenarios, as Browse all lists them under its name. */
export interface ScenarioGroup {
  project: ScenarioProjectRef;
  items: ScenarioRow[];
}

/**
 * *items*, already sorted, under the projects they come from: a group per
 * project, placed where its first scenario is, with its scenarios in the same
 * order. So the sort orders the groups by their first scenario and the
 * scenarios within each group.
 */
export function groupScenariosByProject(items: readonly ScenarioRow[]): ScenarioGroup[] {
  const byProject = new Map<string, ScenarioGroup>();
  for (const row of items) {
    const group = byProject.get(row.project.id);
    if (group) {
      group.items.push(row);
    } else {
      byProject.set(row.project.id, { project: row.project, items: [row] });
    }
  }
  return Array.from(byProject.values());
}

/** One scenario set's scenarios, as Browse all lists them under its name. */
export interface ScenarioSetGroup {
  /** `<projectId>/<setId>`. */
  key: string;
  set: { id: string; name: string };
  project: ScenarioProjectRef;
  items: ScenarioRow[];
}

/**
 * *items*, already sorted, under their scenario sets: a project's sets
 * together, where its first scenario is (`groupScenariosByProject`), each set
 * where its first scenario is within them. A row from before sets is in a set
 * named after its project.
 */
export function groupScenariosBySet(items: readonly ScenarioRow[]): ScenarioSetGroup[] {
  const out: ScenarioSetGroup[] = [];
  for (const project of groupScenariosByProject(items)) {
    const bySet = new Map<string, ScenarioSetGroup>();
    for (const row of project.items) {
      const set = row.set?.id ? row.set : { id: "", name: row.project.name };
      const key = `${row.project.id}/${set.id}`;
      const group = bySet.get(key);
      if (group) group.items.push(row);
      else bySet.set(key, { key, set: { id: set.id, name: set.name || row.project.name }, project: row.project, items: [row] });
    }
    out.push(...bySet.values());
  }
  return out;
}
