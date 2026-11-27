/**
 * The review and change cards' pure text and state derivations (memo dev/142,
 * F4: split out of `AgentReviewCard.tsx`): the source block's labels, a landed
 * plan's row for each node (what its row says and offers, from the
 * attachment's ledgers and what runs on the plan now), an install's outcome
 * and effect lines, and a plan's details.
 */
import type { AgentProposalPart, AgentSourceRef } from "../../../../services/agents";

/** What a plan's sections read of its card, a change's: its tool and plan. */
export type PlanDisplay = { tool: string; plan?: AgentProposalPart["plan"] };
import { tryGetNodeDescriptor } from "../../../../registry/nodeRegistry";
import nodeSettings from "../../../../contracts/nodeSettings.json";

/** dev/114 (DEC-072): the Source block's kind headline — how the runtime
 * grounded what the agent's code opens or fetches. */
export const SOURCE_KIND_LABEL: Record<string, string> = {
  catalog: "Data Catalog",
  external: "External source",
  "user-path": "User-provided path",
  "user-values": "User-provided values",
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
    case "user-values":
      // The values the code added to the node's own, each typed in the chat.
      return `${ref.value ?? ""} (typed in the chat)`;
    case "synthetic":
      // Beside another source, the calls that made values up, as the user asked.
      return ref.value
        ? `${ref.value} (made up in the node, as the user asked)`
        : "generated in the node, no external source";
    default:
      return ref.value ?? String(ref.kind);
  }
}

/** A landed plan's per-node state (its mirror + the builder session), with
 * what runs on it now. */
export interface PlanNodeReviewState {
  /** The refs the plan placed. */
  appliedRefs: string[];
  /** dev/71: ref → created|solving|validated|approved|failed. */
  nodeStates?: Record<string, string>;
  /** ref → the change its validated code landed as, and the attachment
   * whose chat holds it (dev/72: the node's own agent). */
  nodeChanges?: Record<string, { changeId: string; attachmentId?: string | null }>;
  /** ref → the node the plan made. */
  nodeIds?: Record<string, string>;
  /** ref → how the code that landed was checked: `ran` in the sandbox,
   *  `valid` against its grammar, or `written`, with no code to run. */
  nodeChecks?: Record<string, string>;
  /** #662: scenario index → applied|refused. */
  scenarioStates?: Record<string, string>;
  /** A Build & validate runs on the plan (`buildRunningOn`): no row's Solve
   * starts, since it would build the same node beside the build. */
  buildRunning?: boolean;
  /** The ref the running build works on, and what it does there now. */
  buildRef?: string | null;
  buildActivity?: string | null;
  /** A Solve of the whole plan runs: no row's Solve starts beside it. */
  batchRunning?: boolean;
  /** The ref whose row's Solve runs on the server (the listing's
   * `validating`), the one a pick goes on with among them: its row reads
   * Building, and no other row's Solve starts over it. */
  solvingRef?: string | null;
  /** node id → its run: the live batch's over the persisted ones. */
  runs?: Record<string, string>;
  /** node id → why it failed: the live batch's reasons, and a build's pause
   *  on it. */
  failures?: Record<string, string>;
  /** node id → a notice that is no failure (a skip, code written that ran
   *  nowhere). */
  notices?: Record<string, string>;
  /** The nodes that wait for the person's pick of their source. */
  waitsForPick?: string[];
}

/** What a row says of a node waiting for its source, by what it waits on. */
export const ROW_WAIT_WORDS: Record<string, string> = {
  "awaiting-source": "Needs a source",
  "awaiting-download": "Downloading its source",
  "awaiting-install": "Needs its dataset installed",
};

/** A built row's tick, by how its code was checked: its name and its tooltip. */
export const ROW_CHECK: Record<string, { name: string; says: string }> = {
  ran: { name: "Solved", says: "Solved: its code ran in the sandbox" },
  valid: { name: "Valid", says: "Valid: its document was checked against its grammar" },
  written: { name: "Written", says: "Written: it has no code to run, and renders in the browser" },
};

/** What a node at work does now, on its row's tooltip. */
const AT_WORK_ROW_WORDS: Record<string, string> = {
  solving: "Solving it",
  generating: "Writing its code",
  verifying: "Running it in the sandbox",
  fixing: "The run failed: fixing it",
};

/** A node's runs that are over, its runs while a Solve works on it, and its
 * ledger states that are built. */
const BUILT_RUN = new Set(["solved", "verified", "written"]);
const AT_WORK_RUN = new Set(["solving", "generating", "verifying", "fixing"]);
const BUILT_STATE = new Set(["validated", "approved"]);

export const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The target changed since this was proposed; ask the agent to propose again",
};

/** What a pending install says on an invited editor's chat, in place of
 * Apply and Dismiss: the dataflow's owner reviews it. */
export const WAITS_FOR_OWNER = "Waits for the dataflow's owner to review it: an install changes their account.";

/** What a pending review of a change (`landsAsAChange`) says in place of
 * Apply: it was saved before agents changed the dataflow directly, so only
 * its Dismiss is left (the server's refusal of its Apply says the same). */
export const MADE_BEFORE_DIRECT_EDITS =
  "Made before agents edited the dataflow directly, so it can no longer be applied: dismiss it and ask the agent again.";

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

/** A node kind as its template names it ("Data Loading"), else its id. */
export function templateLabelOf(nodeType: string): string {
  return tryGetNodeDescriptor(nodeType)?.label || nodeType;
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

/** dev/112: the removals block title of a landed plan: nodes, connections,
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

/** A plan card's title, in Curio's words: "Plan: 3 nodes, 2 connections",
 * and its scenarios when it saves any. */
export function planTitle(part: PlanDisplay): string {
  const plan = part.plan;
  if (!plan) return "Plan";
  const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
  const parts = [count(plan.nodes.length, "node"), count(plan.edgeCount ?? plan.edges?.length ?? 0, "connection")];
  if (plan.scenarios?.length) parts.push(count(plan.scenarios.length, "scenario"));
  return `Plan: ${parts.join(", ")}`;
}

/** "a" or "an" before *word*, by its first letter. */
function article(word: string): string {
  return /^[aeiou]/i.test(word) ? "an" : "a";
}

/** A change card's title, in Curio's words: what the change did, and to the
 * node its header names (*nodeName*, null when the node is not on the canvas):
 * "Replaced the code of CPL branches", "Changed the settings of Pools",
 * "Added a Python Computation node", "Added CPL branches, a Data Loading
 * node", "Plan: 3 nodes, 2 connections". Without its node, a code or a
 * settings change says the change's own summary, which the agents read too. */
export function changeTitle(
  part: PlanDisplay & { kind: string; summary: string; nodeType?: string },
  nodeName: string | null,
): string {
  if (part.kind === "plan" && part.plan) return planTitle(part);
  if (part.kind === "content" && nodeName) return `Replaced the code of ${nodeName}`;
  if (part.kind === "settings" && nodeName) return `Changed the settings of ${nodeName}`;
  if (part.kind === "node") {
    const label = part.nodeType ? tryGetNodeDescriptor(part.nodeType)?.label : undefined;
    if (label) {
      const kind = `${article(label)} ${label} node`;
      return nodeName && nodeName !== label ? `Added ${nodeName}, ${kind}` : `Added ${kind}`;
    }
  }
  return part.summary;
}

/** One source of a change, as its one line names it: a dataset by its title,
 * a URL, a key by its name; null for data made up in the node. */
function sourceName(ref: AgentSourceRef): string | null {
  switch (ref.kind) {
    case "catalog":
      return ref.title ?? ref.datasetId ?? null;
    case "secret":
      return ref.name ?? null;
    case "synthetic":
      return ref.value ?? null;
    default:
      return ref.value ?? null;
  }
}

/** A change's source on one line: "Source: Chicago Neighborhoods, Data
 * Catalog", each source with its kind when it has several. The rest of what
 * the runtime grounded (a format, a dataset's id, a key's host) is the
 * line's tooltip (`sourceRefText`). */
export function sourceLine(source: { kind: string; refs: AgentSourceRef[] }): string {
  const named = source.refs.map((ref) => {
    const kind = SOURCE_KIND_LABEL[ref.kind] ?? ref.kind;
    const name = sourceName(ref);
    return name ? `${name}, ${kind}` : kind;
  });
  if (!named.length) return `Source: ${SOURCE_KIND_LABEL[source.kind] ?? source.kind}`;
  return `${named.length === 1 ? "Source" : "Sources"}: ${named.join("; ")}`;
}

/** What a node's code put out, as its check line says it. */
const OUTPUT_WORDS: Record<string, string> = {
  dataframe: "a DataFrame",
  geodataframe: "a GeoDataFrame",
  int: "a number",
  float: "a number",
  str: "a string",
  bool: "a boolean",
  list: "a list",
  dict: "a dictionary",
  raster: "a raster",
  outputs: "several outputs",
  value: "a value",
};

/** What a round put out, in words: "a GeoDataFrame". */
export function outputWords(dataType: string): string {
  const key = dataType.trim().toLowerCase();
  return OUTPUT_WORDS[key] ?? `${article(key)} ${key}`;
}

/** What a landed plan's row shows of its node. */
export type PlanRowView =
  /** The plan could not place it. */
  | "not-placed"
  /** A build or a Solve works on it now. */
  | "building"
  /** Its code landed: the row's tick. */
  | "done"
  /** Its source waits: for the person's pick, a download, an install. */
  | "pick"
  | "download"
  | "install"
  | "failed"
  /** It waits for a node upstream of it to be built. */
  | "after"
  /** Its Solve can run now. */
  | "solve"
  /** Nothing to say or offer while a build or a Solve runs over the plan. */
  | "none";

/** A landed plan node's row (dev/71): what it shows, whether its Solve may
 * run, and the facts it names. Its connections landed with the plan, so only
 * an upstream plan node not built yet holds it back ("after"). While a build
 * or a Solve runs over the plan no row's Solve starts, and a row the run is
 * not at says nothing of what it waits for: the line says what runs. A loader whose
 * source waits says what for; one that waits for the person's pick goes on
 * by itself once the pick is made, so its row offers no Solve. */
export function planNodeRowState(
  part: PlanDisplay,
  node: { ref: string; nodeType?: string },
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
  const idOf = (ref: string) => planNodeState?.nodeIds?.[ref] ?? null;
  const runOf = (ref: string) => {
    const id = idOf(ref);
    return id ? planNodeState?.runs?.[id] : undefined;
  };
  const builtRef = (ref: string) => BUILT_STATE.has(nodeStates[ref] ?? "") || BUILT_RUN.has(runOf(ref) ?? "");
  const nodeId = idOf(node.ref);
  const run = runOf(node.ref);
  const unsolvedUpstream = incoming.filter((edge) => planRefSet.has(edge.from) && !builtRef(edge.from));
  const buildRunning = Boolean(planNodeState?.buildRunning);
  const batchRunning = Boolean(planNodeState?.batchRunning);
  const solvingRef = planNodeState?.solvingRef ?? null;
  const solving = solvingRef === node.ref;
  const building =
    solving || (buildRunning && planNodeState?.buildRef === node.ref) || AT_WORK_RUN.has(run ?? "");
  const waitsForPick =
    state === "awaiting-source" || Boolean(nodeId && planNodeState?.waitsForPick?.includes(nodeId));
  const view: PlanRowView = !applied
    ? "not-placed"
    : building
      ? "building"
      : builtRef(node.ref)
        ? "done"
        : waitsForPick
          ? "pick"
          : state === "awaiting-download"
            ? "download"
            : state === "awaiting-install"
              ? "install"
              : state === "failed" || run === "failed"
                ? "failed"
                : buildRunning || batchRunning || solvingRef !== null
                  ? "none"
                  : unsolvedUpstream.length
                    ? "after"
                    : "solve";
  // Its Solve, while nothing runs over the plan: a node not built yet, one
  // whose check failed, and a loader whose source was picked and waits.
  const solvable =
    ["solve", "failed", "download", "install"].includes(view) && !buildRunning && !batchRunning && solvingRef === null;
  // How the code that landed was checked: the ledger's word, else the run's,
  // else by its kind: a chart's or a map's document is checked against its
  // grammar, any other code runs in the sandbox.
  const check =
    view !== "done"
      ? null
      : planNodeState?.nodeChecks?.[node.ref] ??
        (run === "written"
          ? "written"
          : run === "verified"
            ? "ran"
            : node.nodeType && tryGetNodeDescriptor(node.nodeType)?.grammarId
              ? "valid"
              : "ran");
  const atWork =
    view === "building"
      ? (planNodeState?.buildRef === node.ref && planNodeState?.buildActivity
          ? sentenceCase(planNodeState.buildActivity)
          : AT_WORK_ROW_WORDS[run ?? ""]) ?? null
      : null;
  // dev/72: the chat that holds the change its code landed as.
  const changeHomeId = planNodeState?.nodeChanges?.[node.ref]?.attachmentId ?? null;
  return {
    deps,
    applied,
    state,
    view,
    solvable,
    solving,
    check,
    atWork,
    afterLabel: unsolvedUpstream[0]?.fromLabel ?? null,
    reason: view === "failed" && nodeId ? planNodeState?.failures?.[nodeId] ?? null : null,
    notice: nodeId ? planNodeState?.notices?.[nodeId] ?? null : null,
    nodeId,
    changeHomeId,
  };
}

/** *text* with its first letter a capital. */
function sentenceCase(text: string): string {
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : text;
}

/** #662: a widget as its row reads it: its name, kind and value. */
function widgetText(widget: { name: string; type: string; default?: unknown; value?: unknown }): string {
  const value = widget.value !== undefined ? widget.value : widget.default;
  return `${widget.name} (${widget.type}${value !== undefined ? `, ${JSON.stringify(value)}` : ""})`;
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

/** #662: a planned node's widgets, a Spatial Join's operation and output
 * among them, its scenario, and the node a copy copies; a Data Pool's modes
 * and a Simple View's image column, in the pool's and the view's own words. */
export function planNodeExtras(part: PlanDisplay, node: { ref: string }): string[] {
  const row = part.plan!.nodes.find((n) => n.ref === node.ref);
  if (!row) return [];
  const lines: string[] = [];
  if (row.scenario) {
    const original = row.copyOf ? part.plan!.nodes.find((n) => n.ref === row.copyOf) : undefined;
    lines.push(`in ${row.scenario}` + (original ? ` · a copy of ${original.title}` : ""));
  }
  if (row.widgets?.length) lines.push(`widgets: ${row.widgets.map(widgetText).join(", ")}`);
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
