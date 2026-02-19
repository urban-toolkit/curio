/**
 * Pure utility functions for immutable node and edge updates.
 *
 * All functions return new arrays without mutating originals.
 * Designed to be used inside React state setters:
 *   setNodes(prev => updateNodeData(prev, nodeId, updater))
 */
import { Node, Edge } from "reactflow";

// ---------------------------------------------------------------------------
// Single-node / single-edge updates
// ---------------------------------------------------------------------------

/**
 * Update a single node's data immutably.
 * The `updater` receives the current data and returns the new data object.
 */
export function updateNodeData(
    nodes: Node[],
    nodeId: string,
    updater: (data: any) => any
): Node[] {
    return nodes.map(node =>
        node.id === nodeId
            ? { ...node, data: updater(node.data) }
            : node
    );
}

// ---------------------------------------------------------------------------
// Bulk updates via id-to-value maps
// ---------------------------------------------------------------------------

/**
 * For each node whose id appears in `idToValue`, set `node.data[field]` to the
 * mapped value. Nodes not in the map are returned unchanged.
 */
export function updateNodesByMap(
    nodes: Node[],
    idToValue: Record<string, any>,
    field: string
): Node[] {
    return nodes.map(node => {
        const value = idToValue[node.id];
        if (value !== undefined) {
            return { ...node, data: { ...node.data, [field]: value } };
        }
        return node;
    });
}

/**
 * Same as updateNodesByMap but for edges.
 */
export function updateEdgesByMap(
    edges: Edge[],
    idToValue: Record<string, any>,
    field: string
): Edge[] {
    return edges.map(edge => {
        const value = idToValue[edge.id];
        if (value !== undefined) {
            return { ...edge, data: { ...edge.data, [field]: value } };
        }
        return edge;
    });
}

// ---------------------------------------------------------------------------
// Trill spec parsing helpers
// ---------------------------------------------------------------------------

/**
 * Extract a map of { nodeId -> fieldValue } from a Trill specification.
 * `field` is the property name on each node object (e.g. 'goal', 'warnings').
 */
export function extractNodeFieldMap(
    trillSpec: any,
    field: string
): Record<string, any> {
    const map: Record<string, any> = {};
    if (trillSpec.dataflow?.nodes) {
        for (const node of trillSpec.dataflow.nodes) {
            if (node[field] !== undefined) {
                map[node.id] = node[field];
            }
        }
    }
    return map;
}

/**
 * Extract keyword maps for both nodes and edges from a Trill specification.
 * Keywords live under `metadata.keywords` (different from top-level fields).
 */
export function extractKeywordMaps(trillSpec: any): {
    nodeToKeywords: Record<string, number[]>;
    edgeToKeywords: Record<string, number[]>;
} {
    const nodeToKeywords: Record<string, number[]> = {};
    const edgeToKeywords: Record<string, number[]> = {};

    if (trillSpec.dataflow) {
        if (trillSpec.dataflow.nodes) {
            for (const node of trillSpec.dataflow.nodes) {
                if (node.metadata?.keywords) {
                    nodeToKeywords[node.id] = [...node.metadata.keywords];
                }
            }
        }
        if (trillSpec.dataflow.edges) {
            for (const edge of trillSpec.dataflow.edges) {
                if (edge.metadata?.keywords) {
                    edgeToKeywords[edge.id] = [...edge.metadata.keywords];
                }
            }
        }
    }

    return { nodeToKeywords, edgeToKeywords };
}
