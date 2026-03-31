import { NodeType } from "./constants";
import { formatDate, mapTypes } from "./utils/formatters";
import { getToken } from "./utils/authApi";
import { pyodideExecutor } from "./services/PyodideExecutor";

const BACKEND_ONLY_TYPES = new Set([NodeType.VIS_UTK]);

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
        nodeType: NodeType,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any
    ) {
        const usePyodide =
            process.env.PYODIDE_ENABLED === 'true' &&
            pyodideExecutor.isLoaded() &&
            !BACKEND_ONLY_TYPES.has(nodeType);

        if (usePyodide) {
            this._runWithPyodide(unresolvedUserCode, userCode, input, nodeType, nodeId, workflow_name, nodeExecProv, callback);
        } else {
            this._runWithBackend(unresolvedUserCode, userCode, input, inputTypes, nodeType, nodeId, workflow_name, nodeExecProv, callback);
        }
    }

    // ── Pyodide path ──────────────────────────────────────────────────────────

    private async _runWithPyodide(
        unresolvedUserCode: string,
        userCode: string,
        input: any,
        nodeType: NodeType,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any,
        callback: any
    ) {
        const startTime = new Date().toISOString();

        try {
            const result = await pyodideExecutor.execute(userCode, input, nodeType as string);

            const endTime = new Date().toISOString();

            const typesInput = input ? [input.dataType] : [];
            const typesOutput = result.output && 'dataType' in result.output
                ? [result.output.dataType]
                : ['error'];

            nodeExecProv(
                startTime, endTime, workflow_name,
                nodeType + '-' + nodeId,
                this._mapTypes(typesInput),
                this._mapTypes(typesOutput),
                unresolvedUserCode
            );

            callback({
                stdout: result.stdout,
                stderr: result.stderr,
                input: input || '',
                output: result.output,
            });
        } catch (err: any) {
            callback({
                stdout: [],
                stderr: String(err),
                input: input || '',
                output: {},
            });
        }
    }

    // ── Backend path ──────────────────────────────────────────────────────────

    private _runWithBackend(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        nodeType: NodeType,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any,
        callback: any
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

        const _token = getToken();
        fetch(process.env.BACKEND_URL + "/processPythonCode", {
            method: "POST",
            body: JSON.stringify({
                code: unifiedLines,
                input: input,
                inputTypes: inputTypes,
                nodeType: nodeType
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
                if (input !== "") typesInput = [json.input?.dataType ?? ''];

                let typesOutput: string[] = [];
                if (json.output !== "") {
                    typesOutput = json.stderr !== "" ? ["error"] : [json.output?.dataType ?? ''];
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

    // ── Helpers ───────────────────────────────────────────────────────────────

    private _mapTypes(typesList: string[]): Record<string, number> {
        const map: Record<string, number> = {
            DATAFRAME: 0, GEODATAFRAME: 0, VALUE: 0, LIST: 0, JSON: 0,
        };
        for (const t of typesList) {
            if (['int', 'str', 'float', 'bool'].includes(t)) map.VALUE = 1;
            else if (t === 'list') map.LIST = 1;
            else if (t === 'json' || t === 'dict') map.JSON = 1;
            else if (t === 'dataframe') map.DATAFRAME = 1;
            else if (t === 'geodataframe') map.GEODATAFRAME = 1;
        }
        return map;
    }
}
