import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

type NodeLike = { id: string; data?: any };

/** What a scenario's details and its box call a node: the name its header
 *  was renamed to on the canvas, else its title (an agent's or an example's),
 *  else its header's label. */
export function nodeLabel(node: NodeLike | undefined, id: string): string {
  if (!node) return id.slice(0, 8);
  const renamed = node.data?.packageTemplateLabel;
  if (typeof renamed === "string" && renamed.trim()) return renamed.trim();
  if (typeof node.data?.title === "string" && node.data.title.trim()) return node.data.title.trim();
  try {
    return resolveNodeDisplayLabel(node.data) || id.slice(0, 8);
  } catch {
    return id.slice(0, 8);
  }
}

/** The kind of node it is, as its template names it: Python, Autark… A
 *  header renamed on the canvas does not change it. */
export function nodeKind(node: NodeLike | undefined): string {
  if (!node) return "";
  try {
    return resolveNodeDisplayLabel({ ...node.data, packageTemplateLabel: undefined }) || "";
  } catch {
    return "";
  }
}

// An outcome's latest output, as a word, lives where a header's chips can read
// it without the node registry (utils/nodeOutputStatus).
export { outputStatus, type OutputTone } from "../../utils/nodeOutputStatus";
