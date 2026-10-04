import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";

type NodeLike = { id: string; data?: any };

/** What the panel and a box call a node: its title, else its header's label. */
export function nodeLabel(node: NodeLike | undefined, id: string): string {
  if (!node) return id.slice(0, 8);
  if (typeof node.data?.title === "string" && node.data.title.trim()) return node.data.title.trim();
  try {
    return resolveNodeDisplayLabel(node.data) || id.slice(0, 8);
  } catch {
    return id.slice(0, 8);
  }
}

export type OutputTone = "done" | "error" | "stale" | "none";

/** An outcome's latest output, as a word: done, failed, stale or not run. */
export function outputStatus(
  node: NodeLike | undefined,
  execStatus: Record<string, "stale" | "executed" | "errored">,
): { text: string; tone: OutputTone } {
  if (!node) return { text: "Not run", tone: "none" };
  const status = execStatus[node.id];
  if (status === "errored" || node.data?.output?.code === "error") return { text: "Error", tone: "error" };
  if (status === "stale") return { text: "Stale", tone: "stale" };
  if (status === "executed" || node.data?.output?.code === "success") return { text: "Done", tone: "done" };
  return { text: "Not run", tone: "none" };
}
