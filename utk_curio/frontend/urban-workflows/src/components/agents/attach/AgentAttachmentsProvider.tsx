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
  /** Persist a manual conversation title (memo dev/25): always wins over
   * auto-generation and survives conversation clears. */
  saveTitle: (attachmentId: string, title: string) => Promise<void>;
  /** Clear the server transcript and the local cache (keeps the attachment). */
  clearConversation: (attachmentId: string) => Promise<void>;
  /** Transient tool-activity lines for the live send (memo dev/41): shown as
   * system lines while streaming, never persisted, gone on rehydrate. */
  toolActivity: Record<string, string[]>;
  /** Apply a pending review proposal (the only mutation path); refreshes the
   * transcript + listing so the outcome and result turn arrive together. */
  applyProposal: (attachmentId: string, proposalId: string) => Promise<void>;
  /** Dismiss a pending review proposal without applying it. */
  dismissProposal: (attachmentId: string, proposalId: string) => Promise<void>;
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
  const [toolActivity, setToolActivity] = useState<Record<string, string[]>>({});
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

  const replaceLastAgentTurn = useCallback(
    (
      attachmentId: string,
      text: string,
      execution?: AgentSessionTurn["execution"],
      content?: AgentSessionTurn["content"],
    ) => {
      setTranscripts((prev) => {
        const turns = prev[attachmentId] ?? [];
        const last = turns[turns.length - 1];
        if (!last || last.role !== "agent") return prev;
        const updated = {
          ...last,
          text,
          ...(execution ? { execution } : {}),
          ...(content && content.length ? { content } : {}),
        };
        return { ...prev, [attachmentId]: [...turns.slice(0, -1), updated] };
      });
    },
    [],
  );

  const appendErrorTurn = useCallback(
    (attachmentId: string, e: unknown) => {
      const msg = e instanceof Error ? e.message : "run failed";
      const body = (e as { body?: { resetAt?: string } } | null)?.body;
      const reset = body?.resetAt ? ` — resets ${new Date(body.resetAt).toLocaleString()}` : "";
      appendTurns(attachmentId, [{ role: "agent", text: `(error) ${msg}${reset}`, error: true }]);
    },
    [appendTurns],
  );

  // Streams the reply into a live agent turn (memo dev/22). A failure before
  // any delta with no HTTP status (transport / stream-unsupported / provider
  // stream error) falls back to the blocking run once; HTTP errors (quota 429,
  // 404, …) surface directly as a soft error turn.
  const sendMessage = useCallback(
    async (attachmentId: string, message: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      // The first successful exchange may mint an auto title server-side
      // (memo dev/25); refresh the listing afterwards only while the
      // attachment is untitled so titled sends stay reload-free.
      const untitled = !state.attachments.find((a) => a.attachmentId === attachmentId)?.title;
      appendTurns(attachmentId, [{ role: "user", text: message }]);
      let streamed = "";
      let succeeded = false;
      let sawProposal = false;
      setToolActivity((prev) => ({ ...prev, [attachmentId]: [] }));
      const onEvent = (name: string, payload: Record<string, unknown>) => {
        // Transient system lines (dev/41): "<tool> …" then "<tool> · <status>".
        const tool = typeof payload.tool === "string" ? payload.tool : "";
        const line =
          name === "tool_requested"
            ? `${tool} …`
            : name === "tool_result"
              ? `${tool} · ${payload.status ?? ""}`
              : null;
        if (line)
          setToolActivity((prev) => ({
            ...prev,
            [attachmentId]: [...(prev[attachmentId] ?? []), line],
          }));
        if (name === "review_required") sawProposal = true;
      };
      try {
        const result = await agentsApi.runAttachmentStream(
          pid,
          attachmentId,
          message,
          (delta) => {
            if (!streamed) appendTurns(attachmentId, [{ role: "agent", text: delta }]);
            else replaceLastAgentTurn(attachmentId, streamed + delta);
            streamed += delta;
          },
          onEvent,
        );
        // The finalized turn keeps the run's execution identity + Actual usage
        // (memo dev/37) and its typed content parts (memo dev/39) so the
        // local transcript matches the persisted one.
        const execution = result.executionId
          ? { executionId: result.executionId, usage: result.usage ?? null, status: "ok" as const }
          : undefined;
        const content = result.content && result.content.length ? result.content : undefined;
        sawProposal = sawProposal || Boolean(content?.some((p) => p.type === "proposal"));
        if (!streamed)
          appendTurns(attachmentId, [
            {
              role: "agent",
              text: result.reply,
              ...(execution ? { execution } : {}),
              ...(content ? { content } : {}),
            },
          ]);
        else replaceLastAgentTurn(attachmentId, result.reply, execution, content);
        succeeded = true;
      } catch (e) {
        const status = (e as { status?: number } | null)?.status;
        if (!streamed && status === undefined) {
          // Pre-delta stream failure → one blocking-run fallback.
          try {
            const reply = await state.run(attachmentId, message);
            appendTurns(attachmentId, [{ role: "agent", text: reply }]);
            succeeded = true;
          } catch (e2) {
            appendErrorTurn(attachmentId, e2);
          }
        } else {
          // Mid-stream failure keeps the partial text visible; HTTP errors
          // (e.g. the stable quota 429) render directly.
          appendErrorTurn(attachmentId, e);
        }
      } finally {
        // The live tool lines are transient: gone once the turn finalizes
        // (the durable record is execution.toolCalls, dev/41).
        setToolActivity((prev) => ({ ...prev, [attachmentId]: [] }));
      }
      // A minted proposal changes the attachment's activeProposal mirror.
      if (succeeded && (untitled || sawProposal)) await state.reload();
    },
    [appendTurns, replaceLastAgentTurn, appendErrorTurn, state.run, state.reload, state.attachments],
  );

  const applyProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        await agentsApi.applyProposal(pid, attachmentId, proposalId);
      } finally {
        // Success appends the result turn + statuses; a 409 marked it stale —
        // either way the transcript and listing are the truth: refresh both
        // (dropping the once-guard so the session refetches).
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const dismissProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        await agentsApi.dismissProposal(pid, attachmentId, proposalId);
      } finally {
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
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

  const saveTitle = useCallback(
    async (attachmentId: string, title: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      await agentsApi.updateAttachmentTitle(pid, attachmentId, title);
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
      saveTitle,
      clearConversation,
      toolActivity,
      applyProposal,
      dismissProposal,
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
      saveTitle,
      clearConversation,
      toolActivity,
      applyProposal,
      dismissProposal,
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
