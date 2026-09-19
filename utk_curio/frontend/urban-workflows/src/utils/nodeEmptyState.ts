/**
 * Why a node body has nothing to show, so it can say so.
 *
 * "Data Pool and Simple View render as an empty area when they have nothing to
 * display... an unconnected or not-yet-run node looks the same as a broken one"
 * (#224). The fix is not one message but four, because the four states need
 * different things from the user: connect something, run the upstream node,
 * widen the query, or accept that this payload has no table in it.
 *
 * The reason is derived rather than stored, so it cannot drift from what the
 * node actually has.
 */

export type NodeEmptyReason =
  /** Nothing is wired into this node's input. */
  | "disconnected"
  /** Wired, but whatever feeds it has not produced an output yet. */
  | "upstream-not-run"
  /** Wired, and the node feeding it ran and failed. */
  | "upstream-errored"
  /** Ran and produced a table with no rows in it. */
  | "no-rows"
  /** Ran and produced something this node cannot render as a table. */
  | "not-tabular"
  /** Connected and fed, but no spec has been written yet. */
  | "no-spec"
  /** A spec is written, but the node has not been run. */
  | "not-run"
  /** The spec compiled and ran, but drew nothing. */
  | "rendered-empty"
  /** The input arrived, but this node cannot chart that kind of payload. */
  | "input-type-rejected"
  /** A geoshape spec, but the data has no geometry column to draw. */
  | "geometry-unresolved"
  /** Several geometry columns and no way to tell which one is meant. */
  | "geometry-ambiguous";

export interface NodeEmptyCopy {
  /** The state, in the user's terms. */
  title: string;
  /** What to do about it. Empty when there is nothing for the user to do. */
  hint: string;
}

/**
 * Deliberately plain. These appear inside a node body a few hundred pixels
 * wide, so each is one short line: naming the state and naming the next action.
 */
export const NODE_EMPTY_COPY: Record<NodeEmptyReason, NodeEmptyCopy> = {
  disconnected: {
    title: "No data yet",
    hint: "Connect a node to this one's input.",
  },
  "upstream-not-run": {
    title: "No data yet",
    hint: "Run the node feeding this one.",
  },
  // Without this, a failed upstream node read as "upstream-not-run" - telling
  // the user to run the node they had just run and watched fail (#347).
  "upstream-errored": {
    title: "No data yet",
    hint: "The node feeding this one failed. Open it to see the error.",
  },
  "no-rows": {
    title: "No rows to show",
    hint: "The input ran, but came back empty.",
  },
  "not-tabular": {
    title: "Nothing to display",
    hint: "This input is not tabular data.",
  },
  // The grammar states below are reported by a chart node rather than a table.
  "no-spec": {
    title: "No spec yet",
    hint: "Write a Vega-Lite spec, or connect an input to generate one.",
  },
  "not-run": {
    title: "Not drawn yet",
    hint: "Press play to draw this spec.",
  },
  "rendered-empty": {
    title: "Nothing was drawn",
    hint: "The spec ran, but produced no marks.",
  },
  // They are persistent node-body copy on purpose: these used to be toasts,
  // which decay after a few seconds and leave exactly the unexplained blank
  // node #224 was filed about.
  "input-type-rejected": {
    title: "Nothing to display",
    hint: "This chart cannot read that kind of input.",
  },
  "geometry-unresolved": {
    title: "No geometry to draw",
    hint: 'This spec draws "geoshape", but the data has no geometry column.',
  },
  "geometry-ambiguous": {
    title: "Several geometry columns",
    hint: 'Add "shape": {"field": "<name>", "type": "geojson"} to pick one.',
  },
};

/** Duck-typed so this module needs no ``reactflow`` import (see mergeFlowUtils). */
interface EdgeLike {
  target?: unknown;
  source?: unknown;
}

/** Is anything wired into *nodeId*'s input? */
export function hasIncomingEdge(edges: readonly EdgeLike[] | null | undefined, nodeId: string): boolean {
  if (!edges || !nodeId) return false;
  return edges.some((e) => e?.target === nodeId);
}

/** The ids of the nodes feeding *nodeId*, so their state can be asked about. */
export function incomingSourceIds(
  edges: readonly EdgeLike[] | null | undefined,
  nodeId: string,
): string[] {
  if (!edges || !nodeId) return [];
  const ids = new Set<string>();
  for (const edge of edges) {
    if (edge?.target !== nodeId) continue;
    if (typeof edge?.source === "string" && edge.source) ids.add(edge.source);
  }
  return Array.from(ids);
}

/** Payload kinds a node can put in a table. */
const TABULAR_DATA_TYPES = new Set(["dataframe", "geodataframe"]);

/**
 * Is *input* a payload that was meant to become a table?
 *
 * Asked of the PAYLOAD rather than of the rendered row count, which is the
 * #347 correction. ``useTableData.processDataAsync`` drops dataframe and
 * geodataframe layers with zero rows before they ever reach ``tabData``, so a
 * node that legitimately ran and returned an empty table arrives at the empty
 * branch looking exactly like a payload with no table in it. Deriving from the
 * declared ``dataType`` keeps "ran and came back empty" distinguishable from
 * "this is not tabular at all".
 */
export function isTabularPayload(input: unknown): boolean {
  if (!input || typeof input !== "object") return false;
  const payload = input as { dataType?: unknown; data?: unknown };
  if (payload.dataType === "outputs") {
    // A multi-output envelope is tabular when any layer in it is.
    return Array.isArray(payload.data) && payload.data.some(isTabularPayload);
  }
  return typeof payload.dataType === "string" && TABULAR_DATA_TYPES.has(payload.dataType);
}

export interface NodeEmptyInputs {
  /** True when an edge terminates on this node. */
  connected: boolean;
  /** True when a node feeding this one ran and failed. */
  upstreamErrored?: boolean;
  /** True once an input payload has actually arrived. */
  hasInput: boolean;
  /** True when the payload is a kind this node can tabulate. */
  tabular: boolean;
  /** Row count of the rendered table, when there is one. */
  rowCount: number;
}

/**
 * Which of the four states a node is in, or ``null`` when it has data to show.
 *
 * Order matters and encodes precedence: an unconnected node is unconnected
 * whether or not it also has stale rows lying around, so connectivity is asked
 * first and the more specific complaints only apply once the earlier ones pass.
 */
export function resolveNodeEmptyReason(inputs: NodeEmptyInputs): NodeEmptyReason | null {
  if (!inputs.connected) return "disconnected";
  // Above hasInput on purpose: a failed upstream never calls outputCallback, so
  // hasInput stays false and the node would otherwise advise running a node the
  // user just watched fail (#347). Above it also covers the rarer case where a
  // stale input from an earlier successful run is still sitting there.
  if (inputs.upstreamErrored) return "upstream-errored";
  if (!inputs.hasInput) return "upstream-not-run";
  if (!inputs.tabular) return "not-tabular";
  if (inputs.rowCount <= 0) return "no-rows";
  return null;
}


/** What a *grammar* node (Vega-Lite, and later autk-grammar) has, or lacks. */
export interface GrammarEmptyInputs {
  /** True when an edge terminates on this node. */
  connected: boolean;
  /** True when a node feeding this one ran and failed. */
  upstreamErrored?: boolean;
  /** True once an input payload has actually arrived. */
  hasInput: boolean;
  /** True when the editor holds something to compile. */
  hasSpec: boolean;
  /** True once a compile has been attempted. */
  hasRun: boolean;
  /** Set when preparing the input failed in a specific, nameable way. */
  inputProblem?: NodeEmptyReason | null;
  /** True when a compile succeeded but produced no marks. */
  renderedEmpty?: boolean;
}

/**
 * Which state a grammar node is in, or ``null`` when it has a chart to show.
 *
 * A sibling of ``resolveNodeEmptyReason`` rather than an extension of it. The
 * two take genuinely different inputs -- a chart has no notion of rows or of
 * being "tabular", and a table has no notion of a spec -- and folding them into
 * one function would mean a union of unrelated fields where half are always
 * undefined. They share the copy table and the component, which is where
 * consistency actually matters to the user.
 *
 * Order encodes precedence, most fundamental first: there is no point telling
 * someone their spec drew nothing when the real problem is that nothing is
 * connected. The input problem is checked before the spec, because an input
 * this node cannot read is a fact about the data that no spec will fix.
 */
export function resolveGrammarEmptyReason(
  inputs: GrammarEmptyInputs,
): NodeEmptyReason | null {
  if (!inputs.connected) return "disconnected";
  if (inputs.upstreamErrored) return "upstream-errored";  // see the note above
  if (!inputs.hasInput) return "upstream-not-run";
  if (inputs.inputProblem) return inputs.inputProblem;
  if (!inputs.hasSpec) return "no-spec";
  if (!inputs.hasRun) return "not-run";
  if (inputs.renderedEmpty) return "rendered-empty";
  return null;
}
