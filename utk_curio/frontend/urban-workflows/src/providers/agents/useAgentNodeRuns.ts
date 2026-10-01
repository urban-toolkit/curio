/**
 * Running and validating one node from chat (memo dev/142, F2 — extracted
 * from `AgentAttachmentsProvider`): the real run through the node (dev/71,
 * journaled) and the validate-node stream (dev/67-7). The result card and any
 * journal-derived state arrive by refetch.
 */
import { useCallback, useMemo } from "react";

import { agentsApi } from "../../services/agents";

type NodeTarget = { ref?: string; nodeId?: string };
type OnEvent = (name: string, payload: Record<string, unknown>) => void;

export interface AgentNodeRunsSlice {
  runNode: (attachmentId: string, target: NodeTarget, onEvent?: OnEvent) => Promise<Record<string, unknown>>;
  validateNode: (attachmentId: string, target: NodeTarget, onEvent?: OnEvent) => Promise<Record<string, unknown>>;
}

export function useAgentNodeRuns(opts: {
  projectRef: React.MutableRefObject<string | null>;
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentNodeRunsSlice {
  const { projectRef, refreshAfterMutation } = opts;

  const runNode = useCallback(
    async (attachmentId: string, target: NodeTarget, onEvent?: OnEvent) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await agentsApi.runNode(pid, attachmentId, target, onEvent ?? (() => undefined));
      } finally {
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  const validateNode = useCallback(
    async (attachmentId: string, target: NodeTarget, onEvent?: OnEvent) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await agentsApi.validateNode(pid, attachmentId, target, onEvent ?? (() => undefined));
      } finally {
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, refreshAfterMutation],
  );

  return useMemo(() => ({ runNode, validateNode }), [runNode, validateNode]);
}
