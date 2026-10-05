// The views a node's selection tags can read (#662): the dataflow's Vega-Lite
// and Autark nodes, other than the node itself, each with the name it shows.
import { useMemo } from "react";
import { NodeType } from "../constants";
import { useFlowContext } from "../providers/FlowProvider";
import { getUnversionedFlowNodeType } from "../utils/flowNodeCanonicalType";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";

export interface SelectionView {
    id: string;
    label: string;
}

const VIEW_TYPES: readonly string[] = [NodeType.VIS_VEGA, NodeType.AUTK_GRAMMAR];

function labelOf(node: { id: string; data?: any }): string {
    try {
        return resolveNodeDisplayLabel(node.data) || node.id;
    } catch {
        return node.id;
    }
}

/** The views among *nodes* other than *nodeId*, in node order. Two with one
 * name are told apart by the start of their ids. */
export function selectionViewsOf(nodes: readonly { id: string; type?: string | null; data?: any }[], nodeId: string): SelectionView[] {
    const views = nodes
        .filter((node) => node.id !== nodeId && VIEW_TYPES.includes(getUnversionedFlowNodeType(node)))
        .map((node) => ({ id: node.id, label: labelOf(node) }));
    return views.map((view) =>
        views.filter((other) => other.label === view.label).length > 1
            ? { ...view, label: `${view.label} (${view.id.slice(0, 8)})` }
            : view,
    );
}

export function useSelectionViews(nodeId: string): SelectionView[] {
    const flow = useFlowContext() as { nodes?: any[] };
    const computed = selectionViewsOf(flow?.nodes ?? [], nodeId);
    // The same list keeps its identity, so the panel does not redraw whenever
    // an unrelated node moves.
    const signature = JSON.stringify(computed);
    return useMemo(() => computed, [signature]);
}
