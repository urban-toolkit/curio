/**
 * A scenario dragged in from the Scenario Catalog (#662), built on the saved
 * shape of a dataflow, as Duplicate selection is:
 *
 * - its levers are copied with fresh ids, each naming its original in
 *   `metadata.copiedFrom`, with the edges between them;
 * - each context node arrives as fixed data: a Data Loading node that reads
 *   a copy of the output the source project saved for it, wired where the
 *   context node was. A Parameter node of the context is copied with its
 *   value;
 * - a context node an earlier drop from the same project already brought is
 *   reused, so two scenarios that shared their context there share it here;
 * - the scenario is added collapsed, its box where it was dropped, naming the
 *   project and scenario it came from.
 *
 * Two steps, around the server's copy: `planScenarioDrop` chooses the ids and
 * says which saved output to copy to which node; `loaderNodes` makes the Data
 * Loading nodes from the datasets the copy made.
 */
import type { ScenarioCopyOutput, ScenarioCopyPlan } from "../../services/scenarioCatalog/scenarioCatalogTypes";
import { isParameterNode, sharedWidgetsOfSpec } from "../references/sharedParameters";
import { duplicateSelection, lineageOf, type SpecEdge, type SpecNode } from "./duplicateSelection";
import { nextScenarioColor } from "./scenarioEdits";
import type { Scenario } from "./scenarioModel";

/** Kept in sync with `NodeType.DATA_LOADING`. */
const DATA_LOADING_TYPE = "curio.builtin/data-loading";

/** One column to the left of the box, where the context lands. */
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
  /** The lever copies and the Parameter copies, to load into the canvas. */
  nodes: SpecNode[];
  edges: SpecEdge[];
  /** The Data Loading nodes to make once their datasets are copied. */
  loaders: PlannedLoader[];
  /** Nodes of this dataflow the drop reads again rather than copies. */
  reused: SpecNode[];
  /** Which saved output of the source each new node gets. */
  outputs: ScenarioCopyOutput[];
  scenario: Scenario;
}

export interface DropOptions {
  newId: () => string;
  /** Where the box goes, in flow coordinates. */
  at: { x: number; y: number };
}

const isDataLoading = (node: SpecNode) => String(node.type ?? "").split("@")[0] === DATA_LOADING_TYPE;
const isParameter = (node: SpecNode) => isParameterNode({ type: typeof node.type === "string" ? node.type : null });
const lastOf = (node: SpecNode) => lineageOf(node).at(-1);

function uniqueName(name: string, scenarios: readonly Scenario[]): string {
  const taken = new Set(scenarios.map((s) => s.name));
  if (!taken.has(name)) return name;
  for (let n = 2; ; n += 1) {
    if (!taken.has(`${name} (${n})`)) return `${name} (${n})`;
  }
}

/**
 * What dropping *plan*'s scenario into the dataflow *live* (its saved shape)
 * adds, or why it cannot be added.
 */
export function planScenarioDrop(
  plan: ScenarioCopyPlan,
  live: { nodes: readonly SpecNode[]; edges: readonly SpecEdge[] },
  scenarios: readonly Scenario[],
  options: DropOptions,
): ScenarioDrop | { error: string } {
  const { at, newId } = options;
  const byId = new Map(plan.dataflow.nodes.map((node) => [node.id, node as SpecNode]));
  const levers = plan.levers.filter((id) => byId.has(id));
  if (levers.length === 0) return { error: `"${plan.scenario.name}" has no nodes to bring.` };

  // What an earlier drop from the same project brought: the nodes outside
  // every scenario here that copy one of its nodes.
  const members = new Set(scenarios.flatMap((s) => s.nodes));
  const fromSameProject = scenarios.some((s) => s.source?.project === plan.project.id);
  const outside = fromSameProject ? live.nodes.filter((node) => !members.has(node.id)) : [];
  const broughtFor = (sourceId: string, kind: (node: SpecNode) => boolean) =>
    outside.find((node) => kind(node) && lastOf(node) === sourceId);

  const left = Math.min(...levers.map((id) => byId.get(id)!.x ?? 0));
  const top = Math.min(...levers.map((id) => byId.get(id)!.y ?? 0));
  const copy = duplicateSelection(plan.dataflow, levers, {
    newId,
    offset: { x: at.x - left, y: at.y - top },
  });

  const reused: SpecNode[] = [];
  const parameters: SpecNode[] = [];
  const loaders: PlannedLoader[] = [];
  const standIn = new Map<string, string>();
  let row = 0;
  const nextPlace = () => ({ x: at.x - CONTEXT_COLUMN, y: at.y + CONTEXT_ROW * row++ });

  for (const entry of plan.context) {
    if (entry.parameter) {
      const original = byId.get(entry.nodeId);
      if (!original) continue;
      const again = broughtFor(original.id, isParameter);
      if (again) {
        reused.push(again);
        continue;
      }
      const place = nextPlace();
      parameters.push({
        ...JSON.parse(JSON.stringify(original)),
        id: newId(),
        x: place.x,
        y: place.y,
        metadata: { ...(original.metadata ?? {}), copiedFrom: [...lineageOf(original), original.id] },
      });
      continue;
    }
    if (!entry.source) continue;
    const again = broughtFor(entry.source.nodeId, isDataLoading);
    if (again) {
      reused.push(again);
      standIn.set(entry.nodeId, again.id);
      continue;
    }
    const loader: PlannedLoader = {
      id: newId(),
      source: entry.source.nodeId,
      goal: `Fixed context of "${plan.scenario.name}": a copy of what ${entry.label} passed on in ${plan.project.name}.`,
      position: nextPlace(),
      copiedFrom: [...entry.source.copiedFrom, entry.source.nodeId],
    };
    loaders.push(loader);
    standIn.set(entry.nodeId, loader.id);
  }

  // A shared tag names a Parameter node by its name, so two with one name
  // leave every reference to it ambiguous.
  const keptHere = new Set(reused.map((node) => node.id));
  const namesHere = new Set(
    sharedWidgetsOfSpec(live.nodes.filter((node) => !keptHere.has(node.id))).map((w) => w.name),
  );
  const arriving = [...copy.nodes.filter(isParameter), ...parameters];
  const clash = sharedWidgetsOfSpec(arriving).find((w) => namesHere.has(w.name));
  if (clash) {
    return {
      error: `This dataflow already has a parameter named "${clash.name}". Rename it, then drag "${plan.scenario.name}" again.`,
    };
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
  for (const outcome of plan.outcomes) {
    for (const source of outcome.sources) {
      const node = copy.ids.get(source);
      if (node && !outputs.some((o) => o.node === node)) outputs.push({ source, node });
    }
  }

  const color = scenarios.some((s) => s.color.toLowerCase() === plan.scenario.color.toLowerCase())
    ? nextScenarioColor(scenarios)
    : plan.scenario.color;
  const scenario: Scenario = {
    id: newId(),
    name: uniqueName(plan.scenario.name, scenarios),
    color,
    ...(plan.scenario.description ? { description: plan.scenario.description } : {}),
    nodes: levers.map((id) => copy.ids.get(id)!),
    collapsed: true,
    box: { x: at.x, y: at.y },
    source: { project: plan.project.id, scenario: plan.scenario.id },
  };

  return { nodes: [...copy.nodes, ...parameters], edges, loaders, reused, outputs, scenario };
}

/**
 * The nodes and edges a drop loads into the canvas: the reused nodes (whose
 * shared tags a restored copy's run key reads), the Data Loading nodes that
 * arrived, and the copies. An edge from a loader that did not arrive is left
 * out, so no edge names a node that is not there.
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
