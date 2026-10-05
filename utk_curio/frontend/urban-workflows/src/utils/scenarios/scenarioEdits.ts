/**
 * The edits the canvas makes to a dataflow's scenarios (#662). Each takes the
 * list and returns a new one; none mutates its argument.
 *
 * A node belongs to at most one scenario, so a scenario is never given a node
 * another scenario holds: the edit is refused, naming that scenario.
 */
import { SCENARIO_COLOR_RE, type Scenario } from "./scenarioModel";

/** The colors new scenarios take in turn, picked to tell apart on the canvas. */
export const SCENARIO_COLORS = [
  "#3567c7",
  "#e86a3c",
  "#2f8f4a",
  "#7a4bd1",
  "#c0392b",
  "#2e6874",
  "#996300",
  "#a3417a",
] as const;

export type ScenarioEdit = { scenarios: Scenario[]; error?: undefined } | { error: string; scenarios?: undefined };

/** The first of `SCENARIO_COLORS` no scenario wears, or the next one round. */
export function nextScenarioColor(scenarios: readonly Scenario[]): string {
  const taken = new Set(scenarios.map((s) => s.color.toLowerCase()));
  return SCENARIO_COLORS.find((c) => !taken.has(c)) ?? SCENARIO_COLORS[scenarios.length % SCENARIO_COLORS.length];
}

/** "Scenario N" for the smallest N no scenario is named with. */
export function nextScenarioName(scenarios: readonly Scenario[], skip: readonly string[] = []): string {
  const taken = new Set([...scenarios.map((s) => s.name), ...skip]);
  for (let n = 1; ; n += 1) {
    if (!taken.has(`Scenario ${n}`)) return `Scenario ${n}`;
  }
}

/**
 * Why *nodeIds* cannot join a scenario other than *except*: the first one
 * that already holds one of them, named, or null.
 */
export function overlapProblem(
  scenarios: readonly Scenario[],
  nodeIds: readonly string[],
  except?: string,
): string | null {
  const wanted = new Set(nodeIds);
  for (const scenario of scenarios) {
    if (scenario.id === except) continue;
    const held = scenario.nodes.filter((id) => wanted.has(id));
    if (held.length > 0) {
      const what = held.length === 1 ? "A node is" : `${held.length} nodes are`;
      return `${what} already in "${scenario.name}". A node belongs to one scenario.`;
    }
  }
  return null;
}

/**
 * The scenario whose nodes are exactly *nodeIds*, in any order. Read it on
 * `liveScenarios`: a member deleted since the last save is still in the list
 * until then, and would hide the match.
 */
export function scenarioHoldingExactly(scenarios: readonly Scenario[], nodeIds: readonly string[]): Scenario | undefined {
  const wanted = new Set(nodeIds);
  return scenarios.find((s) => s.nodes.length === wanted.size && s.nodes.every((id) => wanted.has(id)));
}

/** *scenarios* plus a new one holding *nodeIds*, or why not. */
export function createScenario(
  scenarios: readonly Scenario[],
  nodeIds: readonly string[],
  fields: { id: string; name?: string; color?: string },
): ScenarioEdit {
  const nodes = [...new Set(nodeIds)];
  if (nodes.length === 0) return { error: "Select the nodes the scenario holds first (Shift and drag)." };
  const problem = overlapProblem(scenarios, nodes);
  if (problem) return { error: problem };
  const scenario: Scenario = {
    id: fields.id,
    name: fields.name?.trim() || nextScenarioName(scenarios),
    color: fields.color && SCENARIO_COLOR_RE.test(fields.color) ? fields.color : nextScenarioColor(scenarios),
    nodes,
  };
  return { scenarios: [...scenarios, scenario] };
}

/** *scenarios* with *nodeIds* added to the scenario *id*, or why not. */
export function addNodesToScenario(scenarios: readonly Scenario[], id: string, nodeIds: readonly string[]): ScenarioEdit {
  if (nodeIds.length === 0) return { error: "Select the nodes to add first." };
  const problem = overlapProblem(scenarios, nodeIds, id);
  if (problem) return { error: problem };
  return {
    scenarios: scenarios.map((s) =>
      s.id === id ? { ...s, nodes: [...s.nodes, ...nodeIds.filter((n) => !s.nodes.includes(n))] } : s,
    ),
  };
}

/** *scenarios* with *nodeIds* taken out of whichever scenario holds them. */
export function removeNodesFromScenarios(scenarios: readonly Scenario[], nodeIds: readonly string[]): Scenario[] {
  const gone = new Set(nodeIds);
  return scenarios.map((s) => (s.nodes.some((n) => gone.has(n)) ? { ...s, nodes: s.nodes.filter((n) => !gone.has(n)) } : s));
}

/**
 * *scenarios* with the scenario *id* changed by *patch*. A blank name or a
 * color that is not `#rrggbb` is ignored; an empty description is removed.
 */
export function updateScenario(
  scenarios: readonly Scenario[],
  id: string,
  patch: Partial<Pick<Scenario, "name" | "color" | "description" | "collapsed" | "box">>,
): Scenario[] {
  return scenarios.map((s) => {
    if (s.id !== id) return s;
    const next: Scenario = { ...s };
    if (patch.name !== undefined && patch.name.trim()) next.name = patch.name.trim();
    if (patch.color !== undefined && SCENARIO_COLOR_RE.test(patch.color)) next.color = patch.color;
    if (patch.description !== undefined) {
      if (patch.description.trim()) next.description = patch.description;
      else delete next.description;
    }
    if (patch.collapsed !== undefined) next.collapsed = patch.collapsed;
    if (patch.box !== undefined) next.box = { x: patch.box.x, y: patch.box.y };
    return next;
  });
}

/** *scenarios* without the scenario *id*. Its nodes stay on the canvas. */
export function deleteScenario(scenarios: readonly Scenario[], id: string): Scenario[] {
  return scenarios.filter((s) => s.id !== id);
}

/**
 * *scenarios* followed by *added*, the ones saved elsewhere (an applied agent
 * plan saves its scenarios on the server first). One already in the list, by
 * id, is not added twice.
 */
export function joinScenarios(scenarios: readonly Scenario[], added: readonly Scenario[]): Scenario[] {
  const ids = new Set(scenarios.map((s) => s.id));
  return [...scenarios, ...added.filter((s) => !ids.has(s.id))];
}
