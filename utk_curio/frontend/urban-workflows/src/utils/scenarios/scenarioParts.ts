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

export interface ScenarioNeighbors {
  /** The nodes outside it that feed it, on every path up, in canvas order. */
  upstream: string[];
  /** The nodes outside it that it feeds, on every path down, in canvas order. */
  downstream: string[];
}

/**
 * The nodes around *scenario*: what feeds it and what it feeds, walking every
 * path. A walk stops at another of *scenarios*' nodes, so two scenarios never
 * carry each other. Upstream also holds the Parameter nodes whose shared tags
 * it or its upstream names. A node on a path from one of its nodes to another
 * is upstream only.
 *
 * A save stores them with the scenario, and a drag from the Scenario Catalog
 * brings them with it. The twin of `scenario_neighbors` in
 * `scenario_catalog/domain/parts.py`; both read `scenarioNeighbors.cases.json`.
 */
export function scenarioNeighbors(
  scenario: Scenario,
  scenarios: readonly Scenario[],
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): ScenarioNeighbors {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const members = new Set(scenario.nodes.filter((id) => byId.has(id)));
  const others = new Set(
    scenarios.filter((s) => s.id !== scenario.id).flatMap((s) => s.nodes).filter((id) => !members.has(id)),
  );
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const edge of directedEdgesOf([...edges])) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    incoming.set(edge.target, [...(incoming.get(edge.target) ?? []), edge.source]);
    outgoing.set(edge.source, [...(outgoing.get(edge.source) ?? []), edge.target]);
  }
  const walk = (links: Map<string, string[]>) => {
    const found = new Set<string>();
    const queue = [...members];
    while (queue.length > 0) {
      for (const next of links.get(queue.shift()!) ?? []) {
        if (members.has(next) || others.has(next) || found.has(next)) continue;
        found.add(next);
        queue.push(next);
      }
    }
    return found;
  };

  const upstream = walk(incoming);
  const named = new Set([...members, ...upstream].flatMap((id) => sharedNamesIn(nodeCode(byId.get(id)!))));
  if (named.size > 0) {
    for (const node of nodes) {
      if (members.has(node.id) || others.has(node.id) || !isParameterNode(node)) continue;
      if (normalizeShared(node.data?.widgets).some((widget) => named.has(widget.name))) upstream.add(node.id);
    }
  }
  const downstream = walk(outgoing);
  return {
    upstream: nodes.filter((node) => upstream.has(node.id)).map((node) => node.id),
    downstream: nodes.filter((node) => downstream.has(node.id) && !upstream.has(node.id)).map((node) => node.id),
  };
}

/**
 * The nodes whose saved output stands for *id*'s, in canvas order: itself, or
 * for a pass-through (a chart, a Data Pool, a drawing Autark node), which
 * saves nothing itself, the nodes feeding it, the walk pinned dashboard tiles
 * use. A Parameter node's value is in the spec, so it has none. Kept in sync
 * with `saved_sources` in `scenario_catalog/domain/parts.py`.
 */
export function savedSourcesOf(
  id: string,
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): string[] {
  const node = nodes.find((n) => n.id === id);
  if (!node || isParameterNode(node)) return [];
  if (!isPassThroughNode(node)) return [id];
  const feeding = producersFeeding([id], nodes, edges);
  return nodes.filter((n) => feeding.has(n.id)).map((n) => n.id);
}

/**
 * The nodes whose outputs the scenarios need saved: what stands for each
 * context node, each outcome, and each node upstream or downstream of it, so
 * another project can read them.
 */
export function scenarioSourceNodeIds(
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
  scenarios: readonly Scenario[],
): Set<string> {
  const sources = new Set<string>();
  for (const scenario of scenarios) {
    const { context, outcomes } = scenarioParts(scenario, nodes, edges);
    const { upstream, downstream } = scenarioNeighbors(scenario, scenarios, nodes, edges);
    for (const id of [...context, ...outcomes, ...upstream, ...downstream]) {
      savedSourcesOf(id, nodes, edges).forEach((source) => sources.add(source));
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
