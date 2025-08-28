import { Node, Edge } from 'reactflow';

interface NodeWithPosition extends Node {
  position: { x: number; y: number };
}

const NODE_WIDTH = 200;
// Distance between nodes in the dashboard layout
const DASHBOARD_SPACING = 450;

// Function to apply a dashboard layout to nodes based on their pinned status
// Pinned nodes are arranged in a grid-like structure based on their distances from root nodes
export function applyDashboardLayout(
  nodes: NodeWithPosition[],
  edges: Edge[],
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
      distanceGroups.get(distance)?.forEach(node => {
        updatedNodes.push({ ...node, position: { x: currentX, y: node.position.y } });
      });
    });
  }
  return updatedNodes;
}