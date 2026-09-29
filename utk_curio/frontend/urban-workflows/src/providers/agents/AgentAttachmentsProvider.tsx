import React, { createContext, useContext, useEffect, useMemo } from "react";

import { useFlowContext } from "../FlowProvider";
import { useAgentAttachments, type AgentAttachmentsState } from "../../services/agents";
import { useAgentSession, type AgentSessionSlice } from "./useAgentSession";
import { useAgentProposals, type AgentProposalsSlice } from "./useAgentProposals";
import { useAgentSolve, type AgentSolveSlice } from "./useAgentSolve";
import { useAgentSimulation, type AgentSimulationSlice } from "./useAgentSimulation";
import { useAgentNodeRuns, type AgentNodeRunsSlice } from "./useAgentNodeRuns";

/**
 * One source of truth for a project's agent attachments, shared by the canvas
 * dock (canvas-target agents) and the per-node badges (node-target agents) so
 * the two views stay in sync and the list is fetched once. Also owns which
 * attachment's chat panel is open and the per-attachment chat transcripts —
 * a read-through cache over the server-persisted session (memo dev/20), so
 * closing/reopening a chat (and reloading the page) restores the conversation.
 *
 * Since memo dev/142 (F2) the provider COMPOSES five hooks, one per concern —
 * `useAgentSession` (chat, transcripts, the streamed send and its run status),
 * `useAgentProposals` (review-before-apply and the canvas bridge),
 * `useAgentSolve` (the batch, the per-node Solve, the job re-attach),
 * `useAgentSimulation`, `useAgentNodeRuns` — and the context value keeps every
 * key it had, so no consumer changed.
 */
export interface AgentAttachmentsContextValue
  extends AgentAttachmentsState,
    Omit<AgentSessionSlice, "setSelectedId" | "projectRef" | "refreshAfterMutation">,
    AgentProposalsSlice,
    AgentSolveSlice,
    AgentSimulationSlice,
    AgentNodeRunsSlice {
  closeChat: () => void;
}

const AgentAttachmentsContext = createContext<AgentAttachmentsContextValue | null>(null);

export const AgentAttachmentsProvider: React.FC<{
  /** When false (e.g. shared read-only view) the hook is disabled and no
   * attachments are fetched. */
  enabled?: boolean;
  children: React.ReactNode;
}> = ({ enabled = true, children }) => {
  const { projectId } = useFlowContext();
  const effectiveProjectId = enabled ? (projectId ?? null) : null;
  const state = useAgentAttachments(effectiveProjectId);
  const session = useAgentSession(effectiveProjectId, state);
  const { projectRef, refreshAfterMutation, setSelectedId, ...sessionValue } = session;
  const proposals = useAgentProposals({ effectiveProjectId, projectRef, reload: state.reload, refreshAfterMutation });
  const solve = useAgentSolve({ projectRef, attachments: state.attachments, refreshAfterMutation });
  const simulation = useAgentSimulation({ projectRef, refreshAfterMutation });
  const nodeRuns = useAgentNodeRuns({ projectRef, refreshAfterMutation });

  // Opening a chat whose attachment carries a running job re-attaches to it.
  const { selectedId } = session;
  const { attachSolveJob } = solve;
  useEffect(() => {
    if (!selectedId) return;
    const attachment = state.attachments.find((a) => a.attachmentId === selectedId);
    if (attachment?.liveJob?.status === "running") void attachSolveJob(selectedId);
  }, [selectedId, state.attachments, attachSolveJob]);

  const value = useMemo<AgentAttachmentsContextValue>(
    () => ({
      ...state,
      ...sessionValue,
      closeChat: () => setSelectedId(null),
      ...proposals,
      ...solve,
      ...simulation,
      ...nodeRuns,
    }),
    // `sessionValue` is a rest of `session`, whose identity already tracks its fields.
    [state, session, setSelectedId, proposals, solve, simulation, nodeRuns],
  );

  return <AgentAttachmentsContext.Provider value={value}>{children}</AgentAttachmentsContext.Provider>;
};

/** Context accessor that returns null outside a provider (node components may
 * render in ReactFlow surfaces that have no attachments provider). */
export function useAgentAttachmentsContext(): AgentAttachmentsContextValue | null {
  return useContext(AgentAttachmentsContext);
}
