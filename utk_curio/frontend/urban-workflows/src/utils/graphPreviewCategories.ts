/**
 * The category a preview built in the browser gives a node: its registered
 * descriptor's, which is the category the node's template declares. The
 * server gives a saved project's preview the same, read off the manifests, so
 * a dataflow's thumbnail colours a node alike wherever it is drawn.
 */
import type { GraphPreview } from "../api/projectsApi";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import type { NodeCategory } from "../registry/types";

/** The category of the descriptor registered for *nodeType*, versioned or
 *  not; null for a type nothing registered provides. */
export function registeredCategory(nodeType: unknown): NodeCategory | null {
  if (typeof nodeType !== "string" || nodeType === "") return null;
  return tryGetNodeDescriptor(nodeType)?.category ?? null;
}

/**
 * *preview*, a copy, with each node in its registered descriptor's category,
 * or the category it carries when nothing registered provides its type. A
 * dataflow's versions are drawn this way, so a version recorded before its
 * package registered, or saved without categories, is coloured too.
 */
export function withRegisteredCategories(preview: GraphPreview | null | undefined): GraphPreview | null {
  if (!preview) return null;
  if (!Array.isArray(preview.nodes)) return preview;
  return {
    ...preview,
    nodes: preview.nodes.map((node) => ({
      ...node,
      category: registeredCategory(node.type) ?? node.category ?? null,
    })),
  };
}
