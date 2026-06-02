import { NodeType } from "./constants";
import { NodeTemplateId } from "./registry/types";
import { formatDate, mapTypes } from "./utils/formatters";
import { getToken } from "./utils/authApi";
// import { pythonCode } from "./pythonWrapper";

export class PythonInterpreter {
    // protected _pythonWrapperCode: string[];

    constructor() {
        // parse and store the python wrapper code
        // this._pythonWrapperCode = pythonCode.split("\n");
    }

    public interpretCode(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        callback: any,
        nodeType: NodeTemplateId,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any,
        dataflowId?: string | null,
    ) {
        const callbackError = (message: string) => {
            callback({
                stdout: [],
                stderr: message,
                output: { path: "", dataType: "str" },
            });
        };

        let lines = userCode.split("\n");

        let unifiedLines = "";
        for (const line of lines) {
            unifiedLines += "    " + line + "\n";
        }

        let startTime = formatDate(new Date());

        console.log("unifiedLines", unifiedLines);

        // Diagnostic: surface what the frontend is actually sending as the
        // node's input. Useful when chasing "arg is None" bugs in package /
        // merge-flow scenarios — the most common cause is `data.input`
        // never being updated by `applyNewOutput` before Run fires.
        // Strip large blobs so the console stays readable.
        try {
            const preview = JSON.stringify(input, (_k, v) =>
                typeof v === 'string' && v.length > 200 ? `${v.slice(0, 200)}…[${v.length} chars]` : v,
            );
            console.log(`[PythonInterpreter] node=${nodeType} id=${nodeId} input=${preview}`);
        } catch {
            console.log(`[PythonInterpreter] node=${nodeType} id=${nodeId} input=<unserializable>`);
        }

        const _token = getToken();
        const url = process.env.BACKEND_URL + "/processPythonCode";
        const fetchStartedAt = performance.now();
        // Mirror the JavaScriptInterpreter: cap the wait so a stuck node fails
        // with a clear "execution timed out" message instead of hanging forever.
        // 600 s matches the backend's SANDBOX_EXEC_TIMEOUT.
        const CLIENT_TIMEOUT_MS = 600_000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
        fetch(url, {
            method: "POST",
            body: JSON.stringify({
                code: unifiedLines,
                input: input, // new
                inputTypes: inputTypes, // new
                nodeType: nodeType, // new
                nodeId: nodeId,
                ...(dataflowId ? { dataflowId } : {}),
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
            })
            .then((json) => {
                clearTimeout(timeoutId);
                let endTime = formatDate(new Date());

                let typesInput: string[] = [];
                // console.log("------------ inputTypes", json.inputTypes)
                // console.log("------------", json)
                if (input != "") typesInput = json.input.dataType;//getType([input]);

                let typesOuput: string[] = [];

                if (json.output != "") {
                    if (json.stderr != "") {
                        typesOuput = ["error"];
                    } else {
                        typesOuput = json.output.dataType;// getType([json.output]);
                    }
                }

                nodeExecProv(
                    startTime,
                    endTime,
                    workflow_name,
                    nodeType + "-" + nodeId,
                    mapTypes(typesInput),
                    mapTypes(typesOuput),
                    unresolvedUserCode
                );

                // fetch(process.env.BACKEND_URL+"/nodeExecProv", {
                //     method: "POST",
                //     body: JSON.stringify({
                //         data: {
                //             activityexec_start_time: startTime,
                //             activityexec_end_time: endTime,
                //             workflow_name,
                //             activity_name: nodeType+"_"+nodeId,
                //             types_input: mapTypes(typesInput),
                //             types_output: mapTypes(typesOuput),
                //             activity_source_code: userCode
                //         }
                //     }),
                //     headers: {
                //         "Content-type": "application/json; charset=UTF-8",
                //     }
                // }).then((value: any) => {
                //     updateBoxGraph(workflow_name, nodeType+"_"+nodeId);
                // })

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
                } else if (/Failed to fetch|NetworkError/i.test(baseMsg)) {
                    summary =
                        `Transport error: ${baseMsg}\n` +
                        `URL: ${url}\n` +
                        `Elapsed: ${elapsedStr}\n` +
                        `The backend dropped the connection mid-flight. ` +
                        `Likely causes: backend crashed, sandbox unreachable, or the response exceeded a server-side limit. ` +
                        `Check the backend log.`;
                    if (causeMsg) summary += `\nCause: ${causeMsg}`;
                } else {
                    summary = baseMsg;
                }
                callbackError(summary);
            });
    }
}
