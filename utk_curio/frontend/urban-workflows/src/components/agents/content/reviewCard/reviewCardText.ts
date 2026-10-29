/**
 * The review and change cards' pure text and state derivations (memo dev/142,
 * F4 — split out of `AgentReviewCard.tsx`): the source block's labels, the
 * row-state chips, an install's outcome and effect lines, and the per-row
 * readiness a landed plan's rows compute from the attachment's ledgers.
 */
import type { AgentProposalPart, AgentSourceRef } from "../../../../services/agents";

/** What a plan's sections read of its card, a change's: its tool and plan. */
export type PlanDisplay = { tool: string; plan?: AgentProposalPart["plan"] };
import { tryGetNodeDescriptor } from "../../../../registry/nodeRegistry";
import nodeSettings from "../../../../contracts/nodeSettings.json";

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
        ref.hint ? ` (${ref.hint})` : ""
      }`;
    case "secret":
      // dev/116: the key the code reaches by name — never its value.
      return `Connection key · ${ref.name ?? ""}${ref.host ? ` · ${ref.host}` : ""}`;
    case "user-path":
      return `${ref.value ?? ""} (not checked by Curio)`;
    case "synthetic":
      return "generated in the node, no external source";
    default:
      return ref.value ?? String(ref.kind);
  }
}

/** A landed plan's per-node state (its mirror + the builder session). */
export interface PlanNodeReviewState {
  /** The refs the plan placed. */
  appliedRefs: string[];
  /** dev/71: ref → created|solving|validated|approved|failed. */
  nodeStates?: Record<string, string>;
  /** ref → the change its validated code landed as, and the attachment
   * whose chat holds it (dev/72: the node's own agent). */
  nodeChanges?: Record<string, { changeId: string; attachmentId?: string | null }>;
  /** #662: scenario index → applied|refused. */
  scenarioStates?: Record<string, string>;
}

/** dev/71: what a row's lifecycle state means for its action cluster. */
export const ROW_STATE_CHIP: Record<string, string> = {
  solving: "Validating",
  validated: "Validated ✓",
  approved: "Solved ✓",
  failed: "Failed: Solve retries",
};

export const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The target changed since this was proposed; ask the agent to propose again",
};

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

/** What one Apply click of an install does, per kind: stated on its card. */
export const EFFECT_LINE: Record<string, string> = {
  "project.install":
    "Applying installs only this project template: nothing is imported, attached, run, or published.",
  "dataset.install":
    "Applying installs only this dataset into the project's Data Catalog; no agent is installed.",
  "package.install":
    "Applying opens the package install review (permissions, dependencies, conflicts); nothing installs until you confirm there.",
  "package.draft.apply":
    "Applying installs the exact reviewed artifact and creates its requested nodes; nothing else changes.",
};

/** dev/112: the removals block title of a landed plan — nodes, connections,
 * and the cascade, each only when present. */
export function removalsTitle(nodes: number, edges: number, cascade: number): string {
  const parts: string[] = [];
  if (nodes) parts.push(`${nodes} node${nodes === 1 ? "" : "s"}`);
  if (edges) parts.push(`${edges} connection${edges === 1 ? "" : "s"}`);
  const cascadeNote = cascade
    ? ` (and ${cascade} connected edge${cascade === 1 ? "" : "s"})`
    : "";
  return `Removed ${parts.join(" · ")}${cascadeNote}`;
}

/** How many of a landed plan's removals were dashboard tiles, which left the
 * dashboard; null when none was. */
export function tilesLeftLine(removals: Array<{ pinned?: boolean }>): string | null {
  const tiles = removals.filter((victim) => victim.pinned).length;
  if (!tiles) return null;
  return tiles === 1
    ? "1 of them was a dashboard tile, which left the dashboard."
    : `${tiles} of them were dashboard tiles, which left the dashboard.`;
}

/** A landed plan node's readiness for its row (dev/71): dependencies by name,
 * its lifecycle state, whether Solve may run, and — when not — why. Its
 * connections landed with the plan, so only an upstream plan node that is not
 * solved yet holds it back. */
export function planNodeRowState(
  part: PlanDisplay,
  node: { ref: string },
  planNodeState: PlanNodeReviewState | undefined,
) {
  const planEdges = part.plan!.edges ?? [];
  const nodeStates = planNodeState?.nodeStates ?? {};
  const planRefSet = new Set(part.plan!.nodes.map((n) => n.ref));
  const incoming = planEdges.filter((edge) => edge.to === node.ref);
  const deps = incoming.map((edge) => edge.fromLabel);
  // The plan landed whole: without the attachment's ledger of it (it moved on
  // to another plan), each of its nodes was placed.
  const applied = planNodeState ? planNodeState.appliedRefs.includes(node.ref) : true;
  const state = nodeStates[node.ref] ?? (applied ? "created" : "planned");
  const unsolvedUpstream = incoming.filter(
    (edge) => planRefSet.has(edge.from) && !["validated", "approved"].includes(nodeStates[edge.from] ?? ""),
  );
  const solvable = applied && unsolvedUpstream.length === 0;
  const solveBlocker =
    applied && unsolvedUpstream.length ? `needs '${unsolvedUpstream[0].fromLabel}' solved first` : null;
  // dev/72: the chat that holds the change its validated code landed as.
  const changeHomeId = planNodeState?.nodeChanges?.[node.ref]?.attachmentId ?? null;
  return { deps, applied, state, solvable, solveBlocker, changeHomeId };
}

/** #662: a widget as its row reads it: its name, kind and value. */
function widgetText(widget: { name: string; type: string; default?: unknown; value?: unknown }): string {
  const value = widget.value !== undefined ? widget.value : widget.default;
  return `${widget.name} (${widget.type}${value !== undefined ? `, ${JSON.stringify(value)}` : ""})`;
}

/** A Spatial Join's operation and output, as its row reads them. */
function spatialJoinText(setting: { predicate?: string; output?: string }): string {
  const parts: string[] = [];
  if (setting.predicate !== undefined) parts.push(`operation ${setting.predicate}`);
  if (setting.output !== undefined) parts.push(`output ${setting.output}`);
  return parts.join(", ");
}

/** A setting as its node's own control words it, `<label>: <value>`, each
 * set one in the node's order, joined as the backend's preview joins them. */
function settingText(
  setting: Record<string, string | undefined>,
  labels: Record<string, string>,
  values: Record<string, string> = {},
): string {
  return Object.keys(labels)
    .filter((key) => setting[key] !== undefined)
    .map((key) => `${labels[key]}: ${values[setting[key]!] ?? setting[key]}`)
    .join("; ");
}

/** #662: a planned node's widgets, its scenario, and the node a copy copies;
 * a Spatial Join's operation and output; a Data Pool's modes and a Simple
 * View's image column, in the pool's and the view's own words. */
export function planNodeExtras(part: PlanDisplay, node: { ref: string }): string[] {
  const row = part.plan!.nodes.find((n) => n.ref === node.ref);
  if (!row) return [];
  const lines: string[] = [];
  if (row.scenario) {
    const original = row.copyOf ? part.plan!.nodes.find((n) => n.ref === row.copyOf) : undefined;
    lines.push(`in ${row.scenario}` + (original ? ` · a copy of ${original.title}` : ""));
  }
  if (row.widgets?.length) lines.push(`widgets: ${row.widgets.map(widgetText).join(", ")}`);
  if (row.spatialJoin) lines.push(spatialJoinText(row.spatialJoin));
  if (row.dataPool) {
    lines.push(settingText({ ...row.dataPool }, nodeSettings.dataPool.settings, nodeSettings.dataPool.modes));
  }
  if (row.simpleVis) lines.push(settingText({ ...row.simpleVis }, nodeSettings.simpleVis.settings));
  return lines;
}

/** #662: a planned scenario's nodes, and what a duplicate copies and changes. */
export function planScenarioLine(scenario: {
  nodes: Array<{ label: string }>;
  duplicateOf?: string;
  values?: Record<string, Record<string, unknown>>;
}): string {
  const parts = [scenario.nodes.map((n) => n.label).join(", ")];
  if (scenario.duplicateOf) parts.unshift(`a copy of ${scenario.duplicateOf}`);
  const changed = Object.values(scenario.values ?? {}).flatMap((values) =>
    Object.entries(values).map(([name, value]) => `${name} ${JSON.stringify(value)}`),
  );
  if (changed.length) parts.push(`sets ${changed.join(", ")}`);
  return parts.join(" · ");
}
