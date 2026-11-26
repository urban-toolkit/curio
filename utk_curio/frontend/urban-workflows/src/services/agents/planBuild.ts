import type { AgentAttachment, AgentSessionTurn, AgentSourcePickPart } from "./types";

/**
 * Whether a Build & validate runs on a landed plan, or a plan row's Solve on
 * one of its nodes, one rule for the plan line, the plan card's rows and Solve
 * this node: while either runs, no other run of the same nodes starts. A build
 * is a stream over the plan, not an agent job, so a Solve started meanwhile
 * would build the same node beside it. The server says whether one runs (the
 * listing's `buildRunning` and `validating`): the browser's clock is never
 * held against the server's.
 */

/** Why no Solve is offered while a build of the plan runs. */
export const BUILD_RUNNING_HINT = "The plan is being built: Stop the build to Solve";

/** Why no build, Step or other row's Solve starts while a row's Solve of the
 * plan runs. */
export const ROW_SOLVE_RUNNING_HINT = "A node of this plan is being solved: wait for its Solve to end";

/** Why Solve this node waits while the node's plan row Solves it. */
export const NODE_ROW_SOLVE_HINT = "This node is being solved by its plan's row: wait for its Solve to end";

/** A build's mode: one action, or every action until a pause. */
export type BuildMode = "step" | "auto";

/** The build running on *attachment*'s plan: the one this tab runs for it
 * (*simulating*), else the one the server says runs (`buildRunning`, another
 * tab's among them); null when none runs. */
export function buildRunningOn(
  attachment: AgentAttachment,
  simulating: BuildMode | null | undefined = null,
): BuildMode | null {
  return simulating ?? attachment.buildRunning ?? null;
}

/** Whether a build runs on a plan that holds the node *nodeId*: a plan of one
 * of *attachments*, whose builds this tab runs are *simulating*, by
 * attachment. */
export function buildRunningOver(
  nodeId: string,
  attachments: AgentAttachment[],
  simulating: Record<string, BuildMode | undefined>,
): boolean {
  return attachments.some(
    (a) =>
      Object.values(a.builderSession?.nodeIds ?? {}).includes(nodeId) &&
      buildRunningOn(a, simulating[a.attachmentId] ?? null) !== null,
  );
}

/** Why Solve this node may not start on the node *nodeId* now: a build runs
 * on a plan that holds it, or a plan row's Solve of it runs (the listing's
 * `validating`); null when nothing runs over it. */
export function solveNodeBlockerFor(
  nodeId: string,
  attachments: AgentAttachment[],
  simulating: Record<string, BuildMode | undefined>,
): string | null {
  if (buildRunningOver(nodeId, attachments, simulating)) return BUILD_RUNNING_HINT;
  if (attachments.some((a) => a.validating?.nodeId === nodeId)) return NODE_ROW_SOLVE_HINT;
  return null;
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
