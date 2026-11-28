/**
 * The plan an invited editor's pick waited on goes on once the dataflow's
 * owner added the dataset he picked, from his tab, as after a direct pick.
 * Her Apply ends the wait and starts no build: it approves adding the
 * dataset, not spending a build. The node's Dataset Finder's record says who
 * picked (`pickedBy`) and keeps how the plan goes on (`goesOn`, the
 * `plan-waiting` answer a direct pick gives); the tab of the account that
 * picked takes it once (`claimGoesOn`, which the server answers once, and
 * with nothing once the plan went on without it) and goes on with it through
 * the pick's own switch (`goOnWithThePlan`). A tab of his opened later, after
 * one closed during the wait, takes it then. The owner's tab takes nothing.
 */
import { useEffect, useRef } from "react";

import { useOptionalToastContext } from "../ToastProvider";
import { useUserContext } from "../userContext";
import { agentsApi, type AgentAttachment } from "../../services/agents";
import { goOnWithThePlan, type PlanRuns } from "./usePickGoesOn";

export function useGoesOnOnceAdded(opts: {
  projectRef: { readonly current: string | null };
  attachments: readonly AgentAttachment[];
} & PlanRuns): void {
  const { projectRef, attachments, runSimulation, validateNode } = opts;
  const { user } = useUserContext();
  const me = user?.id != null ? String(user.id) : null;
  const toast = useOptionalToastContext();
  // Each go-on this tab asked for, by its dataflow, its Finder and the
  // record's time: a listing read again before the server dropped it asks
  // nothing twice.
  const asked = useRef(new Set<string>());

  useEffect(() => {
    const projectId = projectRef.current;
    if (!me || !projectId) return;
    for (const attachment of attachments) {
      const record = attachment.sourceRecord;
      if (!record?.goesOn || record.pickedBy !== me) continue;
      const key = `${projectId}:${attachment.attachmentId}:${record.recordedAt ?? ""}`;
      if (asked.current.has(key)) continue;
      asked.current.add(key);
      agentsApi
        .claimGoesOn(projectId, attachment.attachmentId)
        .then((answer) => goOnWithThePlan(answer?.delegated, { runSimulation, validateNode }, toast))
        .catch(() => {
          // Not taken: the next listing asks again.
          asked.current.delete(key);
        });
    }
  }, [attachments, me, projectRef, runSimulation, validateNode, toast]);
}
