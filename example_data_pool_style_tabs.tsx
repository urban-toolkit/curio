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

function YourNodeWithThreeTabs({ data, isConnectable }) {
    const [templateData, setTemplateData] = useState<Template | any>({});
    const [output, setOutput] = useState<{ code: string; content: string }>({
        code: "",
        content: "",
    }); // stores the output produced by the last update of this box
    const [outputTable, setOutputTable] = useState<any[]>([]); // stores the output in a format used by the table

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

    // This is where you receive results from the backend
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

    const shortenString = (str: string) => {
        if (str.length > 15) {
            return str.slice(0, 15) + "...";
        } else {
            return str;
        }
    };

    const customWidgetsCallback = (div: HTMLElement) => {
        // Add any custom widgets/controls here if needed
        const label = document.createElement("label");
        label.textContent = "Custom Control: ";
        div.appendChild(label);
        
        const select = document.createElement("select");
        select.innerHTML = `
            <option value="option1">Option 1</option>
            <option value="option2">Option 2</option>
            <option value="option3">Option 3</option>
        `;
        div.appendChild(select);
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
                    boxType={BoxType.DATA_POOL} // Replace with your box type
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
                            {/* Tab 1: Summary View */}
                            <Tab eventKey="0" title="Summary">
                                <div style={{ padding: "15px" }}>
                                    <h4>Summary View</h4>
                                    <p>This tab shows a summary of the data.</p>
                                    <ContentComponent tabData={tabData} activeTab={activeTab} />
                                </div>
                            </Tab>
                            
                            {/* Tab 2: Detailed View */}
                            <Tab eventKey="1" title="Details">
                                <div style={{ padding: "15px" }}>
                                    <h4>Detailed View</h4>
                                    <p>This tab shows detailed information.</p>
                                    <ContentComponent tabData={tabData} activeTab={activeTab} />
                                </div>
                            </Tab>
                            
                            {/* Tab 3: Analysis View */}
                            <Tab eventKey="2" title="Analysis">
                                <div style={{ padding: "15px" }}>
                                    <h4>Analysis View</h4>
                                    <p>This tab shows analysis results.</p>
                                    <ContentComponent tabData={tabData} activeTab={activeTab} />
                                </div>
                            </Tab>
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
                    boxType={BoxType.DATA_POOL} // Replace with your box type
                    defaultValue={""}
                    readOnly={false}
                />

                <OutputIcon type="1" />
            </BoxContainer>
        </>
    );
}

export default YourNodeWithThreeTabs; 