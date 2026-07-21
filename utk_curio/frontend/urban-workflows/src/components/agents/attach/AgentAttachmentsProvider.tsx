import React, { createContext, useContext, useMemo, useState } from "react";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useAgentAttachments, type AgentAttachmentsState } from "./useAgentAttachments";

/**
 * One source of truth for a project's agent attachments, shared by the canvas
 * dock (canvas-target agents) and the per-node badges (node-target agents) so
 * the two views stay in sync and the list is fetched once. Also owns which
 * attachment's chat panel is open, so a node badge or a dock tile can open it.
 */
export interface AgentAttachmentsContextValue extends AgentAttachmentsState {
  /** Attachment whose chat panel is open, or null. */
  selectedId: string | null;
  openChat: (attachmentId: string) => void;
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
  const state = useAgentAttachments(enabled ? (projectId ?? null) : null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const value = useMemo<AgentAttachmentsContextValue>(
    () => ({
      ...state,
      selectedId,
      openChat: setSelectedId,
      closeChat: () => setSelectedId(null),
    }),
    [state, selectedId],
  );

  return (
    <AgentAttachmentsContext.Provider value={value}>
      {children}
    </AgentAttachmentsContext.Provider>
  );
};

/** Context accessor that returns null outside a provider (node components may
 * render in ReactFlow surfaces that have no attachments provider). */
export function useAgentAttachmentsContext(): AgentAttachmentsContextValue | null {
  return useContext(AgentAttachmentsContext);
}
