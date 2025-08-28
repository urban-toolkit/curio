import React, { useState, useEffect, useRef } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../constants";
import "./Box.css"

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";

import TemplateModal from "./TemplateModal";
import DescriptionModal from "./DescriptionModal";
import { useUserContext } from "../providers/UserProvider";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

// Import Bootstrap tabs
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";

function YourNodeWithThreeTabs({ data, isConnectable }) {
    const [output, setOutput] = useState<{ code: string; content: string }>({
        code: "",
        content: "",
    });
    const [templateData, setTemplateData] = useState<Template | any>({});
    const [showDescriptionModal, setDescriptionModal] = useState(false);
    
    // State for managing tabs
    const [activeTab, setActiveTab] = useState<string>("0");
    const [tabData, setTabData] = useState<any[]>([]);

    const { editUserTemplate } = useTemplateContext();
    const { user } = useUserContext();

    // This is where you receive results from the backend
    // Modify this useEffect to process your data and create tab content
    useEffect(() => {
        const processDataAsync = async () => {
            try {
                // Process your input data here
                let processedData = data.input;
                
                // Example: Create three different views of your data
                const tab1Data = {
                    title: "Summary View",
                    content: processedData.summary || "No summary available",
                    type: "summary"
                };
                
                const tab2Data = {
                    title: "Detailed View", 
                    content: processedData.details || "No details available",
                    type: "details"
                };
                
                const tab3Data = {
                    title: "Analysis View",
                    content: processedData.analysis || "No analysis available", 
                    type: "analysis"
                };

                // Set the tab data
                setTabData([tab1Data, tab2Data, tab3Data]);
                
                // Update output
                setOutput({ 
                    code: "success", 
                    content: JSON.stringify([tab1Data, tab2Data, tab3Data], null, 2) 
                });
                
                // Notify downstream
                data.outputCallback(data.nodeId, [tab1Data, tab2Data, tab3Data]);
                
            } catch (error) {
                console.error("Error processing data:", error);
                setTabData([]);
                setOutput({ code: "error", content: "Failed to process data." });
            }
        };

        processDataAsync();
    }, [data.input, data.newPropagation]);

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

    // Custom widgets callback for any additional controls
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

    // Content Component with three tabs
    const ContentComponent = ({
        tabData,
        activeTab,
    }: {
        tabData: any[];
        activeTab: string;
    }) => {
        const currentTabData = tabData[parseInt(activeTab)] || {};

        const renderTabContent = (data: any) => {
            switch (data.type) {
                case "summary":
                    return (
                        <div style={{ padding: "15px" }}>
                            <h4>Summary</h4>
                            <p>{data.content}</p>
                            {/* Add summary-specific components here */}
                        </div>
                    );
                    
                case "details":
                    return (
                        <div style={{ padding: "15px" }}>
                            <h4>Detailed Information</h4>
                            <div style={{ 
                                backgroundColor: "#f8f9fa", 
                                padding: "10px", 
                                borderRadius: "5px",
                                fontFamily: "monospace",
                                fontSize: "12px"
                            }}>
                                {data.content}
                            </div>
                        </div>
                    );
                    
                case "analysis":
                    return (
                        <div style={{ padding: "15px" }}>
                            <h4>Analysis Results</h4>
                            <div style={{ 
                                border: "1px solid #dee2e6", 
                                padding: "10px", 
                                borderRadius: "5px" 
                            }}>
                                {data.content}
                            </div>
                        </div>
                    );
                    
                default:
                    return (
                        <div style={{ padding: "15px", textAlign: "center", color: "#666" }}>
                            No data available for this tab.
                        </div>
                    );
            }
        };

        return (
            <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
                <Tabs
                    id="three-tabs"
                    activeKey={activeTab}
                    onSelect={(k) => setActiveTab(k || "0")}
                    className="mb-3"
                    style={{ flexShrink: 0 }}
                >
                    {Array.isArray(tabData) && tabData.length > 0 ? (
                        tabData.map((tab, index) => (
                            <Tab 
                                eventKey={index.toString()} 
                                title={tab.title} 
                                key={index}
                                style={{ flex: 1, overflow: "auto" }}
                            >
                                <div style={{ 
                                    height: "calc(100vh - 200px)", 
                                    overflowY: "auto",
                                    padding: "10px"
                                }}>
                                    {renderTabContent(tab)}
                                </div>
                            </Tab>
                        ))
                    ) : (
                        <Tab eventKey="0" title="No Data">
                            <div style={{ 
                                padding: "20px", 
                                textAlign: "center", 
                                color: "#666",
                                height: "calc(100vh - 200px)"
                            }}>
                                No data available. Please check your input.
                            </div>
                        </Tab>
                    )}
                </Tabs>
            </div>
        );
    };

    return (
        <>
            {/* Input handle */}
            <Handle
                type="target"
                position={Position.Left}
                id="in"
                isConnectable={isConnectable}
            />
            
            {/* Output handle */}
            <Handle
                type="source"
                position={Position.Right}
                id="out"
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
                    boxType={BoxType.YOUR_BOX_TYPE} // Replace with your box type
                    name={templateData.name}
                    description={templateData.description}
                    accessLevel={templateData.accessLevel}
                    show={showDescriptionModal}
                    handleClose={closeDescription}
                    custom={templateData.custom}
                />

                {/* This is the key part - using BoxEditor with contentComponent */}
                <BoxEditor
                    customWidgetsCallback={customWidgetsCallback}
                    contentComponent={
                        <ContentComponent
                            tabData={tabData}
                            activeTab={activeTab}
                        />
                    }
                    setSendCodeCallback={(_: any) => {}}
                    code={false} // Set to true if you need code editing
                    grammar={false} // Set to true if you need grammar editing
                    widgets={true} // Set to true if you need custom widgets
                    provenance={false} // Set to true if you need provenance
                    setOutputCallback={setOutput}
                    data={data}
                    output={output}
                    boxType={BoxType.YOUR_BOX_TYPE} // Replace with your box type
                    defaultValue={""}
                    readOnly={false}
                />

                <OutputIcon type="1" />
            </BoxContainer>
        </>
    );
}

export default YourNodeWithThreeTabs; 