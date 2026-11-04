/**
 * The nodes whose code an editor on this tab is bound to (y-monaco): while one
 * is, the editor applies each change to that code, this tab's typing and
 * everyone else's, and the canvas takes it from the editor. The doc's
 * changes reach the code of every other node through the canvas
 * (`providers/flow/useDataflowDoc.ts`).
 */
import type * as Y from "yjs";

const bound = new WeakMap<Y.Doc, Map<string, number>>();

/** Note that an editor binds *nodeId*'s code in *doc*; the call it returns
 *  takes the note back. */
export function markBound(doc: Y.Doc, nodeId: string): () => void {
    let nodes = bound.get(doc);
    if (!nodes) {
        nodes = new Map();
        bound.set(doc, nodes);
    }
    nodes.set(nodeId, (nodes.get(nodeId) ?? 0) + 1);
    let released = false;
    return () => {
        if (released) return;
        released = true;
        const count = (nodes!.get(nodeId) ?? 1) - 1;
        if (count > 0) nodes!.set(nodeId, count);
        else nodes!.delete(nodeId);
    };
}

/** Whether an editor binds *nodeId*'s code in *doc*. */
export function isBound(doc: Y.Doc, nodeId: string): boolean {
    return (bound.get(doc)?.get(nodeId) ?? 0) > 0;
}
