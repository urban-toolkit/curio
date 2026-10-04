// What a node or an edge needs to know about the notebook view, in a context of
// its own: it changes only when the layout does, so edges and node bodies do
// not re-render on every flow change.
import { createContext, useContext } from "react";

export interface NotebookViewValue {
    /** The dataflow is showing as notebook cells. */
    on: boolean;
    /** The x of the lane each connection runs along in the bar, by edge id. */
    laneX: ReadonlyMap<string, number>;
    /** Each cell's height, by node id. */
    heights: ReadonlyMap<string, number>;
    /**
     * Scroll the first of these nodes' cells into view, where the canvas would
     * frame them instead; false on the canvas. Here rather than only on the flow
     * context so light components (palette rows, node pills) can reach it.
     */
    reveal: (nodeIds: string[], options?: { ifMoved?: boolean }) => boolean;
}

export const NotebookViewContext = createContext<NotebookViewValue>({
    on: false,
    laneX: new Map(),
    heights: new Map(),
    reveal: () => false,
});

export const useNotebookViewContext = () => useContext(NotebookViewContext);
