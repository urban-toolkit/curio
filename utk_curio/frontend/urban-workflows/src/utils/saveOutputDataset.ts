import { defaultSaveOutputDatasetFromEnv } from "./curioEnvFlag";
import { flowOutputRefFromRaw, FlowOutputRef } from "./flowOutputRef";

/** Workflow-wide default when a node has no explicit ``saveOutputDataset`` (env + UI). */
export const DEFAULT_SAVE_OUTPUT_DATASET = defaultSaveOutputDatasetFromEnv();

/** Whether a node run should write catalog parquet + auto-install. */
export function resolveSaveOutputDataset(
  data: { saveOutputDataset?: boolean } | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
): boolean {
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
  data?: { nodeId?: string; saveOutputDataset?: boolean } | null;
}

/**
 * Build the catalog ``liveOutputs`` list from in-session node outputs, keeping
 * only the nodes whose "Save output dataset" toggle is enabled (which defaults
 * to ``CURIO_DEFAULT_SAVE_NODE_OUTPUT``). Nodes that don't save their output are
 * ephemeral and must not surface as Computed datasets in the catalog/palette.
 */
export function buildSaveableLiveOutputs(
  outputs: SaveableOutput[] | null | undefined,
  nodes: SaveableNode[] | null | undefined,
  defaultSave: boolean = DEFAULT_SAVE_OUTPUT_DATASET,
): FlowOutputRef[] | undefined {
  if (!outputs || outputs.length === 0) return undefined;

  const saveByNodeId = new Map<string, boolean>();
  for (const node of nodes || []) {
    const enabled = resolveSaveOutputDataset(node?.data, defaultSave);
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
