import type { AgentDropTarget } from "./agentsPaletteEvents";

/**
 * Orchestrates a palette-agent drop → attach. A node target is validated by the
 * backend against the *saved* spec, so a freshly-added (unsaved) node would 400;
 * we persist the current graph first (`saveProject`, create-or-update) so the
 * target node is on disk, then attach using the resolved project id. Canvas
 * targets need no specific node, so they skip the pre-save.
 *
 * Dependencies are injected (no React coupling) so this stays unit-testable.
 */
export interface AgentDropAttachDeps {
  /** `null` as well as `undefined`: FlowContext exposes it as `string | null`. */
  projectId: string | null | undefined;
  target: AgentDropTarget;
  agentCoord: string;
  /** Persist the current dataflow (create-or-update); resolves to the project detail. */
  saveProject: () => Promise<{ id?: string } | null | undefined>;
  attach: (projectId: string, coord: string, target: AgentDropTarget) => Promise<unknown>;
}

/**
 * Persist-then-attach. Returns the target that was attached (for the caller's
 * success message). Throws when there is no resolvable project id, or when the
 * save/attach rejects — the caller surfaces the message.
 */
export async function attachAgentOnDrop(deps: AgentDropAttachDeps): Promise<{ target: AgentDropTarget }> {
  let projectId = deps.projectId;
  if (deps.target.kind === "node") {
    // Flush the graph so the just-dropped-on node exists in the saved spec the
    // backend validates against. Also covers a never-saved project (create).
    const detail = await deps.saveProject();
    projectId = detail?.id ?? projectId;
  }
  if (!projectId) {
    throw new Error("Save the project before attaching an agent.");
  }
  await deps.attach(projectId, deps.agentCoord, deps.target);
  return { target: deps.target };
}
