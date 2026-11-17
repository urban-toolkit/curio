import { getToken } from "./authApi";
import { backendUrl } from "./backendUrl";
import { requestHeaders } from "./requestHeaders";

// One node run on the backend, as both interpreters send it.
//
// The browser keeps no clock of its own on a run. The backend answers every
// run, and its own timeout is the node's (#863). A clock here would also count
// the run's wait for a turn or a free slot in the sandbox, and give up on a
// node the backend still runs (#888). Runs on the server (useServerRun) leave
// the timeout to the backend the same way.

// The nodes whose run the backend still holds, with how many runs each.
const openRuns = new Map<string, number>();

/** Whether the backend still holds a run of the node: it is waiting for its
 *  turn or running, and will be answered, so it is not stuck. */
export function nodeRunIsOpen(nodeId: string): boolean {
    return (openRuns.get(nodeId) ?? 0) > 0;
}

function countOpenRun(nodeId: string, change: 1 | -1): void {
    const count = (openRuns.get(nodeId) ?? 0) + change;
    if (count > 0) openRuns.set(nodeId, count);
    else openRuns.delete(nodeId);
}

async function readReply(response: Response): Promise<any> {
    let json: any = null;
    try {
        json = await response.json();
    } catch (error: any) {
        throw new Error(
            `Backend returned invalid JSON (${response.status}): ${error?.message || String(error)}`
        );
    }

    if (!response.ok) {
        // Backend now returns clean JSON for sandbox timeouts /
        // connection errors (see _sandbox_call in routes.py).
        if (json?.error === "sandbox_timeout" || json?.error === "sandbox_unreachable") {
            throw new Error(json.message || `Backend execution failed with status ${response.status}`);
        }
        throw new Error(
            json?.stderr || `Backend execution failed with status ${response.status}`
        );
    }

    return json;
}

function describeFailure(error: any, url: string, sentAt: number): string {
    const baseMsg: string = error?.message || String(error);
    if (!/Failed to fetch|NetworkError/i.test(baseMsg)) return baseMsg;
    const elapsedMs = Math.round(performance.now() - sentAt);
    const causeMsg: string | undefined =
        error?.cause && (error.cause.message || String(error.cause));
    let summary =
        `Transport error: ${baseMsg}\n` +
        `URL: ${url}\n` +
        `Elapsed: ${(elapsedMs / 1000).toFixed(1)}s\n` +
        `The backend dropped the connection mid-flight. ` +
        `Likely causes: backend crashed, sandbox unreachable, or the response exceeded a server-side limit. ` +
        `Check the backend log.`;
    if (causeMsg) summary += `\nCause: ${causeMsg}`;
    return summary;
}

/** How long a run waits before it first asks how far its node's downloads
 *  have come, and then between two asks: a run answered sooner asks nothing. */
export const PROGRESS_ASK_MS = 1000;

/** The id a run is posted with, which its asks of its progress name. */
function newProgressId(): string {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Ask the backend, every PROGRESS_ASK_MS while a run waits, how far the
 * downloads on first use of what its node reads have come
 * (`GET <path>/progress?play=<progressId>`), and hand each new message to
 * *show*: an empty one once they are over. Returns what stops the asking.
 */
function askProgress(path: string, progressId: string, show: (message: string) => void): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let shown = "";
    const ask = async () => {
        timer = null;
        try {
            const response = await fetch(
                `${backendUrl()}${path}/progress?play=${encodeURIComponent(progressId)}`,
                { headers: requestHeaders(getToken()) },
            );
            // A backend that answers no such ask is asked no more.
            if (!response.ok) stopped = true;
            const answer = stopped ? null : await response.json();
            const message = typeof answer?.message === "string" ? answer.message : "";
            if (!stopped && message !== shown) {
                shown = message;
                show(message);
            }
        } catch {
            // An ask that did not get through: the next one tries again.
        }
        if (!stopped) timer = setTimeout(ask, PROGRESS_ASK_MS);
    };
    timer = setTimeout(ask, PROGRESS_ASK_MS);
    return () => {
        stopped = true;
        if (timer !== null) clearTimeout(timer);
    };
}

/** POST one node run to *path* and hand its reply to *onReply*, or a sentence
 *  saying why it failed to *onFailure*. With *onProgress*, while the run
 *  waits, each new word of how far its node's downloads on first use have
 *  come is handed to it (an empty one once they are over), until the run is
 *  answered. */
export function runNodeOnBackend(
    path: "/processPythonCode" | "/processJavaScriptCode",
    body: Record<string, unknown>,
    nodeId: string,
    onReply: (json: any) => void,
    onFailure: (message: string) => void,
    onProgress?: (message: string) => void,
): void {
    const url = backendUrl() + path;
    const sentAt = performance.now();
    const progressId = onProgress ? newProgressId() : null;
    let answered = false;
    const stopAsking = progressId && onProgress
        ? askProgress(path, progressId, (message) => { if (!answered) onProgress(message); })
        : () => undefined;
    const settle = () => {
        answered = true;
        stopAsking();
    };
    countOpenRun(nodeId, 1);
    fetch(url, {
        method: "POST",
        body: JSON.stringify(progressId ? { ...body, progressId } : body),
        headers: requestHeaders(getToken(), { "Content-type": "application/json; charset=UTF-8" }),
    })
        .then(readReply)
        .then((json) => {
            settle();
            onReply(json);
        })
        .catch((error: any) => {
            settle();
            onFailure(describeFailure(error, url, sentAt));
        })
        .finally(() => countOpenRun(nodeId, -1));
}
