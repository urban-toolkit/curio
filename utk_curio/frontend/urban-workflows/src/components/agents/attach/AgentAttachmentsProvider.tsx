import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useFlowContext } from "../../../providers/FlowProvider";
import { agentsApi, type AgentSessionTurn } from "../../../api/agentsApi";
import { useAgentAttachments, type AgentAttachmentsState } from "./useAgentAttachments";

/**
 * One source of truth for a project's agent attachments, shared by the canvas
 * dock (canvas-target agents) and the per-node badges (node-target agents) so
 * the two views stay in sync and the list is fetched once. Also owns which
 * attachment's chat panel is open and the per-attachment chat transcripts —
 * a read-through cache over the server-persisted session (memo dev/20), so
 * closing/reopening a chat (and reloading the page) restores the conversation.
 */
export interface AgentAttachmentsContextValue extends AgentAttachmentsState {
  /** Attachment whose chat panel is open, or null. */
  selectedId: string | null;
  openChat: (attachmentId: string) => void;
  closeChat: () => void;
  /** Per-attachment transcript cache, hydrated from the server session. */
  transcripts: Record<string, AgentSessionTurn[]>;
  /** Attachment id whose session history is currently loading, or null. */
  hydratingId: string | null;
  /** Per-attachment history-load errors (retry via hydrateSession). */
  hydrateErrors: Record<string, string>;
  hydrateSession: (attachmentId: string) => Promise<void>;
  /** Run one turn: appends the user turn, the reply (or an error marker). */
  sendMessage: (attachmentId: string, message: string) => Promise<void>;
  /** Persist the attachment's editable intent (null/empty → prompt source). */
  saveIntent: (attachmentId: string, intent: string | null) => Promise<void>;
  /** Clear the server transcript and the local cache (keeps the attachment). */
  clearConversation: (attachmentId: string) => Promise<void>;
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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, AgentSessionTurn[]>>({});
  const [hydratingId, setHydratingId] = useState<string | null>(null);
  const [hydrateErrors, setHydrateErrors] = useState<Record<string, string>>({});
  const hydratedRef = useRef<Set<string>>(new Set());
  const projectRef = useRef<string | null>(effectiveProjectId);

  // Project switch: sessions are project-private — drop the chat state.
  useEffect(() => {
    projectRef.current = effectiveProjectId;
    setSelectedId(null);
    setTranscripts({});
    setHydrateErrors({});
    hydratedRef.current = new Set();
  }, [effectiveProjectId]);

  const appendTurns = useCallback((attachmentId: string, turns: AgentSessionTurn[]) => {
    setTranscripts((prev) => ({
      ...prev,
      [attachmentId]: [...(prev[attachmentId] ?? []), ...turns],
    }));
  }, []);

  const hydrateSession = useCallback(
    async (attachmentId: string) => {
      const pid = projectRef.current;
      if (!pid || hydratedRef.current.has(attachmentId)) return;
      setHydratingId(attachmentId);
      setHydrateErrors((prev) => {
        if (!(attachmentId in prev)) return prev;
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
      try {
        const session = await agentsApi.getSession(pid, attachmentId);
        if (projectRef.current !== pid) return; // stale: project switched mid-fetch
        hydratedRef.current.add(attachmentId);
        setTranscripts((prev) => ({ ...prev, [attachmentId]: session.turns }));
      } catch (e) {
        if (projectRef.current !== pid) return;
        setHydrateErrors((prev) => ({
          ...prev,
          [attachmentId]: e instanceof Error ? e.message : "Failed to load the conversation",
        }));
      } finally {
        setHydratingId((cur) => (cur === attachmentId ? null : cur));
      }
    },
    [],
  );

  const openChat = useCallback(
    (attachmentId: string) => {
      setSelectedId(attachmentId);
      void hydrateSession(attachmentId);
    },
    [hydrateSession],
  );

  const sendMessage = useCallback(
    async (attachmentId: string, message: string) => {
      appendTurns(attachmentId, [{ role: "user", text: message }]);
      try {
        const reply = await state.run(attachmentId, message);
        appendTurns(attachmentId, [{ role: "agent", text: reply }]);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "run failed";
        appendTurns(attachmentId, [{ role: "agent", text: `(error) ${msg}`, error: true }]);
      }
    },
    [appendTurns, state.run],
  );

  const saveIntent = useCallback(
    async (attachmentId: string, intent: string | null) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      await agentsApi.updateAttachmentIntent(pid, attachmentId, intent);
      await state.reload();
    },
    [state.reload],
  );

  const clearConversation = useCallback(
    async (attachmentId: string) => {
      const pid = projectRef.current;
      if (!pid) return;
      await agentsApi.clearSession(pid, attachmentId);
      setTranscripts((prev) => ({ ...prev, [attachmentId]: [] }));
    },
    [],
  );

  // Detach also drops the chat state: a transcript lives exactly as long as
  // its attachment (the server deletes the session file on detach).
  const detach = useCallback(
    async (attachmentId: string) => {
      await state.detach(attachmentId);
      hydratedRef.current.delete(attachmentId);
      setTranscripts((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
    },
    [state.detach],
  );

  const value = useMemo<AgentAttachmentsContextValue>(
    () => ({
      ...state,
      detach,
      selectedId,
      openChat,
      closeChat: () => setSelectedId(null),
      transcripts,
      hydratingId,
      hydrateErrors,
      hydrateSession,
      sendMessage,
      saveIntent,
      clearConversation,
    }),
    [
      state,
      detach,
      selectedId,
      openChat,
      transcripts,
      hydratingId,
      hydrateErrors,
      hydrateSession,
      sendMessage,
      saveIntent,
      clearConversation,
    ],
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
