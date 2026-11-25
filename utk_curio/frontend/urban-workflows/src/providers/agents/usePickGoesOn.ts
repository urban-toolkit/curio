/**
 * The user's pick on a node's candidates card, from the client's side: the
 * pick is recorded on the node's Dataset Finder (`useAgentProposals`), then
 * the chat that asked for the candidates is read again, since it says the
 * source is recorded too, and the plan that waited for the node goes on by
 * itself, as the pick's `plan-waiting` answer says: with its Build & validate
 * when that paused on the node, else with the plan row's Solve that left the
 * node waiting. A build running now builds the node itself, and a pick no plan
 * waited on starts nothing more here (the server starts the node's builder).
 */
import { useCallback } from "react";

import { useOptionalToastContext } from "../ToastProvider";
import type { AgentDatasetPick, AgentDatasetSelection } from "../../services/agents/types";

export function usePickGoesOn(opts: {
  recordDatasetSelection: (attachmentId: string, picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
  runSimulation: (attachmentId: string, mode: "step" | "auto") => Promise<unknown>;
  validateNode: (attachmentId: string, target: { ref?: string }) => Promise<unknown>;
}): (attachmentId: string, picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection> {
  const { recordDatasetSelection, refreshAfterMutation, runSimulation, validateNode } = opts;
  // The toast says why a plan could not go on; the provider still renders
  // where none is mounted (a test, an embedded surface).
  const toast = useOptionalToastContext();

  return useCallback(
    async (attachmentId: string, picks: AgentDatasetPick[]) => {
      const selection = await recordDatasetSelection(attachmentId, picks);
      const asker = selection.askedBy;
      if (asker && asker !== attachmentId) void refreshAfterMutation(asker).catch(() => undefined);
      const delegated = selection.delegated;
      if (delegated?.status === "plan-waiting" && delegated.attachmentId && !delegated.running) {
        const planAgent = delegated.attachmentId;
        const goesOn =
          delegated.continueWith === "build"
            ? runSimulation(planAgent, "auto")
            : delegated.continueWith === "node" && delegated.ref
              ? validateNode(planAgent, { ref: delegated.ref })
              : null;
        goesOn?.catch((e) => {
          toast?.showToast(
            `The plan could not go on with the source: ${e instanceof Error ? e.message : String(e)}`,
            "error",
          );
        });
      }
      return selection;
    },
    [recordDatasetSelection, refreshAfterMutation, runSimulation, validateNode, toast],
  );
}
