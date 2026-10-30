/**
 * The chat side of an attachment (memo dev/142, F2 — extracted from
 * `AgentAttachmentsProvider`): which chat is open, the per-attachment
 * transcript cache (a read-through cache over the server-persisted session,
 * memo dev/20), the asks and their turns with their run status (dev/22,
 * dev/80), and the intent/title/clear edits. It also owns the project ref and
 * the "refresh after a mutation" sequence the other agent hooks share.
 *
 * A turn runs on the server as a job (`turn_jobs.py`): it goes on when the tab
 * that asked closes, and one turn runs at a time per attachment, a second ask
 * waiting its turn. Every tab of the dataflow's owner and editors follows each
 * ask through the room (`agent_turn`), the tab that asked among them: its
 * message, then its reply as the model writes it, its tool lines, the changes
 * it lands and its end. A tab no room holds (a hosted guest's) asks and follows
 * the answer itself, and follows the ask by its id when that answer breaks. A
 * chat opened while a turn runs or asks wait reads them as they stand, then
 * the events after them (`seq`).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { AgentRemedy } from "../../services/agents";
import { agentsApi, bridgeLandedChangeEvent, type AgentAttachmentsState } from "../../services/agents";
import type {
  AgentAskView,
  AgentRunSkillPins,
  AgentSessionTurn,
  AgentTurnEnvelope,
  AgentTurnWriter,
  AgentUsage,
} from "../../services/agents/types";
import type { AgentRunStatus } from "../../services/agents/agentRunStatus";
import { useCollab } from "../CollaborationProvider";
import {
  AGENT_TURN_EVENT,
  isTurnEnvelope,
  liveAskOf,
  newAskId,
  toolActivityLine,
  toolCallOf,
  usageOf,
  type LiveAsk,
  type WaitingAsk,
} from "./turnAsks";

export type { WaitingAsk } from "./turnAsks";

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
  /** The asks waiting their turn, per attachment, in order. */
  waitingAsks: Record<string, WaitingAsk[]>;
  /** Stop the running turn of an attachment: whoever asked it, the owner or
   * an editor may. */
  stopTurn: (attachmentId: string) => Promise<void>;
  /** Withdraw an ask still waiting its turn: whoever asked it may. */
  withdrawAsk: (attachmentId: string, askId: string) => Promise<void>;
  detach: (attachmentId: string) => Promise<void>;
  /** The current project id, readable inside async callbacks. */
  projectRef: React.MutableRefObject<string | null>;
  /** After a mutation the transcript and the listing are the truth: drop the
   * once-guard, refetch the session, reload the listing. */
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}

/** A `done` event's payload, as a turn's end says it. */
interface TurnEnd {
  reply?: string;
  executionId?: string;
  usage?: AgentUsage | null;
  durationMs?: number;
  content?: AgentSessionTurn["content"];
  skills?: AgentRunSkillPins;
  skillsLoaded?: string[];
  stopped?: { by: AgentTurnWriter | null };
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
  // dev/80: per-attachment run status for the chat status strip, from the
  // attachment's running turn.
  const [runStatus, setRunStatus] = useState<Record<string, AgentRunStatus>>({});
  const [waitingAsks, setWaitingAsks] = useState<Record<string, WaitingAsk[]>>({});
  const hydratedRef = useRef<Set<string>>(new Set());
  const projectRef = useRef<string | null>(effectiveProjectId);
  // The asks this tab follows, per attachment and id: how far it has seen each.
  const asksRef = useRef<Record<string, Record<string, LiveAsk>>>({});
  // The room's events of a chat being read, applied once its read is in.
  const bufferRef = useRef<Record<string, AgentTurnEnvelope[]>>({});
  // A chat to read once more after the read in flight.
  const rereadRef = useRef<Set<string>>(new Set());
  const attachmentsRef = useRef(state.attachments);
  attachmentsRef.current = state.attachments;
  const reloadRef = useRef(state.reload);
  reloadRef.current = state.reload;

  const collab = useCollab();
  // A tab the dataflow's room holds follows every ask through it; any other
  // follows its own asks over HTTP. Once the room held it, it stays the
  // room's while it reconnects: a join reads its chats again.
  const roomedForRef = useRef<string | null>(null);
  if (collab.role !== null && effectiveProjectId) roomedForRef.current = effectiveProjectId;
  const inRoomRef = useRef(false);
  inRoomRef.current =
    collab.role !== null || (effectiveProjectId !== null && roomedForRef.current === effectiveProjectId);

  // Project switch: sessions are project-private — drop the chat state.
  useEffect(() => {
    projectRef.current = effectiveProjectId;
    setSelectedId(null);
    setTranscripts({});
    setHydrateErrors({});
    setWaitingAsks({});
    hydratedRef.current = new Set();
    asksRef.current = {};
    bufferRef.current = {};
  }, [effectiveProjectId]);

  const appendTurns = useCallback((attachmentId: string, turns: AgentSessionTurn[]) => {
    setTranscripts((prev) => ({
      ...prev,
      [attachmentId]: [...(prev[attachmentId] ?? []), ...turns],
    }));
  }, []);

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

  const setWaiting = useCallback((attachmentId: string, entry: WaitingAsk) => {
    setWaitingAsks((prev) => {
      const list = prev[attachmentId] ?? [];
      const at = list.findIndex((w) => w.askId === entry.askId);
      const next = at === -1 ? [...list, entry] : list.map((w, i) => (i === at ? entry : w));
      return { ...prev, [attachmentId]: next };
    });
  }, []);

  const dropWaiting = useCallback((attachmentId: string, askId: string) => {
    setWaitingAsks((prev) => {
      const list = prev[attachmentId];
      if (!list?.some((w) => w.askId === askId)) return prev;
      return { ...prev, [attachmentId]: list.filter((w) => w.askId !== askId) };
    });
  }, []);

  /** The ask's message, as the transcript shows it. */
  const userTurnOf = (ask: LiveAsk): AgentSessionTurn => ({
    role: "user", text: ask.message, ...(ask.by ? { by: ask.by } : {}),
  });

  /** The ask's turn starts: its message joins the transcript, the strip runs. */
  const startAsk = useCallback(
    (ask: LiveAsk, startedAt: number) => {
      const attachmentId = ask.attachmentId;
      ask.state = "running";
      ask.startedAt = startedAt;
      dropWaiting(attachmentId, ask.askId);
      if (!ask.inTranscript) {
        appendTurns(attachmentId, [userTurnOf(ask)]);
        ask.inTranscript = true;
      }
      setRunStatus((prev) => ({ ...prev, [attachmentId]: { phase: "running", startedAt } }));
      setToolActivity((prev) => ({ ...prev, [attachmentId]: [] }));
    },
    [appendTurns, dropWaiting],
  );

  // Read through a ref, so the handlers below stay stable.
  const rereadLater = useRef<(attachmentId: string) => void>(() => undefined);

  /** The ask is over: no longer followed. A turn's live tool lines go with
   * it (*ran*): they are transient, and the durable record is
   * execution.toolCalls (dev/41). */
  const forgetAsk = useCallback(
    (ask: LiveAsk, ran: boolean = ask.state === "running") => {
      const asks = asksRef.current[ask.attachmentId] ?? {};
      if (asks[ask.askId] === ask) delete asks[ask.askId];
      dropWaiting(ask.attachmentId, ask.askId);
      if (ran) setToolActivity((prev) => ({ ...prev, [ask.attachmentId]: [] }));
    },
    [dropWaiting],
  );

  /** The ask failed: its partial reply stays, an error turn follows it. */
  const failAsk = useCallback(
    (ask: LiveAsk, e: unknown) => {
      const attachmentId = ask.attachmentId;
      const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "run failed";
      const body = (e as { body?: { resetAt?: string; remedy?: AgentRemedy } } | null)?.body;
      const reset = body?.resetAt ? ` (resets ${new Date(body.resetAt).toLocaleString()})` : "";
      const turns: AgentSessionTurn[] = ask.inTranscript ? [] : [userTurnOf(ask)];
      ask.inTranscript = true;
      turns.push({
        role: "agent", text: `(error) ${msg}${reset}`, error: true,
        ...(body?.remedy ? { remedy: body.remedy } : {}),
      });
      const startedAt = ask.startedAt;
      setRunStatus((prev) => ({
        ...prev, [attachmentId]: { phase: "error", startedAt, durationMs: Date.now() - startedAt },
      }));
      appendTurns(attachmentId, turns);
      forgetAsk(ask, true);
    },
    [appendTurns, forgetAsk],
  );

  /** The ask's turn ended (`done`): its reply lands with its execution record
   * (memo dev/37), its duration (dev/80), its tool calls (#447), the skills
   * it held and loaded, its content parts (memo dev/39) and who stopped it,
   * so the transcript matches the persisted one. */
  const endAsk = useCallback(
    (ask: LiveAsk, end: TurnEnd) => {
      const attachmentId = ask.attachmentId;
      const durationMs = end.durationMs ?? Date.now() - ask.startedAt;
      const execution = end.executionId
        ? {
            executionId: end.executionId,
            usage: end.usage ?? null,
            status: end.stopped ? ("stopped" as const) : ("ok" as const),
            durationMs,
            ...(ask.toolCalls.length ? { toolCalls: [...ask.toolCalls] } : {}),
            ...(end.skills ? { pins: { skills: end.skills } } : {}),
            ...(end.skillsLoaded?.length ? { skillsLoaded: [...end.skillsLoaded] } : {}),
            ...(end.stopped ? { stoppedBy: end.stopped.by ?? null } : {}),
          }
        : undefined;
      const content = end.content && end.content.length ? end.content : undefined;
      const sawProposal =
        ask.sawProposal || Boolean(content?.some((p) => p.type === "proposal" || p.type === "change"));
      if (!ask.inTranscript) {
        appendTurns(attachmentId, [userTurnOf(ask)]);
        ask.inTranscript = true;
      }
      // Same synchronous block as the turn landing (dev/80): React 18
      // batches both updates into one commit. Status first as
      // defense-in-depth: the safe intermediate is "done beside partial
      // text", never "final text beside running".
      setRunStatus((prev) => ({
        ...prev,
        [attachmentId]: { phase: "done", startedAt: ask.startedAt, durationMs, usage: end.usage ?? null },
      }));
      const reply = end.reply ?? ask.streamed;
      if (!ask.streamed)
        appendTurns(attachmentId, [
          { role: "agent", text: reply, ...(execution ? { execution } : {}), ...(content ? { content } : {}) },
        ]);
      else replaceLastAgentTurn(attachmentId, reply, execution, content);
      forgetAsk(ask, true);
      // The first exchange may title the conversation (memo dev/25), and a
      // proposal or a change moves the listing's mirrors: every tab that
      // followed the turn reads the listing again.
      const untitled = !attachmentsRef.current.find((a) => a.attachmentId === attachmentId)?.title;
      if (sawProposal || untitled) void reloadRef.current();
    },
    [appendTurns, replaceLastAgentTurn, forgetAsk],
  );

  /** What one event of an ask does to the chat. *quiet*: an event read with
   * the ask as it stood, which happened before this tab saw it, so a change
   * does not play on its canvas again. */
  const applyEvent = useCallback(
    (ask: LiveAsk, name: string, data: Record<string, unknown>, quiet = false) => {
      const attachmentId = ask.attachmentId;
      if (name === "asked") {
        if (ask.inTranscript) {
          // This tab placed its own message at the transcript's end, but an
          // earlier turn runs first: the chat as it stands says where.
          if (data.waiting) {
            ask.state = "waiting";
            ask.inTranscript = false;
            rereadLater.current(attachmentId);
          }
          return;
        }
        if (ask.state === "running") return;
        ask.state = "waiting";
        setWaiting(attachmentId, {
          askId: ask.askId, by: ask.by, message: ask.message, status: data.waiting ? "waiting" : "asked",
        });
        return;
      }
      if (name === "started") {
        startAsk(ask, typeof data.startedAt === "number" ? data.startedAt * 1000 : Date.now());
        return;
      }
      if (name === "withdrawn") {
        forgetAsk(ask);
        return;
      }
      if (ask.state !== "running") startAsk(ask, Date.now());
      if (name === "delta") {
        const text = typeof data.text === "string" ? data.text : "";
        if (!text) return;
        if (!ask.streamed) appendTurns(attachmentId, [{ role: "agent", text }]);
        else replaceLastAgentTurn(attachmentId, ask.streamed + text);
        ask.streamed += text;
        return;
      }
      if (name === "usage") {
        // dev/80: interim provider-reported usage sums feed the live token
        // counter, Actuals only (dev/37), never a system line.
        const usage = usageOf(data);
        if (!usage) return;
        setRunStatus((prev) => {
          const cur = prev[attachmentId];
          if (!cur || cur.phase !== "running") return prev;
          return { ...prev, [attachmentId]: { ...cur, liveUsage: usage } };
        });
        return;
      }
      if (name === "done") {
        endAsk(ask, data as TurnEnd);
        return;
      }
      if (name === "error") {
        failAsk(ask, typeof data.error === "string" ? data.error : "agent run failed");
        return;
      }
      if (name === "execution") {
        if (typeof data.executionId === "string") ask.executionId = data.executionId;
        return;
      }
      // A change the agent made landed on the server: a canvas no doc binds
      // takes it now, before the reply ends.
      if (name === "change") {
        if (!quiet) bridgeLandedChangeEvent("change", data);
        ask.sawProposal = true;
        return;
      }
      if (name === "tool_result") ask.toolCalls.push(toolCallOf(data));
      if (name === "review_required") ask.sawProposal = true;
      const line = toolActivityLine(name, data);
      if (line)
        setToolActivity((prev) => ({
          ...prev,
          [attachmentId]: [...(prev[attachmentId] ?? []), line],
        }));
    },
    [appendTurns, replaceLastAgentTurn, setWaiting, startAsk, forgetAsk, endAsk, failAsk],
  );

  /** One of an ask's events through the room: applied once, in order. An
   * ask this tab follows is its own or one of a chat it read; a chat it has
   * not read shows nothing of others' asks, though their end may move the
   * listing. An ask this tab follows by its own stream takes none of the
   * room's. An event that skips one, or one of an ask this tab never saw
   * asked, reads the chat again. */
  const applyEnvelope = useCallback(
    (env: AgentTurnEnvelope) => {
      const attachmentId = env.attachmentId;
      const buffered = bufferRef.current[attachmentId];
      if (buffered) {
        buffered.push(env);
        return;
      }
      const asks = (asksRef.current[attachmentId] ??= {});
      let ask = asks[env.askId];
      if (ask?.via === "stream") return;
      if (!ask && !hydratedRef.current.has(attachmentId)) {
        if (env.event === "done") {
          const content = (env.data as TurnEnd).content ?? [];
          const untitled = !attachmentsRef.current.find((a) => a.attachmentId === attachmentId)?.title;
          if (untitled || content.some((p) => p.type === "proposal" || p.type === "change")) void reloadRef.current();
        }
        return;
      }
      if (!ask) {
        if (env.event === "withdrawn") return;
        if (env.event !== "asked" || env.seq !== 0) {
          rereadLater.current(attachmentId);
          return;
        }
        const data = env.data as { by?: AgentTurnWriter | null; message?: string };
        ask = asks[env.askId] = {
          askId: env.askId, attachmentId, by: data.by ?? null, message: String(data.message ?? ""),
          state: "waiting", seq: -1, startedAt: Date.now(), streamed: "", toolCalls: [],
          sawProposal: false, inTranscript: false, via: "room",
        };
      }
      if (env.seq <= ask.seq) return;
      if (env.seq !== ask.seq + 1) {
        rereadLater.current(attachmentId);
        return;
      }
      ask.seq = env.seq;
      applyEvent(ask, env.event, env.data ?? {});
    },
    [applyEvent],
  );

  /** The chat as it stands on the server: its transcript, then its running
   * turn's message and reply so far, and the asks waiting their turn. An ask
   * this tab follows by its own stream stays as that stream brought it, after
   * them, until its turn is in the transcript. */
  const restore = useCallback((attachmentId: string, turns: AgentSessionTurn[], views: AgentAskView[]) => {
    const settled = new Set(turns.map((turn) => turn.execution?.executionId));
    const own = Object.values(asksRef.current[attachmentId] ?? {}).filter(
      (ask) => ask.via === "stream" && !(ask.executionId && settled.has(ask.executionId)),
    );
    const asks: Record<string, LiveAsk> = {};
    const restored = [...turns];
    const waiting: WaitingAsk[] = [];
    let running: { ask: LiveAsk; liveUsage: AgentUsage | null } | null = null;
    let lines: string[] = [];
    for (const view of views) {
      if (own.some((ask) => ask.askId === view.askId)) continue;
      const ask = liveAskOf(attachmentId, view);
      asks[ask.askId] = ask;
      if (ask.state !== "running") {
        waiting.push({ askId: ask.askId, by: ask.by, message: ask.message, status: "waiting" });
        continue;
      }
      let liveUsage: AgentUsage | null = null;
      restored.push(userTurnOf(ask));
      if (ask.streamed) restored.push({ role: "agent", text: ask.streamed });
      for (const event of view.events ?? []) {
        const data = event.data ?? {};
        if (event.event === "tool_result") ask.toolCalls.push(toolCallOf(data));
        if (event.event === "review_required" || event.event === "change") ask.sawProposal = true;
        if (event.event === "usage") liveUsage = usageOf(data);
        const line = toolActivityLine(event.event, data);
        if (line) lines = [...lines, line];
      }
      running = { ask, liveUsage };
    }
    let ownRuns = false;
    for (const ask of own) {
      asks[ask.askId] = ask;
      if (!ask.inTranscript) {
        waiting.push({
          askId: ask.askId, by: ask.by, message: ask.message, status: ask.state === "asking" ? "sending" : "waiting",
        });
        continue;
      }
      restored.push(userTurnOf(ask));
      if (ask.streamed) restored.push({ role: "agent", text: ask.streamed });
      if (ask.state === "running") ownRuns = true;
    }
    asksRef.current[attachmentId] = asks;
    setTranscripts((prev) => ({ ...prev, [attachmentId]: restored }));
    setWaitingAsks((prev) => ({ ...prev, [attachmentId]: waiting }));
    // The tool lines and the strip of a turn this tab streams stay its own.
    if (!ownRuns) setToolActivity((prev) => ({ ...prev, [attachmentId]: lines }));
    if (running) {
      const { ask, liveUsage } = running;
      setRunStatus((prev) => ({
        ...prev,
        [attachmentId]: { phase: "running", startedAt: ask.startedAt, ...(liveUsage ? { liveUsage } : {}) },
      }));
    } else if (!ownRuns) {
      setRunStatus((prev) => {
        if (prev[attachmentId]?.phase !== "running") return prev;
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
    }
  }, []);

  const hydrateSession = useCallback(
    async (attachmentId: string) => {
      const pid = projectRef.current;
      if (!pid || hydratedRef.current.has(attachmentId)) return;
      if (bufferRef.current[attachmentId]) {
        rereadRef.current.add(attachmentId);
        return;
      }
      bufferRef.current[attachmentId] = [];
      setHydratingId(attachmentId);
      setHydrateErrors((prev) => {
        if (!(attachmentId in prev)) return prev;
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
      let read = false;
      try {
        const session = await agentsApi.getSession(pid, attachmentId);
        if (projectRef.current !== pid) return; // stale: project switched mid-fetch
        restore(attachmentId, session.turns, session.asks ?? []);
        hydratedRef.current.add(attachmentId);
        read = true;
      } catch (e) {
        if (projectRef.current !== pid) return;
        setHydrateErrors((prev) => ({
          ...prev,
          [attachmentId]: e instanceof Error ? e.message : "Failed to load the conversation",
        }));
      } finally {
        setHydratingId((cur) => (cur === attachmentId ? null : cur));
        const buffered = bufferRef.current[attachmentId] ?? [];
        delete bufferRef.current[attachmentId];
        // The events that came while the chat was read: those after it apply.
        if (read) for (const env of buffered) applyEnvelope(env);
        if (rereadRef.current.delete(attachmentId) && projectRef.current === pid) {
          hydratedRef.current.delete(attachmentId);
          void hydrateSession(attachmentId);
        }
      }
    },
    [restore, applyEnvelope],
  );

  /** Read a chat again from the server: an event of it went missing. */
  const reread = useCallback(
    (attachmentId: string) => {
      if (bufferRef.current[attachmentId]) {
        rereadRef.current.add(attachmentId);
        return;
      }
      hydratedRef.current.delete(attachmentId);
      void hydrateSession(attachmentId);
    },
    [hydrateSession],
  );
  rereadLater.current = reread;

  // Every ask's events, through the dataflow's room.
  const { onRemote, participantId } = collab;
  useEffect(
    () =>
      onRemote(AGENT_TURN_EVENT, (payload) => {
        if (isTurnEnvelope(payload) && payload.projectId === projectRef.current) applyEnvelope(payload);
      }),
    [onRemote, applyEnvelope],
  );
  // A tab that joins the room again may have missed events while it was
  // away: it reads its chats again.
  // A tab away from the room has no id there: the join is the next id that
  // differs from the last one it had.
  const joinedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!participantId) return;
    const before = joinedRef.current;
    joinedRef.current = participantId;
    if (!before || before === participantId) return;
    for (const attachmentId of Array.from(hydratedRef.current)) reread(attachmentId);
  }, [participantId, reread]);

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

  /** A tab no room holds follows its own ask by its id once the answer that
   * streamed it broke before its reply began: the turn went on on the server,
   * and is never asked again. The ask as it stands comes first. */
  const followAsk = useCallback(
    async (pid: string, ask: LiveAsk, cause: unknown) => {
      const live = () => Boolean(asksRef.current[ask.attachmentId]?.[ask.askId]);
      try {
        await agentsApi.followTurn(pid, ask.attachmentId, ask.askId, (env) => {
          if (!live()) return;
          if (env.event === "snapshot") {
            const view = env.data as unknown as AgentAskView;
            ask.toolCalls = [];
            setToolActivity((prev) => ({ ...prev, [ask.attachmentId]: [] }));
            if (view.state !== "waiting" && ask.state !== "running")
              startAsk(ask, view.startedAt ? view.startedAt * 1000 : Date.now());
            if (view.text && !ask.streamed) applyEvent(ask, "delta", { text: view.text }, true);
            for (const event of view.events ?? []) if (live()) applyEvent(ask, event.event, event.data ?? {}, true);
            ask.seq = env.seq;
            return;
          }
          if (env.seq <= ask.seq) return;
          ask.seq = env.seq;
          applyEvent(ask, env.event, env.data ?? {});
        });
      } catch {
        // Followed no further: the ask's own failure says what happened.
      }
      if (live()) failAsk(ask, cause);
    },
    [applyEvent, startAsk, failAsk],
  );

  /** Ask a message of an attachment's agent. The ask shows at once: its
   * message ends the transcript when the agent has nothing to do here, else
   * it waits its turn after the transcript. Its turn then runs on the
   * server. */
  const sendMessage = useCallback(
    async (attachmentId: string, message: string, context?: string | null) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      const asks = (asksRef.current[attachmentId] ??= {});
      const busy = Object.keys(asks).length > 0;
      const ask: LiveAsk = {
        askId: newAskId(), attachmentId, by: null, message, state: "asking", seq: -1,
        startedAt: Date.now(), streamed: "", toolCalls: [], sawProposal: false, inTranscript: false,
        via: inRoomRef.current ? "room" : "stream",
      };
      asks[ask.askId] = ask;
      if (busy) {
        // The room says whether the server holds it back; its own stream says
        // nothing until its turn starts, and an earlier ask is ahead of it.
        if (ask.via === "stream") ask.state = "waiting";
        setWaiting(attachmentId, {
          askId: ask.askId, by: null, message, status: ask.via === "stream" ? "waiting" : "sending",
        });
      } else startAsk(ask, Date.now());
      const live = () => Boolean(asksRef.current[attachmentId]?.[ask.askId]);
      if (inRoomRef.current) {
        // The room brings every event of it, this tab's own ask's too.
        for (let attempt = 0; ; attempt++) {
          try {
            await agentsApi.askTurn(pid, attachmentId, ask.askId, message, context);
            return;
          } catch (e) {
            // An answer that never came may still have asked: asked again by
            // its id, it is the same ask.
            if ((e as { status?: number } | null)?.status !== undefined || attempt > 0) {
              if (live()) failAsk(ask, e);
              return;
            }
          }
        }
      }
      // No room: this tab follows the answer of its own ask.
      const next = (event: string, data: Record<string, unknown>) => {
        if (!live()) return;
        ask.seq += 1;
        applyEvent(ask, event, data);
      };
      try {
        const result = await agentsApi.runAttachmentStream(
          pid,
          attachmentId,
          message,
          (delta) => next("delta", { text: delta }),
          (name, payload) => next(name, payload),
          context,
          ask.askId,
        );
        next("done", result as unknown as Record<string, unknown>);
      } catch (e) {
        if (!live()) return;
        if ((e as { status?: number } | null)?.status === undefined && !ask.streamed) {
          // The answer broke before the reply began: the turn goes on on the
          // server, so this tab follows it there.
          await followAsk(pid, ask, e);
          return;
        }
        // Mid-stream failure keeps the partial text visible; HTTP errors
        // render directly.
        failAsk(ask, e);
      }
    },
    [setWaiting, startAsk, failAsk, applyEvent, followAsk],
  );

  const stopTurn = useCallback(async (attachmentId: string) => {
    const pid = projectRef.current;
    const running = Object.values(asksRef.current[attachmentId] ?? {}).find((a) => a.state === "running");
    if (!pid || !running) return;
    await agentsApi.stopTurn(pid, attachmentId, running.askId);
  }, []);

  const withdrawAsk = useCallback(
    async (attachmentId: string, askId: string) => {
      const pid = projectRef.current;
      if (!pid) return;
      await agentsApi.withdrawTurn(pid, attachmentId, askId);
      // A tab no room holds hears no withdrawn: it forgets the ask itself.
      const ask = asksRef.current[attachmentId]?.[askId];
      if (ask) forgetAsk(ask);
    },
    [forgetAsk],
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
      delete asksRef.current[attachmentId];
      setTranscripts((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
      setRunStatus((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
      setWaitingAsks((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
    },
    [state.detach],
  );

  return useMemo(
    () => ({
      selectedId, setSelectedId, openChat, transcripts, hydratingId, hydrateErrors, hydrateSession,
      sendMessage, saveIntent, saveTitle, clearConversation, toolActivity, runStatus, waitingAsks,
      stopTurn, withdrawAsk, detach, projectRef, refreshAfterMutation,
    }),
    [selectedId, openChat, transcripts, hydratingId, hydrateErrors, hydrateSession, sendMessage,
     saveIntent, saveTitle, clearConversation, toolActivity, runStatus, waitingAsks, stopTurn,
     withdrawAsk, detach, refreshAfterMutation],
  );
}
