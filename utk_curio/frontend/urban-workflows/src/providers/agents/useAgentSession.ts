/**
 * The chat side of an attachment (memo dev/142, F2 — extracted from
 * `AgentAttachmentsProvider`): which chat is open, the per-attachment
 * transcript cache (a read-through cache over the server-persisted session,
 * memo dev/20), the streamed send with its run status (dev/22, dev/80), and
 * the intent/title/clear edits. It also owns the project ref and the
 * "refresh after a mutation" sequence the other agent hooks share.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AgentRemedy } from "../../services/agents";
import { agentsApi, type AgentAttachmentsState } from "../../services/agents";
import type { AgentSessionTurn, AgentUsage } from "../../services/agents/types";
import type { AgentRunStatus } from "../../services/agents/agentRunStatus";

export interface AgentSessionSlice {
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  openChat: (attachmentId: string) => void;
  transcripts: Record<string, AgentSessionTurn[]>;
  hydratingId: string | null;
  hydrateErrors: Record<string, string>;
  hydrateSession: (attachmentId: string) => Promise<void>;
  sendMessage: (attachmentId: string, message: string, context?: string | null) => Promise<void>;
  saveIntent: (attachmentId: string, intent: string | null) => Promise<void>;
  saveTitle: (attachmentId: string, title: string) => Promise<void>;
  clearConversation: (attachmentId: string) => Promise<void>;
  toolActivity: Record<string, string[]>;
  runStatus: Record<string, AgentRunStatus>;
  detach: (attachmentId: string) => Promise<void>;
  /** The current project id, readable inside async callbacks. */
  projectRef: React.MutableRefObject<string | null>;
  /** After a mutation the transcript and the listing are the truth: drop the
   * once-guard, refetch the session, reload the listing. */
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}

export function useAgentSession(
  effectiveProjectId: string | null,
  state: AgentAttachmentsState,
): AgentSessionSlice {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [transcripts, setTranscripts] = useState<Record<string, AgentSessionTurn[]>>({});
  const [hydratingId, setHydratingId] = useState<string | null>(null);
  const [hydrateErrors, setHydrateErrors] = useState<Record<string, string>>({});
  const [toolActivity, setToolActivity] = useState<Record<string, string[]>>({});
  // dev/80: per-attachment run status for the chat status strip. The seq
  // counter guards against a stale run's late events overwriting a newer
  // run's entry (rapid re-sends).
  const [runStatus, setRunStatus] = useState<Record<string, AgentRunStatus>>({});
  const runSeqRef = useRef<Record<string, number>>({});
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

  const hydrateSession = useCallback(async (attachmentId: string) => {
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
  }, []);

  const refreshAfterMutation = useCallback(
    async (attachmentId: string) => {
      hydratedRef.current.delete(attachmentId);
      await hydrateSession(attachmentId);
      await state.reload();
    },
    [hydrateSession, state.reload],
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
      const body = (e as { body?: { resetAt?: string; remedy?: AgentRemedy } } | null)?.body;
      const reset = body?.resetAt ? ` (resets ${new Date(body.resetAt).toLocaleString()})` : "";
      appendTurns(attachmentId, [{
        role: "agent", text: `(error) ${msg}${reset}`, error: true,
        ...(body?.remedy ? { remedy: body.remedy } : {}),
      }]);
    },
    [appendTurns],
  );

  // Streams the reply into a live agent turn (memo dev/22). A failure before
  // any delta with no HTTP status (transport / stream-unsupported / provider
  // stream error) falls back to the blocking run once; HTTP errors (quota 429,
  // 404, …) surface directly as a soft error turn.
  const sendMessage = useCallback(
    async (attachmentId: string, message: string, context?: string | null) => {
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
      // Run status (memo dev/80): `running` from here until the same
      // synchronous block that lands the final turn finalizes it.
      const seq = (runSeqRef.current[attachmentId] = (runSeqRef.current[attachmentId] ?? 0) + 1);
      const startedAt = Date.now();
      setRunStatus((prev) => ({ ...prev, [attachmentId]: { phase: "running", startedAt } }));
      const finalizeStatus = (patch: Omit<AgentRunStatus, "startedAt">) => {
        // A newer run owns this attachment's strip — never clobber it.
        if (runSeqRef.current[attachmentId] !== seq) return;
        setRunStatus((prev) => ({ ...prev, [attachmentId]: { startedAt, ...patch } }));
      };
      const landTurn = (result: {
        reply: string;
        executionId?: string;
        usage?: AgentUsage | null;
        durationMs?: number;
        content?: AgentSessionTurn["content"];
      }) => {
        // The finalized turn keeps the run's execution identity + Actual usage
        // (memo dev/37), its duration (dev/80), and its typed content parts
        // (memo dev/39) so the local transcript matches the persisted one.
        const durationMs = result.durationMs ?? Date.now() - startedAt;
        const execution = result.executionId
          ? { executionId: result.executionId, usage: result.usage ?? null, status: "ok" as const, durationMs }
          : undefined;
        const content = result.content && result.content.length ? result.content : undefined;
        sawProposal = sawProposal || Boolean(content?.some((p) => p.type === "proposal"));
        // Same synchronous block as the turn landing (dev/80): React 18
        // batches both updates into one commit. Status first as
        // defense-in-depth: the safe intermediate is "done beside partial
        // text", never "final text beside running".
        finalizeStatus({ phase: "done", durationMs, usage: result.usage ?? null });
        return { execution, content };
      };
      setToolActivity((prev) => ({ ...prev, [attachmentId]: [] }));
      const onEvent = (name: string, payload: Record<string, unknown>) => {
        // dev/80: interim provider-reported usage sums feed the live token
        // counter — Actuals only (dev/37), never a system line.
        if (name === "usage") {
          const usage = payload.usage as AgentUsage | null | undefined;
          if (!usage || runSeqRef.current[attachmentId] !== seq) return;
          setRunStatus((prev) => {
            const cur = prev[attachmentId];
            if (!cur || cur.phase !== "running") return prev;
            return { ...prev, [attachmentId]: { ...cur, liveUsage: usage } };
          });
          return;
        }
        const line = toolActivityLine(name, payload);
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
          context,
        );
        const { execution, content } = landTurn(result);
        if (!streamed)
          appendTurns(attachmentId, [
            { role: "agent", text: result.reply, ...(execution ? { execution } : {}), ...(content ? { content } : {}) },
          ]);
        else replaceLastAgentTurn(attachmentId, result.reply, execution, content);
        succeeded = true;
      } catch (e) {
        const status = (e as { status?: number } | null)?.status;
        if (!streamed && status === undefined) {
          // Pre-delta stream failure → one blocking-run fallback. Payload
          // parity with the streamed path (dev/53): the turn keeps its
          // execution record AND its content parts.
          try {
            const result = await state.run(attachmentId, message, context);
            const { execution, content } = landTurn(result);
            appendTurns(attachmentId, [
              { role: "agent", text: result.reply, ...(execution ? { execution } : {}), ...(content ? { content } : {}) },
            ]);
            succeeded = true;
          } catch (e2) {
            finalizeStatus({ phase: "error", durationMs: Date.now() - startedAt });
            appendErrorTurn(attachmentId, e2);
          }
        } else {
          // Mid-stream failure keeps the partial text visible; HTTP errors
          // (e.g. the stable quota 429) render directly.
          finalizeStatus({ phase: "error", durationMs: Date.now() - startedAt });
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

  const clearConversation = useCallback(async (attachmentId: string) => {
    const pid = projectRef.current;
    if (!pid) return;
    await agentsApi.clearSession(pid, attachmentId);
    setTranscripts((prev) => ({ ...prev, [attachmentId]: [] }));
    // dev/80: the status strip lives exactly as long as the conversation.
    setRunStatus((prev) => {
      const { [attachmentId]: _drop, ...rest } = prev;
      return rest;
    });
  }, []);

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
      setRunStatus((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
    },
    [state.detach],
  );

  return useMemo(
    () => ({
      selectedId, setSelectedId, openChat, transcripts, hydratingId, hydrateErrors, hydrateSession,
      sendMessage, saveIntent, saveTitle, clearConversation, toolActivity, runStatus, detach,
      projectRef, refreshAfterMutation,
    }),
    [selectedId, openChat, transcripts, hydratingId, hydrateErrors, hydrateSession, sendMessage,
     saveIntent, saveTitle, clearConversation, toolActivity, runStatus, detach, refreshAfterMutation],
  );
}

/** Transient system lines (dev/41 tools; dev/48 delegates; dev/54 plan
 * revisions): live during the run, gone on finalize — the durable record is
 * the execution. dev/72: the delegate event names the delegate. */
function toolActivityLine(name: string, payload: Record<string, unknown>): string | null {
  const tool = typeof payload.tool === "string" ? payload.tool : "";
  const capability = typeof payload.capability === "string" ? payload.capability : "";
  const coord = typeof payload.coord === "string" ? payload.coord : "";
  return name === "tool_requested"
    ? `${tool} …`
    : name === "tool_result"
      ? `${tool} · ${payload.status ?? ""}`
      : name === "delegate_requested"
        ? `delegating ${capability} …`
        : name === "delegate_result"
          ? `${(typeof payload.name === "string" && payload.name) || coord || capability} · ${payload.status ?? ""}`
          : name === "plan_revision"
            ? `revising the plan (attempt ${payload.attempt ?? "?"}) …`
            : null;
}
