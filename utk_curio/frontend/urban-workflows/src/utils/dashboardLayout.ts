import { Node, Edge } from 'reactflow';

import { NodeType } from '../constants';
import { classifyAutkSpecString } from './autkSpecKind';
import { getUnversionedFlowNodeType } from './flowNodeCanonicalType';

interface NodeWithPosition extends Node {
  position: { x: number; y: number };
}

/**
 * The element a dashboard tile can be dragged by, while its layout is unlocked.
 *
 * React Flow takes a selector; the tile's title band carries the same class
 * without the dot. Restricting the handle means a click inside a chart or a
 * table does not move the tile out from under the pointer.
 */
export const DASHBOARD_TILE_DRAG_HANDLE = '.curio-dashboard-tile-handle';

const NODE_WIDTH = 200;
// Distance between nodes in the dashboard layout
const DASHBOARD_SPACING = 450;
const START_Y = 50;
const V_GAP = 20;
const DEFAULT_NODE_HEIGHT = 350;

// Function to apply a dashboard layout to nodes based on their pinned status
// Pinned nodes are arranged in a grid-like structure based on their distances from root nodes
export function applyDashboardLayout(
  nodes: NodeWithPosition[],
  edges: readonly Edge[],
  dashboardPins: { [key: string]: boolean }
): NodeWithPosition[] {
  // If there are no nodes or no pinned nodes, return the original nodes
  if (!nodes.length || !Object.values(dashboardPins).some(Boolean)) return nodes;

  // The nodes are divided into pinned and unpinned categories to calc the horizontal positions
  const pinnedNodes = nodes.filter(node => dashboardPins[node.id]);
  const unpinnedNodes = nodes.filter(node => !dashboardPins[node.id]);
  const updatedNodes: NodeWithPosition[] = [...unpinnedNodes];

  // If there are no pinned nodes, return the unpinned nodes
  if (pinnedNodes.length > 0) {
    const adjacencyMap = new Map<string, string[]>();
    // Create an adjacency map to track connections between nodes
    nodes.forEach(node => adjacencyMap.set(node.id, []));
    edges.forEach(edge => adjacencyMap.get(edge.source)?.push(edge.target));
    // Find root nodes (nodes that are not targets of any edge) and calculate distances
    const rootNodes = nodes.filter(node => !edges.some(edge => edge.target === node.id) && dashboardPins[node.id]);
    const pinnedDistances = new Map<string, number>();
    // Function to calculate distances from root nodes to pinned nodes
    const calculateDistances = (nodeId: string, distance: number, visited: Set<string>) => {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);
      if (dashboardPins[nodeId] && !pinnedDistances.has(nodeId)) {
        pinnedDistances.set(nodeId, distance);
      }
      const neighbors = adjacencyMap.get(nodeId) || [];
      const nextDistance = dashboardPins[nodeId] ? distance + 1 : distance;
      neighbors.forEach(neighborId => calculateDistances(neighborId, nextDistance, visited));
    };
    // Start calculating distances from each root node
    rootNodes.forEach(rootNode => calculateDistances(rootNode.id, 0, new Set<string>()));
    const distanceGroups = new Map<number, NodeWithPosition[]>();
    pinnedNodes.forEach(node => {
      const distance = pinnedDistances.get(node.id) ?? 0;
      if (!distanceGroups.has(distance)) distanceGroups.set(distance, []);
      distanceGroups.get(distance)?.push(node);
    });
    const baseX = Math.min(...pinnedNodes.map(n => n.position.x));
    Array.from(distanceGroups.keys()).sort((a, b) => a - b).forEach(distance => {
      const currentX = baseX + distance * (NODE_WIDTH + DASHBOARD_SPACING);
      const group = distanceGroups.get(distance) ?? [];
      // Sort column by original Y for consistent ordering
      group.sort((a, b) => (a.position?.y ?? 0) - (b.position?.y ?? 0));
      group.forEach((node, nodeIndex) => {
        // If node has a saved dashboard position, use it; otherwise auto-layout
        if (typeof node.data?.dashboardX === "number") {
          updatedNodes.push({ ...node, position: { x: node.data.dashboardX, y: node.data.dashboardY } });
        } else {
          const nodeH = node.data?.dashboardHeight ?? node.data?.nodeHeight ?? DEFAULT_NODE_HEIGHT;
          const y = START_Y + nodeIndex * (nodeH + V_GAP);
          updatedNodes.push({ ...node, position: { x: currentX, y } });
        }
      });
    });
  }
  return updatedNodes;
}


/**
 * Lay a loaded dataflow out as a dashboard.
 *
 * Pure: it never mutates its arguments, and it is the only place that decides
 * what a dashboard's node list looks like. Three things happen here.
 *
 * ``data.workflowPosition`` is stamped on every node first. ``TrillGenerator``
 * saves that in preference to ``position``, so a save made from the dashboard
 * keeps the canvas coordinates the dataflow was authored with rather than
 * writing tile positions over them.
 *
 * Pinned nodes move to their saved slot (``dashboardX``/``dashboardY``) or, when
 * they have none, to the automatic layout.
 *
 * Unpinned nodes stay MOUNTED and are hidden with ``display: none``. React
 * Flow's own ``hidden`` unmounts the node component, which would break every
 * chain that runs through an unpinned Data Pool or Merge: their behaviour hooks
 * are what re-derive a tile's data from the restored outputs. Edges are hidden
 * the ordinary way, since nothing depends on an edge being rendered.
 */
export function prepareDashboardNodes<N extends Node, E extends Edge>(
  nodes: readonly N[],
  edges: readonly E[],
  dashboardPins: { [key: string]: boolean },
): { nodes: N[]; edges: E[] } {
  const stamped = nodes.map((node) => ({
    ...node,
    data: {
      ...node.data,
      workflowPosition: node.data?.workflowPosition ?? { ...node.position },
    },
  })) as unknown as NodeWithPosition[];

  const laidOut = applyDashboardLayout(stamped, edges, dashboardPins);

  const dashboardNodes = laidOut.map((node) => {
    if (dashboardPins[node.id]) {
      return {
        ...node,
        style: undefined,
        draggable: true,
        selectable: true,
        dragHandle: DASHBOARD_TILE_DRAG_HANDLE,
      };
    }
    return {
      ...node,
      style: { ...(node.style ?? {}), display: 'none' },
      draggable: false,
      selectable: false,
    };
  }) as unknown as N[];

  return {
    nodes: dashboardNodes,
    edges: edges.map((edge) => ({ ...edge, hidden: true })) as E[],
  };
}

/**
 * Node kinds that pass data through rather than produce it.
 *
 * Each of these re-derives what it shows from ``data.input`` whenever that
 * changes, which is what a project load does through ``hydrateRestoredOutputs``.
 * So a dashboard does not need their output saved: it needs the output of
 * whatever feeds them. Everything else makes new data, and that is what has to
 * be in the Data Catalog for a tile to render without a run.
 *
 * An Autark node is only a pass-through when its spec draws (``map``/``plot``);
 * its data and compute forms produce layers, so they are sources.
 */
function isPassThroughNode(node: { type?: string | null; data?: any }): boolean {
  const kind = getUnversionedFlowNodeType(node as any);
  if (
    kind === NodeType.VIS_VEGA ||
    kind === NodeType.VIS_SIMPLE ||
    kind === NodeType.DATA_POOL ||
    kind === NodeType.MERGE_FLOW
  ) {
    return true;
  }
  if (kind === NodeType.AUTK_GRAMMAR) {
    const spec = node.data?.code ?? node.data?.defaultCode;
    return classifyAutkSpecString(spec) === 'render';
  }
  return false;
}

/**
 * The nodes whose outputs a dashboard needs saved.
 *
 * Walking up from each pinned tile, the first node on every path that is not a
 * pass-through is where that tile's data is actually made. Those are the nodes
 * whose outputs go to the Data Catalog, so a reload can hand the tile its data
 * without anyone pressing Run.
 *
 * A pinned node's own output is not in the set. What a tile renders comes from
 * its input; a node that renders its own run output instead (a code node's
 * stdout pane, a Data Summary's table) has nothing a saved dataset could
 * restore, so saving it would add a dataset that nothing reads.
 */
export function dashboardSourceNodeIds(
  nodes: readonly { id: string; type?: string | null; data?: any }[],
  edges: readonly { source?: unknown; target?: unknown }[],
): Set<string> {
  const sources = new Set<string>();
  const pinned = nodes.filter((node) => node.data?.dashboardPinned).map((node) => node.id);
  if (pinned.length === 0) return sources;

  const byId = new Map(nodes.map((node) => [node.id, node]));
  const incoming = new Map<string, string[]>();
  for (const edge of edges) {
    const target = typeof edge?.target === 'string' ? edge.target : null;
    const source = typeof edge?.source === 'string' ? edge.source : null;
    if (!target || !source) continue;
    const list = incoming.get(target);
    if (list) list.push(source);
    else incoming.set(target, [source]);
  }

  // Breadth-first, with a visited set: a cycle (or a diamond) must terminate.
  const queue = [...pinned];
  const visited = new Set<string>();
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (visited.has(id)) continue;
    visited.add(id);
    for (const sourceId of incoming.get(id) ?? []) {
      const node = byId.get(sourceId);
      if (!node) continue;
      if (isPassThroughNode(node)) queue.push(sourceId);
      else sources.add(sourceId);
    }
  }
  return sources;
}
