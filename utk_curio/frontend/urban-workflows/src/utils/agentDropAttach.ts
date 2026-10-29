import type { AgentDropTarget } from "../services/agents";
import { hostedGuestSignInNote } from "../components/apiSettings/useHostedGuest";

/**
 * Orchestrates a palette-agent drop → attach. A node target is validated by the
 * backend against the dataflow as the server holds it, so a node added a
 * moment ago must reach the server first: `keepDataflow` waits until the
 * server holds every change this tab made (a dataflow not saved yet is made
 * first), then the attach uses the resolved project id. Canvas targets need no
 * specific node, so they skip the wait.
 *
 * Dependencies are injected (no React coupling) so this stays unit-testable.
 */
export interface AgentDropAttachDeps {
  /** `null` as well as `undefined`: FlowContext exposes it as `string | null`. */
  projectId: string | null | undefined;
  target: AgentDropTarget;
  agentCoord: string;
  /** The dataflow's id once the server holds this tab's every change, a
   *  dataflow not saved yet made first (`ensureProjectId`). */
  keepDataflow: () => Promise<string | null | undefined>;
  attach: (projectId: string, coord: string, target: AgentDropTarget) => Promise<unknown>;
  /** A hosted guest (`isHostedGuest`), who cannot save the dataflow. */
  hostedGuest?: boolean;
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
  // drawn edge needs the same wait first.
  const keepsFirst = deps.target.kind === "node" || deps.target.kind === "connection";
  // A hosted guest cannot make the dataflow, nor attach to one it never
  // saved: it is told to sign in, before anything is sent. A note, shown as a
  // warning like the other sign-in notes, not as a failure.
  if (deps.hostedGuest && (keepsFirst || !projectId)) {
    throw Object.assign(new Error(hostedGuestSignInNote("attach agents")), { toastVariant: "warning" as const });
  }
  if (keepsFirst) {
    // The just-dropped-on element reaches the server before the attach is
    // checked against the dataflow. Also covers a never-saved one (made now).
    projectId = (await deps.keepDataflow()) ?? projectId;
  }
  if (!projectId) {
    throw new Error("Save the project before attaching an agent.");
  }
  await deps.attach(projectId, deps.agentCoord, deps.target);
  return { target: deps.target };
}
