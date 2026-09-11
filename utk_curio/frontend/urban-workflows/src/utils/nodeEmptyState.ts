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
  | "not-tabular";

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
