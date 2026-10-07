import { useNotebookViewContext } from "../providers/flow/notebookViewContext";
import { graphEditGates } from "../utils/notebookLayout";
import { useSharedView } from "./useSharedView";

/**
 * What this viewer may change in the graph where it is (`graphEditGates`):
 * everything on a canvas it edits; nothing in the notebook view or on a
 * read-only canvas. MainCanvas (connecting, dropping, the Delete key) and a
 * node's Delete node tool read this one rule.
 */
export function useGraphEditGates() {
    const notebook = useNotebookViewContext();
    const sharedView = useSharedView();
    return graphEditGates({ notebookOn: notebook.on, sharedView });
}
