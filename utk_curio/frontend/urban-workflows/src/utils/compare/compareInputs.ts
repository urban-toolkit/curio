/**
 * The scenarios a node comparing them reads (#662), from the live graph: the
 * node feeding each input circle, and the scenario that node belongs to, which
 * labels the input. A node belongs to at most one scenario. A Vega-Lite node
 * with its Compare scenarios switch on (utils/vegaCompare) reads its inputs
 * this way.
 *
 * Duck-typed nodes and edges, so this module needs no `reactflow` import.
 */
import { inputSlotOf, isDataEdge } from "../inputSlots";
import { liveScenarios } from "../scenarios/scenarioParts";
import type { Scenario } from "../scenarios/scenarioModel";
import { nodeLabel } from "../../components/scenarios/scenarioLabels";

/** What labels one input circle: its scenario, or the node's name. */
export interface CompareInputLabel {
  /** The scenario's id; absent for a node in no scenario. */
  scenario?: string;
  name: string;
  /** A CSS hex color, `#rrggbb`. */
  color: string;
}

/** The color of an input whose node is in no scenario. */
export const NO_SCENARIO_COLOR = "#8a8f98";

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export interface CompareInput {
  /** Its circle, counted from 0. */
  slot: number;
  /** The node feeding it. */
  source: string;
  /** The scenario that node is in, or null. */
  scenario: Scenario | null;
  label: CompareInputLabel;
}

/** The wired inputs of node *nodeId*, in circle order. */
export function compareInputs(
  nodeId: string,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): CompareInput[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const scenarioOf = new Map<string, Scenario>();
  for (const scenario of liveScenarios(scenarios, nodes)) {
    for (const id of scenario.nodes) if (!scenarioOf.has(id)) scenarioOf.set(id, scenario);
  }
  const sourceOf = new Map<number, string>();
  for (const edge of edges) {
    if (edge.target !== nodeId || !isDataEdge(edge)) continue;
    const slot = inputSlotOf(edge.targetHandle);
    if (slot >= 0 && !sourceOf.has(slot)) sourceOf.set(slot, edge.source);
  }
  return [...sourceOf.entries()]
    .sort(([a], [b]) => a - b)
    .map(([slot, source]) => {
      const scenario = scenarioOf.get(source) ?? null;
      const label: CompareInputLabel = scenario
        ? { scenario: scenario.id, name: scenario.name, color: scenario.color }
        : { name: nodeLabel(byId.get(source), source), color: NO_SCENARIO_COLOR };
      return { slot, source, scenario, label };
    });
}
