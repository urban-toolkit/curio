import { useCollab } from "../providers/CollaborationProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { canvasRole } from "../providers/collab/participants";

export { canvasRole, type CanvasRole } from "../providers/collab/participants";

/**
 * Whether the canvas is read-only: a watcher's (`canvasRole`). MainCanvas,
 * the top bar, each node's resize handle and code editors, the Map Editor and
 * every other gate on editing read this one rule.
 */
export function useSharedView(): boolean {
    const { viewerMode } = useFlowContext();
    const collab = useCollab();
    return canvasRole(viewerMode, collab) === "watcher";
}
