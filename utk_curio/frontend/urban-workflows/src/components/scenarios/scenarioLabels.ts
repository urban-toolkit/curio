import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

type NodeLike = { id: string; data?: any };

/** What a scenario's details and its box call a node: the name its header
 *  shows, its title, else its template's label. */
export function nodeLabel(node: NodeLike | undefined, id: string): string {
  if (!node) return id.slice(0, 8);
  try {
    return resolveNodeDisplayLabel(node.data) || id.slice(0, 8);
  } catch {
    return id.slice(0, 8);
  }
}

/** The kind of node it is, as its template names it: Python, Autark… Its
 *  title does not change it. */
export function nodeKind(node: NodeLike | undefined): string {
  if (!node) return "";
  try {
    return resolveNodeDisplayLabel({ ...node.data, title: undefined }) || "";
  } catch {
    return "";
  }
}

// An outcome's latest output, as a word, lives where a header's chips can read
// it without the node registry (utils/nodeOutputStatus).
export { outputStatus, type OutputTone } from "../../utils/nodeOutputStatus";
