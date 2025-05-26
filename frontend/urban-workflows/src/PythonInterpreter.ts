import { BoxType } from "./constants";
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

        const formatDate = (date: Date) => {
            // Get individual date components
            const month = date.toLocaleString("default", { month: "short" });
            const day = date.getDate();
            const year = date.getFullYear();
            const hours = date.getHours();
            const minutes = date.getMinutes();
            const seconds = date.getSeconds();

            // Format the string
            const formattedDate = `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;

            return formattedDate;
        };

        let startTime = formatDate(new Date());

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

                // const getType = (inputs: any[]) => {
                //     let typesInput: string[] = [];

                //     for (const input of inputs) {
                //         let parsedInput = input;

                //         if (typeof input == "string")
                            
                //             parsedInput = JSON.parse(parsedInput);

                //         if (parsedInput.dataType == "outputs") {
                //             typesInput = typesInput.concat(
                //                 getType(parsedInput.data)
                //             );
                //         } else {
                //             typesInput.push(parsedInput.dataType);
                //         }
                //     }

                //     return typesInput;
                // };

                const mapTypes = (typesList: string[]) => {
                    let mapTypes: any = {
                        "DATAFRAME": 0,
                        "GEODATAFRAME": 0,
                        "VALUE": 0,
                        "LIST": 0,
                        "JSON": 0,
                    };

                    for (const typeValue of typesList) {
                        if (
                            typeValue == "int" ||
                            typeValue == "str" ||
                            typeValue == "float" ||
                            typeValue == "bool"
                        ) {
                            mapTypes["VALUE"] = 1;
                        } else if (typeValue == "list") {
                            mapTypes["LIST"] = 1;
                        } else if (typeValue == "dict") {
                            mapTypes["JSON"] = 1;
                        } else if (typeValue == "dataframe") {
                            mapTypes["DATAFRAME"] = 1;
                        } else if (typeValue == "geodataframe") {
                            mapTypes["GEODATAFRAME"] = 1;
                        }
                    }

                    return mapTypes;
                };

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
