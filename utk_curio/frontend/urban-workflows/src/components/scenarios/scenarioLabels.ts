import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

type NodeLike = { id: string; data?: any };

/** What a scenario's details and its box call a node: its title, else its
 *  header's label. */
export function nodeLabel(node: NodeLike | undefined, id: string): string {
  if (!node) return id.slice(0, 8);
  if (typeof node.data?.title === "string" && node.data.title.trim()) return node.data.title.trim();
  try {
    return resolveNodeDisplayLabel(node.data) || id.slice(0, 8);
  } catch {
    return id.slice(0, 8);
  }
}

/** The kind of node it is, as its header names it: Python, Autark… */
export function nodeKind(node: NodeLike | undefined): string {
  if (!node) return "";
  try {
    return resolveNodeDisplayLabel(node.data) || "";
  } catch {
    return "";
  }
}

// An outcome's latest output, as a word, lives where a header's chips can read
// it without the node registry (utils/nodeOutputStatus).
export { outputStatus, type OutputTone } from "../../utils/nodeOutputStatus";
