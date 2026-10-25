import { useFlowContext } from "../providers/FlowProvider";
import { hasIncomingEdge, incomingSourceIds } from "../utils/nodeEmptyState";

/**
 * What a node knows about the edge into it: whether one arrives, and whether
 * the node at its other end ran and failed. The Vega-Lite and Autark nodes ask
 * the same way, the Data Pool's way (#347), so they say the same thing in the
 * same situation. A code node asks it too before it runs (#603), and names the
 * failed node from ``erroredSourceIds``.
 *
 * On a dashboard it also says whether a viewer's run is making what the tiles
 * show (``upstreamRunning``) and why the last one stopped short of them, at a
 * step this browser could not run or with the run refused (``upstreamStopped``,
 * useDashboardRun): a visitor runs no node and opens none, so a tile says that
 * instead, and what is not in yet is on its way (``onDashboard``).
 */
export function useGrammarInputState(nodeId: string): {
  connected: boolean;
  upstreamErrored: boolean;
  erroredSourceIds: string[];
  upstreamRunning: boolean;
  upstreamStopped: string | null;
  onDashboard: boolean;
} {
  const { edges, nodeExecStatus, dashboardOn, serverRunActive, dashboardStopped } = useFlowContext() as {
    edges?: Array<{ source?: unknown; target?: unknown }>;
    nodeExecStatus?: Record<string, string>;
    dashboardOn?: boolean;
    serverRunActive?: boolean;
    dashboardStopped?: string | null;
  };
  const list = edges ?? [];
  const erroredSourceIds = incomingSourceIds(list, nodeId).filter(
    (id) => nodeExecStatus?.[id] === "errored",
  );
  return {
    connected: hasIncomingEdge(list, nodeId),
    upstreamErrored: erroredSourceIds.length > 0,
    erroredSourceIds,
    upstreamRunning: !!dashboardOn && !!serverRunActive,
    upstreamStopped: dashboardOn ? dashboardStopped ?? null : null,
    onDashboard: !!dashboardOn,
  };
}
