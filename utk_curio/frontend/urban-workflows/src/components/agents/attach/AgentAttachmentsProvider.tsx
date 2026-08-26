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
import {
  agentsApi,
  type AgentApplyResult,
  type AgentSessionTurn,
  type AgentUsage,
} from "../../../api/agentsApi";
import { notifyAgentCanvasMutation } from "../../../utils/agentCanvasEvents";
import { notifyAgentCatalogRefresh } from "../../../utils/agentCatalogEvents";
import { useAgentAttachments, type AgentAttachmentsState } from "./useAgentAttachments";
import type { AgentRunStatus } from "./agentRunStatus";

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
  /** Run one turn: appends the user turn, the reply (or an error marker).
   * `context` is the ephemeral grounded canvas state (memo dev/44), composed
   * fresh by the caller on every send. */
  sendMessage: (attachmentId: string, message: string, context?: string | null) => Promise<void>;
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
  /** Per-attachment run status (memo dev/80): `running` from send until the
   * SAME synchronous block that lands the final turn finalizes it to
   * `done`/`error` — the chat status strip's source of truth. Survives panel
   * close/reopen and attachment cycling; cleared with the conversation. */
  runStatus: Record<string, AgentRunStatus>;
  /** Apply a pending review proposal (the only mutation path); refreshes the
   * transcript + listing so the outcome and result turn arrive together. */
  applyProposal: (attachmentId: string, proposalId: string) => Promise<AgentApplyResult>;
  /** dev/67-5: apply ONE planned node (Simulation Mode: create) — the
   * proposal stays pending; the created node reaches the live canvas. */
  applyPlanNode: (attachmentId: string, proposalId: string, ref: string) => Promise<void>;
  /** dev/67-9: run the Simulation Mode driver (step or auto) — canvas
   * mutations from the stream apply live; resolves with the done payload. */
  runSimulation: (
    attachmentId: string,
    mode: "step" | "auto",
  ) => Promise<Record<string, unknown>>;
  /** dev/67-9: transient narration of the running simulation's current step. */
  simulationActivity: Record<string, string>;
  /** dev/67-9: cancel the running simulation at its next boundary. */
  cancelSimulation: (attachmentId: string) => Promise<void>;
  /** dev/67-8: apply plan edges (all pending, or a subset by index) — the
   * connection review stage; applied edges reach the live canvas. */
  applyPlanEdges: (
    attachmentId: string,
    proposalId: string,
    indices?: number[],
  ) => Promise<import("../../../api/agentsApi").AgentPlanEdgesResult>;
  /** dev/71: run the dataflow through one node (real run; journaled). */
  runNode: (
    attachmentId: string,
    target: { ref?: string; nodeId?: string },
    onEvent?: (name: string, payload: Record<string, unknown>) => void,
  ) => Promise<Record<string, unknown>>;
  /** dev/67-7: validate one node by running the dataflow through it —
   * resolves with the done payload (verdict, evidence, proposalId). */
  validateNode: (
    attachmentId: string,
    target: { ref?: string; nodeId?: string },
    onEvent?: (name: string, payload: Record<string, unknown>) => void,
  ) => Promise<Record<string, unknown>>;
  /** dev/67-5: edit one planned node's goal before creation. */
  savePlanGoal: (
    attachmentId: string,
    proposalId: string,
    ref: string,
    goal: string,
  ) => Promise<void>;
  /** dev/52 Solve: one authenticated batch; optional nodeIds = the Retry
   * subset. Streams per-node progress (dev/63) — see `solveProgress`. */
  solveAttachment: (
    attachmentId: string,
    nodeIds?: string[],
  ) => Promise<import("../../../api/agentsApi").AgentSolveResult>;
  /** Transient per-node solve statuses for the LIVE batch (dev/63):
   * attachmentId → nodeId → solving|solved|failed|skipped. Display overlay
   * only — cleared on the terminal event; the persisted builderSession stays
   * the truth. */
  solveProgress: Record<string, Record<string, string>>;
  /** dev/106: the LIVE batch's per-node failure reasons (attachmentId →
   * nodeId → error text from the `node_result` event). Cleared when the
   * attachment's next solve starts — NOT on done, so the strip can show why
   * the pills say failed. The Solve turn's card is the durable record. */
  solveErrors: Record<string, Record<string, string>>;
  /** Cancel the running solve (dev/63): in-flight children finish and
   * persist; undispatched targets revert to pending. */
  cancelSolve: (attachmentId: string) => Promise<void>;
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
  // dev/80: per-attachment run status for the chat status strip. The seq
  // counter guards against a stale run's late events overwriting a newer
  // run's entry (rapid re-sends).
  const [runStatus, setRunStatus] = useState<Record<string, AgentRunStatus>>({});
  const runSeqRef = useRef<Record<string, number>>({});
  // dev/63: the live solve's per-node overlay + its abort handle.
  const [solveProgress, setSolveProgress] = useState<Record<string, Record<string, string>>>({});
  const [solveErrors, setSolveErrors] = useState<Record<string, Record<string, string>>>({});
  // dev/67-9: the running simulation's narration line, per attachment.
  const [simulationActivity, setSimulationActivity] = useState<Record<string, string>>({});
  const solveAbortRef = useRef<Map<string, AbortController>>(new Map());
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
      // synchronous block that lands the final turn finalizes it — the strip
      // never shows a final message beside a stale "running" (or no) status.
      const seq = (runSeqRef.current[attachmentId] =
        (runSeqRef.current[attachmentId] ?? 0) + 1);
      const startedAt = Date.now();
      setRunStatus((prev) => ({ ...prev, [attachmentId]: { phase: "running", startedAt } }));
      const finalizeStatus = (patch: Omit<AgentRunStatus, "startedAt">) => {
        // A newer run owns this attachment's strip — never clobber it.
        if (runSeqRef.current[attachmentId] !== seq) return;
        setRunStatus((prev) => ({ ...prev, [attachmentId]: { startedAt, ...patch } }));
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
        // Transient system lines (dev/41 tools; dev/48 delegates): live during
        // the run, gone on finalize — the durable record is the execution.
        const tool = typeof payload.tool === "string" ? payload.tool : "";
        const capability = typeof payload.capability === "string" ? payload.capability : "";
        const coord = typeof payload.coord === "string" ? payload.coord : "";
        const line =
          name === "tool_requested"
            ? `${tool} …`
            : name === "tool_result"
              ? `${tool} · ${payload.status ?? ""}`
              : name === "delegate_requested"
                ? `delegating ${capability} …`
                : name === "delegate_result"
                  ? // dev/72: the event names the delegate; the durable record
                    // is the turn's delegation entry (icon-linked to its home).
                    `${(typeof payload.name === "string" && payload.name) || coord || capability} · ${payload.status ?? ""}`
                  : name === "plan_revision"
                    ? `revising the plan (attempt ${payload.attempt ?? "?"}) …`
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
          context,
        );
        // The finalized turn keeps the run's execution identity + Actual usage
        // (memo dev/37), its duration (dev/80), and its typed content parts
        // (memo dev/39) so the local transcript matches the persisted one.
        const durationMs = result.durationMs ?? Date.now() - startedAt;
        const execution = result.executionId
          ? {
              executionId: result.executionId,
              usage: result.usage ?? null,
              status: "ok" as const,
              durationMs,
            }
          : undefined;
        const content = result.content && result.content.length ? result.content : undefined;
        sawProposal = sawProposal || Boolean(content?.some((p) => p.type === "proposal"));
        // Same synchronous block as the turn landing (dev/80): React 18
        // batches both updates into one commit — the reply and its finished
        // status appear together. Status first as defense-in-depth: were the
        // pair ever unbatched, the safe intermediate is "done beside partial
        // text", never "final text beside running".
        finalizeStatus({ phase: "done", durationMs, usage: result.usage ?? null });
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
          // Pre-delta stream failure → one blocking-run fallback. Payload
          // parity with the streamed path (dev/53): the turn keeps its
          // execution record AND its content parts — a proposal minted over
          // this path still renders its review card.
          try {
            const result = await state.run(attachmentId, message, context);
            const durationMs = result.durationMs ?? Date.now() - startedAt;
            const execution = result.executionId
              ? {
                  executionId: result.executionId,
                  usage: result.usage ?? null,
                  status: "ok" as const,
                  durationMs,
                }
              : undefined;
            const content = result.content && result.content.length ? result.content : undefined;
            sawProposal = sawProposal || Boolean(content?.some((p) => p.type === "proposal"));
            finalizeStatus({ phase: "done", durationMs, usage: result.usage ?? null });
            appendTurns(attachmentId, [
              {
                role: "agent",
                text: result.reply,
                ...(execution ? { execution } : {}),
                ...(content ? { content } : {}),
              },
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

  const applyProposal = useCallback(
    async (attachmentId: string, proposalId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyProposal(pid, attachmentId, proposalId);
        // The apply→canvas bridge (dev/48 §3.3): the saved spec was mutated;
        // carry the same mutation to the LIVE canvas in this user action so
        // the next save can't clobber it. The apply response is the only
        // payload source.
        if (result.requiresRegistryRefresh && result.installedPackage) {
          // dev/89: an applied package draft — the bridge refreshes the
          // package registry BEFORE painting the created nodes.
          notifyAgentCanvasMutation({
            kind: "package-nodes-created",
            artifactDigest: proposalId,
            packageDir: result.installedPackage.dirName,
            nodes: result.createdNodes ?? [],
          });
        } else if (result.createdNode) {
          notifyAgentCanvasMutation({
            kind: "node-created",
            node: result.createdNode,
            createdPackageDir: result.createdTemplate?.packageDir,
          });
        } else if (result.appliedContent) {
          notifyAgentCanvasMutation({
            kind: "node-content-applied",
            nodeId: result.appliedContent.nodeId,
            content: result.appliedContent.content,
          });
        } else if (result.appliedGraph) {
          // dev/52: a whole applied plan — bulk insert + edges + fit;
          // dev/59: removals ride the same event, applied first.
          notifyAgentCanvasMutation({
            kind: "graph-created",
            planId: proposalId,
            nodes: result.appliedGraph.nodes,
            edges: result.appliedGraph.edges,
            removedNodeIds: result.appliedGraph.removedNodeIds,
            removedEdgeIds: result.appliedGraph.removedEdgeIds,
          });
        }
        // dev/106: a reviewed project.install landed a template (and its
        // required closure) in the lockfile — the AGENTS palette repaints.
        if (result.installedCoord) notifyAgentCatalogRefresh();
        // dev/105 A3: callers that queue follow-ups (the package install
        // review) read the result to walk them one at a time.
        return result;
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

  const applyPlanNode = useCallback(
    async (attachmentId: string, proposalId: string, ref: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyPlanNode(pid, attachmentId, proposalId, ref);
        // The created node reaches the LIVE canvas through the same bridge
        // path as node.create applies (dev/48 §3.3).
        if (result.createdNode) {
          notifyAgentCanvasMutation({ kind: "node-created", node: result.createdNode });
        }
        // dev/71: the progressive sweep's edges draw immediately too.
        if (result.createdEdges?.length) {
          notifyAgentCanvasMutation({
            kind: "edges-created",
            batchId: `${proposalId}:${ref}:${result.createdEdges.map((e) => e.id).join(",")}`,
            edges: result.createdEdges,
          });
        }
      } finally {
        // The result turn + the per-node ledger both refresh.
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const runSimulation = useCallback(
    async (attachmentId: string, mode: "step" | "auto") => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      const narrate = (line: string | null) =>
        setSimulationActivity((prev) => {
          if (line === null) {
            const { [attachmentId]: _gone, ...rest } = prev;
            return rest;
          }
          return { ...prev, [attachmentId]: line };
        });
      try {
        return await agentsApi.simulate(pid, attachmentId, mode, (name, payload) => {
          if (name === "node_created" && payload.createdNode) {
            notifyAgentCanvasMutation({
              kind: "node-created",
              node: payload.createdNode as never,
            });
          } else if (name === "node_content_applied" && typeof payload.nodeId === "string") {
            notifyAgentCanvasMutation({
              kind: "node-content-applied",
              nodeId: payload.nodeId,
              content: String(payload.content ?? ""),
            });
          } else if (name === "edges_created" && Array.isArray(payload.createdEdges)) {
            const edges = payload.createdEdges as Array<{ id: string; source: string; target: string }>;
            notifyAgentCanvasMutation({
              kind: "edges-created",
              batchId: `sim:${edges.map((e) => e.id).join(",")}`,
              edges,
            });
          } else if (name === "stage") {
            narrate(
              `${String(payload.action)}${payload.label ? ` — ${String(payload.label)}` : ""}`,
            );
          } else if (name === "node_executed") {
            narrate(`executing upstream ${Number(payload.index) + 1}/${String(payload.total)}`);
          } else if (name === "generation_round") {
            narrate(`generating content (round ${String(payload.round)})`);
          }
        });
      } finally {
        narrate(null);
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const cancelSimulation = useCallback(async (attachmentId: string) => {
    const pid = projectRef.current;
    if (!pid) return;
    try {
      await agentsApi.cancelSimulate(pid, attachmentId);
    } catch {
      // Nothing running (finished at the boundary first) — fine.
    }
  }, []);

  const applyPlanEdges = useCallback(
    async (attachmentId: string, proposalId: string, indices?: number[]) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        const result = await agentsApi.applyPlanEdges(pid, attachmentId, proposalId, indices);
        if (result.createdEdges.length) {
          notifyAgentCanvasMutation({
            kind: "edges-created",
            batchId: `${proposalId}:${result.createdEdges.map((e) => e.id).join(",")}`,
            edges: result.createdEdges,
          });
        }
        return result;
      } finally {
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const runNode = useCallback(
    async (
      attachmentId: string,
      target: { ref?: string; nodeId?: string },
      onEvent?: (name: string, payload: Record<string, unknown>) => void,
    ) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await agentsApi.runNode(
          pid, attachmentId, target, onEvent ?? (() => undefined),
        );
      } finally {
        // The result card + any journal-derived state arrive by refetch.
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const validateNode = useCallback(
    async (
      attachmentId: string,
      target: { ref?: string; nodeId?: string },
      onEvent?: (name: string, payload: Record<string, unknown>) => void,
    ) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      try {
        return await agentsApi.validateNode(
          pid, attachmentId, target, onEvent ?? (() => undefined),
        );
      } finally {
        // The validated proposal + ledger states arrive by refetch.
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const savePlanGoal = useCallback(
    async (attachmentId: string, proposalId: string, ref: string, goal: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      await agentsApi.savePlanGoal(pid, attachmentId, proposalId, ref, goal);
      await state.reload(); // the mirror carries editedGoals
    },
    [state.reload],
  );

  const solveAttachment = useCallback(
    async (attachmentId: string, nodeIds?: string[]) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      // Streaming is THE solve path (dev/63): per-node progress overlays the
      // pills, and each solved node's content reaches the LIVE canvas the
      // moment its child finishes — the same bridge path as node.content.write
      // applies (dev/51 semantics). The persisted session is refetched at the
      // end either way; the overlay is display-only.
      const controller = new AbortController();
      solveAbortRef.current.set(attachmentId, controller);
      const mark = (nodeId: string, status: string) =>
        setSolveProgress((prev) => ({
          ...prev,
          [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: status },
        }));
      // dev/106: a fresh batch starts with a clean reason slate.
      setSolveErrors((prev) => {
        const { [attachmentId]: _gone, ...rest } = prev;
        return rest;
      });
      try {
        const result = await agentsApi.solveAttachmentStream(
          pid,
          attachmentId,
          (name, payload) => {
            const nodeId = typeof payload.nodeId === "string" ? payload.nodeId : null;
            if (name === "node_started" && nodeId) mark(nodeId, "solving");
            else if (name === "node_result" && nodeId) {
              mark(nodeId, typeof payload.status === "string" ? payload.status : "failed");
              if (typeof payload.error === "string" && payload.error) {
                const reason = payload.error;
                setSolveErrors((prev) => ({
                  ...prev,
                  [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: reason },
                }));
              }
              if (payload.status === "solved" && typeof payload.content === "string") {
                notifyAgentCanvasMutation({
                  kind: "node-content-applied",
                  nodeId,
                  content: payload.content,
                });
              }
            }
          },
          nodeIds,
          controller.signal,
        );
        return result;
      } finally {
        solveAbortRef.current.delete(attachmentId);
        setSolveProgress((prev) => {
          const { [attachmentId]: _gone, ...rest } = prev;
          return rest;
        });
        // The solve result turn + the builder session both refresh.
        hydratedRef.current.delete(attachmentId);
        await hydrateSession(attachmentId);
        await state.reload();
      }
    },
    [hydrateSession, state.reload],
  );

  const cancelSolve = useCallback(async (attachmentId: string) => {
    const pid = projectRef.current;
    if (!pid) return;
    try {
      // The durable signal: the server stops dispatching at the next node
      // boundary; the stream then ends normally with `done.cancelled` — no
      // abort needed, so in-flight pills still resolve.
      await agentsApi.cancelSolve(pid, attachmentId);
    } catch {
      // No solve running (finished meanwhile) — fine. If the endpoint is
      // unreachable, at least stop listening: the server halts dispatch at
      // its next yield to the gone client.
      solveAbortRef.current.get(attachmentId)?.abort();
    }
  }, []);

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
      // dev/80: the status strip lives exactly as long as the conversation.
      setRunStatus((prev) => {
        const { [attachmentId]: _drop, ...rest } = prev;
        return rest;
      });
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
      setRunStatus((prev) => {
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
      runStatus,
      applyProposal,
      solveAttachment,
      solveProgress,
      solveErrors,
      cancelSolve,
      applyPlanNode,
      savePlanGoal,
      applyPlanEdges,
      validateNode,
      runNode,
      runSimulation,
      simulationActivity,
      cancelSimulation,
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
      runStatus,
      applyProposal,
      solveAttachment,
      solveProgress,
      solveErrors,
      cancelSolve,
      applyPlanNode,
      savePlanGoal,
      applyPlanEdges,
      validateNode,
      runNode,
      runSimulation,
      simulationActivity,
      cancelSimulation,
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
