import { ICodeData } from "../types/nodeTypes";

/** The four values a node's ``data-curio-node-status`` attribute can take. */
export type NodeRunStatus = "idle" | "running" | "done" | "error";

/**
 * Map a node's latest output onto a run status.
 *
 * The node header already switches on these same ``output.code`` values to
 * render "Done" / a spinner / "Error", but that rendering is a styled ``span``
 * matched by text, which makes every assertion about a run depend on copy. This
 * exposes the same state as a stable attribute instead.
 *
 * "idle" covers both a node that has never run (``output`` undefined) and one
 * whose output carries a code we do not model, so the attribute is always
 * present and callers never have to handle a missing value.
 */
export function nodeRunStatus(output?: ICodeData): NodeRunStatus {
    switch (output?.code) {
        case "success":
            return "done";
        case "exec":
            return "running";
        case "error":
            return "error";
        default:
            return "idle";
    }
}
