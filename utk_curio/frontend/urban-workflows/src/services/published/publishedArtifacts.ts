// Where the artifacts of a published run are read (`services/api.ts`).
//
// A visitor running a published dashboard is not the account that wrote the
// run's artifacts, and may hold no account at all, so they are read through
// `/api/published/runs/<runId>/...` with the run's key. Only the names the run
// produced go there: the ones its steps output, and the parts a bundle it
// produced lists, as the backend allows them (`published/service.py`). Every
// other name is read as before.

interface PublishedRunAccess {
    runId: string;
    key: string;
    names: Set<string>;
}

let current: PublishedRunAccess | null = null;

const ARTIFACT_KEYS = new Set(["path", "dataset", "filename", "fileName"]);

function collect(value: unknown, into: Set<string>): void {
    if (Array.isArray(value)) {
        value.forEach((item) => collect(item, into));
        return;
    }
    if (value == null || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
        if (ARTIFACT_KEYS.has(key) && typeof item === "string" && item.trim()) into.add(item.trim());
        else collect(item, into);
    }
}

/** The run a visitor started (or follows): its artifacts are read with its key. */
export function setPublishedRun(runId: string, key: string): void {
    if (current?.runId === runId && current.key === key) return;
    current = { runId, key, names: new Set() };
}

/** Names the current run produced: a step's output, or what an artifact it served lists. */
export function notePublishedArtifacts(value: unknown): void {
    if (current) collect(value, current.names);
}

/** Forget the current run: every name is read as before. */
export function clearPublishedRun(): void {
    current = null;
}

export type PublishedArtifactRoute = "get" | "get-preview" | "raster";

/**
 * The path (from the backend's base) a published run's artifact *fileName* is
 * read at, or null when it is not one of the current run's.
 */
export function publishedArtifactPath(route: PublishedArtifactRoute, fileName: string): string | null {
    if (!current || !current.names.has(fileName)) return null;
    const runId = encodeURIComponent(current.runId);
    return `/api/published/runs/${runId}/${route}?key=${encodeURIComponent(current.key)}&fileName=${encodeURIComponent(fileName)}`;
}
