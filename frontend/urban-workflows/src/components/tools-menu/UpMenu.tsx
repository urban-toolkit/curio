import React, { useState } from "react";
import CSS from "csstype";
import FileUpload from "./FileUpload";
import { useFlowContext } from "../../providers/FlowProvider";
import { useCode } from "../../hook/useCode";
import { TrillGenerator } from "../../TrillGenerator";
import TrillProvenanceWindow from "./TrillProvenanceWindow";
// import { useLLMContext } from "../../providers/LLMProvider";
// import { LLMEvents } from "../../constants";

export function UpMenu({ setDashBoardMode, setDashboardOn, dashboardOn }: { setDashBoardMode: (mode: boolean) => void; setDashboardOn: (mode: boolean) => void; dashboardOn: boolean }) {
    const [isEditing, setIsEditing] = useState(false);
    const [fileMenuOpen, setFileMenuOpen] = useState(false);
    const [trillProvenanceOpen, setTrillProvenanceOpen] = useState(false);
    // const { llmEvents } = useLLMContext();

    // const { workflowGoal } = useFlowContext();
    const { nodes, edges, workflowNameRef, setWorkflowName } = useFlowContext();
    const { loadTrill } = useCode();

    const closeTrillProvenanceModal = () => {
        setTrillProvenanceOpen(false);
    }

    const openTrillProvenanceModal = () => {
        setTrillProvenanceOpen(true);
    }
    
    const handleNameChange = (e: any) => {
        setWorkflowName(e.target.value);
    };

    const handleNameBlur = () => {
        setIsEditing(false);
    };

    const handleKeyPress = (e: any) => {
        if (e.key === "Enter") {
            setIsEditing(false);
        }
    };

    const exportTrill = (e:any) => {
        let trill_spec = TrillGenerator.generateTrill(nodes, edges, workflowNameRef.current);
        
        const jsonString = JSON.stringify(trill_spec, null, 2);

        const blob = new Blob([jsonString], { type: 'application/json' });

        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = workflowNameRef.current+'.json';

        document.body.appendChild(link);

        link.click();

        document.body.removeChild(link);
    }

    const handleFileUpload = (e:any) => {
        const file = e.target.files[0]; // Get the selected file

        if (file && file.type === 'application/json') {
            const reader = new FileReader();
    
            reader.onload = (e:any) => {
                try {
                    const jsonContent = JSON.parse(e.target.result);

                    console.log('Uploaded JSON content:', jsonContent);
                    loadTrill(jsonContent);
                } catch (err) {
                    console.error('Invalid JSON file:', err);
                }
            };
    
            reader.onerror = (e:any) => {
                console.error('Error reading file:', e.target.error);
            };
    
            reader.readAsText(file);
        } else {
            console.error('Please select a valid .json file.');
        }
    }

    const loadTrillFile = (e:any) => {
        const fileInput = document.getElementById('loadTrill') as HTMLElement;
        fileInput.click();
    }

    return (
        <>
            {/* Top Menu Bar */}
            <div className="nowheel nodrag" style={{...menuBar}}>
                {/* <button style={button}>Back to Projects</button> */}
                <div style={dropdownWrapper}>
                    <button
                        style={button}
                        onClick={() => setFileMenuOpen((prev) => !prev)}
                    >
                        File
                    </button>
                    {fileMenuOpen && (
                        <div style={dropdownMenu}>
                            {/* <button style={dropdownItem}>New Workflow</button> */}
                            <button style={dropdownItem} onClick={exportTrill}>Export Specification</button>
                            <div>
                                <button style={dropdownItem} onClick={loadTrillFile}>Load Specification</button>
                                <input type="file" accept=".json" id="loadTrill" style={{ display: 'none' }} onChange={handleFileUpload}/>
                            </div>
                        </div>
                    )}
                </div>
                <FileUpload style={button} />
                <button style={{...button, ...(dashboardOn ? {background: "repeating-linear-gradient(-45deg, transparent 0px, transparent 8px,rgb(226, 45, 124) 8px, rgb(226, 45, 124) 12px)"} : {background: "transparent"})}} onClick={() => {setDashBoardMode(!dashboardOn); setDashboardOn(!dashboardOn);}}>Dashboard Mode</button>
                <button style={{...button}} onClick={openTrillProvenanceModal}>Provenance</button>
            </div>
            {/* Editable Workflow Name */}
            <div style={{...workflowNameContainer}}>
                {isEditing ? (
                    <input
                        type="text"
                        value={workflowNameRef.current}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyPress={handleKeyPress}
                        autoFocus
                        style={input}
                    />
                ) : (
                    <h1
                        style={workflowNameStyle}
                        onClick={() => setIsEditing(true)}
                    >
                        {workflowNameRef.current}
                    </h1>
                )}
            </div>
            {/* Trill Provenance Modal */}
            <TrillProvenanceWindow 
                open={trillProvenanceOpen}
                closeModal={closeTrillProvenanceModal}
                workflowName={workflowNameRef.current}
            />
        </>

    );
}

const menuBar: CSS.Properties = {
    position: "fixed",
    width: "100%",
    top: 0,
    display: "flex",
    alignItems: "center",
    background: "linear-gradient(to bottom, #23c686, #1ea872)",
    height: "65px",
    padding: "10px",
    fontFamily: "Rubik",
    zIndex: 100,
};

const button: CSS.Properties = {
    margin: "0 10px",
    padding: "6px 10px",
    cursor: "pointer",
    fontWeight: "bold",
    backgroundColor: "transparent",
    color: "#fbfcf6",
    border: "2px solid #fbfcf6",
    borderRadius: "4px",
};

const dropdownMenu: CSS.Properties = {
    position: "absolute",
    top: "100%",
    left: "0",
    backgroundColor: "#fff",
    border: "1px solid #ccc",
    boxShadow: "0 2px 5px rgba(0, 0, 0, 0.2)",
    zIndex: 100,
};

const dropdownItem: CSS.Properties = {
    display: "block",
    padding: "8px 12px",
    width: "200px",
    textAlign: "left",
    cursor: "pointer",
    backgroundColor: "#fff",
    border: "none",
    borderBottom: "1px solid #eee",
};

const workflowNameContainer: CSS.Properties = {
    marginTop: "20px",
    textAlign: "center",
    zIndex: 80,
    top: "60px",
    left: "50px",
    position: "fixed",
};

const workflowNameStyle: CSS.Properties = {
    fontSize: "24px",
    cursor: "pointer",
};

const input: CSS.Properties = {
    fontSize: "24px",
    textAlign: "center",
    border: "1px solid #ccc",
    borderRadius: "4px",
    padding: "5px",
};

const dropdownWrapper: CSS.Properties = {
  position: "relative"
};
