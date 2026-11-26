/**
 * The user's pick on a node's candidates card, from the client's side: the
 * pick is recorded on the node's Dataset Finder (`useAgentProposals`), naming
 * the card it was made on, then every chat that asked for the candidates is
 * read again, since each says the source is recorded too, and the plan that
 * waited for the node goes on by itself, as the pick's `plan-waiting` answer
 * says, as the user was going: with its Build & validate after a Build &
 * validate, with one Step after a Step, else with the plan row's Solve that
 * left the node waiting. A build running now builds the node itself, and a
 * pick no plan waited on starts nothing more here (the server starts the
 * node's builder).
 */
import { useCallback } from "react";

import { useOptionalToastContext } from "../ToastProvider";
import type { AgentDatasetPick, AgentDatasetSelection } from "../../services/agents/types";

export function usePickGoesOn(opts: {
  recordDatasetSelection: (
    attachmentId: string,
    picks: AgentDatasetPick[],
    discoveryId?: string,
  ) => Promise<AgentDatasetSelection>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
  runSimulation: (attachmentId: string, mode: "step" | "auto") => Promise<unknown>;
  validateNode: (attachmentId: string, target: { ref?: string }) => Promise<unknown>;
}): (attachmentId: string, picks: AgentDatasetPick[], discoveryId?: string) => Promise<AgentDatasetSelection> {
  const { recordDatasetSelection, refreshAfterMutation, runSimulation, validateNode } = opts;
  // The toast says why a plan could not go on; the provider still renders
  // where none is mounted (a test, an embedded surface).
  const toast = useOptionalToastContext();

  return useCallback(
    async (attachmentId: string, picks: AgentDatasetPick[], discoveryId?: string) => {
      const selection = await (discoveryId
        ? recordDatasetSelection(attachmentId, picks, discoveryId)
        : recordDatasetSelection(attachmentId, picks));
      // Every chat that asked holds the same card and its Source recorded turn.
      const askers = selection.askers?.length ? selection.askers : selection.askedBy ? [selection.askedBy] : [];
      for (const asker of askers) {
        if (asker !== attachmentId) void refreshAfterMutation(asker).catch(() => undefined);
      }
      const delegated = selection.delegated;
      if (delegated?.status === "plan-waiting" && delegated.attachmentId && !delegated.running) {
        const planAgent = delegated.attachmentId;
        const goesOn =
          delegated.continueWith === "build"
            ? runSimulation(planAgent, "auto")
            : delegated.continueWith === "step"
              ? runSimulation(planAgent, "step")
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
