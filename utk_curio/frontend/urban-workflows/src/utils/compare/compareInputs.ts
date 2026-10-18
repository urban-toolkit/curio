/**
 * A Compare Scenarios node's inputs (#662), read from the live graph: the node
 * feeding each input circle, and the scenario that node belongs to, which
 * labels the input. A node belongs to at most one scenario.
 *
 * Duck-typed nodes and edges, so this module needs no `reactflow` import.
 */
import { inputSlotOf, isDataEdge } from "../inputSlots";
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";
import { liveScenarios } from "../scenarios/scenarioParts";
import type { Scenario } from "../scenarios/scenarioModel";
import { nodeLabel } from "../../components/scenarios/scenarioLabels";
import { NO_SCENARIO_COLOR, normalizeCompareSettings, sameLabels, type CompareInputLabel } from "./compareSettings";

/** The Compare Scenarios node's type, without its version. */
export const COMPARE_SCENARIOS_TYPE = "curio.builtin/compare-scenarios";

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

/** The wired inputs of the Compare Scenarios node *nodeId*, in circle order. */
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

/**
 * The labels a Compare Scenarios node's chart draws with: the *stored* ones
 * (`metadata.compareScenarios.inputs`), else those of its *inputs* as the graph
 * shows them.
 */
export function chartLabels(
  stored: readonly CompareInputLabel[] | undefined,
  inputs: readonly CompareInput[],
): readonly CompareInputLabel[] {
  return stored ?? inputs.map((input) => input.label);
}

/**
 * The labels of the Compare Scenarios node that node *nodeId* reads on its
 * first input circle, directly or through nodes of one input each: the labels
 * the Compare node's chart draws with (`chartLabels`). Null when that walk
 * reaches no Compare node, or one with no inputs.
 */
export function upstreamCompareLabels(
  nodeId: string,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): readonly CompareInputLabel[] | null {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const into = (id: string) => edges.filter((edge) => edge.target === id && isDataEdge(edge));
  const visited = new Set<string>([nodeId]);
  let source = into(nodeId).find((edge) => inputSlotOf(edge.targetHandle) === 0)?.source;
  while (source !== undefined && !visited.has(source)) {
    visited.add(source);
    const node = byId.get(source);
    if (!node) return null;
    if (getUnversionedFlowNodeType(node) === COMPARE_SCENARIOS_TYPE) {
      const stored = normalizeCompareSettings(node.data?.compareScenarios)?.inputs;
      const labels = chartLabels(stored, compareInputs(node.id, nodes, edges, scenarios));
      return labels.length > 0 ? labels : null;
    }
    const feeding = into(source);
    source = feeding.length === 1 ? feeding[0].source : undefined;
  }
  return null;
}

/**
 * Whether the node's labels, and the code written from them, must be written
 * again: the *inputs* the graph shows no longer say what the *stored* labels
 * say. A project load adds a dataflow's nodes before its edges, so for a moment
 * a node that has inputs shows none; while the dataflow has no edge at all
 * (*graphHasEdges* false), stored labels are kept rather than written away.
 */
export function labelsNeedWriting(
  stored: readonly CompareInputLabel[] | undefined,
  inputs: readonly CompareInput[],
  graphHasEdges: boolean,
): boolean {
  if (sameLabels(stored, inputs.map((input) => input.label))) return false;
  return graphHasEdges;
}

/** How *inputs* are read, said once per problem: an input in no scenario, and
 * inputs that share one. */
export function labelWarnings(inputs: readonly CompareInput[]): string[] {
  const warnings: string[] = [];
  for (const input of inputs) {
    if (input.scenario === null) {
      warnings.push(
        `input_${input.slot} comes from ${input.label.name}, which is in no scenario: its rows carry the node's name, and What differs leaves it out.`,
      );
    }
  }
  const slotsOf = new Map<string, number[]>();
  for (const input of inputs) {
    if (input.scenario === null) continue;
    slotsOf.set(input.scenario.id, [...(slotsOf.get(input.scenario.id) ?? []), input.slot]);
  }
  for (const [id, slots] of slotsOf) {
    if (slots.length < 2) continue;
    const name = inputs.find((input) => input.scenario?.id === id)!.label.name;
    warnings.push(`Inputs ${listOf(slots.map(String))} come from one scenario, ${name}: their rows carry the same name.`);
  }
  return warnings;
}

/**
 * The layers the node can read from its inputs, given each input's layer
 * names: the ones every input that holds several layers (an Autark node's
 * workspace) has, in the first such input's order. Empty when no input holds
 * several, since an input of one table needs no choice.
 */
export function layersToPick(perInput: readonly (readonly (string | null)[])[]): string[] {
  const several = perInput
    .map((names) => names.filter((name): name is string => typeof name === "string" && name.length > 0))
    .filter((names, i) => perInput[i].length > 1);
  if (several.length === 0) return [];
  const [first, ...rest] = several;
  return [...new Set(first)].filter((name) => rest.every((names) => names.includes(name)));
}

/** `a`, `a and b`, `a, b and c`. */
export function listOf(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
