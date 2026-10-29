/**
 * The agent tools whose work lands at once as the agent's change, with its
 * Undo (`proposals/changes.py` on the server): those of
 * `contracts/agentChanges.json`, which the server reads too. A review of one,
 * saved before agents changed the dataflow directly, can no longer be
 * applied: its card says so and offers Dismiss alone, and the server refuses
 * its Apply.
 */
import agentChanges from "../../contracts/agentChanges.json";

/** The agent tools whose work lands as the agent's change. */
export const AGENT_CHANGE_TOOLS: ReadonlySet<string> = new Set(agentChanges.tools);

/** Whether the work of *tool* lands as the agent's change, so that a review
 * of it is one saved before agents changed the dataflow directly. */
export function landsAsAChange(tool: string | null | undefined): boolean {
  return typeof tool === "string" && AGENT_CHANGE_TOOLS.has(tool);
}
