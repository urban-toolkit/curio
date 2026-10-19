/**
 * Which nodes are Vega-Lite charts: the built-in Vega-Lite node, and a package
 * template that draws with its grammar (`grammarId: "vega-lite"`), such as the
 * SCOUT Comparison package's charts (`packages/scout.comparison@1`). Such a
 * template draws with the Vega-Lite node's own behavior, so every rule keyed
 * on the node's kind asks this instead of comparing the type with the
 * built-in's: the chart draws from a restored input (`UniversalNode`), a
 * dashboard or a scenario walks through it and saves no output of its own
 * (`utils/dashboardLayout`, `utils/saveOutputDataset`), a notebook cell gives
 * it a chart's height (`utils/notebookLayout`), a selection tag can read its
 * selection (`hook/useSelectionViews`), and a notebook export writes its spec
 * (`NotebookConvertor`). The backend asks the same of a template's manifest
 * (`template_grammar` in `projects/categories.py`).
 *
 * Pure, with no React and no provider.
 */
import { NodeType } from '../constants';
import { unversionedNodeType } from '../utils/flowNodeCanonicalType';
import { tryGetNodeDescriptor } from './nodeRegistry';

/** The grammar a template names to draw as the Vega-Lite node does. */
export const VEGA_LITE_GRAMMAR = 'vega-lite';

/** Whether a node of *nodeType*, versioned or not, is a Vega-Lite chart. */
export function isVegaLiteNodeType(nodeType: string | null | undefined): boolean {
  if (!nodeType) return false;
  if (unversionedNodeType(nodeType) === NodeType.VIS_VEGA) return true;
  return tryGetNodeDescriptor(nodeType)?.grammarId === VEGA_LITE_GRAMMAR;
}
