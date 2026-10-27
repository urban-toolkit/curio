import { NodeType } from "../constants";
import { declaresBehavior } from "../registry/declaredNodes";
import { isVegaLiteNodeType } from "../registry/vegaLiteNodes";
import { defaultSaveOutputDatasetFromEnv } from "./curioEnvFlag";
import { flowOutputRefFromRaw, FlowOutputRef } from "./flowOutputRef";
import { getFlowNodeCanonicalType } from "./flowNodeCanonicalType";
import { isDatasetPaletteNode } from "../services/datasetCatalog/datasetApplication";

/**
 * The behaviors of the "sink" nodes, which never produce a NEW dataset. The
 * charts consume a dataframe to render and pass their INPUT straight through
 * as their output (outputCallback(nodeId, data.input)) so they can sit
 * mid-chain: saving their passthrough would auto-install a redundant computed
 * dataset that just duplicates the upstream node's output (same file,
 * different node id). A Data Export's output is the name of the file it wrote,
 * no dataset either. Kept equal with the backend ``_SINK_BEHAVIORS``
 * (utk_curio/backend/app/projects/services.py).
 */
const NON_PRODUCING_BEHAVIORS: ReadonlySet<string> = new Set(["vega", "simple-vis", "data-export"]);

/**
 * The built-in sink nodes, for a type no template declares a behavior for.
 *
 * Kept set-equal with the backend ``_SINK_NODE_TYPES``
 * (utk_curio/backend/app/projects/services.py) — a drift-guard test enforces
 * it. Entries are UNVERSIONED; check membership via ``isNonProducingNodeType``,
 * which strips the ``@<major>`` palette-dragged nodes carry (#169).
 */
export const NON_PRODUCING_NODE_TYPES: ReadonlySet<string> = new Set([
  NodeType.VIS_VEGA,
  NodeType.VIS_SIMPLE,
  NodeType.DATA_EXPORT,
]);

/**
 * Whether a node of *nodeType* makes no dataset of its own: its template
 * declares a sink's behavior (registry/declaredNodes), or draws with the
 * Vega-Lite grammar (registry/vegaLiteNodes), as the backend's
 * ``_is_sink_node_type`` reads it.
 */
export function isNonProducingNodeType(nodeType: string): boolean {
  return (
    declaresBehavior(nodeType, NON_PRODUCING_BEHAVIORS, NON_PRODUCING_NODE_TYPES) ||
    isVegaLiteNodeType(nodeType)
  );
}

/**
 * Whether a node's footer shows the save-output toggle (#445): a playable node
 * whose output can be saved. Not a dataset-palette node (saving is locked
 * there) and not a visualization sink (nothing of its own to save).
 */
export function showsSaveOutputToggle(data: any, disablePlay: boolean): boolean {
  if (disablePlay) return false;
  if (isDatasetPaletteNode(data)) return false;
  return !isNonProducingNodeType(String(data?.nodeType ?? ""));
}

/** Workflow-wide default when a node has no explicit ``saveOutputDataset`` (env + UI). */
export const DEFAULT_SAVE_OUTPUT_DATASET = defaultSaveOutputDatasetFromEnv();

/**
 * Whether a node's output must be saved because a dashboard tile needs it.
 *
 * A pinned tile renders from its input, so the node feeding it has to have its
 * output in the Data Catalog for the dashboard to draw without a run
 * (``dashboardSourceNodeIds`` picks those nodes). This is on top of the per-node
 * Save toggle, never instead of it.
 *
 * A dataset-palette node is the exception and stays off: its output IS an
 * installed dataset, so a reload restores it from the dataset it reads and a
 * computed copy would just duplicate it (the backend installers refuse it too).
 */
export function shouldSaveOutputOnRun(
  data: { saveOutputDataset?: boolean } | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
  isDashboardSource: boolean = false,
): boolean {
  if (isDatasetPaletteNode(data)) return false;
  return resolveSaveOutputDataset(data, defaultSave) || isDashboardSource;
}

/** Whether a node run should write catalog parquet + auto-install. */
export function resolveSaveOutputDataset(
  data: { saveOutputDataset?: boolean } | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
): boolean {
  // A dataset-palette node just loads an already-installed listing — it must
  // never regenerate a dataset, so saving is force-disabled regardless of the
  // per-node toggle or workflow default. buildSaveableLiveOutputs routes through
  // here, so this also keeps "Play all" from auto-installing these nodes.
  if (isDatasetPaletteNode(data)) {
    return false;
  }
  if (data && typeof data.saveOutputDataset === "boolean") {
    return data.saveOutputDataset;
  }
  return defaultSave;
}

interface SaveableOutput {
  nodeId?: string;
  output?: unknown;
}

interface SaveableNode {
  id?: string;
  type?: string | null;
  data?: { nodeId?: string; nodeType?: string | null; saveOutputDataset?: boolean } | null;
}

/**
 * Build the catalog ``liveOutputs`` list from in-session node outputs, keeping
 * only the nodes whose "Save output dataset" toggle is enabled (which defaults
 * to ``CURIO_DEFAULT_SAVE_NODE_OUTPUT``) or which feed a pinned dashboard tile
 * (*dashboardSources*). Nodes that don't save their output are ephemeral and
 * must not surface as Computed datasets in the catalog/palette.
 */
export function buildSaveableLiveOutputs(
  outputs: SaveableOutput[] | null | undefined,
  nodes: SaveableNode[] | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
  dashboardSources?: ReadonlySet<string> | null,
): FlowOutputRef[] | undefined {
  if (!outputs || outputs.length === 0) return undefined;

  const feedsADashboardTile = (node: SaveableNode): boolean => {
    if (!dashboardSources || dashboardSources.size === 0) return false;
    if (typeof node?.id === "string" && dashboardSources.has(node.id)) return true;
    const dataNodeId = node?.data?.nodeId;
    return typeof dataNodeId === "string" && dashboardSources.has(dataNodeId);
  };

  const saveByNodeId = new Map<string, boolean>();
  for (const node of nodes || []) {
    // Visualization/sink nodes never produce a new dataset — they pass their
    // input through — so never save them, regardless of the per-node toggle.
    const isSink = isNonProducingNodeType(getFlowNodeCanonicalType(node));
    // A node feeding a pinned dashboard tile is recorded whatever its toggle
    // says: the ref is what lets a reload hand the tile its data. Unlike the
    // toggle, this also records a dataset-palette node, whose ref resolves
    // against the dataset it reads rather than a computed copy.
    const enabled =
      !isSink
      && (feedsADashboardTile(node)
        || resolveSaveOutputDataset(node?.data, defaultSave));
    if (typeof node?.id === "string") saveByNodeId.set(node.id, enabled);
    const dataNodeId = node?.data?.nodeId;
    if (typeof dataNodeId === "string") saveByNodeId.set(dataNodeId, enabled);
  }

  const refs = outputs
    .filter((o) => saveByNodeId.get(o?.nodeId ?? "") === true)
    .map((o) => flowOutputRefFromRaw(o?.nodeId ?? "", o?.output))
    .filter((r): r is FlowOutputRef => r !== null);

  return refs.length > 0 ? refs : undefined;
}
