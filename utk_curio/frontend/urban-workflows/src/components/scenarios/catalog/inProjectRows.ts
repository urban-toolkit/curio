import type { GraphPreview } from "../../../api/projectsApi";
import type {
  ScenarioDetails,
  ScenarioNodeEntry,
  ScenarioRow,
} from "../../../services/scenarioCatalog";
import { registeredCategory } from "../../../utils/graphPreviewCategories";
import type { Scenario } from "../../../utils/scenarios/scenarioModel";
import type { ScenarioParts } from "../../../utils/scenarios/scenarioParts";
import { nodeLabel } from "../scenarioLabels";

/**
 * A scenario of the open dataflow in the shapes the Scenario Catalog shows a
 * saved one in (`ScenarioRow`, `ScenarioDetails`), read off the canvas rather
 * than the server: the drawer's In project tab lists the dataflow's scenarios
 * as the canvas holds them, saved or not, with the card and the details
 * Browse all uses.
 */

type LiveNode = {
  id: string;
  type?: string | null;
  position?: { x: number; y: number };
  width?: number | null;
  height?: number | null;
  data?: any;
};

type LiveEdge = { source: string; target: string };

/** The open dataflow, as a row names its project. */
export interface LiveProject {
  /** Null until its first save. */
  id: string | null;
  name: string;
}

/** The canvas's graph as a saved project's preview draws it, each node in
 *  its registered descriptor's category. */
export function liveGraphPreview(nodes: readonly LiveNode[], edges: readonly LiveEdge[]): GraphPreview {
  return {
    nodes: nodes.map((node) => {
      const type = node.data?.nodeType ?? node.type ?? "";
      return {
        id: node.id,
        type,
        category: registeredCategory(type),
        x: node.position?.x ?? 0,
        y: node.position?.y ?? 0,
        w: node.width ?? null,
        h: node.height ?? null,
      };
    }),
    edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
  };
}

/** The scenario's card: its name, color, description and the nodes it holds
 *  on the canvas now. */
export function inProjectRow(
  scenario: Scenario,
  parts: ScenarioParts,
  project: LiveProject,
  preview: GraphPreview | null,
): ScenarioRow {
  return {
    key: `${project.id ?? ""}/${scenario.id}`,
    id: scenario.id,
    name: scenario.name,
    color: scenario.color,
    description: scenario.description ?? "",
    nodeCount: parts.levers.length,
    project: { id: project.id ?? "", name: project.name, isExample: false, updatedAt: "" },
    preview,
  };
}

/** Its details: its fixed context, levers and outcomes, each node by the
 *  label the canvas gives it. Nothing is said of saved outputs: what the
 *  canvas shows may not be saved yet. */
export function inProjectDetails(
  scenario: Scenario,
  parts: ScenarioParts,
  nodes: readonly LiveNode[],
  project: LiveProject,
  preview: GraphPreview | null,
): ScenarioDetails {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const entry = (id: string): ScenarioNodeEntry => {
    const node = byId.get(id);
    return { id, type: node?.data?.nodeType ?? node?.type ?? "", label: nodeLabel(node, id), results: [] };
  };
  return {
    ...inProjectRow(scenario, parts, project, preview),
    // What it keeps; a scenario that feeds nothing outside it shows its own
    // last nodes, as the catalog does.
    context: (scenario.context ?? parts.context).filter((id) => byId.has(id)).map(entry),
    levers: parts.levers.map(entry),
    outcomes: (scenario.outcomes?.length ? scenario.outcomes : parts.outcomes).filter((id) => byId.has(id)).map(entry),
  };
}
