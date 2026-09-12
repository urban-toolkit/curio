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
}

/** Is anything wired into *nodeId*'s input? */
export function hasIncomingEdge(edges: readonly EdgeLike[] | null | undefined, nodeId: string): boolean {
  if (!edges || !nodeId) return false;
  return edges.some((e) => e?.target === nodeId);
}

export interface NodeEmptyInputs {
  /** True when an edge terminates on this node. */
  connected: boolean;
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
  if (!inputs.hasInput) return "upstream-not-run";
  if (!inputs.tabular) return "not-tabular";
  if (inputs.rowCount <= 0) return "no-rows";
  return null;
}


/** What a *grammar* node (Vega-Lite, and later autk-grammar) has, or lacks. */
export interface GrammarEmptyInputs {
  /** True when an edge terminates on this node. */
  connected: boolean;
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
  if (!inputs.hasInput) return "upstream-not-run";
  if (inputs.inputProblem) return inputs.inputProblem;
  if (!inputs.hasSpec) return "no-spec";
  if (!inputs.hasRun) return "not-run";
  if (inputs.renderedEmpty) return "rendered-empty";
  return null;
}
