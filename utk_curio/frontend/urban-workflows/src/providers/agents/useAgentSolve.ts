/**
 * Solve from the client's side (memo dev/142, F2 — extracted from
 * `AgentAttachmentsProvider`): the streamed batch (dev/52/63) and its
 * per-node overlay, the per-node Solve (dev/115 A2) and its narration, the
 * background-job re-attach (dev/115, DEC-021 slice), and cancel. Streaming
 * is THE solve path: per-node progress overlays the pills and each solved
 * node's content reaches the LIVE canvas the moment its child finishes;
 * the persisted session is refetched at the end either way.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import { agentsApi, notifyAgentCanvasMutation } from "../../services/agents";
import type { AgentAttachment, AgentRemedy, AgentSolveResult, AgentSolveWave } from "../../services/agents/types";

export type AgentSolveWaiting = Array<{ nodeId: string; kind: string; reason?: string; attachmentId?: string | null }>;

export interface AgentSolveSlice {
  solveAttachment: (attachmentId: string, nodeIds?: string[]) => Promise<AgentSolveResult>;
  solveProgress: Record<string, Record<string, string>>;
  solveErrors: Record<string, Record<string, string>>;
  solveRemedies: Record<string, Record<string, AgentRemedy>>;
  solveWave: Record<string, AgentSolveWave>;
  solveNotices: Record<string, Record<string, string>>;
  solvePass: Record<string, number>;
  solveWaiting: Record<string, AgentSolveWaiting>;
  solveEndedBy: Record<string, string>;
  cancelSolve: (attachmentId: string) => Promise<void>;
  solveNode: (attachmentId: string, nodeId: string) => Promise<Record<string, unknown>>;
  solveNodeActivity: Record<string, string>;
  attachSolveJob: (attachmentId: string) => Promise<void>;
}

type ById<T> = Record<string, T>;

function without<T>(prev: ById<T>, key: string): ById<T> {
  const { [key]: _gone, ...rest } = prev;
  return rest;
}

function readWaiting(raw: unknown): AgentSolveWaiting {
  return Array.isArray(raw)
    ? (raw as Array<Record<string, unknown>>).map((w) => ({
        nodeId: String(w.nodeId ?? ""),
        kind: String(w.kind ?? "retry"),
        reason: typeof w.reason === "string" ? w.reason : undefined,
        attachmentId: typeof w.attachmentId === "string" ? w.attachmentId : null,
      }))
    : [];
}

export function useAgentSolve(opts: {
  projectRef: React.MutableRefObject<string | null>;
  attachments: AgentAttachment[];
  refreshAfterMutation: (attachmentId: string) => Promise<void>;
}): AgentSolveSlice {
  const { projectRef, attachments, refreshAfterMutation } = opts;
  // dev/63: the live solve's per-node overlay + its abort handle.
  const [solveProgress, setSolveProgress] = useState<ById<Record<string, string>>>({});
  const [solveErrors, setSolveErrors] = useState<ById<Record<string, string>>>({});
  const [solveRemedies, setSolveRemedies] = useState<ById<Record<string, AgentRemedy>>>({});
  const [solveWave, setSolveWave] = useState<ById<AgentSolveWave>>({});
  const [solveNotices, setSolveNotices] = useState<ById<Record<string, string>>>({});
  const [solvePass, setSolvePass] = useState<ById<number>>({});
  const [solveWaiting, setSolveWaiting] = useState<ById<AgentSolveWaiting>>({});
  const [solveEndedBy, setSolveEndedBy] = useState<ById<string>>({});
  // dev/115: the per-node Solve's narration, and the background jobs this
  // client is already attached to (never attach twice to one execution).
  const [solveNodeActivity, setSolveNodeActivity] = useState<ById<string>>({});
  const attachedJobsRef = useRef<Set<string>>(new Set());
  const solveAbortRef = useRef<Map<string, AbortController>>(new Map());

  // dev/115: ONE handler for the Solve stream, whether the batch was started
  // here or re-attached — node_started/node_result (dev/63) plus the verified
  // loop's rounds (node_round → generating, node_executed → verifying,
  // node_verdict → verified | fixing) so the pills say what is happening.
  const solveEventHandler = useCallback((attachmentId: string) => {
    const mark = (nodeId: string, status: string) =>
      setSolveProgress((prev) => ({ ...prev, [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: status } }));
    /**
     * dev/137: drop what an earlier pass said about this node. dev/131 made
     * Solve a SESSION of passes, and these maps were only ever written — so
     * the owner's `7a27b702` showed every pill *solved* beside "not fixed
     * after 15 attempts …". Both lines were true of an earlier pass; the
     * event that supersedes a line is what removes it.
     */
    const forget = (nodeId: string) => {
      const drop = <T,>(prev: ById<Record<string, T>>) => {
        const forAttachment = prev[attachmentId];
        if (!forAttachment || !(nodeId in forAttachment)) return prev;
        return { ...prev, [attachmentId]: without(forAttachment, nodeId) };
      };
      setSolveErrors(drop);
      setSolveNotices(drop);
      setSolveRemedies(drop);
    };
    return (name: string, payload: Record<string, unknown>) => {
      if (name === "solve_pass" || name === "solve_waiting") {
        // dev/131: the session keeps making passes; `waiting` names the nodes
        // it is blocked on, and a "dataset-selection" kind means the USER is
        // the blocker.
        if (typeof payload.pass === "number") {
          setSolvePass((prev) => ({ ...prev, [attachmentId]: payload.pass as number }));
        }
        setSolveWaiting((prev) => ({ ...prev, [attachmentId]: readWaiting(payload.waiting) }));
        setSolveEndedBy((prev) => without(prev, attachmentId));
        // dev/137: a node this pass will attempt again carries nothing from
        // the pass before it.
        if (Array.isArray(payload.targets)) {
          for (const target of payload.targets) {
            if (typeof target === "string") forget(target);
          }
        }
        return;
      }
      if (name === "solve_wave") {
        // dev/118 (DEC-075): the batch runs in topological waves.
        const wave = typeof payload.wave === "number" ? payload.wave : 0;
        const of = typeof payload.of === "number" ? payload.of : 0;
        const ids = Array.isArray(payload.nodeIds) ? payload.nodeIds.filter((x): x is string => typeof x === "string") : [];
        setSolveWave((prev) => ({ ...prev, [attachmentId]: { wave, of, nodeIds: ids } }));
        return;
      }
      const nodeId = typeof payload.nodeId === "string" ? payload.nodeId : null;
      if (!nodeId) return;
      if (name === "node_started") mark(nodeId, "solving");
      else if (name === "node_round") mark(nodeId, "generating");
      else if (name === "node_executed") mark(nodeId, "verifying");
      else if (name === "node_verdict")
        mark(nodeId, payload.verdict === "pass" ? "verified" : payload.verdict === "fail" ? "fixing" : "solving");
      else if (name === "node_result") {
        const status = typeof payload.status === "string" ? payload.status : "failed";
        const verification = payload.verification as { status?: unknown; reason?: unknown } | undefined;
        const notExecutable = status === "solved" && verification?.status === "not-executable";
        // dev/118: a browser-rendered kind is WRITTEN, never "verified".
        mark(nodeId, notExecutable ? "written" : status === "solved" && payload.verdict === "pass" ? "verified" : status);
        // dev/137: this result is the node's current truth — whatever an
        // earlier pass said about it is gone before the new state is written.
        forget(nodeId);
        const notice =
          notExecutable && typeof verification?.reason === "string"
            ? verification.reason
            : (status === "pending" || status === "skipped") && typeof payload.reason === "string"
              ? `${status}: ${payload.reason}`
              : null;
        if (notice) {
          setSolveNotices((prev) => ({ ...prev, [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: notice } }));
        }
        if (typeof payload.error === "string" && payload.error) {
          const reason = payload.error;
          setSolveErrors((prev) => ({ ...prev, [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: reason } }));
        }
        const remedy = payload.remedy;
        if (remedy && typeof remedy === "object" && typeof (remedy as { kind?: unknown }).kind === "string") {
          const typed = remedy as AgentRemedy;
          setSolveRemedies((prev) => ({ ...prev, [attachmentId]: { ...(prev[attachmentId] ?? {}), [nodeId]: typed } }));
        }
        if (payload.status === "solved" && typeof payload.content === "string") {
          notifyAgentCanvasMutation({ kind: "node-content-applied", nodeId, content: payload.content });
        }
      }
    };
  }, []);

  /** The live overlay is display-only: gone on the terminal event. */
  const clearLiveOverlay = useCallback((attachmentId: string) => {
    solveAbortRef.current.delete(attachmentId);
    setSolveProgress((prev) => without(prev, attachmentId));
    setSolveWave((prev) => without(prev, attachmentId));
  }, []);

  const solveAttachment = useCallback(
    async (attachmentId: string, nodeIds?: string[]) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      const controller = new AbortController();
      solveAbortRef.current.set(attachmentId, controller);
      // dev/106: a fresh batch starts with a clean reason slate.
      setSolveErrors((prev) => without(prev, attachmentId));
      setSolveNotices((prev) => without(prev, attachmentId));
      setSolveRemedies((prev) => without(prev, attachmentId));
      try {
        const result = await agentsApi.solveAttachmentStream(
          pid, attachmentId, solveEventHandler(attachmentId), nodeIds, controller.signal,
        );
        // dev/131: how the session ended, for the strip's one honest line.
        const endedBy = (result as { endedBy?: string } | undefined)?.endedBy;
        if (typeof endedBy === "string" && endedBy) {
          setSolveEndedBy((prev) => ({ ...prev, [attachmentId]: endedBy }));
        }
        const waiting = (result as { waiting?: unknown } | undefined)?.waiting;
        if (endedBy === "complete") {
          // dev/137: a session that finished everything waits for nothing.
          setSolveWaiting((prev) => without(prev, attachmentId));
        } else if (Array.isArray(waiting)) {
          // Stopped, out of budget or blocked: those nodes DO still wait.
          setSolveWaiting((prev) => ({ ...prev, [attachmentId]: readWaiting(waiting) }));
        }
        return result;
      } finally {
        clearLiveOverlay(attachmentId);
        setSolvePass((prev) => without(prev, attachmentId));
        // The solve result turn + the builder session both refresh.
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, solveEventHandler, clearLiveOverlay, refreshAfterMutation],
  );

  const narrateNodeSolve = useCallback((attachmentId: string, line: string | null) => {
    setSolveNodeActivity((prev) => (line === null ? without(prev, attachmentId) : { ...prev, [attachmentId]: line }));
  }, []);

  // dev/115 (DEC-021 slice): re-attach to a running background Solve — the
  // batch kept going while the panel was closed or the page reloaded; the
  // stream replays what happened and tails the rest. One attach per
  // execution; the session refetch at the end is the truth.
  const attachSolveJob = useCallback(
    async (attachmentId: string) => {
      const pid = projectRef.current;
      if (!pid) return;
      const attachment = attachments.find((a) => a.attachmentId === attachmentId);
      const job = attachment?.liveJob;
      if (!job || job.status !== "running" || attachedJobsRef.current.has(job.executionId)) return;
      attachedJobsRef.current.add(job.executionId);
      const controller = new AbortController();
      solveAbortRef.current.set(attachmentId, controller);
      try {
        if (job.kind === "solve-batch") {
          await agentsApi.attachJobStream(pid, attachmentId, solveEventHandler(attachmentId), controller.signal);
        } else {
          await agentsApi.attachJobStream(
            pid, attachmentId,
            (name, payload) => {
              const round = typeof payload.round === "number" ? payload.round : null;
              const line =
                name === "generation_round" ? `Round ${round ?? "?"}: generating…`
                : name === "node_executed" ? `Round ${round ?? ""}: running in the sandbox…`.replace("Round : ", "")
                : name === "round_verdict" ? `Round ${round ?? "?"}: ${payload.verdict === "pass" ? "passed" : "failed, fixing…"}`
                : null;
              if (line) narrateNodeSolve(attachmentId, line);
            },
            controller.signal,
          );
        }
      } catch {
        // A dropped re-attach is display-only; the job runs on the server.
      } finally {
        clearLiveOverlay(attachmentId);
        narrateNodeSolve(attachmentId, null);
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, attachments, solveEventHandler, clearLiveOverlay, narrateNodeSolve, refreshAfterMutation],
  );

  // dev/115 (Amendment A2): the per-node Solve from the node's own agent.
  const solveNode = useCallback(
    async (attachmentId: string, nodeId: string) => {
      const pid = projectRef.current;
      if (!pid) throw new Error("no project");
      narrateNodeSolve(attachmentId, "Starting: running the node's current code…");
      try {
        return await agentsApi.solveNodeStream(pid, attachmentId, nodeId, (name, payload) => {
          const round = typeof payload.round === "number" ? payload.round : null;
          const line =
            name === "generation_round"
              ? round === 1 ? "Round 1: running the current code…" : `Round ${round}: generating a fix…`
              : name === "node_executed" ? "Running in the sandbox…"
              : name === "round_verdict"
                ? `Round ${round ?? "?"}: ${payload.verdict === "pass" ? "passed ✓" : payload.verdict === "fail" ? "failed, fixing…" : "not verified (sandbox unreachable)"}`
                : null;
          if (line) narrateNodeSolve(attachmentId, line);
        });
      } finally {
        narrateNodeSolve(attachmentId, null);
        await refreshAfterMutation(attachmentId);
      }
    },
    [projectRef, narrateNodeSolve, refreshAfterMutation],
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
  }, [projectRef]);

  return useMemo(
    () => ({
      solveAttachment, solveProgress, solveErrors, solveRemedies, solveWave, solveNotices, solvePass,
      solveWaiting, solveEndedBy, cancelSolve, solveNode, solveNodeActivity, attachSolveJob,
    }),
    [solveAttachment, solveProgress, solveErrors, solveRemedies, solveWave, solveNotices, solvePass,
     solveWaiting, solveEndedBy, cancelSolve, solveNode, solveNodeActivity, attachSolveJob],
  );
}
