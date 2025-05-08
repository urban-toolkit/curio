import React, { useState } from "react";
import CSS from "csstype";
import { FileUpload, TrillProvenanceWindow, DatasetsWindow } from "components/menus";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useCode } from "../../../hook/useCode";
import { TrillGenerator } from "../../../TrillGenerator";
import styles from "./UpMenu.module.css";
import clsx from 'clsx';
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase } from "@fortawesome/free-solid-svg-icons";

export default function UpMenu({ setDashBoardMode, setDashboardOn, dashboardOn }: { setDashBoardMode: (mode: boolean) => void; setDashboardOn: (mode: boolean) => void; dashboardOn: boolean }) {
    const [isEditing, setIsEditing] = useState(false);
    const [fileMenuOpen, setFileMenuOpen] = useState(false);
    const [trillProvenanceOpen, setTrillProvenanceOpen] = useState(false);
    const [datasetsOpen, setDatasetsOpen] = useState(false);

    const { nodes, edges, workflowNameRef, setWorkflowName } = useFlowContext();
    const { loadTrill } = useCode();

    const closeTrillProvenanceModal = () => {
        setTrillProvenanceOpen(false);
    }

    const openTrillProvenanceModal = () => {
        setTrillProvenanceOpen(true);
    }

    const closeDatasetsModal = () => {
        setDatasetsOpen(false);
    }

    const openDatasetsModal = () => {
        setDatasetsOpen(true);
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
            <div className={clsx(styles.menuBar, "nowheel", "nodrag")}>
                <div className={styles.dropdownWrapper}>
                    <button
                        className={styles.button}
                        onClick={() => setFileMenuOpen((prev) => !prev)}
                    >
                        File
                    </button>
                    {fileMenuOpen && (
                        <div className={styles.dropDownMenu}>
                            <button className={styles.dropDownMenu} onClick={exportTrill}>Export Specification</button>
                            <div>
                                <button className={styles.dropDownMenu} onClick={loadTrillFile}>Load Specification</button>
                                <input type="file" accept=".json" id="loadTrill" style={{ display: 'none' }} onChange={handleFileUpload}/>
                            </div>
                        </div>
                    )}
                </div>
                <button   
                    className={clsx(
                        styles.button,
                        dashboardOn ? styles.dashboardOn : styles.dashboardOff
                    )}
                    onClick={() => {setDashBoardMode(!dashboardOn); setDashboardOn(!dashboardOn);}}>
                        Dashboard Mode
                </button>
                <button className={styles.button} onClick={openTrillProvenanceModal}>Provenance</button>
            </div>
            {/* Right-side top menu */}
            <div className={styles.rightSide}>
                <FileUpload />
                <button className={styles.button} onClick={openDatasetsModal}><FontAwesomeIcon icon={faDatabase} /></button>
            </div>
            {/* Editable Workflow Name */}
            <div className={styles.workflowNameContainer}>
                {isEditing ? (
                    <input
                        type="text"
                        value={workflowNameRef.current}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyPress={handleKeyPress}
                        autoFocus
                        className={styles.input}
                    />
                ) : (
                    <h1
                        className={styles.workflowNameStyle}
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
            {/* Datasets Modal */}
            <DatasetsWindow 
                open={datasetsOpen}
                closeModal={closeDatasetsModal}
            />
        </>

    );
}
