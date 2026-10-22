/**
 * Picks between an Interaction node and the Autark maps it feeds and is
 * linked to (#662), carried as a selection crosses between two views: a pick
 * on a map is that map's selection, which the interaction edge carries to the
 * node (`providers/flow/useInteractions`), and what the node picks, or a rule
 * matches, goes back the same way and lights up on the map. A selection names
 * its features by the values of the layer's id column, as a view that names
 * its key columns does (`selectFields`), and its layer by the table the map
 * draws it under; it is read back with `matchSelections`.
 */
import { NodeType, VisInteractionType } from "../../constants";
import { featureRows, matchSelections, type IncomingSelection, type SelectDetail } from "../selectionMatch";
import { selectionLayer, type SelectionId } from "../references/selectionTags";
import { idKey } from "./applyEdits";

/** The detail a map's pick, and the Interaction node's own, is sent as: the one an Autark map's pick is. */
export const EDIT_SELECTION = "autk_selection";

/**
 * The selection that names *ids*, values of the column *key*, on the layer the
 * map draws as *table*, sent by a node of type *source*. No ids: a selection
 * that holds nothing, which clears what was lit up.
 */
export function editSelection(ids: readonly SelectionId[], key: string, table: string, source: string = NodeType.AUTK_GRAMMAR): Record<string, SelectDetail & { source: string; layerRef: string }> {
  return {
    [EDIT_SELECTION]: {
      type: ids.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
      data: ids.map((id) => ({ [key]: id })),
      priority: 1,
      source,
      layerRef: table,
    },
  };
}

/** What a feature of a layer is to a selection: its id, and its properties. */
export interface SelectableFeature {
  id: SelectionId | null;
  properties: Record<string, unknown>;
}

/**
 * The ids among *features* that the selections in *incoming* pick, each once,
 * in the features' order: the selections *accepts* takes, by the node each
 * comes from and the layer it names (undefined when it names none). Null when
 * it takes none, which is not a selection of nothing.
 */
export function selectedIdsIn(
  incoming: unknown,
  accepts: (nodeId: string | undefined, layer: string | undefined) => boolean,
  features: readonly SelectableFeature[],
): SelectionId[] | null {
  const selections = (Array.isArray(incoming) ? incoming : []).filter(
    (selection: any) => accepts(selection?.nodeId, selectionLayer(selection?.details)),
  ) as IncomingSelection[];
  if (selections.length === 0) return null;
  const rows = featureRows({ features: features.map((feature) => ({ properties: feature.properties })) });
  const ids: SelectionId[] = [];
  const seen = new Set<string>();
  for (const position of [...new Set(matchSelections(selections, rows))].sort((a, b) => a - b)) {
    const id = features[position]?.id;
    const key = id === null || id === undefined ? null : idKey(id);
    if (key === null || seen.has(key)) continue;
    seen.add(key);
    ids.push(id as SelectionId);
  }
  return ids;
}

/** Whether two lists hold the same ids, in the same order. */
export function sameIds(a: readonly SelectionId[], b: readonly SelectionId[]): boolean {
  return a.length === b.length && a.every((id, i) => idKey(id) === idKey(b[i]));
}

/** *current* with *id* added when it is not there, and taken out when it is: a shift-click. */
export function toggledIds(current: readonly SelectionId[], id: SelectionId): SelectionId[] {
  const key = idKey(id);
  return current.some((other) => idKey(other) === key) ? current.filter((other) => idKey(other) !== key) : [...current, id];
}
