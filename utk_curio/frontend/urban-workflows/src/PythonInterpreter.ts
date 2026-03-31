import { BoxType } from "./constants";
import { pyodideExecutor } from "./services/PyodideExecutor";

/**
 * Box types that require the backend sandbox (geospatial / 3D).
 * These will never be routed to Pyodide.
 */
const BACKEND_ONLY_TYPES = new Set([BoxType.VIS_UTK]);

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
        boxType: BoxType,
        nodeId: string,
        workflow_name: string,
        boxExecProv: any
    ) {
        const usePyodide =
            process.env.PYODIDE_ENABLED === 'true' &&
            pyodideExecutor.isLoaded() &&
            !BACKEND_ONLY_TYPES.has(boxType);

        if (usePyodide) {
            this._runWithPyodide(unresolvedUserCode, userCode, input, boxType, nodeId, workflow_name, boxExecProv, callback);
        } else {
            this._runWithBackend(unresolvedUserCode, userCode, input, inputTypes, boxType, nodeId, workflow_name, boxExecProv, callback);
        }
    }

    // ── Pyodide path ──────────────────────────────────────────────────────────

    private async _runWithPyodide(
        unresolvedUserCode: string,
        userCode: string,
        input: any,
        boxType: BoxType,
        nodeId: string,
        workflow_name: string,
        boxExecProv: any,
        callback: any
    ) {
        const startTime = new Date().toISOString();

        try {
            const result = await pyodideExecutor.execute(userCode, input, boxType as string);

            const endTime = new Date().toISOString();

            const typesInput = input ? [input.dataType] : [];
            const typesOutput = result.output && 'dataType' in result.output
                ? [result.output.dataType]
                : ['error'];

            boxExecProv(
                startTime, endTime, workflow_name,
                boxType + '-' + nodeId,
                this._mapTypes(typesInput),
                this._mapTypes(typesOutput),
                unresolvedUserCode
            );

            // Normalize to the same shape the backend returns so callback works unchanged
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

    // ── Backend path (original) ───────────────────────────────────────────────

    private _runWithBackend(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        boxType: BoxType,
        nodeId: string,
        workflow_name: string,
        boxExecProv: any,
        callback: any
    ) {
        let lines = userCode.split("\n");

        let unifiedLines = "";
        for (const line of lines) {
            unifiedLines += "    " + line + "\n";
        }

        const startTime = new Date().toISOString();

        fetch(process.env.BACKEND_URL + "/processPythonCode", {
            method: "POST",
            body: JSON.stringify({
                code: unifiedLines,
                input: input,
                inputTypes: inputTypes,
                boxType: boxType
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        })
            .then((response) => response.json())
            .then((json) => {
                const endTime = new Date().toISOString();

                let typesInput: string[] = [];
                if (input !== "") typesInput = [json.input?.dataType ?? ''];

                let typesOutput: string[] = [];
                if (json.output !== "") {
                    typesOutput = json.stderr !== "" ? ["error"] : [json.output?.dataType ?? ''];
                }

                boxExecProv(
                    startTime,
                    endTime,
                    workflow_name,
                    boxType + "-" + nodeId,
                    this._mapTypes(typesInput),
                    this._mapTypes(typesOutput),
                    unresolvedUserCode
                );

                // fetch(process.env.BACKEND_URL+"/boxExecProv", {
                //     method: "POST",
                //     body: JSON.stringify({
                //         data: {
                //             activityexec_start_time: startTime,
                //             activityexec_end_time: endTime,
                //             workflow_name,
                //             activity_name: boxType+"_"+nodeId,
                //             types_input: mapTypes(typesInput),
                //             types_output: mapTypes(typesOuput),
                //             activity_source_code: userCode
                //         }
                //     }),
                //     headers: {
                //         "Content-type": "application/json; charset=UTF-8",
                //     }
                // }).then((value: any) => {
                //     updateBoxGraph(workflow_name, boxType+"_"+nodeId);
                // })

                callback(json);
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
