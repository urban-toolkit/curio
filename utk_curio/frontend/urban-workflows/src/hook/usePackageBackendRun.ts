/**
 * dev/91 commit 5 — registry-driven dispatch for backend-handler templates.
 *
 * A node whose descriptor carries `backendHandler` Runs through the package
 * backend sandbox route instead of `/processPythonCode` — dispatch is keyed
 * on the DESCRIPTOR (the registry truth), never on another hardcoded
 * template-id literal (the §0 dispatch gap this memo closes).
 *
 * The invocation payload is the node's run context, one stable shape the
 * package-writing prompt's contract documents for handler authors:
 * `{ "content": <the node's editor text>, "input": <upstream JSON or null> }`.
 * The reply's `result` becomes the node's output display; a well-formed
 * `ok: false` envelope or a transport error becomes the node's error surface
 * — never a silent console-only failure (dev/91 §5).
 */
import { useMemo } from "react";

import { invokePackageBackend } from "../services/packages";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import type { NodeTemplateId } from "../registry/types";

export interface BackendRunOutcome {
    ok: boolean;
    /** Pretty-printed result JSON on success; the sanitized error text on failure. */
    content: string;
}

export type PackageBackendRun = (args: {
    content?: string;
    input?: unknown;
    /** The dataflow the run is of, as a play names it (`agentsDataflowId`). */
    dataflowId?: string | null;
}) => Promise<BackendRunOutcome>;

/**
 * The sandbox runner for *nodeType*, or `null` when its template declares no
 * `backendHandler` — callers fall through to the ordinary interpreters.
 */
export function usePackageBackendRun(nodeType: NodeTemplateId): PackageBackendRun | null {
    const descriptor = tryGetNodeDescriptor(nodeType);
    const handler = descriptor?.backendHandler;
    const packageId = descriptor?.package?.packageId;
    const major = descriptor?.package?.major;

    return useMemo(() => {
        if (!handler || !packageId || major === undefined) return null;
        const dirName = `${packageId}@${major}`;
        const run: PackageBackendRun = async ({ content, input, dataflowId }) => {
            try {
                const body = { content: content ?? "", input: input ?? null };
                const res = await (dataflowId
                    ? invokePackageBackend(dirName, handler, body, dataflowId)
                    : invokePackageBackend(dirName, handler, body));
                if (res.reply.ok) {
                    return { ok: true, content: JSON.stringify(res.reply.result, null, 2) };
                }
                return { ok: false, content: `${res.reply.kind}: ${res.reply.error}` };
            } catch (e) {
                return {
                    ok: false,
                    content: e instanceof Error ? e.message : "the backend invocation failed",
                };
            }
        };
        return run;
    }, [handler, packageId, major]);
}
