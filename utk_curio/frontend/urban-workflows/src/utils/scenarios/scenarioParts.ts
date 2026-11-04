/**
 * What a scenario is made of on the canvas (#662), by role, read from the live
 * graph:
 *
 * - `nodes`, its Scenario-specific nodes;
 * - `last`, its own last nodes: those of its nodes whose output nothing in it
 *   reads, or that something outside it reads, the results it shows;
 * - `context`, its Shared context: the nodes upstream of it, outside every
 *   scenario's box, that it keeps (`scenarioSets.ts`);
 * - `outcomes`, its Shared outcomes: the nodes downstream of it, outside every
 *   box, that it keeps;
 * - `boundary`, the nodes whose output crosses into it, or into one of its
 *   shared outcomes from outside every box and every shared outcome: the
 *   context a drop brings as data.
 *
 * The canvas and the Scenario Catalog show the whole shared context and shared
 * outcomes. What saves its output because of a scenario is what stands for its
 * boundary, its own last nodes and its shared outcomes, and nothing else
 * (`scenarioSourceNodeIds`).
 *
 * The twin of `utk_curio/backend/app/scenario_catalog/domain/parts.py`; both
 * read `scenarioParts.cases.json`. A scenario's member list can name a node
 * deleted since the last save, so everything here reads the nodes still on
 * the canvas.
 */
import { dashboardSourceNodeIds, isPassThroughNode, producersFeeding } from "../dashboardLayout";
import type { Scenario } from "./scenarioModel";
import { inferContextOutcomes, isInteraction } from "./scenarioSets";

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = {
  source: string;
  target: string;
  type?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export interface ScenarioParts {
  /** Its Scenario-specific nodes on the canvas, in the scenario's order. */
  nodes: string[];
  /** Its own last nodes, in the scenario's order. */
  last: string[];
  /** Its Shared context, in canvas order. */
  context: string[];
  /** Its Shared outcomes, in canvas order. */
  outcomes: string[];
  /** What crosses into it or its shared outcomes from outside, in canvas order. */
  boundary: string[];
}

/**
 * *scenarios* with each member list cut to the nodes in *nodes*. A scenario
 * that loses nothing is returned as it is, so a caller can compare by identity.
 */
export function liveScenarios(scenarios: readonly Scenario[], nodes: readonly { id: string }[]): Scenario[] {
  const live = new Set(nodes.map((node) => node.id));
  return scenarios.map((scenario) =>
    scenario.nodes.every((id) => live.has(id))
      ? scenario
      : { ...scenario, nodes: scenario.nodes.filter((id) => live.has(id)) },
  );
}

/**
 * The parts of *scenario*, one of the dataflow's *scenarios*. A node of a box
 * is never in its context or outcomes; a list the scenario does not keep is
 * the one Curio infers for it (`inferContextOutcomes`), as a save fills it in.
 */
export function scenarioParts(
  scenario: Scenario,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): ScenarioParts {
  const order = nodes.map((node) => node.id);
  const known = new Set(order);
  const own = [...new Set(scenario.nodes.filter((id) => known.has(id)))];
  const members = new Set(own);
  const boxed = new Set([...own, ...scenarios.flatMap((s) => s.nodes)]);
  const links = edges.filter((edge) => !isInteraction(edge) && known.has(edge.source) && known.has(edge.target));

  let inferred: { context: string[]; outcomes: string[] } | null = null;
  const kept = (key: "context" | "outcomes"): string[] => {
    let given = scenario[key];
    if (!Array.isArray(given)) {
      inferred ??= inferContextOutcomes(own, order, links, boxed);
      given = inferred[key];
    }
    const listed = new Set(given);
    return order.filter((id) => listed.has(id) && !boxed.has(id));
  };
  const context = kept("context");
  const outcomes = kept("outcomes");

  const outcomeSet = new Set(outcomes);
  const everyOutcome = new Set([...outcomes, ...scenarios.flatMap((s) => s.outcomes ?? [])]);
  const boundary = new Set<string>();
  const readInside = new Set<string>();
  const readOutside = new Set<string>();
  for (const edge of links) {
    if (members.has(edge.source)) (members.has(edge.target) ? readInside : readOutside).add(edge.source);
    if (members.has(edge.target) && !members.has(edge.source)) boundary.add(edge.source);
    else if (outcomeSet.has(edge.target) && !boxed.has(edge.source) && !everyOutcome.has(edge.source)) {
      boundary.add(edge.source);
    }
  }
  const last = own.filter((id) => !readInside.has(id) || readOutside.has(id));
  return { nodes: own, last, context, outcomes, boundary: order.filter((id) => boundary.has(id)) };
}

/**
 * The nodes whose saved output stands for *id*'s, in canvas order: itself, or
 * for a pass-through (a chart, a Data Pool, a drawing Autark node), which
 * saves nothing itself, the nodes feeding it, the walk pinned dashboard tiles
 * use. Kept in sync with `saved_sources` in `scenario_catalog/domain/parts.py`.
 */
export function savedSourcesOf(
  id: string,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): string[] {
  const node = nodes.find((n) => n.id === id);
  if (!node) return [];
  if (!isPassThroughNode(node)) return [id];
  const feeding = producersFeeding([id], nodes, edges);
  return nodes.filter((n) => feeding.has(n.id)).map((n) => n.id);
}

/**
 * The nodes whose outputs the scenarios need saved: what stands for each
 * one's boundary, its own last nodes and its shared outcomes, so a drop into
 * another project brings them and the Scenario Catalog shows them.
 */
export function scenarioSourceNodeIds(
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): Set<string> {
  const sources = new Set<string>();
  for (const scenario of scenarios) {
    const { boundary, last, outcomes } = scenarioParts(scenario, nodes, edges, scenarios);
    for (const id of [...boundary, ...last, ...outcomes]) {
      savedSourcesOf(id, nodes, edges).forEach((source) => sources.add(source));
    }
  }
  return sources;
}

/**
 * Every node whose output a save or a run records whatever its own Save toggle
 * says: what a pinned dashboard tile reads, and what stands for a scenario's
 * boundary, its own last nodes and its shared outcomes. The one rule both the run
 * (`isDashboardSource`) and the save (`buildOutputRefs`) read.
 */
export function savedSourceNodeIds(
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[] | null | undefined,
): Set<string> {
  const sources = dashboardSourceNodeIds(nodes, edges);
  if (scenarios && scenarios.length > 0) {
    scenarioSourceNodeIds(nodes, edges, scenarios).forEach((id) => sources.add(id));
  }
  return sources;
}
