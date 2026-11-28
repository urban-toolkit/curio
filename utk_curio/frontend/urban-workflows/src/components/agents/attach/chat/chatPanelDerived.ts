/**
 * Pure derivations the chat panel renders from (memo dev/142, F4 — split out
 * of `AgentChatPanel.tsx`): the turns a chat draws, the per-turn status meta,
 * the failed tool calls a reply keeps lines for and how they read, whether a
 * canvas agent's reply changed nothing, the plan-row state a landed plan's
 * card gets from the attachment, the header's target label, and the newest
 * turn's suggested prompts.
 */
import {
  declaresCapability,
  NODE_BUILD_CAPABILITY,
  ORCHESTRATE_CAPABILITY,
  turnStatusDisplay,
  type AgentAttachment,
  type AgentChangePart,
  type AgentDelegationPart,
  type AgentSessionTurn,
  type AgentToolCall,
  type AgentSuggestedPromptsPart,
  type AgentRunStatus,
  type RunStatusDisplay,
} from "../../../../services/agents";
import { isBuiltNode } from "../../../../services/agents/planBuild";
import type { PlanNodeReviewState } from "../../content/AgentReviewCard";

/** Whether the chat draws *turn*: a turn the runtime keeps for the agents
 * alone (`forAgents`), such as a pick's Source recorded turn, whose words the
 * card says, is read by the agents and never drawn. */
export function shownInChat(turn: AgentSessionTurn): boolean {
  return turn.forAgents !== true;
}

/** Whether *text* is a candidates block, as the runtime recognizes one
 * (`delegates._extract_candidates_reply`): a JSON object whose
 * `datasetCandidates.lanes` is an object. */
function isCandidatesBlock(text: string): boolean {
  try {
    const payload = JSON.parse(text) as { datasetCandidates?: { lanes?: unknown } } | null;
    const lanes = payload && typeof payload === "object" ? payload.datasetCandidates?.lanes : undefined;
    return Boolean(lanes && typeof lanes === "object" && !Array.isArray(lanes));
  } catch {
    return false;
  }
}

/** A fenced block of any language tag, as the runtime reads one. */
const FENCED = /```[A-Za-z0-9_.-]*[ \t]*\n([\s\S]*?)\n?```/g;

/** The start of a candidates object, whose first key is `datasetCandidates`. */
const OPENS_CANDIDATES = /^\{\s*"datasetCandidates"\s*:/;

/** Whether *text* is a candidates object the reply's cut ended in: it opens
 * one, and does not parse. The chat keeps a delegated reply's first 2,000
 * characters (`delegates._run_delegate_traced`). */
function isCutCandidatesBlock(text: string): boolean {
  if (!OPENS_CANDIDATES.test(text)) return false;
  try {
    JSON.parse(text);
    return false;
  } catch {
    return true;
  }
}

/** A reply's words as the chat draws them: the candidates a Dataset Finder
 * printed, bare or in a fence, whole or cut where the chat cut the reply,
 * are not drawn, since the card of those candidates shows them (board S08);
 * the agents read the reply whole. Any other text is drawn as it is. */
export function shownReplyText(text: string): string {
  const whole = text.trim();
  if (isCandidatesBlock(whole) || isCutCandidatesBlock(whole)) return "";
  let removed = false;
  let kept = text.replace(FENCED, (block: string, body: string) => {
    if (!isCandidatesBlock(body.trim())) return block;
    removed = true;
    return "";
  });
  // A fence the cut left open, around the candidates: the reply's last
  // fence, when it holds an odd number of them.
  const at = kept.lastIndexOf("```");
  if (at >= 0 && (kept.match(/```/g) ?? []).length % 2 === 1) {
    const head = /^```[A-Za-z0-9_.-]*[ \t]*\n/.exec(kept.slice(at));
    if (head && isCutCandidatesBlock(kept.slice(at + head[0].length).trim())) {
      kept = kept.slice(0, at);
      removed = true;
    }
  }
  return removed ? kept.trim() : text;
}

/** Whether an agent turn draws nothing in the chat: its words were only the
 * candidates its card shows (`shownReplyText`), it carries no part the chat
 * draws (a card of its run's trace is drawn only with *runDetails*), and
 * nothing stays under it. Such a turn takes no place in the chat. */
export function drawsNothing(
  turn: AgentSessionTurn,
  shownText: string,
  runDetails: boolean,
  under: { failedCalls: number; meta: boolean; canvasUnchanged: boolean },
): boolean {
  if (turn.error || !turn.text.trim() || shownText) return false;
  if (under.failedCalls > 0 || under.meta || under.canvasUnchanged || runDetails) return false;
  return (turn.content ?? []).every((part) => part.type === "card" && (part as { runDetails?: boolean }).runDetails === true);
}

/** The one quiet line a task another agent asked of this one reads as:
 * "Asked by the Dataflow Builder: find a source for CPL branches." Null for
 * any other turn. */
export function askedLine(turn: AgentSessionTurn): string | null {
  const asked = turn.role === "user" ? turn.asked : undefined;
  if (!asked?.by || !asked.task) return null;
  const task = asked.task.trim().replace(/\.$/, "");
  return `Asked by the ${asked.by}: ${task}.`;
}

/** How a failed tool call reads under its reply, without its tool's id, which
 * Show run details adds: what the call did, in plain words, then its reason. */
export function failedCallWords(call: AgentToolCall): string {
  const what = CALL_WORDS[call.tool] ?? "A step";
  const reason = (call.reason ?? "").trim();
  return /^refused\b/i.test(reason) ? `${what} was ${reason}` : `${what} failed: ${reason}`;
}

/** The tools whose failed calls a reply names in plain words; any other is "A
 * step". */
const CALL_WORDS: Record<string, string> = {
  "web.fetch": "A page read",
  "web.search": "A web search",
  "node.create": "Adding a node",
  "node.content.write": "Writing a node's code",
  "node.settings.write": "Changing a node's settings",
  "dataflow.plan.write": "Landing the plan",
};

/** The tools a reply's run called, each once, in the order it first called
 * them: Show run details lists them. */
export function toolsCalledBy(turn: AgentSessionTurn): string[] {
  const tools = (turn.execution?.toolCalls ?? []).map((call) => call.tool).filter(Boolean);
  return tools.filter((tool, i) => tools.indexOf(tool) === i);
}

/** The meta line under one agent turn: the streaming reply shows the live
 * running indicator; finalized replies show their persisted execution
 * record; the newest reply to a message falls back to the live run record
 * when an old server sent no execution fields, so a final message never
 * renders bare. A turn the runtime wrote after the reply (a source's
 * candidates, a Recorded line) answers no message: it shows none. */
export function turnMetaFor(
  t: AgentSessionTurn,
  i: number,
  ctx: {
    turns: AgentSessionTurn[];
    runStatus: AgentRunStatus | null | undefined;
    runInFlight: boolean;
  },
): RunStatusDisplay | null {
  const { turns, runStatus, runInFlight } = ctx;
  const isLast = i === turns.length - 1;
  if (runInFlight && isLast && t.role === "agent" && !t.error && runStatus)
    return { kind: "running", startedAt: runStatus.startedAt };
  const derived = turnStatusDisplay(t);
  if (derived) {
    // The just-failed reply's elapsed-at-failure lives on the run record
    // (client error turns carry no execution).
    if (derived.kind === "error" && derived.durationMs == null && isLast && runStatus?.phase === "error")
      return { ...derived, durationMs: runStatus.durationMs };
    return derived;
  }
  if (isLast && t.role === "agent" && !t.error && turns[i - 1]?.role === "user" && runStatus?.phase === "done")
    return {
      kind: "done",
      durationMs: runStatus.durationMs,
      usage: runStatus.usage ?? null,
    };
  return null;
}

/** The statuses of a tool call that succeeded: a change that landed is
 * "applied", an install waiting for its review "proposed". */
const SUCCEEDED = new Set(["ok", "proposed", "applied"]);

/**
 * #447: the failed tool calls whose reason stays under a reply, live and after
 * a reload. Only a failed call of a granted tool carries a reason (a request
 * for a tool the agent is not granted is refused to the model only). An
 * egress refusal always keeps its line; any other failure keeps it only when
 * no later call of the same tool in that turn succeeded, so a request the
 * model corrected leaves nothing beside the change that followed.
 */
export function lastingToolFailures(turn: AgentSessionTurn): AgentToolCall[] {
  const calls = turn.execution?.toolCalls ?? [];
  return calls.filter(
    (call, i) =>
      Boolean(call.reason) &&
      (call.egress === true ||
        !calls.slice(i + 1).some((later) => later.tool === call.tool && SUCCEEDED.has(later.status))),
  );
}

/** What an agent whose work lands on the canvas declares (#243): it builds
 * nodes, or plans and solves a dataflow. */
const CANVAS_CAPABILITIES = [NODE_BUILD_CAPABILITY, ORCHESTRATE_CAPABILITY];

/**
 * #243: a canvas agent's reply that holds no change and no install's review
 * changed nothing on the canvas, and says so, so a reply that claims a new
 * node is never the only account. Read from the transcript, so it holds after
 * a reload too:
 * - only a reply to the user's message: a Solve verdict or an apply result
 *   follows no message, and a task another agent delegated here carries that
 *   run's id (`parentExecutionId`);
 * - only once the reply landed with its execution record, so a reply still
 *   streaming says nothing yet;
 * - a delegation that went through hands the change to the agent it names,
 *   whose chat holds its card, so that reply says nothing either.
 */
export function canvasUnchangedFor(attachment: AgentAttachment, turns: AgentSessionTurn[], i: number): boolean {
  const t = turns[i];
  if (!CANVAS_CAPABILITIES.some((capability) => declaresCapability(attachment, capability))) return false;
  if (t.role !== "agent" || t.error || !t.execution || "parentExecutionId" in t.execution) return false;
  if (turns[i - 1]?.role !== "user") return false;
  return !(t.content ?? []).some(
    (p) =>
      p.type === "proposal" ||
      p.type === "change" ||
      (p.type === "delegation" && (p as AgentDelegationPart).status === "ok"),
  );
}

/** What runs on a plan now, as the chat streams it: the live batch's runs,
 * its reasons and notices, the nodes it waits on the person for, and the
 * running build's narration. */
export interface PlanLive {
  solveProgress?: Record<string, string>;
  solveErrors?: Record<string, string>;
  solveNotices?: Record<string, string>;
  solveWaiting?: Array<{ nodeId: string; kind: string }>;
  simulationActivity?: string;
}

/** A landed plan's card gets the plan's per-node state: the attachment's
 * plan (`planProposal`) and builder session, while they are this plan's,
 * with what runs on it now (*live*): whether a build runs on it
 * (*buildRunning*), on which node and doing what, or a batch Solve; the row
 * whose Solve runs on the server (the listing's `validating`), which reads
 * Building and holds the others; each node's run, the reason it failed (a
 * build's pause on it among them), the notice of one left pending or
 * skipped, and the nodes that wait for the person's pick of their source.
 * Reasons and notices are the live batch's words, over those the plan's
 * ledger keeps of the last Solve (`nodeReasons`), which a reload and every
 * tab read, said only of a node still not built, and not while a batch runs,
 * whose stream says its own. */
export function planNodeStateFor(
  attachment: AgentAttachment,
  part: AgentChangePart,
  buildRunning = false,
  live: PlanLive = {},
): PlanNodeReviewState | undefined {
  const plan = part.planId && attachment.planProposal?.proposalId === part.planId ? attachment.planProposal : null;
  if (!plan) return undefined;
  const session = attachment.builderSession;
  const nodeIds = { ...(session?.nodeIds ?? {}), ...(plan.nodeIds ?? {}) };
  const runs = { ...(session?.nodeRuns ?? {}), ...(live.solveProgress ?? {}) };
  const batchRunning =
    session?.phase === "solving" ||
    (attachment.liveJob?.status === "running" && attachment.liveJob.kind === "solve-batch");
  // What the last Solve said of each node it left unbuilt, as its run says.
  const keptFailures: Record<string, string> = {};
  const keptNotices: Record<string, string> = {};
  if (!batchRunning) {
    const stateOf: Record<string, string | undefined> = {};
    for (const [ref, id] of Object.entries(nodeIds)) stateOf[id] = session?.nodeStates?.[ref];
    for (const [id, reason] of Object.entries(session?.nodeReasons ?? {})) {
      const run = runs[id];
      if (isBuiltNode(stateOf[id], run)) continue;
      if (run === "failed") keptFailures[id] = reason;
      else if (run === "pending" || run === "skipped") keptNotices[id] = `${run}: ${reason}`;
    }
  }
  const failures = { ...keptFailures, ...(live.solveErrors ?? {}) };
  // A build that paused on a node whose check failed says why on its row.
  const pause = session?.pauseReason;
  if (!buildRunning && pause?.kind === "validation-failed" && pause.ref && nodeIds[pause.ref]) {
    const message = pause.message.trim();
    const failedId = nodeIds[pause.ref];
    if (!failures[failedId]) failures[failedId] = `${message.charAt(0).toUpperCase()}${message.slice(1)}`;
  }
  return {
    appliedRefs: plan.appliedRefs ?? [],
    nodeStates: session?.nodeStates ?? {}, // dev/71: the lifecycle ledger
    nodeChanges: session?.nodeChanges ?? {}, // dev/72: where each node's change lives
    nodeChecks: session?.nodeChecks ?? {},
    nodeIds,
    scenarioStates: plan.scenarioStates ?? {}, // #662: which scenarios are saved
    buildRunning,
    buildRef: buildRunning ? session?.currentRef ?? null : null,
    buildActivity: buildRunning ? live.simulationActivity ?? null : null,
    batchRunning,
    solvingRef: attachment.validating?.ref ?? null,
    runs,
    failures,
    notices: { ...keptNotices, ...(live.solveNotices ?? {}) },
    waitsForPick: [
      ...(attachment.waitsForYou ?? []),
      ...(live.solveWaiting ?? []).filter((w) => w.kind === "dataset-selection").map((w) => w.nodeId),
    ],
  };
}

/** What an agent is attached to, in the chat's words. */
export interface TargetPhrase {
  /** The header's words after the title: "on the canvas", "on Load buildings",
   *  "from Load buildings to Join blocks". */
  header: string;
  /** What the agent stays attached to: "the canvas", "Load buildings", "the
   *  connection from Load buildings to Join blocks". */
  object: string;
  /** The rail's line under the agent's name; none for the canvas. */
  short: string | null;
}

/**
 * The canvas, the node by the name its header shows, or the connection by the
 * two nodes it joins, never by an id (#228). *targetName* is resolved by the
 * overlay, which can see the canvas: a node's name, or "from A to B" for a
 * connection. A target the canvas no longer holds is named by its kind and
 * id; the ids are on the header's tooltip either way.
 */
export function targetPhraseFor(attachment: AgentAttachment, targetName: string | null | undefined): TargetPhrase {
  const { kind, targetId } = attachment.target;
  if (kind === "canvas") return { header: "on the canvas", object: "the canvas", short: null };
  const name = targetName?.trim();
  if (!name) {
    const unnamed = `${kind} ${targetId ?? ""}`.trim();
    return { header: `on ${unnamed}`, object: unnamed, short: unnamed };
  }
  return kind === "connection"
    ? { header: name, object: `the connection ${name}`, short: name }
    : { header: `on ${name}`, object: name, short: name };
}

/** A connection by the two nodes it joins, as the header and the rail say it. */
export function connectionName(from: string, to: string): string {
  return `from ${from} to ${to}`;
}

/** The diagnostic ids live in the target's tooltip rather than the header (#228). */
export function targetTooltipFor(attachment: AgentAttachment): string {
  return attachment.target.kind === "canvas"
    ? `session ${attachment.sessionId}`
    : `${attachment.target.kind} ${attachment.target.targetId ?? ""} · session ${attachment.sessionId}`;
}

/** SUGGESTED PROMPTS (memo dev/39, docs/08): only the newest turn's part
 * counts, drawn or kept for the agents: once the user replies, or the runtime
 * writes a turn after the reply, earlier follow-ups are stale noise. A turn
 * the chat does not draw offers none of its own. */
export function suggestedPromptsOf(turns: AgentSessionTurn[]): AgentSuggestedPromptsPart | null {
  const last = turns[turns.length - 1];
  if (!last || last.role !== "agent" || last.error || !shownInChat(last)) return null;
  const part = (last.content ?? []).find((p) => p.type === "suggestedPrompts");
  return (part as AgentSuggestedPromptsPart | undefined) ?? null;
}
