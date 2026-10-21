/**
 * The scenario box each of a node's inputs comes from (#662), read from the
 * live graph: the node feeding each input circle, the box that node is in,
 * and the label the input's rows are named and drawn by. A node belongs to at
 * most one box. An input whose node is in no box is named by that node, in a
 * neutral color.
 *
 * A Vega-Lite chart that reads its inputs stacked as `inputs` names their
 * rows by these labels and draws them in the boxes' colors and order
 * (`scaleLabelsOf`), and an Autark map draws a layer in the color of its
 * input's box (adapters/node/autkScenarioColors).
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

/**
 * The labels a chart's scales draw *inputs* with: each box once, in the order
 * the dataflow lists its boxes (*scenarios*), then each input from no box, in
 * circle order. The rows themselves stack in circle order.
 */
export function scaleLabelsOf(inputs: readonly InputScenario[], scenarios: readonly Scenario[]): ScenarioLabel[] {
  const listed = new Map(scenarios.map((scenario, index) => [scenario.id, index]));
  const boxes = new Map<string, ScenarioLabel>();
  for (const input of inputs) {
    if (input.scenario && !boxes.has(input.scenario.id)) boxes.set(input.scenario.id, input.label);
  }
  const place = (id: string) => listed.get(id) ?? Number.MAX_SAFE_INTEGER;
  return [
    ...[...boxes.entries()].sort(([a], [b]) => place(a) - place(b)).map(([, label]) => label),
    ...inputs.filter((input) => !input.scenario).map((input) => input.label),
  ];
}

/**
 * The labels a chart reading `inputs` draws `scenario_name` with
 * (utils/scenarios/scenarioScales): *labels*, `scaleLabelsOf`'s, when an input
 * comes from a box; none when no input does, so the spec's own colors and
 * order stand.
 */
export function boxFill(labels: readonly ScenarioLabel[]): readonly ScenarioLabel[] | null {
  return labels.some((label) => label.scenario != null) ? labels : null;
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
