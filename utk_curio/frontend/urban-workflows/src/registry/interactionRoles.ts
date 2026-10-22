/**
 * Whether an interaction edge between two nodes carries a selection, read off
 * their registered templates as the agents read it off the manifests
 * (`interaction_roles` and `interaction_highlighters` in
 * `agents/domain/plan_topology.py`). Both ends of an interaction edge have the
 * `in/out` handle, which a template that declares `bidirectional` gets. Such a
 * node is a visualization when its category is one (`vis_*`), else a pool. A
 * pool takes every selection it receives, and a grammar visualization
 * (`vis_grammar`) highlights the rows another view selects; any other
 * visualization, such as a Simple View, shows none.
 *
 * Pure, with no React and no provider.
 */
import { tryGetNodeDescriptor } from './nodeRegistry';

/** What the canvas says when it refuses an interaction edge that would carry nothing. */
export const INTERACTION_EDGE_CARRIES_NOTHING =
  'Neither node shows the selections it receives, so this interaction edge would carry nothing. ' +
  'Link one to a Data Pool and feed the other from the pool.';

/** Whether a node of *nodeType* shows a selection it receives over an
 * interaction edge. A type no descriptor is registered for is taken to show
 * one: no refusal is made up. */
export function showsReceivedSelections(nodeType: string | null | undefined): boolean {
  if (!nodeType) return true;
  const category = tryGetNodeDescriptor(nodeType)?.category;
  if (category === undefined) return true;
  return !category.startsWith('vis') || category === 'vis_grammar';
}

/** Whether an interaction edge between nodes of these types carries a
 * selection: at least one end shows what the other selects. */
export function interactionEdgeCarries(
  sourceType: string | null | undefined,
  targetType: string | null | undefined,
): boolean {
  return showsReceivedSelections(sourceType) || showsReceivedSelections(targetType);
}
