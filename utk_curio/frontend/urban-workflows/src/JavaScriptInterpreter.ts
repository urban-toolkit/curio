import { NodeType } from "./constants";
import { formatDate, mapTypes } from "./utils/formatters";
import { getToken } from "./utils/authApi";
import { BACKEND_URL } from "./utils/backendUrl";

export class JavaScriptInterpreter {
    public interpretCode(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        callback: any,
        nodeType: NodeType,
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
        fetch(BACKEND_URL + "/processJavaScriptCode", {
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
                callbackError(error?.message || String(error));
            });
    }
}
