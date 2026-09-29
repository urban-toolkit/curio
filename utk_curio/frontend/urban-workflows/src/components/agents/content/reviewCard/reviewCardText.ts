/**
 * The review card's pure text and state derivations (memo dev/142, F4 — split
 * out of `AgentReviewCard.tsx`; every function keeps its name): the source
 * block's labels, the row-state chips, the outcome and effect lines, and the
 * per-row readiness the plan lists compute from the attachment's ledgers.
 */
import type { AgentProposalPart, AgentSourceRef } from "../../../../services/agents";
import { tryGetNodeDescriptor } from "../../../../registry/nodeRegistry";

/** dev/114 (DEC-072): the Source block's kind headline — how the runtime
 * grounded what the proposed code opens or fetches. */
export const SOURCE_KIND_LABEL: Record<string, string> = {
  catalog: "Data Catalog",
  external: "External source",
  "user-path": "User-provided path",
  synthetic: "Synthetic data",
  secret: "Connection key",
  mixed: "Several sources",
};

/** One grounded reference, as plain text (the chip states the verdict). */
export function sourceRefText(ref: AgentSourceRef): string {
  switch (ref.kind) {
    case "catalog":
      return `${ref.title ?? ref.datasetId ?? "dataset"}${ref.format ? ` (${ref.format})` : ""}${
        ref.datasetId ? ` · ${ref.datasetId}` : ""
      }`;
    case "external":
      return `${ref.value ?? ""}${ref.requirement === "credential-gated" ? " · credential-gated" : ""}${
        ref.hint ? ` — ${ref.hint}` : ""
      }`;
    case "secret":
      // dev/116: the key the code reaches by name — never its value.
      return `Connection key · ${ref.name ?? ""}${ref.host ? ` · ${ref.host}` : ""}`;
    case "user-path":
      return `${ref.value ?? ""} — not checked by Curio`;
    case "synthetic":
      return "generated in the node — no external source";
    default:
      return ref.value ?? String(ref.kind);
  }
}

/** dev/67-5/67-8/71: the per-node review state (mirror + builderSession). */
export interface PlanNodeReviewState {
  appliedRefs: string[];
  editedGoals: Record<string, string>;
  /** dev/67-8: edge index → planned|applied|refused. */
  edgeStates?: Record<string, string>;
  /** dev/71: ref → planned|created|solving|validated|approved|failed. */
  nodeStates?: Record<string, string>;
  /** dev/72: ref → its content proposal + the attachment it lives on (the
   * node's own agent when homed; legacy string = builder-homed). */
  nodeProposals?: Record<
    string,
    string | { proposalId: string; attachmentId?: string | null }
  >;
}

/** dev/71: what a row's lifecycle state means for its action cluster. */
export const ROW_STATE_CHIP: Record<string, string> = {
  solving: "Content review pending",
  validated: "Validated — review below",
  approved: "Solved ✓",
  failed: "Failed — Solve retries",
};

export const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The target changed since this was proposed — ask the agent to propose again",
};

/** What one Apply click does, per proposal kind — stated on the card. */
/**
 * dev/119 (DEC-076): can the sandbox run a node.create's kind? The roster's
 * own flag rides the proposal (`pins.executable`); a part minted before that
 * flag falls back to the installed registry descriptor (`hasCode`); a kind
 * the registry has never seen answers null — the card then says nothing.
 */
export function nodeKindExecutable(pins: AgentProposalPart["pins"] | undefined): boolean | null {
  if (typeof pins?.executable === "boolean") return pins.executable;
  const nodeType = pins?.nodeType;
  if (typeof nodeType !== "string" || !nodeType) return null;
  const descriptor = tryGetNodeDescriptor(nodeType);
  return descriptor ? Boolean(descriptor.hasCode) : null;
}

export const EFFECT_LINE: Record<string, string> = {
  "node.create": "Applying adds this node to the canvas.",
  "project.install":
    "Applying installs only this project template — nothing is imported, attached, run, or published.",
  "node.template.create":
    "Applying registers the node type in this project and adds its first node.",
  "dataset.install":
    "Applying installs only this dataset into the project's Data Catalog — no agent is installed.",
  "package.install":
    "Applying opens the package install review (permissions, dependencies, conflicts) — nothing installs until you confirm there.",
  "package.draft.apply":
    "Applying installs the exact reviewed artifact and creates its requested nodes — nothing else changes.",
};

/** dev/112: the removals block title — nodes, connections, and the cascade,
 * each only when present. */
export function removalsTitle(nodes: number, edges: number, cascade: number): string {
  const parts: string[] = [];
  if (nodes) parts.push(`${nodes} node${nodes === 1 ? "" : "s"}`);
  if (edges) parts.push(`${edges} connection${edges === 1 ? "" : "s"}`);
  const cascadeNote = cascade
    ? ` (and ${cascade} connected edge${cascade === 1 ? "" : "s"})`
    : "";
  return `Removes ${parts.join(" · ")}${cascadeNote}`;
}

/** dev/52 (+dev/59): the plan card's effect line — dynamic and honest about
 * removals. */
export function planEffectLine(part: AgentProposalPart): string | null {
  if (part.tool !== "dataflow.plan.write" || !part.plan) return null;
  const n = part.plan.nodes.length;
  const removed = part.plan.removals?.length ?? 0;
  const removedEdges = part.plan.removedEdges?.length ?? 0;
  if (removed) {
    return (
      `Applying adds ${n} node${n === 1 ? "" : "s"} and removes ${removed} — ` +
      "removal deletes their content and cannot be undone."
    );
  }
  if (removedEdges) {
    // dev/112: an edge-only revision — truthful about what changes.
    const e = part.plan.edgeCount;
    return (
      `Applying adds ${e} connection${e === 1 ? "" : "s"} and removes ${removedEdges} — ` +
      "nodes and their content are untouched."
    );
  }
  if (n === 0) {
    const e = part.plan.edgeCount;
    return `Applying adds ${e} connection${e === 1 ? "" : "s"} — existing work is untouched.`;
  }
  return `Applying adds these ${n} connected node${n === 1 ? "" : "s"} to the canvas — existing work is untouched.`;
}

/** A plan node's readiness for its row (dev/71): dependencies by name, its
 * lifecycle state, whether Solve may run, and — when not — why. */
export function planNodeRowState(
  part: AgentProposalPart,
  node: { ref: string },
  planNodeState: PlanNodeReviewState | undefined,
) {
  const planEdges = part.plan!.edges ?? [];
  const nodeStates = planNodeState?.nodeStates ?? {};
  const edgeStates = planNodeState?.edgeStates ?? {};
  const planRefSet = new Set(part.plan!.nodes.map((n) => n.ref));
  const incoming = planEdges.map((edge, index) => ({ ...edge, index })).filter((edge) => edge.to === node.ref);
  const deps = incoming.map((edge) => edge.fromLabel);
  const applied = (planNodeState?.appliedRefs ?? []).includes(node.ref);
  const state = nodeStates[node.ref] ?? (applied ? "created" : "planned");
  const disconnected = incoming.filter((edge) => edgeStates[String(edge.index)] !== "applied");
  const unsolvedUpstream = incoming.filter(
    (edge) => planRefSet.has(edge.from) && nodeStates[edge.from] !== "approved",
  );
  const solvable = applied && disconnected.length === 0 && unsolvedUpstream.length === 0;
  const solveBlocker = !applied
    ? null
    : disconnected.length
      ? `needs '${disconnected[0].fromLabel}' connected first`
      : unsolvedUpstream.length
        ? `needs '${unsolvedUpstream[0].fromLabel}' solved first`
        : null;
  // dev/72: the ref's content review lives on the node's own agent when homed.
  const proposalEntry = planNodeState?.nodeProposals?.[node.ref];
  const reviewHomeId =
    proposalEntry && typeof proposalEntry === "object" ? (proposalEntry.attachmentId ?? null) : null;
  return { deps, applied, state, solvable, solveBlocker, reviewHomeId };
}

/** A plan edge's readiness for its row (dev/67-8): both endpoints must exist
 * (a plan ref must already be applied) before it can be connected. */
export function planEdgeRowState(
  part: AgentProposalPart,
  edge: { from: string; to: string; fromLabel: string; toLabel: string },
  index: number,
  planNodeState: PlanNodeReviewState | undefined,
) {
  const state = planNodeState?.edgeStates?.[String(index)];
  const applied = planNodeState?.appliedRefs ?? [];
  const fromReady = !part.plan!.nodes.some((n) => n.ref === edge.from) || applied.includes(edge.from);
  const toReady = !part.plan!.nodes.some((n) => n.ref === edge.to) || applied.includes(edge.to);
  const blockedBy = !fromReady ? edge.fromLabel : !toReady ? edge.toLabel : null;
  return { state, blockedBy };
}
