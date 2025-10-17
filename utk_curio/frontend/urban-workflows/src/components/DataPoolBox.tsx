import React, { useState, useEffect, useRef } from "react";
import { Handle, Position } from "reactflow";

import CSS from "csstype";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType, ResolutionType, VisInteractionType } from "../constants";

import "./Box.css"
import { BoxContainer } from "./styles";

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
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import BoxEditor from "./editing/BoxEditor";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

import { fetchData, fetchPreviewData } from '../services/api';
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";


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

    const [activeTab, setActiveTab] = useState<string>("0"); // Track the active tab
    const [tabData, setTabData] = useState<any[]>([]); // Store data for each tab

    useEffect(() => {
  const processDataAsync = async () => {
    try {
      // Normalize input wrappers: handle merge outputs
      let wrappers: any[] = [];
      if (data.input && typeof data.input === 'object') {
        if (data.input.dataType === 'outputs' && Array.isArray(data.input.data)) {
          wrappers = data.input.data;
        } else {
          wrappers = [data.input];
        }
      }

      // Fetch each wrapper by filename or path
      const fetched = await Promise.all(
        wrappers.map(async (w) => {
          const fileId = w.filename ?? w.path;
          if (!fileId) return null;
          try {
            return await fetchData(fileId);
          } catch (err) {
            console.error('Fetch failed for', fileId, err);
            return null;
          }
        })
      );

      // Filter out nulls
      const tabd = (fetched.filter((x) => x != null) as any[]);
      setTabData(tabd);

      // Local output (string)
      setOutput({ code: 'success', content: JSON.stringify(tabd, null, 2) });

      // Notify downstream of raw array
      data.outputCallback(data.nodeId, tabd);
    } catch (error) {
      console.error('Error processing data asynchronously:', error);
      setTabData([]);
      setOutput({ code: 'error', content: 'Failed to process data.' });
    }
  };
  processDataAsync();
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
            //data array error - James
            /*let typesInput: string[] = [];


            if (data.input != "") typesInput = data.input.dataType;//getType([data.input]);

            let typesOuput: string[] = [...typesInput];
            */
           let typesInput: string[] = [];
            if (data.input && data.input.dataType) {
            typesInput = Array.isArray(data.input.dataType)
                ? data.input.dataType
                : [data.input.dataType];
            }
            let typesOuput: string[] = [...typesInput];
            //end data array error - James 
            boxExecProv(
                startTime,
                startTime,
                workflowNameRef.current,
                BoxType.DATA_POOL + "-" + data.nodeId,
                mapTypes(typesInput),
                mapTypes(typesOuput),
                ""
            );
        }

        dataInputBypass.current = true;
    }, [data.input]);

    const createTable = (output: any) => {
        let tableData = [];

        if (output && output.dataType === "dataframe") {
            let columns = Object.keys(output.data);
            let dfIndices = Object.keys(output.data[columns[0]]);

            for (let i = 0; i < dfIndices.length; i++) {
                let element: any = {};

                for (const column of columns) {
                    element[column] = output.data[column][dfIndices[i]];
                }

                tableData.push(element);
            }
        } else if (output && output.dataType === "geodataframe" && output.data.features.length > 0) {
            let columns = Object.keys(output.data.features[0].properties);

            for (let i = 0; i < output.data.features.length; i++) {
                let element: any = {};

                for (const column of columns) {
                    element[column] = output.data.features[i].properties[column];
                }

                tableData.push(element);
            }
        }

        return tableData;
    };

    useEffect(() => {
        setOutputTable(createTable(output.content));
    }, [output]);

    useEffect(() => {
        if (output.content != "" && data.interactions != undefined) {
            
            let parsedInput = output.content;//data.input;
            // parsedInput.data = parsedInput.data;

            let interactedIndices: any = []; // between visualizations

            let columns: string[] = [];
            let dfIndices: string[] = [];

            if (parsedInput.dataType == "dataframe") {
                columns = Object.keys(parsedInput.data);
                dfIndices = Object.keys(parsedInput.data[columns[0]]);
            }
            // console.log(data.interactions);
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
                    } else if (details[select].type == VisInteractionType.INTERVAL) {
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
                                let brushBoundaries = details[select].data[brushedColumn];

                                if (brushBoundaries.length > 0 && typeof brushBoundaries[0] == "string") {
                                    // categorial or ordinal variable

                                    if (parsedInput.dataType == "dataframe") {
                                        if (!brushBoundaries.includes(parsedInput.data[brushedColumn][dfIndices[i]])) {
                                            interacted = false;
                                            break;
                                        }
                                    } else if (parsedInput.dataType == "geodataframe") {
                                        if (!brushBoundaries.includes(parsedInput.data.features[i].properties[brushedColumn])) {
                                            interacted = false;
                                            break;
                                        }
                                    }
                                } else if (brushBoundaries.length == 2) {
                                    // numerical interval

                                    let value = -1;

                                    if (parsedInput.dataType == "dataframe") {
                                        value = parsedInput.data[brushedColumn][dfIndices[i]];
                                    } else if (
                                        parsedInput.dataType == "geodataframe"
                                    ) {
                                        value = parsedInput.data.features[i].properties[brushedColumn];
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
                    // console.log(interactedList);
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
                            parsedInput.data.features[i].properties.interacted = "1"; // 1 -> interacted with
                            if (parsedInput.data.features[i].properties.linked != undefined) {
                                for (const index of parsedInput.data.features[i].properties[dfIndices[i]].linked) {
                                    propagationObj.propagation[index] = "1";
                                }
                            }
                        }
                    } else {
                        if (parsedInput.dataType == "dataframe") {
                            parsedInput.data.interacted[dfIndices[i]] = "0"; // 0 -> not interacted with
                            if (parsedInput.data.linked != undefined) {
                                for (const index of parsedInput.data.linked[dfIndices[i]]) {
                                    propagationObj.propagation[index] = "0";
                                }
                            }
                        } else if (parsedInput.dataType == "geodataframe") {
                            parsedInput.data.features[i].properties.interacted = "0";
                            if (parsedInput.data.features[i].properties.linked != undefined) {
                                for (const index of parsedInput.data.features[i].properties.linked) {
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

            // parsedInput.data = JSON.stringify(parsedInput.data);
            // let newOutput = JSON.stringify(parsedInput); // new output after applying interactions
            // parsedInput.data = parsedInput.data;
            let newOutput = parsedInput; // new output after applying interactions

            const clonedOutput = JSON.parse(JSON.stringify(newOutput));
            setOutput({ code: "success", content: clonedOutput });
            data.outputCallback(data.nodeId, clonedOutput);
            // setOutput({ code: "success", content: newOutput });
            // data.outputCallback(data.nodeId, newOutput);

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
        tabData,
        activeTab,
    }: {
        tabData: any[];
        activeTab: string;
    }) => {
        const displayTable = tabData[parseInt(activeTab)] || {};

        const tableData = createTable(displayTable);

        return (
            <div
                className="nowheel"
                style={{ overflowY: "auto", height: "100%" }}
            >
                <TableContainer component={Paper}>
                    <Table aria-label="simple table">
                        {tableData.length > 0 ? (
                            <TableHead>
                                <TableRow>
                                    {Object.keys(tableData[0]).map((column, index) => (
                                        <TableCell
                                            style={{ fontWeight: "bold" }}
                                            key={`cell_header_${index}`}
                                            align="right"
                                        >
                                            {column}
                                        </TableCell>
                                    ))}
                                </TableRow>
                            </TableHead>
                        ) : null}

                        <TableBody>
                            {tableData.slice(0, 100).map((row: any, index: any) => (
                                <TableRow
                                    key={`row_${index}`}
                                    sx={{ "&:last-child td, &:last-child th": { border: 0 } }}
                                >
                                    {Object.keys(row).map((column, columnIndex) => (
                                        <TableCell
                                            key={`cell_${columnIndex}_${index}`}
                                            align="right"
                                        >
                                            {row[column] != undefined && row[column] != null
                                                ? shortenString(row[column].toString())
                                                : "null"}
                                        </TableCell>
                                    ))}
                                </TableRow>
                            ))}
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
                isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
            />
            {/* Data going to the next node (replication of incoming data) */}
            <Handle
                type="source"
                position={Position.Right}
                id="out"
                isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
            />
            {/* Used to connect visualizations. Data flows in both ways */}
            <Handle
                type="source"
                position={Position.Top}
                id="in/out"
                isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
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
                        <Tabs
                            id="data-tabs"
                            activeKey={activeTab}
                            onSelect={(k) => setActiveTab(k || "0")}
                            className="mb-3"
                        >
                            {Array.isArray(tabData) && tabData.length > 0 ? (
                                tabData.map((_, index) => (
                                    <Tab eventKey={index.toString()} title={`Tab ${index + 1}`} key={index}>
                                        <ContentComponent tabData={tabData} activeTab={activeTab} />
                                    </Tab>
                                ))
                            ) : (
                                <Tab eventKey="0" title="No Data">
                                    <div style={{ padding: "10px", textAlign: "center" }}>
                                        No data available.
                                    </div>
                                </Tab>
                            )}
                        </Tabs>
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
                    fullscreen={""}
                />

                <OutputIcon type="1" />
            </BoxContainer>
        </>
    );
}

export default DataPoolBox;