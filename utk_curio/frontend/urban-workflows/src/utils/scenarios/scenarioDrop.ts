/**
 * One scenario dragged in from the Scenario Catalog (#662), built on the saved
 * shape of a dataflow, as Duplicate selection is:
 *
 * - its own nodes, and the shared outcomes of its set that land with it (the
 *   server keeps those whose every input is in once it is), are copied with
 *   fresh ids, each naming its original in `metadata.copiedFrom`, with the
 *   edges between them, the top left at the drop;
 * - each node whose output crosses into them arrives once, as fixed data: a
 *   Data Loading node that reads a copy of the output the source project saved
 *   for it, wired where the context node was;
 * - the first drop of a set's scenario makes the set's copy here, named as
 *   the set, a name no set here has, recording the project and set it copies;
 *   a later drop of another scenario of that set joins that copy, found by
 *   where it came from, never by its name: it reuses the context the copy
 *   brought, and wires a shared outcome that lands now to the copy's nodes;
 * - a scenario the copy holds already is refused (`alreadyInCopy`);
 * - everything arrives collapsed: the scenario's box, and on the first drop
 *   the set's shared context and outcomes.
 *
 * Two steps, around the server's copy: `planScenarioDrop` chooses the ids and
 * says which saved output to copy to which node; `loaderNodes` makes the Data
 * Loading nodes from the datasets the copy made.
 */
import type { ScenarioCopyOutput, ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import { duplicateSelection, lineageOf, type SpecEdge, type SpecNode } from "./duplicateSelection";
import { nextScenarioColor, uniqueSetName } from "./scenarioEdits";
import type { Scenario, ScenarioSet } from "./scenarioModel";
import { newSetId } from "./scenarioSets";

/** Kept in sync with `NodeType.DATA_LOADING`. */
const DATA_LOADING_TYPE = "curio.builtin/data-loading";

/** One column to the left of the copies, where the context lands. */
const CONTEXT_COLUMN = 645;
/** Room between two context nodes stacked in that column. */
const CONTEXT_ROW = 420;

export interface PlannedLoader {
  id: string;
  /** The source project's node whose saved output it reads. */
  source: string;
  /** What it is, for its goal: the context node it stands for, and where from. */
  goal: string;
  position: { x: number; y: number };
  copiedFrom: string[];
}

export interface ScenarioDrop {
  /** The copies of its nodes and of the shared outcomes landing, to load into the canvas. */
  nodes: SpecNode[];
  edges: SpecEdge[];
  /** The Data Loading nodes to make once their datasets are copied. */
  loaders: PlannedLoader[];
  /** Nodes of the set's copy the drop's edges come from rather than copies. */
  reused: SpecNode[];
  /** Which saved output of the source each new node gets. */
  outputs: ScenarioCopyOutput[];
  /** The dataflow's scenarios after the drop: the one added last, and those
   *  of the copy listing a shared outcome that landed with it. */
  scenarios: Scenario[];
  /** The dataflow's sets after the drop: the copy added by a first drop. */
  sets: ScenarioSet[];
  /** The scenario added. */
  scenario: Scenario;
  /** Its set here: the copy, made now or joined. */
  set: ScenarioSet;
  /** Whether the drop made the copy, rather than joined it. */
  made: boolean;
}

export interface DropOptions {
  newId: () => string;
  /** Where the copies' top left goes, in flow coordinates. */
  at: { x: number; y: number };
}

/** What a drop of a scenario of a project's set needs to find its copy here. */
export interface DroppedFrom {
  projectId: string;
  setId: string;
  scenarioId: string;
  name: string;
}

const isDataLoading = (node: SpecNode) => String(node.type ?? "").split("@")[0] === DATA_LOADING_TYPE;
const lastOf = (node: SpecNode) => lineageOf(node).at(-1);

/** This dataflow's copy of the set *from* names, by the project and set it copies. */
export function setCopyOf(from: Pick<DroppedFrom, "projectId" | "setId">, sets: readonly ScenarioSet[]): ScenarioSet | null {
  if (!from.setId) return null;
  return sets.find((set) => set.source?.project === from.projectId && set.source.set === from.setId) ?? null;
}

/** The ids, in its project, of the scenarios this dataflow's copy of *from*'s set holds. */
export function presentInCopy(
  from: Pick<DroppedFrom, "projectId" | "setId">,
  scenarios: readonly Scenario[],
  sets: readonly ScenarioSet[],
): string[] {
  const copy = setCopyOf(from, sets);
  if (!copy) return [];
  return scenarios.flatMap((s) =>
    s.set === copy.id && s.source?.project === from.projectId ? [s.source.scenario] : [],
  );
}

/** Why *from*'s scenario cannot come in: the copy of its set here holds it. Null when it can. */
export function alreadyInCopy(
  from: DroppedFrom,
  scenarios: readonly Scenario[],
  sets: readonly ScenarioSet[],
): string | null {
  if (!presentInCopy(from, scenarios, sets).includes(from.scenarioId)) return null;
  const copy = setCopyOf(from, sets)!;
  return `"${from.name}" is already in the scenario set "${copy.name}" here. A scenario comes in once.`;
}

/** *name*, or "*name* (2)", "*name* (3)", ...: the first no scenario of *others* has. */
function uniqueName(name: string, others: readonly Scenario[]): string {
  const taken = new Set(others.map((s) => s.name.trim().toLowerCase()));
  if (!taken.has(name.trim().toLowerCase())) return name;
  for (let n = 2; ; n += 1) {
    if (!taken.has(`${name} (${n})`.toLowerCase())) return `${name} (${n})`;
  }
}

/**
 * What dropping *plan*'s scenario into the dataflow *live* (its saved shape),
 * whose scenarios and sets are *scenarios* and *sets*, adds, or why it cannot
 * be added.
 */
export function planScenarioDrop(
  plan: ScenarioCopyPlan,
  live: { nodes: readonly SpecNode[]; edges: readonly SpecEdge[] },
  scenarios: readonly Scenario[],
  sets: readonly ScenarioSet[],
  options: DropOptions,
): ScenarioDrop | { error: string } {
  const { at, newId } = options;
  const from = { projectId: plan.project.id, setId: plan.set.id, scenarioId: plan.scenario.id, name: plan.scenario.name };
  const refused = alreadyInCopy(from, scenarios, sets);
  if (refused) return { error: refused };
  const byId = new Map(plan.dataflow.nodes.map((node) => [node.id, node as SpecNode]));
  const own = plan.nodes.filter((id) => byId.has(id));
  if (own.length === 0) return { error: `"${plan.scenario.name}" has no nodes to bring.` };

  // The copy of its set here, and its nodes by the node of the source each
  // copies: its scenarios' nodes, the context it brought, and the shared
  // outcomes that landed.
  const copySet = setCopyOf(from, sets);
  const inCopy = copySet ? scenarios.filter((s) => s.set === copySet.id) : [];
  const held = new Set(inCopy.flatMap((s) => [...s.nodes, ...(s.context ?? []), ...(s.outcomes ?? [])]));
  const copyOf = new Map<string, SpecNode>();
  const loaderFor = new Map<string, SpecNode>();
  for (const node of live.nodes) {
    const last = lastOf(node);
    if (!held.has(node.id) || !last) continue;
    if (isDataLoading(node) && !loaderFor.has(last)) loaderFor.set(last, node);
    if (!copyOf.has(last)) copyOf.set(last, node);
  }

  const copied = [...byId.keys()];
  const left = Math.min(...copied.map((id) => byId.get(id)!.x ?? 0));
  const top = Math.min(...copied.map((id) => byId.get(id)!.y ?? 0));
  const offset = { x: at.x - left, y: at.y - top };
  const copy = duplicateSelection(plan.dataflow, copied, { newId, offset });

  const reused = new Map<string, SpecNode>();
  const loaders: PlannedLoader[] = [];
  const standIn = new Map<string, string>();
  for (const entry of plan.context) {
    if (!entry.source) continue;
    const again = loaderFor.get(entry.source.nodeId);
    if (again) {
      reused.set(again.id, again);
      standIn.set(entry.nodeId, again.id);
      continue;
    }
    const loader: PlannedLoader = {
      id: newId(),
      source: entry.source.nodeId,
      goal: `Shared context of "${plan.set.name}": a copy of what ${entry.label} passed on in ${plan.project.name}.`,
      position: { x: at.x - CONTEXT_COLUMN, y: at.y + CONTEXT_ROW * loaders.length },
      copiedFrom: [...entry.source.copiedFrom, entry.source.nodeId],
    };
    loaders.push(loader);
    standIn.set(entry.nodeId, loader.id);
  }

  const edges: SpecEdge[] = [];
  const copies = new Set(copy.ids.values());
  for (const edge of copy.edges) {
    if (copies.has(edge.source)) {
      edges.push(edge);
      continue;
    }
    const loader = standIn.get(edge.source);
    if (loader) {
      edges.push({ ...edge, source: loader, sourceHandle: "out" });
      continue;
    }
    // A shared outcome landing now reads a node an earlier drop brought.
    const earlier = copyOf.get(edge.source);
    if (earlier) {
      reused.set(earlier.id, earlier);
      edges.push({ ...edge, source: earlier.id });
    }
  }

  const outputs: ScenarioCopyOutput[] = loaders.map((loader) => ({ source: loader.source, node: loader.id }));
  for (const outcome of plan.shared) {
    for (const source of outcome.sources) {
      const node = copy.ids.get(source);
      if (node && !outputs.some((o) => o.node === node)) outputs.push({ source, node });
    }
  }

  const scenarioId = newId();
  const set: ScenarioSet = copySet ?? {
    id: newSetId(scenarioId, sets.map((x) => x.id)),
    name: uniqueSetName(plan.set.name, sets),
    shared: { context: { collapsed: true }, outcomes: { collapsed: true } },
    source: { project: plan.project.id, set: plan.set.id },
  };
  const landed = (id: string) => copy.ids.get(id) ?? copyOf.get(id)?.id;
  const scenario: Scenario = {
    id: scenarioId,
    name: uniqueName(plan.scenario.name, inCopy),
    color: scenarios.some((s) => s.color.toLowerCase() === plan.scenario.color.toLowerCase())
      ? nextScenarioColor(scenarios)
      : plan.scenario.color,
    ...(plan.scenario.description ? { description: plan.scenario.description } : {}),
    nodes: own.map((id) => copy.ids.get(id)!),
    set: set.id,
    context: plan.context.flatMap((entry) => standIn.get(entry.nodeId) ?? []),
    outcomes: plan.outcomes.flatMap((id) => landed(id) ?? []),
    collapsed: true,
    box: {
      x: Math.min(...own.map((id) => byId.get(id)!.x ?? 0)) + offset.x,
      y: Math.min(...own.map((id) => byId.get(id)!.y ?? 0)) + offset.y,
    },
    source: { project: plan.project.id, scenario: plan.scenario.id },
  };

  // The copy's scenarios that list a shared outcome landing now list its copy.
  const after = scenarios.map((s) => {
    if (s.set !== set.id || s.source?.project !== plan.project.id) return s;
    const more = plan.shared.flatMap((entry) =>
      entry.scenarios.includes(s.source!.scenario) ? (copy.ids.get(entry.nodeId) ?? []) : [],
    );
    return more.length === 0 ? s : { ...s, outcomes: [...(s.outcomes ?? []), ...more] };
  });

  return {
    nodes: copy.nodes,
    edges,
    loaders,
    reused: [...reused.values()],
    outputs,
    scenarios: [...after, scenario],
    sets: copySet ? [...sets] : [...sets, set],
    scenario,
    set,
    made: !copySet,
  };
}

/**
 * The nodes and edges a drop loads into the canvas: the reused nodes, which
 * the copies' edges may come from, the Data Loading nodes that arrived, and
 * the copies. An edge from a loader that did not arrive is left out, so no
 * edge names a node that is not there.
 */
export function dropGraph(drop: ScenarioDrop, loaders: readonly SpecNode[]): { nodes: SpecNode[]; edges: SpecEdge[] } {
  const arrived = new Set(loaders.map((node) => node.id));
  const missing = new Set(drop.loaders.map((loader) => loader.id).filter((id) => !arrived.has(id)));
  return {
    nodes: [...drop.reused, ...loaders, ...drop.nodes],
    edges: drop.edges.filter((edge) => !missing.has(edge.source)),
  };
}

/** What `buildDatasetLoaderNodeOptions` gives a Data Loading node. */
export interface LoaderOptions {
  code: string;
  datasetRefs?: string[];
  datasetSource?: unknown;
}

/**
 * The Data Loading nodes of *loaders*, each reading the dataset the copy made
 * for it (*datasets*, by loader id), as a Data Catalog drop builds one with
 * *build*. A loader whose dataset did not arrive is left out.
 */
export function loaderNodes(
  loaders: readonly PlannedLoader[],
  datasets: Record<string, unknown>,
  build: (dataset: any, position: { x: number; y: number }) => LoaderOptions,
): SpecNode[] {
  return loaders.flatMap((loader) => {
    const dataset = datasets[loader.id];
    if (!dataset) return [];
    const options = build(dataset, loader.position);
    const metadata: Record<string, unknown> = { keywords: [], copiedFrom: loader.copiedFrom };
    if (options.datasetRefs?.length) metadata.datasetRefs = options.datasetRefs;
    if (options.datasetSource) metadata.datasetSource = options.datasetSource;
    return [{
      id: loader.id,
      type: DATA_LOADING_TYPE,
      x: loader.position.x,
      y: loader.position.y,
      content: options.code,
      in: "DEFAULT",
      out: "DEFAULT",
      goal: loader.goal,
      metadata,
    }];
  });
}
