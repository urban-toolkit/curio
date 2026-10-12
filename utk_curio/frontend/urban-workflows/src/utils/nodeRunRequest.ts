import { getToken } from "./authApi";
import { backendUrl } from "./backendUrl";

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

/** POST one node run to *path* and hand its reply to *onReply*, or a sentence
 *  saying why it failed to *onFailure*. */
export function runNodeOnBackend(
    path: "/processPythonCode" | "/processJavaScriptCode",
    body: Record<string, unknown>,
    nodeId: string,
    onReply: (json: any) => void,
    onFailure: (message: string) => void,
): void {
    const token = getToken();
    const url = backendUrl() + path;
    const sentAt = performance.now();
    countOpenRun(nodeId, 1);
    fetch(url, {
        method: "POST",
        body: JSON.stringify(body),
        headers: {
            "Content-type": "application/json; charset=UTF-8",
            ...(token ? { "Authorization": `Bearer ${token}` } : {}),
        },
    })
        .then(readReply)
        .then(onReply)
        .catch((error: any) => onFailure(describeFailure(error, url, sentAt)))
        .finally(() => countOpenRun(nodeId, -1));
}
