/**
 * A chat turn's ask as a tab follows it: the room's event that carries an
 * ask's events (`turn_jobs.EVENT` on the server), what a tab keeps of each
 * ask it follows, and how one event of the ask reads.
 *
 * A turn runs on the server as a job: every tab of the dataflow's owner and
 * editors follows it through the room, the tab that asked among them, and a
 * tab no room holds follows its own asks over HTTP. Each event of an ask
 * carries its place among the ask's events (`seq`), so a tab applies each
 * once and in order, and a tab that missed one reads the chat again.
 */
import type {
  AgentAskView,
  AgentToolCall,
  AgentTurnEnvelope,
  AgentTurnWriter,
  AgentUsage,
} from "../../services/agents/types";

/** The room's event that carries an ask's events to the tabs that edit the
 * dataflow, each in an `AgentTurnEnvelope`. */
export const AGENT_TURN_EVENT = "agent_turn";

/** An ask a tab follows, as far as the tab has seen it. */
export interface LiveAsk {
  askId: string;
  attachmentId: string;
  by: AgentTurnWriter | null;
  message: string;
  /** `asking`: this tab asked it and the server has said nothing of it yet. */
  state: "asking" | "waiting" | "running";
  /** The place of the last event of it this tab applied; -1 before any. */
  seq: number;
  /** When its turn started (epoch ms), or when this tab asked it. */
  startedAt: number;
  /** Its reply's text so far. */
  streamed: string;
  /** Its turn's tool calls, as their results said them. */
  toolCalls: AgentToolCall[];
  /** It proposed an install or landed a change: the listing moved with it. */
  sawProposal: boolean;
  /** Its message is the transcript's: its turn runs, or this tab placed it
   * there when it asked of an agent that had nothing to do. */
  inTranscript: boolean;
}

/** An ask waiting its turn, as the chat lists it after the transcript. */
export interface WaitingAsk {
  askId: string;
  by: AgentTurnWriter | null;
  message: string;
  /** `sending`: this tab asked it a moment ago; `asked`: the server has it
   * and its turn starts now; `waiting`: an earlier turn runs first. */
  status: "sending" | "asked" | "waiting";
}

/** A new ask's id: 32 hexadecimal characters, as the server takes them. */
export function newAskId(): string {
  const bytes = new Uint8Array(16);
  const crypto = (globalThis as { crypto?: Crypto }).crypto;
  if (crypto?.getRandomValues) crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Whether *payload*, a room event's, is an ask's envelope. */
export function isTurnEnvelope(payload: unknown): payload is AgentTurnEnvelope {
  const env = payload as Partial<AgentTurnEnvelope> | null;
  return (
    Boolean(env) &&
    typeof env?.projectId === "string" &&
    typeof env?.attachmentId === "string" &&
    typeof env?.askId === "string" &&
    typeof env?.seq === "number" &&
    typeof env?.event === "string"
  );
}

/** The ask a tab follows from *view*, an ask as the server has it now. */
export function liveAskOf(attachmentId: string, view: AgentAskView): LiveAsk {
  return {
    askId: view.askId,
    attachmentId,
    by: view.by ?? null,
    message: view.message,
    state: view.state === "running" ? "running" : "waiting",
    seq: view.seq,
    startedAt: view.startedAt ? view.startedAt * 1000 : Date.now(),
    streamed: view.text ?? "",
    toolCalls: [],
    sawProposal: false,
    inTranscript: view.state === "running",
  };
}

/** One tool_result event as the turn's record keeps it (dev/41): a granted
 * call that did not succeed carries its reason, and an egress refusal says so
 * (#447). */
export function toolCallOf(payload: Record<string, unknown>): AgentToolCall {
  return {
    tool: typeof payload.tool === "string" ? payload.tool : "",
    status: typeof payload.status === "string" ? payload.status : "",
    ...(typeof payload.reason === "string" && payload.reason ? { reason: payload.reason } : {}),
    ...(payload.egress === true ? { egress: true } : {}),
  };
}

/** Transient system lines (dev/41 tools; dev/48 delegates; dev/54 plan
 * revisions): live during the run, gone on finalize; the durable record is
 * the execution. dev/72: the delegate event names the delegate. A tool that
 * did not succeed shows its reason, the line the reply keeps (#447). */
export function toolActivityLine(name: string, payload: Record<string, unknown>): string | null {
  const tool = typeof payload.tool === "string" ? payload.tool : "";
  const capability = typeof payload.capability === "string" ? payload.capability : "";
  const coord = typeof payload.coord === "string" ? payload.coord : "";
  const reason = typeof payload.reason === "string" && payload.reason ? payload.reason : null;
  return name === "tool_requested"
    ? `${tool} …`
    : name === "tool_result"
      ? `${tool} · ${reason ?? payload.status ?? ""}`
      : name === "delegate_requested"
        ? `delegating ${capability} …`
        : name === "delegate_result"
          ? `${(typeof payload.name === "string" && payload.name) || coord || capability} · ${payload.status ?? ""}`
          : name === "plan_revision"
            ? `revising the plan (attempt ${payload.attempt ?? "?"}) …`
            : null;
}

/** The usage an event carries, when it is a `usage` event's. */
export function usageOf(payload: Record<string, unknown>): AgentUsage | null {
  const usage = payload.usage as AgentUsage | null | undefined;
  return usage ?? null;
}
