import { formatNodeTypeLabel } from "../../../services/datasetLineage/datasetLineageResolver";
// The registry module itself, not its index: the index loads the node
// behaviors, whose components reach the dataset panels.
import { tryGetNodeDescriptor } from "../../../registry/nodeRegistry";

/**
 * A node's kind as the palette names it: its template's label when the
 * registry holds the template, else its type in words. A template id is not
 * always its label: `computation-analysis` is Python Computation.
 */
export function nodeKindLabel(nodeType: string | null | undefined): string {
  return (nodeType && tryGetNodeDescriptor(nodeType)?.label) || formatNodeTypeLabel(nodeType ?? undefined);
}
