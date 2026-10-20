/**
 * The scenario box each of a node's inputs comes from (#662), read from the
 * live graph: the node feeding each input circle, the box that node is in,
 * and the label the input's rows are named and drawn by. A node belongs to at
 * most one box. An input whose node is in no box is named by that node, in a
 * neutral color.
 *
 * A Vega-Lite chart that reads its inputs stacked as `inputs` names their
 * rows by these labels, an Autark map draws a layer in the color of its
 * input's box (adapters/node/autkScenarioColors), and a Compare Scenarios
 * node labels its inputs with them (utils/compare/compareInputs).
 *
 * Duck-typed nodes and edges, so this module needs no `reactflow` import.
 */
import { inputSlotOf, isDataEdge } from "../inputSlots";
import { nodeLabel } from "../../components/scenarios/scenarioLabels";
import { liveScenarios } from "./scenarioParts";
import type { Scenario } from "./scenarioModel";
import { NO_SCENARIO_COLOR, type ScenarioLabel } from "./scenarioColors";

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export interface InputScenario {
  /** Its circle, counted from 0. */
  slot: number;
  /** The node feeding it. */
  source: string;
  /** The box that node is in, or null. */
  scenario: Scenario | null;
  label: ScenarioLabel;
}

/** The box *nodeId* sits in, or null: the first box that holds it. */
export function scenarioOfNode(
  nodeId: string,
  nodes: readonly FlowNodeLike[],
  scenarios: readonly Scenario[],
): Scenario | null {
  return liveScenarios(scenarios, nodes).find((scenario) => scenario.nodes.includes(nodeId)) ?? null;
}

/**
 * The label of an input fed by the node *sourceId* (*source*), which sits in
 * *scenario*: the box's id, name and color, else the node's name in a neutral
 * color.
 */
export function inputLabelOf(
  scenario: Scenario | null,
  source: FlowNodeLike | undefined,
  sourceId: string,
): ScenarioLabel {
  return scenario
    ? { scenario: scenario.id, name: scenario.name, color: scenario.color }
    : { name: nodeLabel(source, sourceId), color: NO_SCENARIO_COLOR };
}

/** The wired inputs of node *nodeId*, in circle order, each with its box. */
export function inputScenarios(
  nodeId: string,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): InputScenario[] {
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
      return { slot, source, scenario, label: inputLabelOf(scenario, byId.get(source), source) };
    });
}
