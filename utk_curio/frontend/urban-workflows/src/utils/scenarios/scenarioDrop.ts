/**
 * Scenarios of one set dragged in from the Scenario Catalog (#662), built on
 * the saved shape of a dataflow, as Duplicate selection is:
 *
 * - their levers, and the set's shared outcomes that come (the server keeps
 *   only those whose every input comes too), are copied with fresh ids, each
 *   naming its original in `metadata.copiedFrom`, with the edges between them,
 *   keeping their places relative to one another, the top left at the drop;
 * - each context node they read arrives once, as fixed data: a Data Loading
 *   node that reads a copy of the output the source project saved for it,
 *   wired where the context node was, for every scenario that read it;
 * - they make a new scenario set of this dataflow, named after theirs with
 *   "(copy)", a name no set here has; each keeps its name, and its color
 *   unless a scenario here wears it;
 * - everything arrives collapsed: each scenario's box, and the set's shared
 *   context and outcomes.
 *
 * Two steps, around the server's copy: `planScenarioDrop` chooses the ids and
 * says which saved output to copy to which node; `loaderNodes` makes the Data
 * Loading nodes from the datasets the copy made.
 */
import { v4 as uuid } from "uuid";

import type { ScenarioCopyOutput, ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import { duplicateSelection, type SpecEdge, type SpecNode } from "./duplicateSelection";
import { nextScenarioColor, uniqueSetName } from "./scenarioEdits";
import type { Scenario, ScenarioSet } from "./scenarioModel";

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
  /** The copies of the levers and shared outcomes, to load into the canvas. */
  nodes: SpecNode[];
  edges: SpecEdge[];
  /** The Data Loading nodes to make once their datasets are copied. */
  loaders: PlannedLoader[];
  /** Which saved output of the source each new node gets. */
  outputs: ScenarioCopyOutput[];
  /** The scenarios added, in the order they were dragged. */
  scenarios: Scenario[];
  /** The new set they are in. */
  set: ScenarioSet;
}

export interface DropOptions {
  newId: () => string;
  /** Where the copies' top left goes, in flow coordinates. */
  at: { x: number; y: number };
}

/**
 * What dropping *plan*'s scenarios into the dataflow *live* (its saved shape),
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
  const byId = new Map(plan.dataflow.nodes.map((node) => [node.id, node as SpecNode]));
  const dragged = plan.scenarios.map((s) => ({ ...s, levers: s.levers.filter((id) => byId.has(id)) }));
  const empty = dragged.find((s) => s.levers.length === 0);
  if (empty) return { error: `"${empty.name}" has no nodes to bring.` };

  const copied = [...byId.keys()];
  const left = Math.min(...copied.map((id) => byId.get(id)!.x ?? 0));
  const top = Math.min(...copied.map((id) => byId.get(id)!.y ?? 0));
  const offset = { x: at.x - left, y: at.y - top };
  const copy = duplicateSelection(plan.dataflow, copied, { newId, offset });

  const loaders: PlannedLoader[] = [];
  const standIn = new Map<string, string>();
  for (const entry of plan.context) {
    if (!entry.source) continue;
    const loader: PlannedLoader = {
      id: newId(),
      source: entry.source.nodeId,
      goal: `Fixed context of "${plan.set.name}": a copy of what ${entry.label} passed on in ${plan.project.name}.`,
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
    const source = standIn.get(edge.source);
    if (source) edges.push({ ...edge, source, sourceHandle: "out" });
  }

  const outputs: ScenarioCopyOutput[] = loaders.map((loader) => ({ source: loader.source, node: loader.id }));
  for (const outcome of [...plan.outcomes, ...plan.shared]) {
    for (const source of outcome.sources) {
      const node = copy.ids.get(source);
      if (node && !outputs.some((o) => o.node === node)) outputs.push({ source, node });
    }
  }

  const set: ScenarioSet = {
    id: `set-${uuid()}`,
    name: uniqueSetName(`${plan.set.name} (copy)`, sets),
    shared: { context: { collapsed: true }, outcomes: { collapsed: true } },
  };
  const made: Scenario[] = [];
  for (const s of dragged) {
    const worn = [...scenarios, ...made].some((x) => x.color.toLowerCase() === s.color.toLowerCase());
    const box = {
      x: Math.min(...s.levers.map((id) => byId.get(id)!.x ?? 0)) + offset.x,
      y: Math.min(...s.levers.map((id) => byId.get(id)!.y ?? 0)) + offset.y,
    };
    made.push({
      id: newId(),
      name: s.name,
      color: worn ? nextScenarioColor([...scenarios, ...made]) : s.color,
      ...(s.description ? { description: s.description } : {}),
      nodes: s.levers.map((id) => copy.ids.get(id)!),
      set: set.id,
      context: s.context.flatMap((id) => standIn.get(id) ?? []),
      outcomes: s.outcomes.flatMap((id) => copy.ids.get(id) ?? []),
      collapsed: true,
      box,
      source: { project: plan.project.id, scenario: s.id },
    });
  }

  return { nodes: copy.nodes, edges, loaders, outputs, scenarios: made, set };
}

/**
 * The nodes and edges a drop loads into the canvas: the Data Loading nodes
 * that arrived, and the copies. An edge from a loader that did not arrive is
 * left out, so no edge names a node that is not there.
 */
export function dropGraph(drop: ScenarioDrop, loaders: readonly SpecNode[]): { nodes: SpecNode[]; edges: SpecEdge[] } {
  const arrived = new Set(loaders.map((node) => node.id));
  const missing = new Set(drop.loaders.map((loader) => loader.id).filter((id) => !arrived.has(id)));
  return {
    nodes: [...loaders, ...drop.nodes],
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
