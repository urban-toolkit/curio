import { NodeType } from "./constants";
import { NodeKindId } from "./registry/types";
import { formatDate, mapTypes } from "./utils/formatters";
import { getToken } from "./utils/authApi";

export class JavaScriptInterpreter {
    public interpretCode(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        callback: any,
        nodeType: NodeKindId,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any
    ) {
        const callbackError = (message: string) => {
            callback({
                stdout: [],
                stderr: message,
                output: { path: "", dataType: "str" },
            });
        };

        let startTime = formatDate(new Date());

        const _token = getToken();
        const url = process.env.BACKEND_URL + "/processJavaScriptCode";
        const fetchStartedAt = performance.now();
        const CLIENT_TIMEOUT_MS = 180_000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
        fetch(url, {
            method: "POST",
            body: JSON.stringify({
                code: userCode,
                input: input,
                inputTypes: inputTypes,
                nodeType: nodeType,
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
                ...(_token ? { "Authorization": `Bearer ${_token}` } : {}),
            },
            signal: controller.signal,
        })
            .then(async (response) => {
                let json: any = null;
                try {
                    json = await response.json();
                } catch (error: any) {
                    throw new Error(
                        `Backend returned invalid JSON (${response.status}): ${error?.message || String(error)}`
                    );
                }

                if (!response.ok) {
                    throw new Error(
                        json?.stderr || `Backend execution failed with status ${response.status}`
                    );
                }

                return json;
            })
            .then((json) => {
                clearTimeout(timeoutId);
                let endTime = formatDate(new Date());

                let typesInput: string[] = [];
                if (input != "") typesInput = json.input.dataType;

                let typesOutput: string[] = [];
                if (json.output != "") {
                    if (json.stderr != "") {
                        typesOutput = ["error"];
                    } else {
                        typesOutput = json.output.dataType;
                    }
                }

                nodeExecProv(
                    startTime,
                    endTime,
                    workflow_name,
                    nodeType + "-" + nodeId,
                    mapTypes(typesInput),
                    mapTypes(typesOutput),
                    unresolvedUserCode
                );

                callback(json);
            })
            .catch((error: any) => {
                clearTimeout(timeoutId);
                const elapsedMs = Math.round(performance.now() - fetchStartedAt);
                const elapsedStr = `${(elapsedMs / 1000).toFixed(1)}s`;
                const name: string = error?.name || "Error";
                const baseMsg: string = error?.message || String(error);
                const causeMsg: string | undefined =
                    error?.cause && (error.cause.message || String(error.cause));

                let summary: string;
                if (name === "AbortError") {
                    summary =
                        `Execution timed out after ${elapsedStr} ` +
                        `(client timeout = ${CLIENT_TIMEOUT_MS / 1000}s).\n` +
                        `URL: ${url}\n` +
                        `The backend or sandbox is still running but the browser stopped waiting. ` +
                        `Check the backend log for this request.`;
                } else {
                    summary =
                        `${name}: ${baseMsg}\n` +
                        `URL: ${url}\n` +
                        `Elapsed: ${elapsedStr}\n` +
                        `This is a transport error (browser <-> backend), not your autkdb code. ` +
                        `Likely causes: backend crashed mid-response, connection reset, CORS, ` +
                        `or backend not reachable.`;
                    if (causeMsg) summary += `\nCause: ${causeMsg}`;
                }
                callbackError(summary);
            });
    }
}
