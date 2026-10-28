/**
 * A dataflow's scenario sets, at `dataflow.scenarioSets`. A set groups the
 * scenarios that answer one question: they are compared on the same shared
 * context and outcomes, and scenarios of different sets never mix.
 *
 * A scenario keeps its finalized `context` (the nodes upstream of it it uses)
 * and `outcomes` (the nodes downstream of it it feeds), nodes outside every
 * box; a node in them can belong to some of a set's scenarios and not others.
 * `inferContextOutcomes` is what Curio proposes, which the person then edits.
 *
 * The twin of `utk_curio/backend/app/projects/scenario_sets.py`; both read
 * `scenarioSets.cases.json`.
 */
import type { Scenario, ScenarioSet } from "./scenarioModel";

type EdgeLike = {
  source: string;
  target: string;
  type?: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

const isInteraction = (e: EdgeLike) =>
  e.type === "Interaction" || (e.sourceHandle === "in/out" && e.targetHandle === "in/out");

function walk(start: string[], step: Map<string, string[]>, boxed: Set<string>): Set<string> {
  const seen = new Set<string>();
  const frontier = [...start];
  while (frontier.length) {
    const id = frontier.pop()!;
    for (const next of step.get(id) ?? []) {
      if (boxed.has(next) || seen.has(next)) continue;
      seen.add(next);
      frontier.push(next);
    }
  }
  return seen;
}

/**
 * The context and outcomes Curio proposes for a scenario of *members*, in
 * the order of *nodeIds*: every node upstream of a member and every node
 * downstream of one, the walk stopping at any node in *boxed* (the nodes of
 * every scenario's box) and never following an Interaction link.
 */
export function inferContextOutcomes(
  members: readonly string[],
  nodeIds: readonly string[],
  edges: readonly EdgeLike[],
  boxed: Iterable<string>,
): { context: string[]; outcomes: string[] } {
  const known = new Set(nodeIds);
  const inside = members.filter((m) => known.has(m));
  const boxedSet = new Set([...boxed, ...inside]);
  const up = new Map<string, string[]>();
  const down = new Map<string, string[]>();
  for (const e of edges) {
    if (isInteraction(e) || !known.has(e.source) || !known.has(e.target)) continue;
    up.set(e.target, [...(up.get(e.target) ?? []), e.source]);
    down.set(e.source, [...(down.get(e.source) ?? []), e.target]);
  }
  const context = walk(inside, up, boxedSet);
  const outcomes = walk(inside, down, boxedSet);
  return {
    context: nodeIds.filter((id) => context.has(id)),
    outcomes: nodeIds.filter((id) => outcomes.has(id)),
  };
}

/**
 * The ids of *scenarios* in groups, each with every other that shares a
 * context or outcome node with it, directly or through others; groups and
 * their members keep the scenarios' order.
 */
export function groupIntoSets(scenarios: readonly Pick<Scenario, "id" | "context" | "outcomes">[]): string[][] {
  const parent = new Map(scenarios.map((s) => [s.id, s.id]));
  const find = (x: string): string => {
    while (parent.get(x) !== x) {
      parent.set(x, parent.get(parent.get(x)!)!);
      x = parent.get(x)!;
    }
    return x;
  };
  const firstWith = new Map<string, string>();
  for (const s of scenarios) {
    for (const id of [...(s.context ?? []), ...(s.outcomes ?? [])]) {
      const first = firstWith.get(id);
      if (first === undefined) {
        firstWith.set(id, s.id);
        continue;
      }
      const a = find(first);
      const b = find(s.id);
      if (a !== b) parent.set(b, a);
    }
  }
  const groups = new Map<string, string[]>();
  for (const s of scenarios) {
    const root = find(s.id);
    groups.set(root, [...(groups.get(root) ?? []), s.id]);
  }
  return [...groups.values()];
}

function wellFormedSets(raw: unknown): ScenarioSet[] {
  const out: ScenarioSet[] = [];
  const seen = new Set<string>();
  for (const entry of Array.isArray(raw) ? raw : []) {
    if (!entry || typeof entry !== "object") continue;
    const e = entry as Record<string, unknown>;
    if (typeof e.id !== "string" || !e.id || typeof e.name !== "string" || !e.name.trim() || seen.has(e.id)) continue;
    seen.add(e.id);
    const kept: ScenarioSet = { id: e.id, name: e.name };
    if (typeof e.description === "string" && e.description) kept.description = e.description;
    out.push(kept);
  }
  return out;
}

function freeId(base: string, taken: Set<string>): string {
  let candidate = base;
  for (let n = 2; taken.has(candidate); n++) candidate = `${base}-${n}`;
  taken.add(candidate);
  return candidate;
}

/**
 * `{scenarios, sets}` as a spec keeps them, from scenarios already through
 * `normalizeScenarios`. A scenario without a `context` or `outcomes` list
 * gets the inferred one; the lists it has keep only nodes of the dataflow
 * outside every box, in the dataflow's order. A scenario whose `set` is not
 * one of *rawSets* is grouped with the others like it into a new set, named
 * after the dataflow when it is the only one. A set no scenario names is
 * dropped.
 */
export function normalizeScenarioSets(
  scenarios: readonly Scenario[],
  rawSets: unknown,
  nodeIds: readonly string[],
  edges: readonly EdgeLike[],
  dataflowName?: string | null,
): { scenarios: Scenario[]; sets: ScenarioSet[] } {
  const boxed = new Set(scenarios.flatMap((s) => s.nodes));
  const known = new Set(nodeIds);
  const filled: Scenario[] = scenarios.map((s) => {
    let inferred: { context: string[]; outcomes: string[] } | null = null;
    const out: Scenario = { ...s };
    for (const key of ["context", "outcomes"] as const) {
      const given = s[key];
      if (Array.isArray(given)) {
        const keep = new Set(given);
        out[key] = nodeIds.filter((id) => keep.has(id) && !boxed.has(id) && known.has(id));
      } else {
        inferred ??= inferContextOutcomes(s.nodes, nodeIds, edges, boxed);
        out[key] = inferred[key];
      }
    }
    return out;
  });

  let sets = wellFormedSets(rawSets);
  const setIds = new Set(sets.map((x) => x.id));
  const loose = filled.filter((s) => !s.set || !setIds.has(s.set));
  const groups = groupIntoSets(loose);
  const taken = new Set(setIds);
  const names = new Map(filled.map((s) => [s.id, s.name]));
  const only = groups.length === 1 && sets.length === 0;
  for (const group of groups) {
    const id = freeId(`set-${group[0]}`, taken);
    const name =
      only && typeof dataflowName === "string" && dataflowName.trim()
        ? dataflowName.trim()
        : group.map((g) => names.get(g)).join(" vs ");
    sets.push({ id, name });
    for (const s of filled) if (group.includes(s.id)) s.set = id;
  }
  const used = new Set(filled.map((s) => s.set));
  sets = sets.filter((x) => used.has(x.id));

  const ordered = filled.map((s) => {
    const { set, context, outcomes, collapsed, box, source, ...rest } = s;
    const entry: Scenario = { ...rest, set, context, outcomes };
    if (collapsed !== undefined) entry.collapsed = collapsed;
    if (box !== undefined) entry.box = box;
    if (source !== undefined) entry.source = source;
    return entry;
  });
  return { scenarios: ordered, sets };
}

/** For one set: its scenario ids, and each context and outcome node's scenario ids, in the set's order. */
export function setMembership(
  scenarios: readonly Scenario[],
  setId: string,
): { scenarios: string[]; context: Record<string, string[]>; outcomes: Record<string, string[]> } {
  const members = scenarios.filter((s) => s.set === setId);
  const out = { scenarios: members.map((s) => s.id), context: {} as Record<string, string[]>, outcomes: {} as Record<string, string[]> };
  for (const key of ["context", "outcomes"] as const) {
    for (const s of members) {
      for (const id of s[key] ?? []) (out[key][id] ??= []).push(s.id);
    }
  }
  return out;
}
