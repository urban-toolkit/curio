// The views a node's selection tags can read (#662): the dataflow's Vega-Lite
// and Autark nodes, other than the node itself, each with the name it shows.
// An Autark node of several views is offered whole, its newest selection,
// then each of its views with an `id` ("Node · heights").
import { useMemo } from "react";
import { NodeType } from "../constants";
import { useFlowContext } from "../providers/FlowProvider";
import { isVegaLiteNodeType } from "../registry/vegaLiteNodes";
import { documentViews } from "../utils/autkDocumentViews";
import { getUnversionedFlowNodeType } from "../utils/flowNodeCanonicalType";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";

export interface SelectionView {
    /** The view's node. */
    id: string;
    label: string;
    /** The `id` of one view of an Autark node of several views; none, the whole node. */
    view?: string;
    /** That view's table, whose rows the tag's ids are read from. */
    layer?: string;
}

/** The document an Autark node holds now: what its editor floats, else what it loaded with. */
function documentOf(data: any): unknown {
    for (const text of [data?.code, data?.defaultCode, data?.content]) {
        if (typeof text === "string" && text.trim() !== "") return text;
    }
    return undefined;
}

/** The views of an Autark node of several views that have an `id`, each with its table. */
function autkViewsOf(node: { data?: any }): Array<{ view: string; layer?: string }> {
    const views = documentViews(documentOf(node.data)) ?? [];
    if (views.length < 2) return [];
    const seen = new Set<string>();
    return views.flatMap((view) => {
        if (view.id === undefined || seen.has(view.id)) return [];
        seen.add(view.id);
        return [{ view: view.id, ...(view.table ? { layer: view.table } : {}) }];
    });
}

/** A view: a Vega-Lite chart, a package's too (registry/vegaLiteNodes), or an Autark node. */
function isView(kind: string): boolean {
    return isVegaLiteNodeType(kind) || kind === NodeType.AUTK_GRAMMAR;
}

function labelOf(node: { id: string; data?: any }): string {
    try {
        return resolveNodeDisplayLabel(node.data) || node.id;
    } catch {
        return node.id;
    }
}

/** The views among *nodes* other than *nodeId*, in node order, each Autark
 * node of several views followed by its views with an `id`. Two nodes with one
 * name are told apart by the start of their ids. */
export function selectionViewsOf(nodes: readonly { id: string; type?: string | null; data?: any }[], nodeId: string): SelectionView[] {
    const shown = nodes.filter((node) => node.id !== nodeId && isView(getUnversionedFlowNodeType(node)));
    const named = shown.map((node) => ({ node, label: labelOf(node) }));
    return named.flatMap(({ node, label }) => {
        const whole = named.filter((other) => other.label === label).length > 1
            ? `${label} (${node.id.slice(0, 8)})`
            : label;
        const parts = getUnversionedFlowNodeType(node) === NodeType.AUTK_GRAMMAR ? autkViewsOf(node) : [];
        return [
            { id: node.id, label: whole },
            ...parts.map(({ view, layer }) => ({ id: node.id, label: `${whole} · ${view}`, view, ...(layer ? { layer } : {}) })),
        ];
    });
}

export function useSelectionViews(nodeId: string): SelectionView[] {
    const flow = useFlowContext() as { nodes?: any[] };
    const computed = selectionViewsOf(flow?.nodes ?? [], nodeId);
    // The same list keeps its identity, so the panel does not redraw whenever
    // an unrelated node moves.
    const signature = JSON.stringify(computed);
    return useMemo(() => computed, [signature]);
}
