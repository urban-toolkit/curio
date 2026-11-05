import { useCallback, useEffect, useRef, useState } from "react";
import { agentsApi } from "./agentsApi";
import { AGENT_DOCK_REFRESH_EVENT, notifyAgentDockRefresh } from "./agentEvents";
import type { AgentAttachment, AgentContentPart, AgentRunSkillPins, AgentTarget, AgentUsage } from "./types";

/**
 * Self-contained hook for a project's agent attachments: the dock reads them,
 * the canvas attaches on drop, and the chat runs them — all over ``agentsApi``.
 * Stays in sync via the ``curio:agent-dock-refresh`` window event, and with
 * the agents someone else attaches, takes off or changes through the
 * dataflow's room (`providers/agents/useAttachmentsInTheRoom.ts`).
 */
export interface AgentAttachmentsState {
  attachments: AgentAttachment[];
  busy: boolean;
  error: string | null;
  reload: () => Promise<void>;
  attach: (coord: string, target: AgentTarget) => Promise<AgentAttachment | null>;
  detach: (attachmentId: string) => Promise<void>;
  run: (
    attachmentId: string,
    message: string,
    context?: string | null,
  ) => Promise<{
    reply: string;
    executionId?: string;
    usage?: AgentUsage | null;
    /** The run's wall-clock duration (memo dev/80); absent on old servers. */
    durationMs?: number;
    content?: AgentContentPart[];
    /** The skills the run's system turn held, as its record keeps them. */
    skills?: AgentRunSkillPins;
    /** The skills the run loaded with skill.read. */
    skillsLoaded?: string[];
  }>;
}

export function useAgentAttachments(projectId: string | null): AgentAttachmentsState {
  const [attachments, setAttachments] = useState<AgentAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only the newest read's answer is kept: reads can overlap, as the room's
  // word at once and its word when a wait ends do, and an older answer, or
  // its failure, can land last.
  const lastReadRef = useRef(0);
  const reload = useCallback(async () => {
    const mine = ++lastReadRef.current;
    if (!projectId) {
      setAttachments([]);
      return;
    }
    try {
      const r = await agentsApi.listAttachments(projectId);
      if (lastReadRef.current === mine) setAttachments(r.attachments);
    } catch (e) {
      if (lastReadRef.current !== mine) return;
      setError(e instanceof Error ? e.message : "Failed to load attachments");
      setAttachments([]);
    }
  }, [projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    const onRefresh = () => reload();
    window.addEventListener(AGENT_DOCK_REFRESH_EVENT, onRefresh);
    return () => window.removeEventListener(AGENT_DOCK_REFRESH_EVENT, onRefresh);
  }, [reload]);

  const attach = useCallback(
    async (coord: string, target: AgentTarget) => {
      if (!projectId) return null;
      setBusy(true);
      setError(null);
      try {
        const created = await agentsApi.attach(projectId, coord, target);
        notifyAgentDockRefresh();
        return created;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Attach failed");
        return null;
      } finally {
        setBusy(false);
      }
    },
    [projectId],
  );

  const detach = useCallback(
    async (attachmentId: string) => {
      if (!projectId) return;
      setBusy(true);
      try {
        await agentsApi.detachAttachment(projectId, attachmentId);
        notifyAgentDockRefresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Detach failed");
      } finally {
        setBusy(false);
      }
    },
    [projectId],
  );

  const run = useCallback(
    async (attachmentId: string, message: string, context?: string | null) => {
      if (!projectId) throw new Error("no project");
      // The FULL payload (dev/53): the stream fallback must lose no content
      // parts: a plan or a node an agent landed over this path still needs its
      // change card, and the execution record still belongs on the turn.
      return agentsApi.runAttachment(projectId, attachmentId, message, context);
    },
    [projectId],
  );

  return { attachments, busy, error, reload, attach, detach, run };
}
