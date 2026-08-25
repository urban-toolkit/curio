/**
 * dev/91 — the package backend sandbox's invocation API, in its own module
 * ON PURPOSE: `packagesApi.ts` re-exports the registry bootstrap (and with
 * it the whole node-adapter graph, vega included); the run path must stay a
 * light import for every component that executes nodes.
 */
import { apiFetch } from "../utils/authApi";

/** One sandboxed backend invocation's response — the curio.pkgbackend.v1
 * envelope plus the runtime's invocation metadata. */
export interface PackageBackendInvokeResult {
    reply:
        | { contract: string; ok: true; result: unknown }
        | { contract: string; ok: false; error: string; kind: string };
    invocationId: string;
    durationMs: number;
    limitsApplied: string[];
    entryDigest: string;
}

/** Invoke one declared backend handler of an installed package — the
 * handler runs in a per-invocation sandboxed worker, never in Curio's host
 * process. Non-2xx statuses throw via ``apiFetch`` (404 undeclared, 409
 * digest drift, 413/422 bounds, 503 busy, 507 data-dir cap, 502 worker
 * failure); a well-formed ``ok: false`` reply resolves normally. */
export function invokePackageBackend(
    dirName: string,
    handler: string,
    payload: unknown,
): Promise<PackageBackendInvokeResult> {
    return apiFetch(
        `/api/packages/${encodeURIComponent(dirName)}/backend/${encodeURIComponent(handler)}`,
        { method: "POST", body: JSON.stringify({ payload }) },
    );
}
