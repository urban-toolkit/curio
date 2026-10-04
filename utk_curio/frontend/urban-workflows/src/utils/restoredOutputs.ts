/**
 * Saved outputs the server restored, as the canvas takes them in. Opening a
 * project hands over the manifest's outputs (#407), and a scenario dropped
 * from the Scenario Catalog the outputs copied for it (#662), both as
 * `{node_id, filename, data_type}` refs.
 */
import type { IOutput } from "../providers/flow/flowTypes";

export interface SavedOutputRef {
  node_id: string;
  filename: string;
  data_type?: string;
}

/** The file each restored node's output is in, by node: those nodes are built as having run. */
export function restoredByNode(refs: readonly SavedOutputRef[] | null | undefined): Record<string, string> {
  const restored: Record<string, string> = {};
  for (const ref of refs ?? []) {
    if (ref?.node_id && ref.filename) restored[ref.node_id] = ref.filename;
  }
  return restored;
}

/** The refs as flow outputs. */
export function restoredOutputs(refs: readonly SavedOutputRef[]): IOutput[] {
  return refs.map((ref) => ({
    nodeId: ref.node_id,
    // Carry the TYPE, not just the name. A Vega node refuses an input
    // whose type it cannot see ("undefined is not a valid input type"),
    // and a bare filename has none, so a restored chart rejected its own
    // data and rendered the empty state instead. The manifest records the
    // type beside the filename precisely so this does not have to be
    // guessed.
    output: ref.data_type ? { path: ref.filename, dataType: ref.data_type } : ref.filename,
  }));
}

/** *prev* with *next* merged in: a node's restored output replaces the one it had. */
export function withOutputs(prev: IOutput[], next: readonly IOutput[]): IOutput[] {
  const merged = [...prev];
  for (const output of next) {
    const index = merged.findIndex((m) => m.nodeId === output.nodeId);
    if (index >= 0) merged[index] = output;
    else merged.push(output);
  }
  return merged;
}
