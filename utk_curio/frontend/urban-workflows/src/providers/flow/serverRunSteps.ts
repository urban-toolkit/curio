// What a run on the server means for the canvas, as plain functions: what an
// event does to its node, which nodes the browser still has to run, which
// outputs a reopened canvas takes from the run, and which ancestor outputs a
// play reuses. useServerRun applies them.
import type { Edge, Node } from "reactflow";
import type { RunEvent, RunStep, StepRole, StepStatus } from "../../services/runs/runsApi";
import type { IOutput } from "./flowTypes";
import { directedEdgesOf, nodesToRunUpTo } from "./runLevels";

/** What a node shows when Stop ended the run while it was executing. */
export const STOPPED_MESSAGE = "Stopped before this node finished, so its result was not kept.";

/** A step as the canvas tracks it while the run goes. */
export type TrackedStep = { role: StepRole; status: StepStatus };

export type NodeChange =
  | { kind: "running" }
  | { kind: "result"; reply: any; startedAt?: number; finishedAt?: number }
  | { kind: "skipped"; reason: string }
  | { kind: "stopped" };

/**
 * What a step event does to its node, or ``null`` when the canvas does
 * nothing: a node the run forwarded passes its data on as it lands, and one
 * only the browser runs waits for the run's end.
 */
export function nodeChangeFor(
  event: RunEvent,
  step: TrackedStep | undefined,
  { started }: { started: boolean },
): NodeChange | null {
  if (event.kind === "step_started") return { kind: "running" };
  if (event.kind !== "step_finished") return null;
  switch (event.status) {
    case "ok":
    case "error":
      if (step && step.role !== "run") return null;
      return {
        kind: "result",
        reply: event.reply ?? replyFromTails(event),
        startedAt: event.startedAt,
        finishedAt: event.finishedAt,
      };
    case "skipped":
      return { kind: "skipped", reason: event.skipReason ?? "" };
    case "cancelled":
    case "interrupted":
      // A node that never started keeps what it showed.
      return started ? { kind: "stopped" } : null;
    default:
      return null;
  }
}

/** The reply a step stands for when the run kept only its tails: an engine-made failure, or a record. */
export function replyFromTails(step: {
  output?: { path?: string; dataType?: string } | null;
  stdoutTail?: string | null;
  stderrTail?: string | null;
}): any {
  const path = step.output?.path ?? "";
  return {
    stdout: step.stdoutTail ? [step.stdoutTail] : [],
    stderr: step.stderrTail ?? "",
    output: { path, dataType: step.output?.dataType ?? "str" },
  };
}

/** A recorded step as the event that finished it. */
export function replyFromRecord(step: RunStep): any {
  return replyFromTails({
    output: step.outputPath ? { path: step.outputPath, dataType: step.outputType ?? undefined } : null,
    stdoutTail: step.stdoutTail,
    stderrTail: step.stderrTail,
  });
}

/**
 * The nodes a tab runs once the server's part has ended: every node only a
 * browser can run, every node that waited for one, and the nodes the run
 * forwarded above them. A forwarded node passes its data on in the canvas, a
 * Data Pool after a fetch of its own, so the walk includes it and runs a node
 * below it only once that data has arrived, as Run All does.
 *
 * *played* is the node a play ran up to. When the run only forwarded it (a
 * chart, say), the browser still runs it, as its play button would.
 */
export function browserWalk(steps: Map<string, TrackedStep>, edges: Edge[], played?: string | null): string[] {
  const walk = new Set<string>();
  for (const [nodeId, step] of steps) {
    if (step.status === "browser" || step.status === "waiting") walk.add(nodeId);
  }
  if (played && steps.get(played)?.status === "forwarded") walk.add(played);
  if (!walk.size) return [];
  const predecessors = new Map<string, string[]>();
  for (const edge of directedEdgesOf(edges)) {
    const list = predecessors.get(edge.target) ?? [];
    list.push(edge.source);
    predecessors.set(edge.target, list);
  }
  const queue = [...walk];
  while (queue.length) {
    const nodeId = queue.pop()!;
    for (const source of predecessors.get(nodeId) ?? []) {
      if (!walk.has(source) && steps.get(source)?.status === "forwarded") {
        walk.add(source);
        queue.push(source);
      }
    }
  }
  return [...walk];
}

/** Whether the browser's outcome for this step is the run's to record. */
export function reportsToRun(step: TrackedStep | undefined): boolean {
  return !!step && (step.role === "browser" || step.status === "waiting");
}

/**
 * The steps whose output a canvas opened after the run shows as its nodes'
 * own: executed, succeeded, with an output, on code the node still holds, and
 * for a node the saved outputs did not already restore.
 */
export function stepsToRestore(steps: RunStep[], restored: ReadonlySet<string>): RunStep[] {
  return steps.filter(
    (step) =>
      step.role === "run" &&
      step.status === "ok" &&
      !!step.outputPath &&
      step.codeCurrent === true &&
      !restored.has(step.nodeId),
  );
}

/**
 * The ancestor outputs a play of *targetNodeId* reuses: those of the ancestors
 * the in-browser walk would not run again, as the canvas holds them.
 */
export function reuseFor(
  targetNodeId: string,
  nodes: Node[],
  edges: Edge[],
  emittedForInput: Map<string, unknown>,
  outputs: IOutput[],
): Record<string, unknown> {
  const { ancestorIds, willRun } = nodesToRunUpTo(targetNodeId, nodes, edges, emittedForInput);
  const reuse: Record<string, unknown> = {};
  for (const nodeId of ancestorIds) {
    if (willRun.has(nodeId)) continue;
    const output = outputs.find((o) => o.nodeId === nodeId)?.output as any;
    if (output && typeof output === "object" && (output.path || output.data)) reuse[nodeId] = output;
  }
  return reuse;
}
