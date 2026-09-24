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

/**
 * The failure text to expose as ``data-curio-node-error``, or undefined.
 *
 * AUTK_GRAMMAR nodes render no output box — `CodeEditor`'s
 * ``[data-curio-node-output]`` is the only one, and the grammar editor has
 * none — so a failed Autark node carried its reason nowhere a test or a
 * support request could read it. The message went to a transient toast and the
 * browser console, which is why an Interaction_AutkMap failure in CI took a
 * month and an Allure attachment to explain (#318).
 *
 * Trimmed to keep the DOM attribute bounded; the console keeps the full text.
 */
export function nodeRunError(output?: ICodeData): string | undefined {
    if (output?.code !== "error") return undefined;
    const content = typeof output.content === "string" ? output.content : String(output.content ?? "");
    const text = content.trim();
    if (text === "") return undefined;
    return text.length > 2000 ? `${text.slice(0, 2000)}…` : text;
}
