/**
 * A node's run key (#662): what a run of it depends on, which its last
 * result is stamped with (`data.executedCode`), so the result is reused only
 * while the key still holds.
 */
import { nodeRunKey } from "../widgets/widgetModel";
import { selectionNamesIn } from "./codeReferences";
import { normalizeSelections } from "./selectionTags";

type FlowNodeLike = { id: string; data?: any };

/**
 * What a run of a node depends on: `nodeRunKey` (its code and its widgets'
 * values), and what the node's selection tags its code names hold
 * (*selections*, the node's `data.selections`). Code that names none keeps
 * `nodeRunKey`'s key, so no saved result goes stale; a new selection changes
 * the key.
 */
export function runKeyOf(code: string, widgets: unknown, selections?: unknown): string {
  let key = nodeRunKey(code, widgets);
  const picked = selectionNamesIn(code);
  if (picked.length > 0) {
    const tags = normalizeSelections(selections);
    const held = picked.map((name) => {
      const tag = tags.find((t) => t.name === name);
      return [name, tag ? (Array.isArray(tag.ids) ? tag.ids : { count: tag.count }) : null];
    });
    key += "\u0000selection" + JSON.stringify(held);
  }
  return key;
}

/** A canvas node's run key as its *data* holds it: its code, widgets and selection tags. */
export function runKeyOfData(data: any): string {
  return runKeyOf(String(data?.code ?? ""), data?.widgets, data?.selections);
}

/**
 * Every canvas node's run key now. A run on the server reads them just before
 * the save it runs (useServerRun), so a step's result is stamped with the key
 * its run started with, not one a value changed meanwhile gives.
 */
export function runKeysOf(nodes: readonly FlowNodeLike[]): Map<string, string> {
  return new Map(nodes.map((node) => [node.id, runKeyOfData(node.data)]));
}
