import { useCollab } from "../providers/CollaborationProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { canEditRole, type RoomRole } from "../providers/collab/participants";

/** Who a tab is on the open dataflow. */
export type CanvasRole = "owner" | "editor" | "watcher";

/**
 * The role a tab has on the open dataflow.
 *
 * The owner's tab, and that of a dataflow not saved yet, is the owner's.
 * Another account's dataflow, opened from its link (`viewerMode` "shared"), is
 * edited only with collaboration on, by an account its room says edits it: an
 * editor the owner invited. Before the join answers, after a refusal, and
 * with collaboration off, the tab watches.
 *
 * Saving stays the owner's: a tab saves the dataflow only on `viewerMode`
 * "owner", whatever this says.
 */
export function canvasRole(
    viewerMode: "owner" | "shared" | undefined,
    collab: { enabled: boolean; role?: RoomRole | null },
): CanvasRole {
    if (viewerMode !== "shared") return "owner";
    return collab.enabled && canEditRole(collab.role) ? "editor" : "watcher";
}

/**
 * Whether the canvas is read-only: a watcher's (`canvasRole`). MainCanvas,
 * the top bar, each node's resize handle, the Map Editor and every other
 * gate on editing read this one rule.
 */
export function useSharedView(): boolean {
    const { viewerMode } = useFlowContext();
    const collab = useCollab();
    return canvasRole(viewerMode, collab) === "watcher";
}
