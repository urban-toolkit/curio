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
 * - The context and outcomes of the scenario pointed at in the Scenario
 *   Catalog drawer's In project tab are marked, and so are those of a
 *   scenario being defined (`preview`).
 * - Each scenario set's shared context and shared outcomes are a group each
 *   (`groups`), framed, or collapsed into one box the way a scenario is: its
 *   nodes hidden, and the edges crossing its edge drawn to or from the box.
 * - A shared context or outcome node of a set with two scenarios or more gets
 *   a row of circles under it, one per scenario of the set: filled when that
 *   scenario uses it (`dots`).
 * - A scenario set is outlined around its scenarios' frames and boxes and the
 *   context and outcomes they share, under the set's title (`sets`).
 *
 * Boxes, frames and stand-ins are not React Flow nodes or edges: React Flow's
 * store is what `reactFlow.getNodes()` returns to Run All and to a save, so
 * `ScenarioLayers` draws them beside it.
 */
import type { CSSProperties } from "react";
import type { Edge, Node } from "reactflow";
import { directedEdgesOf } from "../../providers/flow/runLevels";
import { hideNode } from "../hiddenNodes";
import type { Scenario, ScenarioSet, SharedKind } from "./scenarioModel";
import { scenarioParts, type ScenarioParts } from "./scenarioParts";

export const SCENARIO_MEMBER_CLASS = "curio-scenario-member";
export const SCENARIO_FIXED_CLASS = "curio-scenario-fixed";
export const SCENARIO_OUTCOME_CLASS = "curio-scenario-outcome";

export interface ScenarioBox {
  scenario: Scenario;
  /** Where the box sits on the canvas: `scenario.box`, else its members' top left. */
  x: number;
  y: number;
  parts: ScenarioParts;
  /** Its own nodes, one row each, in the dataflow's order. */
  rows: string[];
}

/** A scenario set's shared context or shared outcomes: the nodes outside every box. */
export interface SharedGroup {
  /** `group:<set>:<kind>`, which a stand-in edge's end names as its box. */
  key: string;
  set: string;
  kind: SharedKind;
  nodes: string[];
  collapsed: boolean;
  /** Where its collapsed box sits: where it was moved, else its nodes' top left. */
  x: number;
  y: number;
}

export const sharedGroupKey = (set: string, kind: SharedKind) => `group:${set}:${kind}`;

export interface ScenarioFrame {
  scenario: Scenario;
  members: string[];
}

/**
 * A stand-in edge's end: a node's handle, or the port of a box's row for one
 * of its nodes. *box* is a scenario's id or a shared group's key.
 */
export type StandInEnd =
  | { node: string; handle?: string | null }
  | { box: string; port: "in" | "out"; of: string };

export interface StandInEdge {
  id: string;
  source: StandInEnd;
  target: StandInEnd;
}

/** The circles under a shared node: one per scenario of its set, in the set's order. */
export interface MembershipDots {
  node: string;
  dots: { scenario: string; name: string; color: string; member: boolean }[];
}

/** What a scenario set's outline goes around. */
export interface ScenarioSetOutline {
  set: string;
  /** Its expanded scenarios, drawn as frames. */
  frames: string[];
  /** Its collapsed scenarios, drawn as boxes. */
  boxes: string[];
  /** Its shared groups, framed or collapsed, by key. */
  groups: string[];
}

export interface ScenarioCanvasView<N extends Node, E extends Edge> {
  nodes: N[];
  edges: E[];
  boxes: ScenarioBox[];
  frames: ScenarioFrame[];
  standIns: StandInEdge[];
  dots: MembershipDots[];
  sets?: ScenarioSetOutline[];
  groups?: SharedGroup[];
}

function withClass<N extends Node>(node: N, extra: string): N {
  return { ...node, className: node.className ? `${node.className} ${extra}` : extra };
}

function memberLook<N extends Node>(node: N, scenario: Scenario): N {
  const style = { ...(node.style ?? {}), "--scenario-color": scenario.color } as CSSProperties;
  return { ...withClass(node, SCENARIO_MEMBER_CLASS), style };
}

export function scenarioCanvasView<N extends Node, E extends Edge>(
  nodes: N[],
  edges: E[],
  scenarios: readonly Scenario[],
  options: {
    fixedFor?: string | null;
    /** The context and outcomes of a scenario being defined, marked like the pointed one's. */
    preview?: { context: readonly string[]; outcomes: readonly string[] } | null;
    /** The dataflow's scenario sets: how each draws its shared groups. */
    sets?: readonly ScenarioSet[];
  } = {},
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
  const preview = options.preview;
  if (active.length === 0 && !preview) return { nodes, edges, boxes: [], frames: [], standIns: [], dots: [] };

  const highlighted = active.find((s) => s.id === options.fixedFor);
  const marked = preview ?? highlighted;
  // A scenario keeps its finalized context; one from before sets, the nodes it reads.
  const fixed = new Set(
    marked ? (marked.context ?? (highlighted ? scenarioParts(highlighted, nodes, edges).context : [])) : [],
  );
  const outcomeMarks = new Set(marked?.outcomes ?? []);

  const groups = sharedGroups(nodes, active, memberOf, options.sets ?? []);
  const groupOf = new Map<string, SharedGroup>();
  for (const group of groups) {
    if (group.collapsed) group.nodes.forEach((id) => groupOf.set(id, group));
  }
  // The box a node is hidden in: its collapsed scenario's, or its collapsed group's.
  const hiddenIn = (id: string): string | undefined => {
    const scenario = memberOf.get(id);
    if (scenario?.collapsed) return scenario.id;
    return groupOf.get(id)?.key;
  };

  const viewNodes = nodes.map((node) => {
    const scenario = memberOf.get(node.id);
    if (hiddenIn(node.id)) return { ...hideNode(node), selected: false };
    let next = scenario ? memberLook(node, scenario) : node;
    if (fixed.has(node.id)) next = withClass(next, SCENARIO_FIXED_CLASS);
    if (outcomeMarks.has(node.id)) next = withClass(next, SCENARIO_OUTCOME_CLASS);
    return next;
  });

  const viewEdges = edges.map((edge) =>
    hiddenIn(edge.source) || hiddenIn(edge.target) ? { ...edge, hidden: true } : edge,
  );

  const standIns: StandInEdge[] = [];
  const seen = new Set<string>();
  for (const edge of directedEdgesOf(edges)) {
    if (!live.has(edge.source) || !live.has(edge.target)) continue;
    const from = hiddenIn(edge.source);
    const to = hiddenIn(edge.target);
    if (!from && !to) continue;
    // Inside one box: nothing crosses its edge.
    if (from && to && from === to) continue;
    // An edge leaves a box from its source's row, and enters one at its target's.
    const source: StandInEnd = from
      ? { box: from, port: "out", of: edge.source }
      : { node: edge.source, handle: edge.sourceHandle };
    const target: StandInEnd = to
      ? { box: to, port: "in", of: edge.target }
      : { node: edge.target, handle: edge.targetHandle };
    // Two edges between the same two ends draw once.
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
    boxes.push({
      scenario,
      x,
      y,
      parts: scenarioParts(scenario, nodes, edges),
      rows: members.map((node) => node.id),
    });
  }

  return {
    nodes: viewNodes,
    edges: viewEdges,
    boxes,
    frames,
    standIns,
    dots: membershipDots(active, live, memberOf),
    sets: setOutlines(active, groups),
    groups,
  };
}

/**
 * Each set's shared context and shared outcomes: the nodes its scenarios list,
 * on the canvas and outside every box, in the dataflow's order. A node two
 * groups list is in the first only.
 */
export function sharedGroups<N extends Node>(
  nodes: readonly N[],
  scenarios: readonly Scenario[],
  memberOf: ReadonlyMap<string, Scenario>,
  sets: readonly ScenarioSet[],
): SharedGroup[] {
  const lookOf = new Map(sets.map((set) => [set.id, set.shared ?? {}]));
  const setIds = [...new Set(scenarios.map((s) => s.set).filter((id): id is string => !!id))];
  const claimed = new Set<string>();
  const groups: SharedGroup[] = [];
  for (const set of setIds) {
    const members = scenarios.filter((s) => s.set === set);
    for (const kind of ["context", "outcomes"] as const) {
      const listed = new Set(members.flatMap((s) => s[kind] ?? []));
      const held = nodes.filter((n) => listed.has(n.id) && !memberOf.has(n.id) && !claimed.has(n.id));
      if (held.length === 0) continue;
      held.forEach((n) => claimed.add(n.id));
      const look = lookOf.get(set)?.[kind] ?? {};
      groups.push({
        key: sharedGroupKey(set, kind),
        set,
        kind,
        nodes: held.map((n) => n.id),
        collapsed: look.collapsed === true,
        x: look.box?.x ?? Math.min(...held.map((n) => n.position.x)),
        y: look.box?.y ?? Math.min(...held.map((n) => n.position.y)),
      });
    }
  }
  return groups;
}

/** Each scenario set's outline: its scenarios, and its shared groups. */
export function setOutlines(scenarios: readonly Scenario[], groups: readonly SharedGroup[] = []): ScenarioSetOutline[] {
  const bySet = new Map<string, ScenarioSetOutline>();
  for (const scenario of scenarios) {
    if (!scenario.set) continue;
    const outline = bySet.get(scenario.set) ?? { set: scenario.set, frames: [], boxes: [], groups: [] };
    (scenario.collapsed ? outline.boxes : outline.frames).push(scenario.id);
    bySet.set(scenario.set, outline);
  }
  for (const group of groups) bySet.get(group.set)?.groups.push(group.key);
  return [...bySet.values()];
}

/**
 * The circles under each shared node of a set with two scenarios or more: one
 * per scenario of the set, filled when it lists the node in its context or
 * outcomes. A node in a collapsed scenario's box draws none.
 */
export function membershipDots(
  scenarios: readonly Scenario[],
  live: ReadonlySet<string>,
  memberOf: ReadonlyMap<string, Scenario> = new Map(),
): MembershipDots[] {
  const bySet = new Map<string, Scenario[]>();
  for (const scenario of scenarios) {
    if (!scenario.set) continue;
    bySet.set(scenario.set, [...(bySet.get(scenario.set) ?? []), scenario]);
  }
  const out = new Map<string, MembershipDots>();
  for (const members of bySet.values()) {
    if (members.length < 2) continue;
    const shared = new Set(members.flatMap((s) => [...(s.context ?? []), ...(s.outcomes ?? [])]));
    for (const node of shared) {
      if (!live.has(node) || memberOf.has(node)) continue;
      const entry = out.get(node) ?? { node, dots: [] };
      for (const s of members) {
        entry.dots.push({
          scenario: s.id,
          name: s.name,
          color: s.color,
          member: (s.context ?? []).includes(node) || (s.outcomes ?? []).includes(node),
        });
      }
      out.set(node, entry);
    }
  }
  return [...out.values()];
}
