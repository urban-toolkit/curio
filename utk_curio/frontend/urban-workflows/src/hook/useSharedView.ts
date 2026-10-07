import { useCollab } from "../providers/CollaborationProvider";
import { useFlowContext } from "../providers/FlowProvider";

/**
 * Whether the canvas is read-only: another user's dataflow, opened from its
 * link, with real-time collaboration off. With collaboration on, a peer who
 * opens the owner's link edits along with the owner. MainCanvas, the top bar
 * and each node's resize handle read this one rule.
 */
export function useSharedView(): boolean {
    const { viewerMode } = useFlowContext();
    const collab = useCollab();
    return viewerMode === "shared" && !collab.enabled;
}
