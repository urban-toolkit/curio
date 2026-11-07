import type { AgentDropTarget } from "../services/agents";

/**
 * Orchestrates a palette-agent drop → attach. A node target is validated by the
 * backend against the dataflow as the server holds it, so a node added a
 * moment ago must reach the server first: `keepDataflow` waits until the
 * server holds every change this tab made (a dataflow not saved yet is made
 * first), then the attach uses the resolved project id. A drop on the canvas
 * needs no specific node, so it waits only when the dataflow has no id yet,
 * to make it.
 *
 * Dependencies are injected (no React coupling) so this stays unit-testable.
 */
export interface AgentDropAttachDeps {
  /** `null` as well as `undefined`: FlowContext exposes it as `string | null`. */
  projectId: string | null | undefined;
  target: AgentDropTarget;
  agentCoord: string;
  /** The dataflow's id once the server holds this tab's every change, a
   *  dataflow not saved yet made first (`ensureProjectId`): an account's, and
   *  a hosted guest's own, kept until the server starts again. */
  keepDataflow: () => Promise<string | null | undefined>;
  attach: (projectId: string, coord: string, target: AgentDropTarget) => Promise<unknown>;
  /** Whether this is the owner's tab, whose drop waits for `keepDataflow`.
   * An editor the owner invited makes no dataflow and records nothing: the
   * editor's canvas is bound to the dataflow's doc on the server, which the
   * attach reads, so the editor's drop waits for `whenKept` alone. */
  savesHere?: boolean;
  /** Resolves once the server has every change this tab made (the editor's
   *  wait), or gives up after a moment (`FlowProvider.whenChangesKept`). */
  whenKept?: () => Promise<unknown>;
}

/**
 * Keep-then-attach. Returns the target that was attached (for the caller's
 * success message). Throws when there is no resolvable project id, or when the
 * attach rejects — the caller surfaces the message.
 */
export async function attachAgentOnDrop(deps: AgentDropAttachDeps): Promise<{ target: AgentDropTarget }> {
  let projectId = deps.projectId;
  // A connection target is validated against the dataflow's edges exactly the
  // way a node target is validated against its nodes, so a drop onto a freshly
  // drawn edge needs the same wait first. A drop on the canvas of a dataflow
  // not saved yet makes it first, as a drop on its node does: an agent is
  // attached to a dataflow the server holds.
  const keepsFirst = deps.target.kind === "node" || deps.target.kind === "connection" || !projectId;
  if (keepsFirst && deps.savesHere !== false) {
    // The just-dropped-on element reaches the server before the attach is
    // checked against the dataflow. Also covers a never-saved one (made now).
    projectId = (await deps.keepDataflow()) ?? projectId;
  } else if (keepsFirst) {
    // An editor's own change (a node just added, a connection just drawn)
    // reaches the server the same way, through the doc.
    await deps.whenKept?.();
  }
  if (!projectId) {
    throw new Error("Save the project before attaching an agent.");
  }
  await deps.attach(projectId, deps.agentCoord, deps.target);
  return { target: deps.target };
}
