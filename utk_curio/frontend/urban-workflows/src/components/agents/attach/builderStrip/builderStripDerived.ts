/**
 * The plan line's pure vocabulary and derivations (memo dev/142, F4, split
 * out of `AgentBuilderStrip.tsx`): the line's words and its one action, the
 * running line's detail, whether a landed plan has nodes left to build, the
 * order the plan's nodes read in, and the remedy de-duplication. The line says
 * where the plan stands in one count, and names the node a pause or a failure
 * is about; each node's own state is on its row of the plan's card.
 */
import type { AgentBuilderSession, AgentProposalSummary, AgentRemedy, AgentSolveWave } from "../../../../services/agents";

/** The plan line's one action, or none while a build nobody can stop runs. */
export type PlanMainAction = "solve" | "stop-solve" | "stop-build" | "resume" | "show-sources" | "run" | null;

/** Which action the plan line holds: Stop while a batch or a build runs and
 *  can be stopped; Show its sources while a node waits for the person's pick
 *  of its source, which goes on by itself once made; Resume when a build
 *  paused on anything else; Run workflow once the plan is ready; else Solve
 *  (or its Retry, or Solving… while a batch nobody can stop runs). A running
 *  build offers no Solve: it would run over the same nodes. */
export function mainActionOf(opts: {
  solveRunning: boolean;
  canStopSolve: boolean;
  building: boolean;
  canStopBuild: boolean;
  waitsForPick: boolean;
  paused: boolean;
  phase: string;
}): PlanMainAction {
  if (opts.solveRunning) return opts.canStopSolve ? "stop-solve" : "solve";
  if (opts.building) return opts.canStopBuild ? "stop-build" : null;
  if (opts.waitsForPick) return "show-sources";
  if (opts.paused) return "resume";
  return opts.phase === "ready" ? "run" : "solve";
}

/** The line's words while nothing runs: the phase, in bold; then, after a
 *  dot, either a count (`muted`), or the node it is about (`subject`) and
 *  what of it (`predicate`, in the *tone* of a wait or a failure); and last,
 *  a node that waits for the person's pick while others can still go on
 *  (`waits`, in the wait's tone). */
export interface PlanLineWords {
  phase: string;
  muted?: string;
  subject?: string;
  predicate?: string;
  tone?: "warn" | "fail";
  waits?: string;
}

/** Why a build paused, as the line names it. */
export interface PauseView {
  /** `pick`: nodes wait for the person's pick of their source; `download`
   *  and `install`: for a source picked; `failed`: a node's check failed;
   *  `other`: anything else, said in the server's words. */
  kind: "pick" | "download" | "install" | "failed" | "other";
  /** The nodes it is about, by name, in plan order. */
  names: string[];
  /** The server's words, for `other`. */
  message?: string;
}

/** How many of *n* things, "1 node", "3 nodes". */
export function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/** The nodes a line names: one by its name, several by their count. */
function named(names: string[]): { subject: string; several: boolean } {
  return names.length === 1 ? { subject: names[0], several: false } : { subject: plural(names.length, "node"), several: true };
}

/**
 * The plan line's words while nothing runs: "Planned · 3 nodes", "Planned ·
 * 2 of 3 built" once some are built, "Ready · 3 nodes built", "Paused · CPL
 * branches needs a source", "Paused · CPL
 * branches failed", "Failed · 2 nodes", "Stopped · 2 left", "Interrupted · 2
 * left". A pause or a failure names its node, or counts them when several.
 * Nodes that wait for the person's pick pause the plan when no other node is
 * left to build (*pickBlocksAll*); else the line ends with them.
 */
export function planLineWords(opts: {
  phase: string;
  /** Nodes that wait for the person's pick of their source, by name. */
  waitingForPick: string[];
  /** Every node left to build waits for a pick. */
  pickBlocksAll: boolean;
  pause: PauseView | null;
  /** Nodes whose Solve failed, by name. */
  failed: string[];
  /** How the last batch session ended: stopped, budget or blocked. */
  ended: string | null;
  /** This line's build was stopped, and nothing ran since. */
  buildStopped: boolean;
  /** The plan's nodes, and how many of them are not built yet. */
  nodes: number;
  left: number;
}): PlanLineWords {
  const { waitingForPick, pickBlocksAll } = opts;
  if (waitingForPick.length > 0) {
    const { subject, several } = named(waitingForPick);
    const predicate = several ? "need a source" : "needs a source";
    if (pickBlocksAll) return { phase: "Paused", subject, predicate, tone: "warn" };
    return { ...lineWordsBesidePicks(opts), waits: `${subject} ${predicate}` };
  }
  return lineWordsBesidePicks(opts);
}

/** The line's words but for nodes that wait for a pick. */
function lineWordsBesidePicks(opts: {
  phase: string;
  pause: PauseView | null;
  failed: string[];
  ended: string | null;
  buildStopped: boolean;
  nodes: number;
  left: number;
}): PlanLineWords {
  const { phase, pause, failed, ended, buildStopped, nodes, left } = opts;
  if (pause) {
    const { subject, several } = named(pause.names);
    switch (pause.kind) {
      case "failed":
        return { phase: "Paused", subject, predicate: "failed", tone: "fail" };
      case "download":
        return { phase: "Paused", subject, predicate: several ? "wait for their downloads" : "waits for its download", tone: "warn" };
      case "install":
        return { phase: "Paused", subject, predicate: several ? "need their datasets installed" : "needs its dataset installed", tone: "warn" };
      case "pick":
        return { phase: "Paused", subject, predicate: several ? "need a source" : "needs a source", tone: "warn" };
      default:
        return { phase: "Paused", predicate: pause.message ?? "", tone: "warn" };
    }
  }
  if (phase === "interrupted") return { phase: "Interrupted", muted: `${left} left` };
  if (failed.length > 0) {
    return { phase: "Failed", subject: named(failed).subject, tone: "fail" };
  }
  if (left > 0 && phase !== "ready") {
    if (ended === "blocked") return { phase: "Stopped", predicate: "a specialist must be installed first", tone: "warn" };
    if (ended === "stopped" || buildStopped) return { phase: "Stopped", muted: `${left} left` };
    if (ended === "budget") return { phase: "Out of time", muted: `${left} left` };
  }
  if (phase === "ready") return { phase: "Ready", muted: `${plural(nodes, "node")} built` };
  if (phase === "idle") return { phase: "No plan yet" };
  // One count: the plan's nodes, or once some are built, how many of them.
  return { phase: "Planned", muted: left > 0 && left < nodes ? builtCount(nodes - left, nodes) : plural(nodes, "node") };
}

/** Whether *plan*, the plan the agent landed, has a node Build & validate
 * still has work on: one not approved yet in the builder session's ledger. */
export function planLeftToBuild(
  plan: AgentProposalSummary | null | undefined,
  session: Pick<AgentBuilderSession, "nodeStates">,
): boolean {
  if (!plan || plan.tool !== "dataflow.plan.write" || plan.status !== "applied") return false;
  const states = session.nodeStates ?? {};
  return (plan.appliedRefs ?? []).some((ref) => (states[ref] ?? "created") !== "approved");
}

/** The order the plan's nodes read in: the plan's own, as its card lists its
 * nodes; then each node it does not list, an earlier plan's, in the canvas's
 * order; then any other by id. The session's runs come keyed by node id, in
 * an order that says nothing of the plan: the server's answer sorts them by
 * their keys. */
export function inPlanOrder<T>(
  entries: Array<[string, T]>,
  plan: AgentProposalSummary | null | undefined,
  canvasIds: string[],
): Array<[string, T]> {
  const order = [...(plan?.appliedRefs ?? []).map((ref) => plan?.nodeIds?.[ref]), ...canvasIds];
  const rank = (nodeId: string) => {
    const at = order.indexOf(nodeId);
    return at < 0 ? order.length : at;
  };
  return [...entries].sort(([a], [b]) => rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0));
}

/** A node's run states that are over. */
export const BUILT_RUNS = new Set(["solved", "verified", "written"]);
/** A node's ledger states that are built. */
export const BUILT_STATES = new Set(["validated", "approved"]);
/** A node's run states while its Solve works on it. */
export const AT_WORK_RUNS = new Set(["solving", "generating", "verifying", "fixing"]);

/** What a node at work does now, in words, on its row's and the line's
 *  tooltip. */
export const AT_WORK_WORDS: Record<string, string> = {
  solving: "solving it",
  generating: "writing its code",
  verifying: "running it in the sandbox",
  fixing: "the run failed: fixing it",
};

/** The running line's count: "0 of 3 built". */
export function builtCount(built: number, nodes: number): string {
  return `${built} of ${nodes} built`;
}

/** dev/118: the batch's wave in words, for Show run details: "wave 2 of 3: 4
 *  nodes"; null with one wave. */
export function waveWords(solveWave: AgentSolveWave | undefined): string | null {
  return solveWave && solveWave.of > 1
    ? `wave ${solveWave.wave} of ${solveWave.of}: ${plural(solveWave.nodeIds.length, "node")}`
    : null;
}

/** dev/131: the pass line while the session runs, for Show run details. */
export function passLineText(pass: number, unresolved: number, userBlocked: number): string {
  return (
    `Managing the dataflow: pass ${pass}` +
    (unresolved ? ` · ${plural(unresolved, "node")} left` : "") +
    (userBlocked ? ` · waiting for you on ${plural(userBlocked, "node")}` : "")
  );
}

/** dev/116: one action per host, whatever the number of nodes that need it. */
export function remediesByHost(solveRemedies: Record<string, AgentRemedy> | undefined): AgentRemedy[] {
  return Object.values(solveRemedies ?? {}).filter(
    (r, i, all) => r && r.host && all.findIndex((o) => o.kind === r.kind && o.host === r.host) === i,
  );
}

/** One line per DISTINCT text (six identical node failures → one line). */
export function distinctLines(byNode: Record<string, string> | undefined): string[] {
  return Array.from(new Set(Object.values(byNode ?? {}).filter(Boolean)));
}
