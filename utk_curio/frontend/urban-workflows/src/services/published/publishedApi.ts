// Published dashboards (backend `published/`): the owner publishes a dataflow's
// dashboard under a link, and whoever holds the link runs it with their own
// values for its pinned widgets, on the server, as the owner, saving nothing.
import { apiFetch } from "../../utils/authApi";
import { postSseStream } from "../../utils/sseStream";
import type { Run, RunEvent } from "../runs/runsApi";

export type PublishAccess = "link" | "signed-in";

export interface PublishedInput {
    nodeId: string;
    name: string;
    type: string;
    label: string;
    options: Record<string, unknown>;
    value: unknown;
}

export interface Publication {
    projectId: string;
    token: string;
    access: PublishAccess;
    specRevision: number | null;
    publishedAt: string | null;
    inputs: PublishedInput[];
}

/** What a run start answers: the run, and the key that opens it. */
export interface PublishedRunStart {
    runId: string;
    key: string;
    cached: boolean;
}

/** The URL query parameter that carries a published dashboard's link token. */
export const PUBLISH_LINK_PARAM = "run";

const q = (value: string) => encodeURIComponent(value);

export const publishedApi = {
    // ── The owner ────────────────────────────────────────────────────────
    async get(projectId: string): Promise<Publication | null> {
        const body = await apiFetch<{ published: Publication | null }>(`/api/projects/${q(projectId)}/publish`);
        return body.published ?? null;
    },

    async publish(projectId: string, access: PublishAccess): Promise<Publication> {
        const body = await apiFetch<{ published: Publication }>(`/api/projects/${q(projectId)}/publish`, {
            method: "PUT",
            body: JSON.stringify({ access }),
        });
        return body.published;
    },

    unpublish(projectId: string): Promise<void> {
        return apiFetch<void>(`/api/projects/${q(projectId)}/publish`, { method: "DELETE" });
    },

    // ── Whoever holds the link ───────────────────────────────────────────
    /** What the link lets a visitor set. */
    describe(token: string): Promise<{ projectId: string; access: PublishAccess; inputs: PublishedInput[] }> {
        return apiFetch(`/api/published/${q(token)}`);
    },

    startRun(token: string, inputs: Record<string, Record<string, unknown>>): Promise<PublishedRunStart> {
        return apiFetch<PublishedRunStart>(`/api/published/${q(token)}/runs`, {
            method: "POST",
            body: JSON.stringify({ inputs }),
        });
    },

    getRun(runId: string, key: string): Promise<Run> {
        return apiFetch<Run>(`/api/published/runs/${q(runId)}?key=${q(key)}`);
    },

    cancel(runId: string, key: string): Promise<Run> {
        return apiFetch<Run>(`/api/published/runs/${q(runId)}/cancel?key=${q(key)}`, { method: "POST" });
    },

    follow(runId: string, key: string, onEvent: (event: RunEvent) => void, signal?: AbortSignal): Promise<void> {
        return postSseStream(
            `/api/published/runs/${q(runId)}/stream?key=${q(key)}`,
            undefined,
            (event, payload) => {
                if (event === "run") onEvent({ kind: "run", run: payload as unknown as Run });
                else onEvent({ kind: event, ...payload } as RunEvent);
            },
            signal,
            "GET",
        );
    },
};

/** The link token in the page's address (`?run=<token>`), or null. */
export function publishLinkToken(search: string = typeof window === "undefined" ? "" : window.location.search): string | null {
    const token = new URLSearchParams(search).get(PUBLISH_LINK_PARAM);
    return token && token.trim() ? token.trim() : null;
}

/** The address a visitor opens to run the published dashboard. */
export function runLink(dashboardUrl: string, token: string): string {
    return `${dashboardUrl}?${PUBLISH_LINK_PARAM}=${encodeURIComponent(token)}`;
}
