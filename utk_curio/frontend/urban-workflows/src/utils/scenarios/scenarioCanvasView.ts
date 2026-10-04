/**
 * How the canvas draws a dataflow's scenarios (#662). One pure function, called
 * where MainCanvas hands nodes and edges to React Flow, so none of it is
 * dataflow state: the FlowProvider's nodes and edges never hold a box, a frame
 * or a stand-in edge, and run levels, Run All, a save and an agent's view read
 * the same graph whatever is collapsed.
 *
 * - A collapsed scenario's members stay mounted and keep running, drawn hidden
 *   (`hideNode`, as the dashboard hides unpinned nodes). The edges they touch
 *   are hidden, and each edge crossing the scenario's edge is drawn to or from
 *   its box instead, as a stand-in.
 * - An expanded scenario's members wear its color, inside a frame.
 * - The fixed context of the scenario the panel highlights is marked.
 *
 * Boxes, frames and stand-ins are not React Flow nodes or edges: React Flow's
 * store is what `reactFlow.getNodes()` returns to Run All and to a save, so
 * `ScenarioLayers` draws them beside it.
 */
import type { CSSProperties } from "react";
import type { Edge, Node } from "reactflow";
import { directedEdgesOf } from "../../providers/flow/runLevels";
import { hideNode } from "../hiddenNodes";
import type { Scenario } from "./scenarioModel";
import { scenarioParts, type ScenarioParts } from "./scenarioParts";

export const SCENARIO_MEMBER_CLASS = "curio-scenario-member";
export const SCENARIO_FIXED_CLASS = "curio-scenario-fixed";

export interface ScenarioBox {
  scenario: Scenario;
  /** Where the box sits on the canvas: `scenario.box`, else its members' top left. */
  x: number;
  y: number;
  parts: ScenarioParts;
}

export interface ScenarioFrame {
  scenario: Scenario;
  members: string[];
}

/** A stand-in edge's end: a node's handle, or a box's port for one of its nodes. */
export type StandInEnd =
  | { node: string; handle?: string | null }
  | { box: string; port: "context" | "outcome"; of: string };

export interface StandInEdge {
  id: string;
  source: StandInEnd;
  target: StandInEnd;
}

export interface ScenarioCanvasView<N extends Node, E extends Edge> {
  nodes: N[];
  edges: E[];
  boxes: ScenarioBox[];
  frames: ScenarioFrame[];
  standIns: StandInEdge[];
}

function withClass<N extends Node>(node: N, extra: string): N {
  return { ...node, className: node.className ? `${node.className} ${extra}` : extra };
}

function memberLook<N extends Node>(node: N, scenario: Scenario): N {
  const style = { ...(node.style ?? {}), "--curio-scenario-color": scenario.color } as CSSProperties;
  return { ...withClass(node, SCENARIO_MEMBER_CLASS), style };
}

export function scenarioCanvasView<N extends Node, E extends Edge>(
  nodes: N[],
  edges: E[],
  scenarios: readonly Scenario[],
  options: { fixedFor?: string | null } = {},
): ScenarioCanvasView<N, E> {
  const live = new Set(nodes.map((node) => node.id));
  const memberOf = new Map<string, Scenario>();
  const active: Scenario[] = [];
  for (const scenario of scenarios) {
    const members = scenario.nodes.filter((id) => live.has(id) && !memberOf.has(id));
    if (members.length === 0) continue;
    members.forEach((id) => memberOf.set(id, scenario));
    active.push(scenario);
  }
  if (active.length === 0) return { nodes, edges, boxes: [], frames: [], standIns: [] };

  const highlighted = active.find((s) => s.id === options.fixedFor);
  const fixed = new Set(highlighted ? scenarioParts(highlighted, nodes, edges).context : []);
  const collapsedOf = (id: string) => {
    const scenario = memberOf.get(id);
    return scenario?.collapsed ? scenario : undefined;
  };

  const viewNodes = nodes.map((node) => {
    const scenario = memberOf.get(node.id);
    if (scenario?.collapsed) return { ...hideNode(node), selected: false };
    let next = scenario ? memberLook(node, scenario) : node;
    if (fixed.has(node.id)) next = withClass(next, SCENARIO_FIXED_CLASS);
    return next;
  });

  const viewEdges = edges.map((edge) =>
    collapsedOf(edge.source) || collapsedOf(edge.target) ? { ...edge, hidden: true } : edge,
  );

  const standIns: StandInEdge[] = [];
  const seen = new Set<string>();
  for (const edge of directedEdgesOf(edges)) {
    if (!live.has(edge.source) || !live.has(edge.target)) continue;
    const from = collapsedOf(edge.source);
    const to = collapsedOf(edge.target);
    if (!from && !to) continue;
    // Inside one collapsed scenario: nothing crosses its edge.
    if (from && to && from.id === to.id) continue;
    const source: StandInEnd = from
      ? { box: from.id, port: "outcome", of: edge.source }
      : { node: edge.source, handle: edge.sourceHandle };
    const target: StandInEnd = to
      ? { box: to.id, port: "context", of: edge.source }
      : { node: edge.target, handle: edge.targetHandle };
    // Two edges from one context node into a box meet at one port.
    const id = `${JSON.stringify(source)}->${JSON.stringify(target)}`;
    if (seen.has(id)) continue;
    seen.add(id);
    standIns.push({ id, source, target });
  }

  const boxes: ScenarioBox[] = [];
  const frames: ScenarioFrame[] = [];
  for (const scenario of active) {
    const members = nodes.filter((node) => memberOf.get(node.id) === scenario);
    if (!scenario.collapsed) {
      frames.push({ scenario, members: members.map((node) => node.id) });
      continue;
    }
    const x = scenario.box?.x ?? Math.min(...members.map((node) => node.position.x));
    const y = scenario.box?.y ?? Math.min(...members.map((node) => node.position.y));
    boxes.push({ scenario, x, y, parts: scenarioParts(scenario, nodes, edges) });
  }

  return { nodes: viewNodes, edges: viewEdges, boxes, frames, standIns };
}
