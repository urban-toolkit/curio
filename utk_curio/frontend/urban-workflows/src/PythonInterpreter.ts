import { BoxType } from "./constants";
import { formatDate, mapTypes } from "./utils/formatters";
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
        boxType: BoxType,
        nodeId: string,
        workflow_name: string,
        boxExecProv: any
    ) {
        let lines = userCode.split("\n");

        let unifiedLines = "";
        for (const line of lines) {
            unifiedLines += "    " + line + "\n";
        }

        let startTime = formatDate(new Date());

        console.log("unifiedLines", unifiedLines);

        fetch(process.env.BACKEND_URL + "/processPythonCode", {
            method: "POST",
            body: JSON.stringify({
                code: unifiedLines,
                input: input, // new
                inputTypes: inputTypes, // new
                boxType: boxType // new
            }),
            headers: {
                "Content-type": "application/json; charset=UTF-8",
            },
        })
            .then((response) => response.json())
            .then((json) => {
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

                boxExecProv(
                    startTime,
                    endTime,
                    workflow_name,
                    boxType + "-" + nodeId,
                    mapTypes(typesInput),
                    mapTypes(typesOuput),
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
}
