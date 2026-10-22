/**
 * A node's latest output, as a word: done, failed, stale or not run. Read from
 * the flow's `nodeExecStatus` and the node's own output, with no import of the
 * node registry, so a header's chips (utils/references/inputScope) can ask it
 * as a scenario's details do (components/scenarios/scenarioLabels).
 */

type NodeLike = { id: string; data?: any };

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
