import React, { useState, useEffect, useRef } from "react";
import { Handle, Position } from "reactflow";

import CSS from "csstype";

// Bootstrap
import Button from "react-bootstrap/Button";
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType, ResolutionType, VisInteractionType } from "../constants";
import Tab from "react-bootstrap/Tab";

import { BoxContainer } from "./styles";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";

// mui
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Paper from "@mui/material/Paper";
import { IPropagation, useFlowContext } from "../providers/FlowProvider";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { Template } from "../providers/TemplateProvider";
import { useUserContext } from "../providers/UserProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import BoxEditor from "./editing/BoxEditor";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

function DataPoolBox({ data, isConnectable }) {
    const [templateData, setTemplateData] = useState<Template | any>({});
    const [output, setOutput] = useState<{ code: string; content: string }>({
        code: "",
        content: "",
    }); // stores the output produced by the last update of this box
    const [outputTable, setOutputTable] = useState<any[]>([]); // stores the output in a format used by the table
    const [resolutionMode, setResolutionMode] = useState<string>(
        ResolutionType.OVERWRITE
    ); // how interaction conflicts between plots are resolved
    const [plotResolutionMode, setPlotResolutionMode] = useState<string>(
        ResolutionType.OVERWRITE
    ); // how interaction conflicts are solved in the context of one plot

    const [showDescriptionModal, setDescriptionModal] = useState(false);
    const { workflowNameRef } = useFlowContext();
    const { boxExecProv } = useProvenanceContext();

    const dataInputBypass = useRef(false);

    const promptDescription = () => {
        setDescriptionModal(true);
    };

    const closeDescription = () => {
        setDescriptionModal(false);
    };

    const iconStyle: CSS.Properties = {
        fontSize: "1.5em",
        color: "#888787",
    };

    useEffect(() => {
        let newInput = data.input;

        if (newInput != "") {
            // including interacted tag
            let parsedInput = JSON.parse(newInput);

            parsedInput.data = JSON.parse(parsedInput.data);

            if (parsedInput.dataType == "dataframe") {
                let columns = Object.keys(parsedInput.data);
                let dfIndices = Object.keys(parsedInput.data[columns[0]]);

                if (parsedInput.data.interacted == undefined) {
                    parsedInput.data.interacted = {};

                    for (const dfIndex of dfIndices) {
                        // initializing the interacted attribute
                        parsedInput.data.interacted[dfIndex] = "0";
                    }
                }

                if (data.propagation != undefined) {
                    // handling possible propagation of interaction from another pool
                    let propagatedIndices = Object.keys(data.propagation).map(
                        (index: string) => {
                            return parseInt(index);
                        }
                    );

                    let interactedKeys = Object.keys(
                        parsedInput.data.interacted
                    );

                    for (let i = 0; i < interactedKeys.length; i++) {
                        let key = interactedKeys[i];

                        if (propagatedIndices.includes(i)) {
                            parsedInput.data.interacted[key] =
                                data.propagation[i];
                        }
                    }
                }
            } else if (parsedInput.dataType == "geodataframe") {
                for (const feature of parsedInput.data.features) {
                    // initializing the interacted attribute
                    feature.properties.interacted = "0";
                }

                if (data.propagation != undefined) {
                    // handling possible propagation of interaction from another pool
                    let propagatedIndices = Object.keys(data.propagation).map(
                        (index: string) => {
                            return parseInt(index);
                        }
                    );

                    for (let i = 0; i < parsedInput.data.features.length; i++) {
                        if (propagatedIndices.includes(i))
                            parsedInput.data.features[i].properties.interacted =
                                data.propagation[i];
                    }
                }
            }

            parsedInput.data = JSON.stringify(parsedInput.data);
            newInput = JSON.stringify(parsedInput);
        }

        setOutput({ code: "success", content: newInput });
        data.outputCallback(data.nodeId, newInput);
    }, [data.input, data.newPropagation]);

    useEffect(() => {
        if (dataInputBypass.current) {
            const formatDate = (date: Date) => {
                // Get individual date components
                const month = date.toLocaleString("default", {
                    month: "short",
                });
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

            const getType = (inputs: any[]) => {
                let typesInput: string[] = [];

                for (const input of inputs) {
                    let parsedInput = input;

                    if (typeof input == "string")
                        parsedInput = JSON.parse(parsedInput);

                    if (parsedInput.dataType == "outputs") {
                        typesInput = typesInput.concat(
                            getType(parsedInput.data)
                        );
                    } else {
                        typesInput.push(parsedInput.dataType);
                    }
                }

                return typesInput;
            };

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

            if (data.input != "") typesInput = getType([data.input]);

            let typesOuput: string[] = [...typesInput];

            boxExecProv(
                startTime,
                startTime,
                workflowNameRef.current,
                BoxType.DATA_POOL + "_" + data.nodeId,
                mapTypes(typesInput),
                mapTypes(typesOuput),
                ""
            );
        }

        dataInputBypass.current = true;
    }, [data.input]);

    const createTable = (output: string) => {
        let tableData = [];

        if (output != "") {
            let parsedOutput = JSON.parse(output);
            parsedOutput.data = JSON.parse(parsedOutput.data);

            if (parsedOutput.dataType == "dataframe") {
                let columns = Object.keys(parsedOutput.data);
                let dfIndices = Object.keys(parsedOutput.data[columns[0]]);

                for (let i = 0; i < dfIndices.length; i++) {
                    let element: any = {};

                    for (const column of columns) {
                        element[column] =
                            parsedOutput.data[column][dfIndices[i]];
                    }

                    tableData.push(element);
                }
            } else if (
                parsedOutput.dataType == "geodataframe" &&
                parsedOutput.data.features.length > 0
            ) {
                let columns = Object.keys(
                    parsedOutput.data.features[0].properties
                );

                for (let i = 0; i < parsedOutput.data.features.length; i++) {
                    let element: any = {};

                    for (const column of columns) {
                        element[column] =
                            parsedOutput.data.features[i].properties[column];
                    }

                    tableData.push(element);
                }
            }
        }

        return tableData;
    };

    useEffect(() => {
        setOutputTable(createTable(output.content));
    }, [output]);

    useEffect(() => {
        if (output.content != "") {
            let parsedInput = JSON.parse(data.input);
            parsedInput.data = JSON.parse(parsedInput.data);

            let interactedIndices: any = []; // between visualizations

            let columns: string[] = [];
            let dfIndices: string[] = [];

            if (parsedInput.dataType == "dataframe") {
                columns = Object.keys(parsedInput.data);
                dfIndices = Object.keys(parsedInput.data[columns[0]]);
            }

            for (const interaction of data.interactions) {
                let localInteractedIndices: any = [];

                let details = interaction.details;

                let selects = Object.keys(details);

                for (const select of selects) {
                    if (details[select].source == BoxType.VIS_UTK) {
                        // interactions from UTK only affect matching named geodataframes
                        if (parsedInput.data.metadata == undefined) {
                            continue;
                        }

                        if (parsedInput.data.metadata.name == undefined) {
                            continue;
                        }

                        if (parsedInput.data.metadata.name != select) {
                            continue;
                        }
                    }

                    if (details[select].type == VisInteractionType.POINT) {
                        // solve point interaction
                        localInteractedIndices.push({
                            priority: details[select].priority,
                            indices: details[select].data.map(
                                (index: number) => {
                                    return index;
                                }
                            ),
                        });
                    } else if (
                        details[select].type == VisInteractionType.INTERVAL
                    ) {
                        // solve interval (brushing) interaction
                        let brushedColumns = Object.keys(details[select].data);

                        let interactedObj: {
                            priority: number;
                            indices: number[];
                        } = {
                            priority: details[select].priority,
                            indices: [],
                        };

                        let objectsCounter = 0;

                        if (parsedInput.dataType == "dataframe")
                            objectsCounter = dfIndices.length;
                        else if (parsedInput.dataType == "geodataframe")
                            objectsCounter = parsedInput.data.features.length;

                        for (let i = 0; i < objectsCounter; i++) {
                            let interacted = true;

                            for (const brushedColumn of brushedColumns) {
                                let brushBoundaries =
                                    details[select].data[brushedColumn];

                                if (
                                    brushBoundaries.length > 0 &&
                                    typeof brushBoundaries[0] == "string"
                                ) {
                                    // categorial or ordinal variable

                                    if (parsedInput.dataType == "dataframe") {
                                        if (
                                            !brushBoundaries.includes(
                                                parsedInput.data[brushedColumn][
                                                    dfIndices[i]
                                                ]
                                            )
                                        ) {
                                            interacted = false;
                                            break;
                                        }
                                    } else if (
                                        parsedInput.dataType == "geodataframe"
                                    ) {
                                        if (
                                            !brushBoundaries.includes(
                                                parsedInput.data.features[i]
                                                    .properties[brushedColumn]
                                            )
                                        ) {
                                            interacted = false;
                                            break;
                                        }
                                    }
                                } else if (brushBoundaries.length == 2) {
                                    // numerical interval

                                    let value = -1;

                                    if (parsedInput.dataType == "dataframe") {
                                        value =
                                            parsedInput.data[brushedColumn][
                                                dfIndices[i]
                                            ];
                                    } else if (
                                        parsedInput.dataType == "geodataframe"
                                    ) {
                                        value =
                                            parsedInput.data.features[i]
                                                .properties[brushedColumn];
                                    }

                                    if (
                                        value < brushBoundaries[0] ||
                                        value > brushBoundaries[1]
                                    ) {
                                        interacted = false;
                                        break;
                                    }
                                }
                            }

                            if (brushedColumns.length == 0) {
                                interacted = false;
                            }

                            if (interacted) {
                                interactedObj.indices.push(i);
                            }
                        }

                        localInteractedIndices.push(interactedObj);
                    } else if (
                        details[select].type == VisInteractionType.UNDETERMINED
                    ) {
                        localInteractedIndices.push({
                            priority: details[select].priority,
                            indices: [],
                        });
                    }
                }

                let interactedList: number[] = [];

                if (plotResolutionMode == ResolutionType.OVERWRITE) {
                    for (const elem of localInteractedIndices) {
                        // using the interactions of the plot with higher priority
                        if (elem.priority == 1) {
                            interactedList = [...elem.indices];
                        }
                    }
                } else if (plotResolutionMode == ResolutionType.MERGE_AND) {
                    let allArrays = localInteractedIndices.map((elem: any) => {
                        return [...elem.indices];
                    });

                    if (allArrays.length > 0)
                        interactedList = allArrays.reduce(
                            (a: number[], b: number[]) =>
                                a.filter((c) => b.includes(c))
                        ); // index is only include if it was interacted in all plots
                } else if (plotResolutionMode == ResolutionType.MERGE_OR) {
                    let auxSet = new Set();

                    for (const elem of localInteractedIndices) {
                        // using the interactions of the plot with higher priority
                        for (const value of elem.indices) {
                            auxSet.add(value);
                        }
                    }

                    interactedList = Array.from(auxSet) as number[];
                }

                interactedIndices.push({
                    priority: interaction.priority,
                    indices: [...interactedList],
                });
            }

            let interactedList: number[] = [];

            if (resolutionMode == ResolutionType.OVERWRITE) {
                for (const elem of interactedIndices) {
                    // using the interactions of the plot with higher priority
                    if (elem.priority == 1) {
                        interactedList = [...elem.indices];
                    }
                }
            } else if (resolutionMode == ResolutionType.MERGE_AND) {
                let allArrays = interactedIndices.map((elem: any) => {
                    return [...elem.indices];
                });

                if (allArrays.length > 0)
                    interactedList = allArrays.reduce(
                        (a: number[], b: number[]) =>
                            a.filter((c) => b.includes(c))
                    ); // index is only include if it was interacted in all plots
            } else if (resolutionMode == ResolutionType.MERGE_OR) {
                let auxSet = new Set();

                for (const elem of interactedIndices) {
                    // using the interactions of the plot with higher priority
                    for (const value of elem.indices) {
                        auxSet.add(value);
                    }
                }

                interactedList = Array.from(auxSet) as number[];
            }

            parsedInput.data.interacted = {};

            let propagationObj: IPropagation = {
                nodeId: data.nodeId,
                propagation: {},
            };

            let objectsCounter = 0;

            let buildingsLayer = false;

            if (
                parsedInput.data.features != undefined &&
                parsedInput.data.features.length > 0 &&
                parsedInput.data.features[0].properties.building_id != undefined
            )
                buildingsLayer = true;

            if (parsedInput.dataType == "dataframe")
                objectsCounter = dfIndices.length;
            else if (parsedInput.dataType == "geodataframe")
                objectsCounter = parsedInput.data.features.length;

            if (!buildingsLayer) {
                for (let i = 0; i < objectsCounter; i++) {
                    if (interactedList.includes(i)) {
                        if (parsedInput.dataType == "dataframe") {
                            parsedInput.data.interacted[dfIndices[i]] = "1"; // 1 -> interacted with

                            if (parsedInput.data.linked != undefined) {
                                for (const index of parsedInput.data.linked[
                                    dfIndices[i]
                                ]) {
                                    propagationObj.propagation[index] = "1";
                                }
                            }
                        } else if (parsedInput.dataType == "geodataframe") {
                            parsedInput.data.features[i].properties.interacted =
                                "1"; // 1 -> interacted with

                            if (
                                parsedInput.data.features[i].properties
                                    .linked != undefined
                            ) {
                                for (const index of parsedInput.data.features[i]
                                    .properties.linked) {
                                    propagationObj.propagation[index] = "1";
                                }
                            }
                        }
                    } else {
                        if (parsedInput.dataType == "dataframe") {
                            parsedInput.data.interacted[dfIndices[i]] = "0"; // 0 -> not interacted with
                            if (parsedInput.data.linked != undefined) {
                                for (const index of parsedInput.data.linked[
                                    dfIndices[i]
                                ]) {
                                    propagationObj.propagation[index] = "0";
                                }
                            }
                        } else if (parsedInput.dataType == "geodataframe") {
                            parsedInput.data.features[i].properties.interacted =
                                "0"; // 0 -> not interacted with
                            if (
                                parsedInput.data.features[i].properties
                                    .linked != undefined
                            ) {
                                for (const index of parsedInput.data.features[i]
                                    .properties.linked) {
                                    propagationObj.propagation[index] = "0";
                                }
                            }
                        }
                    }
                }
            } else {
                let currentBuildingId = -1;
                let uniqueBuildingIndex = -1;

                for (const feature of parsedInput.data.features) {
                    if (feature.properties.building_id != currentBuildingId) {
                        currentBuildingId = feature.properties.building_id;
                        uniqueBuildingIndex += 1;
                    }

                    if (interactedList.includes(uniqueBuildingIndex)) {
                        feature.properties.interacted = "1"; // 1 -> interacted with
                    } else {
                        feature.properties.interacted = "0"; // 0 -> not interacted with
                    }
                }
            }

            parsedInput.data = JSON.stringify(parsedInput.data);
            let newOutput = JSON.stringify(parsedInput); // new output after applying interactions

            setOutput({ code: "success", content: newOutput });

            data.outputCallback(data.nodeId, newOutput);

            // call callback propagation
            data.propagationCallback(propagationObj);
        }
    }, [data.interactions]);

    useEffect(() => {
        const selectBetween = document.getElementById(
            data.nodeId + "_" + "select_between"
        ) as HTMLElement;

        selectBetween.addEventListener("change", (event) => {
            if (event.target != null) {
                let target = event.target as HTMLOptionElement;
                const selectedOption = target.value;
                setResolutionMode(selectedOption);
            }
        });

        const selectIntra = document.getElementById(
            data.nodeId + "_" + "select_intra"
        ) as HTMLElement;

        selectIntra.addEventListener("change", (event) => {
            if (event.target != null) {
                let target = event.target as HTMLOptionElement;
                const selectedOption = target.value;
                setPlotResolutionMode(selectedOption);
            }
        });
    }, []);

    const shortenString = (str: string) => {
        if (str.length > 15) {
            return str.slice(0, 15) + "...";
        } else {
            return str;
        }
    };

    const customWidgetsCallback = (div: HTMLElement) => {
        const labelBetween = document.createElement("label");
        labelBetween.setAttribute("for", "betweenPlot");
        labelBetween.style.marginRight = "5px";
        labelBetween.textContent = "Conflict between visualizations: ";

        const selectBetween = document.createElement("select");
        selectBetween.setAttribute("name", "betweenPlot");
        selectBetween.setAttribute("id", data.nodeId + "_select_between");

        ["Overwrite", "Merge (AND)", "Merge (OR)"].forEach((optionText) => {
            const option = document.createElement("option");
            option.setAttribute(
                "value",
                optionText.toUpperCase().replace(/\s/g, "_")
            );
            option.textContent = optionText;
            selectBetween.appendChild(option);
        });

        const br = document.createElement("br");

        const labelIntra = document.createElement("label");
        labelIntra.setAttribute("for", "intraPlots");
        labelIntra.style.marginRight = "5px";
        labelIntra.textContent = "Conflict inside visualization: ";

        const selectIntra = document.createElement("select");
        selectIntra.setAttribute("name", "intraPlots");
        selectIntra.setAttribute("id", data.nodeId + "_select_intra");

        ["Overwrite", "Merge (AND)", "Merge (OR)"].forEach((optionText) => {
            const option = document.createElement("option");
            option.setAttribute(
                "value",
                optionText.toUpperCase().replace(/\s/g, "_")
            );
            option.textContent = optionText;
            selectIntra.appendChild(option);
        });

        div.appendChild(labelBetween);
        div.appendChild(selectBetween);
        div.appendChild(br);
        div.appendChild(labelIntra);
        div.appendChild(selectIntra);
    };

    const ContentComponent = ({
        outputTable,
        data,
    }: {
        outputTable: any;
        data: any;
    }) => {
        return (
            <div
                className="nowheel"
                style={{ overflowY: "auto", height: "100%" }}
            >
                <TableContainer component={Paper}>
                    <Table aria-label="simple table">
                        {outputTable.length > 0 ? (
                            <TableHead>
                                <TableRow>
                                    {Object.keys(outputTable[0]).map(
                                        (column, index) => {
                                            return (
                                                <TableCell
                                                    style={{
                                                        fontWeight: "bold",
                                                    }}
                                                    key={
                                                        "cell_header_" +
                                                        index +
                                                        "_" +
                                                        data.nodeId
                                                    }
                                                    align="right"
                                                >
                                                    {column}
                                                </TableCell>
                                            );
                                        }
                                    )}
                                </TableRow>
                            </TableHead>
                        ) : null}

                        <TableBody>
                            {outputTable
                                .slice(0, 100)
                                .map((row: any, index: any) => {
                                    return (
                                        <TableRow
                                            key={"row_" + index + data.nodeId}
                                            sx={{
                                                "&:last-child td, &:last-child th":
                                                    { border: 0 },
                                            }}
                                        >
                                            {Object.keys(row).map(
                                                (column, columnIndex) => {
                                                    return (
                                                        <TableCell
                                                            key={
                                                                "cell_" +
                                                                columnIndex +
                                                                "_" +
                                                                index +
                                                                "_" +
                                                                data.nodeId
                                                            }
                                                            align="right"
                                                        >
                                                            {row[column] !=
                                                                undefined &&
                                                            row[column] != null
                                                                ? shortenString(
                                                                      row[
                                                                          column
                                                                      ].toString()
                                                                  )
                                                                : "null"}
                                                        </TableCell>
                                                    );
                                                }
                                            )}
                                        </TableRow>
                                    );
                                })}
                        </TableBody>
                    </Table>
                </TableContainer>
            </div>
        );
    };

    return (
        <>
            {/* Incoming data that will overwrite anything that is inside the pool */}
            <Handle
                type="target"
                position={Position.Left}
                id="in"
                isConnectable={isConnectable}
            />
            {/* Data going to the next node (replication of incoming data) */}
            <Handle
                type="source"
                position={Position.Right}
                id="out"
                isConnectable={isConnectable}
            />
            {/* Used to connect visualizations. Data flows in both ways */}
            <Handle
                type="source"
                position={Position.Top}
                id="in/out"
                isConnectable={isConnectable}
            />
            <BoxContainer
                nodeId={data.nodeId}
                data={data}
                templateData={templateData}
                setOutputCallback={setOutput}
                promptDescription={promptDescription}
            >
                <InputIcon type="1" />

                <DescriptionModal
                    nodeId={data.nodeId}
                    boxType={BoxType.DATA_POOL}
                    name={templateData.name}
                    description={templateData.description}
                    accessLevel={templateData.accessLevel}
                    show={showDescriptionModal}
                    handleClose={closeDescription}
                    custom={templateData.custom}
                />

                <BoxEditor
                    customWidgetsCallback={customWidgetsCallback}
                    contentComponent={
                        <ContentComponent
                            outputTable={outputTable}
                            data={data}
                        />
                    }
                    setSendCodeCallback={(_: any) => {}}
                    code={false}
                    grammar={false}
                    widgets={true}
                    provenance={false}
                    setOutputCallback={setOutput}
                    data={data}
                    output={output}
                    boxType={BoxType.DATA_POOL}
                    defaultValue={""}
                    readOnly={false}
                />

                <OutputIcon type="1" />
            </BoxContainer>
        </>
    );
}

export default DataPoolBox;
