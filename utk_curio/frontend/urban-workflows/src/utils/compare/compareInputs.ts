/**
 * A Compare Scenarios node's inputs (#662), read from the live graph: the node
 * feeding each input circle, and the scenario that node belongs to, which
 * labels the input. A node belongs to at most one scenario.
 *
 * Duck-typed nodes and edges, so this module needs no `reactflow` import.
 */
import { inputSlotOf, isDataEdge } from "../inputSlots";
import { liveScenarios } from "../scenarios/scenarioParts";
import type { Scenario } from "../scenarios/scenarioModel";
import { nodeLabel } from "../../components/scenarios/scenarioLabels";
import { NO_SCENARIO_COLOR, sameLabels, type CompareInputLabel } from "./compareSettings";

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
        `Input ${input.slot} comes from ${input.label.name}, which is in no scenario: its rows carry the node's name, and What differs leaves it out.`,
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

/** `a`, `a and b`, `a, b and c`. */
export function listOf(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
