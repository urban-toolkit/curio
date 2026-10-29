/**
 * What the editors a dataflow's owner invited do with its agents.
 *
 * The owner and the editors the owner invited drive the dataflow's agents, on
 * the owner's model and key, in chats they share; a watcher has none. The
 * server decides who is which (`projects/access.py`) and refuses the rest.
 * An install a proposal makes changes an account, the owner's, so only the
 * owner reviews it: the tools that install are those of
 * `contracts/agentInstalls.json`, which the server reads too.
 */
import agentInstalls from "../../contracts/agentInstalls.json";

import type { AgentTurnWriter } from "./types";

/** The agent tools whose Apply installs into an account. */
export const ACCOUNT_INSTALL_TOOLS: ReadonlySet<string> = new Set(agentInstalls.tools);

/** Whether a proposal of *tool* installs into an account, so that its review
 * is the dataflow owner's. */
export function installsIntoAccount(tool: string | null | undefined): boolean {
  return typeof tool === "string" && ACCOUNT_INSTALL_TOOLS.has(tool);
}

/** What a canvas does with the dataflow's agents, by the role the tab has on
 * the dataflow (`canvasRole`): the owner and an invited editor drive them, a
 * watcher has none, and on an editor's canvas an install waits for the owner. */
export function agentsOnCanvas(role: "owner" | "editor" | "watcher"): {
  drives: boolean;
  installsWaitForOwner: boolean;
} {
  return { drives: role !== "watcher", installsWaitForOwner: role === "editor" };
}

/** The dataflow whose agents a canvas drives, by the role the tab has on the
 * dataflow (`canvasRole`). The owner's tab drives those of the dataflow it
 * saves, *saved* (the flow state's `projectId`). An invited editor's tab saves
 * no dataflow, so its `projectId` is null: it drives those of the dataflow its
 * link opened, *opened*. A watcher drives none. */
export function agentsDataflowId(
  role: "owner" | "editor" | "watcher",
  saved: string | null | undefined,
  opened: string | null | undefined,
): string | null {
  if (role === "watcher") return null;
  return (role === "editor" ? opened : saved) ?? null;
}

/** Whether a message *by* names was written by someone other than the
 * viewer, the account *viewerAccount*: the chat names its writer then. A
 * message that names no writer is the viewer's own: one from before writers
 * were kept, or the local copy of one this tab just sent. */
export function writtenBySomeoneElse(
  by: AgentTurnWriter | null | undefined,
  viewerAccount: string | null | undefined,
): boolean {
  return Boolean(by?.account) && by?.account !== (viewerAccount ?? null);
}
