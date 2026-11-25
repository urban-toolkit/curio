import type { AgentAttachment, AgentSessionTurn, AgentSourcePickPart } from "./types";

/**
 * Whether a Build & validate runs on a landed plan, one rule for the plan
 * line, the plan card's rows and Solve this node: while one runs over a node's
 * plan, no Solve of that node starts. A build is a stream over the plan, not an
 * agent job, so a Solve started meanwhile would build the same node beside it.
 */

/** Why no Solve is offered while a build of the plan runs. */
export const BUILD_RUNNING_HINT = "The plan is being built: Stop the build to Solve";

/** How long a build may run before the server takes it for gone, in seconds
 * (`solve/budgets.py`'s `SIMULATE_STALE_SECONDS`). */
export const BUILD_STALE_S = 15 * 60;

/** A build's mode: one action, or every action until a pause. */
export type BuildMode = "step" | "auto";

/** The build running on *attachment*'s plan: the one this tab runs for it
 * (*simulating*), else the one the listing names (another tab's), while its
 * start is more recent than a build may run; null when none runs. */
export function buildRunningOn(
  attachment: AgentAttachment,
  simulating: BuildMode | null | undefined = null,
  nowS: number = Date.now() / 1000,
): BuildMode | null {
  if (simulating) return simulating;
  const session = attachment.builderSession;
  const mode = session?.simulateMode;
  const since = Number(session?.simulatingSince ?? 0);
  if (!mode || !since || nowS - since >= BUILD_STALE_S) return null;
  return mode;
}

/** Whether a build runs on a plan that holds the node *nodeId*: a plan of one
 * of *attachments*, whose builds this tab runs are *simulating*, by
 * attachment. */
export function buildRunningOver(
  nodeId: string,
  attachments: AgentAttachment[],
  simulating: Record<string, BuildMode | undefined>,
  nowS: number = Date.now() / 1000,
): boolean {
  return attachments.some(
    (a) =>
      Object.values(a.builderSession?.nodeIds ?? {}).includes(nodeId) &&
      buildRunningOn(a, simulating[a.attachmentId] ?? null, nowS) !== null,
  );
}

/** Whether a chat's *turns* hold the card of the node *nodeId*'s candidates:
 * the card the chat that asked for them holds (a `sourcePick` part), or, in
 * the chat of the node's own Dataset Finder (*findsFor* is its node), the
 * Finder's own card. */
export function holdsSourceCardFor(turns: AgentSessionTurn[], nodeId: string, findsFor?: string | null): boolean {
  return turns.some((turn) =>
    (turn.content ?? []).some(
      (part) =>
        (part.type === "sourcePick" && (part as AgentSourcePickPart).nodeId === nodeId) ||
        (part.type === "datasetCandidates" && findsFor === nodeId),
    ),
  );
}
