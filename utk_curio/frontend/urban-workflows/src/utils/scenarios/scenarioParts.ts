/**
 * What a scenario is made of on the canvas (#662), read from the live graph:
 *
 * - its levers, the nodes in it, which an alternative changes;
 * - its fixed context, the nodes outside it that it reads, through an edge
 *   into it or through a shared tag (`[!! @name !!]`) its code names. A tag
 *   has no edge, so the edges alone would miss a Parameter node;
 * - its outcomes, the nodes in it whose output nothing in it reads, or that
 *   something outside it reads.
 *
 * A scenario's member list can name a node deleted since the last save, so
 * everything here reads the members that are still on the canvas.
 */
import { directedEdgesOf } from "../../providers/flow/runLevels";
import { dashboardSourceNodeIds, isPassThroughNode, producersFeeding } from "../dashboardLayout";
import { sharedNamesIn } from "../references/codeReferences";
import { isParameterNode, nodeCode, normalizeShared } from "../references/sharedParameters";
import type { Scenario } from "./scenarioModel";

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

export interface ScenarioParts {
  /** Its nodes on the canvas, in the scenario's order. */
  levers: string[];
  /** The nodes outside it that it reads, in canvas order. */
  context: string[];
  /** The levers whose output is not read inside it, or is read outside it. */
  outcomes: string[];
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

export function scenarioParts(
  scenario: Scenario,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): ScenarioParts {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const members = new Set(scenario.nodes.filter((id) => byId.has(id)));
  const levers = [...members];

  const context = new Set<string>();
  const readInside = new Set<string>();
  const readOutside = new Set<string>();
  for (const edge of directedEdgesOf([...edges])) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    const fromInside = members.has(edge.source);
    const toInside = members.has(edge.target);
    if (!fromInside && toInside) context.add(edge.source);
    else if (fromInside && toInside) readInside.add(edge.source);
    else if (fromInside && !toInside) readOutside.add(edge.source);
  }

  const named = new Set(levers.flatMap((id) => sharedNamesIn(nodeCode(byId.get(id)!))));
  if (named.size > 0) {
    for (const node of nodes) {
      if (members.has(node.id) || !isParameterNode(node)) continue;
      if (normalizeShared(node.data?.widgets).some((widget) => named.has(widget.name))) {
        context.add(node.id);
      }
    }
  }

  // A Parameter node has no output, so it is never an outcome.
  const outcomes = levers.filter(
    (id) => !isParameterNode(byId.get(id)!) && (!readInside.has(id) || readOutside.has(id)),
  );
  return {
    levers,
    context: nodes.filter((node) => context.has(node.id)).map((node) => node.id),
    outcomes,
  };
}

/**
 * The nodes whose outputs the scenarios need saved: each context node and each
 * outcome, so another project can read them. A pass-through (a chart, a Data
 * Pool, a drawing Autark node) saves nothing itself and resolves to the nodes
 * feeding it, the walk pinned dashboard tiles use. A Parameter node's value is
 * in the spec, so it needs nothing.
 */
export function scenarioSourceNodeIds(
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): Set<string> {
  const sources = new Set<string>();
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const scenario of scenarios) {
    const { context, outcomes } = scenarioParts(scenario, nodes, edges);
    for (const id of [...context, ...outcomes]) {
      const node = byId.get(id);
      if (!node || isParameterNode(node)) continue;
      if (isPassThroughNode(node)) producersFeeding([id], nodes, edges).forEach((p) => sources.add(p));
      else sources.add(id);
    }
  }
  return sources;
}

/**
 * Every node whose output a save or a run records whatever its own Save toggle
 * says: what a pinned dashboard tile reads, and what a scenario's context and
 * outcomes produce. The one rule both the run (`isDashboardSource`) and the
 * save (`buildOutputRefs`) read.
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
