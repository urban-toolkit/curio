import { useFlowContext } from "../providers/FlowProvider";
import { hasIncomingEdge, incomingSourceIds } from "../utils/nodeEmptyState";

/**
 * What a grammar node knows about the edge into it: whether one arrives, and
 * whether the node at its other end ran and failed. The Vega-Lite and Autark
 * nodes ask the same way, the Data Pool's way (#347), so they say the same
 * thing in the same situation.
 */
export function useGrammarInputState(nodeId: string): { connected: boolean; upstreamErrored: boolean } {
  const { edges, nodeExecStatus } = useFlowContext() as {
    edges?: Array<{ source?: unknown; target?: unknown }>;
    nodeExecStatus?: Record<string, string>;
  };
  const list = edges ?? [];
  return {
    connected: hasIncomingEdge(list, nodeId),
    upstreamErrored: incomingSourceIds(list, nodeId).some((id) => nodeExecStatus?.[id] === "errored"),
  };
}
