import { useCallback, useEffect, useState } from "react";
import { agentsApi, type AgentAttachment, type AgentTarget } from "../../../api/agentsApi";
import { AGENT_DOCK_REFRESH_EVENT, notifyAgentDockRefresh } from "../../../utils/agentsPaletteEvents";

/**
 * Self-contained hook for a project's agent attachments: the dock reads them,
 * the canvas attaches on drop, and the chat runs them — all over ``agentsApi``.
 * Stays in sync via the ``curio:agent-dock-refresh`` window event.
 */
export interface AgentAttachmentsState {
  attachments: AgentAttachment[];
  busy: boolean;
  error: string | null;
  reload: () => Promise<void>;
  attach: (coord: string, target: AgentTarget) => Promise<AgentAttachment | null>;
  detach: (attachmentId: string) => Promise<void>;
  run: (attachmentId: string, message: string) => Promise<string>;
}

export function useAgentAttachments(projectId: string | null): AgentAttachmentsState {
  const [attachments, setAttachments] = useState<AgentAttachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!projectId) {
      setAttachments([]);
      return;
    }
    try {
      const r = await agentsApi.listAttachments(projectId);
      setAttachments(r.attachments);
    } catch (e) {
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
      const r = await agentsApi.runAttachment(projectId, attachmentId, message, context);
      return r.reply;
    },
    [projectId],
  );

  return { attachments, busy, error, reload, attach, detach, run };
}
